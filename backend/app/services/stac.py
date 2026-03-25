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


async def sign_pc_url(url: str) -> str:
    """Sign a Planetary Computer asset URL for authenticated access.

    SAS tokens are short-lived; always sign at response time, never cache.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(PC_SIGN_URL, params={"href": url})
        resp.raise_for_status()
        return str(resp.json()["href"])


# ── Item selection (deduplication per time period) ────────────────────────────


def _capture_date(item: dict[str, object]) -> date:
    dt_str = str(item["properties"]["datetime"])  # type: ignore[index]
    return date.fromisoformat(dt_str[:10])


def _doy(item: dict[str, object]) -> int:
    return _capture_date(item).timetuple().tm_yday


def select_naip_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """One NAIP item per year — closest to mid-summer (day 196 ≈ July 15).

    NAIP is cloud-free aerial photography; we just want the best seasonal look.
    """
    target_doy = 196
    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        by_year[_capture_date(item).year].append(item)

    selected = [
        min(year_items, key=lambda i: abs(_doy(i) - target_doy))
        for year_items in by_year.values()
    ]
    return sorted(selected, key=_capture_date)


def select_landsat_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """One Landsat item per year — lowest cloud cover within that year."""
    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        by_year[_capture_date(item).year].append(item)

    selected = [
        min(
            year_items,
            key=lambda i: float(
                i["properties"].get("eo:cloud_cover", 100)  # type: ignore[union-attr]
            ),
        )
        for year_items in by_year.values()
    ]
    return sorted(selected, key=_capture_date)


def select_sentinel_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """One Sentinel-2 item per calendar quarter — lowest cloud cover."""
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
    return sorted(selected, key=_capture_date)


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
