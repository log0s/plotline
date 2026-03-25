"""Demographics API endpoints.

GET /parcels/{parcel_id}/demographics — returns census snapshots with
interpretive subtitles.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.demographics import (
    CensusSnapshotResponse,
    DemographicsResponse,
)
from app.services import demographics as demographics_service

router = APIRouter()


@router.get(
    "/parcels/{parcel_id}/demographics",
    response_model=DemographicsResponse,
)
def get_demographics(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DemographicsResponse:
    """Return all census snapshots for a parcel, sorted by year ascending."""
    from sqlalchemy import text as sa_text

    # Use raw SQL to avoid GeoAlchemy2 AsEWKB incompatibility with SQLite tests
    row = db.execute(
        sa_text("SELECT id, census_tract_id FROM parcels WHERE id = :id"),
        {"id": str(parcel_id)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")
    tract_fips = row["census_tract_id"]

    snapshots = demographics_service.get_census_snapshots(db, parcel_id)
    subtitles = demographics_service.compute_subtitles(snapshots)

    return DemographicsResponse(
        parcel_id=parcel_id,
        tract_fips=tract_fips,
        snapshots=[
            CensusSnapshotResponse(
                year=s.year,
                dataset=s.dataset,
                total_population=s.total_population,
                median_household_income=s.median_household_income,
                median_home_value=s.median_home_value,
                median_year_built=s.median_year_built,
                total_housing_units=s.total_housing_units,
                occupied_housing_units=s.occupied_housing_units,
                owner_occupied_units=s.owner_occupied_units,
                renter_occupied_units=s.renter_occupied_units,
                vacancy_rate=s.vacancy_rate,
                median_age=s.median_age,
                median_gross_rent=s.median_gross_rent,
            )
            for s in snapshots
        ],
        subtitles=subtitles,
    )
