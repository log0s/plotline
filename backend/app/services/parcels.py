"""Parcel business logic.

Handles the get-or-create deduplication pattern:
  - Given a geocode result, look for an existing parcel within 50 metres
  - If found, return the existing parcel (deduplication)
  - If not found, insert a new parcel and return it
"""

from __future__ import annotations

import logging

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint
from sqlalchemy import cast
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.parcels import Parcel
from app.services.geocoder import GeocodeResult

logger = logging.getLogger(__name__)


def _lock_parcel_location(db: Session, latitude: float, longitude: float) -> None:
    """Serialize concurrent get-or-create calls for one geocoded location.

    "Within 50 m" dedup can't be expressed as a unique constraint, so two
    concurrent first geocodes of the same address would both miss the
    lookup and insert duplicate parcels. A transaction-scoped advisory
    lock on the geocoded coordinates closes the window: it's released when
    the insert commits, at which point the waiter's lookup sees the new
    row. The same address always geocodes to the same point, so both
    requests contend on the same key. No-op on SQLite (tests), which has
    no advisory locks.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    key = f"parcel:{longitude:.6f},{latitude:.6f}"
    db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


def find_nearby_parcel(
    db: Session,
    latitude: float,
    longitude: float,
    radius_meters: float,
) -> Parcel | None:
    """Find an existing parcel within `radius_meters` of the given point.

    Uses PostGIS ST_DWithin on geography type so the distance is in metres,
    not degrees.

    Returns the nearest parcel, or None if no match exists.
    """
    geography_type = Geography(geometry_type="POINT", srid=4326)

    # Build a geography-cast point for the query location
    query_point = cast(
        ST_MakePoint(longitude, latitude),
        geography_type,
    )

    result = (
        db.query(Parcel)
        .filter(
            ST_DWithin(
                cast(Parcel.point, geography_type),
                query_point,
                radius_meters,
            )
        )
        .order_by(ST_Distance(cast(Parcel.point, geography_type), query_point))
        .first()
    )
    return result


def get_or_create_parcel(
    db: Session,
    address: str,
    geocode_result: GeocodeResult,
    settings: Settings,
) -> tuple[Parcel, bool]:
    """Return (parcel, is_new).

    Looks for an existing parcel within the configured deduplication radius.
    Creates a new parcel if none is found.

    Args:
        db:             SQLAlchemy session.
        address:        Original address string as submitted by the user.
        geocode_result: Structured result from the geocoder service.
        settings:       Application settings (provides dedup radius).

    Returns:
        A tuple of (Parcel, is_new) where is_new is True if a new row was inserted.
    """
    _lock_parcel_location(db, geocode_result.latitude, geocode_result.longitude)

    existing = find_nearby_parcel(
        db=db,
        latitude=geocode_result.latitude,
        longitude=geocode_result.longitude,
        radius_meters=settings.parcel_dedup_radius_meters,
    )

    if existing:
        # Backfill census metadata the existing parcel is missing — each
        # field independently, so a parcel with a tract but no county
        # still heals.
        changed = False
        if not existing.census_tract_id and geocode_result.census_tract_id:
            existing.census_tract_id = geocode_result.census_tract_id
            changed = True
        if not existing.county and geocode_result.county:
            existing.county = geocode_result.county
            changed = True
        if not existing.state_fips and geocode_result.state_fips:
            existing.state_fips = geocode_result.state_fips
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)
            logger.info(
                "Backfilled census metadata on existing parcel",
                extra={"parcel_id": str(existing.id), "tract": existing.census_tract_id},
            )
        logger.info(
            "Deduplication hit — returning existing parcel",
            extra={"parcel_id": str(existing.id), "radius_m": settings.parcel_dedup_radius_meters},
        )
        return existing, False

    # Build WKT point for GeoAlchemy2
    wkt_point = f"SRID=4326;POINT({geocode_result.longitude} {geocode_result.latitude})"

    parcel = Parcel(
        address=address,
        normalized_address=geocode_result.normalized_address,
        latitude=geocode_result.latitude,
        longitude=geocode_result.longitude,
        point=wkt_point,
        census_tract_id=geocode_result.census_tract_id,
        county=geocode_result.county,
        state_fips=geocode_result.state_fips,
    )

    db.add(parcel)
    db.commit()
    db.refresh(parcel)

    logger.info(
        "New parcel created",
        extra={"parcel_id": str(parcel.id), "address": parcel.normalized_address},
    )

    return parcel, True
