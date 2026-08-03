"""Alembic environment configuration."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

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

# Arbitrary but fixed: every process running migrations against this database
# must use the same key for the lock to mean anything.
_MIGRATION_LOCK_KEY = 8675309


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
        # Session-scoped, not transaction-scoped: each migration runs in its
        # own transaction, so a transaction-scoped lock would be released
        # after the first one.
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY}
            )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
