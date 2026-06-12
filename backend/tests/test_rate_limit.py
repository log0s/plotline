"""Tests for the per-IP rate limit dependency."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from app.api.rate_limit import RateLimit, _client_ip


def _make_request(headers: dict[str, str] | None = None, host: str = "1.2.3.4") -> MagicMock:
    request = MagicMock()
    request.url.path = "/api/v1/geocode"
    request.headers = headers or {}
    request.client.host = host
    return request


def _settings(enabled: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.rate_limit_enabled = enabled
    return settings


class TestClientIp:
    def test_prefers_fly_client_ip(self) -> None:
        request = _make_request({"fly-client-ip": "9.9.9.9", "x-forwarded-for": "8.8.8.8"})
        assert _client_ip(request) == "9.9.9.9"

    def test_falls_back_to_first_forwarded_hop(self) -> None:
        request = _make_request({"x-forwarded-for": "8.8.8.8, 10.0.0.1"})
        assert _client_ip(request) == "8.8.8.8"

    def test_falls_back_to_socket_peer(self) -> None:
        assert _client_ip(_make_request()) == "1.2.3.4"


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold() -> None:
    limiter = RateLimit(times=2, seconds=60)
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=[1, 2, 3])

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_make_request(), _settings())
        await limiter(_make_request(), _settings())
        with pytest.raises(HTTPException) as exc_info:
            await limiter(_make_request(), _settings())

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_down() -> None:
    limiter = RateLimit(times=1, seconds=60)
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=RedisError("down"))

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_make_request(), _settings())
        await limiter(_make_request(), _settings())


@pytest.mark.asyncio
async def test_rate_limit_disabled_skips_redis() -> None:
    limiter = RateLimit(times=1, seconds=60)

    with patch("app.api.rate_limit.get_async_redis") as mock_redis:
        await limiter(_make_request(), _settings(enabled=False))

    mock_redis.assert_not_called()
