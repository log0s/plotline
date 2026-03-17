"""Timeline task stubs — will be implemented in Phase 2.

Phase 2 tasks:
  - fetch_naip_imagery: Query Planetary Computer STAC for NAIP scenes
  - fetch_landsat_imagery: Query Planetary Computer STAC for Landsat scenes
  - build_timeline: Orchestrate all imagery and data fetching for a parcel
"""

from __future__ import annotations

import logging
import uuid

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="tasks.build_timeline")  # type: ignore[misc]
def build_timeline(self, parcel_id: str) -> dict[str, str]:  # type: ignore[misc]
    """Stub: orchestrate historical data fetching for a parcel.

    Will be fully implemented in Phase 2 with:
      - NAIP aerial imagery from Microsoft Planetary Computer STAC
      - Landsat imagery from Microsoft Planetary Computer STAC
      - USGS historical topographic maps
      - Census demographic data by decade

    Args:
        parcel_id: UUID string of the parcel to build a timeline for.

    Returns:
        Dict with task result metadata.
    """
    logger.info("build_timeline task received (Phase 2 stub)", extra={"parcel_id": parcel_id})

    # Validate the parcel_id is a valid UUID
    try:
        uuid.UUID(parcel_id)
    except ValueError:
        raise ValueError(f"Invalid parcel_id: {parcel_id!r}")

    # Phase 1: just acknowledge and return a placeholder
    return {
        "status": "queued",
        "parcel_id": parcel_id,
        "message": "Timeline build not yet implemented (Phase 2)",
    }
