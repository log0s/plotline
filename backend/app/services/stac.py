"""Microsoft Planetary Computer STAC API client.

Handles searching imagery collections, signing asset URLs, and computing
bounding boxes from geocoded points.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

import httpx
from shapely.geometry import Point
from shapely.ops import transform

logger = logging.getLogger(__name__)

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

# Resolution in metres per source
RESOLUTION_M: dict[str, float] = {
    "naip": 1.0,
    "landsat-c2-l2": 30.0,
    "sentinel-2-l2a": 10.0,
}


# ── Bounding box ───────────────────────────────────────────────────────────────


def get_utm_epsg(lng: float, lat: float) -> int:
    """Return the UTM zone EPSG code for a given WGS-84 coordinate."""
    zone = int((lng + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


def point_to_bbox(
    lat: float,
    lng: float,
    buffer_m: float = 500,
) -> tuple[float, float, float, float]:
    """Create a bounding box around a point.

    Args:
        lat: Latitude (WGS-84).
        lng: Longitude (WGS-84).
        buffer_m: Buffer radius in metres.

    Returns:
        (west, south, east, north) bounding box in WGS-84 degrees.
    """
    import pyproj

    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS(f"EPSG:{get_utm_epsg(lng, lat)}")

    to_utm = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
    to_wgs = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True).transform

    point_utm = transform(to_utm, Point(lng, lat))
    buffer_wgs = transform(to_wgs, point_utm.buffer(buffer_m))

    bounds = buffer_wgs.bounds  # (minx, miny, maxx, maxy)
    return (bounds[0], bounds[1], bounds[2], bounds[3])


# ── STAC search ───────────────────────────────────────────────────────────────


async def search_stac(
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_items: int = 50,
    query: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Search a STAC collection for items intersecting a bounding box.

    Args:
        collection: STAC collection ID (e.g. "naip").
        bbox: (west, south, east, north) in WGS-84.
        datetime_range: ISO 8601 interval string, e.g. "2003-01-01/2024-12-31".
        max_items: Maximum items to return (hard cap at 500).
        query: Additional property filters, e.g. {"eo:cloud_cover": {"lt": 20}}.

    Returns:
        List of GeoJSON Feature dicts (STAC items).
    """
    max_items = min(max_items, 500)

    payload: dict[str, object] = {
        "collections": [collection],
        "bbox": list(bbox),
        "datetime": datetime_range,
        "limit": min(max_items, 100),
    }
    if query:
        payload["query"] = query

    items: list[dict[str, object]] = []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{STAC_API}/search", json=payload)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("features", []))

        while len(items) < max_items:
            next_link = next(
                (lnk for lnk in data.get("links", []) if lnk["rel"] == "next"),
                None,
            )
            if not next_link:
                break
            resp = await client.get(next_link["href"])
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("features", []))

    return items[:max_items]


# ── URL signing ───────────────────────────────────────────────────────────────


_SAS_CACHE_TTL = 600  # 10 minutes (tokens last ~30 min)


_sign_client: httpx.AsyncClient | None = None


def _get_sign_client() -> httpx.AsyncClient:
    """Module-level pooled client so parallel signs share TLS connections."""
    global _sign_client
    if _sign_client is None:
        _sign_client = httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _sign_client


async def sign_pc_url(url: str) -> str:
    """Sign a Planetary Computer asset URL for authenticated access.

    Signed URLs are cached in Redis for 10 minutes to avoid redundant
    roundtrips to the SAS signing endpoint. Tokens last ~30 min so
    the 10-min TTL provides a safe margin.
    """
    from app.db import get_async_redis

    cache_key = f"sas:{url}"
    redis = get_async_redis()
    try:
        cached = await redis.get(cache_key)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    except Exception:
        pass  # Redis down — fall through to signing

    resp = await _get_sign_client().get(PC_SIGN_URL, params={"href": url})
    resp.raise_for_status()
    signed = str(resp.json()["href"])

    try:
        await redis.setex(cache_key, _SAS_CACHE_TTL, signed.encode())
    except Exception:
        pass  # Redis down — signed URL still works, just not cached

    return signed


