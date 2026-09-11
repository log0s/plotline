"""Marshall Fire point selection — read-only, throwaway, not wired into anything.

Run inside the api container (it has shapely/pyproj/httpx):

    docker compose exec -T api python - [lat,lon[,label] ...] \
        < docs/audits/2026-09-featured-vetting/queries/marshall_points.py

With no arguments: ranks Sagamore (Superior) and Harper Lake (Louisville)
addresses from Boulder County's residential damage layer. With points: tests
each point against the WFIGS Marshall perimeter and counts structures by damage
status within 250 / 500 / 1000 m and inside the default z15 viewport half-extent.

Sources (all public, read-only GETs):
  - Boulder County RDA_Public_View layer 0 (fields addr, damage, jurisdiction)
  - NIFC WFIGS_Interagency_Perimeters layer 0, IRWIN {C63FC371-BC70-4615-841B-B0838C21064F}
"""

from __future__ import annotations

import collections
import math
import re
import sys

import httpx
import pyproj
from shapely.geometry import Point, shape
from shapely.ops import transform

RDA = (
    "https://services3.arcgis.com/0jWpHMuhmHsukKE3/arcgis/rest/services/"
    "RDA_Public_View/FeatureServer/0/query"
)
WFIGS = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Interagency_Perimeters/FeatureServer/0/query"
)
MARSHALL_IRWIN = "{C63FC371-BC70-4615-841B-B0838C21064F}"

# Street sets that define each neighbourhood, from the layer itself (see VETTING.md §3).
SAGAMORE = {"MOHAWK CIRCLE", "BLACKFOOT STREET", "CHEROKEE AVENUE", "FOX LANE", "SHAWNEE LANE", "CAYAUGA WAY"}
HARPER = {
    "ARAPAHOE CIRCLE", "ELDORADO LANE", "WEST ENCLAVE CIRCLE", "SUNFLOWER STREET",
    "LARKSPUR LANE", "LARKSPUR COURT", "HILLSIDE LANE", "HILLSIDE COURT", "WILLOW PLACE",
    "HONEYSUCKLE LANE", "ARAPAHOE COURT",
}

UTM13 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32613", always_xy=True).transform

# z15 at ~40 N: 156543.03 * cos(lat) / 2**15 m/px. A 1280x800 map pane is the
# assumed default viewport; half-extents are reported, not asserted.
def z_half_extents(lat: float, zoom: int, w_px: int = 1280, h_px: int = 800) -> tuple[float, float]:
    mpp = 156543.03392 * math.cos(math.radians(lat)) / 2**zoom
    return (w_px * mpp / 2, h_px * mpp / 2)


def fetch_rda() -> list[dict]:
    r = httpx.get(
        RDA,
        params={
            "where": "1=1",
            "outFields": "addr,damage,jurisdiction",
            "returnGeometry": "true",
            "outSR": "4326",
            "resultRecordCount": 2000,
            "f": "json",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("exceededTransferLimit"):
        # Two pages is enough for this layer (1,720 rows at time of writing).
        r2 = httpx.get(RDA, params={**r.request.url.params, "resultOffset": 2000}, timeout=60)
        d["features"] += r2.json()["features"]
    return d["features"]


def fetch_perimeter():
    r = httpx.get(
        WFIGS,
        params={
            "where": f"poly_IRWINID='{MARSHALL_IRWIN}'",
            "outFields": "poly_IncidentName,poly_GISAcres,poly_FeatureCategory,attr_UniqueFireIdentifier",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=60,
    )
    r.raise_for_status()
    feats = r.json()["features"]
    return [(f["properties"], shape(f["geometry"])) for f in feats]


def street_of(addr: str) -> str:
    return re.sub(r"^\d+\s+", "", (addr or "").strip().upper())


def main() -> None:
    feats = fetch_rda()
    perims = fetch_perimeter()
    print(f"# RDA rows: {len(feats)}; WFIGS Marshall perimeter features: {len(perims)}")
    for props, geom in perims:
        print(f"#   {props}")
    perim = perims[0][1] if perims else None
    pts = [
        (
            f["attributes"]["addr"],
            f["attributes"]["damage"],
            f["attributes"]["jurisdiction"],
            f["geometry"]["y"],
            f["geometry"]["x"],
        )
        for f in feats
        if f.get("geometry")
    ]

    if len(sys.argv) <= 1:
        for label, streets in (("SAGAMORE (Superior)", SAGAMORE), ("HARPER LAKE (Louisville)", HARPER)):
            members = [p for p in pts if street_of(p[0]) in streets]
            status = collections.Counter(p[1] for p in members)
            lat_c = sum(p[3] for p in members) / len(members)
            lon_c = sum(p[4] for p in members) / len(members)
            print(f"\n## {label}: {len(members)} structures, status {dict(status)}")
            print(f"centroid {lat_c:.6f},{lon_c:.6f}")
            cx, cy = UTM13(lon_c, lat_c)
            ranked = sorted(members, key=lambda p: math.dist(UTM13(p[4], p[3]), (cx, cy)))
            for p in ranked[:8]:
                d = math.dist(UTM13(p[4], p[3]), (cx, cy))
                print(f"  {p[0]!r:40s} {p[1]:10s} {p[3]:.6f},{p[4]:.6f}  {d:6.1f} m from centroid")
        return

    for arg in sys.argv[1:]:
        parts = arg.split(",")
        lat, lon = float(parts[0]), float(parts[1])
        label = parts[2] if len(parts) > 2 else arg
        x0, y0 = UTM13(lon, lat)
        inside = perim.contains(Point(lon, lat)) if perim is not None else None
        edge_m = None
        if perim is not None:
            perim_utm = transform(UTM13, perim)
            edge_m = perim_utm.exterior.distance(Point(x0, y0)) if perim_utm.geom_type == "Polygon" else perim_utm.boundary.distance(Point(x0, y0))
        hx, hy = z_half_extents(lat, 15)
        print(f"\n## {label} {lat:.6f},{lon:.6f}")
        print(f"inside WFIGS Marshall perimeter: {inside}; distance to perimeter boundary: {edge_m:.0f} m")
        for radius in (250, 500, 1000):
            c = collections.Counter(
                p[1] for p in pts if math.dist(UTM13(p[4], p[3]), (x0, y0)) <= radius
            )
            print(f"  within {radius:4d} m: {dict(c)}")
        c = collections.Counter(
            p[1]
            for p in pts
            if abs(UTM13(p[4], p[3])[0] - x0) <= hx and abs(UTM13(p[4], p[3])[1] - y0) <= hy
        )
        print(f"  inside z15 viewport (+/-{hx:.0f} m E-W, +/-{hy:.0f} m N-S, 1280x800 px assumed): {dict(c)}")
        nearest = sorted(pts, key=lambda p: math.dist(UTM13(p[4], p[3]), (x0, y0)))[:5]
        for p in nearest:
            print(f"  nearest: {p[0]!r:40s} {p[1]:10s} {math.dist(UTM13(p[4], p[3]), (x0, y0)):6.1f} m")


if __name__ == "__main__":
    main()
