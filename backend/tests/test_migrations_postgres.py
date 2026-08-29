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


def _scalar(url: str, sql: str) -> object:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return connection.execute(text(sql)).scalar_one()
    finally:
        engine.dispose()


@requires_postgres
def test_0012_backfills_scope_origin_and_partial() -> None:
    """0012's three backfills, against rows that predate it.

    The fixture is production's shape in miniature: one request whose tasks
    all completed, one with a failed task beside completed ones (Crawford
    County ``6563dedf``), and one where every task failed. Only the middle
    one may flip.
    """
    with _temp_database() as url:
        with _database_url(url):
            command.upgrade(_alembic_config(), "0011")

        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO parcels (id, address, latitude, longitude, point)"
                        " VALUES (gen_random_uuid(), 'x', 39.7, -105.0,"
                        " ST_SetSRID(ST_MakePoint(-105.0, 39.7), 4326))"
                    )
                )
                parcel = connection.execute(text("SELECT id FROM parcels LIMIT 1")).scalar_one()
                for label, task_statuses in (
                    ("clean", ["complete", "complete", "skipped"]),
                    ("crawford", ["complete", "failed", "failed"]),
                    ("dead", ["failed", "failed"]),
                ):
                    request = connection.execute(
                        text(
                            "INSERT INTO timeline_requests (id, parcel_id, status, error_message)"
                            " VALUES (gen_random_uuid(), :p, 'complete', :m) RETURNING id"
                        ),
                        {"p": parcel, "m": label},
                    ).scalar_one()
                    for source, status in zip(
                        ("naip", "landsat", "sentinel2"), task_statuses, strict=False
                    ):
                        connection.execute(
                            text(
                                "INSERT INTO timeline_request_tasks"
                                " (id, timeline_request_id, source, status)"
                                " VALUES (gen_random_uuid(), :r, :s, :st)"
                            ),
                            {"r": request, "s": source, "st": status},
                        )
        finally:
            engine.dispose()

        with _database_url(url):
            command.upgrade(_alembic_config(), "head")

        assert _scalar(url, "SELECT count(*) FROM timeline_requests WHERE origin = 'user'") == 3
        assert (
            _scalar(url, "SELECT count(*) FROM timeline_requests WHERE cardinality(sources) = 6")
            == 3
        )
        assert _scalar(url, "SELECT count(*) FROM timeline_requests WHERE status = 'partial'") == 1
        assert (
            _scalar(
                url,
                "SELECT error_message FROM timeline_requests WHERE status = 'partial'",
            )
            == "crawford"
        )
        # 'dead' recorded 'complete' with every task failed — the same rule
        # aggregate_request_status applies at runtime says 'failed'.
        # Production has zero of these; the branch exists so the migration
        # implements the whole definition rather than two thirds of it.
        assert _scalar(url, "SELECT count(*) FROM timeline_requests WHERE status = 'failed'") == 1
        assert (
            _scalar(url, "SELECT error_message FROM timeline_requests WHERE status = 'failed'")
            == "dead"
        )
        assert _scalar(url, "SELECT count(*) FROM timeline_requests WHERE status = 'complete'") == 1


@requires_postgres
def test_0012_rejects_an_unknown_source_and_an_unknown_origin() -> None:
    """The CHECKs are load-bearing: cardinality only means "full scope" if
    the array cannot hold a duplicate or an unknown name."""
    import sqlalchemy.exc

    with _temp_database() as url:
        with _database_url(url):
            command.upgrade(_alembic_config(), "head")

        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO parcels (id, address, latitude, longitude, point)"
                        " VALUES (gen_random_uuid(), 'x', 39.7, -105.0,"
                        " ST_SetSRID(ST_MakePoint(-105.0, 39.7), 4326))"
                    )
                )
                parcel = connection.execute(text("SELECT id FROM parcels LIMIT 1")).scalar_one()

            for column, value in (
                ("sources", "ARRAY['naip', 'landsat_9']::text[]"),
                ("sources", "ARRAY[]::text[]"),
                ("origin", "'cron'"),
            ):
                other = "origin" if column == "sources" else "sources"
                other_value = "'user'" if other == "origin" else "ARRAY['naip']::text[]"
                with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO timeline_requests"
                            f" (id, parcel_id, status, {column}, {other})"
                            f" VALUES (gen_random_uuid(), :p, 'queued', {value}, {other_value})"
                        ),
                        {"p": parcel},
                    )
        finally:
            engine.dispose()


