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


def test_reconcile_quarter_scope_keeps_other_quarters_of_the_year(db: Session) -> None:
    """Sentinel-2 selects per quarter, so a Q3 replacement must not delete
    the Q1 row that this run also selected — or the ones it didn't."""
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
    assert bucket == f"t{int(time.time()) // 600}"
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
    assert url.split("?v=")[1] == f"t{int(time.time()) // 600}"


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
