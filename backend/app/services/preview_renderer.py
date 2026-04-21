"""Pre-render static preview JPEGs for FeaturedLocation cards.

Uses Titiler's ``/cog/bbox`` endpoint to crop a fixed ground footprint around
the parcel centroid from the latest NAIP snapshot. When the primary NAIP scene
doesn't fully cover the preview bbox (common at scene edges — e.g. Hudson
Yards on Manhattan's west side), the snapshot's ``additional_cog_urls`` mosaic
components are fetched as PNG-with-alpha and alpha-composited to fill the gaps
before the final JPEG is written.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from io import BytesIO

import httpx
from PIL import Image
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

    # Scale bbox to match image aspect ratio so Titiler doesn't stretch
    aspect = width / height
    half_y = half_side_m
    half_x = half_side_m * aspect
    minx, miny, maxx, maxy = _bbox_around(parcel.latitude, parcel.longitude, half_x, half_y)

    # At scene edges a single NAIP COG may only cover part of the preview bbox,
    # yielding a half-empty JPEG. Prefer the newest snapshot whose STAC footprint
    # fully contains the requested extent; fall back to the latest if none do
    # (and rely on the mosaic composite below to fill the gaps).
    def _contains(snap_bbox: tuple[float, float, float, float]) -> bool:
        sw, ss, se, sn = snap_bbox
        return sw <= minx and ss <= miny and se >= maxx and sn >= maxy

    latest = next(
        (s for s in reversed(snapshots) if s.bbox and _contains(s.bbox)),
        snapshots[-1],
    )

    cog_urls = [latest.cog_url, *(latest.additional_cog_urls or [])]
    titiler_png_url = (
        f"{settings.titiler_url}/cog/bbox/"
        f"{minx},{miny},{maxx},{maxy}/{width}x{height}.png"
    )

    async def _fetch_tile(client: httpx.AsyncClient, raw_url: str) -> Image.Image | None:
        try:
            signed = await stac_service.sign_pc_url(raw_url)
        except Exception as exc:
            logger.warning("URL signing failed for %s, using unsigned", loc.slug, exc_info=exc)
            signed = raw_url
        resp = await client.get(
            titiler_png_url,
            params={"url": signed, "bidx": [1, 2, 3], "rescale": "0,255"},
        )
        if resp.status_code != 200:
            logger.warning(
                "Titiler bbox render failed for %s (%s): %s %s",
                loc.slug, raw_url, resp.status_code, resp.text[:200],
            )
            return None
        return Image.open(BytesIO(resp.content)).convert("RGBA")

    async with httpx.AsyncClient(timeout=60) as client:
        tiles = await asyncio.gather(
            *(_fetch_tile(client, url) for url in cog_urls)
        )

    valid_tiles = [t for t in tiles if t is not None]
    if not valid_tiles:
        logger.error("All Titiler renders failed for %s", loc.slug)
        return None

    # Paint tiles primary-first onto a black canvas; alpha_composite fills
    # transparent (out-of-footprint) pixels from each subsequent tile. Flatten
    # to RGB before JPEG save since JPEG has no alpha channel.
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    for tile in valid_tiles:
        canvas = Image.alpha_composite(canvas, tile)
    rgb = canvas.convert("RGB")

    out_dir = os.path.join(settings.static_dir, "featured")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{loc.slug}.jpg")
    rgb.save(out_path, "JPEG", quality=85, optimize=True)

    rel_url = f"/static/featured/{loc.slug}.jpg"
    logger.info(
        "Rendered preview for %s from %d NAIP tile(s) (%s)",
        loc.slug, len(valid_tiles), latest.capture_date.isoformat(),
    )
    return rel_url
