"""Tests for Census API client, FIPS parsing, demographics service, and endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.census import (
    CensusFetcher,
    _parse_response,
    _to_number,
    parse_tract_fips,
)
from app.services.demographics import (
    CensusSnapshotRow,
    compute_subtitles,
    get_census_snapshots,
    upsert_census_snapshot,
)


# ── FIPS parsing ──────────────────────────────────────────────────────────────


class TestParseTractFips:
    def test_valid_fips(self) -> None:
        state, county, tract = parse_tract_fips("08031006202")
        assert state == "08"
        assert county == "031"
        assert tract == "006202"

    def test_different_fips(self) -> None:
        state, county, tract = parse_tract_fips("36061002300")
        assert state == "36"
        assert county == "061"
        assert tract == "002300"

    def test_invalid_length(self) -> None:
        with pytest.raises(ValueError, match="11-character"):
            parse_tract_fips("0803100")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError, match="11-character"):
            parse_tract_fips("")


# ── Census API response parsing ───────────────────────────────────────────────


class TestParseResponse:
    def test_normal_response(self) -> None:
        data = [
            ["B01003_001E", "B19013_001E", "state", "county", "tract"],
            ["4523", "52340", "08", "031", "006202"],
        ]
        result = _parse_response(data)
        assert result == {"B01003_001E": 4523, "B19013_001E": 52340}

    def test_empty_response(self) -> None:
        assert _parse_response([]) == {}
        assert _parse_response([["header"]]) == {}

    def test_excludes_geography_fields(self) -> None:
        data = [
            ["B01003_001E", "state", "county", "tract"],
            ["1000", "08", "031", "006202"],
        ]
        result = _parse_response(data)
        assert "state" not in result
        assert "county" not in result
        assert "tract" not in result
        assert result["B01003_001E"] == 1000


class TestToNumber:
    def test_integer(self) -> None:
        assert _to_number("4523") == 4523

    def test_float(self) -> None:
        assert _to_number("34.2") == 34.2

    def test_not_available_sentinel(self) -> None:
        assert _to_number("-666666666") is None

    def test_none(self) -> None:
        assert _to_number(None) is None

    def test_empty_string(self) -> None:
        assert _to_number("") is None

    def test_non_numeric(self) -> None:
        assert _to_number("N/A") is None


# ── CensusFetcher ─────────────────────────────────────────────────────────────


class TestCensusFetcher:
    @pytest.mark.asyncio
    async def test_fetch_acs5_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [
                "B01003_001E", "B19013_001E", "B25077_001E", "B25035_001E",
                "B25003_001E", "B25003_002E", "B25003_003E", "B01002_001E",
                "B25064_001E", "state", "county", "tract",
            ],
            [
                "4523", "52340", "215000", "1978",
                "1764", "1102", "662", "34.2",
                "1150", "08", "031", "006202",
            ],
        ]

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_acs5(2023, "08", "031", "006202")

        assert result["total_population"] == 4523
        assert result["median_household_income"] == 52340
        assert result["median_home_value"] == 215000
        assert result["median_age"] == 34.2
        assert result["median_gross_rent"] == 1150

    @pytest.mark.asyncio
    async def test_fetch_decennial_2020(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            ["P1_001N", "H1_001N", "state", "county", "tract"],
            ["5200", "2100", "08", "031", "006202"],
        ]

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_decennial(2020, "08", "031", "006202")
        assert result["total_population"] == 5200
        assert result["total_housing_units"] == 2100

    @pytest.mark.asyncio
    async def test_fetch_decennial_2000_variable_names(self) -> None:
        """2000 uses P001001/H001001 instead of 2020's P1_001N/H1_001N."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            ["P001001", "H001001", "state", "county", "tract"],
            ["2841", "1205", "08", "031", "006202"],
        ]

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_decennial(2000, "08", "031", "006202")
        assert result["total_population"] == 2841
        assert result["total_housing_units"] == 1205

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_204(self) -> None:
        """204 = tract doesn't exist in this vintage. Should return empty dict."""
        mock_response = MagicMock()
        mock_response.status_code = 204

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_acs5(2009, "08", "031", "999999")
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_decennial(1990, "08", "031", "999999")
        assert result == {}

    @pytest.mark.asyncio
    async def test_sentinel_value_handled(self) -> None:
        """Census API returns -666666666 for unavailable data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [
                "B01003_001E", "B19013_001E", "B25077_001E", "B25035_001E",
                "B25003_001E", "B25003_002E", "B25003_003E", "B01002_001E",
                "B25064_001E", "state", "county", "tract",
            ],
            [
                "4523", "-666666666", "-666666666", "1978",
                "1764", "1102", "662", "34.2",
                "-666666666", "08", "031", "006202",
            ],
        ]

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        result = await fetcher.fetch_acs5(2009, "08", "031", "006202")
        assert result["total_population"] == 4523
        assert result["median_household_income"] is None
        assert result["median_home_value"] is None
        assert result["median_gross_rent"] is None
        assert result["median_year_built"] == 1978


# ── Demographics service (DB layer) ──────────────────────────────────────────


class TestDemographicsService:
    def test_upsert_and_query(self, db) -> None:
        """Insert a census snapshot and read it back."""
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point, census_tract_id) "
                "VALUES (:id, :addr, :lat, :lng, :pt, :tract)"
            ),
            {
                "id": parcel_id,
                "addr": "123 Main St",
                "lat": 39.7,
                "lng": -104.9,
                "pt": "POINT(-104.9 39.7)",
                "tract": "08031006202",
            },
        )
        db.commit()

        pid = uuid.UUID(parcel_id)
        upsert_census_snapshot(
            db,
            parcel_id=pid,
            tract_fips="08031006202",
            dataset="acs5",
            year=2023,
            data={
                "total_population": 4523,
                "median_household_income": 52340,
                "median_home_value": 215000,
                "occupied_housing_units": 1764,
                "total_housing_units": 1876,
            },
        )

        rows = get_census_snapshots(db, pid)
        assert len(rows) == 1
        assert rows[0].year == 2023
        assert rows[0].total_population == 4523
        assert rows[0].vacancy_rate is not None
        assert abs(rows[0].vacancy_rate - 0.0597) < 0.01

    def test_idempotent_upsert(self, db) -> None:
        """Running upsert twice with same (parcel, dataset, year) should not create duplicates."""
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point) "
                "VALUES (:id, :addr, :lat, :lng, :pt)"
            ),
            {"id": parcel_id, "addr": "456 Oak Ave", "lat": 39.7, "lng": -104.9, "pt": "POINT(-104.9 39.7)"},
        )
        db.commit()

        pid = uuid.UUID(parcel_id)
        data = {"total_population": 3000, "total_housing_units": 1200}

        upsert_census_snapshot(db, parcel_id=pid, tract_fips="08031006202", dataset="decennial", year=2020, data=data)
        upsert_census_snapshot(db, parcel_id=pid, tract_fips="08031006202", dataset="decennial", year=2020, data={"total_population": 3100, "total_housing_units": 1250})

        rows = get_census_snapshots(db, pid)
        assert len(rows) == 1
        assert rows[0].total_population == 3100  # Updated, not duplicated


# ── Subtitle generation ───────────────────────────────────────────────────────


class TestComputeSubtitles:
    def test_population_growth(self) -> None:
        snapshots = [
            CensusSnapshotRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), tract_fips="08031006202",
                dataset="decennial", year=1990, total_population=2000,
            ),
            CensusSnapshotRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), tract_fips="08031006202",
                dataset="acs5", year=2023, total_population=8000,
                median_household_income=65000, median_home_value=350000,
                occupied_housing_units=3000, owner_occupied_units=1800,
            ),
        ]
        subtitles = compute_subtitles(snapshots)
        assert any("300%" in s for s in subtitles)
        assert any("Population grew" in s for s in subtitles)

    def test_empty_snapshots(self) -> None:
        assert compute_subtitles([]) == []

    def test_home_value_subtitle(self) -> None:
        snapshots = [
            CensusSnapshotRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), tract_fips="08031006202",
                dataset="acs5", year=2009, median_home_value=200000,
            ),
            CensusSnapshotRow(
                id=uuid.uuid4(), parcel_id=uuid.uuid4(), tract_fips="08031006202",
                dataset="acs5", year=2023, median_home_value=450000,
            ),
        ]
        subtitles = compute_subtitles(snapshots)
        assert any("home value" in s.lower() for s in subtitles)
        assert any("125%" in s for s in subtitles)


# ── Demographics endpoint ─────────────────────────────────────────────────────


class TestDemographicsEndpoint:
    def test_get_demographics_404(self, client) -> None:
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/parcels/{fake_id}/demographics")
        assert resp.status_code == 404

    def test_get_demographics_empty(self, client, db) -> None:
        """A parcel with no census data should return empty snapshots."""
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point, census_tract_id) "
                "VALUES (:id, :addr, :lat, :lng, :pt, :tract)"
            ),
            {
                "id": parcel_id,
                "addr": "789 Elm St",
                "lat": 39.7,
                "lng": -104.9,
                "pt": "POINT(-104.9 39.7)",
                "tract": "08031006202",
            },
        )
        db.commit()

        resp = client.get(f"/api/v1/parcels/{parcel_id}/demographics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["parcel_id"] == parcel_id
        assert data["tract_fips"] == "08031006202"
        assert data["snapshots"] == []
        assert isinstance(data["subtitles"], list)
        assert "notes" in data

    def test_get_demographics_with_data(self, client, db) -> None:
        """Insert census data and verify the endpoint returns it sorted."""
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point, census_tract_id) "
                "VALUES (:id, :addr, :lat, :lng, :pt, :tract)"
            ),
            {
                "id": parcel_id,
                "addr": "100 Test Blvd",
                "lat": 39.7,
                "lng": -104.9,
                "pt": "POINT(-104.9 39.7)",
                "tract": "08031006202",
            },
        )
        # Insert two census snapshots
        snap1 = str(uuid.uuid4())
        snap2 = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO census_snapshots (id, parcel_id, tract_fips, dataset, year, total_population) "
                "VALUES (:id, :pid, :tract, :ds, :yr, :pop)"
            ),
            {"id": snap1, "pid": parcel_id, "tract": "08031006202", "ds": "decennial", "yr": 2020, "pop": 5000},
        )
        db.execute(
            text(
                "INSERT INTO census_snapshots (id, parcel_id, tract_fips, dataset, year, total_population, median_household_income) "
                "VALUES (:id, :pid, :tract, :ds, :yr, :pop, :inc)"
            ),
            {"id": snap2, "pid": parcel_id, "tract": "08031006202", "ds": "acs5", "yr": 2023, "pop": 5500, "inc": 72000},
        )
        db.commit()

        resp = client.get(f"/api/v1/parcels/{parcel_id}/demographics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["snapshots"]) == 2
        assert data["snapshots"][0]["year"] == 2020
        assert data["snapshots"][1]["year"] == 2023
        assert data["snapshots"][1]["median_household_income"] == 72000
