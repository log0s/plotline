"""Tests for the imagery service and API endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.orm import Session, sessionmaker

# ── Imagery service unit tests ─────────────────────────────────────────────────


def _insert_parcel(db: Session, parcel_id: uuid.UUID, addr: str = "Test St") -> None:
    """Insert a minimal parcel row using raw SQL (no PostGIS needed)."""
    from sqlalchemy import text

    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, :addr, :lat, :lng, :pt)"
        ),
        {
            "id": str(parcel_id),
            "addr": addr,
            "lat": 39.7,
            "lng": -105.0,
            "pt": "POINT(-105.0 39.7)",
        },
    )
    db.commit()


def test_get_or_create_reuses_inflight_request(db: Session) -> None:
    """A queued/processing request is reused — no duplicate pipeline."""
    from app.services.imagery import get_or_create_timeline_request

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    first, created_first = get_or_create_timeline_request(db, parcel_id)
    second, created_second = get_or_create_timeline_request(db, parcel_id)

    assert created_first is True
    assert created_second is False
    assert second.id == first.id


def test_get_or_create_reuses_complete_request(db: Session) -> None:
    from app.services.imagery import (
        get_or_create_timeline_request,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    first, _ = get_or_create_timeline_request(db, parcel_id)
    update_timeline_request_status(db, first, "complete")

    second, created = get_or_create_timeline_request(db, parcel_id)
    assert created is False
    assert second.id == first.id


def test_get_or_create_replaces_failed_request(db: Session) -> None:
    from app.services.imagery import (
        get_or_create_timeline_request,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    first, _ = get_or_create_timeline_request(db, parcel_id)
    update_timeline_request_status(db, first, "failed", error_message="boom")

    second, created = get_or_create_timeline_request(db, parcel_id)
    assert created is True
    assert second.id != first.id


def test_get_or_create_takes_over_stale_inflight(db: Session) -> None:
    """An in-flight request untouched past the hard time limit is replaced."""
    from sqlalchemy import text

    from app.models.parcels import TimelineRequest
    from app.services.imagery import get_or_create_timeline_request

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    first, _ = get_or_create_timeline_request(db, parcel_id)
    db.execute(
        text("UPDATE timeline_requests SET updated_at = '2020-01-01 00:00:00' WHERE id = :id"),
        {"id": first.id.hex},
    )
    db.commit()
    db.expire_all()

    second, created = get_or_create_timeline_request(db, parcel_id)
    assert created is True
    assert second.id != first.id

    db.expire_all()
    stale = db.get(TimelineRequest, first.id)
    assert stale is not None
    assert stale.status == "failed"


def test_dispatch_timeline_task_marks_failed_when_broker_down(db: Session) -> None:
    """A broker outage at dispatch must not leave the request 'queued'
    forever — the client would poll it indefinitely."""
    from kombu.exceptions import OperationalError

    from app.services.imagery import (
        dispatch_timeline_task,
        get_or_create_timeline_request,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    request, _ = get_or_create_timeline_request(db, parcel_id)

    with patch("app.tasks.timeline.fetch_imagery_timeline") as mock_task:
        mock_task.delay.side_effect = OperationalError("broker down")
        queued = dispatch_timeline_task(db, request)

    assert queued is False
    assert request.status == "failed"


def test_create_request_tasks_idempotent(db: Session) -> None:
    """Re-running the orchestrator (Celery redelivery) must not duplicate
    task rows — existing rows are reset to queued instead."""
    from sqlalchemy import text

    from app.services.imagery import (
        create_request_tasks,
        get_or_create_timeline_request,
        update_request_task,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    request, _ = get_or_create_timeline_request(db, parcel_id)

    tasks = create_request_tasks(db, request.id, ["naip", "landsat"])
    update_request_task(db, tasks[0], "failed", error_message="boom")

    tasks_again = create_request_tasks(db, request.id, ["naip", "landsat"])

    count = db.execute(
        text("SELECT COUNT(*) FROM timeline_request_tasks WHERE timeline_request_id = :rid"),
        {"rid": request.id.hex},
    ).scalar()
    assert count == 2
    assert all(t.status == "queued" for t in tasks_again)
    assert all(t.error_message is None for t in tasks_again)


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
    from app.services.imagery import get_imagery_snapshots, upsert_imagery_snapshot

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
        db,
        parcel_id=parcel_id,
        source="naip",
        capture_date=date(2020, 6, 1),
        stac_item_id="naip_1",
        stac_collection="naip",
        cog_url="https://example.com/1.tif",
    )
    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source="landsat",
        capture_date=date(1990, 6, 1),
        stac_item_id="ls_1",
        stac_collection="landsat-c2-l2",
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
        {
            "id": str(parcel_id),
            "addr": "Empty Ave",
            "lat": 39.0,
            "lng": -104.0,
            "pt": "POINT(-104.0 39.0)",
        },
    )
    db.commit()

    # Mock the sign URL calls (list_imagery is async and signs URLs)
    with patch("app.api.v1.imagery.stac_service.sign_pc_url", new_callable=AsyncMock) as mock_sign:
        mock_sign.side_effect = lambda url, **_kwargs: url  # identity
        resp = client.get(f"/api/v1/parcels/{parcel_id}/imagery")

    assert resp.status_code == 200
    data = resp.json()
    assert data["parcel_id"] == str(parcel_id)
    assert data["snapshots"] == []


def test_list_imagery_caps_rendered_preview_thumbnails(client: TestClient, db: Session) -> None:
    """rendered_preview thumbnails come back size-capped and unsigned.

    Uncapped, preview.png renders the full scene (~1 MB) for a 64px card,
    and signing one is a wasted round-trip — the SAS endpoint returns it
    unchanged.
    """
    from app.services.imagery import upsert_imagery_snapshot

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Preview St")
    preview = (
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png"
        "?collection=naip&item=naip_2020_item&assets=image&format=png"
    )
    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source="naip",
        capture_date=date(2020, 7, 15),
        stac_item_id="naip_2020_item",
        stac_collection="naip",
        cog_url="https://example.com/naip.tif",
        thumbnail_url=preview,
        resolution_m=1.0,
    )

    with patch("app.api.v1.imagery.stac_service.sign_pc_url", new_callable=AsyncMock) as mock_sign:
        mock_sign.side_effect = lambda url, **_kwargs: url
        resp = client.get(f"/api/v1/parcels/{parcel_id}/imagery")

    assert resp.status_code == 200
    thumb = resp.json()["snapshots"][0]["thumbnail_url"]
    assert "max_size=128" in thumb
    assert preview not in [call.args[0] for call in mock_sign.call_args_list]


# ── Backfill eligibility ──────────────────────────────────────────────────────


def _backfill_setup(
    db: Session, property_status: str, age_hours: float = 24.0
) -> tuple[object, object]:
    """Insert a completed request whose property task has the given status.

    ``age_hours`` is how long ago the request was created — backfill is
    suppressed inside the cooldown window, so the default puts it safely
    outside.

    The parcel is a stand-in rather than an ORM load — the real model selects
    its PostGIS geometry column, which SQLite can't evaluate.
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.models.parcels import TimelineRequest, TimelineRequestTask

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "1437 Bannock St")

    # Inserted through the ORM so the UUID columns are bound the same way the
    # service's lookups bind them.
    req = TimelineRequest(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        status="complete",
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    db.add(req)
    for source, status in (("property", property_status), ("usgs_topo", "complete")):
        db.add(
            TimelineRequestTask(
                id=uuid.uuid4(),
                timeline_request_id=req.id,
                source=source,
                status=status,
                items_found=0,
            )
        )
    db.commit()

    parcel = SimpleNamespace(id=parcel_id, census_tract_id=None, county="Denver")
    return parcel, req


def test_backfill_retries_failed_property_task(db: Session) -> None:
    """A property task left failed by a county portal outage must be retried
    on the next visit — otherwise the outage is permanent for that parcel."""
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req = _backfill_setup(db, "failed")

    assert maybe_refetch_for_backfill(db, parcel, req) is not None


def test_backfill_suppressed_inside_the_cooldown(db: Session) -> None:
    """A failed source inside the cooldown window does not re-dispatch.

    Without this, every page view of a parcel with one persistently failing
    source re-runs the whole five-source pipeline.
    """
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req = _backfill_setup(db, "failed", age_hours=1.0)

    assert maybe_refetch_for_backfill(db, parcel, req) is None


def test_backfill_resumes_outside_the_cooldown(db: Session) -> None:
    """The same parcel becomes eligible again once the window has passed."""
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req = _backfill_setup(db, "failed", age_hours=7.0)

    assert maybe_refetch_for_backfill(db, parcel, req) is not None


def test_backfill_leaves_complete_property_task_alone(db: Session) -> None:
    """A genuine 'no records at this address' result is not refetched."""
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req = _backfill_setup(db, "complete")

    assert maybe_refetch_for_backfill(db, parcel, req) is None


# ── Snapshot reconciliation ───────────────────────────────────────────────────


def _persist(db: Session, parcel_id: uuid.UUID, source: str, item_id: str, day: str) -> None:
    from app.services.imagery import upsert_imagery_snapshot

    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source=source,
        capture_date=date.fromisoformat(day),
        stac_item_id=item_id,
        stac_collection=source,
        cog_url=f"https://example.com/{item_id}.tif",
    )


