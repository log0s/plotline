"""Imagery timeline + census demographics Celery task.

Searches Planetary Computer STAC for NAIP, Landsat, and Sentinel-2 imagery
at a parcel location, then persists the results as imagery_snapshots rows.
Also fetches Census Bureau demographic data for the parcel's tract.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx

from app.services import demographics as demographics_service
from app.services import imagery as imagery_service
from app.services import property_events as property_events_service
from app.services import stac as stac_service
from app.services.address_normalizer import extract_search_terms, is_address_match
from app.services.census import (
    ACS5_YEARS,
    DECENNIAL_YEARS,
    CensusApiError,
    CensusFetcher,
    parse_tract_fips,
)
from app.services.county_adapters import get_adapter_for_county
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
        "chunk_by_year": False,
        "use_viewport_filter": True,  # NAIP: mosaic multiple tiles per year
    },
    {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "start_year": 1984,
        "end_year": 2025,
        "max_items_per_year": 20,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": stac_service.select_landsat_items,
        "resolution_m": 30.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    },
    {
        "source": "sentinel2",
        "collection": "sentinel-2-l2a",
        "start_year": 2015,
        "end_year": 2025,
        "max_items_per_year": 20,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": stac_service.select_sentinel_items,
        "resolution_m": 10.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    },
]


# ── STAC retry helper ─────────────────────────────────────────────────────────

_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


async def _search_stac_with_retry(
    *,
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_items: int,
    query: dict[str, object] | None = None,
    attempts: int = 3,
) -> list[dict[str, object]]:
    """Call ``stac_service.search_stac`` with bounded exponential backoff.

    Retries on transient network errors and retryable HTTP statuses
    (429 / 500 / 502 / 503 / 504). Non-retryable HTTPStatusError (4xx
    other than 429) propagates immediately. After ``attempts`` retries
    the last exception is re-raised so the caller can decide whether
    to skip-and-continue or fail.
    """
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await stac_service.search_stac(
                collection=collection,
                bbox=bbox,
                datetime_range=datetime_range,
                max_items=max_items,
                query=query,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_HTTP_STATUSES:
                raise
            last_exc = exc
        except httpx.RequestError as exc:
            last_exc = exc
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
            delay *= 2
    assert last_exc is not None  # only reached when at least one attempt failed
    raise last_exc


# ── Async implementation ───────────────────────────────────────────────────────


async def _fetch_source(
    source_cfg: dict[str, Any],
    search_bbox: tuple[float, float, float, float],
    viewport_bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    lat: float = 0.0,
    lng: float = 0.0,
) -> int:
    """Fetch one imagery source and persist snapshots. Returns items_found count.

    ``search_bbox`` is the larger buffered bbox used for the STAC query.
    ``viewport_bbox`` is the smaller display viewport used for mosaic-coverage
    selection.
    """
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

    # Search STAC (async HTTP, outside the DB session).
    # For sources with a wide historical range we chunk by year so the
    # default "newest first" ordering doesn't cap us at the most recent
    # 100 scenes and miss older years entirely.
    try:
        if source_cfg.get("chunk_by_year"):
            start_year = int(source_cfg["start_year"])
            end_year = int(source_cfg["end_year"])
            per_year = int(source_cfg["max_items_per_year"])
            raw_items: list[dict[str, object]] = []
            # One bad year is a gap, not a wipeout: retries handle transient
            # 429/5xx/network errors, and a year that still fails after
            # retries is logged and skipped so the other 40 years still land.
            for year in range(start_year, end_year + 1):
                try:
                    chunk = await _search_stac_with_retry(
                        collection=collection,
                        bbox=search_bbox,
                        datetime_range=f"{year}-01-01/{year}-12-31",
                        max_items=per_year,
                        query=source_cfg.get("query"),
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    logger.warning(
                        "STAC year chunk failed after retries; skipping",
                        extra={
                            "source": source_name,
                            "year": year,
                            "error": str(exc),
                        },
                    )
                    continue
                raw_items.extend(chunk)
        else:
            raw_items = await _search_stac_with_retry(
                collection=collection,
                bbox=search_bbox,
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
            from sqlalchemy import select as sa_select

            from app.models.parcels import TimelineRequestTask

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

    # Spatial filter. NAIP uses the looser "intersects viewport" filter so
    # adjacent tiles can contribute to a mosaic; Landsat/S2 use strict
    # point-containment since their scenes already cover a huge area.
    if source_cfg.get("use_viewport_filter"):
        raw_items = stac_service.filter_items_intersecting_bbox(
            raw_items, viewport_bbox
        )
    elif lat and lng:
        raw_items = stac_service.filter_items_containing_point(raw_items, lat, lng)

    # Select representative items. NAIP selector accepts the viewport for
    # greedy multi-tile coverage; other selectors ignore it.
    if source_cfg.get("use_viewport_filter"):
        selected_groups: list[list[dict[str, object]]] = source_cfg["selector"](
            raw_items, viewport_bbox
        )
    else:
        selected_groups = source_cfg["selector"](raw_items)

    elapsed = time.perf_counter() - t0
    logger.info(
        f"STAC search complete: {source_name}",
        extra={
            "raw_count": len(raw_items),
            "selected_groups": len(selected_groups),
            "selected_items": sum(len(g) for g in selected_groups),
            "wall_time_s": round(elapsed, 2),
        },
    )

    # Persist snapshots — one row per group, with primary cog_url and
    # additional_cog_urls for mosaic components.
    items_saved = 0
    with SessionLocal() as db:
        for group in selected_groups:
            if not group:
                continue
            primary = group[0]
            primary_cog_url = stac_service.extract_cog_url(primary, collection)
            if not primary_cog_url:
                continue

            additional_urls: list[str] = []
            for extra_item in group[1:]:
                extra_url = stac_service.extract_cog_url(extra_item, collection)
                if extra_url:
                    additional_urls.append(extra_url)

            thumbnail_url = stac_service.extract_thumbnail_url(primary)
            capture_date = stac_service.extract_capture_date(primary)
            cloud_cover = primary.get("properties", {}).get("eo:cloud_cover")  # type: ignore[union-attr]
            bbox_wkt = stac_service.extract_bbox_wkt(primary)

            was_inserted = imagery_service.upsert_imagery_snapshot(
                db,
                parcel_id=parcel_id,
                source=source_name,
                capture_date=capture_date,
                stac_item_id=str(primary["id"]),
                stac_collection=collection,
                cog_url=primary_cog_url,
                additional_cog_urls=additional_urls or None,
                thumbnail_url=thumbnail_url,
                resolution_m=source_cfg["resolution_m"],
                cloud_cover_pct=float(cloud_cover) if cloud_cover is not None else None,
                bbox_wkt=bbox_wkt,
            )
            if was_inserted:
                items_saved += 1

        # Update task status
        from sqlalchemy import select as sa_select

        from app.models.parcels import TimelineRequestTask

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


async def _fetch_census(
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    tract_fips: str,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> int:
    """Fetch Census Bureau data for a parcel's tract and persist snapshots.

    Returns the number of census snapshots saved.
    """
    from sqlalchemy import select as sa_select

    from app.db import SessionLocal
    from app.models.parcels import TimelineRequestTask

    try:
        state_fips, county_fips, tract_code = parse_tract_fips(tract_fips)
    except ValueError as exc:
        logger.warning(f"Invalid tract FIPS: {exc}")
        with SessionLocal() as db:
            task_row = db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
                .where(TimelineRequestTask.source == "census")
            ).scalars().first()
            if task_row:
                imagery_service.update_request_task(
                    db, task_row, "skipped", error_message=str(exc)
                )
        return 0

    # Mark task as processing
    with SessionLocal() as db:
        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == "census")
        ).scalars().first()
        if task_row:
            imagery_service.update_request_task(db, task_row, "processing")

    fetcher = CensusFetcher(api_key=api_key, timeout=timeout)
    items_saved = 0

    try:
        # Fetch decennial data
        for year in DECENNIAL_YEARS:
            try:
                data = await fetcher.fetch_decennial(
                    year, state_fips, county_fips, tract_code
                )
                if data:
                    with SessionLocal() as db:
                        demographics_service.upsert_census_snapshot(
                            db,
                            parcel_id=parcel_id,
                            tract_fips=tract_fips,
                            dataset="decennial",
                            year=year,
                            data=data,
                            raw_data=data,
                        )
                        items_saved += 1
                    logger.info(f"Census decennial {year} saved", extra={"tract": tract_fips})
            except CensusApiError as exc:
                logger.warning(f"Census decennial {year} failed: {exc}")
            # Be a good citizen — small delay between requests
            await asyncio.sleep(0.5)

        # Fetch ACS 5-year data
        for year in ACS5_YEARS:
            try:
                data = await fetcher.fetch_acs5(
                    year, state_fips, county_fips, tract_code
                )
                if data:
                    with SessionLocal() as db:
                        demographics_service.upsert_census_snapshot(
                            db,
                            parcel_id=parcel_id,
                            tract_fips=tract_fips,
                            dataset="acs5",
                            year=year,
                            data=data,
                            raw_data=data,
                        )
                        items_saved += 1
                    logger.info(f"Census ACS5 {year} saved", extra={"tract": tract_fips})
            except CensusApiError as exc:
                logger.warning(f"Census ACS5 {year} failed: {exc}")
            await asyncio.sleep(0.5)

    finally:
        await fetcher.close()

    # Update task status
    with SessionLocal() as db:
        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == "census")
        ).scalars().first()
        if task_row:
            imagery_service.update_request_task(
                db, task_row, "complete", items_found=items_saved
            )

    logger.info("Census fetch complete", extra={"items_saved": items_saved, "tract": tract_fips})
    return items_saved


async def _fetch_property(
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    county: str,
    normalized_address: str,
    app_token: str | None = None,
) -> int:
    """Fetch property history from county open data and persist events.

    Returns the number of events saved.
    """
    from sqlalchemy import select as sa_select

    from app.db import SessionLocal
    from app.models.parcels import TimelineRequestTask

    adapter = get_adapter_for_county(county)

    # Mark task processing / skipped
    with SessionLocal() as db:
        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == "property")
        ).scalars().first()

        if not adapter:
            logger.info(
                f"No property adapter for county: {county}",
                extra={"parcel_id": str(parcel_id)},
            )
            if task_row:
                imagery_service.update_request_task(
                    db, task_row, "skipped",
                    error_message=f"Property data not yet available for {county} County",
                )
            return 0

        if task_row:
            imagery_service.update_request_task(db, task_row, "processing")

    # Extract search terms from the normalized address
    street_number, street_name = extract_search_terms(normalized_address)
    if not street_number:
        logger.warning("Could not extract search terms from address", extra={
            "address": normalized_address,
        })
        with SessionLocal() as db:
            task_row = db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
                .where(TimelineRequestTask.source == "property")
            ).scalars().first()
            if task_row:
                imagery_service.update_request_task(
                    db, task_row, "failed",
                    error_message="Could not extract search terms from address",
                )
        return 0

    logger.info(
        "Fetching property history",
        extra={
            "county": county,
            "street_number": street_number,
            "street_name": street_name,
        },
    )

    # Fetch sales and permits in parallel
    all_events = []
    try:
        sales, permits = await asyncio.gather(
            adapter.fetch_sales(street_number, street_name, app_token=app_token),
            adapter.fetch_permits(street_number, street_name, app_token=app_token),
        )
        all_events.extend(sales)
        all_events.extend(permits)
    except Exception as exc:
        logger.error(f"Property fetch failed for {county}: {exc}")
        with SessionLocal() as db:
            task_row = db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
                .where(TimelineRequestTask.source == "property")
            ).scalars().first()
            if task_row:
                imagery_service.update_request_task(
                    db, task_row, "failed", error_message=str(exc),
                )
        return 0

    # Filter by fuzzy address match
    matched_events = []
    for event in all_events:
        # Check if raw_data has an address field to compare
        raw_addr = (
            event.raw_data.get("address")
            or event.raw_data.get("situs_address")
            or ""
        )
        if raw_addr and not is_address_match(normalized_address, raw_addr):
            continue
        matched_events.append(event)

    logger.info(
        "Property events filtered",
        extra={
            "raw_count": len(all_events),
            "matched_count": len(matched_events),
            "county": county,
        },
    )

    # Persist events
    items_saved = 0
    with SessionLocal() as db:
        for event in matched_events:
            if not event.source_record_id:
                continue
            was_inserted = property_events_service.upsert_property_event(
                db,
                parcel_id=parcel_id,
                event_type=event.event_type,
                event_date=event.event_date,
                sale_price=event.sale_price,
                permit_type=event.permit_type,
                permit_description=event.permit_description,
                permit_valuation=event.permit_valuation,
                description=event.description,
                source=event.source,
                source_record_id=event.source_record_id,
                raw_data=event.raw_data,
            )
            if was_inserted:
                items_saved += 1

        # Update task status
        task_row = db.execute(
            sa_select(TimelineRequestTask)
            .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
            .where(TimelineRequestTask.source == "property")
        ).scalars().first()
        if task_row:
            imagery_service.update_request_task(
                db, task_row, "complete", items_found=items_saved,
            )

    logger.info(
        "Property history fetch complete",
        extra={"items_saved": items_saved, "county": county},
    )
    return items_saved


async def _run_timeline(timeline_request_id: str) -> dict[str, Any]:
    """Orchestrate all imagery sources for a timeline request."""
    try:
        return await _run_timeline_inner(timeline_request_id)
    finally:
        await stac_service.close_clients()
        from app.db import close_async_redis
        await close_async_redis()


async def _run_timeline_inner(timeline_request_id: str) -> dict[str, Any]:
    from sqlalchemy import select as sa_select

    from app.db import SessionLocal
    from app.models.parcels import TimelineRequest

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
        tract_fips = parcel.census_tract_id
        county = parcel.county
        normalized_address = parcel.normalized_address or parcel.address

        # Transition to processing
        imagery_service.update_timeline_request_status(db, request, "processing")

        # Create per-source task rows
        sources = [s["source"] for s in _SOURCES]
        if tract_fips:
            sources.append("census")
        if county:
            sources.append("property")
        imagery_service.create_request_tasks(
            db,
            timeline_request_id=req_uuid,
            sources=sources,
        )

    # Compute bounding boxes:
    #  - search_bbox: wider buffer for the STAC query itself
    #  - viewport_bbox: the display viewport used for NAIP mosaic-coverage
    #    selection. Sized to match the frontend MapView at its default
    #    zoom (~15) plus the widest featured-preview aspect — so the
    #    mosaic covers whatever the user can actually see on screen.
    search_bbox = stac_service.point_to_bbox(lat, lng, buffer_m=1500)
    viewport_bbox = stac_service.point_to_bbox(lat, lng, buffer_m=1250)
    logger.info(
        "Timeline bbox computed",
        extra={
            "parcel_id": str(parcel_id),
            "search_bbox": search_bbox,
            "viewport_bbox": viewport_bbox,
        },
    )

    # Run all sources concurrently. Each coroutine manages its own DB
    # session, per-source task row, and count return, so there's no
    # shared mutable state. ``return_exceptions=True`` keeps a single
    # source raising from cancelling its siblings.
    from app.config import get_settings
    settings = get_settings()

    coros: list[tuple[str, Any]] = []
    for source_cfg in _SOURCES:
        coros.append((
            source_cfg["source"],
            _fetch_source(
                source_cfg, search_bbox, viewport_bbox, parcel_id, req_uuid, lat, lng,
            ),
        ))
    if tract_fips:
        coros.append((
            "census",
            _fetch_census(
                parcel_id, req_uuid, tract_fips,
                api_key=settings.census_api_key,
                timeout=settings.census_api_timeout,
            ),
        ))
    if county:
        coros.append((
            "property",
            _fetch_property(
                parcel_id, req_uuid, county, normalized_address,
                app_token=settings.socrata_app_token,
            ),
        ))

    results = await asyncio.gather(
        *(c for _, c in coros), return_exceptions=True,
    )

    total_items = 0
    for (source_name, _coro), result in zip(coros, results, strict=True):
        if isinstance(result, BaseException):
            logger.error(
                "Unexpected error for source",
                extra={"source": source_name, "error": str(result)},
            )
        else:
            total_items += result

    # Mark request "failed" only if every per-source task ended up "failed";
    # otherwise "complete". A single success or a "skipped" task (e.g. county
    # not yet supported) is enough to keep the parent complete — per-task rows
    # already expose the per-source breakdown via GET /timeline-requests/{id}.
    with SessionLocal() as db:
        from app.models.parcels import TimelineRequestTask

        request = db.execute(
            sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid)
        ).scalars().first()
        if request:
            task_rows = db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == req_uuid)
            ).scalars().all()
            if task_rows and all(t.status == "failed" for t in task_rows):
                failed_sources = ", ".join(t.source for t in task_rows)
                imagery_service.update_timeline_request_status(
                    db, request, "failed",
                    error_message=f"All sources failed: {failed_sources}",
                )
            else:
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
        # Boundary: anything escaping _run_timeline gets surfaced as a
        # failed TimelineRequest so the user sees a definitive status.
        logger.error(
            "Timeline task failed",
            extra={"timeline_request_id": timeline_request_id, "error": str(exc)},
        )
        try:
            from sqlalchemy import select as sa_select

            from app.db import SessionLocal
            from app.models.parcels import TimelineRequest

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
            # Cleanup-of-cleanup: if marking failed itself fails (DB down,
            # stale request id), swallow so we still re-raise the original
            # exception below for Celery's retry/visibility.
            pass
        raise
