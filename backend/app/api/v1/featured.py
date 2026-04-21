"""Featured locations API — curated landing page examples."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.parcels import FeaturedLocation, ImagerySnapshot, Parcel
from app.schemas.featured import FeaturedListResponse, FeaturedLocationResponse

if TYPE_CHECKING:
    import uuid

logger = logging.getLogger(__name__)

router = APIRouter()


def _snapshot_ids_for_parcels(
    db: Session, parcel_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """Return ``{parcel_id: (earliest_snapshot_id, latest_snapshot_id)}``.

    One query for any number of parcels — the rows are sorted by
    parcel_id then capture_date so we can bucket on the way through.
    """
    if not parcel_ids:
        return {}
    rows = db.execute(
        select(
            ImagerySnapshot.parcel_id,
            ImagerySnapshot.id,
            ImagerySnapshot.capture_date,
        )
        .where(ImagerySnapshot.parcel_id.in_(parcel_ids))
        .order_by(
            ImagerySnapshot.parcel_id, ImagerySnapshot.capture_date.asc()
        )
    ).all()
    out: dict[uuid.UUID, tuple[str, str]] = {}
    for pid, sid, _capture_date in rows:
        sid_str = str(sid)
        if pid not in out:
            out[pid] = (sid_str, sid_str)
        else:
            out[pid] = (out[pid][0], sid_str)
    return out


def _build_response(
    loc: FeaturedLocation,
    *,
    latitude: float,
    longitude: float,
    earliest_snapshot_id: str | None,
    latest_snapshot_id: str | None,
) -> FeaturedLocationResponse:
    return FeaturedLocationResponse(
        id=str(loc.id),
        parcel_id=str(loc.parcel_id),
        name=loc.name,
        subtitle=loc.subtitle,
        slug=loc.slug,
        key_stat=loc.key_stat,
        description=loc.description,
        latitude=latitude,
        longitude=longitude,
        earliest_snapshot_id=earliest_snapshot_id,
        latest_snapshot_id=latest_snapshot_id,
        preview_image_url=loc.preview_image_url,
    )


@router.get("/featured", response_model=FeaturedListResponse)
def list_featured(db: Session = Depends(get_db)) -> FeaturedListResponse:
    """List all featured locations for the landing page."""
    locations = db.scalars(
        select(FeaturedLocation).order_by(FeaturedLocation.display_order.asc())
    ).all()
    if not locations:
        return FeaturedListResponse(locations=[])

    parcel_ids = [loc.parcel_id for loc in locations]

    # Batch-load just the parcel coordinates (skipping the PostGIS geometry
    # column so this stays compatible with the SQLite test DB).
    parcel_rows = db.execute(
        select(Parcel.id, Parcel.latitude, Parcel.longitude)
        .where(Parcel.id.in_(parcel_ids))
    ).all()
    parcel_coords: dict[uuid.UUID, tuple[float, float]] = {
        pid: (lat, lng) for pid, lat, lng in parcel_rows
    }
    snapshot_ids = _snapshot_ids_for_parcels(db, parcel_ids)

    results: list[FeaturedLocationResponse] = []
    for loc in locations:
        coords = parcel_coords.get(loc.parcel_id)
        if coords is None:
            logger.warning(
                "Featured location %r (slug=%s) references missing parcel %s — skipping",
                loc.name, loc.slug, loc.parcel_id,
            )
            continue
        earliest_id, latest_id = snapshot_ids.get(loc.parcel_id, (None, None))
        results.append(
            _build_response(
                loc,
                latitude=coords[0],
                longitude=coords[1],
                earliest_snapshot_id=earliest_id,
                latest_snapshot_id=latest_id,
            )
        )

    return FeaturedListResponse(locations=results)


@router.get("/featured/{slug}", response_model=FeaturedLocationResponse)
def get_featured_by_slug(
    slug: str, db: Session = Depends(get_db)
) -> FeaturedLocationResponse:
    """Get a single featured location by slug."""
    loc = db.scalars(
        select(FeaturedLocation).where(FeaturedLocation.slug == slug)
    ).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Featured location '{slug}' not found")

    parcel_row = db.execute(
        select(Parcel.id, Parcel.latitude, Parcel.longitude)
        .where(Parcel.id == loc.parcel_id)
    ).first()
    if not parcel_row:
        raise HTTPException(status_code=404, detail="Parcel for featured location not found")
    _, lat, lng = parcel_row

    earliest_id, latest_id = _snapshot_ids_for_parcels(
        db, [loc.parcel_id]
    ).get(loc.parcel_id, (None, None))

    return _build_response(
        loc,
        latitude=lat,
        longitude=lng,
        earliest_snapshot_id=earliest_id,
        latest_snapshot_id=latest_id,
    )
