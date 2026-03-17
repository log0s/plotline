"""Tests for GET /api/v1/health."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    """Health check returns 200 when both DB and Redis are connected."""
    with (
        patch("app.api.v1.health.check_db_connection", return_value=True),
        patch("app.api.v1.health.redis_client.from_url") as mock_redis,
    ):
        mock_redis.return_value.ping.return_value = True

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
        patch("app.api.v1.health.redis_client.from_url") as mock_redis,
    ):
        mock_redis.return_value.ping.return_value = True

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
        patch("app.api.v1.health.redis_client.from_url") as mock_redis,
    ):
        mock_redis.return_value.ping.side_effect = ConnectionError("Redis unavailable")

        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "connected"
    assert body["redis"] == "error"
