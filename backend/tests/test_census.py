"""Tests for Census API client, FIPS parsing, demographics service, and endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.census import (
    _ACS5_VARIABLES,
    CensusFetcher,
    CensusMissingKeyError,
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

    def test_other_acs_annotation_values(self) -> None:
        # ACS uses several large negative annotation values, not just one.
        assert _to_number("-999999999") is None
        assert _to_number("-888888888") is None
        assert _to_number("-555555555") is None
        assert _to_number("-222222222") is None
        assert _to_number("-666666666.0") is None

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
                "B01003_001E",
                "B19013_001E",
                "B25077_001E",
                "B25035_001E",
                "B25003_001E",
                "B25003_002E",
                "B25003_003E",
                "B01002_001E",
                "B25064_001E",
                "state",
                "county",
                "tract",
            ],
            [
                "4523",
                "52340",
                "215000",
                "1978",
                "1764",
                "1102",
                "662",
                "34.2",
                "1150",
                "08",
                "031",
                "006202",
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
    async def test_fetch_decennial_unsupported_year(self) -> None:
        """Year without config should return empty dict."""
        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        result = await fetcher.fetch_decennial(1980, "08", "031", "006202")
        assert result == {}
        fetcher.client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_raises_on_http_error(self) -> None:
        """Network errors in _request should raise CensusApiError."""
        from app.services.census import CensusApiError

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(CensusApiError, match="HTTP error"):
            await fetcher.fetch_acs5(2023, "08", "031", "006202")

    @pytest.mark.asyncio
    async def test_request_raises_on_unexpected_status(self) -> None:
        """Non-200/204/404 responses should raise CensusApiError."""
        from app.services.census import CensusApiError

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(CensusApiError, match="500"):
            await fetcher.fetch_acs5(2023, "08", "031", "006202")

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self) -> None:
        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        await fetcher.close()
        fetcher.client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_without_key_raises(self) -> None:
        with pytest.raises(CensusMissingKeyError, match="CENSUS_API_KEY"):
            CensusFetcher()

    @pytest.mark.asyncio
    async def test_302_missing_key_redirect(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {
            "location": "https://api.census.gov/data/missing_key.html",
            "x-datawebapi-keyerror": "1",
        }

        fetcher = CensusFetcher(api_key="expired-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(CensusMissingKeyError, match="missing or invalid"):
            await fetcher.fetch_acs5(2023, "08", "031", "006202")

    @pytest.mark.asyncio
    async def test_sentinel_value_handled(self) -> None:
        """Census API returns -666666666 for unavailable data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [
                "B01003_001E",
                "B19013_001E",
                "B25077_001E",
                "B25035_001E",
                "B25003_001E",
                "B25003_002E",
                "B25003_003E",
                "B01002_001E",
                "B25064_001E",
                "state",
                "county",
                "tract",
            ],
            [
                "4523",
                "-666666666",
                "-666666666",
                "1978",
                "1764",
                "1102",
                "662",
                "34.2",
                "-666666666",
                "08",
                "031",
                "006202",
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


# ── Housing pipeline (fetch → persist) ───────────────────────────────────────

# Captured verbatim from the live API: 2023 ACS5, tract 36061007600.
# Internally consistent the way real responses are — owner + renter ==
# occupied (345 + 1080 == 1425) and occupied + vacant == total
# (1425 + 201 == 1626) — which hand-built fixtures rarely are.
_LIVE_ACS5_2023 = {
    "B01003_001E": "2455",
    "B19013_001E": "164188",
    "B25077_001E": "2000001",
    "B25035_001E": "1938",
    "B25001_001E": "1626",
    "B25002_003E": "201",
    "B25003_001E": "1425",
    "B25003_002E": "345",
    "B25003_003E": "1080",
    "B01002_001E": "34.4",
    "B25064_001E": "2840",
}


def _acs5_api_response() -> list[list[str]]:
    """Build a response covering exactly the variables we currently request.

    Driven off _ACS5_VARIABLES so the fixture cannot drift from the real
    request the way a hardcoded header row can.
    """
    variables = list(_ACS5_VARIABLES.keys())
    missing = [v for v in variables if v not in _LIVE_ACS5_2023]
    assert not missing, f"No captured value for {missing}; refresh from the live API"
    return [
        [*variables, "state", "county", "tract"],
        [*(_LIVE_ACS5_2023[v] for v in variables), "36", "061", "007600"],
    ]


class TestHousingPipeline:
    """The path HousingChart depends on: fetch_acs5 → upsert → persisted row."""

    @pytest.mark.asyncio
    async def test_acs5_row_satisfies_housing_chart_filter(self, db) -> None:
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point, census_tract_id) "
                "VALUES (:id, :addr, :lat, :lng, :pt, :tract)"
            ),
            {
                "id": parcel_id,
                "addr": "350 5th Ave",
                "lat": 40.748,
                "lng": -73.985,
                "pt": "POINT(-73.985 40.748)",
                "tract": "36061007600",
            },
        )
        db.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _acs5_api_response()

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(return_value=mock_response)

        data = await fetcher.fetch_acs5(2023, "36", "061", "007600")

        # The total-units variable must actually be on the wire — its absence
        # is what left every ACS row without a total.
        requested = fetcher.client.get.call_args.kwargs["params"]["get"]
        assert "B25001_001E" in requested

        pid = uuid.UUID(parcel_id)
        upsert_census_snapshot(
            db,
            parcel_id=pid,
            tract_fips="36061007600",
            dataset="acs5",
            year=2023,
            data=data,
            raw_data=data,
        )

        (row,) = get_census_snapshots(db, pid)

        # Exactly the combination HousingChart filters on.
        assert row.total_housing_units is not None
        assert row.owner_occupied_units is not None or row.renter_occupied_units is not None

        assert row.total_housing_units == 1626
        assert row.occupied_housing_units == 1425
        assert row.owner_occupied_units == 345
        assert row.renter_occupied_units == 1080

        # 201 vacant / 1626 total — previously uncomputable, so always NULL.
        assert row.vacancy_rate is not None
        assert abs(row.vacancy_rate - 0.1236) < 0.001

    @pytest.mark.asyncio
    async def test_unavailable_variable_drops_field_instead_of_year(self) -> None:
        """A vintage missing one variable must not cost us the whole year."""
        rejected = MagicMock()
        rejected.status_code = 400
        rejected.text = "error: unknown variable 'B25002_003E'"

        ok = MagicMock()
        ok.status_code = 200
        variables = [v for v in _ACS5_VARIABLES if v != "B25002_003E"]
        ok.json.return_value = [
            [*variables, "state", "county", "tract"],
            [*(_LIVE_ACS5_2023[v] for v in variables), "36", "061", "007600"],
        ]

        fetcher = CensusFetcher(api_key="test-key")
        fetcher.client = AsyncMock()
        fetcher.client.get = AsyncMock(side_effect=[rejected, ok])

        data = await fetcher.fetch_acs5(2009, "36", "061", "007600")

        assert "vacant_housing_units" not in data
        assert data["total_housing_units"] == 1626
        assert data["total_population"] == 2455

        retried = fetcher.client.get.call_args.kwargs["params"]["get"]
        assert "B25002_003E" not in retried

    def test_vacancy_rate_derived_when_vacant_count_absent(self, db) -> None:
        """Older vintages may lack B25002_003E; vacancy still derives."""
        from sqlalchemy import text

        parcel_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point, census_tract_id) "
                "VALUES (:id, :addr, :lat, :lng, :pt, :tract)"
            ),
            {
                "id": parcel_id,
                "addr": "350 5th Ave",
                "lat": 40.748,
                "lng": -73.985,
                "pt": "POINT(-73.985 40.748)",
                "tract": "36061007600",
            },
        )
        db.commit()

        pid = uuid.UUID(parcel_id)
        upsert_census_snapshot(
            db,
            parcel_id=pid,
            tract_fips="36061007600",
            dataset="acs5",
            year=2009,
            data={
                "total_population": 2455,
                "total_housing_units": 1626,
                "occupied_housing_units": 1425,
                "owner_occupied_units": 345,
                "renter_occupied_units": 1080,
            },
        )

        (row,) = get_census_snapshots(db, pid)
        assert row.vacancy_rate is not None
        assert abs(row.vacancy_rate - 0.1236) < 0.001


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
            {
                "id": parcel_id,
                "addr": "456 Oak Ave",
                "lat": 39.7,
                "lng": -104.9,
                "pt": "POINT(-104.9 39.7)",
            },
        )
        db.commit()

        pid = uuid.UUID(parcel_id)
        data = {"total_population": 3000, "total_housing_units": 1200}

        upsert_census_snapshot(
            db, parcel_id=pid, tract_fips="08031006202", dataset="decennial", year=2020, data=data
        )
        upsert_census_snapshot(
            db,
            parcel_id=pid,
            tract_fips="08031006202",
            dataset="decennial",
            year=2020,
            data={"total_population": 3100, "total_housing_units": 1250},
        )

        rows = get_census_snapshots(db, pid)
        assert len(rows) == 1
        assert rows[0].total_population == 3100  # Updated, not duplicated


