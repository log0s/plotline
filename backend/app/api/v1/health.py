"""Health check endpoint."""

from __future__ import annotations

import logging

import redis as redis_client
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

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
)
def health_check(settings: Settings = Depends(get_settings)) -> JSONResponse:
    db_status = "connected" if check_db_connection() else "error"

    try:
        r = redis_client.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        redis_status = "connected"
    except Exception:
        logger.warning("Redis health check failed")
        redis_status = "error"

    overall = "ok" if (db_status == "connected" and redis_status == "connected") else "degraded"

    payload = HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
    )

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(content=payload.model_dump(), status_code=status_code)
