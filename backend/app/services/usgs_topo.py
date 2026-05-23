"""USGS Historical Topographic Maps — search via TNM API.

The National Map (TNM) API provides programmatic access to USGS Historical
Topographic Map Collection products. GeoTIFF files are hosted on public S3
(no authentication needed) and served through Titiler like other COG sources.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

import httpx

logger = logging.getLogger(__name__)

TNM_API_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"

# Lower = more detail. Used to prefer 7.5-minute quads over coarser sheets
# when multiple extents are available for the same decade.
_EXTENT_PRIORITY: dict[str, int] = {
    "3.75 x 3.75 minute": 0,
    "7.5 x 7.5 minute": 1,
    "7.5 x 15 minute": 2,
    "15 x 15 minute": 3,
    "30 x 30 minute": 4,
    "30 x 60 minute": 5,
    "1 x 1 degree": 6,
    "1 x 2 degree": 7,
    "1 x 3 degree": 8,
    "1 x 4 degree": 9,
    "2 x 1 degree": 10,
}

_tnm_client: httpx.AsyncClient | None = None


def _get_tnm_client() -> httpx.AsyncClient:
    """Return a shared httpx client for TNM API requests."""
    global _tnm_client
    if _tnm_client is None:
        _tnm_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _tnm_client


async def close_client() -> None:
    """Close the shared TNM API client and release connections."""
    global _tnm_client
    if _tnm_client is not None:
        await _tnm_client.aclose()
        _tnm_client = None


async def search_usgs_topo(
    bbox: tuple[float, float, float, float],
    max_items: int = 100,
) -> list[dict[str, object]]:
    """Search TNM API for historical topo maps intersecting the bounding box.

    Returns raw product dicts from the TNM API, filtered to those with
    available GeoTIFF downloads.
    """
    params: dict[str, str | int] = {
        "datasets": "Historical Topographic Maps",
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "max": max_items,
        "outputFormat": "JSON",
    }

    client = _get_tnm_client()
    resp = await client.get(TNM_API_URL, params=params)
    resp.raise_for_status()
    data = resp.json()

    items: list[dict[str, object]] = data.get("items", [])
    return [
        item
        for item in items
        if isinstance((urls := item.get("urls")), dict) and urls.get("GeoTIFF")
    ]


def select_topo_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pick one topo map per decade — best detail, earliest year.

    Within each decade, prefers 7.5-minute quads (most detail) over coarser
    sheets, and within the same extent picks the earliest publication year.
    """
    by_decade: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        year = _publication_year(item)
        if year is None:
            continue
        decade = (year // 10) * 10
        by_decade[decade].append(item)

    selected: list[dict[str, object]] = []
    for decade in sorted(by_decade.keys()):
        candidates = by_decade[decade]
        candidates.sort(
            key=lambda i: (
                _EXTENT_PRIORITY.get(str(i.get("extent", "")), 99),
                str(i.get("publicationDate", "9999")),
            )
        )
        selected.append(candidates[0])

    return selected


def extract_geotiff_url(item: dict[str, object]) -> str | None:
    """Extract the GeoTIFF download URL from a TNM product item."""
    urls = item.get("urls")
    if isinstance(urls, dict):
        val = urls.get("GeoTIFF")
        return str(val) if val else None
    return None


def extract_publication_date(item: dict[str, object]) -> date:
    """Return the publication year as a date (Jan 1 of that year)."""
    year = _publication_year(item) or 1900
    return date(year, 1, 1)


def extract_source_id(item: dict[str, object]) -> str:
    """Extract the USGS source ID from a TNM product item."""
    return str(item.get("sourceId", ""))


def extract_bbox_wkt(item: dict[str, object]) -> str | None:
    """Convert a TNM bounding box to a WKT POLYGON string."""
    bb = item.get("boundingBox")
    if not isinstance(bb, dict):
        return None
    try:
        w, s = float(bb["minX"]), float(bb["minY"])
        e, n = float(bb["maxX"]), float(bb["maxY"])
    except (KeyError, ValueError, TypeError):
        return None
    return f"SRID=4326;POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def _publication_year(item: dict[str, object]) -> int | None:
    pub_date = str(item.get("publicationDate", ""))
    if len(pub_date) < 4:
        return None
    try:
        return int(pub_date[:4])
    except ValueError:
        return None
