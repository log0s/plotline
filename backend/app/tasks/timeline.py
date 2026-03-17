"""Imagery timeline Celery task.

Searches Planetary Computer STAC for NAIP, Landsat, and Sentinel-2 imagery
at a parcel location, then persists the results as imagery_snapshots rows.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.services import stac as stac_service
from app.services import imagery as imagery_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Source configuration ───────────────────────────────────────────────────────

_SOURCES: list[dict[str, Any]] = [
    {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2003-01-01/2025-12-31",
        "max_items": 50,
        "query": None,
        "selector": stac_service.select_naip_items,
        "resolution_m": 1.0,
    },
    {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "datetime_range": "1984-01-01/2025-12-31",
        "max_items": 100,
        "query": {"eo:cloud_cover": {"lt": 20}},
        "selector": stac_service.select_landsat_items,
        "resolution_m": 30.0,
    },
    {
        "source": "sentinel2",
        "collection": "sentinel-2-l2a",
        "datetime_range": "2015-01-01/2025-12-31",
        "max_items": 100,
        "query": {"eo:cloud_cover": {"lt": 20}},
        "selector": stac_service.select_sentinel_items,
        "resolution_m": 10.0,
    },
]


# ── Async implementation ───────────────────────────────────────────────────────


async def _fetch_source(
    source_cfg: dict[str, Any],
    bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
) -> int:
    """Fetch one imagery source and persist snapshots. Returns items_found count."""
    from app.db import SessionLocal

    source_name: str = source_cfg["source"]
    collection: str = source_cfg["collection"]

    logger.info(f"Starting STAC search: {source_name}", extra={"collection": collection})
    t0 = time.perf_counter()

    with SessionLocal() as db:
        # Find and update the task row
        from sqlalchemy import select as sa_select
        from app.models.parcels import TimelineRequest, TimelineRequestTask

        request = db.execute(
            sa_select(TimelineRequest).where(TimelineRequest.id == timeline_request_id)
        ).scalars().first()
        if not request:
            logger.error("Timeline request not found", extra={"id": str(timeline_request_id)})
            return 0

        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == source_name)
        ).scalars().first()
        if not task_row:
            logger.warning(f"No task row found for {source_name}")
            return 0

        imagery_service.update_request_task(db, task_row, "processing")

    # Search STAC (async HTTP, outside the DB session)
    try:
        raw_items = await stac_service.search_stac(
            collection=collection,
            bbox=bbox,
            datetime_range=source_cfg["datetime_range"],
            max_items=source_cfg["max_items"],
            query=source_cfg.get("query"),
        )
    except Exception as exc:
        logger.error(
            f"STAC search failed for {source_name}",
            extra={"error": str(exc)},
        )
        with SessionLocal() as db:
            from app.models.parcels import TimelineRequestTask
            from sqlalchemy import select as sa_select

            task_row = db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
                .where(TimelineRequestTask.source == source_name)
            ).scalars().first()
            if task_row:
                imagery_service.update_request_task(
                    db, task_row, "failed", error_message=str(exc)
                )
        return 0

    # Select representative items (one per year/quarter)
    selected = source_cfg["selector"](raw_items)
    elapsed = time.perf_counter() - t0
    logger.info(
        f"STAC search complete: {source_name}",
        extra={
            "raw_count": len(raw_items),
            "selected_count": len(selected),
            "wall_time_s": round(elapsed, 2),
        },
    )

    # Persist snapshots
    items_saved = 0
    with SessionLocal() as db:
        for item in selected:
            cog_url = stac_service.extract_cog_url(item, collection)
            if not cog_url:
                continue

            thumbnail_url = stac_service.extract_thumbnail_url(item)
            capture_date = stac_service.extract_capture_date(item)
            cloud_cover = item.get("properties", {}).get("eo:cloud_cover")  # type: ignore[union-attr]
            bbox_wkt = stac_service.extract_bbox_wkt(item)

            was_inserted = imagery_service.upsert_imagery_snapshot(
                db,
                parcel_id=parcel_id,
                source=source_name,
                capture_date=capture_date,
                stac_item_id=str(item["id"]),
                stac_collection=collection,
                cog_url=cog_url,
                thumbnail_url=thumbnail_url,
                resolution_m=source_cfg["resolution_m"],
                cloud_cover_pct=float(cloud_cover) if cloud_cover is not None else None,
                bbox_wkt=bbox_wkt,
            )
            if was_inserted:
                items_saved += 1

        # Update task status
        from app.models.parcels import TimelineRequestTask
        from sqlalchemy import select as sa_select

        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == source_name)
        ).scalars().first()
        if task_row:
            imagery_service.update_request_task(
                db, task_row, "complete", items_found=items_saved
            )

    logger.info(
        f"Imagery source done: {source_name}",
        extra={"items_saved": items_saved},
    )
    return items_saved


async def _run_timeline(timeline_request_id: str) -> dict[str, Any]:
    """Orchestrate all imagery sources for a timeline request."""
    from app.db import SessionLocal
    from app.models.parcels import TimelineRequest
    from sqlalchemy import select as sa_select

    req_uuid = uuid.UUID(timeline_request_id)

    # Load the request and its parcel
    with SessionLocal() as db:
        request = db.execute(
            sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid)
        ).scalars().first()
        if not request:
            raise ValueError(f"TimelineRequest {timeline_request_id!r} not found")

        parcel_id = request.parcel_id
        if not parcel_id:
            raise ValueError("TimelineRequest has no parcel_id")

        from app.models.parcels import Parcel

        parcel = db.execute(
            sa_select(Parcel).where(Parcel.id == parcel_id)
        ).scalars().first()
        if not parcel:
            raise ValueError(f"Parcel {parcel_id} not found")

        lat, lng = parcel.latitude, parcel.longitude

        # Transition to processing
        imagery_service.update_timeline_request_status(db, request, "processing")

        # Create per-source task rows
        imagery_service.create_request_tasks(
            db,
            timeline_request_id=req_uuid,
            sources=[s["source"] for s in _SOURCES],
        )

    # Compute bounding box
    bbox = stac_service.point_to_bbox(lat, lng, buffer_m=500)
    logger.info(
        "Timeline bbox computed",
        extra={"parcel_id": str(parcel_id), "bbox": bbox},
    )

    # Fetch each source independently — one failure doesn't block others
    total_items = 0
    for source_cfg in _SOURCES:
        try:
            count = await _fetch_source(source_cfg, bbox, parcel_id, req_uuid)
            total_items += count
        except Exception as exc:
            logger.error(
                f"Unexpected error for source {source_cfg['source']}",
                extra={"error": str(exc)},
            )

    # Mark request complete
    with SessionLocal() as db:
        request = db.execute(
            sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid)
        ).scalars().first()
        if request:
            imagery_service.update_timeline_request_status(db, request, "complete")

    logger.info(
        "Timeline request complete",
        extra={"request_id": timeline_request_id, "total_items": total_items},
    )
    return {"status": "complete", "timeline_request_id": timeline_request_id, "total_items": total_items}


# ── Celery task ────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="tasks.fetch_imagery_timeline", max_retries=3)  # type: ignore[misc]
def fetch_imagery_timeline(self: Any, timeline_request_id: str) -> dict[str, Any]:  # type: ignore[misc]
    """Fetch NAIP, Landsat, and Sentinel-2 imagery for a timeline request.

    Each source is fetched independently — a failure in one source does not
    prevent the others from completing.

    Args:
        timeline_request_id: UUID string of the TimelineRequest to process.
    """
    logger.info(
        "fetch_imagery_timeline task started",
        extra={"timeline_request_id": timeline_request_id},
    )
    try:
        return asyncio.run(_run_timeline(timeline_request_id))
    except Exception as exc:
        logger.error(
            "Timeline task failed",
            extra={"timeline_request_id": timeline_request_id, "error": str(exc)},
        )
        # Mark the request as failed in the DB
        try:
            from app.db import SessionLocal
            from app.models.parcels import TimelineRequest
            from sqlalchemy import select as sa_select

            req_uuid = uuid.UUID(timeline_request_id)
            with SessionLocal() as db:
                request = db.execute(
                    sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid)
                ).scalars().first()
                if request:
                    imagery_service.update_timeline_request_status(
                        db, request, "failed", error_message=str(exc)
                    )
        except Exception:
            pass
        raise
