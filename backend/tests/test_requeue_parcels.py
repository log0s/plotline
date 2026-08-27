"""Deployment-gate tests for scripts/requeue_parcels.py.

The script lives outside the backend package, so it is loaded by path.
Every test exercises ``_check_deploy_gate`` directly: the gate runs before
any database access, so nothing here needs a session.

The health fetch moved to ``app.services.deploy``; these patch ``httpx.get``
on the module itself, which both that module and this script resolve
through, so the gate's behaviour is still what is under test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

_HERE = Path(__file__).resolve()
# Repo layout puts scripts/ beside backend/; the container copies it to /app/scripts.
_SCRIPT = next(
    p / "scripts" / "requeue_parcels.py"
    for p in _HERE.parents
    if (p / "scripts" / "requeue_parcels.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("requeue_parcels", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["requeue_parcels"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _health(sha: str, status_code: int = 200) -> _Response:
    return _Response(status_code, {"status": "ok", "version": {"sha": sha}})


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record health calls, failing loudly if one is made unexpectedly."""
    calls: list[str] = []

    def _get(url: str, **kwargs: Any) -> _Response:
        calls.append(url)
        raise AssertionError(f"unexpected health request to {url}")

    monkeypatch.setattr(httpx, "get", _get)
    return calls


def test_matching_sha_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _health("abc123def456"))
    script._check_deploy_gate("http://api:8000", "abc123", skip=False)


def test_mismatched_sha_refuses(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _health("abc123def456"))
    with pytest.raises(SystemExit) as exc:
        script._check_deploy_gate("http://api:8000", "999999", skip=False)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "REFUSING" in err
    assert "abc123def456" in err


def test_unreachable_health_refuses(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def _boom(*a: Any, **k: Any) -> _Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _boom)
    with pytest.raises(SystemExit) as exc:
        script._check_deploy_gate("http://api:8000", "abc123", skip=False)
    assert exc.value.code == 1
    assert "could not reach" in capsys.readouterr().err


def test_unknown_sha_refuses(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _health("unknown"))
    with pytest.raises(SystemExit) as exc:
        script._check_deploy_gate("http://api:8000", "abc123", skip=False)
    assert exc.value.code == 1
    assert "unknown" in capsys.readouterr().err


def test_skip_deploy_check_proceeds_without_calling_health(no_http: list[str]) -> None:
    script._check_deploy_gate("http://api:8000", None, skip=True)
    assert no_http == []


def test_gate_runs_for_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run still reports whether the real run would be allowed."""
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _health("abc123def456"))
    monkeypatch.setattr(
        sys, "argv", ["requeue_parcels.py", "--dry-run", "--require-sha", "999999", "not-a-uuid"]
    )
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 1


def test_groups_without_from_ledger_refuses(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["requeue_parcels.py", "--skip-deploy-check", "not-a-uuid", "--groups", "2000"],
    )
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 2
    assert "--groups only means something with --from-ledger" in capsys.readouterr().err


def test_bare_invocation_refuses_naming_both_flags(no_http: list[str], capsys: Any) -> None:
    with pytest.raises(SystemExit) as exc:
        script._check_deploy_gate("http://api:8000", None, skip=False)
    assert exc.value.code == 1
    assert no_http == []
    err = capsys.readouterr().err
    assert "--require-sha" in err
    assert "--skip-deploy-check" in err
    assert "wrong granules" in err


def test_both_flags_refuse(no_http: list[str], capsys: Any) -> None:
    with pytest.raises(SystemExit) as exc:
        script._check_deploy_gate("http://api:8000", "abc123", skip=True)
    assert exc.value.code == 1
    assert no_http == []
    assert "mutually exclusive" in capsys.readouterr().err


# ── --sources and --from-ledger ──────────────────────────────────────────────


def test_sources_rejects_an_unknown_value(
    monkeypatch: pytest.MonkeyPatch, no_http: list[str], capsys: Any
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "requeue_parcels.py",
            "--skip-deploy-check",
            "--sources",
            "naip,not_a_source",
            "00000000-0000-0000-0000-000000000000",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 2
    assert "invalid --sources value(s): not_a_source" in capsys.readouterr().err
    assert no_http == []


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["--sources", "naip", "{pid}"],
        ["{pid}", "--sources", "naip"],
    ],
)
def test_sources_does_not_swallow_a_trailing_parcel_id(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, argv_tail: list[str]
) -> None:
    """HEAL-1/HEAL-2: with nargs='+', ``--sources naip <id>`` used to consume
    the id as a second (invalid) source. A single comma-separated flag value
    can't do that — both token orders must select the same scope."""
    pid = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(script, "_known_parcels", lambda ids: set(ids))
    argv = ["requeue_parcels.py", "--skip-deploy-check", "--dry-run"]
    argv += [tok.format(pid=pid) for tok in argv_tail]
    monkeypatch.setattr(sys, "argv", argv)

    script.main()

    out = capsys.readouterr().out
    assert f"would re-queue: {pid} [naip]" in out