# ── Spatial filtering ─────────────────────────────────────────────────────────


def filter_items_containing_point(
    items: list[dict[str, object]],
    lat: float,
    lng: float,
) -> list[dict[str, object]]:
    """Keep only STAC items whose bbox actually contains the given point.

    The STAC search uses a buffered bbox, so it can return items that
    intersect the search area but don't cover the parcel itself (e.g.
    adjacent NAIP tiles).  This filters them out.
    """
    result = []
    for item in items:
        bbox = item.get("bbox")
        if not bbox or len(bbox) < 4:  # type: ignore[arg-type]
            result.append(item)  # no bbox — keep it, can't verify
            continue
        w, s, e, n = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        if w <= lng <= e and s <= lat <= n:
            result.append(item)
    return result


def _bbox_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Area of the intersection of two (w, s, e, n) bboxes in degree² units."""
    w = max(a[0], b[0])
    s = max(a[1], b[1])
    e = min(a[2], b[2])
    n = min(a[3], b[3])
    if e <= w or n <= s:
        return 0.0
    return (e - w) * (n - s)


def filter_items_intersecting_bbox(
    items: list[dict[str, object]],
    viewport: tuple[float, float, float, float],
) -> list[dict[str, object]]:
    """Keep STAC items whose bbox intersects the given viewport.

    Looser than ``filter_items_containing_point`` — useful for NAIP where
    small tiles may cover only part of the display viewport but are still
    worth ingesting as mosaic components.
    """
    result = []
    for item in items:
        bbox = item.get("bbox")
        if not bbox or len(bbox) < 4:  # type: ignore[arg-type]
            result.append(item)
            continue
        item_bbox = (
            float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]),
        )
        if _bbox_intersection_area(item_bbox, viewport) > 0:
            result.append(item)
    return result


# ── Item selection (deduplication per time period) ────────────────────────────


def _capture_date(item: dict[str, object]) -> date:
    dt_str = str(item["properties"]["datetime"])  # type: ignore[index]
    return date.fromisoformat(dt_str[:10])


def _doy(item: dict[str, object]) -> int:
    return _capture_date(item).timetuple().tm_yday


def select_naip_items(
    items: list[dict[str, object]],
    viewport: tuple[float, float, float, float] | None = None,
    *,
    max_tiles_per_year: int = 3,
    coverage_target: float = 0.95,
) -> list[list[dict[str, object]]]:
    """Select NAIP tiles per year, grouped as mosaics.

    Returns a list of groups, one per year. Each group contains 1 to
    ``max_tiles_per_year`` tiles selected greedily to maximise coverage of
    the supplied ``viewport`` bbox. If ``viewport`` is None, falls back to
    a single tile per year closest to mid-summer (legacy behaviour).

    Within a year, the first tile is the one with the largest viewport
    overlap (tie-broken by proximity to mid-summer, day 196 ≈ July 15).
    Subsequent tiles are added only if they cover a portion of the
    viewport not yet covered by already-selected tiles, and up to
    ``coverage_target`` fraction of the viewport is covered.
    """
    target_doy = 196
    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        by_year[_capture_date(item).year].append(item)

    groups: list[list[dict[str, object]]] = []

    for year in sorted(by_year.keys()):
        year_items = by_year[year]

        if viewport is None:
            # Legacy single-tile behaviour
            pick = min(year_items, key=lambda i: abs(_doy(i) - target_doy))
            groups.append([pick])
            continue

        viewport_area = (viewport[2] - viewport[0]) * (viewport[3] - viewport[1])
        if viewport_area <= 0:
            pick = min(year_items, key=lambda i: abs(_doy(i) - target_doy))
            groups.append([pick])
            continue

        # Greedy: pick tile with best remaining-viewport coverage, breaking
        # ties by proximity to mid-summer.
        remaining = viewport
        selected_for_year: list[dict[str, object]] = []
        candidates = list(year_items)

        while candidates and len(selected_for_year) < max_tiles_per_year:
            def score(item: dict[str, object]) -> tuple[float, float]:
                bbox = item.get("bbox")
                if not bbox or len(bbox) < 4:  # type: ignore[arg-type]
                    return (0.0, float(abs(_doy(item) - target_doy)))
                ib = (
                    float(bbox[0]), float(bbox[1]),  # type: ignore[index]
                    float(bbox[2]), float(bbox[3]),  # type: ignore[index]
                )
                area = _bbox_intersection_area(ib, remaining)
                # Maximize area, minimize doy distance
                return (-area, float(abs(_doy(item) - target_doy)))

            best = min(candidates, key=score)
            best_bbox = best.get("bbox")
            if not best_bbox or len(best_bbox) < 4:  # type: ignore[arg-type]
                # No bbox to reason about; just take it and stop
                selected_for_year.append(best)
                break
            best_ibox = (
                float(best_bbox[0]), float(best_bbox[1]),  # type: ignore[index]
                float(best_bbox[2]), float(best_bbox[3]),  # type: ignore[index]
            )
            gain = _bbox_intersection_area(best_ibox, remaining)
            if gain <= 0 and selected_for_year:
                break
            selected_for_year.append(best)
            candidates.remove(best)

            # Check if we've covered enough of the viewport. We approximate
            # "remaining uncovered" by shrinking the tracked rectangle to
            # the portion of the viewport not covered by the selected
            # tile's bbox. This is an approximation (a union of tiles is
            # not a rectangle), but good enough for a few-tile mosaic.
            covered_so_far = sum(
                _bbox_intersection_area(
                    (
                        float(s["bbox"][0]),  # type: ignore[index]
                        float(s["bbox"][1]),  # type: ignore[index]
                        float(s["bbox"][2]),  # type: ignore[index]
                        float(s["bbox"][3]),  # type: ignore[index]
                    ),
                    viewport,
                )
                for s in selected_for_year
                if s.get("bbox") and len(s["bbox"]) >= 4  # type: ignore[arg-type,index]
            )
            if covered_so_far / viewport_area >= coverage_target:
                break

            # Update `remaining` to the sub-rectangle not covered by the
            # selected tile along the axis where the tile overlap is largest.
            tile_w, tile_s, tile_e, tile_n = best_ibox
            rw, rs, re_, rn = remaining
            # Choose the residual rectangle with the largest area: the
            # strip of remaining viewport that lies outside the tile
            # horizontally or vertically, whichever is bigger.
            residuals = []
            if tile_e < re_:
                residuals.append((max(tile_e, rw), rs, re_, rn))
            if tile_w > rw:
                residuals.append((rw, rs, min(tile_w, re_), rn))
            if tile_n < rn:
                residuals.append((rw, max(tile_n, rs), re_, rn))
            if tile_s > rs:
                residuals.append((rw, rs, re_, min(tile_s, rn)))
            if not residuals:
                break
            remaining = max(
                residuals,
                key=lambda r: max(0.0, (r[2] - r[0])) * max(0.0, (r[3] - r[1])),
            )

        groups.append(selected_for_year)

    return groups


def select_landsat_items(items: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """One Landsat item per year — lowest cloud cover within that year.

    Prefers Landsat 5/8/9 (TM, OLI-TIRS). Landsat 7 ETM+ (LE07) scenes
    are used only as a fallback because SLC-off failure since 2003
    produces diagonal stripes of missing data.

    Returns single-item groups (outer list per year, inner list always
    length 1) for shape consistency with NAIP multi-tile groups.
    """
    def is_le07(item: dict[str, object]) -> bool:
        return str(item.get("id", "")).startswith("LE07")

    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        by_year[_capture_date(item).year].append(item)

    selected: list[dict[str, object]] = []
    for year_items in by_year.values():
        non_le07 = [i for i in year_items if not is_le07(i)]
        pool = non_le07 if non_le07 else year_items
        pick = min(
            pool,
            key=lambda i: float(
                i["properties"].get("eo:cloud_cover", 100)  # type: ignore[union-attr]
            ),
        )
        selected.append(pick)
    selected.sort(key=_capture_date)
    return [[i] for i in selected]


def select_sentinel_items(items: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """One Sentinel-2 item per calendar quarter — lowest cloud cover.

    Returns single-item groups for shape consistency with NAIP multi-tile
    groups.
    """
    by_quarter: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        d = _capture_date(item)
        quarter = (d.year, (d.month - 1) // 3 + 1)
        by_quarter[quarter].append(item)

    selected = [
        min(
            q_items,
            key=lambda i: float(
                i["properties"].get("eo:cloud_cover", 100)  # type: ignore[union-attr]
            ),
        )
        for q_items in by_quarter.values()
    ]
    selected.sort(key=_capture_date)
    return [[i] for i in selected]


# ── Asset extraction ──────────────────────────────────────────────────────────


def _is_cog_asset(asset: dict[str, object]) -> bool:
    """Return True if the asset's STAC type indicates a GeoTIFF (COG).

    Planetary Computer uses ``image/tiff; application=geotiff; profile=cloud-optimized``
    for COGs.  Assets without a ``type`` field are assumed safe (some older STAC
    items omit it).
    """
    media_type = asset.get("type", "")
    if not media_type:
        return True  # no type declared — assume COG (backwards-compat)
    return "geotiff" in str(media_type).lower()


def extract_cog_url(item: dict[str, object], collection: str) -> str | None:
    """Extract the primary imagery URL for a STAC item.

    For **NAIP** and **Sentinel-2** this returns a direct COG href (the tile
    proxy uses Titiler's ``/cog/tiles/`` endpoint).

    For **Landsat** this returns the STAC item *self-link* URL.  Individual
    Landsat bands live in separate single-band COGs, so the tile proxy uses
    Titiler's ``/stac/tiles/`` endpoint with ``assets=red,green,blue`` for
    proper RGB compositing — which needs the full item URL, not a band URL.

    Returns None if no suitable asset / link is found.
    """
    assets: dict[str, dict[str, object]] = item.get("assets", {})  # type: ignore[assignment]

    if collection == "naip":
        if "image" in assets and assets["image"].get("href") and _is_cog_asset(assets["image"]):
            return str(assets["image"]["href"])
        return None

    if collection == "landsat-c2-l2":
        # Store the STAC item self-link — the tile proxy uses Titiler's
        # /stac/tiles/ endpoint with per-asset signing at request time to
        # compose a true-colour RGB from the red, green, and blue band COGs.
        links: list[dict[str, str]] = item.get("links", [])  # type: ignore[assignment]
        self_href = next((lnk["href"] for lnk in links if lnk.get("rel") == "self"), None)
        if self_href:
            return str(self_href)
        # Fallback: construct canonical URL from collection + item ID
        item_id = item.get("id")
        if item_id:
            return f"{STAC_API}/collections/{collection}/items/{item_id}"
        return None

    if collection == "sentinel-2-l2a":
        # visual is a uint8 3-band (R/G/B) TCI COG — ideal for display.
        # B04 (single-band uint16, 0-10000) is NOT used: its data range is
        # incompatible with the rescale params configured for TCI tiles.
        if "visual" in assets and assets["visual"].get("href") and _is_cog_asset(assets["visual"]):
            return str(assets["visual"]["href"])
        return None

    return None


def extract_thumbnail_url(item: dict[str, object]) -> str | None:
    """Extract a ready-to-display thumbnail URL from a STAC item.

    Checks standard STAC thumbnail/preview asset keys.
    Returns None if none are available (caller should generate via Titiler).
    """
    assets: dict[str, dict[str, object]] = item.get("assets", {})  # type: ignore[assignment]
    for key in ("rendered_preview", "thumbnail", "overview"):
        if key in assets and assets[key].get("href"):
            return str(assets[key]["href"])
    return None


def extract_capture_date(item: dict[str, object]) -> date:
    """Extract the capture date from a STAC item's datetime property."""
    return _capture_date(item)


def extract_bbox_wkt(item: dict[str, object]) -> str | None:
    """Extract the item bounding box as a WKT POLYGON string, or None."""
    bbox = item.get("bbox")
    if not bbox or len(bbox) < 4:  # type: ignore[arg-type]
        return None
    w, s, e, n = bbox[0], bbox[1], bbox[2], bbox[3]
    return f"SRID=4326;POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
