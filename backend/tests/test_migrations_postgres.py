"""The migration runner, against a real Postgres.

Every other test in this suite builds its schema as hand-written DDL against
in-memory SQLite (``conftest.py``), so ``alembic/`` is never executed anywhere
in CI. That is why X1 shipped: ``alembic upgrade head`` reported success
against production, committed nothing, exited 0, and the container served a
database two revisions of schema short of the code running on it. A test that
cannot execute a migration cannot fail on a migration that does not commit.

These tests need a real server and are skipped without one — except in CI,
where a missing URL is a failure rather than a silent skip, because a required
test that quietly stops running is the same class of problem all over again.

Set ``TEST_POSTGRES_URL`` to a **maintenance** connection: nothing here touches
the database it names. Each test creates a throwaway database, migrates that,
and drops it.

    TEST_POSTGRES_URL=postgresql://plotline:plotline@localhost:5432/plotline \\
        pytest tests/test_migrations_postgres.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from alembic import command

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_MAINTENANCE_URL = os.environ.get("TEST_POSTGRES_URL")

# The advisory lock key alembic/env.py serializes boots on. Repeated rather
# than imported: env.py is a script, not a module, and importing it runs
# migrations.
_MIGRATION_LOCK_KEY = 8675309

requires_postgres = pytest.mark.skipif(
    not _MAINTENANCE_URL,
    reason="TEST_POSTGRES_URL is not set",
)


def test_postgres_migration_tests_are_not_silently_skipped() -> None:
    """In CI this file is required. A missing URL must fail, not skip."""
    if os.environ.get("CI") and not _MAINTENANCE_URL:
        pytest.fail(
            "TEST_POSTGRES_URL is not set, so the migration tests would skip. "
            "They are required in CI — nothing else in the suite executes a "
            "migration. See .github/workflows/deploy.yml."
        )


def _alembic_config() -> Config:
    """An in-process config that deliberately does not read ``alembic.ini``.

    ``env.py`` calls ``fileConfig(config.config_file_name)`` whenever a config
    file is present, and ``fileConfig`` disables every existing logger — which
    silently breaks ``caplog`` for every test that runs after this one. Leaving
    ``config_file_name`` unset skips that branch. The ini's only setting these
    tests need is ``script_location``, and the URL comes from ``DATABASE_URL``
    either way. The subprocesses below do pass ``-c``, which is safe: their
    logging config dies with them.
    """
    config = Config()
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return config


def _script_head() -> str:
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert len(heads) == 1, f"expected a single head, got {heads}"
    return heads[0]


@contextmanager
def _temp_database() -> Iterator[str]:
    """A throwaway database, dropped on the way out.

    The maintenance database itself is never migrated or modified — a
    developer pointing ``TEST_POSTGRES_URL`` at their working database must
    not lose it.
    """
    assert _MAINTENANCE_URL
    name = f"plotline_migtest_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_MAINTENANCE_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            yield (
                make_url(_MAINTENANCE_URL).set(database=name).render_as_string(hide_password=False)
            )
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@contextmanager
def _database_url(url: str) -> Iterator[None]:
    """Point ``env.py``'s ``get_url()`` at ``url`` for the duration."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _versions(url: str) -> list[str]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT to_regclass('alembic_version')")).scalar() is None:
                return []
            return list(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
    finally:
        engine.dispose()


def _table_count(url: str, table: str) -> int:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables"
                        " WHERE table_schema = 'public' AND table_name = :t"
                    ),
                    {"t": table},
                ).scalar_one()
            )
    finally:
        engine.dispose()


@requires_postgres
def test_upgrade_head_commits_the_schema_and_the_version() -> None:
    """The X1 regression: a migration that runs must still be there afterwards.

    Delete-the-fix: revert ``env.py``'s explicit ``connection.begin()`` and
    this fails on the version — either at the head check inside ``env.py`` or,
    with that check reverted too, at the assertions below. It does not fail on
    a connection error, which is what makes it a test of the commit rather
    than of the harness.
    """
    head = _script_head()

    with _temp_database() as url:
        assert _versions(url) == []

        with _database_url(url):
            command.upgrade(_alembic_config(), "head")

        # Read on connections this test owns, after the runner has closed its
        # own — uncommitted DDL is invisible here by construction.
        assert _versions(url) == [head]
        assert _table_count(url, "timeline_task_years") == 1


@requires_postgres
def test_concurrent_boots_from_0010_converge_on_head() -> None:
    """M10's actual property, which has never been tested.

    Two processes run ``alembic upgrade head`` against the same database at
    0010, the way two API machines do when a deploy overlaps them. Both must
    exit 0, the version must end at head exactly once, and neither may hit
    duplicate DDL.

    The contention is forced rather than hoped for: this test holds the
    migration advisory lock itself, waits until both processes are provably
    blocked on it, and only then lets go. Without that, process startup jitter
    is longer than the migration and the two would usually not overlap at all.
    """
    head = _script_head()

    with _temp_database() as url:
        with _database_url(url):
            command.upgrade(_alembic_config(), "0010")
        assert _versions(url) == ["0010"]

        blocker = create_engine(url, poolclass=NullPool)
        environment = {**os.environ, "DATABASE_URL": url}
        processes: list[subprocess.Popen[str]] = []
        try:
            with blocker.connect() as held:
                held.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
                held.commit()

                processes = [
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "alembic",
                            "-c",
                            str(_ALEMBIC_INI),
                            "upgrade",
                            "head",
                        ],
                        cwd=str(_BACKEND_DIR),
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    for _ in range(2)
                ]

                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    waiting = held.execute(
                        text(
                            "SELECT count(*) FROM pg_locks"
                            " WHERE locktype = 'advisory' AND objid = :key AND NOT granted"
                        ),
                        {"key": _MIGRATION_LOCK_KEY},
                    ).scalar_one()
                    if waiting >= 2:
                        break
                    if any(p.poll() is not None for p in processes):
                        break
                    time.sleep(0.2)
                else:
                    pytest.fail("timed out waiting for both boots to block on the migration lock")

                assert waiting == 2, (
                    "both boots should be blocked on the advisory lock before it is "
                    f"released; {waiting} were"
                )
            # `blocker`'s session ends here, releasing the lock and starting the race.

            outputs = [p.communicate(timeout=120) for p in processes]
            codes = [p.returncode for p in processes]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
            blocker.dispose()

        combined = "\n".join(out for out, _ in outputs)
        assert codes == [0, 0], f"exit codes {codes}\n{combined}"
        assert "already exists" not in combined, f"duplicate DDL:\n{combined}"
        assert _versions(url) == [head]
        assert _table_count(url, "timeline_task_years") == 1
