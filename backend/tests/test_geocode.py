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


def test_geocode_success(client: TestClient) -> None:
    """A valid address returns 200 with parcel data."""
    mock_parcel, _ = make_mock_parcel(is_new=True)

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
    ):
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


def test_geocode_dedup_returns_existing(client: TestClient) -> None:
    """When a nearby parcel exists, is_new is False."""
    mock_parcel, _ = make_mock_parcel(is_new=False)

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
    ):
        response = client.post(
            "/api/v1/geocode",
            json={"address": "1600 Pennsylvania Ave NW, Washington DC"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_new"] is False


def test_geocode_address_not_found_returns_422(client: TestClient) -> None:
    """An address that can't be geocoded returns 422."""
    with patch(
        "app.api.v1.geocode.geocoder_service.geocode_address",
        new_callable=AsyncMock,
        side_effect=AddressNotFoundError("No match found"),
    ):
        response = client.post(
            "/api/v1/geocode",
            json={"address": "999 Fake Street, Nowhere, ZZ 00000"},
        )

    assert response.status_code == 422
    assert "geocode" in response.json()["detail"].lower()


def test_geocode_upstream_unavailable_returns_502(client: TestClient) -> None:
    """A Census Geocoder network error returns 502."""
    with patch(
        "app.api.v1.geocode.geocoder_service.geocode_address",
        new_callable=AsyncMock,
        side_effect=GeocoderUnavailableError("Connection refused"),
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
    import respx
    import httpx

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
    import respx
    import httpx

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
    import respx
    import httpx

    from app.config import get_settings
    from app.services.geocoder import geocode_address

    settings = get_settings()

    with respx.mock:
        respx.get(settings.census_geocoder_url).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        with pytest.raises(GeocoderUnavailableError, match="timed out"):
            await geocode_address("1600 Pennsylvania Ave NW", settings)
