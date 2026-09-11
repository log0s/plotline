"""Geometry audit, ported to the post-0019 schema (scenes + parcel_scenes).

The 2026-08 geometry audit's method (FINDINGS.md §1): refetch the STAC item,
parse ``item["geometry"]`` with shapely, test point-in-footprint against the
``item["bbox"]`` test the pipeline used to run, and measure the distance from
the point to the footprint edge in the point's own UTM zone. That audit read
``imagery_snapshots``, which migration 0019 dropped; this reads
``parcel_scenes`` joined to ``scenes``, including every mosaic tile in
``mosaic_scene_ids``, not just the primary.

Read-only, throwaway. Run inside the api container:

    # every parcel that has a featured slug or a label passed as an id
    docker compose exec -T api python - db [<parcel_id> ...] \
        < docs/audits/2026-09-featured-vetting/queries/edge_distance.py

    # or one item against one point
    docker compose exec -T api python - item <collection> <item_id> <lat> <lon> \
        < .../edge_distance.py

Output per row: source, group_key, item id, bbox test, geometry test, distance
to the footprint edge (metres, negative = outside), and whether the stored
``scenes.footprint`` agrees with the refetched geometry.
"""

from __future__ import annotations

import asyncio
import sys

import httpx
import pyproj
from shapely.geometry import Point, box, shape
from shapely.ops import transform
from shapely.wkt import loads as wkt_loads
from sqlalchemy import text

from app.db import SessionLocal
from app.services.stac import get_utm_epsg

PC_ITEM = "https://planetarycomputer.microsoft.com/api/stac/v1/collections/{collection}/items/{item_id}"

ROWS_SQL = """
SELECT f.slug, p.id AS parcel_id, p.address, p.latitude, p.longitude,
       ps.source, ps.group_key, s.collection, s.item_id, s.provenance,
       ST_AsText(s.footprint) AS footprint_wkt, FALSE AS is_mosaic_tile
  FROM parcel_scenes ps
  JOIN scenes s ON s.id = ps.scene_id
  JOIN parcels p ON p.id = ps.parcel_id
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
 WHERE p.id = ANY(:ids)
UNION ALL
SELECT f.slug, p.id, p.address, p.latitude, p.longitude,
       ps.source, ps.group_key, s.collection, s.item_id, s.provenance,
       ST_AsText(s.footprint), TRUE
  FROM parcel_scenes ps
  JOIN parcels p ON p.id = ps.parcel_id
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
  CROSS JOIN LATERAL unnest(ps.mosaic_scene_ids) AS m(scene_id)
  JOIN scenes s ON s.id = m.scene_id
 WHERE p.id = ANY(:ids)
 ORDER BY 1, 6, 7, 12
"""


async def fetch_item(client: httpx.AsyncClient, collection: str, item_id: str) -> dict | None:
    for attempt in range(4):
        r = await client.get(PC_ITEM.format(collection=collection, item_id=item_id))
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        print(f"    item fetch {collection}/{item_id}: HTTP {r.status_code}")
        return None
    print(f"    item fetch {collection}/{item_id}: retries exhausted")
    return None


def measure(item: dict, lat: float, lon: float) -> tuple[bool, bool, float]:
    pt = Point(lon, lat)
    geom = shape(item["geometry"])
    bb = item.get("bbox")
    in_bbox = box(bb[0], bb[1], bb[2], bb[3]).contains(pt) if bb else False
    in_geom = geom.contains(pt)
    utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{get_utm_epsg(lon, lat)}", always_xy=True).transform
    d = transform(utm, geom).boundary.distance(transform(utm, pt))
    return in_bbox, in_geom, d if in_geom else -d


async def db_mode(ids: list[str]) -> None:
    with SessionLocal() as db:
        rows = db.execute(text(ROWS_SQL), {"ids": ids}).mappings().all()
    print(f"# {len(rows)} served scene references across {len(ids)} parcel(s)")
    async with httpx.AsyncClient(timeout=60) as client:
        cache: dict[tuple[str, str], dict | None] = {}
        worst: dict[tuple[str, str], tuple[float, str]] = {}
        for r in rows:
            if r["collection"] == "usgs-historical-topo":
                continue  # TNM products, no STAC item — excluded, as in the 2026-08 audit
            key = (r["collection"], r["item_id"])
            if key not in cache:
                cache[key] = await fetch_item(client, *key)
            item = cache[key]
            label = r["slug"] or str(r["parcel_id"])[:8]
            if item is None:
                print(f"{label:22s} {r['source']:10s} {r['group_key']:6s} {r['item_id']:56s} UNFETCHABLE")
                continue
            in_bbox, in_geom, d = measure(item, r["latitude"], r["longitude"])
            # Does the footprint stored at selection time agree with the one PC
            # serves now? NULL means the row predates footprint storage.
            if not r["footprint_wkt"]:
                stored = " stored-footprint NULL"
            else:
                stored_geom = wkt_loads(r["footprint_wkt"])
                agrees = stored_geom.contains(Point(r["longitude"], r["latitude"])) == in_geom
                stored = "" if agrees else " STORED-FOOTPRINT DISAGREES"
            flag = ""
            if in_bbox and not in_geom:
                flag = "  <<< bbox=Y geom=N"
            elif in_geom and d < 1000:
                flag = "  <<< within 1 km of edge"
            tile = " (mosaic tile)" if r["is_mosaic_tile"] else ""
            print(
                f"{label:22s} {r['source']:10s} {r['group_key']:6s} {r['item_id']:56s} "
                f"bbox={'Y' if in_bbox else 'N'} geom={'Y' if in_geom else 'N'} "
                f"edge={d:9.1f} m {r['provenance']:10s}{stored}{tile}{flag}"
            )
            k = (label, r["source"])
            if k not in worst or d < worst[k][0]:
                worst[k] = (d, f"{r['group_key']} {r['item_id']}")
        print("\n# minimum edge distance per parcel and source")
        for (label, source), (d, what) in sorted(worst.items()):
            print(f"{label:22s} {source:10s} min edge {d:9.1f} m   [{what}]")


async def item_mode(collection: str, item_id: str, lat: float, lon: float) -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        item = await fetch_item(client, collection, item_id)
    if item is None:
        return
    in_bbox, in_geom, d = measure(item, lat, lon)
    print(f"{collection}/{item_id} at {lat},{lon}: bbox={in_bbox} geom={in_geom} edge={d:.1f} m")
    print(f"  item bbox: {item.get('bbox')}")


if sys.argv[1] == "db":
    asyncio.run(db_mode(sys.argv[2:]))
else:
    asyncio.run(item_mode(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])))