def test_sources_speaks_the_ledgers_vocabulary() -> None:
    """``census_decennial`` is a legal --sources value and expands to the two
    census ledger sources only when the operator asked for ``census``."""
    assert "census_decennial" in script.SELECTABLE_SOURCES
    assert script.ledger_filter(["census_decennial"]) == {"census_decennial"}
    assert script.ledger_filter(["census"]) == {"census_acs5", "census_decennial"}
    assert script.ledger_filter(["naip", "landsat"]) == {"naip", "landsat"}
    assert script.ledger_filter(None) is None


def test_ledger_selection_is_scoped_per_parcel(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two parcels, different damage: each gets its own scope, not the union.

    Delete the per-parcel ``setdefault`` in ``select_from_ledger`` and both
    parcels would be re-queued with both sources — half of it pointless work
    against a source that is fine.
    """
    from tests.test_ledger_selection import _parcel, _record, _run

    monkeypatch.setattr(script, "SessionLocal", committing_db)

    landsat_parcel = _parcel(committing_db)
    census_parcel = _parcel(committing_db)
    landsat_tasks = _run(committing_db, landsat_parcel, sources=("landsat",), age_hours=2)
    census_tasks = _run(committing_db, census_parcel, sources=("census",), age_hours=2)
    _record(committing_db, landsat_tasks["landsat"], "landsat", "1993", "failed", "read_timeout")
    _record(committing_db, census_tasks["census"], "census_decennial", "2000", "failed", "sign_5xx")

    selected = script.select_from_ledger(
        [], None, include_cloud_filtered=False, include_absent_api=False
    )

    assert sorted(selected[landsat_parcel]) == ["landsat"]
    assert sorted(selected[census_parcel]) == ["census"]


def test_from_ledger_needs_the_flag_to_reach_absent_api(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decennial-2000 case. Without --include-absent-api the selection is
    empty; with it the parcel appears scoped to census."""
    from tests.test_ledger_selection import _parcel, _record, _run

    monkeypatch.setattr(script, "SessionLocal", committing_db)

    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=2)
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")

    without = script.select_from_ledger(
        [], ["census_decennial"], include_cloud_filtered=False, include_absent_api=False
    )
    with_flag = script.select_from_ledger(
        [], ["census_decennial"], include_cloud_filtered=False, include_absent_api=True
    )

    assert without == {}
    assert sorted(with_flag[parcel_id]) == ["census"]
    assert len(with_flag[parcel_id]["census"]) == 1


def test_groups_narrows_selection_within_a_source(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--groups`` is operator scope on top of the retry policy, not a
    substitute for the stale filter — see test_ledger_selection.py's Y3
    tests for that half."""
    from tests.test_ledger_selection import _parcel, _record, _run

    monkeypatch.setattr(script, "SessionLocal", committing_db)

    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("landsat",), age_hours=2)
    _record(committing_db, tasks["landsat"], "landsat", "1993", "failed", "read_timeout")
    _record(committing_db, tasks["landsat"], "landsat", "1994", "failed", "read_timeout")

    narrowed = script.select_from_ledger(
        [], None, include_cloud_filtered=False, include_absent_api=False, groups=["1993"]
    )

    assert [g.group_key for g in narrowed[parcel_id]["landsat"]] == ["1993"]


def test_from_ledger_narrows_to_the_ids_given(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_ledger_selection import _parcel, _record, _run

    monkeypatch.setattr(script, "SessionLocal", committing_db)

    wanted = _parcel(committing_db)
    other = _parcel(committing_db)
    for parcel_id in (wanted, other):
        tasks = _run(committing_db, parcel_id, sources=("landsat",), age_hours=2)
        _record(committing_db, tasks["landsat"], "landsat", "1993", "failed", "read_timeout")

    selected = script.select_from_ledger(
        [wanted], None, include_cloud_filtered=False, include_absent_api=False
    )

    assert list(selected) == [wanted]
