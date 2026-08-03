"""Tests for GET /api/v1/health."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    """Health check returns 200 when both DB and Redis are connected."""
    with (
        patch("app.api.v1.health.check_db_connection", return_value=True),
        patch("app.api.v1.health.check_redis_connection", return_value=True),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "connected"
    assert body["redis"] == "connected"
    assert "version" in body


def test_health_db_down(client: TestClient) -> None:
    """Health check returns 503 when the database is unreachable."""
    with (
        patch("app.api.v1.health.check_db_connection", return_value=False),
        patch("app.api.v1.health.check_redis_connection", return_value=True),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert body["redis"] == "connected"


def test_health_redis_down(client: TestClient) -> None:
    """Health check returns 503 when Redis is unreachable."""
    with (
        patch("app.api.v1.health.check_db_connection", return_value=True),
        patch("app.api.v1.health.check_redis_connection", return_value=False),
    ):
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "connected"
    assert body["redis"] == "error"


def test_redis_clients_have_socket_timeouts() -> None:
    """Both Redis clients bound socket waits.

    A half-dead Redis — TCP up, no replies — would otherwise hang the
    health probe, every rate-limit check, and the SAS cache forever, and
    the fail-open handlers would never run.
    """
    import asyncio

    from app.db import get_async_redis, get_redis

    sync_kwargs = get_redis().connection_pool.connection_kwargs
    assert sync_kwargs["socket_timeout"] == 2
    assert sync_kwargs["socket_connect_timeout"] == 2

    async def _async_kwargs() -> dict[str, object]:
        kwargs: dict[str, object] = get_async_redis().connection_pool.connection_kwargs
        return kwargs

    async_kwargs = asyncio.run(_async_kwargs())
    assert async_kwargs["socket_timeout"] == 2
    assert async_kwargs["socket_connect_timeout"] == 2
