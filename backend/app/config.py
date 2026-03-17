"""Application configuration via pydantic-settings.

All settings are read from environment variables (or a .env file).
Validation happens at startup — missing required vars raise a clear error.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object. Instantiated once via get_settings()."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string, e.g. postgresql://user:pass@host:5432/db",
    )

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Must be a JSON array in the environment: ["http://localhost:5173"]
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── External APIs ─────────────────────────────────────────────────────────
    census_api_key: str | None = None
    census_geocoder_url: str = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    )
    census_geocoder_timeout: float = 10.0  # seconds

    # ── Parcel deduplication ──────────────────────────────────────────────────
    parcel_dedup_radius_meters: float = 50.0

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Inject via FastAPI Depends()."""
    return Settings()  # type: ignore[call-arg]