# ── 0018: the footprint-validity CHECK, which only PostGIS can express ────────

# A self-intersecting bow-tie: five points, ST_IsValid false, and exactly the
# class NORM-31 found twice in production (Sentinel-2 footprints written by a
# path that predated `normalize_footprint`). Spelled as literal WKT rather than
# built by a helper so the fixture cannot drift into validity.
_BOWTIE = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"
_VALID_SQUARE = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"


def _insert_scene(connection: object, *, footprint: str | None) -> None:
    from sqlalchemy import text as sa_text

    geom = "NULL" if footprint is None else "ST_GeomFromText(:fp, 4326)"
    connection.execute(  # type: ignore[attr-defined]  # a live Connection
        sa_text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date,"
            f" footprint, cog_url, provenance, fetched_at)"
            f" VALUES (gen_random_uuid(), 'sentinel2', 'sentinel-2-l2a',"
            f" 'S2A_' || gen_random_uuid()::text, '2020-01-01', {geom},"
            " 'https://example.com/x.tif', 'selection', now())"
        ),
        {} if footprint is None else {"fp": footprint},
    )


@requires_postgres
def test_0018_refuses_an_invalid_footprint_and_admits_a_valid_one() -> None:
    """The bypass detector, against a real PostGIS.

    This constraint cannot be mirrored in the SQLite test schema — SQLite has
    no ``ST_IsValid``, and inventing one there would make the test agree with
    the test file rather than with the database (NORM-29's rule). So it is
    asserted here, where the predicate that runs is the one production runs.

    Three cases, and the NULL one is not padding: ``footprint`` is nullable by
    design (``usgs_topo`` has no geometry at all, and the deferred enrichment
    queue is defined by NULL), so a constraint that rejected NULL would break
    a live population.

    Delete-the-fix: drop ``op.create_check_constraint`` from 0018's
    ``upgrade()`` and the bow-tie inserts cleanly, which is the state
    production was in when NORM-31 was found by a sweep rather than by the
    database.
    """
    import sqlalchemy.exc

    with _temp_database() as url:
        with _database_url(url):
            command.upgrade(_alembic_config(), "head")

        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                _insert_scene(connection, footprint=_VALID_SQUARE)
                _insert_scene(connection, footprint=None)

            with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as connection:
                _insert_scene(connection, footprint=_BOWTIE)

            with engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM scenes")).scalar_one() == 2, (
                    "the valid and NULL rows landed; the bow-tie did not"
                )
        finally:
            engine.dispose()


@requires_postgres
def test_0018_round_trips_without_touching_anything_else() -> None:
    """Independently revertable: down to 0017 and back up leaves the rows alone.

    The constraint is a rider on step 4 and must be removable on its own, so
    downgrading it must not be entangled with the drop migration or with any
    data. A row written while it is off — the bow-tie — is what makes the
    re-upgrade a real test: PostgreSQL refuses to add a validating CHECK while
    any row fails it, so this asserts the *precondition* discipline the
    migration's docstring describes, using the same failure the NORM-31 heal
    had to clear before 0018 could land at all.
    """
    import sqlalchemy.exc

    with _temp_database() as url:
        with _database_url(url):
            command.upgrade(_alembic_config(), "head")

        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                _insert_scene(connection, footprint=_VALID_SQUARE)

            with _database_url(url):
                command.downgrade(_alembic_config(), "0017")

            # With the constraint off, the invalid row goes in.
            with engine.begin() as connection:
                _insert_scene(connection, footprint=_BOWTIE)

            # And the re-upgrade refuses, because a validating CHECK is
            # checked against what is already there.
            with pytest.raises(sqlalchemy.exc.IntegrityError), _database_url(url):
                command.upgrade(_alembic_config(), "0018")

            # Clear the offender the way a heal would, and it applies.
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM scenes WHERE NOT ST_IsValid(footprint)"))
            with _database_url(url):
                command.upgrade(_alembic_config(), "head")

            with engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM scenes")).scalar_one() == 1
        finally:
            engine.dispose()
