"""Per-IP rate limiting via Redis — protects endpoints that fan out to
external APIs (Census, Planetary Computer, county portals) and to the
Celery worker.

Fails open: if Redis is unreachable the request proceeds. Rate limiting
protects upstream quotas; it must not take the API down with it.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.db import get_async_redis

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    # Fly's proxy sets Fly-Client-IP; generic proxies set X-Forwarded-For.
    #
    # Taking the first X-Forwarded-For entry is spoofable in general — a
    # client can send any value it likes. It is unreachable IN PRODUCTION ON
    # FLY only because Fly's proxy sets Fly-Client-IP itself on every inbound
    # request and the branch above always wins. That makes the deployment
    # topology load-bearing: if this app is ever fronted by a different proxy,
    # or served without one, revisit this — the correct fix is to trust only
    # the Nth-from-last XFF entry for a known proxy depth.
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimit:
    """FastAPI dependency: at most ``times`` requests per ``seconds`` per IP.

    Fixed-window counter (INCR + EXPIRE) keyed by route path and client IP.
    """

    def __init__(self, times: int, seconds: int) -> None:
        self.times = times
        self.seconds = seconds

    async def __call__(
        self,
        request: Request,
        settings: Settings = Depends(get_settings),
    ) -> None:
        if not settings.rate_limit_enabled:
            return

        key = f"ratelimit:{request.url.path}:{_client_ip(request)}"
        try:
            redis = get_async_redis()
            # INCR and EXPIRE go in one pipeline. Issued separately, a
            # process death or a connection drop between them leaves a key
            # with a count and no TTL — an immortal counter that locks that
            # IP out of this route permanently. EXPIRE ... NX so a refresh
            # mid-window can't slide the window forward.
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, self.seconds, nx=True)
                count, _ = await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.warning("Rate limit check failed open: %s", exc)
            return

        if count > self.times:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please slow down and try again shortly.",
            )
