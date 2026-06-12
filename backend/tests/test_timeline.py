"""Tests for the Celery timeline task and its async helpers.

Covers: STAC retry logic, SoftTimeLimitExceeded handling, per-source error
isolation, and status transitions (queued → processing → complete/failed).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from celery.exceptions import SoftTimeLimitExceeded  # noqa: I001

# ── _search_stac_with_retry ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt() -> None:
    """Transient 502 on first call, success on second."""
    from app.tasks.timeline import _search_stac_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 502
    error = httpx.HTTPStatusError("502", request=MagicMock(), response=mock_resp)

    with patch("app.tasks.timeline.stac_service.search_stac", new_callable=AsyncMock) as mock:
        mock.side_effect = [error, [{"id": "ok"}]]
        with patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_stac_with_retry(
                collection="naip",
                bbox=(-105, 39, -104, 40),
                datetime_range="2020-01-01/2020-12-31",
                max_items=10,
                attempts=3,
            )
    assert result == [{"id": "ok"}]
    assert mock.call_count == 2


@pytest.mark.asyncio
async def test_retry_propagates_non_retryable_status() -> None:
    """A 400 error should propagate immediately, not retry."""
    from app.tasks.timeline import _search_stac_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    error = httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)

    with patch("app.tasks.timeline.stac_service.search_stac", new_callable=AsyncMock) as mock:
        mock.side_effect = error
        with pytest.raises(httpx.HTTPStatusError):
            await _search_stac_with_retry(
                collection="naip",
                bbox=(-105, 39, -104, 40),
                datetime_range="2020-01-01/2020-12-31",
                max_items=10,
                attempts=3,
            )
    assert mock.call_count == 1


@pytest.mark.asyncio
async def test_retry_exhausted_raises_last_error() -> None:
    """After all attempts fail with retryable errors, the last exception is raised."""
    from app.tasks.timeline import _search_stac_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    error = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)

    with patch("app.tasks.timeline.stac_service.search_stac", new_callable=AsyncMock) as mock:
        mock.side_effect = [error, error, error]
        with (
            patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await _search_stac_with_retry(
                collection="naip",
                bbox=(-105, 39, -104, 40),
                datetime_range="2020-01-01/2020-12-31",
                max_items=10,
                attempts=3,
            )
    assert mock.call_count == 3


@pytest.mark.asyncio
async def test_retry_on_request_error() -> None:
    """Network errors (RequestError) should be retried."""
    from app.tasks.timeline import _search_stac_with_retry

    error = httpx.ConnectError("Connection refused")

    with patch("app.tasks.timeline.stac_service.search_stac", new_callable=AsyncMock) as mock:
        mock.side_effect = [error, [{"id": "recovered"}]]
        with patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock):
            result = await _search_stac_with_retry(
                collection="naip",
                bbox=(-105, 39, -104, 40),
                datetime_range="2020-01-01/2020-12-31",
                max_items=10,
                attempts=3,
            )
    assert result == [{"id": "recovered"}]


# ── SoftTimeLimitExceeded handler ────────────────────────────────────────────


def test_soft_time_limit_marks_request_failed() -> None:
    """SoftTimeLimitExceeded should mark the timeline request as failed and re-raise."""
    from app.tasks.timeline import fetch_imagery_timeline

    req_id = str(uuid.uuid4())

    mock_request = MagicMock()
    mock_request.id = uuid.UUID(req_id)
    mock_request.status = "processing"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_request

    with (
        patch("app.tasks.timeline.asyncio.run", side_effect=SoftTimeLimitExceeded()),
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status") as mock_update,
        pytest.raises(SoftTimeLimitExceeded),
    ):
        fetch_imagery_timeline(req_id)

    mock_update.assert_called_once()
    args = mock_update.call_args
    assert args[0][1] == mock_request
    assert args[0][2] == "failed"
    assert "timed out" in args[1]["error_message"].lower()


def test_unexpected_exception_marks_request_failed() -> None:
    """Unhandled exceptions should mark the request failed and re-raise."""
    from app.tasks.timeline import fetch_imagery_timeline

    req_id = str(uuid.uuid4())

    mock_request = MagicMock()
    mock_request.id = uuid.UUID(req_id)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_request

    with (
        patch("app.tasks.timeline.asyncio.run", side_effect=RuntimeError("boom")),
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status") as mock_update,
        pytest.raises(RuntimeError, match="boom"),
    ):
        fetch_imagery_timeline(req_id)

    mock_update.assert_called_once()
    args = mock_update.call_args
    assert args[0][2] == "failed"
    assert "boom" in args[1]["error_message"]


# ── _fetch_source per-source error isolation ──────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_source_stac_failure_marks_task_failed() -> None:
    """When STAC search raises, the per-source task row is marked failed."""
    from app.tasks.timeline import _fetch_source

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_request = MagicMock()
    mock_request.id = req_id

    mock_task_row = MagicMock()
    mock_task_row.source = "naip"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    source_cfg = {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2020-01-01/2020-12-31",
        "max_items": 10,
        "query": None,
        "selector": lambda items, vp=None: [[i] for i in items],
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": False,
    }

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline._search_stac_with_retry",
            new_callable=AsyncMock,
            side_effect=RuntimeError("STAC down"),
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_source(
            source_cfg,
            (-105, 39, -104, 40),
            (-105, 39, -104, 40),
            parcel_id,
            req_id,
        )

    assert count == 0
    # Should be called at least twice: once for "processing", once for "failed"
    calls = mock_update.call_args_list
    statuses = [c[0][2] for c in calls]
    assert "processing" in statuses
    assert "failed" in statuses


@pytest.mark.asyncio
async def test_fetch_source_chunk_by_year_skips_failed_years() -> None:
    """When chunk_by_year is True, a failed year is skipped but others proceed."""
    from app.tasks.timeline import _fetch_source

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_task_row.source = "landsat"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    mock_resp = MagicMock()
    mock_resp.status_code = 429

    source_cfg = {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "start_year": 2020,
        "end_year": 2021,
        "max_items_per_year": 5,
        "query": None,
        "selector": lambda items: [[i] for i in items],
        "resolution_m": 30.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    }

    stac_item = {
        "id": "LC09_2021",
        "properties": {"datetime": "2021-07-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {},
        "links": [{"rel": "self", "href": "https://example.com/item"}],
        "bbox": [-105, 39, -104, 40],
    }

    async def mock_search(**kwargs):
        dt = kwargs.get("datetime_range", "")
        if "2020" in dt:
            raise httpx.HTTPStatusError(
                "429",
                request=MagicMock(),
                response=MagicMock(status_code=429),
            )
        return [stac_item]

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline._search_stac_with_retry",
            new_callable=AsyncMock,
            side_effect=mock_search,
        ),
        patch(
            "app.tasks.timeline.stac_service.filter_items_containing_point",
            side_effect=lambda items, lat, lng: items,
        ),
        patch(
            "app.tasks.timeline.stac_service.validate_landsat_selection",
            new_callable=AsyncMock,
            side_effect=lambda groups, raw: groups,
        ),
        patch(
            "app.tasks.timeline.stac_service.extract_cog_url",
            return_value="https://example.com/cog.tif",
        ),
        patch("app.tasks.timeline.stac_service.extract_thumbnail_url", return_value=None),
        patch("app.tasks.timeline.stac_service.extract_capture_date"),
        patch("app.tasks.timeline.stac_service.extract_bbox_wkt", return_value=None),
        patch("app.tasks.timeline.imagery_service.upsert_imagery_snapshot", return_value=True),
        patch("app.tasks.timeline.imagery_service.update_request_task"),
    ):
        count = await _fetch_source(
            source_cfg,
            (-105, 39, -104, 40),
            (-105, 39, -104, 40),
            parcel_id,
            req_id,
            lat=39.5,
            lng=-104.5,
        )

    assert count == 1


# ── _fetch_census ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_census_invalid_fips_marks_skipped() -> None:
    """Invalid FIPS code should mark the census task as skipped."""
    from app.tasks.timeline import _fetch_census

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_census(parcel_id, req_id, "bad_fips")

    assert count == 0
    mock_update.assert_called_once()
    assert mock_update.call_args[0][2] == "skipped"


@pytest.mark.asyncio
async def test_fetch_census_success_persists_snapshots() -> None:
    """Successful census fetch should persist data and mark complete."""
    from app.tasks.timeline import _fetch_census

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch_decennial = AsyncMock(return_value={"total_population": 5000})
    mock_fetcher.fetch_acs5 = AsyncMock(return_value={"total_population": 5500})
    mock_fetcher.close = AsyncMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=mock_fetcher),
        patch("app.tasks.timeline.demographics_service.upsert_census_snapshot"),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
    ):
        count = await _fetch_census(parcel_id, req_id, "08031006202")

    assert count > 0
    update_calls = mock_update.call_args_list
    statuses = [c[0][2] for c in update_calls]
    assert "processing" in statuses
    assert "complete" in statuses


# ── _fetch_property ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_property_unsupported_county_marks_skipped() -> None:
    """Unsupported county should mark property task as skipped."""
    from app.tasks.timeline import _fetch_property

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=None),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            parcel_id,
            req_id,
            "Unsupported County",
            "123 MAIN ST",
        )

    assert count == 0
    mock_update.assert_called_once()
    assert mock_update.call_args[0][2] == "skipped"


@pytest.mark.asyncio
async def test_fetch_property_no_search_terms_marks_failed() -> None:
    """Address with no extractable terms should mark property task as failed."""
    from app.tasks.timeline import _fetch_property

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_adapter = MagicMock()

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=mock_adapter),
        patch("app.tasks.timeline.extract_search_terms", return_value=("", "")),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            parcel_id,
            req_id,
            "Denver",
            "",
        )

    assert count == 0
    update_calls = mock_update.call_args_list
    statuses = [c[0][2] for c in update_calls]
    assert "failed" in statuses


@pytest.mark.asyncio
async def test_fetch_source_persist_failure_marks_task_failed() -> None:
    """An exception after the search (e.g. during persistence) must not
    leave the task row stuck at 'processing' under a 'complete' request."""
    from app.tasks.timeline import _fetch_source

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    source_cfg = {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2020-01-01/2020-12-31",
        "max_items": 10,
        "query": None,
        "selector": lambda items, vp=None: [[i] for i in items],
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": False,
    }

    stac_item = {
        "id": "naip-2020",
        "properties": {"datetime": "2020-07-01T00:00:00Z"},
        "assets": {},
        "bbox": [-105, 39, -104, 40],
    }

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline._search_stac_with_retry",
            new_callable=AsyncMock,
            return_value=[stac_item],
        ),
        patch(
            "app.tasks.timeline.stac_service.extract_cog_url",
            return_value="https://example.com/cog.tif",
        ),
        patch("app.tasks.timeline.stac_service.extract_thumbnail_url", return_value=None),
        patch("app.tasks.timeline.stac_service.extract_bbox_wkt", return_value=None),
        patch(
            "app.tasks.timeline.imagery_service.upsert_imagery_snapshot",
            side_effect=RuntimeError("db exploded"),
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_source(
            source_cfg,
            (-105, 39, -104, 40),
            (-105, 39, -104, 40),
            parcel_id,
            req_id,
            lat=39.5,
            lng=-104.5,
        )

    assert count == 0
    statuses = [c[0][2] for c in mock_update.call_args_list]
    assert statuses[-1] == "failed"


@pytest.mark.asyncio
async def test_fetch_census_all_years_failed_marks_task_failed() -> None:
    """A full Census outage is a failure, not 'complete with 0 items' —
    complete-with-0 would permanently mask the gap."""
    from app.services.census import CensusApiError
    from app.tasks.timeline import _fetch_census

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch_decennial = AsyncMock(side_effect=CensusApiError("503"))
    mock_fetcher.fetch_acs5 = AsyncMock(side_effect=CensusApiError("503"))
    mock_fetcher.close = AsyncMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=mock_fetcher),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
    ):
        count = await _fetch_census(parcel_id, req_id, "08031006202")

    assert count == 0
    statuses = [c[0][2] for c in mock_update.call_args_list]
    assert statuses[-1] == "failed"
    assert "complete" not in statuses


@pytest.mark.asyncio
async def test_fetch_property_filters_other_addresses() -> None:
    """Records the broad LIKE pulled in for other buildings are rejected."""
    from app.services.county_adapters import PropertyEventData
    from app.tasks.timeline import _fetch_property

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    def make_event(record_id: str, situs: str) -> PropertyEventData:
        return PropertyEventData(
            event_type="sale",
            event_date=None,
            sale_price=500000,
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description="Property sale",
            source="dc_sales",
            source_record_id=record_id,
            raw_data={},
            situs_address=situs,
        )

    matching = make_event("ssl-1", "100 MARYLAND AVENUE NE")
    wrong_number = make_event("ssl-2", "1100 MARYLAND AVENUE NE")
    no_situs = make_event("ssl-3", "")

    mock_adapter = MagicMock()
    mock_adapter.fetch_sales = AsyncMock(return_value=[matching, wrong_number, no_situs])
    mock_adapter.fetch_permits = AsyncMock(return_value=[])

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=mock_adapter),
        patch("app.tasks.timeline.property_events_service.upsert_property_event") as mock_upsert,
        patch(
            "app.tasks.timeline.property_events_service.count_property_events",
            return_value=2,
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task"),
    ):
        await _fetch_property(
            parcel_id,
            req_id,
            "District of Columbia",
            "100 MARYLAND AVE NE, WASHINGTON, DC, 20002",
        )

    saved_ids = [c.kwargs["source_record_id"] for c in mock_upsert.call_args_list]
    assert "ssl-1" in saved_ids
    assert "ssl-2" not in saved_ids
    # Records without a situs address can't be verified — they're kept.
    assert "ssl-3" in saved_ids


# ── _run_timeline_inner orchestration ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_timeline_all_sources_failed_marks_request_failed() -> None:
    """When every per-source task ends failed, the parent request is marked
    failed. The fetchers handle their own errors internally — they mark
    their row failed and return 0, they don't raise — so the mocks model
    exactly that."""
    from app.tasks.timeline import _run_timeline_inner

    req_id = uuid.uuid4()
    parcel_id = uuid.uuid4()

    mock_parcel = MagicMock()
    mock_parcel.id = parcel_id
    mock_parcel.latitude = 39.7
    mock_parcel.longitude = -104.9
    mock_parcel.census_tract_id = "08031006202"
    mock_parcel.county = "Denver"
    mock_parcel.normalized_address = "123 MAIN ST"
    mock_parcel.address = "123 Main St"

    mock_request = MagicMock()
    mock_request.id = req_id
    mock_request.parcel_id = parcel_id
    mock_request.status = "queued"

    mock_task_row = MagicMock()
    mock_task_row.status = "failed"
    mock_task_row.source = "naip"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    call_count = [0]

    def mock_execute_side_effect(query):
        result = MagicMock()
        call_count[0] += 1
        if call_count[0] <= 2:
            result.scalars.return_value.first.return_value = mock_request
        elif call_count[0] == 3:
            result.scalars.return_value.first.return_value = mock_parcel
        else:
            result.scalars.return_value.first.return_value = mock_request
            result.scalars.return_value.all.return_value = [mock_task_row]
        return result

    mock_db.execute = MagicMock(side_effect=mock_execute_side_effect)

    mock_settings = MagicMock()
    mock_settings.census_api_key = None
    mock_settings.census_api_timeout = 10
    mock_settings.socrata_app_token = None

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.config.get_settings", return_value=mock_settings),
        patch("app.tasks.timeline.stac_service.point_to_bbox", return_value=(-105, 39, -104, 40)),
        patch("app.tasks.timeline._fetch_source", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_usgs_topo", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_census", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_property", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status") as mock_status,
        patch("app.tasks.timeline.imagery_service.create_request_tasks"),
    ):
        await _run_timeline_inner(str(req_id))

    status_calls = mock_status.call_args_list
    statuses = [c[0][2] for c in status_calls]
    assert "processing" in statuses
    assert "failed" in statuses


# ── _fetch_usgs_topo ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_usgs_topo_error_marks_failed() -> None:
    """USGS topo search failure should mark the task as failed."""
    from app.tasks.timeline import _fetch_usgs_topo

    req_id = uuid.uuid4()
    parcel_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline.topo_service.search_usgs_topo",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TNM down"),
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_usgs_topo((-105, 39, -104, 40), parcel_id, req_id)

    assert count == 0
    update_calls = mock_update.call_args_list
    statuses = [c[0][2] for c in update_calls]
    assert "processing" in statuses
    assert "failed" in statuses
