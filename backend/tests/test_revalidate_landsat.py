"""Tests for scripts/revalidate_landsat.py.

The script lives outside the backend package, so it is loaded by path.

Delete-the-fix: replace ``create_queued_request_waiting`` with
``_create_queued_request`` in the enqueue loop, or drop the ``except
AdmissionRefused`` arm, and
``test_wait_budget_exhausted_names_the_parcels_not_reached`` fails — the
refusal escapes ``main`` as a traceback instead of an unreached report, which
is exactly what the 2026-08-25 sweep did at parcel 31 of 184.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.admission import AdmissionRefused

_HERE = Path(__file__).resolve()
# Repo layout puts scripts/ beside backend/; the container copies it to /app/scripts.
_SCRIPT = next(
    p / "scripts" / "revalidate_landsat.py"
    for p in _HERE.parents
    if (p / "scripts" / "revalidate_landsat.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("revalidate_landsat", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["revalidate_landsat"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

CUTOFF = datetime(2026, 8, 25, 18, 57, 59, tzinfo=UTC)


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


def _request(db: Session, parcel_id: uuid.UUID, created_at: datetime, status: str) -> None:
    db.execute(
        text(
            "INSERT INTO timeline_requests (id, parcel_id, status, created_at, updated_at) "
            "VALUES (:id, :parcel_id, :status, :created_at, :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "parcel_id": str(parcel_id),
            "status": status,
            "created_at": created_at,
        },
    )
    db.commit()


# ── The skip filter ───────────────────────────────────────────────────────────


def test_swept_since_excludes_only_parcels_completed_after_the_cutoff(db: Session) -> None:
    after = _parcel(db)
    before = _parcel(db)
    both = _parcel(db)
    never = _parcel(db)

    _request(db, after, CUTOFF + timedelta(minutes=12), "complete")
    _request(db, before, CUTOFF - timedelta(hours=3), "complete")
    # Swept under the new deploy, then re-run under something older: the
    # *latest* complete request is what decides, so this one is not swept.
    _request(db, both, CUTOFF + timedelta(minutes=5), "complete")
    _request(db, both, CUTOFF - timedelta(minutes=5), "complete")
    _request(db, never, CUTOFF - timedelta(days=1), "complete")

    assert script.swept_since(db, CUTOFF) == {after, both}


def test_swept_since_ignores_requests_that_did_not_complete(db: Session) -> None:
    failed = _parcel(db)
    queued = _parcel(db)
    _request(db, failed, CUTOFF + timedelta(minutes=1), "failed")
    _request(db, queued, CUTOFF + timedelta(minutes=1), "queued")

    assert script.swept_since(db, CUTOFF) == set()


# ── Resolving a SHA to a cutoff ───────────────────────────────────────────────


def _version(sha: str, built: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(sha=sha, built=built)


def test_resolve_cutoff_returns_the_build_time_of_a_matching_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script, "fetch_deployed_version", lambda url: _version("bc1125cdabc", CUTOFF)
    )
    assert script.resolve_cutoff("http://api", "bc1125c") == CUTOFF


def test_resolve_cutoff_refuses_when_prod_runs_a_different_sha(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "fetch_deployed_version", lambda url: _version("deadbeef", CUTOFF))
    with pytest.raises(SystemExit) as exc_info:
        script.resolve_cutoff("http://api", "bc1125c")

    assert exc_info.value.code == 1
    assert "deadbeef" in capsys.readouterr().err


def test_resolve_cutoff_refuses_an_image_with_no_build_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "fetch_deployed_version", lambda url: _version("bc1125cdabc", None))
    with pytest.raises(SystemExit) as exc_info:
        script.resolve_cutoff("http://api", "bc1125c")

    assert exc_info.value.code == 1
    assert "--since" in capsys.readouterr().err


# ── The wait budget ───────────────────────────────────────────────────────────


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
    parcels: list[uuid.UUID],
    enqueue: Any,
    argv: list[str] | None = None,
) -> None:
    monkeypatch.setattr(script, "SessionLocal", _BoundSessionFactory(db))
    monkeypatch.setattr(script, "landsat_parcels", lambda _db: parcels)
    monkeypatch.setattr(
        script.imagery_service, "create_queued_request_waiting", enqueue, raising=True
    )
    monkeypatch.setattr(script.imagery_service, "dispatch_timeline_task", lambda _db, _req: True)
    monkeypatch.setattr(sys, "argv", ["revalidate_landsat.py", *(argv or [])])
    script.main()


def test_wait_budget_exhausted_names_the_parcels_not_reached(
    db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parcels = [uuid.uuid4() for _ in range(3)]
    seen: list[uuid.UUID] = []

    def enqueue(_db: Session, parcel_id: uuid.UUID, **kwargs: Any) -> Any:
        seen.append(parcel_id)
        if len(seen) > 1:
            raise AdmissionRefused("queue_full", depth=30)
        return SimpleNamespace(id=uuid.uuid4()), True

    with pytest.raises(SystemExit) as exc_info:
        _run_main(monkeypatch, db, parcels, enqueue, ["--max-wait-minutes", "0"])

    assert exc_info.value.code == 1, "an incomplete sweep must not exit 0"
    captured = capsys.readouterr()
    assert "queued 1 timeline request" in captured.out
    # The two it never reached are named, so the operator can resume.
    assert f"unreached: {parcels[1]}" in captured.err
    assert f"unreached: {parcels[2]}" in captured.err
    assert str(parcels[0]) not in captured.err
    assert seen == parcels[:2], "the sweep stops at the refusal, it does not skip past it"


def test_a_sweep_that_reaches_every_parcel_exits_cleanly(
    db: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parcels = [uuid.uuid4() for _ in range(3)]

    def enqueue(_db: Session, parcel_id: uuid.UUID, **kwargs: Any) -> Any:
        return SimpleNamespace(id=uuid.uuid4()), True

    _run_main(monkeypatch, db, parcels, enqueue)

    captured = capsys.readouterr()
    assert "queued 3 timeline request(s)" in captured.out
    assert "unreached" not in captured.err


def test_the_wait_deadline_is_passed_through_from_the_flag(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    parcels = [uuid.uuid4()]
    deadlines: list[float] = []

    def enqueue(_db: Session, parcel_id: uuid.UUID, **kwargs: Any) -> Any:
        deadlines.append(kwargs["deadline"])
        return SimpleNamespace(id=uuid.uuid4()), True

    monkeypatch.setattr(script.time, "monotonic", lambda: 1000.0)
    _run_main(monkeypatch, db, parcels, enqueue, ["--max-wait-minutes", "90"])

    assert deadlines == [1000.0 + 90 * 60]
