"""Imagery timeline API endpoints.

POST /api/v1/parcels/{parcel_id}/timeline  — trigger a new fetch
GET  /api/v1/timeline-requests/{request_id} — poll status
GET  /api/v1/parcels/{parcel_id}/imagery    — list snapshots (signed URLs)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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

    # Sign COG URLs at response time (SAS tokens are short-lived)
    snapshot_responses: list[ImagerySnapshotResponse] = []
    for snap in snapshots:
        try:
            signed_cog = await stac_service.sign_pc_url(snap.cog_url)
        except Exception:
            signed_cog = snap.cog_url  # Fall back to unsigned URL on signing failure

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
