"""Demographics service layer.

Handles database operations for census_snapshots — upserts from the Census API
and queries for the demographics endpoint.

Uses raw SQL (like imagery.py) to keep things SQLite-compatible for tests.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class CensusSnapshotRow:
    """Lightweight row representation, avoids ORM for test compatibility."""

    id: uuid.UUID
    parcel_id: uuid.UUID
    tract_fips: str
    dataset: str
    year: int
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
    raw_data: dict | None = None


def upsert_census_snapshot(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    tract_fips: str,
    dataset: str,
    year: int,
    data: dict[str, Any],
    raw_data: dict | None = None,
) -> bool:
    """Insert a census snapshot, updating on conflict (idempotent).

    Returns True if a row was inserted/updated.
    """
    # Compute vacancy_rate if we have the data
    vacancy_rate: float | None = None
    total_housing = data.get("total_housing_units")
    occupied = data.get("occupied_housing_units")
    if total_housing and total_housing > 0 and occupied is not None:
        vacancy_rate = round((total_housing - occupied) / total_housing, 4)

    snap_id = uuid.uuid4()

    sql = sa_text(
        """
        INSERT INTO census_snapshots
            (id, parcel_id, tract_fips, dataset, year,
             total_population, median_household_income, median_home_value,
             median_year_built, total_housing_units, occupied_housing_units,
             owner_occupied_units, renter_occupied_units, vacancy_rate,
             median_age, median_gross_rent, raw_data)
        VALUES
            (:id, :parcel_id, :tract_fips, :dataset, :year,
             :total_population, :median_household_income, :median_home_value,
             :median_year_built, :total_housing_units, :occupied_housing_units,
             :owner_occupied_units, :renter_occupied_units, :vacancy_rate,
             :median_age, :median_gross_rent, :raw_data)
        ON CONFLICT (parcel_id, dataset, year) DO UPDATE SET
            total_population = EXCLUDED.total_population,
            median_household_income = EXCLUDED.median_household_income,
            median_home_value = EXCLUDED.median_home_value,
            median_year_built = EXCLUDED.median_year_built,
            total_housing_units = EXCLUDED.total_housing_units,
            occupied_housing_units = EXCLUDED.occupied_housing_units,
            owner_occupied_units = EXCLUDED.owner_occupied_units,
            renter_occupied_units = EXCLUDED.renter_occupied_units,
            vacancy_rate = EXCLUDED.vacancy_rate,
            median_age = EXCLUDED.median_age,
            median_gross_rent = EXCLUDED.median_gross_rent,
            raw_data = EXCLUDED.raw_data
        """
    )

    import json

    params = {
        "id": str(snap_id),
        "parcel_id": str(parcel_id),
        "tract_fips": tract_fips,
        "dataset": dataset,
        "year": year,
        "total_population": data.get("total_population"),
        "median_household_income": data.get("median_household_income"),
        "median_home_value": data.get("median_home_value"),
        "median_year_built": data.get("median_year_built"),
        "total_housing_units": data.get("total_housing_units"),
        "occupied_housing_units": data.get("occupied_housing_units"),
        "owner_occupied_units": data.get("owner_occupied_units"),
        "renter_occupied_units": data.get("renter_occupied_units"),
        "vacancy_rate": vacancy_rate,
        "median_age": data.get("median_age"),
        "median_gross_rent": data.get("median_gross_rent"),
        "raw_data": json.dumps(raw_data) if raw_data else None,
    }

    db.execute(sql, params)
    db.commit()
    return True


def get_census_snapshots(
    db: Session,
    parcel_id: uuid.UUID,
) -> list[CensusSnapshotRow]:
    """Return all census snapshots for a parcel, sorted by year ascending."""
    sql = sa_text(
        """
        SELECT id, parcel_id, tract_fips, dataset, year,
               total_population, median_household_income, median_home_value,
               median_year_built, total_housing_units, occupied_housing_units,
               owner_occupied_units, renter_occupied_units, vacancy_rate,
               median_age, median_gross_rent, raw_data
        FROM census_snapshots
        WHERE parcel_id = :parcel_id
        ORDER BY year ASC
        """
    )

    rows = db.execute(sql, {"parcel_id": str(parcel_id)}).mappings().all()
    results = []
    for row in rows:
        raw = row["raw_data"]
        if isinstance(raw, str):
            import json
            raw = json.loads(raw)
        results.append(
            CensusSnapshotRow(
                id=uuid.UUID(str(row["id"])),
                parcel_id=uuid.UUID(str(row["parcel_id"])),
                tract_fips=row["tract_fips"],
                dataset=row["dataset"],
                year=row["year"],
                total_population=row["total_population"],
                median_household_income=row["median_household_income"],
                median_home_value=row["median_home_value"],
                median_year_built=row["median_year_built"],
                total_housing_units=row["total_housing_units"],
                occupied_housing_units=row["occupied_housing_units"],
                owner_occupied_units=row["owner_occupied_units"],
                renter_occupied_units=row["renter_occupied_units"],
                vacancy_rate=row["vacancy_rate"],
                median_age=row["median_age"],
                median_gross_rent=row["median_gross_rent"],
                raw_data=raw,
            )
        )
    return results


def compute_subtitles(snapshots: list[CensusSnapshotRow]) -> list[str]:
    """Generate interpretive subtitle strings from census data trends.

    Returns a list of plain-English observations about the data.
    """
    if not snapshots:
        return []

    subtitles: list[str] = []

    # Population trend
    pop_points = [(s.year, s.total_population) for s in snapshots if s.total_population]
    if len(pop_points) >= 2:
        first_year, first_pop = pop_points[0]
        last_year, last_pop = pop_points[-1]
        if first_pop > 0:
            pct = round(((last_pop - first_pop) / first_pop) * 100)
            direction = "grew" if pct > 0 else "declined"
            subtitles.append(
                f"Population {direction} {abs(pct)}% since {first_year} "
                f"({first_pop:,} → {last_pop:,})"
            )

    # Home value trend (ACS only)
    value_points = [
        (s.year, s.median_home_value)
        for s in snapshots
        if s.median_home_value and s.dataset == "acs5"
    ]
    if len(value_points) >= 2:
        first_year, first_val = value_points[0]
        last_year, last_val = value_points[-1]
        if first_val > 0:
            pct = round(((last_val - first_val) / first_val) * 100)
            direction = "rose" if pct > 0 else "fell"
            subtitles.append(
                f"Median home value {direction} {abs(pct)}% since {first_year} "
                f"(${first_val:,} → ${last_val:,}, nominal)"
            )

    # Ownership shift
    owner_points = [
        (s.year, s.owner_occupied_units, s.occupied_housing_units)
        for s in snapshots
        if s.owner_occupied_units and s.occupied_housing_units and s.occupied_housing_units > 0
    ]
    if len(owner_points) >= 2:
        _, first_own, first_occ = owner_points[0]
        _, last_own, last_occ = owner_points[-1]
        first_pct = round(first_own / first_occ * 100)
        last_pct = round(last_own / last_occ * 100)
        if abs(first_pct - last_pct) >= 3:
            subtitles.append(
                f"Owner-occupied shifted from {first_pct}% to {last_pct}%"
            )

    # Median age (latest)
    latest_age = next(
        (s.median_age for s in reversed(snapshots) if s.median_age),
        None,
    )
    if latest_age:
        subtitles.append(f"Median resident age: {latest_age:.1f}")

    # Median year built (latest)
    latest_built = next(
        (s.median_year_built for s in reversed(snapshots) if s.median_year_built),
        None,
    )
    if latest_built:
        subtitles.append(
            f"Typical home built in {latest_built}"
        )

    return subtitles
