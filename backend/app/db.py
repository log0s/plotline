"""Database and Redis connection management.

SQLAlchemy sessions are synchronous throughout; async request handlers push
DB work into the threadpool rather than the ORM being async. The engine and
sessionmaker are created once at module import time from DATABASE_URL.

Redis has two client families here rather than one: a shared synchronous
client in binary mode, and a set of asyncio clients keyed by event loop —
``redis.asyncio`` connections are loop-affine and the Celery worker runs
each task in its own ``asyncio.run()`` loop.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # detect stale connections
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
    """Probe the database — used by the health endpoint.

    Wraps the probe in a 2-second statement_timeout so a slow but
    not-quite-dead Postgres can't make the health endpoint hang
    (which would let a load balancer think the instance is healthy
    while requests pile up behind a stuck DB).

    SET LOCAL is scoped to the transaction, so the setting won't leak
    back into pooled connections used by request handlers.
    """
    from sqlalchemy.exc import SQLAlchemyError

    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET LOCAL statement_timeout = '2s'"))
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


# ── Redis ────────────────────────────────────────────────────────────────────

import asyncio  # noqa: E402
import threading  # noqa: E402

import redis as _redis_lib  # noqa: E402
import redis.asyncio as _redis_async_lib  # noqa: E402

# Without these, a Redis whose TCP connection is up but which has stopped
# answering blocks forever: the health probe, every rate-limit check, and
# the SAS cache all wait on a reply that never comes, and the fail-open
# `except (RedisError, OSError)` never gets the chance to fire. Matches the
# 2-second statement_timeout the DB probe above uses for the same reason.
_REDIS_TIMEOUT = 2

_redis_lock = threading.Lock()
_async_redis_lock = threading.Lock()
_redis_client: _redis_lib.Redis[bytes] | None = None
# Keyed by event loop: the Celery worker runs each task in its own
# asyncio.run() loop, and redis.asyncio connections are loop-affine —
# a single shared client breaks under concurrent tasks.
_async_redis_clients: dict[asyncio.AbstractEventLoop, _redis_async_lib.Redis[bytes]] = {}


def get_redis() -> _redis_lib.Redis[bytes]:
    """Return a shared Redis client (binary mode for tile bytes)."""
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = _redis_lib.from_url(
                    settings.redis_url,
                    decode_responses=False,
                    socket_timeout=_REDIS_TIMEOUT,
                    socket_connect_timeout=_REDIS_TIMEOUT,
                )
    return _redis_client


def get_async_redis() -> _redis_async_lib.Redis[bytes]:
    """Return an asyncio Redis client bound to the running event loop."""
    loop = asyncio.get_running_loop()
    client = _async_redis_clients.get(loop)
    if client is None:
        with _async_redis_lock:
            client = _async_redis_clients.get(loop)
            if client is None:
                client = _redis_async_lib.from_url(
                    settings.redis_url,
                    decode_responses=False,
                    socket_timeout=_REDIS_TIMEOUT,
                    socket_connect_timeout=_REDIS_TIMEOUT,
                )
                _async_redis_clients[loop] = client
    return client


async def close_async_redis() -> None:
    """Close this event loop's async Redis client and release connections."""
    client = _async_redis_clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        # type-ignore: types-redis stubs lag redis 5+, where aclose()
        # replaces the deprecated close()
        await client.aclose()  # type: ignore[attr-defined]


def check_redis_connection() -> bool:
    """Probe Redis — used by the health endpoint."""
    try:
        return get_redis().ping()
    except (_redis_lib.RedisError, OSError):
        return False