# ── Subtitle generation ───────────────────────────────────────────────────────


class TestComputeSubtitles:
    def test_population_growth(self) -> None:
        snapshots = [
            CensusSnapshotRow(
                id=uuid.uuid4(),
                parcel_id=uuid.uuid4(),
                tract_fips="08031006202",
                dataset="decennial",
                year=1990,
                total_population=2000,
            ),
            CensusSnapshotRow(
                id=uuid.uuid4(),
                parcel_id=uuid.uuid4(),
                tract_fips="08031006202",
                dataset="acs5",
                year=2023,
                total_population=8000,
                median_household_income=65000,
                median_home_value=350000,
                occupied_housing_units=3000,
                owner_occupied_units=1800,
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
                id=uuid.uuid4(),
                parcel_id=uuid.uuid4(),
                tract_fips="08031006202",
                dataset="acs5",
                year=2009,
                median_home_value=200000,
            ),
            CensusSnapshotRow(
                id=uuid.uuid4(),
                parcel_id=uuid.uuid4(),
                tract_fips="08031006202",
                dataset="acs5",
                year=2023,
                median_home_value=450000,
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
            {
                "id": snap1,
                "pid": parcel_id,
                "tract": "08031006202",
                "ds": "decennial",
                "yr": 2020,
                "pop": 5000,
            },
        )
        db.execute(
            text(
                "INSERT INTO census_snapshots (id, parcel_id, tract_fips, dataset, year, total_population, median_household_income) "
                "VALUES (:id, :pid, :tract, :ds, :yr, :pop, :inc)"
            ),
            {
                "id": snap2,
                "pid": parcel_id,
                "tract": "08031006202",
                "ds": "acs5",
                "yr": 2023,
                "pop": 5500,
                "inc": 72000,
            },
        )
        db.commit()

        resp = client.get(f"/api/v1/parcels/{parcel_id}/demographics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["snapshots"]) == 2
        assert data["snapshots"][0]["year"] == 2020
        assert data["snapshots"][1]["year"] == 2023
        assert data["snapshots"][1]["median_household_income"] == 72000
