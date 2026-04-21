"""Imagery timeline API endpoints.

POST /api/v1/parcels/{parcel_id}/timeline  — trigger a new fetch
GET  /api/v1/timeline-requests/{request_id} — poll status
GET  /api/v1/parcels/{parcel_id}/imagery    — list snapshots (signed URLs)
GET  /api/v1/imagery/{snapshot_id}/tiles/{z}/{x}/{y} — tile proxy
GET  /api/v1/imagery/{snapshot_id}/stac     — signed STAC item (Landsat)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Response as FastAPIResponse
from fastapi.responses import Response
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.imagery import (
    ImageryListResponse,
    ImagerySnapshotResponse,
    TimelineRequestResponse,
    TimelineRequestTaskResponse,
    TriggerTimelineResponse,
)
from app.services import imagery as imagery_service
from app.services import stac as stac_service
from app.services.imagery import ImagerySnapshotRow

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/parcels/{parcel_id}/timeline",
    response_model=TriggerTimelineResponse,
    status_code=202,
    summary="Trigger imagery timeline fetch",
    description=(
        "Creates a new timeline request for the given parcel and kicks off "
        "an async job to search for NAIP, Landsat, and Sentinel-2 imagery."
    ),
    responses={
        404: {"description": "Parcel not found"},
    },
)
def trigger_timeline(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TriggerTimelineResponse:
    """Trigger a new imagery timeline fetch for an existing parcel."""
    # Verify the parcel exists (raw SQL to avoid GeoAlchemy2 AsEWKB on SQLite)
    from sqlalchemy import text as sa_text

    row = db.execute(
        sa_text("SELECT id FROM parcels WHERE id = :id"),
        {"id": str(parcel_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Parcel {parcel_id} not found")

    # Create timeline request (or return existing complete one)
    request, is_new = imagery_service.get_or_create_timeline_request(db, parcel_id)

    if is_new:
        from app.tasks.timeline import fetch_imagery_timeline

        fetch_imagery_timeline.delay(str(request.id))
        logger.info(
            "Timeline task dispatched",
            extra={"parcel_id": str(parcel_id), "request_id": str(request.id)},
        )

    return TriggerTimelineResponse(timeline_request_id=request.id)


@router.get(
    "/timeline-requests/{request_id}",
    response_model=TimelineRequestResponse,
    summary="Get timeline request status",
    description="Returns the overall status and per-source task breakdown.",
    responses={
        404: {"description": "Timeline request not found"},
    },
)
def get_timeline_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TimelineRequestResponse:
    """Return timeline request status including per-source tasks."""
    request = imagery_service.get_timeline_request(db, request_id)
    if not request:
        raise HTTPException(
            status_code=404, detail=f"Timeline request {request_id} not found"
        )

    tasks = [TimelineRequestTaskResponse.model_validate(t) for t in request.tasks]
    return TimelineRequestResponse(
        id=request.id,
        parcel_id=request.parcel_id,
        status=request.status,
        created_at=request.created_at,
        completed_at=request.completed_at,
        error_message=request.error_message,
        tasks=tasks,
    )


@router.get(
    "/parcels/{parcel_id}/imagery",
    response_model=ImageryListResponse,
    summary="List imagery snapshots for a parcel",
    description=(
        "Returns all available imagery snapshots for the given parcel, "
        "sorted chronologically. COG URLs are signed at response time."
    ),
    responses={
        404: {"description": "Parcel not found"},
    },
)
async def list_imagery(
    parcel_id: uuid.UUID,
    response: FastAPIResponse,
    source: str | None = Query(default=None, description="Filter by source: naip, landsat, sentinel2"),
    start_date: date | None = Query(default=None, description="Filter by start date (inclusive)"),
    end_date: date | None = Query(default=None, description="Filter by end date (inclusive)"),
    db: Session = Depends(get_db),
) -> ImageryListResponse:
    """Return imagery snapshots with signed COG URLs."""
    from sqlalchemy import text as sa_text

    row = db.execute(
        sa_text("SELECT id FROM parcels WHERE id = :id"),
        {"id": str(parcel_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Parcel {parcel_id} not found")

    snapshots = imagery_service.get_imagery_snapshots(
        db,
        parcel_id=parcel_id,
        source=source,
        start_date=start_date,
        end_date=end_date,
    )

    # Sign COG URLs at response time (SAS tokens are short-lived).
    # Landsat cog_url is a STAC item link (public, no signing needed).
    # Collect every URL that needs signing, then run them in parallel —
    # a parcel can have 80+ URLs (e.g. Rodanthe with full Sentinel-2 stack)
    # and serial awaits compound to tens of seconds even with Redis cache.
    urls_to_sign: set[str] = set()
    for snap in snapshots:
        if snap.source != "landsat":
            urls_to_sign.add(snap.cog_url)
            if snap.additional_cog_urls:
                urls_to_sign.update(snap.additional_cog_urls)
        if snap.thumbnail_url:
            urls_to_sign.add(snap.thumbnail_url)

    url_list = list(urls_to_sign)
    results = await asyncio.gather(
        *(stac_service.sign_pc_url(u) for u in url_list),
        return_exceptions=True,
    )
    signed_map: dict[str, str] = {
        u: (r if isinstance(r, str) else u) for u, r in zip(url_list, results, strict=False)
    }

    snapshot_responses: list[ImagerySnapshotResponse] = []
    for snap in snapshots:
        if snap.source == "landsat":
            signed_cog = snap.cog_url
            signed_extras: list[str] | None = snap.additional_cog_urls
        else:
            signed_cog = signed_map.get(snap.cog_url, snap.cog_url)
            signed_extras = (
                [signed_map.get(u, u) for u in snap.additional_cog_urls]
                if snap.additional_cog_urls
                else None
            )

        signed_thumb = (
            signed_map.get(snap.thumbnail_url, snap.thumbnail_url)
            if snap.thumbnail_url
            else None
        )

        snapshot_responses.append(
            ImagerySnapshotResponse(
                id=snap.id,
                source=snap.source,
                capture_date=snap.capture_date,
                cog_url=signed_cog,
                additional_cog_urls=signed_extras,
                bbox=list(snap.bbox) if snap.bbox else None,
                thumbnail_url=signed_thumb,
                resolution_m=snap.resolution_m,
                cloud_cover_pct=snap.cloud_cover_pct,
                stac_item_id=snap.stac_item_id,
                stac_collection=snap.stac_collection,
            )
        )

    # Only cache non-empty responses — empty results may become stale when
    # the timeline completes and imagery is inserted later.
    if snapshot_responses:
        response.headers["Cache-Control"] = "public, max-age=3600"
    else:
        response.headers["Cache-Control"] = "no-cache"

    return ImageryListResponse(parcel_id=parcel_id, snapshots=snapshot_responses)


# ── Tile proxy helpers ────────────────────────────────────────────────────────

# Band/rescale params for single-file COG sources (NAIP and Sentinel-2).
# Landsat uses a separate code path via Titiler's /stac/tiles/ endpoint.
_COG_PARAMS: dict[str, dict[str, object]] = {
    "naip": {"bidx": [1, 2, 3], "rescale": "0,255"},        # 4-band uint8 RGBI
    "sentinel2": {"bidx": [1, 2, 3], "rescale": "0,255"},   # 3-band uint8 TCI
}


# 1x1 transparent PNG (68 bytes) — returned for out-of-bounds tile requests
# so MapLibre doesn't log 404 errors for edge tiles.
_TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _fetch_titiler(
    titiler_url: str,
    params: dict[str, object] | list[tuple[str, str]],
    snapshot_id: uuid.UUID,
) -> Response:
    """Forward a tile request to Titiler and return the response."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            upstream = await client.get(titiler_url, params=params)
    except httpx.RequestError as exc:
        logger.error("Titiler request failed", exc_info=exc)
        raise HTTPException(status_code=502, detail="Titiler upstream unreachable") from exc

    if upstream.status_code >= 500:
        logger.error(
            "Titiler returned %s for snapshot %s",
            upstream.status_code,
            snapshot_id,
            extra={"titiler_body": upstream.text[:500]},
        )
        raise HTTPException(status_code=502, detail="Titiler upstream error")

    # Return a transparent tile for out-of-bounds requests instead of 404,
    # so MapLibre doesn't log errors for edge tiles outside the COG extent.
    if upstream.status_code == 404:
        return Response(
            content=_TRANSPARENT_PNG,
            status_code=200,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


async def _proxy_cog_tile(
    snap: ImagerySnapshotRow,
    z: int,
    x: int,
    y: int,
    settings: Settings,
    *,
    cog_index: int = 0,
) -> Response:
    """Proxy a tile for single-file COG sources (NAIP, Sentinel-2).

    ``cog_index`` selects which COG to render: 0 = primary (``cog_url``),
    1+ = ``additional_cog_urls[cog_index - 1]`` (mosaic components).
    """
    if cog_index == 0:
        source_url = snap.cog_url
    else:
        extras = snap.additional_cog_urls or []
        if cog_index - 1 >= len(extras):
            raise HTTPException(status_code=404, detail="cog index out of range")
        source_url = extras[cog_index - 1]

    try:
        signed_url = await stac_service.sign_pc_url(source_url)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        logger.warning("URL signing failed, falling back to unsigned", exc_info=exc)
        signed_url = source_url

    band_params = _COG_PARAMS.get(snap.source, {"bidx": [1, 2, 3], "rescale": "0,255"})
    params: dict[str, object] = {"url": signed_url, **band_params}
    titiler_url = f"{settings.titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
    return await _fetch_titiler(titiler_url, params, snap.id)


async def _proxy_landsat_tile(
    snap: ImagerySnapshotRow, z: int, x: int, y: int, settings: Settings,
) -> Response:
    """Proxy a Landsat tile via Titiler's STAC endpoint for RGB compositing.

    Landsat bands are separate single-band COGs, so we point Titiler at our
    ``/imagery/{id}/stac`` endpoint which serves the STAC item JSON with
    freshly signed asset URLs.  Titiler reads the red/green/blue COGs and
    composites them into a single RGB tile.
    """
    stac_item_url = f"{settings.api_internal_url}/api/v1/imagery/{snap.id}/stac"
    # Landsat C2 L2 surface reflectance: uint16, nodata=0,
    # scale=2.75e-05, offset=-0.2.  Typical land DNs are 7000–20000.
    # rescale 7000,14000 gives good contrast for most land surfaces.
    params: dict[str, object] = {
        "url": stac_item_url,
        "assets": ["red", "green", "blue"],
        "asset_as_band": True,
        "nodata": 0,
        "rescale": ["7000,14000", "7000,14000", "7000,14000"],
    }
    titiler_url = f"{settings.titiler_url}/stac/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
    return await _fetch_titiler(titiler_url, params, snap.id)


@router.get(
    "/imagery/{snapshot_id}/tiles/{z}/{x}/{y}",
    summary="Proxy a tile through Titiler with fresh signed URLs",
    description=(
        "Routes to Titiler's COG or STAC tile endpoint depending on the "
        "imagery source. SAS tokens are generated at request time so they "
        "never expire in the browser's tile URL template."
    ),
    responses={
        404: {"description": "Snapshot not found"},
        502: {"description": "Titiler upstream error"},
    },
)
async def proxy_imagery_tile(
    snapshot_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    cog: int = Query(default=0, ge=0, description="Mosaic tile index (0 = primary)"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Dispatch to the correct Titiler endpoint based on imagery source."""
    snap = imagery_service.get_snapshot_by_id(db, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    # Close the DB session before the outbound HTTP call to Titiler so we
    # don't hold a connection idle-in-transaction for the duration of the
    # (potentially slow) upstream request.
    db.close()

    if snap.source == "landsat":
        # Landsat mosaic components not yet supported — always render primary
        return await _proxy_landsat_tile(snap, z, x, y, settings)
    return await _proxy_cog_tile(snap, z, x, y, settings, cog_index=cog)


@router.get(
    "/imagery/{snapshot_id}/stac",
    response_class=Response,
    summary="Return a STAC item with signed asset URLs (for Titiler STACReader)",
    description=(
        "Fetches the original STAC item JSON from Planetary Computer and signs "
        "the red, green, and blue band asset hrefs. Titiler calls this endpoint "
        "when serving Landsat tiles via /stac/tiles/."
    ),
    responses={
        404: {"description": "Snapshot not found or not a STAC-tile source"},
        502: {"description": "Failed to fetch STAC item from upstream"},
    },
)
async def get_signed_stac_item(
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Serve a Landsat STAC item with freshly signed band URLs."""
    snap = imagery_service.get_snapshot_by_id(db, snapshot_id)
    if not snap or snap.source != "landsat":
        raise HTTPException(status_code=404, detail="Not found or not a STAC-tile source")

    # Release the DB connection before outbound HTTP calls
    db.close()

    # Try Redis cache for the raw (unsigned) STAC item JSON.
    # The item metadata is immutable; only band URLs need fresh signing.
    from app.db import get_redis

    cache_key = f"stac:{snapshot_id}"
    stac_item = None

    try:
        cached = get_redis().get(cache_key)
        if cached:
            stac_item = json.loads(cached)
    except (RedisError, OSError) as exc:
        logger.debug("STAC item cache read failed: %s", exc)

    if stac_item is None:
        # Fetch the original STAC item from Planetary Computer
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(snap.cog_url)
                resp.raise_for_status()
                stac_item = resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error("Failed to fetch STAC item from %s", snap.cog_url, exc_info=exc)
            raise HTTPException(status_code=502, detail="Failed to fetch STAC item") from exc

        # Cache the raw item (before signing) for 1 hour
        try:
            get_redis().setex(cache_key, 3600, json.dumps(stac_item))
        except (RedisError, OSError) as exc:
            logger.debug("STAC item cache write failed: %s", exc)

    # Sign the band assets Titiler will read (concurrently). Per-band
    # isolation: a single band failing to sign falls back to its
    # unsigned href instead of breaking all three.
    assets = stac_item.get("assets", {})
    bands = [b for b in ("red", "green", "blue") if b in assets and "href" in assets[b]]
    sign_results = await asyncio.gather(
        *(stac_service.sign_pc_url(assets[b]["href"]) for b in bands),
        return_exceptions=True,
    )
    for band, result in zip(bands, sign_results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "Band signing failed; using unsigned href",
                extra={"band": band, "snapshot_id": str(snapshot_id)},
                exc_info=result,
            )
        else:
            assets[band]["href"] = result

    return Response(
        content=json.dumps(stac_item),
        media_type="application/geo+json",
    )
