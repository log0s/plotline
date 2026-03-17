"""Pydantic schemas for imagery timeline endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class TriggerTimelineResponse(BaseModel):
    """Response when triggering a new timeline fetch."""

    timeline_request_id: uuid.UUID


class TimelineRequestTaskResponse(BaseModel):
    """Per-source task status within a timeline request."""

    source: str
    status: str
    items_found: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class TimelineRequestResponse(BaseModel):
    """Full timeline request status including per-source breakdown."""

    id: uuid.UUID
    parcel_id: uuid.UUID | None
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    tasks: list[TimelineRequestTaskResponse] = []

    model_config = {"from_attributes": True}


class ImagerySnapshotResponse(BaseModel):
    """A single imagery snapshot for display in the timeline."""

    id: uuid.UUID
    source: str
    capture_date: date
    cog_url: str
    thumbnail_url: str | None = None
    resolution_m: float | None = None
    cloud_cover_pct: float | None = None
    stac_item_id: str
    stac_collection: str

    model_config = {"from_attributes": True}


class ImageryListResponse(BaseModel):
    """All imagery snapshots for a parcel, optionally filtered."""

    parcel_id: uuid.UUID
    snapshots: list[ImagerySnapshotResponse]
