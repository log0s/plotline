"""USGS Historical Topographic Maps — search via TNM API.

The National Map (TNM) API provides programmatic access to USGS Historical
Topographic Map Collection products. GeoTIFF files are hosted on public S3
(no authentication needed) and served through Titiler like other COG sources.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import httpx

from app.services.imagery import encode_group_key

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

# Keyed by event loop — see the matching comment in stac.py: each Celery
# task runs in its own loop and httpx clients are loop-affine.
_tnm_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _get_tnm_client() -> httpx.AsyncClient:
    """Return a pooled httpx client for TNM API requests (per event loop)."""
    loop = asyncio.get_running_loop()
    client = _tnm_clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        _tnm_clients[loop] = client
    return client


async def close_client() -> None:
    """Close this event loop's TNM API client and release connections."""
    client = _tnm_clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()


@dataclass(frozen=True)
class TopoSearchResult:
    """A TNM search, plus whether its response was capped.

    ``truncated`` is the caller's only way to see the cap: the warning below
    is a log line, and the returned list is already filtered to
    GeoTIFF-carrying products, so its length says nothing about the raw
    response. The ledger needs it — a decade absent from a capped response is
    indeterminate, not absent.
    """

    items: list[dict[str, object]]
    truncated: bool


async def search_usgs_topo(
    bbox: tuple[float, float, float, float],
    max_items: int = 100,
) -> list[dict[str, object]]:
    """Search TNM API for historical topo maps intersecting the bounding box.

    Returns raw product dicts from the TNM API, filtered to those with
    available GeoTIFF downloads.
    """
    return (await search_usgs_topo_products(bbox, max_items)).items


async def search_usgs_topo_products(
    bbox: tuple[float, float, float, float],
    max_items: int = 100,
) -> TopoSearchResult:
    """``search_usgs_topo`` plus the truncation flag."""
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
    truncated = len(items) >= max_items
    # Same instrument the county clients carry (arcgis/ckan/socrata): a
    # response holding exactly its cap is indistinguishable from a complete
    # answer, and TNM's ordering is unspecified, so a truncated pool could
    # silently drop whole decades. Pagination is deliberately not built —
    # see the L6 accept and counties item 13 in the second audit's STATUS.md.
    if truncated:
        logger.warning(
            "TNM query hit its row cap — results are truncated",
            extra={
                "resource": "Historical Topographic Maps",
                "cap": max_items,
                "bbox": params["bbox"],
            },
        )

    return TopoSearchResult(
        items=[
            item
            for item in items
            if isinstance((urls := item.get("urls")), dict) and urls.get("GeoTIFF")
        ],
        truncated=truncated,
    )


def select_topo_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pick one topo map per decade — best detail, earliest year.

    Within each decade, prefers 7.5-minute quads (most detail) over coarser
    sheets, and within the same extent picks the earliest publication year.
    """
    # Keyed by the shared group_key encoding ("1960s"), not a bare int, so
    # the ledger row for a decade and the sheet chosen for it carry the same
    # token. Sorting is unaffected — the keys are four-digit-year prefixed.
    by_decade: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        year = _publication_year(item)
        if year is None:
            continue
        by_decade[encode_group_key("decade", year)].append(item)

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


def extract_publication_date(item: dict[str, object]) -> date | None:
    """Return the publication year as a date (Jan 1 of that year), or None.

    None means the product carries no parseable ``publicationDate``. The
    caller skips it rather than persisting a date we invented: this used to
    fall back to 1900, which renders on the timeline as a real 1900 map.
    """
    year = _publication_year(item)
    if year is None:
        return None
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