def _item_ids(db: Session, parcel_id: uuid.UUID, source: str) -> set[str]:
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT stac_item_id FROM imagery_snapshots WHERE parcel_id = :p AND source = :s"),
        {"p": str(parcel_id), "s": source},
    ).all()
    return {r.stac_item_id for r in rows}


def test_reconcile_replaces_a_revalidated_landsat_scene(db: Session) -> None:
    """The scenario the maintenance script claimed the upsert handled: a
    re-run picks a different scene for the same year."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "landsat", "LT05_A_1987", "1987-06-01")

    # Re-run: validation rejects A's bands and selects B for 1987
    _persist(db, parcel_id, "landsat", "LT05_B_1987", "1987-07-04")
    deleted = reconcile_source_snapshots(
        db, parcel_id, "landsat", [("LT05_B_1987", date(1987, 7, 4))]
    )

    assert deleted == 1
    assert _item_ids(db, parcel_id, "landsat") == {"LT05_B_1987"}


def test_reconcile_keeps_every_tile_of_a_naip_mosaic(db: Session) -> None:
    """NAIP's greedy selector returns several items for one year. Deleting
    on a one-row-per-year assumption would gut the mosaic."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    tiles = ["naip_2020_nw", "naip_2020_ne", "naip_2020_sw"]
    for tile in tiles:
        _persist(db, parcel_id, "naip", tile, "2020-08-01")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "naip",
        [(tile, date(2020, 8, 1)) for tile in tiles],
    )

    assert deleted == 0
    assert _item_ids(db, parcel_id, "naip") == set(tiles)


def test_reconcile_leaves_years_this_run_did_not_select(db: Session) -> None:
    """A chunk_by_year source skips years whose STAC search failed. Those
    years are absent from the selection but their data is still good."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "landsat", "LT05_1987", "1987-06-01")
    _persist(db, parcel_id, "landsat", "LC08_2015", "2015-06-01")

    # Only 2015 came back this run
    deleted = reconcile_source_snapshots(
        db, parcel_id, "landsat", [("LC08_2015", date(2015, 6, 1))]
    )

    assert deleted == 0
    assert _item_ids(db, parcel_id, "landsat") == {"LT05_1987", "LC08_2015"}


def test_reconcile_with_empty_selection_deletes_nothing(db: Session) -> None:
    """A search that returned nothing must not wipe the parcel."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "landsat", "LT05_1987", "1987-06-01")

    assert reconcile_source_snapshots(db, parcel_id, "landsat", []) == 0
    assert _item_ids(db, parcel_id, "landsat") == {"LT05_1987"}


def test_reconcile_scopes_deletion_to_one_source(db: Session) -> None:
    """A Landsat run must not touch the parcel's NAIP rows."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "naip", "naip_1987", "1987-08-01")
    _persist(db, parcel_id, "landsat", "LT05_A_1987", "1987-06-01")
    _persist(db, parcel_id, "landsat", "LT05_B_1987", "1987-07-04")

    reconcile_source_snapshots(db, parcel_id, "landsat", [("LT05_B_1987", date(1987, 7, 4))])

    assert _item_ids(db, parcel_id, "naip") == {"naip_1987"}
    assert _item_ids(db, parcel_id, "landsat") == {"LT05_B_1987"}


# ── Reconciliation scope: usgs_topo groups by decade, not year ───────────────


def test_reconcile_topo_replaces_a_sheet_from_the_same_decade(db: Session) -> None:
    """select_topo_items picks one sheet per decade, so a replacement can
    carry a different publication year. Year-scoping would miss it."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "usgs_topo", "tnm-1954-sheet", "1954-01-01")

    # Re-run selects a different 1950s sheet — same decade, different year
    _persist(db, parcel_id, "usgs_topo", "tnm-1957-sheet", "1957-01-01")
    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "usgs_topo",
        [("tnm-1957-sheet", date(1957, 1, 1))],
        scope="decade",
    )

    assert deleted == 1
    assert _item_ids(db, parcel_id, "usgs_topo") == {"tnm-1957-sheet"}


def test_reconcile_topo_leaves_decades_this_run_did_not_select(db: Session) -> None:
    """A TNM search that came back without the 1900s must not delete them."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "usgs_topo", "tnm-1906-sheet", "1906-01-01")
    _persist(db, parcel_id, "usgs_topo", "tnm-1965-sheet", "1965-01-01")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "usgs_topo",
        [("tnm-1965-sheet", date(1965, 1, 1))],
        scope="decade",
    )

    assert deleted == 0
    assert _item_ids(db, parcel_id, "usgs_topo") == {"tnm-1906-sheet", "tnm-1965-sheet"}


def test_reconcile_topo_empty_selection_deletes_nothing(db: Session) -> None:
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "usgs_topo", "tnm-1954-sheet", "1954-01-01")

    assert reconcile_source_snapshots(db, parcel_id, "usgs_topo", [], scope="decade") == 0
    assert _item_ids(db, parcel_id, "usgs_topo") == {"tnm-1954-sheet"}


def test_reconcile_topo_does_not_touch_other_sources(db: Session) -> None:
    """A decade-wide delete is broad — it must still stop at the source."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "landsat", "LT05_1957", "1957-06-01")
    _persist(db, parcel_id, "naip", "naip_1957", "1957-08-01")
    _persist(db, parcel_id, "usgs_topo", "tnm-1954-sheet", "1954-01-01")
    _persist(db, parcel_id, "usgs_topo", "tnm-1957-sheet", "1957-01-01")

    reconcile_source_snapshots(
        db,
        parcel_id,
        "usgs_topo",
        [("tnm-1957-sheet", date(1957, 1, 1))],
        scope="decade",
    )

    assert _item_ids(db, parcel_id, "usgs_topo") == {"tnm-1957-sheet"}
    assert _item_ids(db, parcel_id, "landsat") == {"LT05_1957"}
    assert _item_ids(db, parcel_id, "naip") == {"naip_1957"}


