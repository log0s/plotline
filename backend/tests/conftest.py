"""Pytest configuration and shared fixtures.

Test strategy:
  - We use SQLite in-memory for the FastAPI integration tests (no PostGIS needed)
    because the endpoint tests mock the service layer, so spatial queries never
    actually execute against the test DB.
  - Pure service-layer unit tests (dedup logic, geocoder parsing) use unittest.mock
    directly and never touch a database.

This keeps CI dependency-free — no Postgres/PostGIS install required.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# `scripts/` is a sibling of `backend/`, not a child, and the script tests load
# their subject by path — so a script that imports `scripts.shared.*` needs the
# repo root importable. The container has it (`PYTHONPATH=/app`, with
# `scripts/` mounted at `/app/scripts`); CI runs pytest from `backend/`, where
# it is one level up and on nobody's path. Without this the two enrichment
# script tests fail at collection in CI while passing everywhere locally,
# which is NORM-21's shape.
_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "scripts" / "seed.py").exists()
)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Must set DATABASE_URL before any app import since pydantic-settings
# reads the environment at class definition time.
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# ── In-memory SQLite engine ───────────────────────────────────────────────────

_SQLITE_URL = "sqlite:///:memory:"

_test_engine = create_engine(
    _SQLITE_URL,
    connect_args={"check_same_thread": False},
)

_TestSessionLocal = sessionmaker(
    bind=_test_engine,
    autocommit=False,
    autoflush=False,
)


def _create_test_tables() -> None:
    """Minimal schema without PostGIS geometry.

    Endpoint tests mock the service layer, so no spatial SQL runs here.
    """
    with _test_engine.connect() as conn:
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS parcels (
                    id               TEXT PRIMARY KEY,
                    address          TEXT NOT NULL,
                    normalized_address TEXT,
                    latitude         REAL NOT NULL
                        CHECK (latitude >= -90 AND latitude <= 90),
                    longitude        REAL NOT NULL
                        CHECK (longitude >= -180 AND longitude <= 180),
                    point            TEXT,
                    census_tract_id  TEXT,
                    county           TEXT,
                    state_fips       TEXT,
                    created_at       TEXT DEFAULT (datetime('now'))
                )
            """)
        )
        conn.execute(
            text("""
                -- `sources` is TEXT here and TEXT[] on PostgreSQL: SQLite has
                -- no array type, so the ORM stores the same list as a JSON
                -- array (see TimelineRequest.sources' with_variant). Both
                -- dialects can count its elements, which is the only thing
                -- the full-scope test reads.
                -- ck_timeline_requests_sources' `<@` half has no SQLite
                -- spelling and is not mirrored; the cardinality half is.
                CREATE TABLE IF NOT EXISTS timeline_requests (
                    id            TEXT PRIMARY KEY,
                    parcel_id     TEXT REFERENCES parcels(id),
                    status        TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'processing', 'complete',
                                          'partial', 'failed')),
                    sources       TEXT NOT NULL
                        DEFAULT '["census","landsat","naip","property","sentinel2","usgs_topo"]'
                        CHECK (json_array_length(sources) > 0),
                    origin        TEXT NOT NULL DEFAULT 'user'
                        CHECK (origin IN ('user', 'backfill', 'heal')),
                    deployed_sha  TEXT,
                    created_at    TEXT DEFAULT (datetime('now')),
                    updated_at    TEXT DEFAULT (datetime('now')),
                    completed_at  TEXT,
                    error_message TEXT
                )
            """)
        )
        conn.execute(
            text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_timeline_requests_parcel_inflight
                ON timeline_requests (parcel_id)
                WHERE status IN ('queued', 'processing')
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS timeline_request_tasks (
                    id                   TEXT PRIMARY KEY,
                    timeline_request_id  TEXT REFERENCES timeline_requests(id),
                    source               TEXT NOT NULL
                        CHECK (source IN ('naip', 'landsat', 'sentinel2',
                                          'census', 'property', 'usgs_topo')),
                    status               TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'processing', 'complete',
                                          'partial', 'failed', 'skipped')),
                    items_found          INTEGER DEFAULT 0,
                    queries_run          INTEGER,
                    queries_failed       INTEGER,
                    rows_returned        INTEGER,
                    rows_matched         INTEGER,
                    coverage             TEXT
                        CHECK (coverage IS NULL OR
                               coverage IN ('covered', 'not_covered', 'no_adapter')),
                    started_at           TEXT,
                    completed_at         TEXT,
                    error_message        TEXT,
                    UNIQUE (timeline_request_id, source)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS timeline_task_years (
                    id          TEXT PRIMARY KEY,
                    task_id     TEXT NOT NULL
                        REFERENCES timeline_request_tasks(id) ON DELETE CASCADE,
                    source      TEXT NOT NULL,
                    group_key   TEXT NOT NULL,
                    outcome     TEXT NOT NULL
                        CHECK (outcome IN ('ok', 'failed', 'absent',
                                           'indeterminate', 'suppressed')),
                    reason      TEXT,
                    detail      TEXT,
                    created_at  TEXT DEFAULT (datetime('now')),
                    UNIQUE (task_id, group_key)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_tty_source_group_outcome
                ON timeline_task_years (source, group_key, outcome)
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_tty_task
                ON timeline_task_years (task_id)
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS imagery_snapshots (
                    id                    TEXT PRIMARY KEY,
                    parcel_id             TEXT NOT NULL REFERENCES parcels(id),
                    source                TEXT NOT NULL
                        CHECK (source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')),
                    capture_date          TEXT NOT NULL,
                    stac_item_id          TEXT NOT NULL,
                    stac_collection       TEXT NOT NULL,
                    bbox                  TEXT,
                    cog_url               TEXT NOT NULL,
                    additional_cog_urls   TEXT,
                    thumbnail_url         TEXT,
                    resolution_m          REAL,
                    cloud_cover_pct       REAL,
                    created_at            TEXT DEFAULT (datetime('now')),
                    UNIQUE (parcel_id, stac_item_id)
                )
            """)
        )
        conn.execute(
            text("""
                -- `footprint` and `bbox` are geometry(POLYGON,4326) on
                -- PostgreSQL and plain TEXT here, the same way
                -- imagery_snapshots.bbox already is: no spatial SQL runs
                -- against this database.
                CREATE TABLE IF NOT EXISTS scenes (
                    id               TEXT PRIMARY KEY,
                    source           TEXT NOT NULL
                        CHECK (source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')),
                    collection       TEXT NOT NULL,
                    item_id          TEXT NOT NULL,
                    capture_date     TEXT NOT NULL,
                    footprint        TEXT,
                    bbox             TEXT,
                    cog_url          TEXT NOT NULL,
                    thumbnail_url    TEXT,
                    resolution_m     REAL,
                    cloud_cover_pct  REAL,
                    platform         TEXT,
                    provenance       TEXT NOT NULL
                        CHECK (provenance IN ('snapshot', 'mosaic_url',
                                              'enriched', 'selection')),
                    fetched_at       TEXT NOT NULL,
                    UNIQUE (collection, item_id)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_scenes_source_capture
                ON scenes (source, capture_date)
            """)
        )
        conn.execute(
            text("""
                -- ck_parcel_scenes_group_key is a POSIX regex on PostgreSQL,
                -- which SQLite has no operator for; GLOB expresses the same
                -- three shapes exactly, so the constraint is mirrored rather
                -- than dropped.
                -- `mosaic_scene_ids` is UUID[] on PostgreSQL and a JSON array
                -- here, per ParcelScene.mosaic_scene_ids' with_variant.
                CREATE TABLE IF NOT EXISTS parcel_scenes (
                    id               TEXT PRIMARY KEY,
                    parcel_id        TEXT NOT NULL
                        REFERENCES parcels(id) ON DELETE CASCADE,
                    source           TEXT NOT NULL
                        CHECK (source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')),
                    group_key        TEXT NOT NULL
                        CHECK (group_key GLOB '[0-9][0-9][0-9][0-9]'
                            OR group_key GLOB '[0-9][0-9][0-9][0-9]Q[1-4]'
                            OR group_key GLOB '[0-9][0-9][0-9][0-9]s'),
                    scene_id         TEXT NOT NULL REFERENCES scenes(id),
                    mosaic_scene_ids TEXT,
                    selected_at      TEXT NOT NULL,
                    selected_by      TEXT,
                    UNIQUE (parcel_id, source, group_key)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_parcel_scenes_scene
                ON parcel_scenes (scene_id)
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS census_snapshots (
                    id                       TEXT PRIMARY KEY,
                    parcel_id                TEXT NOT NULL REFERENCES parcels(id),
                    tract_fips               TEXT NOT NULL,
                    dataset                  TEXT NOT NULL
                        CHECK (dataset IN ('decennial', 'acs5')),
                    year                     INTEGER NOT NULL,
                    total_population         INTEGER,
                    median_household_income   INTEGER,
                    median_home_value        INTEGER,
                    median_year_built        INTEGER,
                    total_housing_units      INTEGER,
                    occupied_housing_units   INTEGER,
                    owner_occupied_units     INTEGER,
                    renter_occupied_units    INTEGER,
                    vacancy_rate             REAL,
                    median_age               REAL,
                    median_gross_rent        INTEGER,
                    raw_data                 TEXT,
                    created_at               TEXT DEFAULT (datetime('now')),
                    updated_at               TEXT DEFAULT (datetime('now')),
                    UNIQUE (parcel_id, dataset, year)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS property_events (
                    id                  TEXT PRIMARY KEY,
                    parcel_id           TEXT NOT NULL REFERENCES parcels(id),
                    event_type          TEXT NOT NULL
                        CHECK (event_type IN ('sale', 'permit_building',
                                              'permit_demolition', 'permit_electrical',
                                              'permit_mechanical', 'permit_plumbing',
                                              'permit_other', 'zoning_change',
                                              'assessment')),
                    event_date          TEXT,
                    sale_price          INTEGER,
                    permit_type         TEXT,
                    permit_description  TEXT,
                    permit_valuation    INTEGER,
                    description         TEXT,
                    source              TEXT NOT NULL,
                    source_record_id    TEXT,
                    raw_data            TEXT,
                    created_at          TEXT DEFAULT (datetime('now')),
                    UNIQUE (parcel_id, source, source_record_id)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_property_events_null_source_record
                ON property_events (parcel_id, source, event_type, event_date)
                WHERE source_record_id IS NULL
            """)
        )
        conn.commit()


_create_test_tables()


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Yield a session that rolls back after each test (transaction isolation)."""
    connection = _test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# Tables the committing fixture below truncates, children first.
_LEDGER_TEST_TABLES = (
    "timeline_task_years",
    "parcel_scenes",
    "scenes",
    "imagery_snapshots",
    "census_snapshots",
    "timeline_request_tasks",
    "timeline_requests",
    "parcels",
)


@pytest.fixture
def committing_db() -> Generator[sessionmaker[Session], None, None]:
    """A sessionmaker the code under test can open and commit through.

    The ``db`` fixture wraps each test in a transaction it rolls back, which
    the per-year ledger tests cannot use: the fetch loops open their own
    ``SessionLocal()`` and the upserts commit for themselves — that commit is
    the thing under test, since an ``ok`` ledger row is supposed to land in
    the same transaction as its snapshot. So this hands out real sessions and
    cleans up by deleting afterwards.
    """
    _truncate_ledger_tables()
    try:
        yield _TestSessionLocal
    finally:
        _truncate_ledger_tables()


def _truncate_ledger_tables() -> None:
    with _test_engine.connect() as conn:
        for table in _LEDGER_TEST_TABLES:
            conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608  # fixed table names
        conn.commit()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden DB and settings dependencies."""
    # Late imports to avoid circular issues at module load
    from app.config import Settings, get_settings
    from app.db import get_db
    from app.main import create_app

    # Clear the lru_cache so our test settings take effect
    get_settings.cache_clear()

    def override_get_settings() -> Settings:
        return Settings(
            database_url="postgresql://test:test@localhost/test",
            redis_url="redis://localhost:6379/0",
            app_env="development",
            log_level="WARNING",
        )

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    get_settings.cache_clear()


def seed_served_scene(
    db: Session,
    *,
    parcel_id: uuid.UUID | str,
    source: str,
    capture_date: date,
    stac_item_id: str,
    stac_collection: str,
    cog_url: str,
    group_key: str | None = None,
    thumbnail_url: str | None = None,
    resolution_m: float | None = None,
    cloud_cover_pct: float | None = None,
    mosaic_cog_urls: Sequence[str] = (),
) -> uuid.UUID:
    """Seed one served period in the normalized shape, and return its id.

    The id the serving reads hand out is ``parcel_scenes.id`` since the ADR
    0001 step-3 cutover, so a test that needs "the id of a snapshot this
    parcel serves" has to write ``scenes`` and ``parcel_scenes`` rather than
    ``imagery_snapshots``. Raw SQL for the reason every other seed here uses
    it: the ORM's UUID and geometry handling do not match this TEXT-typed
    SQLite database.

    ``group_key`` defaults to the year, which is what every source but
    ``usgs_topo`` groups by; pass ``'1950s'`` for a topo row.
    """
    from app.services.imagery import encode_group_key

    scene_ids: list[str] = []
    for url in (cog_url, *mosaic_cog_urls):
        scene_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO scenes (id, source, collection, item_id, capture_date,"
                " cog_url, thumbnail_url, resolution_m, cloud_cover_pct, provenance,"
                " fetched_at)"
                " VALUES (:id, :source, :collection, :item_id, :capture_date,"
                " :cog_url, :thumbnail_url, :resolution_m, :cloud_cover_pct,"
                " 'snapshot', :fetched_at)"
            ),
            {
                "id": scene_id,
                "source": source,
                "collection": stac_collection,
                # Mosaic tiles are first-class scenes with ids of their own.
                "item_id": stac_item_id if not scene_ids else f"{stac_item_id}_t{len(scene_ids)}",
                "capture_date": capture_date.isoformat(),
                "cog_url": url,
                "thumbnail_url": thumbnail_url if not scene_ids else None,
                "resolution_m": resolution_m,
                "cloud_cover_pct": cloud_cover_pct,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )
        scene_ids.append(scene_id)

    served_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id,"
            " mosaic_scene_ids, selected_at, selected_by)"
            " VALUES (:id, :parcel_id, :source, :group_key, :scene_id, :mosaic,"
            " :selected_at, NULL)"
        ),
        {
            "id": str(served_id),
            "parcel_id": str(parcel_id),
            "source": source,
            "group_key": group_key or encode_group_key("year", capture_date),
            "scene_id": scene_ids[0],
            "mosaic": json.dumps(scene_ids[1:]) if len(scene_ids) > 1 else None,
            "selected_at": datetime.now(UTC).isoformat(),
        },
    )
    db.flush()
    return served_id
