"""Alembic environment configuration."""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import Engine

# Import all models so Alembic can detect schema changes for autogenerate
from app.models.parcels import Base  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for 'autogenerate' support
target_metadata = Base.metadata

logger = logging.getLogger("alembic.env")

# Arbitrary but fixed: every process running migrations against this database
# must use the same key for the lock to mean anything.
_MIGRATION_LOCK_KEY = 8675309


def _destination_is_head() -> bool:
    """True when this invocation is an upgrade aimed at the scripts' head.

    ``alembic current``, ``stamp`` and ``downgrade`` run this env.py too, and a
    database deliberately behind head is the expected state for them — the
    check below must not turn a read-only command into an error.
    ``get_revision_argument`` resolves ``head`` to a concrete revision, so an
    explicit ``upgrade 0011`` verifies as well when 0011 is head, and raises
    ``KeyError`` when the command has no destination at all.
    """
    try:
        destination = context.get_revision_argument()
    except KeyError:
        return False
    if destination is None:
        return False
    return destination in set(ScriptDirectory.from_config(config).get_heads())


def _verify_at_head(connectable: Engine) -> None:
    """Read the version back on a fresh connection and refuse a false success.

    On 2026-08-26 production logged ``Running upgrade 0010 -> 0011`` and
    ``Migrations complete.``, exited 0, and served a database still at 0010
    with no ``timeline_task_years`` (X1 in
    ``docs/audits/2026-08-second-audit/STATUS.md``). Nothing read the version
    afterwards, so there was no step left for the lie to fail at.

    The connection matters. ``poolclass=pool.NullPool`` means this ``connect()``
    opens a new session rather than handing back the one that just ran the
    migrations, so what it reads is committed state and not the caller's own
    uncommitted view.
    """
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with connectable.connect() as connection:
        actual = set(MigrationContext.configure(connection).get_current_heads())

    logger.info(
        "Migration head check: database=%s scripts=%s",
        sorted(actual) or "(none)",
        sorted(expected) or "(none)",
    )
    if actual != expected:
        raise RuntimeError(
            "Migrations reported success but the database is not at head: "
            f"database={sorted(actual)}, scripts={sorted(expected)}. "
            "The upgrade did not commit."
        )


def get_url() -> str:
    """Resolve database URL from environment, falling back to alembic.ini."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and configure it."
        )
    # Normalize async driver schemes to psycopg2 (sync) for Alembic migrations
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")
    # psycopg2 uses 'sslmode', not 'ssl'
    url = url.replace("?ssl=true", "?sslmode=require")
    url = url.replace("&ssl=true", "&sslmode=require")
    url = url.replace("?ssl=require", "?sslmode=require")
    url = url.replace("&ssl=require", "&sslmode=require")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a
    connection with the context.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # entrypoint.sh runs `alembic upgrade head` on every API boot, so two
        # machines booting together (a scale-up, or a deploy that briefly
        # overlaps old and new) would both read the same alembic_version and
        # both apply the same migration — one of them crash-looping on
        # duplicate DDL. The advisory lock serializes them: the second waits,
        # then finds itself already at head and does nothing.
        #
        # Both halves of how it is taken are load-bearing, and the first
        # version of this block got both wrong (X1).
        #
        # 1. The transaction is explicit and owned here. Executing the lock
        #    statement on a connection that is not already in a transaction
        #    autobegins one under SQLAlchemy 2.0 anyway; `context.configure`
        #    then reads that as an external transaction
        #    (`MigrationContext._in_external_transaction`) and its own
        #    `begin_transaction()` degrades to a no-op, handing the commit to
        #    a caller that did not exist. `Connection.close()` rolled the DDL
        #    and the version bump back and alembic still exited 0. Migration
        #    0011 was the first migration ever to run under this block and the
        #    first to be silently discarded.
        #
        # 2. The lock is transaction-scoped. `pg_advisory_xact_lock` releases
        #    at COMMIT — the same instant the new `alembic_version` becomes
        #    visible — so a second booter cannot acquire the lock and read a
        #    stale revision in the window between the two. A session-scoped
        #    lock released before the commit reopens exactly the race the lock
        #    exists to close.
        #
        # Ordering: the lock is taken before `context.run_migrations()`, which
        # is where alembic reads the current revision
        # (`MigrationContext.run_migrations` -> `get_current_heads`,
        # alembic/runtime/migration.py:488). `context.configure` reads nothing
        # from the database.
        #
        # `context.begin_transaction()` is deliberately absent: inside this
        # block it can only return a `nullcontext`, and its presence is what
        # made the original look like it committed.
        with connection.begin():
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK_KEY}
            )
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            context.run_migrations()

    if _destination_is_head():
        _verify_at_head(connectable)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
