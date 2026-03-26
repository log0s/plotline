"""Featured locations API — curated landing page examples."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.parcels import FeaturedLocation, ImagerySnapshot
from app.schemas.featured import FeaturedListResponse, FeaturedLocationResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _thumbnails_for_parcel(
    db: Session, parcel_id: str
) -> tuple[str | None, str | None]:
    """Return (earliest_thumbnail, latest_thumbnail) for a parcel."""
    stmt = (
        select(ImagerySnapshot.thumbnail_url, ImagerySnapshot.capture_date)
        .where(ImagerySnapshot.parcel_id == parcel_id)
        .where(ImagerySnapshot.thumbnail_url.is_not(None))
        .order_by(ImagerySnapshot.capture_date.asc())
    )
    rows = db.execute(stmt).all()
    if not rows:
        return (None, None)
    return (rows[0][0], rows[-1][0])


@router.get("/featured", response_model=FeaturedListResponse)
def list_featured(db: Session = Depends(get_db)) -> FeaturedListResponse:
    """List all featured locations for the landing page."""
    stmt = select(FeaturedLocation).order_by(FeaturedLocation.display_order.asc())
    locations = db.scalars(stmt).all()

    results: list[FeaturedLocationResponse] = []
    for loc in locations:
        earliest, latest = _thumbnails_for_parcel(db, str(loc.parcel_id))
        results.append(
            FeaturedLocationResponse(
                id=str(loc.id),
                parcel_id=str(loc.parcel_id),
                name=loc.name,
                subtitle=loc.subtitle,
                slug=loc.slug,
                key_stat=loc.key_stat,
                description=loc.description,
                earliest_thumbnail=earliest,
                latest_thumbnail=latest,
            )
        )

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

    earliest, latest = _thumbnails_for_parcel(db, str(loc.parcel_id))
    return FeaturedLocationResponse(
        id=str(loc.id),
        parcel_id=str(loc.parcel_id),
        name=loc.name,
        subtitle=loc.subtitle,
        slug=loc.slug,
        key_stat=loc.key_stat,
        description=loc.description,
        earliest_thumbnail=earliest,
        latest_thumbnail=latest,
    )
