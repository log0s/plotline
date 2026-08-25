"""Scripts must install a root log handler, or their logging goes nowhere.

The admission-wait line carries ``depth`` and ``cap`` so a full queue can be
watched while a sweep rides it out (``d6b21b3``). The 2026-08-25 completion
sweep waited 112 times and printed none of them: no script called anything
that installs a root handler, so the root logger sat at WARNING with no
handler and every INFO record died before formatting.

The assertion is therefore about **stdout**, not ``caplog``. pytest attaches
its own capture handler to the root logger, so a caplog-based test passes
with the fix deleted — it would be testing pytest's plumbing rather than the
script's. Only a script's real output stream can tell the two apart.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.services import admission as admission_service

_HERE = Path(__file__).resolve()
_SCRIPTS = next(p / "scripts" for p in _HERE.parents if (p / "scripts" / "seed.py").exists())

# Every entry point in scripts/, and whether it is expected to configure
# logging. seed.py is the one deliberate exception: it imports nothing from
# app and emits no log records (see the comment in its main()).
ENTRY_POINTS = sorted(p.name for p in _SCRIPTS.glob("*.py"))
NO_LOGGING_BY_DESIGN = {"seed.py"}


def _load_script(name: str) -> ModuleType:
    path = _SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def restore_logging() -> Any:
    """Undo whatever the script under test does to the root logger."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def test_every_script_entry_point_configures_logging() -> None:
    """A new script that logs into the void fails here rather than in prod."""
    missing = [
        name
        for name in ENTRY_POINTS
        if name not in NO_LOGGING_BY_DESIGN
        and "configure_script_logging()" not in (_SCRIPTS / name).read_text()
    ]
    assert not missing, f"scripts with no root log handler: {missing}"


def test_admission_wait_reaches_stdout_with_depth_and_cap(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restore_logging: None,
) -> None:
    """Run requeue_parcels.main() over a full queue; the wait must be visible."""
    script = _load_script("requeue_parcels.py")
    parcel_id = uuid.uuid4()

    settings = Settings(  # type: ignore[call-arg]  # the rest come from the test env
        database_url="postgresql://t:t@localhost/t",
        max_inflight_timeline_requests=30,
    )
    depths = iter([30, 30, 0])
    monkeypatch.setattr(admission_service, "inflight_depth", lambda db: next(depths))

    def fake_create(db: Any, pid: uuid.UUID, *, deadline: float) -> tuple[Any, bool]:
        admission_service.wait_for_admission_slot(
            db,
            settings,
            deadline=deadline,
            sleeper=lambda seconds: None,
            clock=lambda: 0.0,
        )
        return SimpleNamespace(id=uuid.uuid4()), True

    monkeypatch.setattr(script, "_check_deploy_gate", lambda *a, **k: None)
    monkeypatch.setattr(script, "_known_parcels", lambda ids: set(ids))
    monkeypatch.setattr(script, "SessionLocal", lambda: _NullSession())
    monkeypatch.setattr(script.imagery_service, "create_queued_request_waiting", fake_create)
    monkeypatch.setattr(script.imagery_service, "dispatch_timeline_task", lambda db, r: True)
    monkeypatch.setattr(sys, "argv", ["requeue_parcels.py", "--skip-deploy-check", str(parcel_id)])

    script.main()

    out = capsys.readouterr().out
    assert "Waiting for an admission slot" in out
    assert "depth" in out and "30" in out
    assert "cap" in out


def test_script_logging_is_info_regardless_of_log_level(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restore_logging: None,
) -> None:
    """A production-tuned LOG_LEVEL must not silence a script's INFO lines."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from app.logging_config import configure_script_logging

    settings = Settings(  # type: ignore[call-arg]  # the rest come from the test env
        database_url="postgresql://t:t@localhost/t",
        app_env="production",
        log_level="WARNING",
    )
    configure_script_logging(settings)

    logger = logging.getLogger("test_script_logging")
    logger.info("heal_script_started")

    assert "heal_script_started" in capsys.readouterr().out


class _NullSession:
    def __enter__(self) -> _NullSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
