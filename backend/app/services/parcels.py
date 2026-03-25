"""Parcel business logic.

Handles the get-or-create deduplication pattern:
  - Given a geocode result, look for an existing parcel within 50 metres
  - If found, return the existing parcel (deduplication)
  - If not found, insert a new parcel and return it
"""

from __future__ import annotations

import logging

from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint
from sqlalchemy import cast
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.parcels import Parcel
from app.services.geocoder import GeocodeResult

logger = logging.getLogger(__name__)


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
    existing = find_nearby_parcel(
        db=db,
        latitude=geocode_result.latitude,
        longitude=geocode_result.longitude,
        radius_meters=settings.parcel_dedup_radius_meters,
    )

    if existing:
        # Backfill census tract if the existing parcel is missing it
        # (happens for parcels geocoded before the /geographies/ URL fix)
        if not existing.census_tract_id and geocode_result.census_tract_id:
            existing.census_tract_id = geocode_result.census_tract_id
            existing.county = existing.county or geocode_result.county
            existing.state_fips = existing.state_fips or geocode_result.state_fips
            db.commit()
            db.refresh(existing)
            logger.info(
                "Backfilled census tract on existing parcel",
                extra={"parcel_id": str(existing.id), "tract": geocode_result.census_tract_id},
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
