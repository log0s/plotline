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
from datetime import date
from typing import Any, cast

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from app.services import demographics as demographics_service
from app.services import geocoder as geocoder_service
from app.services import imagery as imagery_service
from app.services import property_events as property_events_service
from app.services import stac as stac_service
from app.services import usgs_topo as topo_service
from app.services.address_normalizer import extract_search_terms, is_address_match
from app.services.census import (
    ACS5_YEARS,
    DECENNIAL_YEARS,
    CensusApiError,
    CensusFetcher,
    CensusMissingKeyError,
    geography_vintage,
    parse_tract_fips,
)
from app.services.county_adapters import get_adapter_for_county
from app.services.geocoder import GeocoderError
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Source configuration ───────────────────────────────────────────────────────

_SOURCES: list[dict[str, Any]] = [
    {
        "source": "naip",
        "collection": "naip",
        "start_date": "2003-01-01",  # end resolved to the current year at fetch time
        "max_items": 50,
        "query": None,
        "selector": stac_service.select_naip_items,
        "selection_scope": "year",
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": True,  # NAIP: mosaic multiple tiles per year
    },
    {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "start_year": 1984,
        "max_items_per_year": 20,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": stac_service.select_landsat_items,
        "selection_scope": "year",
        "resolution_m": 30.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    },
    {
        "source": "sentinel2",
        "collection": "sentinel-2-l2a",
        "start_year": 2015,
        "max_items_per_year": 20,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": stac_service.select_sentinel_items,
        "selection_scope": "quarter",
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


# ── Task-row status helper ────────────────────────────────────────────────────


def _set_task_status(
    timeline_request_id: uuid.UUID,
    source: str,
    status: str,
    *,
    items_found: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update a per-source task row in its own short-lived session."""
    from sqlalchemy import select as sa_select

    from app.db import SessionLocal
    from app.models.parcels import TimelineRequestTask

    with SessionLocal() as db:
        task_row = (
            db.execute(
                sa_select(TimelineRequestTask)
                .where(TimelineRequestTask.timeline_request_id == timeline_request_id)
                .where(TimelineRequestTask.source == source)
            )
            .scalars()
            .first()
        )
        if not task_row:
            logger.warning("No task row found for source", extra={"source": source})
            return
        imagery_service.update_request_task(
            db, task_row, status, items_found=items_found, error_message=error_message
        )


# ── Async implementation ───────────────────────────────────────────────────────


async def _fetch_source(
    source_cfg: dict[str, Any],
    search_bbox: tuple[float, float, float, float],
    viewport_bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    lat: float,
    lng: float,
) -> int:
    """Fetch one imagery source and persist snapshots. Returns items_found count.

    ``search_bbox`` is the larger buffered bbox used for the STAC query.
    ``viewport_bbox`` is the smaller display viewport used for mosaic-coverage
    selection. Any failure — search, selection, or persistence — marks the
    task row failed so it can't be left at "processing" forever.
    """
    source_name: str = source_cfg["source"]

    logger.info("Starting STAC search", extra={"source": source_name})
    _set_task_status(timeline_request_id, source_name, "processing")

    try:
        return await _search_and_persist_source(
            source_cfg,
            search_bbox,
            viewport_bbox,
            parcel_id,
            timeline_request_id,
            lat,
            lng,
        )
    except Exception as exc:
        logger.error("Imagery source failed", extra={"source": source_name}, exc_info=exc)
        _set_task_status(timeline_request_id, source_name, "failed", error_message=str(exc))
        return 0


async def _search_and_persist_source(
    source_cfg: dict[str, Any],
    search_bbox: tuple[float, float, float, float],
    viewport_bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    lat: float,
    lng: float,
) -> int:
    from app.db import SessionLocal

    source_name: str = source_cfg["source"]
    collection: str = source_cfg["collection"]
    t0 = time.perf_counter()

    # Search STAC (async HTTP, outside any DB session).
    # For sources with a wide historical range we chunk by year so the
    # default "newest first" ordering doesn't cap us at the most recent
    # 100 scenes and miss older years entirely.
    if source_cfg.get("chunk_by_year"):
        start_year = int(source_cfg["start_year"])
        end_year = int(source_cfg.get("end_year") or date.today().year)
        per_year = int(source_cfg["max_items_per_year"])
        raw_items: list[dict[str, object]] = []
        # One bad year is a gap, not a wipeout: retries handle transient
        # 429/5xx/network errors, and a year that still fails after
        # retries is logged and skipped so the other 40 years still land.
        # If *every* year fails the source as a whole has failed.
        years = range(start_year, end_year + 1)
        failed_years = 0
        last_exc: Exception | None = None
        for year in years:
            try:
                chunk = await _search_stac_with_retry(
                    collection=collection,
                    bbox=search_bbox,
                    datetime_range=f"{year}-01-01/{year}-12-31",
                    max_items=per_year,
                    query=source_cfg.get("query"),
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                failed_years += 1
                last_exc = exc
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
        if len(years) > 0 and failed_years == len(years) and last_exc is not None:
            raise last_exc
    else:
        datetime_range = (
            source_cfg.get("datetime_range")
            or f"{source_cfg['start_date']}/{date.today().year}-12-31"
        )
        raw_items = await _search_stac_with_retry(
            collection=collection,
            bbox=search_bbox,
            datetime_range=datetime_range,
            max_items=source_cfg["max_items"],
            query=source_cfg.get("query"),
        )

    # Spatial filter. NAIP uses the looser "intersects viewport" filter so
    # adjacent tiles can contribute to a mosaic; Landsat/S2 use strict
    # point-containment since their scenes already cover a huge area.
    if source_cfg.get("use_viewport_filter"):
        raw_items = stac_service.filter_items_intersecting_bbox(raw_items, viewport_bbox)
    elif lat is not None and lng is not None:
        raw_items = stac_service.filter_items_containing_point(raw_items, lat, lng)

    # Select representative items. NAIP selector accepts the viewport for
    # greedy multi-tile coverage; other selectors ignore it.
    if source_cfg.get("use_viewport_filter"):
        selected_groups: list[list[dict[str, object]]] = source_cfg["selector"](
            raw_items, viewport_bbox
        )
        # The viewport selector optimises coverage *area*, so a year with no
        # covering tile in the collection is served as the nearest
        # neighbours — a whole mosaic of the wrong place. Suppress the year
        # instead; a gap in the timeline is honest.
        if lat is not None and lng is not None:
            selected_groups, uncovered = stac_service.filter_groups_containing_point(
                selected_groups, lat, lng
            )
            for group in uncovered:
                logger.warning(
                    "Suppressing imagery year with no covering tile",
                    extra={
                        "parcel_id": str(parcel_id),
                        "source": source_name,
                        "year": stac_service.extract_capture_date(group[0]).year,
                        "reason": "no selected tile's footprint contains the parcel",
                        "tile_ids": [str(i.get("id")) for i in group],
                    },
                )
    else:
        selected_groups = source_cfg["selector"](raw_items)

    # Validate asset accessibility — older Landsat scenes (1984–1990s) can
    # have broken assets that cause tile-serving 502s, and an S2 quarter can
    # land on an unservable granule the same way.  Drop bad items and swap in
    # the next-best candidate from the same year (Landsat) or quarter (S2).
    if collection == "landsat-c2-l2":
        selected_groups = await stac_service.validate_landsat_selection(
            selected_groups,
            raw_items,
        )
    elif collection == "sentinel-2-l2a":
        selected_groups = await stac_service.validate_sentinel_selection(
            selected_groups,
            raw_items,
        )

    elapsed = time.perf_counter() - t0
    logger.info(
        "STAC search complete",
        extra={
            "source": source_name,
            "raw_count": len(raw_items),
            "selected_groups": len(selected_groups),
            "selected_items": sum(len(g) for g in selected_groups),
            "wall_time_s": round(elapsed, 2),
        },
    )

    # Persist snapshots — one row per group, with primary cog_url and
    # additional_cog_urls for mosaic components.
    items_saved = 0
    selected_refs: list[tuple[str, date]] = []
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
            props = primary.get("properties")
            cloud_cover = (
                cast(dict[str, Any], props).get("eo:cloud_cover")
                if isinstance(props, dict)
                else None
            )
            bbox_wkt = stac_service.extract_bbox_wkt(primary)

            imagery_service.upsert_imagery_snapshot(
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
            items_saved += 1
            selected_refs.append((str(primary["id"]), capture_date))

        # Now that the fresh selection is persisted, drop the scenes it
        # replaced — a re-validated Landsat year picks a different item id,
        # which the upsert inserts alongside the broken row rather than
        # over it.
        #
        # Reconciliation assumes every upsert above is already durable: the
        # upsert commits per row, and this runs in the same task, after the
        # loop. If persistence ever becomes batched or atomic, this call has
        # to move inside that transaction. Ordering is the safety property —
        # an interruption between persist and reconcile leaves duplicates,
        # which the next run cleans up, never an empty source.
        imagery_service.reconcile_source_snapshots(
            db,
            parcel_id,
            source_name,
            selected_refs,
            scope=source_cfg["selection_scope"],
        )

        # Use actual DB count — covers items from prior runs too
        total_items = imagery_service.count_imagery_snapshots(db, parcel_id, source_name)

    _set_task_status(timeline_request_id, source_name, "complete", items_found=total_items)

    logger.info(
        "Imagery source done",
        extra={"source": source_name, "items_saved": items_saved},
    )
    return items_saved


async def _fetch_usgs_topo(
    search_bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
) -> int:
    """Fetch USGS Historical Topographic Maps and persist snapshots.

    Uses the TNM API (not STAC). GeoTIFF URLs are public S3 — no signing.
    """
    source_name = "usgs_topo"

    _set_task_status(timeline_request_id, source_name, "processing")

    try:
        return await _search_and_persist_topo(search_bbox, parcel_id, timeline_request_id)
    except Exception as exc:
        logger.error("USGS topo fetch failed", exc_info=exc)
        _set_task_status(timeline_request_id, source_name, "failed", error_message=str(exc))
        return 0


async def _search_and_persist_topo(
    search_bbox: tuple[float, float, float, float],
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
) -> int:
    from app.db import SessionLocal

    source_name = "usgs_topo"

    raw_items = await topo_service.search_usgs_topo(search_bbox)
    selected = topo_service.select_topo_items(raw_items)

    logger.info(
        "USGS topo search complete",
        extra={"raw_count": len(raw_items), "selected_count": len(selected)},
    )

    items_saved = 0
    selected_refs: list[tuple[str, date]] = []
    with SessionLocal() as db:
        for item in selected:
            cog_url = topo_service.extract_geotiff_url(item)
            if not cog_url:
                continue

            publication_date = topo_service.extract_publication_date(item)
            # A product whose publicationDate will not parse has no year to
            # stand on. It used to be minted as 1900, which is indistinguishable
            # on the timeline from a genuine 1900 sheet. Skip it, as the
            # id-less case below does — one dropped sheet is a gap, not a
            # failure, so the task still completes.
            if publication_date is None:
                logger.warning(
                    "Skipping topo product with unparseable publicationDate",
                    extra={
                        "parcel_id": str(parcel_id),
                        "cog_url": cog_url,
                        "publication_date": str(item.get("publicationDate")),
                    },
                )
                continue

            source_id = topo_service.extract_source_id(item)
            # An id-less product would upsert as stac_item_id="", and the
            # conflict target is (parcel_id, stac_item_id) — so every id-less
            # product on a parcel overwrites the last one, leaving one row
            # where there should be several. Skip them, as the property path
            # already does for records with no id.
            if not source_id:
                logger.warning(
                    "Skipping topo product with no sourceId",
                    extra={"parcel_id": str(parcel_id), "cog_url": cog_url},
                )
                continue

            imagery_service.upsert_imagery_snapshot(
                db,
                parcel_id=parcel_id,
                source=source_name,
                capture_date=publication_date,
                stac_item_id=source_id,
                stac_collection="usgs-historical-topo",
                cog_url=cog_url,
                thumbnail_url=None,
                resolution_m=None,
                cloud_cover_pct=None,
                bbox_wkt=topo_service.extract_bbox_wkt(item),
            )
            items_saved += 1
            selected_refs.append((source_id, publication_date))

        # Same persist-then-reconcile ordering as the STAC sources, scoped to
        # the decade select_topo_items groups by: a later run that picks a
        # different sheet for a decade supersedes the old row rather than
        # stacking a second card on the same period.
        imagery_service.reconcile_source_snapshots(
            db,
            parcel_id,
            source_name,
            selected_refs,
            scope="decade",
        )

        total_items = imagery_service.count_imagery_snapshots(db, parcel_id, source_name)

    _set_task_status(timeline_request_id, source_name, "complete", items_found=total_items)

    logger.info("USGS topo done", extra={"items_saved": items_saved})
    return items_saved


async def _fetch_census(
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    tract_fips: str,
    api_key: str | None = None,
    timeout: float = 30.0,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    """Fetch Census Bureau data for a parcel's tract and persist snapshots.

    Coordinates are optional: without them every year is fetched against the
    stored (current-vintage) tract, which is the pre-existing behaviour.

    Returns the number of census snapshots saved.
    """
    try:
        parse_tract_fips(tract_fips)
    except ValueError as exc:
        logger.warning("Invalid tract FIPS", exc_info=exc)
        _set_task_status(timeline_request_id, "census", "skipped", error_message=str(exc))
        return 0

    _set_task_status(timeline_request_id, "census", "processing")

    try:
        return await _fetch_census_years(
            parcel_id,
            timeline_request_id,
            tract_fips,
            api_key,
            timeout,
            latitude,
            longitude,
        )
    except Exception as exc:
        logger.error("Census fetch failed", extra={"tract": tract_fips}, exc_info=exc)
        _set_task_status(timeline_request_id, "census", "failed", error_message=str(exc))
        return 0


class _VintageTracts:
    """Resolves and caches the tract containing a point, per geography vintage.

    One geocoder call per distinct vintage per parcel.  A vintage that yields
    no tract, or a geocoder outage, falls back to the stored tract — the same
    request the code made before per-vintage resolution existed, so the worst
    case is today's behaviour rather than a lost year.
    """

    def __init__(
        self,
        stored_tract: str,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        self._stored = stored_tract
        self._lat = latitude
        self._lon = longitude
        self._cache: dict[str, str] = {}

    async def tract_for(self, dataset: str, year: int) -> str:
        vintage = geography_vintage(dataset, year)
        if vintage is None or self._lat is None or self._lon is None:
            return self._stored
        if vintage in self._cache:
            return self._cache[vintage]

        from app.config import get_settings

        try:
            resolved = await geocoder_service.lookup_tract_at_vintage(
                self._lat, self._lon, vintage, get_settings()
            )
        except GeocoderError as exc:
            logger.warning(
                "Vintage tract lookup failed, using stored tract",
                extra={"vintage": vintage, "tract": self._stored},
                exc_info=exc,
            )
            resolved = None

        tract = resolved or self._stored
        self._cache[vintage] = tract
        logger.info(
            "Resolved tract for vintage",
            extra={"vintage": vintage, "tract": tract, "stored_tract": self._stored},
        )
        return tract


async def _fetch_census_years(
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    tract_fips: str,
    api_key: str | None,
    timeout: float,
    latitude: float | None = None,
    longitude: float | None = None,
) -> int:
    from app.db import SessionLocal

    fetcher = CensusFetcher(api_key=api_key, timeout=timeout)
    tracts = _VintageTracts(tract_fips, latitude, longitude)
    items_saved = 0
    failed_requests = 0

    try:
        # Fetch decennial data
        for year in DECENNIAL_YEARS:
            year_tract = await tracts.tract_for("decennial", year)
            state_fips, county_fips, tract_code = parse_tract_fips(year_tract)
            try:
                data = await fetcher.fetch_decennial(year, state_fips, county_fips, tract_code)
                if data:
                    with SessionLocal() as db:
                        demographics_service.upsert_census_snapshot(
                            db,
                            parcel_id=parcel_id,
                            tract_fips=year_tract,
                            dataset="decennial",
                            year=year,
                            data=data,
                            raw_data=data,
                        )
                        items_saved += 1
                    logger.info("Census decennial saved", extra={"year": year, "tract": year_tract})
            except CensusApiError as exc:
                failed_requests += 1
                logger.warning("Census decennial failed", extra={"year": year}, exc_info=exc)
                if isinstance(exc, CensusMissingKeyError):
                    raise
            # Be a good citizen — small delay between requests
            await asyncio.sleep(0.5)

        # Fetch ACS 5-year data
        for year in ACS5_YEARS:
            year_tract = await tracts.tract_for("acs5", year)
            state_fips, county_fips, tract_code = parse_tract_fips(year_tract)
            try:
                data = await fetcher.fetch_acs5(year, state_fips, county_fips, tract_code)
                if data:
                    with SessionLocal() as db:
                        demographics_service.upsert_census_snapshot(
                            db,
                            parcel_id=parcel_id,
                            tract_fips=year_tract,
                            dataset="acs5",
                            year=year,
                            data=data,
                            raw_data=data,
                        )
                        items_saved += 1
                    logger.info("Census ACS5 saved", extra={"year": year, "tract": year_tract})
            except CensusApiError as exc:
                failed_requests += 1
                logger.warning("Census ACS5 failed", extra={"year": year}, exc_info=exc)
                if isinstance(exc, CensusMissingKeyError):
                    raise
            await asyncio.sleep(0.5)

    finally:
        await fetcher.close()

    # Every single request erroring is an outage, not "tract has no data" —
    # marking it complete-with-0 would permanently mask the gap because
    # backfill only refetches missing or failed census tasks.
    if failed_requests == len(DECENNIAL_YEARS) + len(ACS5_YEARS):
        _set_task_status(
            timeline_request_id,
            "census",
            "failed",
            error_message="All Census API requests failed",
        )
        return 0

    with SessionLocal() as db:
        total_items = demographics_service.count_census_snapshots(db, parcel_id)

    _set_task_status(timeline_request_id, "census", "complete", items_found=total_items)

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
    adapter = get_adapter_for_county(county)
    if not adapter:
        logger.info(
            "No property adapter for county",
            extra={"county": county, "parcel_id": str(parcel_id)},
        )
        _set_task_status(
            timeline_request_id,
            "property",
            "skipped",
            error_message=f"Property data not yet available for {county} County",
        )
        return 0

    _set_task_status(timeline_request_id, "property", "processing")

    # Extract search terms from the normalized address
    street_number, street_name = extract_search_terms(normalized_address)
    if not street_number:
        logger.warning(
            "Could not extract search terms from address",
            extra={"address": normalized_address},
        )
        _set_task_status(
            timeline_request_id,
            "property",
            "failed",
            error_message="Could not extract search terms from address",
        )
        return 0

    try:
        return await _fetch_and_persist_property(
            adapter,
            parcel_id,
            timeline_request_id,
            county,
            normalized_address,
            street_number,
            street_name,
            app_token,
        )
    except Exception as exc:
        logger.error("Property fetch failed", extra={"county": county}, exc_info=exc)
        _set_task_status(timeline_request_id, "property", "failed", error_message=str(exc))
        return 0


async def _fetch_and_persist_property(
    adapter: Any,
    parcel_id: uuid.UUID,
    timeline_request_id: uuid.UUID,
    county: str,
    normalized_address: str,
    street_number: str,
    street_name: str,
    app_token: str | None,
) -> int:
    from app.db import SessionLocal

    logger.info(
        "Fetching property history",
        extra={
            "county": county,
            "street_number": street_number,
            "street_name": street_name,
        },
    )

    sales, permits = await asyncio.gather(
        adapter.fetch_sales(street_number, street_name, app_token=app_token),
        adapter.fetch_permits(street_number, street_name, app_token=app_token),
    )

    # Every query erroring is a portal outage, not "this address has no
    # records" — marking it complete-with-0 would permanently mask the gap
    # because backfill only refetches missing, skipped, or failed tasks.
    queries_attempted = sales.queries_attempted + permits.queries_attempted
    queries_failed = sales.queries_failed + permits.queries_failed
    if queries_attempted > 0 and queries_failed == queries_attempted:
        logger.warning(
            "All property queries failed",
            extra={"county": county, "queries": queries_attempted},
        )
        _set_task_status(
            timeline_request_id,
            "property",
            "failed",
            error_message=f"All {county} County property queries failed",
        )
        return 0

    all_events = [*sales.events, *permits.events]

    # Filter by fuzzy address match — the LIKE queries are deliberately
    # broad, so records for other properties must be rejected here.
    matched_events = []
    for event in all_events:
        if event.situs_address and not is_address_match(normalized_address, event.situs_address):
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

    items_saved = 0
    with SessionLocal() as db:
        for event in matched_events:
            if not event.source_record_id:
                continue
            property_events_service.upsert_property_event(
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
            items_saved += 1

        total_items = property_events_service.count_property_events(db, parcel_id)

    _set_task_status(timeline_request_id, "property", "complete", items_found=total_items)

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
        await topo_service.close_client()
        from app.db import close_async_redis

        await close_async_redis()


async def _run_timeline_inner(timeline_request_id: str) -> dict[str, Any]:
    from sqlalchemy import select as sa_select

    from app.db import SessionLocal
    from app.models.parcels import TimelineRequest

    req_uuid = uuid.UUID(timeline_request_id)

    # Load the request and its parcel
    with SessionLocal() as db:
        request = (
            db.execute(
                sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid).with_for_update()
            )
            .scalars()
            .first()
        )
        if not request:
            raise ValueError(f"TimelineRequest {timeline_request_id!r} not found")

        parcel_id = request.parcel_id
        if not parcel_id:
            raise ValueError("TimelineRequest has no parcel_id")

        from app.models.parcels import Parcel

        parcel = db.execute(sa_select(Parcel).where(Parcel.id == parcel_id)).scalars().first()
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
        sources.append("usgs_topo")
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
        coros.append(
            (
                source_cfg["source"],
                _fetch_source(
                    source_cfg,
                    search_bbox,
                    viewport_bbox,
                    parcel_id,
                    req_uuid,
                    lat,
                    lng,
                ),
            )
        )
    coros.append(
        (
            "usgs_topo",
            _fetch_usgs_topo(search_bbox, parcel_id, req_uuid),
        )
    )
    if tract_fips:
        coros.append(
            (
                "census",
                _fetch_census(
                    parcel_id,
                    req_uuid,
                    tract_fips,
                    api_key=settings.census_api_key,
                    timeout=settings.census_api_timeout,
                    latitude=lat,
                    longitude=lng,
                ),
            )
        )
    if county:
        coros.append(
            (
                "property",
                _fetch_property(
                    parcel_id,
                    req_uuid,
                    county,
                    normalized_address,
                    app_token=settings.socrata_app_token,
                ),
            )
        )

    results = await asyncio.gather(
        *(c for _, c in coros),
        return_exceptions=True,
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

        request = (
            db.execute(sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid))
            .scalars()
            .first()
        )
        if request:
            task_rows = (
                db.execute(
                    sa_select(TimelineRequestTask).where(
                        TimelineRequestTask.timeline_request_id == req_uuid
                    )
                )
                .scalars()
                .all()
            )
            if task_rows and all(t.status == "failed" for t in task_rows):
                failed_sources = ", ".join(t.source for t in task_rows)
                imagery_service.update_timeline_request_status(
                    db,
                    request,
                    "failed",
                    error_message=f"All sources failed: {failed_sources}",
                )
            else:
                imagery_service.update_timeline_request_status(db, request, "complete")

    logger.info(
        "Timeline request complete",
        extra={"request_id": timeline_request_id, "total_items": total_items},
    )
    return {
        "status": "complete",
        "timeline_request_id": timeline_request_id,
        "total_items": total_items,
    }


# ── Celery task ────────────────────────────────────────────────────────────────


# time_limit is coupled to the broker's visibility timeout: with task_acks_late,
# Redis redelivers a task another worker is still running once visibility_timeout
# (default 3600s) elapses. 2100s leaves 25 minutes of margin — raising time_limit
# past 3600 silently enables duplicate execution of the same request.
@celery_app.task(
    bind=True,
    name="tasks.fetch_imagery_timeline",
    soft_time_limit=1800,
    time_limit=2100,
)  # type: ignore[untyped-decorator]  # Celery task decorator lacks complete type stubs
def fetch_imagery_timeline(self: Any, timeline_request_id: str) -> dict[str, Any]:
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
    except SoftTimeLimitExceeded:
        logger.error(
            "Timeline request %s timed out after 30 minutes",
            timeline_request_id,
        )
        try:
            from sqlalchemy import select as sa_select

            from app.db import SessionLocal
            from app.models.parcels import TimelineRequest

            req_uuid = uuid.UUID(timeline_request_id)
            with SessionLocal() as db:
                request = (
                    db.execute(sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid))
                    .scalars()
                    .first()
                )
                if request:
                    imagery_service.update_timeline_request_status(
                        db, request, "failed", error_message="Task timed out"
                    )
        except Exception:
            logger.debug("Failed to mark request as failed during timeout handling", exc_info=True)
        raise
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
                request = (
                    db.execute(sa_select(TimelineRequest).where(TimelineRequest.id == req_uuid))
                    .scalars()
                    .first()
                )
                if request:
                    imagery_service.update_timeline_request_status(
                        db, request, "failed", error_message=str(exc)
                    )
        except Exception:
            logger.debug("Failed to mark request as failed during error handling", exc_info=True)
        raise
