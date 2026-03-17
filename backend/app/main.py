"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import geocode, health, imagery, parcels
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Plotline API",
        description="Geospatial Time Machine — explore how any US location has changed over time.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(geocode.router, prefix="/api/v1", tags=["geocode"])
    app.include_router(parcels.router, prefix="/api/v1", tags=["parcels"])
    app.include_router(imagery.router, prefix="/api/v1", tags=["imagery"])

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info(
            "Plotline API starting",
            extra={"env": settings.app_env, "log_level": settings.log_level},
        )

    return app


app = create_app()
