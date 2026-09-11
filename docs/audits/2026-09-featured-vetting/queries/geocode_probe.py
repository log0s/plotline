"""Resolve candidate points the way the pipeline would — without creating a parcel.

Read-only, throwaway. Run inside the api container:

    docker compose exec -T api python - "<address>" ["<address>" ...] \
        < docs/audits/2026-09-featured-vetting/queries/geocode_probe.py

For each address it prints two things:

1. The **seed path**: ``geocoder.geocode_address`` — the Census forward geocode
   that ``POST /api/v1/geocode`` always tries first and the only path
   ``scripts/seed_featured.py`` uses (it sends no coordinates, so a Census
   miss is a 422 there with no fallback).
2. The **Photon path**: ``GET /api/v1/geocode/autocomplete`` on the running
   local API — the suggestions a user would pick from, with ``place_type``
   (Photon ``osm_value``), which is what AA4's city-level-geocode shape turns on.
   POST /geocode uses these coordinates only when the Census call fails, and
   then through ``reverse_geocode``.

Also prints the tract at each census geography vintage the pipeline asks for
(``census._GEOGRAPHY_VINTAGES``) via ``geocoder.lookup_tract_at_vintage``, so the
2010-vs-2020 lineage can be predicted before any run.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import get_settings
from app.services import geocoder
from app.services.address_normalizer import city_from_address, extract_search_terms
from app.services.county_adapters import get_adapter_for_county

VINTAGES = ("Census2010_Current", "Census2020_Current", "ACS2021_Current", "ACS2023_Current")


async def probe(address: str) -> None:
    settings = get_settings()
    print(f"\n## {address}")
    try:
        r = await geocoder.geocode_address(address, settings)
    except geocoder.AddressNotFoundError as exc:
        print(f"seed path (Census forward): NO MATCH — {exc}")
        r = None
    except geocoder.GeocoderUnavailableError as exc:
        print(f"seed path (Census forward): UNAVAILABLE — {exc}")
        r = None
    if r is not None:
        city = city_from_address(r.normalized_address)
        adapter = get_adapter_for_county(r.county or "")
        print(
            f"seed path (Census forward): {r.latitude:.6f},{r.longitude:.6f} "
            f"matched={r.normalized_address!r} tract={r.census_tract_id} county={r.county!r}"
        )
        print(
            f"  property path: adapter={type(adapter).__name__ if adapter else None} "
            f"city_from_address={city!r} covers={adapter.covers(city) if adapter else 'n/a'} "
            f"search_terms={extract_search_terms(r.normalized_address)}"
        )
        for vintage in VINTAGES:
            try:
                tract = await geocoder.lookup_tract_at_vintage(r.latitude, r.longitude, vintage, settings)
            except geocoder.GeocoderError as exc:
                tract = f"ERROR {exc}"
            print(f"  tract @ {vintage}: {tract}")

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get("http://localhost:8000/api/v1/geocode/autocomplete", params={"q": address})
    print(f"Photon path (local autocomplete): HTTP {resp.status_code}")
    if resp.status_code == 200:
        for s in resp.json():
            print(f"  {s['lat']:.6f},{s['lon']:.6f} place_type={s['place_type']!r} {s['display_name']!r}")


async def main() -> None:
    for address in sys.argv[1:]:
        await probe(address)
        await asyncio.sleep(1.0)


asyncio.run(main())
