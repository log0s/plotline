"""Is the change at a point Landsat-legible? LCMAP land-cover class shares, 1985 vs 2021.

Read-only, throwaway. LCMAP CONUS v1.3 (PC collection ``usgs-lcmap-conus-v13``)
is a Landsat-derived annual land-cover product, 1985-2021, so a class shift in
it is direct evidence the change is legible at Landsat's 30 m. It cannot see
redevelopment inside the Developed class (a campus rebuilt on an office park,
a rail yard decked over) and it ends before the Marshall Fire, so it is used
for the greenfield candidates only.

Run inside the api container (it reaches the local Titiler at http://titiler:80):

    docker compose exec -T api python - lat,lon,label [...] \
        < docs/audits/2026-09-featured-vetting/queries/lcmap_change.py

For each point and year: STAC search (intersects the point), sign the ``lcpri``
asset via PC's /api/sas/v1/sign, then ask local Titiler for categorical
statistics over a 500 m and a 1000 m buffer (UTM-projected squares).
"""

from __future__ import annotations

import sys
import time

import httpx
import pyproj
from shapely.geometry import Point, mapping
from shapely.ops import transform

from app.services.stac import get_utm_epsg

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
TITILER = "http://titiler:80/cog/statistics"
CLASSES = {1: "Developed", 2: "Cropland", 3: "Grass/Shrub", 4: "Tree", 5: "Water", 6: "Wetland", 7: "Ice/Snow", 8: "Barren"}
YEARS = (1985, 2001, 2021)


def square(lat: float, lon: float, half_m: float) -> dict:
    utm = pyproj.CRS(f"EPSG:{get_utm_epsg(lon, lat)}")
    fwd = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    inv = pyproj.Transformer.from_crs(utm, "EPSG:4326", always_xy=True).transform
    return mapping(transform(inv, transform(fwd, Point(lon, lat)).buffer(half_m, cap_style=3)))


def sign(client: httpx.Client, href: str) -> str:
    for attempt in range(4):
        r = client.get(SIGN, params={"href": href})
        if r.status_code == 200 and "href" in r.json():
            return r.json()["href"]
        print(f"    sign attempt {attempt + 1}: HTTP {r.status_code} {r.text[:120]!r}")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("PC sign endpoint refused four times")


def shares(client: httpx.Client, href: str, geom: dict) -> str:
    signed = sign(client, href)
    r = client.post(
        TITILER,
        params={"url": signed, "categorical": "true"},
        json={"type": "Feature", "properties": {}, "geometry": geom},
    )
    r.raise_for_status()
    hist = r.json()["properties"]["statistics"]["b1"]["histogram"]
    counts, values = hist
    total = sum(c for c, v in zip(counts, values) if int(v) in CLASSES)
    parts = [
        f"{CLASSES[int(v)]} {100 * c / total:.0f}%"
        for c, v in sorted(zip(counts, values), key=lambda cv: -cv[0])
        if int(v) in CLASSES and c
    ]
    return ", ".join(parts)


def main() -> None:
    with httpx.Client(timeout=60) as client:
        for arg in sys.argv[1:]:
            lat_s, lon_s, label = arg.split(",", 2)
            lat, lon = float(lat_s), float(lon_s)
            print(f"\n## {label} {lat:.6f},{lon:.6f}")
            for year in YEARS:
                body = {
                    "collections": ["usgs-lcmap-conus-v13"],
                    "intersects": {"type": "Point", "coordinates": [lon, lat]},
                    "datetime": f"{year}-01-01/{year}-12-31",
                    "limit": 5,
                }
                items = client.post(STAC, json=body).json().get("features", [])
                if not items:
                    print(f"  {year}: no LCMAP item")
                    continue
                href = items[0]["assets"]["lcpri"]["href"]
                for half in (500, 1000):
                    print(f"  {year} ±{half} m [{items[0]['id']}]: {shares(client, href, square(lat, lon, half))}")


main()
