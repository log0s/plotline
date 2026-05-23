"""Tests for POST /api/v1/geocode and the geocoder service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.geocoder import (
    AddressNotFoundError,
    GeocodeResult,
    GeocoderUnavailableError,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_GEOCODE_RESULT = GeocodeResult(
    normalized_address="1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
    latitude=38.8977,
    longitude=-77.0365,
    census_tract_id="11001006202",
    county="District of Columbia",
    state_fips="11",
)

SAMPLE_PARCEL_ID = uuid.uuid4()


def make_mock_parcel(is_new: bool = True) -> tuple[MagicMock, bool]:
    """Build a mock Parcel ORM object."""
    parcel = MagicMock()
    parcel.id = SAMPLE_PARCEL_ID
    parcel.address = "1600 Pennsylvania Ave NW, Washington DC"
    parcel.normalized_address = SAMPLE_GEOCODE_RESULT.normalized_address
    parcel.latitude = SAMPLE_GEOCODE_RESULT.latitude
    parcel.longitude = SAMPLE_GEOCODE_RESULT.longitude
    parcel.census_tract_id = SAMPLE_GEOCODE_RESULT.census_tract_id
    return parcel, is_new


# ── Endpoint tests ────────────────────────────────────────────────────────────


def _mock_timeline_request() -> MagicMock:
    """Build a mock TimelineRequest with a stable ID."""
    req = MagicMock()
    req.id = uuid.uuid4()
    req.status = "queued"
    return req


def test_geocode_success(client: TestClient) -> None:
    """A valid address returns 200 with parcel data including timeline_request_id."""
    mock_parcel, _ = make_mock_parcel(is_new=True)
    mock_req = _mock_timeline_request()

    with (
        patch(
            "app.api.v1.geocode.geocoder_service.geocode_address",
            new_callable=AsyncMock,
            return_value=SAMPLE_GEOCODE_RESULT,
        ),
        patch(
            "app.api.v1.geocode.parcels_service.get_or_create_parcel",
            return_value=(mock_parcel, True),
        ),
        patch(
            "app.api.v1.geocode.imagery_service.get_or_create_timeline_request",
            return_value=(mock_req, True),
        ),
        patch("app.tasks.timeline.fetch_imagery_timeline") as mock_task,
    ):
        mock_task.delay = MagicMock()
        response = client.post(
            "/api/v1/geocode",
            json={"address": "1600 Pennsylvania Ave NW, Washington DC"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["parcel_id"] == str(SAMPLE_PARCEL_ID)
    assert body["latitude"] == pytest.approx(38.8977, rel=1e-3)
    assert body["longitude"] == pytest.approx(-77.0365, rel=1e-3)
    assert body["census_tract"] == "11001006202"
    assert body["is_new"] is True
    assert body["timeline_request_id"] == str(mock_req.id)


def test_geocode_dedup_returns_existing(client: TestClient) -> None:
    """When a nearby parcel exists, is_new is False."""
    mock_parcel, _ = make_mock_parcel(is_new=False)
    mock_req = _mock_timeline_request()
    mock_req.status = "complete"

    with (
        patch(
            "app.api.v1.geocode.geocoder_service.geocode_address",
            new_callable=AsyncMock,
            return_value=SAMPLE_GEOCODE_RESULT,
        ),
        patch(
            "app.api.v1.geocode.parcels_service.get_or_create_parcel",
            return_value=(mock_parcel, False),
        ),
        patch(
            "app.api.v1.geocode.imagery_service.get_or_create_timeline_request",
            return_value=(mock_req, False),
        ),
    ):
        response = client.post(
            "/api/v1/geocode",
            json={"address": "1600 Pennsylvania Ave NW, Washington DC"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_new"] is False
    assert body["timeline_request_id"] == str(mock_req.id)


def test_geocode_address_not_found_returns_422(client: TestClient) -> None:
    """An address that can't be geocoded returns 422."""
    with (
        patch(
            "app.api.v1.geocode.geocoder_service.geocode_address",
            new_callable=AsyncMock,
            side_effect=AddressNotFoundError("No match found"),
        ),
    ):
        response = client.post(
            "/api/v1/geocode",
            json={"address": "999 Fake Street, Nowhere, ZZ 00000"},
        )

    assert response.status_code == 422
    assert "could not match" in response.json()["detail"].lower()


def test_geocode_upstream_unavailable_returns_502(client: TestClient) -> None:
    """A Census Geocoder network error returns 502."""
    with (
        patch(
            "app.api.v1.geocode.geocoder_service.geocode_address",
            new_callable=AsyncMock,
            side_effect=GeocoderUnavailableError("Connection refused"),
        ),
    ):
        response = client.post(
            "/api/v1/geocode",
            json={"address": "1600 Pennsylvania Ave NW, Washington DC"},
        )

    assert response.status_code == 502
    assert "unavailable" in response.json()["detail"].lower()


def test_geocode_empty_address_returns_422(client: TestClient) -> None:
    """An empty address fails Pydantic validation with 422."""
    response = client.post("/api/v1/geocode", json={"address": ""})
    assert response.status_code == 422


