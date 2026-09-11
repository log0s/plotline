"""Which addresses does the Census forward geocoder (the seed path) match?

Read-only, throwaway. Same endpoint and benchmark/vintage as
``geocoder.geocode_address`` (Public_AR_Current / Current_Current). Run inside
the api container, one address per argument:

    docker compose exec -T api python - "<address>" ... \
        < docs/audits/2026-09-featured-vetting/queries/census_match_batch.py
"""

from __future__ import annotations

import sys
import time

import httpx

from app.config import get_settings

settings = get_settings()
for address in sys.argv[1:]:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Census Tracts,Counties",
        "format": "json",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key
    r = httpx.get(settings.census_geocoder_url, params=params, timeout=30)
    matches = (r.json().get("result") or {}).get("addressMatches") or [] if r.status_code == 200 else []
    if not matches:
        print(f"HTTP {r.status_code} NO MATCH   {address}")
    for m in matches[:1]:
        c = m["coordinates"]
        tract = (m.get("geographies", {}).get("Census Tracts") or [{}])[0].get("GEOID")
        print(f"HTTP {r.status_code} MATCH {c['y']:.6f},{c['x']:.6f} {m['matchedAddress']!r} tract={tract}   <- {address}")
    time.sleep(0.5)
