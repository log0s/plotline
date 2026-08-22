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


def _fake_redis(counts: list[int] | Exception) -> tuple[MagicMock, MagicMock]:
    """A Redis whose pipeline yields the given INCR results in order.

    Returns (redis, pipe) so tests can assert what was queued.
    """
    pipe = MagicMock()
    if isinstance(counts, Exception):
        pipe.execute = AsyncMock(side_effect=counts)
    else:
        pipe.execute = AsyncMock(side_effect=[[c, True] for c in counts])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)

    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)
    return redis, pipe


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold() -> None:
    limiter = RateLimit(times=2, seconds=60)
    redis, _ = _fake_redis([1, 2, 3])

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_make_request(), _settings())
        await limiter(_make_request(), _settings())
        with pytest.raises(HTTPException) as exc_info:
            await limiter(_make_request(), _settings())

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_down() -> None:
    limiter = RateLimit(times=1, seconds=60)
    redis, _ = _fake_redis(RedisError("down"))

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_make_request(), _settings())
        await limiter(_make_request(), _settings())


@pytest.mark.asyncio
async def test_rate_limit_disabled_skips_redis() -> None:
    limiter = RateLimit(times=1, seconds=60)

    with patch("app.api.rate_limit.get_async_redis") as mock_redis:
        await limiter(_make_request(), _settings(enabled=False))

    mock_redis.assert_not_called()


@pytest.mark.asyncio
async def test_counter_and_expiry_are_issued_atomically() -> None:
    """INCR and EXPIRE ship in one pipeline, with EXPIRE ... NX.

    Issued separately, a death between them leaves a counted key with no
    TTL — a counter that never decays and locks that IP out of the route
    for good.
    """
    limiter = RateLimit(times=5, seconds=60)
    redis, pipe = _fake_redis([1])

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_make_request(), _settings())

    redis.pipeline.assert_called_once_with(transaction=True)
    pipe.incr.assert_called_once()
    pipe.expire.assert_called_once()
    assert pipe.expire.call_args.args[1] == 60
    assert pipe.expire.call_args.kwargs["nx"] is True
    assert pipe.execute.await_count == 1


# ── Key on the route template, not the concrete path (security audit SEC-3) ──


def _routed_request(template: str, concrete: str) -> MagicMock:
    request = _make_request()
    request.url.path = concrete
    request.scope = {"route": MagicMock(path=template)}
    return request


@pytest.mark.asyncio
async def test_rate_limit_key_uses_route_template() -> None:
    """Two snapshot ids share one bucket; keyed on the concrete path each id
    had its own, multiplying every per-id limit by the id space."""
    limiter = RateLimit(times=100, seconds=60)
    redis, pipe = _fake_redis([1, 2])
    template = "/api/v1/imagery/{snapshot_id}/warmup"

    with patch("app.api.rate_limit.get_async_redis", return_value=redis):
        await limiter(_routed_request(template, "/api/v1/imagery/aaa/warmup"), _settings())
        await limiter(_routed_request(template, "/api/v1/imagery/bbb/warmup"), _settings())

    keys = {call.args[0] for call in pipe.incr.call_args_list}
    assert keys == {f"ratelimit:{template}:1.2.3.4"}
    assert "aaa" not in next(iter(keys))


# ── Redis-failure policy per route class (security audit SEC-6 / G2) ─────────


@pytest.mark.asyncio
async def test_fail_closed_limiter_returns_503_when_redis_down() -> None:
    limiter = RateLimit(times=10, seconds=60, fail_closed=True)
    redis, _ = _fake_redis(RedisError("down"))

    with (
        patch("app.api.rate_limit.get_async_redis", return_value=redis),
        pytest.raises(HTTPException) as exc_info,
    ):
        await limiter(_make_request(), _settings())

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "30"}


def test_dispatching_routes_fail_closed_and_read_routes_fail_open() -> None:
    """The classification from REMEDIATION-1.md G2, pinned: creating a parcel
    or dispatching a worker run fails closed; everything else fails open."""
    from fastapi.routing import APIRoute

    from app.main import create_app

    policy: dict[str, bool] = {}
    for route in create_app().routes:
        if not isinstance(route, APIRoute):
            continue
        for dep in route.dependant.dependencies:
            if isinstance(dep.call, RateLimit):
                policy[route.path] = dep.call.fail_closed

    assert policy == {
        "/api/v1/geocode": True,
        "/api/v1/parcels/{parcel_id}/timeline": True,
        "/api/v1/geocode/autocomplete": False,
        "/api/v1/imagery/{snapshot_id}/warmup": False,
        "/api/v1/imagery/{snapshot_id}/stac": False,
    }
