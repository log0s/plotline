"""Tests for scripts/remove_unverified_reverse_parcels.py (security audit SEC-5, B3).

Delete-the-fix: removing the ``if inconclusive: raise EvidenceError`` guard in
``run`` makes ``test_inconclusive_candidate_refuses_the_whole_run`` fail.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

_SCRIPT = next(
    p
    for p in (
        Path(__file__).resolve().parents[2] / "scripts" / "remove_unverified_reverse_parcels.py",
        Path("/app/scripts/remove_unverified_reverse_parcels.py"),
    )
    if p.exists()
)


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("remove_unverified_reverse_parcels", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _insert(db: Session, address: str, normalized: str, lat: float, lon: float) -> str:
    pid = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO parcels (id, address, normalized_address, latitude, longitude, point)"
            " VALUES (:id, :a, :n, :lat, :lon, 'POINT(0 0)')"
        ),
        {"id": pid, "a": address, "n": normalized, "lat": lat, "lon": lon},
    )
    db.commit()
    return pid


def _count(db: Session) -> int:
    return int(db.execute(text("SELECT count(*) FROM parcels")).scalar_one())


def test_candidates_are_the_reverse_path_signature(script: ModuleType, db: Session) -> None:
    _insert(db, "1 Main St", "1 MAIN ST, DENVER, CO, 80202", 39.7, -105.0)  # forward path
    rev = _insert(db, "zzz", "zzz", 39.7, -105.0)
    assert [c.id for c in script.find_candidates(db)] == [rev]


def test_dry_run_deletes_nothing_and_never_calls_photon(script: ModuleType, db: Session) -> None:
    _insert(db, "zzz", "zzz", 39.7, -105.0)
    with patch.object(script, "verify") as verify:
        assert script.run(db, do_verify=False, execute=False) == 0
    verify.assert_not_called()
    assert _count(db) == 1


def test_execute_without_verify_is_refused(script: ModuleType, db: Session) -> None:
    _insert(db, "zzz", "zzz", 39.7, -105.0)
    with pytest.raises(script.EvidenceError):
        script.run(db, do_verify=False, execute=True)
    assert _count(db) == 1


def test_assess_condemns_only_points_far_from_every_suggestion(script: ModuleType) -> None:
    near = script.Candidate("a", "x", 39.7, -105.0, "t")
    far = script.Candidate("b", "x", 39.7, -105.0, "t")
    script.assess(near, [(39.7005, -105.0)])  # ~55 m
    script.assess(far, [(39.71, -105.0)])  # ~1.1 km
    assert not near.condemned and far.condemned


def test_inconclusive_candidate_refuses_the_whole_run(script: ModuleType, db: Session) -> None:
    _insert(db, "far", "far", 39.7, -105.0)
    _insert(db, "unknown", "unknown", 39.7, -105.0)

    def fake_points(_client: object, address: str) -> list[tuple[float, float]]:
        if address == "unknown":
            raise script.httpx.ConnectError("offline")
        return [(39.71, -105.0)]

    with (
        patch.object(script, "photon_points", side_effect=fake_points),
        patch.object(script.time, "sleep"),
        pytest.raises(script.EvidenceError),
    ):
        script.run(db, do_verify=True, execute=True)
    assert _count(db) == 2


def test_execute_deletes_only_condemned_rows(script: ModuleType, db: Session) -> None:
    far = _insert(db, "far", "far", 39.7, -105.0)
    near = _insert(db, "near", "near", 39.7, -105.0)

    def fake_points(_client: object, address: str) -> list[tuple[float, float]]:
        return [(39.71, -105.0)] if address == "far" else [(39.7001, -105.0)]

    with (
        patch.object(script, "photon_points", side_effect=fake_points),
        patch.object(script.time, "sleep"),
    ):
        assert script.run(db, do_verify=True, execute=True) == 1
    ids = {str(r[0]) for r in db.execute(text("SELECT id FROM parcels")).all()}
    assert ids == {near}
    assert far not in ids
