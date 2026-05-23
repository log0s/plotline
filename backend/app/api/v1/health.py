"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.db import check_db_connection, check_redis_connection
from app.schemas.parcels import HealthResponse

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
) -> HealthResponse:
    db_status = "connected" if check_db_connection() else "error"
    redis_status = "connected" if check_redis_connection() else "error"

    overall = "ok" if (db_status == "connected" and redis_status == "connected") else "degraded"
    if overall != "ok":
        response.status_code = 503

    return HealthResponse(status=overall, db=db_status, redis=redis_status)
