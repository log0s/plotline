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

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

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
                CREATE TABLE IF NOT EXISTS timeline_requests (
                    id            TEXT PRIMARY KEY,
                    parcel_id     TEXT REFERENCES parcels(id),
                    status        TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'processing', 'complete', 'failed')),
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
                                          'failed', 'skipped')),
                    items_found          INTEGER NOT NULL DEFAULT 0,
                    started_at           TEXT,
                    completed_at         TEXT,
                    error_message        TEXT,
                    UNIQUE (timeline_request_id, source)
                )
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
