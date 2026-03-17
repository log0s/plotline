"""Tests for GET /api/v1/parcels/{parcel_id} and parcel deduplication logic."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.geocoder import GeocodeResult

# ── Shared fixtures ───────────────────────────────────────────────────────────

GEOCODE_DOWNTOWN_DENVER = GeocodeResult(
    normalized_address="1437 BANNOCK ST, DENVER, CO, 80202",
    latitude=39.7391,
    longitude=-104.9847,
    census_tract_id="08031000200",
    county="Denver",
    state_fips="08",
)

GEOCODE_NEARBY = GeocodeResult(
    # 30 m away from downtown Denver fixture — should deduplicate
    normalized_address="1435 BANNOCK ST, DENVER, CO, 80202",
    latitude=39.73913,  # ~3m N
    longitude=-104.98472,
    census_tract_id="08031000200",
    county="Denver",
    state_fips="08",
)

GEOCODE_FAR = GeocodeResult(
    # ~3 km away — should NOT deduplicate
    normalized_address="1600 GLENARM PL, DENVER, CO, 80202",
    latitude=39.7425,
    longitude=-104.9901,
    census_tract_id="08031001300",
    county="Denver",
    state_fips="08",
)


def _make_parcel_mock(geocode: GeocodeResult) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.address = geocode.normalized_address
    p.normalized_address = geocode.normalized_address
    p.latitude = geocode.latitude
    p.longitude = geocode.longitude
    p.census_tract_id = geocode.census_tract_id
    p.county = geocode.county
    p.state_fips = geocode.state_fips
    return p


# ── GET /api/v1/parcels/{parcel_id} ──────────────────────────────────────────


def test_get_parcel_not_found(client: TestClient) -> None:
    """Returns 404 for an unknown UUID."""
    unknown_id = uuid.uuid4()

    # Patch the SQLAlchemy query chain so it returns None (no matching parcel)
    mock_chain = MagicMock()
    mock_chain.filter.return_value.first.return_value = None

    with patch("app.api.v1.parcels.Parcel") as _:
        # Override the session.query call inside the dependency
        with patch("sqlalchemy.orm.Session.query", return_value=mock_chain):
            response = client.get(f"/api/v1/parcels/{unknown_id}")

    assert response.status_code == 404
    assert str(unknown_id) in response.json()["detail"]


def test_get_parcel_invalid_uuid(client: TestClient) -> None:
    """Returns 422 for a malformed UUID path parameter."""
    response = client.get("/api/v1/parcels/not-a-uuid")
    assert response.status_code == 422


# ── Deduplication logic ───────────────────────────────────────────────────────


def test_dedup_returns_existing_parcel_when_within_radius() -> None:
    """get_or_create_parcel returns (existing, False) when a parcel is within 50 m."""
    from app.config import get_settings
    from app.services.parcels import get_or_create_parcel

    settings = get_settings()
    existing_mock = _make_parcel_mock(GEOCODE_DOWNTOWN_DENVER)
    mock_db = MagicMock()

    with patch(
        "app.services.parcels.find_nearby_parcel",
        return_value=existing_mock,
    ):
        parcel, is_new = get_or_create_parcel(
            db=mock_db,
            address="1437 Bannock St, Denver CO",
            geocode_result=GEOCODE_DOWNTOWN_DENVER,
            settings=settings,
        )

    assert is_new is False
    assert parcel.id == existing_mock.id
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_dedup_creates_new_parcel_when_beyond_radius() -> None:
    """get_or_create_parcel inserts a new row when no nearby parcel exists."""
    from app.config import get_settings
    from app.services.parcels import get_or_create_parcel

    settings = get_settings()
    mock_db = MagicMock()

    # Simulate a DB refresh by making the mock parcel get an id after commit
    created_parcel = _make_parcel_mock(GEOCODE_FAR)

    def fake_refresh(parcel):
        parcel.id = created_parcel.id

    mock_db.refresh.side_effect = fake_refresh

    with patch("app.services.parcels.find_nearby_parcel", return_value=None):
        with patch("app.services.parcels.Parcel") as MockParcel:
            MockParcel.return_value = created_parcel
            parcel, is_new = get_or_create_parcel(
                db=mock_db,
                address="1600 Glenarm Pl, Denver CO",
                geocode_result=GEOCODE_FAR,
                settings=settings,
            )

    assert is_new is True
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_dedup_radius_config_is_respected() -> None:
    """find_nearby_parcel is called with the configured radius from settings."""
    from app.config import get_settings
    from app.services.parcels import get_or_create_parcel

    settings = get_settings()
    mock_db = MagicMock()

    with patch("app.services.parcels.find_nearby_parcel", return_value=None) as mock_find:
        with patch("app.services.parcels.Parcel"):
            get_or_create_parcel(
                db=mock_db,
                address="1437 Bannock St, Denver CO",
                geocode_result=GEOCODE_DOWNTOWN_DENVER,
                settings=settings,
            )

    mock_find.assert_called_once()
    call_kwargs = mock_find.call_args
    assert call_kwargs.kwargs["radius_meters"] == settings.parcel_dedup_radius_meters
