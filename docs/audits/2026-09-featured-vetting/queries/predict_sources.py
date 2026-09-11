"""Per-point source expectations, read from upstream before any pipeline run.

Read-only, throwaway. Everything here is a GET against a public API; nothing
touches the database. Run inside the api container:

    docker compose exec -T api python - lat,lon,label [...] \
        < docs/audits/2026-09-featured-vetting/queries/predict_sources.py

For each point it prints:

* **NAIP** — the pipeline's own search (1500 m bbox, ``2010-01-01/<yr>-12-31``,
  ``max_items=50``), then per year whether any returned tile's *geometry*
  contains the point. A year with no containing tile is the year
  ``filter_groups_containing_point`` suppresses, so the containing-year set is
  the predicted card set. Also prints the state(s) and the raw pool size, so a
  50-item cap hit is visible.
* **topo** — the pipeline's TNM query (same 1500 m bbox, ``max=100``), reduced
  the way ``select_topo_items`` reduces it: one sheet per decade among products
  carrying a GeoTIFF url, a parseable publicationDate and a sourceId.
* **census** — the tract the geocoder resolves at each vintage the pipeline
  asks for, then a live fetch of every (dataset, year) through the app's own
  ``CensusFetcher``, so the expected set is what the API will actually serve.

Landsat and Sentinel-2 are not probed per year here: 43 + 12 searches per point
would be 660 PC searches before the run. Their expectations come from the
config floors (``IMAGERY_SOURCE_START_YEAR``) and the incumbents' current
counts — see PREDICTION.md.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import date

from shapely.geometry import Point, shape

from app.config import get_settings
from app.services import geocoder, stac, usgs_topo
from app.services.census import (
    ACS5_YEARS,
    DECENNIAL_YEARS,
    CensusApiError,
    CensusFetcher,
    geography_vintage,
    parse_tract_fips,
)

THIS_YEAR = date.today().year


async def naip(lat: float, lon: float) -> None:
    bbox = stac.point_to_bbox(lat, lon, buffer_m=1500)
    items = await stac.search_stac(
        collection="naip",
        bbox=bbox,
        datetime_range=f"2010-01-01/{THIS_YEAR}-12-31",
        max_items=50,
    )
    pt = Point(lon, lat)
    by_year: dict[int, list[tuple[str, bool, str]]] = defaultdict(list)
    for item in items:
        props = item.get("properties", {})
        year = int(str(props.get("naip:year") or props.get("datetime", ""))[:4])
        contains = shape(item["geometry"]).contains(pt)
        by_year[year].append((item["id"], contains, str(props.get("naip:state"))))
    covered = sorted(y for y, tiles in by_year.items() if any(c for _, c, _ in tiles))
    uncovered = sorted(y for y, tiles in by_year.items() if not any(c for _, c, _ in tiles))
    states = sorted({s for tiles in by_year.values() for _, _, s in tiles})
    print(f"  NAIP raw pool {len(items)} of cap 50{' — CAP HIT' if len(items) >= 50 else ''}; states {states}")
    print(f"  NAIP years with a containing tile: {covered}")
    print(f"  NAIP years present in the pool but with NO containing tile: {uncovered}")
    for year in sorted(by_year):
        ids = ", ".join(f"{i}{'*' if c else ''}" for i, c, _ in by_year[year])
        print(f"    {year}: {ids}")


async def topo(lat: float, lon: float) -> None:
    bbox = stac.point_to_bbox(lat, lon, buffer_m=1500)
    search = await usgs_topo.search_usgs_topo_products(bbox)
    selected = usgs_topo.select_topo_items(search.items)
    servable = [
        i
        for i in selected
        if usgs_topo.extract_geotiff_url(i)
        and usgs_topo.extract_publication_date(i) is not None
        and usgs_topo.extract_source_id(i)
    ]
    decades = sorted({usgs_topo.extract_publication_date(i).year // 10 * 10 for i in servable})
    print(
        f"  topo: {len(search.items)} GeoTIFF products (truncated={search.truncated}), "
        f"{len(selected)} decade picks, {len(servable)} servable"
    )
    print(f"  topo decades predicted: {[f'{d}s' for d in decades]}")


async def census(lat: float, lon: float, stored_tract: str | None) -> None:
    settings = get_settings()
    cache: dict[str, str | None] = {}

    async def tract_for(dataset: str, year: int) -> str | None:
        vintage = geography_vintage(dataset, year)
        if vintage is None:
            return stored_tract
        if vintage not in cache:
            try:
                cache[vintage] = await geocoder.lookup_tract_at_vintage(lat, lon, vintage, settings)
            except geocoder.GeocoderError as exc:
                cache[vintage] = f"ERROR {exc}"
        return cache[vintage] or stored_tract

    fetcher = CensusFetcher(api_key=settings.census_api_key, timeout=30.0)
    try:
        for dataset, years in (("decennial", DECENNIAL_YEARS), ("acs5", ACS5_YEARS)):
            for year in years:
                tract = await tract_for(dataset, year)
                if not tract or tract.startswith("ERROR"):
                    print(f"  census {dataset} {year}: tract unresolved ({tract})")
                    continue
                s, c, t = parse_tract_fips(tract)
                try:
                    data = (
                        await fetcher.fetch_decennial(year, s, c, t)
                        if dataset == "decennial"
                        else await fetcher.fetch_acs5(year, s, c, t)
                    )
                except CensusApiError as exc:
                    print(f"  census {dataset} {year} tract {tract}: ERROR {exc}")
                    continue
                verdict = "DATA" if data else "empty (204/no data)"
                print(f"  census {dataset} {year} tract {tract}: {verdict}")
                await asyncio.sleep(0.4)
    finally:
        await fetcher.close()
    print(f"  census vintage tracts: {cache}")


async def main() -> None:
    settings = get_settings()
    for arg in sys.argv[1:]:
        lat_s, lon_s, label = arg.split(",", 2)
        lat, lon = float(lat_s), float(lon_s)
        print(f"\n## {label} {lat:.6f},{lon:.6f}")
        try:
            stored = await geocoder.reverse_geocode(lat, lon, label, settings)
            print(f"  reverse geocode: tract={stored.census_tract_id} county={stored.county!r}")
            stored_tract = stored.census_tract_id
        except geocoder.GeocoderError as exc:
            print(f"  reverse geocode FAILED: {exc}")
            stored_tract = None
        await naip(lat, lon)
        await topo(lat, lon)
        await census(lat, lon, stored_tract)
    await stac.close_clients()
    await usgs_topo.close_client()


asyncio.run(main())
