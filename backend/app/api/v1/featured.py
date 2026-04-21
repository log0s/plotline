"""Featured locations API — curated landing page examples."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.parcels import FeaturedLocation
from app.schemas.featured import FeaturedListResponse, FeaturedLocationResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _snapshot_ids_for_parcels(
    db: Session, parcel_id_strs: list[str]
) -> dict[str, tuple[str, str]]:
    """Return ``{parcel_id: (earliest_snapshot_id, latest_snapshot_id)}``.

    One raw-SQL query for any number of parcels — sorted by parcel_id
    then capture_date so we can bucket on the way through. Raw SQL
    avoids the ORM's UUID coercion which doesn't match the SQLite
    TEXT-typed test DB.
    """
    if not parcel_id_strs:
        return {}
    placeholders = ",".join(f":p{i}" for i in range(len(parcel_id_strs)))
    params = {f"p{i}": pid for i, pid in enumerate(parcel_id_strs)}
    rows = db.execute(
        sa_text(
            f"""
            SELECT parcel_id, id, capture_date
            FROM imagery_snapshots
            WHERE parcel_id IN ({placeholders})
            ORDER BY parcel_id, capture_date ASC
            """
        ),
        params,
    ).all()
    out: dict[str, tuple[str, str]] = {}
    for pid, sid, _capture_date in rows:
        pid_str = str(pid)
        sid_str = str(sid)
        if pid_str not in out:
            out[pid_str] = (sid_str, sid_str)
        else:
            out[pid_str] = (out[pid_str][0], sid_str)
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


def _parcel_coords(
    db: Session, parcel_id_strs: list[str]
) -> dict[str, tuple[float, float]]:
    """Batch-load (latitude, longitude) per parcel via raw SQL.

    Skips the PostGIS geometry column so this works on both Postgres
    and the SQLite test DB.
    """
    if not parcel_id_strs:
        return {}
    placeholders = ",".join(f":p{i}" for i in range(len(parcel_id_strs)))
    params = {f"p{i}": pid for i, pid in enumerate(parcel_id_strs)}
    rows = db.execute(
        sa_text(
            f"SELECT id, latitude, longitude FROM parcels "
            f"WHERE id IN ({placeholders})"
        ),
        params,
    ).all()
    return {str(pid): (float(lat), float(lng)) for pid, lat, lng in rows}


@router.get("/featured", response_model=FeaturedListResponse)
def list_featured(db: Session = Depends(get_db)) -> FeaturedListResponse:
    """List all featured locations for the landing page."""
    locations = db.scalars(
        select(FeaturedLocation).order_by(FeaturedLocation.display_order.asc())
    ).all()
    if not locations:
        return FeaturedListResponse(locations=[])

    parcel_id_strs = [str(loc.parcel_id) for loc in locations]
    coords_map = _parcel_coords(db, parcel_id_strs)
    snapshot_ids = _snapshot_ids_for_parcels(db, parcel_id_strs)

    results: list[FeaturedLocationResponse] = []
    for loc in locations:
        pid_str = str(loc.parcel_id)
        coords = coords_map.get(pid_str)
        if coords is None:
            logger.warning(
                "Featured location %r (slug=%s) references missing parcel %s — skipping",
                loc.name, loc.slug, loc.parcel_id,
            )
            continue
        earliest_id, latest_id = snapshot_ids.get(pid_str, (None, None))
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

    pid_str = str(loc.parcel_id)
    coords = _parcel_coords(db, [pid_str]).get(pid_str)
    if coords is None:
        raise HTTPException(status_code=404, detail="Parcel for featured location not found")

    earliest_id, latest_id = _snapshot_ids_for_parcels(db, [pid_str]).get(
        pid_str, (None, None)
    )

    return _build_response(
        loc,
        latitude=coords[0],
        longitude=coords[1],
        earliest_snapshot_id=earliest_id,
        latest_snapshot_id=latest_id,
    )
