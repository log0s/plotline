"""``scripts/ledger_gaps.py``'s stale bucket (Y3).

The script lives outside the backend package, so it is loaded by path,
matching ``test_requeue_parcels.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tests.test_ledger_selection import _parcel, _record, _run

_HERE = Path(__file__).resolve()
_SCRIPT = next(p / "scripts" / "ledger_gaps.py" for p in _HERE.parents if (p / "scripts").exists())


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ledger_gaps", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ledger_gaps"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def test_a_retired_year_is_reported_stale_not_hidden(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(script, "SessionLocal", committing_db)

    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=2)
    _record(committing_db, tasks["census"], "census_decennial", "1990", "absent", "api_no_data")
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")

    rows = script._fetch(None, None, None)
    by_group = {r.group_key: r for r in rows if r.parcel_id == str(parcel_id)}

    assert by_group["1990"].stale is True
    assert by_group["2000"].stale is False


def test_stale_bucket_prints_the_retired_group(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(script, "SessionLocal", committing_db)

    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=2)
    _record(committing_db, tasks["census"], "census_decennial", "1990", "absent", "api_no_data")

    rows = script._fetch(None, str(parcel_id), None)
    script._print_stale(rows)

    out = capsys.readouterr().out
    assert "1 stale" in out
    assert "census_decennial" in out
    assert "1990" in out


def test_stale_bucket_is_silent_when_nothing_is_stale(
    committing_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(script, "SessionLocal", committing_db)

    parcel_id = _parcel(committing_db)
    tasks = _run(committing_db, parcel_id, sources=("census",), age_hours=2)
    _record(committing_db, tasks["census"], "census_decennial", "2000", "absent", "api_no_data")

    rows = script._fetch(None, str(parcel_id), None)
    script._print_stale(rows)

    assert capsys.readouterr().out == ""
