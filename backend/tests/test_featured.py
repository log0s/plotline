"""Tests for the featured locations API.

In particular: locks in the N+1 fix for ``GET /api/v1/featured``.
With the fix in place the endpoint runs ≤3 SQL queries regardless of
how many featured locations exist; previously it was 2N+1.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, text

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


def _seed(db: Session, n_locations: int = 5, snaps_per_parcel: int = 10) -> list[uuid.UUID]:
    """Insert N parcels + featured rows + snapshots. Return the parcel ids."""
    # Ensure the test SQLite DB has a featured_locations table — the
    # main conftest doesn't create it.
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS featured_locations (
            id              TEXT PRIMARY KEY,
            parcel_id       TEXT NOT NULL REFERENCES parcels(id),
            name            TEXT NOT NULL,
            subtitle        TEXT NOT NULL,
            slug            TEXT NOT NULL UNIQUE,
            key_stat        TEXT,
            description     TEXT,
            preview_image_url TEXT,
            display_order   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """))

    parcel_ids: list[uuid.UUID] = []
    for i in range(n_locations):
        pid = uuid.uuid4()
        parcel_ids.append(pid)
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude, point) "
                "VALUES (:id, :addr, :lat, :lng, :pt)"
            ),
            {
                "id": str(pid), "addr": f"{i} Test St",
                "lat": 39.7 + i * 0.001, "lng": -105.0 - i * 0.001,
                "pt": f"POINT({-105.0 - i * 0.001} {39.7 + i * 0.001})",
            },
        )
        db.execute(
            text(
                "INSERT INTO featured_locations "
                "(id, parcel_id, name, subtitle, slug, display_order) "
                "VALUES (:id, :pid, :n, :s, :slug, :ord)"
            ),
            {
                "id": str(uuid.uuid4()), "pid": str(pid),
                "n": f"Featured {i}", "s": f"subtitle {i}",
                "slug": f"feat-{i}", "ord": i,
            },
        )
        for s in range(snaps_per_parcel):
            db.execute(
                text(
                    "INSERT INTO imagery_snapshots "
                    "(id, parcel_id, source, capture_date, stac_item_id, stac_collection, cog_url) "
                    "VALUES (:id, :pid, :src, :dt, :sid, :coll, :url)"
                ),
                {
                    "id": str(uuid.uuid4()), "pid": str(pid),
                    "src": "naip", "dt": (date(2010, 1, 1) + timedelta(days=s * 30)).isoformat(),
                    "sid": f"item-{i}-{s}", "coll": "naip",
                    "url": f"https://example.com/{i}/{s}.tif",
                },
            )
    db.commit()
    return parcel_ids


@contextmanager
def _count_queries(db: Session) -> Any:
    """Count SELECT statements issued on the bound engine while inside."""
    counter: dict[str, int] = {"n": 0}
    engine = db.get_bind()

    def _before_cursor_execute(_c, _cur, statement, _p, _ctx, _em):  # type: ignore[no-untyped-def]
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def test_list_featured_uses_constant_queries(client: TestClient, db: Session) -> None:
    """/featured should issue ≤3 SELECTs no matter how many locations exist."""
    _seed(db, n_locations=5, snaps_per_parcel=10)

    with _count_queries(db) as counter:
        response = client.get("/api/v1/featured")

    assert response.status_code == 200
    body = response.json()
    assert len(body["locations"]) == 5

    # Pre-fix: 2N+1 = 11 queries for N=5. With the batch loader it's
    # 3 queries: list locations, batch parcels, batch snapshots.
    assert counter["n"] <= 4, (
        f"featured endpoint ran {counter['n']} SELECT statements; expected ≤4"
    )


def test_list_featured_returns_snapshot_endpoints(client: TestClient, db: Session) -> None:
    """earliest/latest snapshot ids should be the chronological extremes."""
    parcel_ids = _seed(db, n_locations=1, snaps_per_parcel=3)

    response = client.get("/api/v1/featured")
    assert response.status_code == 200
    locs = response.json()["locations"]
    assert len(locs) == 1
    loc = locs[0]
    assert loc["parcel_id"] == str(parcel_ids[0])
    # 3 snapshots seeded at 30-day intervals starting 2010-01-01;
    # earliest and latest should be different snapshot ids.
    assert loc["earliest_snapshot_id"] is not None
    assert loc["latest_snapshot_id"] is not None
    assert loc["earliest_snapshot_id"] != loc["latest_snapshot_id"]


def test_list_featured_skips_missing_parcel(client: TestClient, db: Session) -> None:
    """A featured row referencing a non-existent parcel is skipped, not a 500."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS featured_locations (
            id              TEXT PRIMARY KEY,
            parcel_id       TEXT NOT NULL REFERENCES parcels(id),
            name            TEXT NOT NULL,
            subtitle        TEXT NOT NULL,
            slug            TEXT NOT NULL UNIQUE,
            key_stat        TEXT,
            description     TEXT,
            preview_image_url TEXT,
            display_order   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """))
    db.execute(
        text(
            "INSERT INTO featured_locations "
            "(id, parcel_id, name, subtitle, slug, display_order) "
            "VALUES (:id, :pid, :n, :s, :slug, :ord)"
        ),
        {
            "id": str(uuid.uuid4()), "pid": str(uuid.uuid4()),
            "n": "Orphan", "s": "no parcel", "slug": "orphan", "ord": 0,
        },
    )
    db.commit()

    response = client.get("/api/v1/featured")
    assert response.status_code == 200
    assert response.json()["locations"] == []
