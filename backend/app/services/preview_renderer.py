"""Pre-render static preview JPEGs for FeaturedLocation cards.

Uses Titiler's ``/cog/bbox`` endpoint to crop a fixed ground footprint around
the parcel centroid from the latest NAIP snapshot, then writes the JPEG to a
mounted static directory served by FastAPI at ``/static``.
"""

from __future__ import annotations

import logging
import math
import os
import uuid

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.parcels import FeaturedLocation, Parcel
from app.services import imagery as imagery_service
from app.services import stac as stac_service

logger = logging.getLogger(__name__)


def _bbox_around(
    lat: float, lng: float, half_x_m: float, half_y_m: float | None = None,
) -> tuple[float, float, float, float]:
    """Return a lon/lat bbox ``(minx, miny, maxx, maxy)`` centred on ``(lat, lng)``.

    ``half_x_m`` controls the east-west extent; ``half_y_m`` controls
    north-south (defaults to ``half_x_m`` for a square footprint).
    """
    if half_y_m is None:
        half_y_m = half_x_m
    dlat = half_y_m / 111_320.0
    dlng = half_x_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)


async def render_preview(
    db: Session,
    loc: FeaturedLocation,
    settings: Settings,
    *,
    width: int = 672,
    height: int = 288,
    half_side_m: float = 300.0,
) -> str | None:
    """Render a JPEG preview for ``loc`` from its latest NAIP snapshot.

    Returns the relative URL path (e.g. ``/static/featured/<slug>.jpg``) on
    success, or ``None`` if no NAIP snapshot is available.
    """
    parcel = db.get(Parcel, loc.parcel_id)
    if parcel is None:
        logger.warning("No parcel for featured %s", loc.slug)
        return None

    snapshots = imagery_service.get_imagery_snapshots(
        db, parcel_id=uuid.UUID(str(loc.parcel_id)), source="naip"
    )
    if not snapshots:
        logger.warning("No NAIP snapshots for featured %s", loc.slug)
        return None

    latest = snapshots[-1]  # get_imagery_snapshots sorts ASC by capture_date
    try:
        signed_url = await stac_service.sign_pc_url(latest.cog_url)
    except Exception as exc:
        logger.warning("URL signing failed for %s, using unsigned", loc.slug, exc_info=exc)
        signed_url = latest.cog_url

    # Scale bbox to match image aspect ratio so Titiler doesn't stretch
    aspect = width / height
    half_y = half_side_m
    half_x = half_side_m * aspect
    minx, miny, maxx, maxy = _bbox_around(parcel.latitude, parcel.longitude, half_x, half_y)
    titiler_url = (
        f"{settings.titiler_url}/cog/bbox/"
        f"{minx},{miny},{maxx},{maxy}/{width}x{height}.jpg"
    )
    params: dict[str, object] = {
        "url": signed_url,
        "bidx": [1, 2, 3],
        "rescale": "0,255",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(titiler_url, params=params)
    if resp.status_code != 200:
        logger.error(
            "Titiler bbox render failed for %s: %s %s",
            loc.slug, resp.status_code, resp.text[:300],
        )
        return None

    out_dir = os.path.join(settings.static_dir, "featured")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{loc.slug}.jpg")
    with open(out_path, "wb") as f:
        f.write(resp.content)

    rel_url = f"/static/featured/{loc.slug}.jpg"
    logger.info(
        "Rendered preview for %s (%d bytes) from NAIP %s",
        loc.slug, len(resp.content), latest.capture_date.isoformat(),
    )
    return rel_url
