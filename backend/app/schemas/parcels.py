"""Pydantic schemas for the parcels endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ParcelResponse(BaseModel):
    """Full parcel record returned by GET /api/v1/parcels/{parcel_id}."""

    id: uuid.UUID
    address: str
    normalized_address: str | None
    latitude: float
    longitude: float
    census_tract_id: str | None
    county: str | None
    state_fips: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    """Response body for GET /api/v1/health."""

    status: str = Field(description="Overall health status: 'ok' or 'degraded'")
    db: str = Field(description="'connected' or 'error'")
    redis: str = Field(description="'connected' or 'error'")
    version: str = Field(default="0.1.0")
