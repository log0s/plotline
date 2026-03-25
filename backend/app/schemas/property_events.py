"""Pydantic schemas for property events endpoints."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel


class PropertyEventResponse(BaseModel):
    """A single property event for display."""

    id: uuid.UUID
    event_type: str
    event_date: date | None = None
    description: str | None = None
    sale_price: int | None = None
    permit_type: str | None = None
    permit_description: str | None = None
    permit_valuation: int | None = None
    source: str

    model_config = {"from_attributes": True}


class PricePoint(BaseModel):
    """A single sale price data point."""

    date: str
    price: int


class EventsSummary(BaseModel):
    """Computed summary of property events."""

    total_events: int
    total_sales: int
    total_permits: int
    price_history: list[PricePoint]
    appreciation: str | None = None


class PropertyEventsResponse(BaseModel):
    """All property events for a parcel with summary."""

    parcel_id: uuid.UUID
    county: str | None
    supported: bool
    events: list[PropertyEventResponse]
    summary: EventsSummary
