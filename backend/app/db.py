"""Database session management.

Uses SQLAlchemy's synchronous session for Phase 1 simplicity.
The engine and sessionmaker are created once at module import time
using the DATABASE_URL from settings.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # detect stale connections
    pool_size=10,
    max_overflow=20,
    echo=(settings.app_env == "development"),
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session and ensures it's closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Probe the database — used by the health endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ── Redis ────────────────────────────────────────────────────────────────────

import redis as _redis_lib  # noqa: E402
import redis.asyncio as _redis_async_lib  # noqa: E402

_redis_client: _redis_lib.Redis | None = None
_async_redis_client: _redis_async_lib.Redis | None = None


def get_redis() -> _redis_lib.Redis:
    """Return a shared Redis client (binary mode for tile bytes)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = _redis_lib.from_url(
            settings.redis_url, decode_responses=False
        )
    return _redis_client


def get_async_redis() -> _redis_async_lib.Redis:
    """Return a shared asyncio Redis client for use inside async handlers."""
    global _async_redis_client
    if _async_redis_client is None:
        _async_redis_client = _redis_async_lib.from_url(
            settings.redis_url, decode_responses=False
        )
    return _async_redis_client


def check_redis_connection() -> bool:
    """Probe Redis — used by the health endpoint."""
    try:
        return get_redis().ping()
    except Exception:
        return False
