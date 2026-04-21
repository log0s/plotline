"""Property events API endpoints.

GET /parcels/{parcel_id}/events — returns property history events with
price summary and appreciation.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.property_events import (
    EventsSummary,
    PricePoint,
    PropertyEventResponse,
    PropertyEventsResponse,
)
from app.services import property_events as property_events_service
from app.services.county_adapters import get_adapter_for_county

router = APIRouter()


@router.get(
    "/parcels/{parcel_id}/events",
    response_model=PropertyEventsResponse,
)
def get_property_events(
    parcel_id: uuid.UUID,
    type: str | None = Query(None, description="Comma-separated event types to filter"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
) -> PropertyEventsResponse:
    """Return all property events for a parcel, sorted by event_date ascending."""
    from sqlalchemy import text as sa_text

    # Look up parcel (raw SQL to avoid GeoAlchemy2 issues in tests)
    row = db.execute(
        sa_text("SELECT id, county FROM parcels WHERE id = :id"),
        {"id": str(parcel_id)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")

    county = row["county"]
    supported = bool(county and get_adapter_for_county(county))

    # Parse event type filter
    event_types: list[str] | None = None
    if type:
        event_types = [t.strip() for t in type.split(",") if t.strip()]

    events = property_events_service.get_property_events(
        db,
        parcel_id,
        event_types=event_types,
        start_date=start_date,
        end_date=end_date,
    )

    summary_data = property_events_service.compute_price_summary(events)

    return PropertyEventsResponse(
        parcel_id=parcel_id,
        county=county,
        supported=supported,
        events=[
            PropertyEventResponse(
                id=e.id,
                event_type=e.event_type,
                event_date=e.event_date,
                description=e.description,
                sale_price=e.sale_price,
                permit_type=e.permit_type,
                permit_description=e.permit_description,
                permit_valuation=e.permit_valuation,
                source=e.source,
            )
            for e in events
        ],
        summary=EventsSummary(
            total_events=summary_data["total_events"],
            total_sales=summary_data["total_sales"],
            total_permits=summary_data["total_permits"],
            price_history=[
                PricePoint(date=p["date"], price=p["price"])
                for p in summary_data["price_history"]
            ],
            appreciation=summary_data["appreciation"],
        ),
    )