def test_geocode_missing_address_field_returns_422(client: TestClient) -> None:
    """Missing address field fails with 422."""
    response = client.post("/api/v1/geocode", json={})
    assert response.status_code == 422


# ── Service unit tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_geocoder_service_parses_census_response() -> None:
    """geocode_address() correctly parses a real Census API response structure."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    mock_response = {
        "result": {
            "addressMatches": [
                {
                    "matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
                    "coordinates": {"x": -77.0365, "y": 38.8977},
                    "geographies": {},
                }
            ]
        }
    }

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        result = await geocode_address("1600 Pennsylvania Ave NW", settings)

    assert result.latitude == pytest.approx(38.8977, rel=1e-4)
    assert result.longitude == pytest.approx(-77.0365, rel=1e-4)
    assert "PENNSYLVANIA" in result.normalized_address


@pytest.mark.asyncio
async def test_geocoder_service_raises_on_empty_matches() -> None:
    """geocode_address() raises AddressNotFoundError when API returns no matches."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    mock_response = {"result": {"addressMatches": []}}

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        with pytest.raises(AddressNotFoundError):
            await geocode_address("999 Fake St, Nowhere", settings)


@pytest.mark.asyncio
async def test_geocoder_service_raises_on_timeout() -> None:
    """geocode_address() raises GeocoderUnavailableError on timeout."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        with pytest.raises(GeocoderUnavailableError, match="timed out"):
            await geocode_address("1600 Pennsylvania Ave NW", settings)


@pytest.mark.asyncio
async def test_geocoder_service_parses_census_tract() -> None:
    """geocode_address() extracts census tract FIPS from geographies."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    mock_response = {
        "result": {
            "addressMatches": [
                {
                    "matchedAddress": "123 MAIN ST, DENVER, CO, 80202",
                    "coordinates": {"x": -104.9903, "y": 39.7392},
                    "geographies": {
                        "Census Tracts": [{"STATE": "08", "COUNTY": "031", "TRACT": "006202"}],
                        "Counties": [{"BASENAME": "Denver"}],
                    },
                }
            ]
        }
    }

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        result = await geocode_address("123 Main St, Denver CO", settings)

    assert result.census_tract_id == "08031006202"
    assert result.county == "Denver"
    assert result.state_fips == "08"


@pytest.mark.asyncio
async def test_geocoder_raises_on_http_error() -> None:
    """Non-timeout HTTP errors should raise GeocoderUnavailableError."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(GeocoderUnavailableError, match="HTTP 500"):
            await geocode_address("123 Main St", settings)


@pytest.mark.asyncio
async def test_geocoder_raises_on_network_error() -> None:
    """Network errors should raise GeocoderUnavailableError."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with pytest.raises(GeocoderUnavailableError, match="Network error"):
            await geocode_address("123 Main St", settings)


# ── Reverse geocoder ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reverse_geocode_success() -> None:
    """reverse_geocode() returns census metadata for known coordinates."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import reverse_geocode

    settings = get_settings()

    mock_response = {
        "result": {
            "geographies": {
                "Census Tracts": [{"STATE": "08", "COUNTY": "031", "TRACT": "006202"}],
                "Counties": [{"BASENAME": "Denver"}],
            }
        }
    }

    with respx.mock:
        respx.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        result = await reverse_geocode(
            latitude=39.7392,
            longitude=-104.9903,
            address="123 Main St, Denver CO",
            settings=settings,
        )

    assert result.latitude == 39.7392
    assert result.longitude == -104.9903
    assert result.census_tract_id == "08031006202"
    assert result.county == "Denver"


@pytest.mark.asyncio
async def test_reverse_geocode_timeout_retries() -> None:
    """reverse_geocode() retries on timeout and eventually raises."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import reverse_geocode

    settings = get_settings()

    with respx.mock:
        respx.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        with pytest.raises(GeocoderUnavailableError, match="timed out"):
            await reverse_geocode(
                latitude=39.7392,
                longitude=-104.9903,
                address="123 Main St",
                settings=settings,
            )


@pytest.mark.asyncio
async def test_reverse_geocode_http_error() -> None:
    """reverse_geocode() raises on HTTP status errors."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import reverse_geocode

    settings = get_settings()

    with respx.mock:
        respx.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )
        with pytest.raises(GeocoderUnavailableError):
            await reverse_geocode(
                latitude=39.7392,
                longitude=-104.9903,
                address="123 Main St",
                settings=settings,
            )


@pytest.mark.asyncio
async def test_reverse_geocode_no_tracts_returns_none_fields() -> None:
    """reverse_geocode() with empty geographies returns None for census fields."""
    import httpx
    import respx

    from app.config import get_settings
    from app.services.geocoder import reverse_geocode

    settings = get_settings()

    mock_response = {"result": {"geographies": {}}}

    with respx.mock:
        respx.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        result = await reverse_geocode(
            latitude=39.7392,
            longitude=-104.9903,
            address="123 Main St",
            settings=settings,
        )

    assert result.census_tract_id is None
    assert result.county is None
