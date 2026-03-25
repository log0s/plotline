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
from fastapi.responses import Response
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
    snapshot_responses: list[ImagerySnapshotResponse] = []
    for snap in snapshots:
        if snap.source == "landsat":
            signed_cog = snap.cog_url  # STAC item URL — public, no SAS needed
        else:
            try:
                signed_cog = await stac_service.sign_pc_url(snap.cog_url)
            except Exception:
                signed_cog = snap.cog_url

        try:
            signed_thumb = (
                await stac_service.sign_pc_url(snap.thumbnail_url)
                if snap.thumbnail_url
                else None
            )
        except Exception:
            signed_thumb = snap.thumbnail_url

        # ImagerySnapshotRow is a dataclass — construct response directly
        snapshot_responses.append(
            ImagerySnapshotResponse(
                id=snap.id,
                source=snap.source,
                capture_date=snap.capture_date,
                cog_url=signed_cog,
                thumbnail_url=signed_thumb,
                resolution_m=snap.resolution_m,
                cloud_cover_pct=snap.cloud_cover_pct,
                stac_item_id=snap.stac_item_id,
                stac_collection=snap.stac_collection,
            )
        )

    return ImageryListResponse(parcel_id=parcel_id, snapshots=snapshot_responses)


# ── Tile proxy helpers ────────────────────────────────────────────────────────

# Band/rescale params for single-file COG sources (NAIP and Sentinel-2).
# Landsat uses a separate code path via Titiler's /stac/tiles/ endpoint.
_COG_PARAMS: dict[str, dict[str, object]] = {
    "naip": {"bidx": [1, 2, 3], "rescale": "0,255"},        # 4-band uint8 RGBI
    "sentinel2": {"bidx": [1, 2, 3], "rescale": "0,255"},   # 3-band uint8 TCI
}


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

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "image/png"),
    )


async def _proxy_cog_tile(
    snap: ImagerySnapshotRow, z: int, x: int, y: int, settings: Settings,
) -> Response:
    """Proxy a tile for single-file COG sources (NAIP, Sentinel-2)."""
    try:
        signed_url = await stac_service.sign_pc_url(snap.cog_url)
    except Exception as exc:
        logger.warning("URL signing failed, falling back to unsigned", exc_info=exc)
        signed_url = snap.cog_url

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
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Dispatch to the correct Titiler endpoint based on imagery source."""
    snap = imagery_service.get_snapshot_by_id(db, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    if snap.source == "landsat":
        return await _proxy_landsat_tile(snap, z, x, y, settings)
    return await _proxy_cog_tile(snap, z, x, y, settings)


@router.get(
    "/imagery/{snapshot_id}/stac",
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

    # Fetch the original STAC item from Planetary Computer
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(snap.cog_url)
            resp.raise_for_status()
            stac_item = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch STAC item from %s", snap.cog_url, exc_info=exc)
        raise HTTPException(status_code=502, detail="Failed to fetch STAC item") from exc

    # Sign the band assets Titiler will read (concurrently)
    assets = stac_item.get("assets", {})
    bands = [b for b in ("red", "green", "blue") if b in assets and "href" in assets[b]]
    try:
        signed_hrefs = await asyncio.gather(
            *(stac_service.sign_pc_url(assets[b]["href"]) for b in bands)
        )
        for band, signed in zip(bands, signed_hrefs):
            assets[band]["href"] = signed
    except Exception as exc:
        logger.warning("Band signing partially failed, some may be unsigned", exc_info=exc)

    return Response(
        content=json.dumps(stac_item),
        media_type="application/geo+json",
    )
