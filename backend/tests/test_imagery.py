"""Tests for the imagery service and API endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ── Imagery service unit tests ─────────────────────────────────────────────────


def _insert_parcel(db: Session, parcel_id: uuid.UUID, addr: str = "Test St") -> None:
    """Insert a minimal parcel row using raw SQL (no PostGIS needed)."""
    from sqlalchemy import text

    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, :addr, :lat, :lng, :pt)"
        ),
        {"id": str(parcel_id), "addr": addr, "lat": 39.7, "lng": -105.0, "pt": "POINT(-105.0 39.7)"},
    )
    db.commit()


def test_upsert_imagery_snapshot_insert(db: Session) -> None:
    """upsert_imagery_snapshot returns True on successful insert."""
    from app.services.imagery import upsert_imagery_snapshot

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    inserted = upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source="naip",
        capture_date=date(2020, 7, 15),
        stac_item_id="naip_2020_item",
        stac_collection="naip",
        cog_url="https://example.com/naip.tif",
        thumbnail_url="https://example.com/thumb.png",
        resolution_m=1.0,
        cloud_cover_pct=None,
    )

    assert inserted is True


def test_upsert_imagery_snapshot_dedup(db: Session) -> None:
    """upsert_imagery_snapshot updates cog_url on conflict and reports
    insert vs update via the return value."""
    from app.services.imagery import upsert_imagery_snapshot, get_imagery_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Dupe St")

    kwargs = dict(
        parcel_id=parcel_id,
        source="landsat",
        capture_date=date(1990, 6, 1),
        stac_item_id="landsat_1990_item",
        stac_collection="landsat-c2-l2",
        cog_url="https://example.com/landsat_old.tif",
        resolution_m=30.0,
    )

    first = upsert_imagery_snapshot(db, **kwargs)  # type: ignore[arg-type]
    assert first is True, "First call should report insert"

    # Second call with updated cog_url should refresh the row but report
    # False so callers can distinguish new snapshots from re-runs.
    kwargs["cog_url"] = "https://example.com/landsat_new.tif"
    second = upsert_imagery_snapshot(db, **kwargs)  # type: ignore[arg-type]
    assert second is False, "Second call should report update, not insert"

    # Verify the URL was updated, not duplicated
    snaps = get_imagery_snapshots(db, parcel_id)
    assert len(snaps) == 1, "Should still be one row, not two"
    assert snaps[0].cog_url == "https://example.com/landsat_new.tif"


def test_get_imagery_snapshots_returns_sorted(db: Session) -> None:
    """get_imagery_snapshots returns rows sorted by capture_date ascending."""
    from app.services.imagery import get_imagery_snapshots, upsert_imagery_snapshot

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Sort St")

    for year, item_id in [(2015, "item_2015"), (2000, "item_2000"), (2010, "item_2010")]:
        upsert_imagery_snapshot(
            db,
            parcel_id=parcel_id,
            source="naip",
            capture_date=date(year, 7, 1),
            stac_item_id=item_id,
            stac_collection="naip",
            cog_url=f"https://example.com/{item_id}.tif",
        )

    snapshots = get_imagery_snapshots(db, parcel_id)
    dates = [s.capture_date for s in snapshots]
    assert dates == sorted(dates), "Snapshots should be sorted by date"
    assert len(snapshots) == 3


def test_get_imagery_snapshots_source_filter(db: Session) -> None:
    """get_imagery_snapshots filters by source correctly."""
    from app.services.imagery import get_imagery_snapshots, upsert_imagery_snapshot

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Filter St")

    upsert_imagery_snapshot(
        db, parcel_id=parcel_id, source="naip", capture_date=date(2020, 6, 1),
        stac_item_id="naip_1", stac_collection="naip",
        cog_url="https://example.com/1.tif",
    )
    upsert_imagery_snapshot(
        db, parcel_id=parcel_id, source="landsat", capture_date=date(1990, 6, 1),
        stac_item_id="ls_1", stac_collection="landsat-c2-l2",
        cog_url="https://example.com/2.tif",
    )

    naip_only = get_imagery_snapshots(db, parcel_id, source="naip")
    assert len(naip_only) == 1
    assert naip_only[0].source == "naip"


# ── Timeline request API tests ─────────────────────────────────────────────────


def test_trigger_timeline_404_unknown_parcel(client: TestClient) -> None:
    """Triggering a timeline for a non-existent parcel returns 404."""
    unknown_id = uuid.uuid4()
    resp = client.post(f"/api/v1/parcels/{unknown_id}/timeline")
    assert resp.status_code == 404


def test_get_timeline_request_404_unknown(client: TestClient) -> None:
    """Fetching an unknown timeline request returns 404."""
    resp = client.get(f"/api/v1/timeline-requests/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_imagery_404_unknown_parcel(client: TestClient) -> None:
    """Fetching imagery for a non-existent parcel returns 404."""
    resp = client.get(f"/api/v1/parcels/{uuid.uuid4()}/imagery")
    assert resp.status_code == 404


def test_list_imagery_empty_returns_empty_list(client: TestClient, db: Session) -> None:
    """Fetching imagery for a parcel with no snapshots returns empty list."""
    from sqlalchemy import text

    parcel_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, :addr, :lat, :lng, :pt)"
        ),
        {"id": str(parcel_id), "addr": "Empty Ave", "lat": 39.0, "lng": -104.0, "pt": "POINT(-104.0 39.0)"},
    )
    db.commit()

    # Mock the sign URL calls (list_imagery is async and signs URLs)
    with patch("app.api.v1.imagery.stac_service.sign_pc_url", new_callable=AsyncMock) as mock_sign:
        mock_sign.side_effect = lambda url: url  # identity
        resp = client.get(f"/api/v1/parcels/{parcel_id}/imagery")

    assert resp.status_code == 200
    data = resp.json()
    assert data["parcel_id"] == str(parcel_id)
    assert data["snapshots"] == []
