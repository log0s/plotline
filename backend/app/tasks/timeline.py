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
from typing import Any

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from app.services import demographics as demographics_service
from app.services import geocoder as geocoder_service
from app.services import imagery as imagery_service
from app.services import property_events as property_events_service
from app.services import stac as stac_service
from app.services import usgs_topo as topo_service
from app.services import year_ledger
from app.services.address_normalizer import (
    city_from_address,
    extract_search_terms,
    is_address_match,
)
from app.services.census import (
    ACS5_YEARS,
    DECENNIAL_YEARS,
    CensusApiError,
    CensusFetcher,
    CensusHttpStatusError,
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
        # The PC `naip` collection's own temporal extent starts 2010-01-01
        # (verified 2026-08-13 against /api/stac/v1/collections/naip:
        # interval [["2010-01-01T00:00:00Z", "2023-12-31T00:00:00Z"]]), so the
        # 2003 start this used to carry queried six years the source never
        # had. That floor — not truncation, not flight cycles — is what the
        # fleet-wide 2010 histogram floor measures (STATUS.md T4).
        # The end stays open, resolved to the current year at fetch time: the
        # collection's extent end trails the data as new flights land.
        "start_date": f"{imagery_service.IMAGERY_SOURCE_START_YEAR['naip']}-01-01",
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
        "start_year": imagery_service.IMAGERY_SOURCE_START_YEAR["landsat"],
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
        "start_year": imagery_service.IMAGERY_SOURCE_START_YEAR["sentinel2"],
        "max_items_per_year": 20,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": stac_service.select_sentinel_items,
        # Year, not quarter, since 2026-08-25: the 20-item cap below plus
        # PC's newest-first ordering makes Q1/Q2 unreachable on any year
        # that saturates it, so an absent quarter never meant anything.
        # See select_sentinel_items for the measurement.
        "selection_scope": "year",
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


# ── Per-year ledger helpers ───────────────────────────────────────────────────


def _stac_failure_reason(exc: Exception) -> str:
    """Map a STAC search exception to a ledger reason.

    A 429 lands in ``other`` with its status in ``detail``: the vocabulary's
    ``sign_429`` names the signing endpoint, and inventing a ``stac_429``
    here would put a reason in the table that no reader knows to look for.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 403:
            return "stac_403"
        if 500 <= status < 600:
            return "stac_5xx"
        return "other"
    if isinstance(exc, httpx.TimeoutException):
        return "read_timeout"
    return "connect_error"


def _census_failure_reason(exc: Exception) -> str:
    """Map a CensusApiError to a ledger reason.

    ``CensusFetcher._request`` wraps every ``httpx.HTTPError`` as
    ``CensusApiError(f"HTTP error: {exc}")``, so the transport type survives
    only on ``__cause__`` — which the ``raise ... from exc`` there sets. A
    non-200 status arrives as ``CensusHttpStatusError`` and carries the status
    itself, so it becomes ``http_<status>`` rather than ``other``: an endpoint
    that errors must never aggregate with a tract that has no data.
    """
    if isinstance(exc, CensusHttpStatusError):
        return f"http_{exc.status_code}"
    cause = exc.__cause__
    if isinstance(cause, httpx.TimeoutException):
        return "read_timeout"
    if isinstance(cause, httpx.TransportError):
        return "connect_error"
    return "other"


def _geocoder_failure_reason(exc: Exception) -> str:
    """Map a `GeocoderUnavailableError` from a vintage tract lookup to a ledger reason.

    `lookup_tract_at_vintage` (Z6) wraps every failure as
    `GeocoderUnavailableError`, keeping the original error on `__cause__`: a
    terminal status (4xx, or a 5xx after retries) as `httpx.HTTPStatusError`,
    a retry-exhausted transport failure as the `httpx.RequestError` itself.
    Mirrors `_census_failure_reason`.
    """
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return f"http_{cause.response.status_code}"
    if isinstance(cause, httpx.TimeoutException):
        return "read_timeout"
    if isinstance(cause, httpx.TransportError):
        return "connect_error"
    return "other"


def _range_years(datetime_range: str) -> list[int]:
    """The calendar years an un-chunked source's single search covered.

    NAIP has no per-year fetch loop, so its attempted set is not observable
    from the response — but the query's own date range says which years it
    asked about, and that is what "attempted" means. Returns [] if the range
    is not the ``start/end`` shape the config builds.
    """
    start, _, end = datetime_range.partition("/")
    try:
        first, last = int(start[:4]), int(end[:4])
    except ValueError:
        return []
    if last < first:
        return []
    return list(range(first, last + 1))


async def _classify_empty_chunk(
    *,
    collection: str,
    bbox: tuple[float, float, float, float],
    year: int,
    per_year: int,
) -> tuple[str, str | None]:
    """Why did this year's cloud-filtered search come back empty?

    Landsat and Sentinel-2 push ``eo:cloud_cover < 40`` into the STAC query,
    so a year with nothing but cloudy scenes and a year the satellite never
    imaged both arrive as an empty list. The O6 check found nine 2015 S2 gaps
    that all had covering scenes — cloud-filtered, not scene-absent — and
    those are different answers to "should a heal retry this".

    One extra search per empty year settles it, capped at a single item.
    Empty years are rare (fleet Landsat sits at 43 of 43 years for most
    parcels), so this is a handful of requests per run, not a second pass.
    A probe that itself fails leaves the year ``indeterminate`` rather than
    guessing.
    """
    try:
        probe = await _search_stac_with_retry(
            collection=collection,
            bbox=bbox,
            datetime_range=f"{year}-01-01/{year}-12-31",
            max_items=1,
            query=None,
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return (
            "indeterminate",
            "cloud-probe failed at timeline._classify_empty_chunk; "
            f"cannot tell no_scenes from all_cloud_filtered: {exc}"[:400],
        )
    if probe:
        return "absent", "all_cloud_filtered"
    return "absent", "no_scenes"


def _flush_ledger(
    ledger: year_ledger.YearOutcomeLog,
    timeline_request_id: uuid.UUID,
    source: str,
) -> None:
    """Write a staged ledger in its own session.

    For the paths that raise before reaching the persist session — a whole
    search failing — so the record of what was attempted survives the
    exception that ends the task.
    """
    from app.db import SessionLocal

    with SessionLocal() as db:
        task_id = year_ledger.get_task_id(db, timeline_request_id, source)
        if task_id is None:
            logger.warning("No task row for ledger flush", extra={"source": source})
            return
        ledger.flush(db, task_id)


# ── Task-row status helper ────────────────────────────────────────────────────


def _set_task_status(
    timeline_request_id: uuid.UUID,
    source: str,
    status: str,
    *,
    items_found: int | None = None,
    error_message: str | None = None,
    counts: imagery_service.TaskCounts | None = None,
    clear_items_found: bool = False,
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
            db,
            task_row,
            status,
            items_found=items_found,
            error_message=error_message,
            counts=counts,
            clear_items_found=clear_items_found,
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
    scope: str = source_cfg["selection_scope"]
    t0 = time.perf_counter()

    # The per-year ledger for this source. Non-``ok`` outcomes accumulate
    # here through the async phase and land in the persist session; ``ok``
    # rows are written inline beside their snapshot so the two commit
    # together.
    ledger = year_ledger.YearOutcomeLog(source_name)
    attempted: list[str] = []
    raw_by_key: dict[str, int] = {}
    truncated = False

    # Search STAC (async HTTP, outside any DB session).
    # For sources with a wide historical range we chunk by year. We send no
    # `sortby`, and STAC leaves the ordering of an unsorted search
    # unspecified — so chunking is what bounds the candidate pool *per year*
    # regardless of how the server happens to order results, rather than
    # trusting a whole-range search to hand back the years we want.
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
        attempted = [imagery_service.encode_group_key(scope, y) for y in years]
        failed_years = 0
        last_exc: Exception | None = None
        for year in years:
            key = imagery_service.encode_group_key(scope, year)
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
                # The completion sweep saw two 403s here. They cost no rows,
                # because reconciliation leaves absent groups alone — but
                # nothing recorded that the year was never actually asked.
                ledger.record(key, "failed", _stac_failure_reason(exc), str(exc))
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
            raw_by_key[key] = len(chunk)
            if not chunk and source_cfg.get("query"):
                outcome, reason = await _classify_empty_chunk(
                    collection=collection,
                    bbox=search_bbox,
                    year=year,
                    per_year=per_year,
                )
                ledger.record(key, outcome, reason)
        if len(years) > 0 and failed_years == len(years) and last_exc is not None:
            # Flush before raising, exactly as the un-chunked branch does.
            # Without this the worst case records nothing: every year's
            # `failed` row is staged in `ledger` and dies with the exception,
            # so a source that lost *all* of its years leaves an empty ledger
            # and is invisible to every ledger-driven heal — while a source
            # that lost some of them is fully visible. Crawford County
            # 6563dedf is the live instance: 16 Landsat years and 17 NAIP
            # years recorded `failed/read_timeout`, and Sentinel-2, whose
            # every year failed, recorded nothing at all.
            _flush_ledger(ledger, timeline_request_id, source_name)
            raise last_exc
    else:
        datetime_range = (
            source_cfg.get("datetime_range")
            or f"{source_cfg['start_date']}/{date.today().year}-12-31"
        )
        max_items = int(source_cfg["max_items"])
        # The query's own date range is the attempted set: NAIP runs no
        # per-year loop, so nothing else in the response says which years it
        # asked about (INVESTIGATION UNVERIFIED item 2).
        attempted = [
            imagery_service.encode_group_key(scope, y) for y in _range_years(datetime_range)
        ]
        try:
            raw_items = await _search_stac_with_retry(
                collection=collection,
                bbox=search_bbox,
                datetime_range=datetime_range,
                max_items=max_items,
                query=source_cfg.get("query"),
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            # One search covers every year, so one failure loses every year.
            reason = _stac_failure_reason(exc)
            for key in attempted:
                ledger.record(key, "failed", reason, str(exc))
            _flush_ledger(ledger, timeline_request_id, source_name)
            raise
        for item in raw_items:
            item_key = stac_service.item_group_key(item, scope)
            if item_key is not None:
                raw_by_key[item_key] = raw_by_key.get(item_key, 0) + 1
        # Same instrument the TNM and county clients carry: a response
        # holding exactly its cap is indistinguishable from a complete
        # answer, and with no `sortby` the ordering that decides *which*
        # items survive the cap is unspecified — so a saturated pool could
        # silently drop whole years. It lives on this branch, not inside
        # search_stac, because only the un-chunked sources can be truncated
        # in a way that costs coverage: Landsat and Sentinel-2 saturate
        # their 20-item per-year pools as normal operation on dense years,
        # and warning there would drown this signal. Pagination is
        # deliberately not built — see T4 in the second audit's STATUS.md.
        if len(raw_items) >= max_items:
            truncated = True
            logger.warning(
                "STAC search hit its item cap — results are truncated",
                extra={
                    "source": source_name,
                    "collection": collection,
                    "cap": max_items,
                    "datetime_range": datetime_range,
                },
            )

    # Spatial filter. NAIP uses the looser "intersects viewport" filter so
    # adjacent tiles can contribute to a mosaic; Landsat/S2 use strict
    # point-containment since their scenes already cover a huge area.
    if source_cfg.get("use_viewport_filter"):
        raw_items = stac_service.filter_items_intersecting_bbox(raw_items, viewport_bbox)
    elif lat is not None and lng is not None:
        raw_items = stac_service.filter_items_containing_point(raw_items, lat, lng)

    # Every group this run asked about, classified against what came back.
    # A group already decided above (chunk failure, cloud probe) keeps that
    # decision; the rest divide into "the search covered this period and
    # returned nothing", "it returned items but none of them covers the
    # address", and — when the pool was capped — "cannot tell".
    surviving = {
        item_key
        for item in raw_items
        if (item_key := stac_service.item_group_key(item, scope)) is not None
    }
    for key in attempted:
        if key in ledger:
            continue
        if raw_by_key.get(key, 0) == 0:
            if truncated:
                ledger.record(
                    key,
                    "indeterminate",
                    f"{source_name} search hit its item cap at "
                    "timeline._search_and_persist_source; an absent year may be truncation",
                )
            else:
                ledger.record(key, "absent", "no_scenes")
        elif key not in surviving:
            ledger.record(key, "absent", "no_covering_item")

    # Group key -> the item ids this run positively identified as not
    # servable. The only thing allowed to delete a served snapshot for a
    # group this run did not select — see reconcile_source_snapshots.
    suppressed_items: dict[str, set[str]] = {}

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
                tile_ids = [str(i.get("id")) for i in group]
                suppressed_key = stac_service.item_group_key(group[0], scope)
                if suppressed_key is not None:
                    ledger.record(
                        suppressed_key,
                        "suppressed",
                        "naip_no_point_coverage",
                        f"selected tiles do not contain the parcel: {', '.join(tile_ids)}",
                    )
                    # Carried to reconciliation as ids rather than re-parsed
                    # out of the detail string: the delete is authorised by
                    # *this* item being unservable, and a prose field is not
                    # a place to keep a machine's evidence.
                    suppressed_items.setdefault(suppressed_key, set()).update(tile_ids)
                logger.warning(
                    "Suppressing imagery year with no covering tile",
                    extra={
                        "parcel_id": str(parcel_id),
                        "source": source_name,
                        "year": stac_service.extract_capture_date(group[0]).year,
                        "reason": "no selected tile's footprint contains the parcel",
                        "tile_ids": tile_ids,
                    },
                )
    else:
        selected_groups = source_cfg["selector"](raw_items)

    # Validate asset accessibility — older Landsat scenes (1984–1990s) can
    # have broken assets that cause tile-serving 502s, and an S2 year can
    # land on an unservable granule the same way.  Drop bad items and swap in
    # the next-best candidate from the same year.
    walk_notes: dict[str, year_ledger.GroupNote] = {}
    if collection == "landsat-c2-l2":
        selected_groups = await stac_service.validate_landsat_selection(
            selected_groups,
            raw_items,
            walk_notes,
        )
    elif collection == "sentinel-2-l2a":
        selected_groups = await stac_service.validate_sentinel_selection(
            selected_groups,
            raw_items,
            walk_notes,
        )

    # A period the walk dropped is a failure with a reason, not an absence:
    # the scenes were there and could not be served. A period the walk
    # rescued is an ``ok`` whose detail names the swap — the persist loop
    # below writes it, so it commits with the snapshot.
    fallback_details: dict[str, str | None] = {}
    for key, note in walk_notes.items():
        if note.outcome == "ok":
            fallback_details[key] = note.detail
        else:
            ledger.record(key, note.outcome, note.reason, note.detail)

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
    selected_refs: list[imagery_service.SelectedScene] = []
    persisted: set[str] = set()
    with SessionLocal() as db:
        task_id = year_ledger.get_task_id(db, timeline_request_id, source_name)
        if task_id is not None:
            ledger.flush(db, task_id, commit=False)
        for group in selected_groups:
            if not group:
                continue
            primary = group[0]
            group_key = stac_service.item_group_key(primary, scope)
            primary_cog_url = stac_service.extract_cog_url(primary, collection)
            if not primary_cog_url:
                # Was a silent `continue`. A selected group with no COG asset
                # is a candidate deliberately not served, which is a
                # different answer from "the year was empty".
                if group_key is not None:
                    suppressed_items.setdefault(group_key, set()).add(str(primary.get("id")))
                if task_id is not None and group_key is not None:
                    year_ledger.record_year_outcome(
                        db,
                        task_id,
                        source_name,
                        group_key,
                        "suppressed",
                        "no_cog_url",
                        f"selected item {primary.get('id')} carries no COG asset",
                        commit=False,
                    )
                continue

            # Every tile of the mosaic becomes a SelectedScene, not just a
            # URL: the selector has the real STAC items in hand, so the
            # normalized shape can catalogue each tile as a first-class scene
            # with its own footprint. That is what closes the synthesized-
            # candidate class STEP1-REPORT F1 describes — no later pass has to
            # guess an item id out of a tile URL for a row written here.
            tiles: list[imagery_service.SelectedScene] = []
            for extra_item in group[1:]:
                extra_url = stac_service.extract_cog_url(extra_item, collection)
                if extra_url:
                    tiles.append(
                        imagery_service.SelectedScene.from_stac_item(
                            extra_item,
                            source=source_name,
                            collection=collection,
                            cog_url=extra_url,
                            default_resolution_m=source_cfg["resolution_m"],
                        )
                    )

            # One object, both write shapes. resolution_m is the item's own
            # gsd wherever the item carries one (NORM-9), normalized by
            # imagery_service.normalize_resolution_m (NORM-11), and the
            # snapshot row below is written from the same field so the two
            # tables cannot disagree about a row they were written from
            # together.
            selection = imagery_service.SelectedScene.from_stac_item(
                primary,
                source=source_name,
                collection=collection,
                cog_url=primary_cog_url,
                default_resolution_m=source_cfg["resolution_m"],
                mosaic=tiles,
            )
            additional_urls = [tile.cog_url for tile in tiles]

            # Written before the upsert, uncommitted: the upsert commits for
            # itself, so the ledger row and the snapshot it describes land in
            # one transaction. An ``ok`` committed first would be a claim
            # about a row that might never arrive.
            if task_id is not None and group_key is not None:
                year_ledger.record_year_outcome(
                    db,
                    task_id,
                    source_name,
                    group_key,
                    "ok",
                    detail=fallback_details.get(group_key),
                    commit=False,
                )
            imagery_service.upsert_imagery_snapshot(
                db,
                parcel_id=parcel_id,
                source=source_name,
                capture_date=selection.capture_date,
                stac_item_id=selection.item_id,
                stac_collection=selection.collection,
                cog_url=selection.cog_url,
                additional_cog_urls=additional_urls or None,
                thumbnail_url=selection.thumbnail_url,
                resolution_m=selection.resolution_m,
                cloud_cover_pct=selection.cloud_cover_pct,
                bbox_wkt=selection.bbox_wkt,
            )
            items_saved += 1
            selected_refs.append(selection)
            if group_key is not None:
                persisted.add(group_key)

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
        #
        # It is also where the normalized shape is written: passing
        # SelectedScene objects rather than (id, date) tuples makes this call
        # write scenes and parcel_scenes in the same transaction as the
        # deletes (ADR step 2). An interruption before it leaves the new
        # snapshot rows with no parcel_scenes row, which the next run's
        # reconcile writes — the same recoverable direction the ordering above
        # already chose.
        imagery_service.reconcile_source_snapshots(
            db,
            parcel_id,
            source_name,
            selected_refs,
            scope=source_cfg["selection_scope"],
            suppressed=suppressed_items,
        )

        # Anything attempted that reached here with no verdict is a
        # confession, not a silence: some path between search and persist
        # dropped the group without saying so. Every one of these is a
        # follow-up, and the ledger is where they become countable.
        if task_id is not None:
            for key in attempted:
                if key in ledger or key in persisted:
                    continue
                year_ledger.record_year_outcome(
                    db,
                    task_id,
                    source_name,
                    key,
                    "indeterminate",
                    f"{source_name}: attempted group reached the end of "
                    "timeline._search_and_persist_source with no outcome",
                    commit=False,
                )
        db.commit()

        # Use actual DB count — covers items from prior runs too
        total_items = imagery_service.count_served_scenes(db, parcel_id, source_name)

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

    # Topo has no per-decade fetch loop and no configured decade range: one
    # untimed TNM query returns whatever exists, and which decades were
    # "attempted" is only knowable from the response. So the whole-search
    # outcome is recorded under the whole-source key and the per-decade rows
    # cover only the decades the response actually held. That asymmetry is
    # the source's, not the ledger's — see INVESTIGATION section 3e.
    ledger = year_ledger.YearOutcomeLog(source_name)
    whole = imagery_service.WHOLE_SOURCE_GROUP_KEY

    try:
        search = await topo_service.search_usgs_topo_products(search_bbox)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        ledger.record(whole, "failed", _stac_failure_reason(exc), str(exc))
        _flush_ledger(ledger, timeline_request_id, source_name)
        raise
    except ValueError as exc:
        # A non-JSON body from TNM. Distinct from a transport failure, and
        # the only shape left that reaches here.
        ledger.record(whole, "failed", "other", str(exc))
        _flush_ledger(ledger, timeline_request_id, source_name)
        raise

    raw_items = search.items
    selected = topo_service.select_topo_items(raw_items)

    if search.truncated:
        ledger.record(
            whole,
            "indeterminate",
            "TNM response hit its row cap at usgs_topo.search_usgs_topo_products; "
            "a decade absent from the response may be truncation",
        )
    elif not raw_items:
        ledger.record(whole, "absent", "no_scenes")

    logger.info(
        "USGS topo search complete",
        extra={"raw_count": len(raw_items), "selected_count": len(selected)},
    )

    items_saved = 0
    selected_refs: list[imagery_service.SelectedScene] = []
    with SessionLocal() as db:
        task_id = year_ledger.get_task_id(db, timeline_request_id, source_name)
        if task_id is not None:
            ledger.flush(db, task_id, commit=False)
        for item in selected:
            year = topo_service.extract_publication_date(item)
            decade_key = (
                imagery_service.encode_group_key("decade", year) if year is not None else None
            )
            cog_url = topo_service.extract_geotiff_url(item)
            if not cog_url:
                # Latent: search_usgs_topo_products already filters to
                # GeoTIFF-carrying products, so a row here means an upstream
                # shape defeated that filter — which is the finding.
                if task_id is not None and decade_key is not None:
                    year_ledger.record_year_outcome(
                        db,
                        task_id,
                        source_name,
                        decade_key,
                        "suppressed",
                        "topo_no_geotiff_url",
                        f"product {item.get('sourceId')} carries no GeoTIFF url",
                        commit=False,
                    )
                continue

            publication_date = topo_service.extract_publication_date(item)
            # A product whose publicationDate will not parse has no year to
            # stand on. It used to be minted as 1900, which is indistinguishable
            # on the timeline from a genuine 1900 sheet. Skip it, as the
            # id-less case below does — one dropped sheet is a gap, not a
            # failure, so the task still completes.
            if publication_date is None:
                # Latent too: select_topo_items already drops items whose
                # year will not parse, so this guard is unreachable via that
                # path. There is no decade to key a ledger row on either —
                # that is the whole reason the sheet is dropped — so it is
                # recorded against the whole-source key.
                if task_id is not None:
                    year_ledger.record_year_outcome(
                        db,
                        task_id,
                        source_name,
                        whole,
                        "suppressed",
                        "topo_unparseable_date",
                        f"product {item.get('sourceId')} has publicationDate "
                        f"{item.get('publicationDate')!r}",
                        commit=False,
                    )
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
                # This one is live — the id-less product is the door topo
                # actually loses sheets through.
                if task_id is not None and decade_key is not None:
                    year_ledger.record_year_outcome(
                        db,
                        task_id,
                        source_name,
                        decade_key,
                        "suppressed",
                        "topo_no_source_id",
                        f"product at {cog_url} carries no sourceId",
                        commit=False,
                    )
                logger.warning(
                    "Skipping topo product with no sourceId",
                    extra={"parcel_id": str(parcel_id), "cog_url": cog_url},
                )
                continue

            if task_id is not None and decade_key is not None:
                year_ledger.record_year_outcome(
                    db, task_id, source_name, decade_key, "ok", commit=False
                )
            # Topo products are TNM records, not STAC items: no geometry, no
            # gsd, no platform. The dual-write still runs — parcel_scenes has
            # to hold every group imagery_snapshots holds, or the two tables
            # disagree about which periods a parcel serves — with the fields
            # the source does not have left NULL, exactly as the step-1
            # backfill wrote them.
            selection = imagery_service.SelectedScene(
                source=source_name,
                collection="usgs-historical-topo",
                item_id=source_id,
                capture_date=publication_date,
                cog_url=cog_url,
                bbox_wkt=topo_service.extract_bbox_wkt(item),
            )
            imagery_service.upsert_imagery_snapshot(
                db,
                parcel_id=parcel_id,
                source=source_name,
                capture_date=selection.capture_date,
                stac_item_id=selection.item_id,
                stac_collection=selection.collection,
                cog_url=selection.cog_url,
                thumbnail_url=selection.thumbnail_url,
                resolution_m=selection.resolution_m,
                cloud_cover_pct=selection.cloud_cover_pct,
                bbox_wkt=selection.bbox_wkt,
            )
            items_saved += 1
            selected_refs.append(selection)

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
        db.commit()

        total_items = imagery_service.count_served_scenes(db, parcel_id, source_name)

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
    no tract falls back to the stored tract — the design gap where the
    geocoder's oldest vintage predates the geography a year like decennial
    2000 was published on (Racebrook, `4ce1822`). A geocoder outage does
    *not* fall back (Z6): `GeocoderError` propagates out of `tract_for`, and
    the caller records `failed` for that year and skips the fetch rather than
    writing demographics under a tract the vintage never resolved — a missing
    row the ledger can retry beats a wrong row it can't see.
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

        resolved = await geocoder_service.lookup_tract_at_vintage(
            self._lat, self._lon, vintage, get_settings()
        )

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

    # One 'census' task row covers both datasets, so the ledger's `source`
    # carries which one — 'census_decennial' / 'census_acs5'. That is safe
    # only while the two year lists are disjoint: the unique key is
    # (task_id, group_key), so a year appearing in both lists would collide
    # and the second write would overwrite the first. DECENNIAL_YEARS and
    # ACS5_YEARS have no member in common today; adding one means the census
    # group_key has to carry the dataset instead.
    ledger = year_ledger.YearOutcomeLog("census")
    task_id: uuid.UUID | None = None
    with SessionLocal() as db:
        task_id = year_ledger.get_task_id(db, timeline_request_id, "census")

    try:
        # Fetch decennial data
        for year in DECENNIAL_YEARS:
            key = imagery_service.encode_group_key("year", year)
            try:
                year_tract = await tracts.tract_for("decennial", year)
            except GeocoderError as exc:
                failed_requests += 1
                ledger.record(
                    key,
                    "failed",
                    _geocoder_failure_reason(exc),
                    f"vintage tract lookup ({geography_vintage('decennial', year)}) via "
                    f"geocoder.lookup_tract_at_vintage failed: {exc}",
                    source="census_decennial",
                )
                logger.warning(
                    "Vintage tract lookup failed, skipping year",
                    extra={"year": year, "dataset": "decennial"},
                    exc_info=exc,
                )
                await asyncio.sleep(0.5)
                continue
            state_fips, county_fips, tract_code = parse_tract_fips(year_tract)
            try:
                data = await fetcher.fetch_decennial(year, state_fips, county_fips, tract_code)
                if data:
                    with SessionLocal() as db:
                        if task_id is not None:
                            year_ledger.record_year_outcome(
                                db,
                                task_id,
                                "census_decennial",
                                key,
                                "ok",
                                detail=f"tract {year_tract}",
                                commit=False,
                            )
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
                else:
                    # The silent skip. `{}` arrives from a 204, a year with
                    # no decennial config, and every requested variable being
                    # dropped as unrecognised for the vintage — all collapsed
                    # before the loop sees them. No counter, no log at this
                    # level: the ledger is the only record it happened. A 404
                    # no longer arrives here; it raises and lands below as
                    # `failed`/`http_404`.
                    ledger.record(
                        key,
                        "absent",
                        "api_no_data",
                        f"empty response for tract {year_tract}",
                        source="census_decennial",
                    )
            except CensusApiError as exc:
                failed_requests += 1
                ledger.record(
                    key,
                    "failed",
                    _census_failure_reason(exc),
                    str(exc),
                    source="census_decennial",
                )
                logger.warning("Census decennial failed", extra={"year": year}, exc_info=exc)
                if isinstance(exc, CensusMissingKeyError):
                    raise
            # Be a good citizen — small delay between requests
            await asyncio.sleep(0.5)

        # Fetch ACS 5-year data
        for year in ACS5_YEARS:
            key = imagery_service.encode_group_key("year", year)
            try:
                year_tract = await tracts.tract_for("acs5", year)
            except GeocoderError as exc:
                failed_requests += 1
                ledger.record(
                    key,
                    "failed",
                    _geocoder_failure_reason(exc),
                    f"vintage tract lookup ({geography_vintage('acs5', year)}) via "
                    f"geocoder.lookup_tract_at_vintage failed: {exc}",
                    source="census_acs5",
                )
                logger.warning(
                    "Vintage tract lookup failed, skipping year",
                    extra={"year": year, "dataset": "acs5"},
                    exc_info=exc,
                )
                await asyncio.sleep(0.5)
                continue
            state_fips, county_fips, tract_code = parse_tract_fips(year_tract)
            try:
                data = await fetcher.fetch_acs5(year, state_fips, county_fips, tract_code)
                if data:
                    with SessionLocal() as db:
                        if task_id is not None:
                            year_ledger.record_year_outcome(
                                db,
                                task_id,
                                "census_acs5",
                                key,
                                "ok",
                                detail=f"tract {year_tract}",
                                commit=False,
                            )
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
                else:
                    ledger.record(
                        key,
                        "absent",
                        "api_no_data",
                        f"empty response for tract {year_tract}",
                        source="census_acs5",
                    )
            except CensusApiError as exc:
                failed_requests += 1
                ledger.record(
                    key,
                    "failed",
                    _census_failure_reason(exc),
                    str(exc),
                    source="census_acs5",
                )
                logger.warning("Census ACS5 failed", extra={"year": year}, exc_info=exc)
                if isinstance(exc, CensusMissingKeyError):
                    raise
            await asyncio.sleep(0.5)

    finally:
        await fetcher.close()
        if task_id is not None and len(ledger):
            with SessionLocal() as db:
                ledger.flush(db, task_id)

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
            counts=imagery_service.TaskCounts(
                queries_run=0,
                queries_failed=0,
                coverage="no_adapter",
            ),
            clear_items_found=True,
        )
        return 0

    # The municipality coverage gate. An adapter can be the wrong authority
    # for an address inside the county it serves: Adams County's layer covers
    # unincorporated Adams, and 12804 Emerson is in Thornton, which issues its
    # own permits. Reporting that as complete:0 is the same conflation
    # "no adapter for county" already avoids, one level down — so it resolves
    # to the same skipped state, distinguished by ``coverage``.
    city = city_from_address(normalized_address)
    if not adapter.covers(city):
        logger.info(
            "Address outside adapter coverage",
            extra={"county": county, "city": city, "parcel_id": str(parcel_id)},
        )
        _set_task_status(
            timeline_request_id,
            "property",
            "skipped",
            error_message=(
                f"{county} County's records don't cover {city.title()} — the city keeps its own"
                if city
                else f"Address is outside {county} County's records"
            ),
            counts=imagery_service.TaskCounts(
                queries_run=0,
                queries_failed=0,
                coverage="not_covered",
            ),
            clear_items_found=True,
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
            counts=imagery_service.TaskCounts(
                queries_run=queries_attempted,
                queries_failed=queries_failed,
                rows_returned=0,
                rows_matched=0,
                coverage="covered",
            ),
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

    # Z3: 'complete' now means every query answered, zero rows included. A
    # county with one query (Adams) already failed correctly under H4's rule;
    # a county with several (Denver's 2 permit layers, DC's 7) used to report
    # the survivors as if they were the whole answer.
    status = "partial" if queries_failed else "complete"
    _set_task_status(
        timeline_request_id,
        "property",
        status,
        items_found=total_items,
        error_message=(
            f"{queries_failed} of {queries_attempted} {county} County property "
            "queries failed; this history may be incomplete"
            if status == "partial"
            else None
        ),
        counts=imagery_service.TaskCounts(
            queries_run=queries_attempted,
            queries_failed=queries_failed,
            rows_returned=len(all_events),
            rows_matched=len(matched_events),
            coverage="covered",
        ),
    )

    logger.info(
        "Property history fetch complete",
        extra={"items_saved": items_saved, "county": county, "status": status},
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

        # What this parcel is eligible for, intersected with what the request
        # declared. The declared scope is intent; eligibility is fact, and a
        # request declaring 'census' on a parcel with no tract still runs no
        # census task. Both the task rows and the coroutine fan-out below read
        # `scoped` — scoping only one of them would create fewer rows while
        # still running every fetch, and _set_task_status would log "No task
        # row found for source" instead of failing (INVESTIGATION §1.3).
        eligible = [s["source"] for s in _SOURCES]
        eligible.append("usgs_topo")
        if tract_fips:
            eligible.append("census")
        if county:
            eligible.append("property")
        declared = set(request.sources)
        scoped = {source for source in eligible if source in declared}
        logger.info(
            "Timeline scope resolved",
            extra={
                "request_id": timeline_request_id,
                "origin": request.origin,
                "declared": sorted(declared),
                "running": sorted(scoped),
            },
        )
        imagery_service.create_request_tasks(
            db,
            timeline_request_id=req_uuid,
            sources=sorted(scoped),
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
        if source_cfg["source"] not in scoped:
            continue
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
    if "usgs_topo" in scoped:
        coros.append(
            (
                "usgs_topo",
                _fetch_usgs_topo(search_bbox, parcel_id, req_uuid),
            )
        )
    if "census" in scoped and tract_fips:
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
    if "property" in scoped and county:
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

    # Fold the per-source task rows into the request's status: 'failed' when
    # every source failed, 'partial' when some did and some did not,
    # 'complete' otherwise. 'partial' is the state this used to call
    # 'complete', which is how a parcel could serve zero NAIP and zero
    # Sentinel-2 under a request that claimed success.
    status = "complete"
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
            status, failed_sources = imagery_service.aggregate_request_status(
                (t.source, t.status) for t in task_rows
            )
            # No error_message on 'partial'. Both frontend renderers of
            # request.error_message are gated on status === 'failed'
            # (ParcelInfo.tsx:239-247, Timeline.tsx:482-491), and a
            # request-level error string on a request that is serving a
            # working timeline is one refactor away from becoming a red
            # banner over it. Which sources failed is on the task rows, which
            # is where ParcelInfo already reads it from.
            if status == "partial":
                logger.warning(
                    "Timeline request partial — some sources failed",
                    extra={
                        "request_id": timeline_request_id,
                        "parcel_id": str(parcel_id),
                        "failed_sources": failed_sources,
                    },
                )
            imagery_service.update_timeline_request_status(
                db,
                request,
                status,
                error_message=(
                    f"All sources failed: {', '.join(failed_sources)}"
                    if status == "failed"
                    else None
                ),
            )

    logger.info(
        "Timeline request finished",
        extra={
            "request_id": timeline_request_id,
            "status": status,
            "total_items": total_items,
        },
    )
    return {
        "status": status,
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
