"""Health check endpoint."""

from __future__ import annotations

import logging

import redis as redis_client
from fastapi import APIRouter, Depends, Response
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.db import check_db_connection
from app.schemas.parcels import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns connectivity status for the database and Redis.",
    responses={503: {"description": "One or more dependencies are unhealthy"}},
)
def health_check(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    db_status = "connected" if check_db_connection() else "error"

    try:
        r = redis_client.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        redis_status = "connected"
    except (RedisError, OSError):
        logger.warning("Redis health check failed")
        redis_status = "error"

    overall = "ok" if (db_status == "connected" and redis_status == "connected") else "degraded"
    if overall != "ok":
        response.status_code = 503

    return HealthResponse(status=overall, db=db_status, redis=redis_status)
