"""Pydantic schemas for demographics endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class CensusSnapshotResponse(BaseModel):
    """A single census data point for display."""

    year: int
    dataset: str
    total_population: int | None = None
    median_household_income: int | None = None
    median_home_value: int | None = None
    median_year_built: int | None = None
    total_housing_units: int | None = None
    occupied_housing_units: int | None = None
    owner_occupied_units: int | None = None
    renter_occupied_units: int | None = None
    vacancy_rate: float | None = None
    median_age: float | None = None
    median_gross_rent: int | None = None

    model_config = {"from_attributes": True}


class DemographicsResponse(BaseModel):
    """All census snapshots for a parcel with interpretive context."""

    parcel_id: uuid.UUID
    tract_fips: str | None
    snapshots: list[CensusSnapshotResponse]
    subtitles: list[str]
    notes: str = (
        "Census tract boundaries may differ across decades. "
        "Data shown is for the tract containing this address in each "
        "respective year's geography. Dollar values are nominal (not inflation-adjusted)."
    )
