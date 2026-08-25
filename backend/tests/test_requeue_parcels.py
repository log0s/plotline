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
