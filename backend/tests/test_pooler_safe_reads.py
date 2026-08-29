"""Read-only intent must be transaction-scoped, because production is pooled.

NORM-30: ``SET default_transaction_read_only = on``, committed, is a *session*
GUC. Production's ``DATABASE_URL`` is Neon's transaction-mode pooler, where a
transaction borrows a server-side backend and hands it back at COMMIT — so the
GUC outlives the client that set it and applies to whoever borrows that backend
next. The probe that was meant to prove a read was safe made a shared
production backend read-only and killed an authorized write on its next batch
(``docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT-3.md`` §6b).

Two tests, because the property has two halves and neither implies the other:

* **Textual** — no script issues a session-level ``SET``. This is a grep-shaped
  assertion on purpose, the same class as ``test_script_logging.py``'s root
  handler guard: the property *is* textual (what statement the source sends),
  and a behavioural version would need a pooler in the test rig to observe the
  leak at all.
* **Behavioural** — against a real Postgres, ``SET TRANSACTION READ ONLY``
  actually blocks a write, and the session is clean once the transaction ends.
  SQLite cannot express either half (NORM-29: state the limit, do not fake it),
  so this half skips without ``TEST_POSTGRES_URL`` — and fails rather than
  skips in CI, which sets it.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import InternalError
from sqlalchemy.pool import NullPool

_HERE = Path(__file__).resolve()
_SCRIPTS = next(p / "scripts" for p in _HERE.parents if (p / "scripts" / "seed.py").exists())
_BACKEND = _HERE.parents[1]

_MAINTENANCE_URL = os.environ.get("TEST_POSTGRES_URL")

requires_postgres = pytest.mark.skipif(
    not _MAINTENANCE_URL,
    reason="TEST_POSTGRES_URL is not set",
)

# A session-level SET, in the forms that reach a backend and stay there:
# psycopg2's set_session(), an explicit SET SESSION, and a bare SET of a GUC.
# SET LOCAL and SET TRANSACTION are transaction-scoped and therefore allowed.
#
# The bare-GUC branch is anchored to a quote so it means "this SQL string
# *starts* with SET" — unanchored it fires on every `UPDATE … SET col = :v` in
# the repo, which is how it first ran here.
_SESSION_SET = re.compile(
    r"""
      \.set_session\s*\(
    | SET \s+ SESSION \s+ (?! = ) [A-Za-z_]
    | ["'] \s* SET \s+ (?! LOCAL\b | TRANSACTION\b | CONSTRAINTS\b )
      [A-Za-z_][A-Za-z_0-9.]* \s* (?: = | \s TO \b )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _load_script(name: str) -> ModuleType:
    path = _SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _offending_lines(path: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if _SESSION_SET.search(line)
    ]


def test_no_script_issues_a_session_level_set() -> None:
    """A new script that sets a session GUC fails here, not in production."""
    offenders = [line for p in sorted(_SCRIPTS.glob("*.py")) for line in _offending_lines(p)]
    assert not offenders, (
        "session-level SET leaks through the production pooler (NORM-30); "
        f"use SET LOCAL / SET TRANSACTION instead: {offenders}"
    )


def test_no_app_code_issues_a_session_level_set() -> None:
    """Same rule for the app: every prod connection goes through the pooler."""
    offenders = [
        line for p in sorted((_BACKEND / "app").rglob("*.py")) for line in _offending_lines(p)
    ]
    assert not offenders, f"session-level SET in app code (NORM-30): {offenders}"


def test_the_postgres_half_is_not_silently_skipped() -> None:
    """In CI the behavioural half is required — a missing URL must fail."""
    if os.environ.get("CI") and not _MAINTENANCE_URL:
        pytest.fail(
            "TEST_POSTGRES_URL is not set, so the read-only scoping test would "
            "skip. CI must run it; see .github/workflows/deploy.yml."
        )


def test_the_regex_would_catch_the_statement_that_caused_norm30(tmp_path: Path) -> None:
    """The guard is only worth having if it fails on the original defect."""
    sample = tmp_path / "regression.py"
    sample.write_text(
        'db.execute(sa_text("SET default_transaction_read_only = on"))\n'
        'cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")\n'
        "conn.set_session(readonly=True)\n"
        "db.execute(sa_text(\"SET LOCAL statement_timeout = '2s'\"))\n"
        'db.execute(sa_text("SET TRANSACTION READ ONLY"))\n'
    )
    caught = _offending_lines(sample)
    assert len(caught) == 3, caught


@requires_postgres
def test_transaction_read_only_blocks_a_write_and_does_not_survive_the_transaction() -> None:
    """The script's own statement: enforced inside, gone outside.

    Both halves on one connection, so the second is a real observation of
    leakage rather than a fresh session that never had the flag. Under the old
    committed session GUC the write would still fail after the transaction
    ended and the last assertion would fail.
    """
    assert _MAINTENANCE_URL  # narrowed for mypy; the marker already guaranteed it
    read_only_statement = _load_script("snapshot_reads.py").READ_ONLY_STATEMENT

    engine = create_engine(_MAINTENANCE_URL, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(read_only_statement))
                assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
                with pytest.raises(InternalError, match="read-only transaction"):
                    conn.execute(text("CREATE TEMP TABLE norm30_probe (id int)"))

            # New transaction, same backend: the setting must be gone.
            with conn.begin():
                assert conn.execute(text("SHOW transaction_read_only")).scalar() == "off"
                assert conn.execute(text("SHOW default_transaction_read_only")).scalar() == "off"
                conn.execute(text("CREATE TEMP TABLE norm30_probe (id int)"))
                conn.execute(text("DROP TABLE norm30_probe"))
    finally:
        engine.dispose()
