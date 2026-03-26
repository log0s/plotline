"""Featured locations API — curated landing page examples."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.parcels import FeaturedLocation, ImagerySnapshot, Parcel
from app.schemas.featured import FeaturedListResponse, FeaturedLocationResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _snapshot_ids_for_parcel(
    db: Session, parcel_id: str
) -> tuple[str | None, str | None]:
    """Return (earliest_snapshot_id, latest_snapshot_id) for a parcel."""
    stmt = (
        select(ImagerySnapshot.id, ImagerySnapshot.capture_date)
        .where(ImagerySnapshot.parcel_id == parcel_id)
        .order_by(ImagerySnapshot.capture_date.asc())
    )
    rows = db.execute(stmt).all()
    if not rows:
        return (None, None)
    return (str(rows[0][0]), str(rows[-1][0]))


def _build_response(
    loc: FeaturedLocation, parcel: Parcel, db: Session
) -> FeaturedLocationResponse:
    earliest_id, latest_id = _snapshot_ids_for_parcel(db, str(loc.parcel_id))
    return FeaturedLocationResponse(
        id=str(loc.id),
        parcel_id=str(loc.parcel_id),
        name=loc.name,
        subtitle=loc.subtitle,
        slug=loc.slug,
        key_stat=loc.key_stat,
        description=loc.description,
        latitude=parcel.latitude,
        longitude=parcel.longitude,
        earliest_snapshot_id=earliest_id,
        latest_snapshot_id=latest_id,
    )


@router.get("/featured", response_model=FeaturedListResponse)
def list_featured(db: Session = Depends(get_db)) -> FeaturedListResponse:
    """List all featured locations for the landing page."""
    stmt = select(FeaturedLocation).order_by(FeaturedLocation.display_order.asc())
    locations = db.scalars(stmt).all()

    results: list[FeaturedLocationResponse] = []
    for loc in locations:
        parcel = db.get(Parcel, loc.parcel_id)
        if not parcel:
            continue
        results.append(_build_response(loc, parcel, db))

    return FeaturedListResponse(locations=results)


@router.get("/featured/{slug}", response_model=FeaturedLocationResponse)
def get_featured_by_slug(
    slug: str, db: Session = Depends(get_db)
) -> FeaturedLocationResponse:
    """Get a single featured location by slug."""
    stmt = select(FeaturedLocation).where(FeaturedLocation.slug == slug)
    loc = db.scalars(stmt).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Featured location '{slug}' not found")

    parcel = db.get(Parcel, loc.parcel_id)
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel for featured location not found")

    return _build_response(loc, parcel, db)