def test_reconcile_year_scope_would_miss_a_cross_year_topo_replacement(db: Session) -> None:
    """Guards the investigation's finding: scoping topo by year leaves the
    superseded sheet in place, which is why scope has to match the selector."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "usgs_topo", "tnm-1954-sheet", "1954-01-01")
    _persist(db, parcel_id, "usgs_topo", "tnm-1957-sheet", "1957-01-01")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "usgs_topo",
        [("tnm-1957-sheet", date(1957, 1, 1))],
        scope="year",
    )

    assert deleted == 0
    assert len(_item_ids(db, parcel_id, "usgs_topo")) == 2


def test_reconcile_sentinel_year_scope_collapses_the_whole_year(db: Session) -> None:
    """Sentinel-2 selects per year, so one pick supersedes every row of it.

    Delete-the-fix guard for the reconciliation half: under the old
    ``scope="quarter"`` the February row sat in a group this run never
    selected and survived — which is how Green Valley Ranch came to hold
    two rows for one quarter and four for one year (G3).
    """
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "sentinel2", "S2_2020Q1", "2020-02-10")
    _persist(db, parcel_id, "sentinel2", "S2_2020Q3_old", "2020-08-10")
    _persist(db, parcel_id, "sentinel2", "S2_2020Q3_new", "2020-09-02")
    _persist(db, parcel_id, "sentinel2", "S2_2021", "2021-09-02")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "sentinel2",
        [("S2_2020Q3_new", date(2020, 9, 2))],
        scope="year",
    )

    assert deleted == 2
    assert _item_ids(db, parcel_id, "sentinel2") == {"S2_2020Q3_new", "S2_2021"}


def test_reconcile_quarter_scope_still_buckets_by_quarter(db: Session) -> None:
    """``SELECTION_SCOPES["quarter"]`` has no caller since S2 moved to year.

    Kept as a pin on the lambda itself so a future sub-annual source
    inherits a bucket rule that is known to work, not one that rotted
    unobserved.
    """
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "sentinel2", "S2_2020Q1", "2020-02-10")
    _persist(db, parcel_id, "sentinel2", "S2_2020Q3_old", "2020-08-10")
    _persist(db, parcel_id, "sentinel2", "S2_2020Q3_new", "2020-09-02")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "sentinel2",
        [("S2_2020Q3_new", date(2020, 9, 2))],
        scope="quarter",
    )

    assert deleted == 1
    assert _item_ids(db, parcel_id, "sentinel2") == {"S2_2020Q1", "S2_2020Q3_new"}


# ── Tile-proxy input bounds and STAC fetch allowlist ──────────────────────────


def test_tile_proxy_rejects_out_of_range_zoom(client: TestClient) -> None:
    """z outside 0–24 is rejected at the boundary, not forwarded to Titiler."""
    snapshot_id = uuid.uuid4()
    assert client.get(f"/api/v1/imagery/{snapshot_id}/tiles/50/1/1").status_code == 422
    assert client.get(f"/api/v1/imagery/{snapshot_id}/tiles/-1/1/1").status_code == 422


def test_tile_proxy_rejects_negative_tile_index(client: TestClient) -> None:
    """Negative x/y are rejected at the boundary."""
    snapshot_id = uuid.uuid4()
    assert client.get(f"/api/v1/imagery/{snapshot_id}/tiles/10/-1/1").status_code == 422
    assert client.get(f"/api/v1/imagery/{snapshot_id}/tiles/10/1/-1").status_code == 422


def test_stac_host_allowlist() -> None:
    """Only the Planetary Computer host may be fetched for STAC items."""
    from app.api.v1.imagery import _is_allowed_stac_host

    assert _is_allowed_stac_host(
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
        "landsat-c2-l2/items/LT05_L2SP_033033_19870704_02_T1"
    )
    assert not _is_allowed_stac_host("https://evil.example.com/api/stac/v1/items/x")
    assert not _is_allowed_stac_host("http://169.254.169.254/latest/meta-data/")
    # A host that merely ends with the allowed name must not pass.
    assert not _is_allowed_stac_host("https://planetarycomputer.microsoft.com.evil.test/x")


# ── Signing failures never leak an unsigned href ─────────────────────────────

_BLOB_URL = "https://landsateuwest.blob.core.windows.net/landsat-c2/naip_2020.tif"


def _insert_snapshot(db: Session, parcel_id: uuid.UUID, source: str, cog_url: str) -> uuid.UUID:
    from app.services.imagery import get_imagery_snapshots, upsert_imagery_snapshot

    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source=source,
        capture_date=date(2020, 7, 15),
        stac_item_id=f"{source}_2020_item",
        stac_collection="naip" if source == "naip" else "landsat-c2-l2",
        cog_url=cog_url,
        thumbnail_url=None,
        resolution_m=1.0,
    )
    return get_imagery_snapshots(db, parcel_id=parcel_id, source=source)[0].id


def _insert_topo_snapshot(db: Session, parcel_id: uuid.UUID, cog_url: str) -> uuid.UUID:
    from app.services.imagery import get_imagery_snapshots, upsert_imagery_snapshot

    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source="usgs_topo",
        capture_date=date(1954, 1, 1),
        stac_item_id="tnm-1954-sheet",
        stac_collection="usgs_topo",
        cog_url=cog_url,
        thumbnail_url=None,
        resolution_m=2.0,
    )
    return get_imagery_snapshots(db, parcel_id=parcel_id, source="usgs_topo")[0].id


def test_topo_tile_on_an_unlisted_host_is_refused(client: TestClient, db: Session) -> None:
    """N5: the topo URL comes straight out of TNM's `urls.GeoTIFF`, unsigned.

    Nothing else inspects it — `_proxy_cog_tile` is called with `sign=False`
    for usgs_topo — so this check is the only thing between a stored value
    and Titiler fetching an attacker-chosen host from inside the network.
    Delete-the-fix: drop the `_refuse_unlisted_host` call at
    `api/imagery.py:486` and the request reaches Titiler.
    """
    from app.api.v1.imagery import _snapshot_cache

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Topo Ln")
    snapshot_id = _insert_topo_snapshot(db, parcel_id, "https://evil.example.com/topo.tif")
    _snapshot_cache.clear()

    with patch("app.api.v1.imagery._get_titiler_client") as mock_titiler:
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/12/100/200")

    assert resp.status_code == 502
    assert "evil.example.com" not in resp.text
    mock_titiler.assert_not_called()


def test_topo_tile_on_the_tnm_host_is_served(client: TestClient, db: Session) -> None:
    """The positive control: `prd-tnm.s3.amazonaws.com` is the real TNM host.

    Verified against production 2026-08-27: 1183 `usgs_topo`
    `imagery_snapshots` rows, one distinct host, this one. Without this half
    the refusal above would also pass with the allowlist emptied.
    """
    from app.api.v1.imagery import _snapshot_cache

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Quad St")
    url = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/x.tif"
    snapshot_id = _insert_topo_snapshot(db, parcel_id, url)
    _snapshot_cache.clear()

    upstream = MagicMock()
    upstream.status_code = 200
    upstream.content = b"tile"
    upstream.headers = {"content-type": "image/png"}
    titiler = MagicMock()
    titiler.get = AsyncMock(return_value=upstream)

    with patch("app.api.v1.imagery._get_titiler_client", return_value=titiler):
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/12/100/200")

    assert resp.status_code == 200
    assert titiler.get.await_args.kwargs["params"]["url"] == url


def test_tile_proxy_502s_when_signing_fails(client: TestClient, db: Session) -> None:
    """A terminal signing failure 502s instead of handing Titiler an
    unsigned href — which Planetary Computer rejects with a 409 that
    surfaces to the user as a broken tile."""
    import httpx

    from app.api.v1.imagery import _snapshot_cache

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Unsigned Ave")
    snapshot_id = _insert_snapshot(db, parcel_id, "naip", _BLOB_URL)
    _snapshot_cache.clear()

    with (
        patch("app.api.v1.imagery.stac_service.sign_pc_url", new_callable=AsyncMock) as mock_sign,
        patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
    ):
        mock_sign.side_effect = httpx.RequestError("signer unreachable")
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/12/100/200")

    assert resp.status_code == 502
    assert "blob.core.windows.net" not in resp.text
    assert _BLOB_URL not in resp.text
    mock_titiler.assert_not_called()


def test_signed_stac_item_502s_when_band_signing_fails(client: TestClient, db: Session) -> None:
    """One unsignable band fails the whole item rather than serving a
    private blob href Titiler can only 409 on."""
    import httpx

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Band St")
    stac_url = (
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
        "landsat-c2-l2/items/LT05_2020"
    )
    snapshot_id = _insert_snapshot(db, parcel_id, "landsat", stac_url)

    item = {
        "id": "LT05_2020",
        "assets": {band: {"href": f"{_BLOB_URL}#{band}"} for band in ("red", "green", "blue")},
    }
    fetch_client = AsyncMock()
    fetch_client.get.return_value = httpx.Response(
        200, json=item, request=httpx.Request("GET", stac_url)
    )

    async def _sign(url: str, **_kwargs: object) -> str:
        if url.endswith("#green"):
            raise httpx.HTTPStatusError(
                "429",
                request=httpx.Request("GET", url),
                response=httpx.Response(429, request=httpx.Request("GET", url)),
            )
        return f"{url}?sig=ok"

    with (
        patch("app.api.v1.imagery._get_stac_fetch_client", return_value=fetch_client),
        patch("app.api.v1.imagery.stac_service.sign_pc_url", side_effect=_sign),
    ):
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/stac")

    assert resp.status_code == 502
    assert "blob.core.windows.net" not in resp.text


# ── The Landsat STAC callback URL rotates with its SAS token ─────────────────

_LANDSAT_STAC_URL = (
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_2020"
)


def _landsat_snapshot(db: Session, street: str) -> uuid.UUID:
    from app.api.v1.imagery import _snapshot_cache

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, street)
    snapshot_id = _insert_snapshot(db, parcel_id, "landsat", _LANDSAT_STAC_URL)
    _snapshot_cache.clear()
    return snapshot_id


def _titiler_url_param(mock_titiler: MagicMock) -> str:
    params = mock_titiler.return_value.get.await_args.kwargs["params"]
    return str(params["url"])


def _ok_titiler() -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(
        return_value=httpx.Response(
            200,
            content=b"tile",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", "http://titiler/x"),
        )
    )
    return client


def test_landsat_tile_url_carries_token_expiry(client: TestClient, db: Session) -> None:
    """Titiler keys its STAC item cache on this URL, so it must name the
    token expiry the callback will embed."""
    snapshot_id = _landsat_snapshot(db, "Expiry Way")

    with (
        patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
        patch(
            "app.api.v1.imagery.stac_service.container_token_expiry",
            new_callable=AsyncMock,
            return_value="2026-08-12T05:00:40Z",
        ),
    ):
        mock_titiler.return_value = _ok_titiler()
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/14/4757/6457")
        url = _titiler_url_param(mock_titiler)

    assert resp.status_code == 200
    assert url.endswith(f"/api/v1/imagery/{snapshot_id}/stac?v=2026-08-12T05%3A00%3A40Z")


def test_landsat_tile_url_changes_when_token_rotates(client: TestClient, db: Session) -> None:
    """The regression test: a constant URL let Titiler serve a cached item
    whose SAS token had expired, which surfaced as a 502."""
    snapshot_id = _landsat_snapshot(db, "Rotation Rd")
    urls = []

    for expiry in ("2026-08-12T05:00:40Z", "2026-08-12T05:45:40Z"):
        with (
            patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
            patch(
                "app.api.v1.imagery.stac_service.container_token_expiry",
                new_callable=AsyncMock,
                return_value=expiry,
            ),
        ):
            mock_titiler.return_value = _ok_titiler()
            client.get(f"/api/v1/imagery/{snapshot_id}/tiles/14/4757/6457")
            urls.append(_titiler_url_param(mock_titiler))

    assert urls[0] != urls[1]


@pytest.mark.parametrize(
    "failure",
    [
        httpx.RequestError("signer unreachable"),
        RedisError("connection lost"),
        OSError("socket closed"),
    ],
    ids=["signer-down", "redis-down", "socket-error"],
)
def test_landsat_tile_falls_back_to_time_bucket_when_expiry_unavailable(
    client: TestClient, db: Session, caplog: pytest.LogCaptureFixture, failure: Exception
) -> None:
    """Computing a cache key must never fail a tile the callback could serve.

    Every dependency of the versioning step — the signer, Redis, the socket
    under it — degrades to a wall-clock bucket and a warning, not a 502.
    """
    snapshot_id = _landsat_snapshot(db, "Fallback Ave")

    with (
        caplog.at_level(logging.WARNING, logger="app.api.v1.imagery"),
        patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
        patch(
            "app.api.v1.imagery.stac_service.container_token_expiry",
            new_callable=AsyncMock,
            side_effect=failure,
        ),
    ):
        mock_titiler.return_value = _ok_titiler()
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/14/4757/6457")
        url = _titiler_url_param(mock_titiler)

    assert resp.status_code == 200
    bucket = url.split("?v=")[1]
    from app.api.v1.imagery import _STAC_URL_BUCKET_S

    assert bucket == f"t{int(time.time()) // _STAC_URL_BUCKET_S}"
    assert "Landsat SAS token expiry unavailable" in caplog.text


def test_landsat_tile_versions_url_when_token_has_no_expiry(
    client: TestClient, db: Session
) -> None:
    """A token with no ``se`` yields None, not an exception — still version it."""
    snapshot_id = _landsat_snapshot(db, "No Expiry Ln")

    with (
        patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
        patch(
            "app.api.v1.imagery.stac_service.container_token_expiry",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_titiler.return_value = _ok_titiler()
        resp = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/14/4757/6457")
        url = _titiler_url_param(mock_titiler)

    assert resp.status_code == 200
    from app.api.v1.imagery import _STAC_URL_BUCKET_S

    assert url.split("?v=")[1] == f"t{int(time.time()) // _STAC_URL_BUCKET_S}"


def test_warmup_uses_the_same_stac_url_as_the_tile_proxy(client: TestClient, db: Session) -> None:
    """Warming a different URL than tiles read primes a key nothing uses —
    and leaves the first tile paying the cold fetch anyway."""
    snapshot_id = _landsat_snapshot(db, "Warmup Walk")
    urls = []

    for path in ("tiles/14/4757/6457", "warmup"):
        with (
            patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
            patch(
                "app.api.v1.imagery.stac_service.container_token_expiry",
                new_callable=AsyncMock,
                return_value="2026-08-12T05:00:40Z",
            ),
        ):
            mock_titiler.return_value = _ok_titiler()
            method = client.post if path == "warmup" else client.get
            method(f"/api/v1/imagery/{snapshot_id}/{path}")
            urls.append(_titiler_url_param(mock_titiler))

    assert urls[0] == urls[1]


def test_signed_stac_item_cache_control_tracks_token_expiry(
    client: TestClient, db: Session
) -> None:
    """The item goes stale the moment its token does, so it must say so."""
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Freshness Ct")
    snapshot_id = _insert_snapshot(db, parcel_id, "landsat", _LANDSAT_STAC_URL)

    item = {
        "id": "LT05_2020",
        "assets": {
            band: {"href": f"https://landsateuwest.blob.core.windows.net/landsat-c2/{band}.tif"}
            for band in ("red", "green", "blue")
        },
    }
    fetch_client = AsyncMock()
    fetch_client.get.return_value = httpx.Response(
        200, json=item, request=httpx.Request("GET", _LANDSAT_STAC_URL)
    )

    def _sign_expiring_at(expiry: datetime) -> object:
        async def _sign(url: str, **_kwargs: object) -> str:
            return f"{url}?se={expiry.strftime('%Y-%m-%dT%H:%M:%SZ')}&sig=ok"

        return _sign

    live = datetime.now(UTC) + timedelta(minutes=30)
    with (
        patch("app.api.v1.imagery._get_stac_fetch_client", return_value=fetch_client),
        patch("app.api.v1.imagery.stac_service.sign_pc_url", side_effect=_sign_expiring_at(live)),
    ):
        fresh = client.get(f"/api/v1/imagery/{snapshot_id}/stac")

    max_age = int(fresh.headers["cache-control"].split("max-age=")[1])
    assert 0 < max_age <= 30 * 60 - 300

    dead = datetime.now(UTC) - timedelta(minutes=1)
    with (
        patch("app.api.v1.imagery._get_stac_fetch_client", return_value=fetch_client),
        patch("app.api.v1.imagery.stac_service.sign_pc_url", side_effect=_sign_expiring_at(dead)),
    ):
        stale = client.get(f"/api/v1/imagery/{snapshot_id}/stac")

    assert stale.headers["cache-control"] == "no-store"


def test_list_imagery_omits_snapshots_it_cannot_sign(client: TestClient, db: Session) -> None:
    """An unsignable snapshot is left out of the listing, not returned with
    a private blob URL the browser could only fail on."""
    import httpx

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Partial Way")
    good_url = "https://example.blob.core.windows.net/good.tif"
    from app.services.imagery import upsert_imagery_snapshot

    upsert_imagery_snapshot(
        db,
        parcel_id=parcel_id,
        source="naip",
        capture_date=date(2018, 7, 15),
        stac_item_id="naip_2018",
        stac_collection="naip",
        cog_url=good_url,
        thumbnail_url=None,
        resolution_m=1.0,
    )
    _insert_snapshot(db, parcel_id, "sentinel2", _BLOB_URL)

    async def _sign(url: str, **_kwargs: object) -> str:
        if url == _BLOB_URL:
            raise httpx.RequestError("signer unreachable")
        return f"{url}?sig=ok"

    with patch("app.api.v1.imagery.stac_service.sign_pc_url", side_effect=_sign):
        resp = client.get(f"/api/v1/parcels/{parcel_id}/imagery")

    assert resp.status_code == 200
    snapshots = resp.json()["snapshots"]
    assert [s["cog_url"] for s in snapshots] == [f"{good_url}?sig=ok"]
    assert _BLOB_URL not in resp.text


# ── Stranded-work janitor ────────────────────────────────────────────────────


def _stranded_setup(
    db: Session,
    *,
    request_status: str,
    task_status: str,
    age_minutes: float,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a request of the given age with one task row under it."""
    from datetime import UTC, datetime, timedelta

    from app.models.parcels import TimelineRequest, TimelineRequestTask

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Stranded Rd")
    stamp = datetime.now(UTC) - timedelta(minutes=age_minutes)
    req = TimelineRequest(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        status=request_status,
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(req)
    db.add(
        TimelineRequestTask(
            id=uuid.uuid4(),
            timeline_request_id=req.id,
            source="landsat",
            status=task_status,
            items_found=0,
        )
    )
    db.commit()
    return req.id, parcel_id


def _reload(db: Session, request_id: uuid.UUID) -> tuple[str, str]:
    from app.models.parcels import TimelineRequest, TimelineRequestTask

    db.expire_all()
    req = db.get(TimelineRequest, request_id)
    task = (
        db.query(TimelineRequestTask)
        .filter(TimelineRequestTask.timeline_request_id == request_id)
        .one()
    )
    assert req is not None
    return req.status, task.status


def test_janitor_fails_a_stale_processing_request(db: Session) -> None:
    """A request left processing past the hard time limit is failed, and its
    task rows with it — an OOM kill never runs the timeout handler."""
    from app.services.imagery import sweep_stranded_work

    request_id, _ = _stranded_setup(
        db, request_status="processing", task_status="processing", age_minutes=90
    )

    assert sweep_stranded_work(db) == (1, 0)

    from app.models.parcels import TimelineRequest

    assert _reload(db, request_id) == ("failed", "failed")
    req = db.get(TimelineRequest, request_id)
    assert req is not None
    assert req.error_message == "Stranded: worker died mid-task (janitor)"


def test_janitor_leaves_a_fresh_request_alone(db: Session) -> None:
    """Work that started minutes ago is running, not stranded."""
    from app.services.imagery import sweep_stranded_work

    request_id, _ = _stranded_setup(
        db, request_status="processing", task_status="processing", age_minutes=5
    )

    assert sweep_stranded_work(db) == (0, 0)
    assert _reload(db, request_id) == ("processing", "processing")


def test_janitor_fails_task_rows_orphaned_under_a_terminal_request(db: Session) -> None:
    """The shape actually found in production: the request is already failed
    (soft-limit handler, or a later stale takeover) while a task row under it
    is still processing. Nothing else ever closes those rows, and backfill
    cannot see the source as failed while they sit open."""
    from app.services.imagery import sweep_stranded_work

    request_id, _ = _stranded_setup(
        db, request_status="failed", task_status="processing", age_minutes=1440
    )

    assert sweep_stranded_work(db) == (0, 1)
    assert _reload(db, request_id) == ("failed", "failed")


def test_janitor_leaves_task_rows_under_a_just_finished_request(db: Session) -> None:
    """A request that completed seconds ago may still be mid-write."""
    from app.services.imagery import sweep_stranded_work

    request_id, _ = _stranded_setup(
        db, request_status="complete", task_status="queued", age_minutes=2
    )

    assert sweep_stranded_work(db) == (0, 0)
    assert _reload(db, request_id) == ("complete", "queued")


def test_janitor_runs_on_worker_startup() -> None:
    """The sweep is wired to worker_ready — a worker that was OOM-killed
    heals its own stranded rows on the next boot, with no separate script."""
    from celery.signals import worker_ready

    from app.tasks.celery_app import sweep_stranded_work as hook

    connected = [ref() if callable(ref) else ref for _, ref in worker_ready.receivers]
    assert any(getattr(r, "__name__", None) == hook.__name__ for r in connected)


def test_janitor_startup_hook_survives_a_database_outage() -> None:
    """A database hiccup at boot must not stop the worker starting."""
    from sqlalchemy.exc import OperationalError

    from app.tasks.celery_app import sweep_stranded_work as hook

    with patch(
        "app.services.imagery.sweep_stranded_work",
        side_effect=OperationalError("x", {}, Exception()),
    ):
        hook()


# ── Titiler access token (security audit SEC-1) ─────────────────────────────


def _settings_with_token(token: str | None) -> MagicMock:
    from app.config import Settings

    return Settings(
        database_url="postgresql://test:test@localhost/test",
        titiler_url="http://titiler",
        titiler_access_token=token,
    )


def test_titiler_params_unset_is_byte_identical() -> None:
    """With no token configured the request Titiler sees is exactly today's.

    This property is what makes the deploy ordering safe: the API can ship
    first, and a Titiler that does not yet enforce a token sees no change.
    """
    from app.services.titiler import titiler_params

    params = {"url": "https://x/y.tif", "bidx": [1, 2, 3]}
    assert titiler_params(_settings_with_token(None), params) == params
    assert titiler_params(_settings_with_token(""), params) == params
    assert "access_token" not in titiler_params(_settings_with_token(None), params)


def test_titiler_params_appends_token_when_set() -> None:
    from app.services.titiler import titiler_params

    out = titiler_params(_settings_with_token("s3cret"), {"url": "https://x/y.tif"})
    assert out == {"url": "https://x/y.tif", "access_token": "s3cret"}


def test_every_titiler_call_site_sends_the_token(client: TestClient, db: Session) -> None:
    """Tile proxy (COG and STAC) and warmup (COG and STAC) all carry access_token."""
    from app.config import get_settings

    client.app.dependency_overrides[get_settings] = lambda: _settings_with_token("s3cret")  # type: ignore[attr-defined]  # TestClient.app is typed as the ASGI protocol, not FastAPI
    landsat_id = _landsat_snapshot(db, "Token Way")
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Token Ave")
    naip_id = _insert_snapshot(db, parcel_id, "naip", _NAIP_BLOB_URL)

    calls = [
        (f"/api/v1/imagery/{landsat_id}/tiles/14/4757/6457", "get"),
        (f"/api/v1/imagery/{naip_id}/tiles/14/4757/6457", "get"),
        (f"/api/v1/imagery/{landsat_id}/warmup", "post"),
        (f"/api/v1/imagery/{naip_id}/warmup", "post"),
    ]
    for path, method in calls:
        with (
            patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
            patch(
                "app.api.v1.imagery.stac_service.sign_pc_url",
                new_callable=AsyncMock,
                return_value=_NAIP_BLOB_URL + "?sig=x",
            ),
            patch(
                "app.api.v1.imagery.stac_service.container_token_expiry",
                new_callable=AsyncMock,
                return_value="2026-08-12T05:00:40Z",
            ),
        ):
            mock_titiler.return_value = _ok_titiler()
            resp = getattr(client, method)(path)
            params = mock_titiler.return_value.get.await_args.kwargs["params"]
        assert resp.status_code in (200, 204), path
        assert params.get("access_token") == "s3cret", path


# ── Outbound host allowlist at the Titiler boundary (security audit P5) ─────

_NAIP_BLOB_URL = "https://naipeuwest.blob.core.windows.net/naip/v002/co/2021/x.tif"


def test_tile_proxy_refuses_non_allowlisted_cog_host(client: TestClient, db: Session) -> None:
    """A stored cog_url on an unknown host never reaches Titiler's url= or the signer."""
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Evil St")
    snapshot_id = _insert_snapshot(db, parcel_id, "naip", "https://evil.example.com/x.tif")

    with (
        patch("app.api.v1.imagery._get_titiler_client") as mock_titiler,
        patch("app.api.v1.imagery.stac_service.sign_pc_url", new_callable=AsyncMock) as sign,
    ):
        tile = client.get(f"/api/v1/imagery/{snapshot_id}/tiles/14/4757/6457")
        warm = client.post(f"/api/v1/imagery/{snapshot_id}/warmup")

    assert tile.status_code == 502
    assert warm.status_code == 204
    sign.assert_not_awaited()
    mock_titiler.assert_not_called()


# ── Declared scope: sources, origin, and what counts as the current request ──


def _scoped_request(
    db: Session,
    parcel_id: uuid.UUID,
    sources: list[str],
    *,
    status: str = "complete",
    origin: str = "backfill",
    age_hours: float = 1.0,
) -> object:
    from app.models.parcels import TimelineRequest

    req = TimelineRequest(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        status=status,
        sources=sources,
        origin=origin,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    db.add(req)
    db.commit()
    return req


def test_a_request_declares_full_scope_by_default(db: Session) -> None:
    from app.models.parcels import TimelineRequest
    from app.services.imagery import get_or_create_timeline_request

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    request, _ = get_or_create_timeline_request(db, parcel_id)

    assert request.sources == list(TimelineRequest.FULL_SCOPE)
    assert request.origin == "user"


def test_normalize_sources_dedupes_sorts_and_rejects_unknowns() -> None:
    """The cardinality test for "full scope" is only sound if this is."""
    from app.services.imagery import FULL_SCOPE, normalize_sources

    assert normalize_sources(None) == list(FULL_SCOPE)
    assert normalize_sources(["naip", "naip", "census"]) == ["census", "naip"]
    with pytest.raises(ValueError, match="Unknown timeline source"):
        normalize_sources(["naip", "landsat_8"])
    with pytest.raises(ValueError, match="at least one source"):
        normalize_sources([])


def test_scoped_request_never_becomes_the_parcels_current_request(db: Session) -> None:
    """INVESTIGATION §2.2a, trigger 6, traced through the new query.

    Before this filter: a census-only backfill is the parcel's newest
    queued/complete request, so ``_find_reusable_request`` hands it to
    ``maybe_refetch_for_backfill``, which finds no ``usgs_topo`` task row on
    it, fires trigger 6, and dispatches a full pipeline — on every page view,
    forever. Delete the ``full_scope_clause`` line from
    ``_find_reusable_request`` and this test fails on the id assertion.
    """
    from app.services.imagery import (
        _find_reusable_request,
        get_or_create_timeline_request,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    full, _ = get_or_create_timeline_request(db, parcel_id)
    update_timeline_request_status(db, full, "complete")

    scoped = _scoped_request(db, parcel_id, ["census"], age_hours=0.0)

    current = _find_reusable_request(db, parcel_id)
    assert current is not None
    assert current.id == full.id, "a scoped request must never be the current one"
    assert current.id != scoped.id


def test_a_scoped_request_does_not_trigger_a_full_backfill(db: Session) -> None:
    """The same scenario one level up: the trigger cannot see the scoped run."""
    from types import SimpleNamespace

    from app.services.imagery import (
        create_request_tasks,
        get_or_create_timeline_request,
        maybe_refetch_for_backfill,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    full, _ = get_or_create_timeline_request(db, parcel_id)
    create_request_tasks(db, full.id, ["usgs_topo", "property"])
    update_timeline_request_status(db, full, "complete")
    _scoped_request(db, parcel_id, ["census"], age_hours=0.0)

    parcel = SimpleNamespace(id=parcel_id, census_tract_id=None, county=None)
    assert maybe_refetch_for_backfill(db, parcel, full) is None


def test_a_partial_request_is_reusable_like_a_complete_one(db: Session) -> None:
    from app.services.imagery import (
        _find_reusable_request,
        get_or_create_timeline_request,
        update_timeline_request_status,
    )

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    request, _ = get_or_create_timeline_request(db, parcel_id)
    update_timeline_request_status(db, request, "partial")

    found = _find_reusable_request(db, parcel_id)
    assert found is not None and found.id == request.id


def test_losing_the_race_to_a_scoped_request_reuses_it(
    committing_db: sessionmaker[Session],
) -> None:
    """``uq_timeline_requests_parcel_inflight`` does not care about scope.

    A scoped backfill holds the parcel's one in-flight slot, so the loser of
    that race has to be able to find it. Point ``_create_queued_request``'s
    recovery at ``_find_reusable_request`` — which is scope-filtered — and
    the lookup returns None and the IntegrityError is re-raised.

    ``committing_db`` rather than ``db``: the recovery path runs after a
    ``rollback()``, and the rollback-per-test fixture would take the racing
    request with it, so the race could not be staged at all.
    """
    from app.services.imagery import _create_queued_request

    parcel_id = uuid.uuid4()
    with committing_db() as db:
        _insert_parcel(db, parcel_id)
        inflight = _scoped_request(db, parcel_id, ["landsat"], status="queued", age_hours=0.0)
        inflight_id = inflight.id  # type: ignore[attr-defined]  # _scoped_request returns a TimelineRequest

    with committing_db() as db:
        request, created = _create_queued_request(db, parcel_id)

    assert created is False
    assert request.id == inflight_id


def test_create_queued_request_stamps_deployed_sha(db: Session) -> None:
    """Y7's write side: every request created through the service records
    the process's own build SHA — the same value /api/v1/health reports. A
    NULL deployed_sha can only be a pre-0013 row."""
    from app.config import get_settings
    from app.services.imagery import _create_queued_request

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)

    request, created = _create_queued_request(db, parcel_id)

    assert created is True
    assert request.deployed_sha == get_settings().git_sha
    assert request.deployed_sha is not None


# ── Scoped task creation leaves other sources' ledger history alone ──────────


def test_create_request_tasks_only_touches_the_named_sources(db: Session) -> None:
    """A census-only run must not erase the landsat ledger it did not re-run."""
    from sqlalchemy import text

    from app.services.imagery import create_request_tasks, get_or_create_timeline_request
    from app.services.year_ledger import record_year_outcome

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    request, _ = get_or_create_timeline_request(db, parcel_id)
    tasks = create_request_tasks(db, request.id, ["census", "landsat"])
    by_source = {t.source: t for t in tasks}
    record_year_outcome(db, by_source["landsat"].id, "landsat", "1993", "failed", "read_timeout")
    record_year_outcome(
        db, by_source["census"].id, "census_decennial", "2000", "absent", "api_no_data"
    )

    create_request_tasks(db, request.id, ["census"])

    rows = db.execute(
        text(
            "SELECT y.source, y.group_key FROM timeline_task_years y"
            " JOIN timeline_request_tasks t ON t.id = y.task_id"
            " WHERE t.timeline_request_id = :rid"
        ),
        {"rid": request.id.hex},
    ).all()
    assert [(r.source, r.group_key) for r in rows] == [("landsat", "1993")]


# ── Request status aggregation ───────────────────────────────────────────────


def test_aggregate_request_status_partial() -> None:
    """Crawford County 6563dedf: naip and sentinel2 failed, the rest did not.

    Delete the ``partial`` branch of ``aggregate_request_status`` and this
    reads ``complete`` — which is exactly what production said while the
    parcel served zero NAIP and zero Sentinel-2 rows.
    """
    from app.services.imagery import aggregate_request_status

    status, failed = aggregate_request_status(
        [
            ("census", "complete"),
            ("landsat", "complete"),
            ("naip", "failed"),
            ("property", "skipped"),
            ("sentinel2", "failed"),
            ("usgs_topo", "complete"),
        ]
    )
    assert status == "partial"
    assert failed == ["naip", "sentinel2"]


def test_aggregate_request_status_complete_and_failed() -> None:
    from app.services.imagery import aggregate_request_status

    assert aggregate_request_status([("naip", "complete"), ("property", "skipped")]) == (
        "complete",
        [],
    )
    assert aggregate_request_status([("naip", "failed"), ("census", "failed")]) == (
        "failed",
        ["naip", "census"],
    )
    assert aggregate_request_status([]) == ("complete", [])


def test_aggregate_request_status_treats_a_partial_task_as_degraded() -> None:
    """A property task that lost some of its county queries holes the request.

    Delete-the-fix: drop ``"partial"`` from the ``degraded`` comprehension in
    ``aggregate_request_status`` and the first assertion reads ``complete`` —
    a request advertising a full timeline over a history that is missing
    whatever the 429'd permit layer held.

    The all-failed arm still reads ``failed`` only from genuinely failed
    tasks: a partial task served data, and demoting the whole request to
    ``failed`` for it would be the same lie in the other direction.
    """
    from app.services.imagery import aggregate_request_status

    assert aggregate_request_status(
        [("naip", "complete"), ("property", "partial")],
    ) == ("partial", ["property"])
    assert aggregate_request_status([("property", "partial")]) == ("partial", ["property"])
    assert aggregate_request_status(
        [("naip", "failed"), ("property", "partial")],
    ) == ("partial", ["naip", "property"])


# ── Reconciliation: a suppressed group is the one authority to delete ────────

# e513188c, live on 2026-08-26: the parcel serves a NAIP 2023 card built from
# tile nj_m_4007309_sw_18_030_20230820_20231019, while the point-coverage gate
# records that year suppressed/naip_no_point_coverage naming that same tile.
_E513188C_TILE = "nj_m_4007309_sw_18_030_20230820_20231019"
_E513188C_SIBLING = "nj_m_4007424_ne_18_030_20230820_20231019"


def _e513188c(db: Session) -> uuid.UUID:
    """Its eight ok NAIP years plus the wrong 2023 card."""
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    for year in (2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022):
        _persist(db, parcel_id, "naip", f"naip_{year}", f"{year}-08-20")
    _persist(db, parcel_id, "naip", _E513188C_TILE, "2023-08-20")
    return parcel_id


def _reselect_the_eight_ok_years() -> list[tuple[str, date]]:
    return [(f"naip_{y}", date(y, 8, 20)) for y in (2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022)]


def test_reconcile_deletes_a_group_this_run_suppressed(db: Session) -> None:
    """The G1 fix. 2023 is absent from the selection — rule 3 keeps it — but
    this run positively identified the served tile as not covering the
    parcel, and that is the one thing allowed to say a served row is wrong.

    Delete the ``suppressed.get(group_key, ())`` branch from
    ``reconcile_source_snapshots`` and the wrong card survives, which is
    exactly what production does today.
    """
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = _e513188c(db)

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "naip",
        _reselect_the_eight_ok_years(),
        suppressed={"2023": {_E513188C_TILE, _E513188C_SIBLING}},
    )

    assert deleted == 1
    assert _E513188C_TILE not in _item_ids(db, parcel_id, "naip")
    assert len(_item_ids(db, parcel_id, "naip")) == 8, "no other NAIP row may change"


def test_reconcile_does_not_delete_on_an_absent_outcome(db: Session) -> None:
    """The inverse, and it matters more than the delete does.

    All four absent reasons mean "the fetch completed and found nothing
    usable *this time*"; naip absent/no_scenes alone is 1,848 latest ledger
    rows fleet-wide, so a rule that deleted on absence would delete on the
    largest population in the ledger. Only ``suppressed`` reaches the
    ``suppressed`` argument at all — this asserts the boundary holds when the
    same group is absent rather than suppressed.
    """
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = _e513188c(db)

    deleted = reconcile_source_snapshots(
        db, parcel_id, "naip", _reselect_the_eight_ok_years(), suppressed={}
    )

    assert deleted == 0
    assert _E513188C_TILE in _item_ids(db, parcel_id, "naip")


def test_reconcile_leaves_a_different_item_in_a_suppressed_group(db: Session) -> None:
    """The item-id condition is the safety property, not decoration.

    A suppression names the tiles the gate rejected. A row for the same year
    built from a *different* item was never judged, so it is not the
    suppression's to delete.
    """
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _persist(db, parcel_id, "naip", "some_other_2023_item", "2023-08-20")
    _persist(db, parcel_id, "naip", "naip_2021", "2021-08-20")

    deleted = reconcile_source_snapshots(
        db,
        parcel_id,
        "naip",
        [("naip_2021", date(2021, 8, 20))],
        suppressed={"2023": {_E513188C_TILE}},
    )

    assert deleted == 0
    assert _item_ids(db, parcel_id, "naip") == {"some_other_2023_item", "naip_2021"}


def test_reconcile_can_delete_a_suppression_when_nothing_was_selected(db: Session) -> None:
    """A run whose every other year came back empty still knows this tile is
    wrong: the suppression is positive evidence about an item, not an
    inference from an absence."""
    from app.services.imagery import reconcile_source_snapshots

    parcel_id = _e513188c(db)

    deleted = reconcile_source_snapshots(
        db, parcel_id, "naip", [], suppressed={"2023": {_E513188C_TILE}}
    )

    assert deleted == 1
    assert _E513188C_TILE not in _item_ids(db, parcel_id, "naip")


# ── Backfill reads the ledger ────────────────────────────────────────────────


def _ledger_backfill_parcel(
    db: Session, *, age_hours: float = 24.0, declared: list[str] | None = None
) -> tuple[object, object, uuid.UUID]:
    """A parcel whose latest full-scope request reads complete and whose
    ledger holds one failed landsat year. The three task-row triggers are all
    satisfied, so only the ledger can produce a refetch."""
    from types import SimpleNamespace

    from app.models.parcels import TimelineRequest, TimelineRequestTask
    from app.services.year_ledger import record_year_outcome

    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id, "Crawford County")
    req = TimelineRequest(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        status="complete",
        sources=declared if declared is not None else list(TimelineRequest.FULL_SCOPE),
        origin="user",
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    db.add(req)
    db.commit()
    task_ids = {}
    for source in ("landsat", "usgs_topo"):
        task = TimelineRequestTask(
            id=uuid.uuid4(),
            timeline_request_id=req.id,
            source=source,
            status="complete",
            items_found=1,
        )
        db.add(task)
        task_ids[source] = task.id
    db.commit()
    record_year_outcome(db, task_ids["landsat"], "landsat", "1993", "failed", "read_timeout")
    record_year_outcome(db, task_ids["usgs_topo"], "usgs_topo", "1960s", "ok")

    parcel = SimpleNamespace(id=parcel_id, census_tract_id=None, county=None)
    return parcel, req, task_ids["landsat"]


def test_backfill_dispatches_a_scoped_request_from_the_ledger(db: Session) -> None:
    """The Crawford shape: a failed year under a complete task, which no
    task-row trigger can see. Delete the ``_ledger_backfill_sources`` call
    and this returns None — which is what production does today.
    """
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req, _ = _ledger_backfill_parcel(db)

    new_req = maybe_refetch_for_backfill(db, parcel, req)  # type: ignore[arg-type]  # SimpleNamespace stands in for Parcel

    assert new_req is not None
    assert new_req.sources == ["landsat"], "scoped to the source with work, not a full re-run"
    assert new_req.origin == "backfill"


def test_backfill_does_not_dispatch_for_a_never_retryable_outcome(db: Session) -> None:
    """absent/no_scenes is the fleet's largest population. It must not become
    a per-page-view dispatch."""
    from app.services.imagery import maybe_refetch_for_backfill
    from app.services.year_ledger import record_year_outcome

    parcel, req, task_id = _ledger_backfill_parcel(db)
    record_year_outcome(db, task_id, "landsat", "1993", "absent", "no_scenes")

    assert maybe_refetch_for_backfill(db, parcel, req) is None  # type: ignore[arg-type]  # SimpleNamespace


def test_backfill_never_selects_the_flag_gated_classes(db: Session) -> None:
    """Making absence retryable is an operator's assertion that the request
    changed. Backfill has no way to make that assertion, so it never does."""
    from app.services.imagery import maybe_refetch_for_backfill
    from app.services.year_ledger import record_year_outcome

    parcel, req, task_id = _ledger_backfill_parcel(db)
    record_year_outcome(db, task_id, "landsat", "1993", "absent", "api_no_data")

    assert maybe_refetch_for_backfill(db, parcel, req) is None  # type: ignore[arg-type]  # SimpleNamespace


def test_the_ledger_cooldown_is_per_source(db: Session) -> None:
    """A landsat request an hour ago blocks a landsat backfill. A census-only
    request an hour ago does not — which is what a per-parcel max(created_at)
    could not express.
    """
    from app.models.parcels import TimelineRequest
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req, _ = _ledger_backfill_parcel(db)

    # A census-only run an hour ago. Landsat was untouched by it, so the
    # landsat backfill is still eligible; a per-parcel max(created_at) would
    # have blocked it for six hours.
    db.add(
        TimelineRequest(
            id=uuid.uuid4(),
            parcel_id=parcel.id,  # type: ignore[attr-defined]  # SimpleNamespace
            status="complete",
            sources=["census"],
            origin="backfill",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    db.commit()
    assert maybe_refetch_for_backfill(db, parcel, req) is not None  # type: ignore[arg-type]  # SimpleNamespace


def test_a_recent_run_of_the_same_source_suppresses_the_backfill(db: Session) -> None:
    from app.services.imagery import maybe_refetch_for_backfill

    parcel, req, _ = _ledger_backfill_parcel(db, age_hours=1.0)

    assert maybe_refetch_for_backfill(db, parcel, req) is None  # type: ignore[arg-type]  # SimpleNamespace
