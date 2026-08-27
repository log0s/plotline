"""Tests for scripts/backfill_census_housing.py.

The script lives outside the backend package, so it is loaded by path — the
same pattern as ``test_revalidate_landsat.py``.

This file exists to close the Y7 UNVERIFIED register's entry 1
(``docs/audits/2026-08-y7-y8/REPORT.md``), which recorded the script's
``deployed_sha`` write as confirmed by code reading only, on the grounds that
"the SQLite in-memory fixture the rest of the suite uses is not reachable from
a script-level ``SessionLocal``". That is true of ``app.db.SessionLocal``
itself and false of the script: ``from app.db import SessionLocal`` binds a
name **on the script module**, and rebinding that attribute is exactly what
``test_revalidate_landsat.py:178`` already does. The gap was a missing test,
not a missing seam.

Delete-the-fix: drop ``deployed_sha=get_settings().git_sha`` from
``_timeline_request_id`` and ``test_new_request_records_the_deployed_sha``
fails on the ``is not None`` assertion — the column falls back to NULL, which
``services/ledger.same_deployed_sha`` reads as "changed", making every absent
outcome the heal wrote look retryable forever.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType

from sqlalchemy import text
from sqlalchemy.orm import Session

_HERE = Path(__file__).resolve()
# Repo layout puts scripts/ beside backend/; the container copies it to /app/scripts.
_SCRIPT = next(
    p / "scripts" / "backfill_census_housing.py"
    for p in _HERE.parents
    if (p / "scripts" / "backfill_census_housing.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_census_housing", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_census_housing"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


class _BoundSessionFactory:
    """Stand in for ``SessionLocal``, handing back the test's own session.

    The script opens sessions itself (``with SessionLocal() as db``), so the
    fixture session has to arrive through the name it calls.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def __call__(self) -> _BoundSessionFactory:
        return self

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc: object) -> bool:
        return False


def _parcel(db: Session) -> uuid.UUID:
    parcel_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude, point) "
            "VALUES (:id, 'x', 39.7, -105.0, 'POINT(-105.0 39.7)')"
        ),
        {"id": str(parcel_id)},
    )
    db.commit()
    return parcel_id


def test_new_request_records_the_deployed_sha(db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]  # pytest fixture type
    """A heal that creates its own request stamps the SHA it ran under."""
    from app.config import get_settings

    monkeypatch.setattr(script, "SessionLocal", _BoundSessionFactory(db))
    parcel_id = _parcel(db)

    request_id = script._timeline_request_id(str(parcel_id))

    # Read back through the ORM: SQLAlchemy's UUID type stores dashless hex on
    # SQLite, so a raw-SQL lookup by the dashed string the script returns
    # finds nothing here even though it is the same row.
    from app.models.parcels import TimelineRequest

    request = db.get(TimelineRequest, uuid.UUID(request_id))
    assert request is not None
    assert str(request.parcel_id) == str(parcel_id)
    assert request.deployed_sha is not None
    assert request.deployed_sha == get_settings().git_sha


def test_existing_request_is_reused_and_not_restamped(db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]  # pytest fixture type
    """Reuse is the common path and must not invent a second request.

    The SHA on an existing row belongs to the run that created it; rewriting
    it here would date a stale outcome to today's deploy, which is the exact
    failure ``deployed_sha`` exists to prevent.
    """
    monkeypatch.setattr(script, "SessionLocal", _BoundSessionFactory(db))
    parcel_id = _parcel(db)
    existing_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO timeline_requests (id, parcel_id, status, sources, deployed_sha) "
            "VALUES (:id, :parcel_id, 'complete', '[\"census\"]', 'older-sha')"
        ),
        {"id": str(existing_id), "parcel_id": str(parcel_id)},
    )
    db.commit()

    request_id = script._timeline_request_id(str(parcel_id))

    assert request_id == str(existing_id)
    assert (
        db.execute(
            text("SELECT count(*) FROM timeline_requests WHERE parcel_id = :pid"),
            {"pid": str(parcel_id)},
        ).scalar()
        == 1
    )
    assert (
        db.execute(
            text("SELECT deployed_sha FROM timeline_requests WHERE id = :id"),
            {"id": str(existing_id)},
        ).scalar()
        == "older-sha"
    )
