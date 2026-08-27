"""Tests for the Celery timeline task and its async helpers.

Covers: STAC retry logic, SoftTimeLimitExceeded handling, per-source error
isolation, and status transitions (queued → processing → complete/failed).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from celery.exceptions import SoftTimeLimitExceeded  # noqa: I001

from app.models.parcels import TimelineRequest
from app.services import usgs_topo as topo_service

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
        "selection_scope": "year",
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
            lat=39.5,
            lng=-104.5,
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
        "selection_scope": "year",
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
            side_effect=lambda groups, raw, notes=None: groups,
        ),
        patch(
            "app.tasks.timeline.stac_service.extract_cog_url",
            return_value="https://example.com/cog.tif",
        ),
        patch("app.tasks.timeline.stac_service.extract_thumbnail_url", return_value=None),
        # A real date, not a bare MagicMock: the group_key encoding formats
        # it, so a mock leaks into f-strings the ledger and the reconciler
        # both build.
        patch(
            "app.tasks.timeline.stac_service.extract_capture_date",
            return_value=date(2021, 7, 1),
        ),
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


# ── cap-saturation instrument ────────────────────────────────────────────────


async def _run_fetch_source(source_cfg: dict, mock_search) -> None:
    """Drive _fetch_source with a stubbed search and no persistence.

    The selectors return no groups, so nothing is written — these tests are
    about what the *search* logged, upstream of selection.
    """
    from app.tasks.timeline import _fetch_source

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

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
            side_effect=lambda groups, raw, notes=None: groups,
        ),
        patch("app.tasks.timeline.imagery_service.reconcile_source_snapshots"),
        patch("app.tasks.timeline.imagery_service.count_imagery_snapshots", return_value=0),
        patch("app.tasks.timeline.imagery_service.update_request_task"),
    ):
        await _fetch_source(
            source_cfg,
            (-105, 39, -104, 40),
            (-105, 39, -104, 40),
            uuid.uuid4(),
            uuid.uuid4(),
            lat=39.5,
            lng=-104.5,
        )


def _naip_cfg(max_items: int) -> dict:
    return {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2010-01-01/2026-12-31",
        "max_items": max_items,
        "query": None,
        "selector": lambda items: [],
        "selection_scope": "year",
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": False,
    }


def _item(item_id: str) -> dict:
    return {
        "id": item_id,
        "properties": {"datetime": "2021-07-01T00:00:00Z"},
        "assets": {},
        "bbox": [-105, 39, -104, 40],
    }


@pytest.mark.asyncio
async def test_naip_search_at_its_cap_warns(caplog: pytest.LogCaptureFixture) -> None:
    """A pool holding exactly its cap is indistinguishable from a complete one."""

    async def mock_search(**kwargs):
        return [_item(f"naip_{i}") for i in range(3)]

    with caplog.at_level(logging.WARNING, logger="app.tasks.timeline"):
        await _run_fetch_source(_naip_cfg(3), mock_search)

    assert "STAC search hit its item cap" in caplog.text
    record = next(r for r in caplog.records if "hit its item cap" in r.getMessage())
    assert record.cap == 3  # type: ignore[attr-defined]  # logged via extra=
    assert record.collection == "naip"  # type: ignore[attr-defined]  # logged via extra=
    assert record.datetime_range == "2010-01-01/2026-12-31"  # type: ignore[attr-defined]  # logged via extra=


@pytest.mark.asyncio
async def test_naip_search_below_its_cap_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def mock_search(**kwargs):
        return [_item(f"naip_{i}") for i in range(2)]

    with caplog.at_level(logging.WARNING, logger="app.tasks.timeline"):
        await _run_fetch_source(_naip_cfg(3), mock_search)

    assert "hit its item cap" not in caplog.text


@pytest.mark.asyncio
async def test_saturated_landsat_year_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Chunked sources saturate their per-year pools as normal operation.

    Warning on those would bury the NAIP signal this instrument exists for.
    """
    cfg = {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "start_year": 2020,
        "end_year": 2021,
        "max_items_per_year": 2,
        "query": None,
        "selector": lambda items: [],
        "selection_scope": "year",
        "resolution_m": 30.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    }

    async def mock_search(**kwargs):
        return [_item(f"LC09_{i}") for i in range(2)]

    with caplog.at_level(logging.WARNING, logger="app.tasks.timeline"):
        await _run_fetch_source(cfg, mock_search)

    assert "hit its item cap" not in caplog.text


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


@pytest.mark.asyncio
async def test_fetch_census_uses_ancestor_tract_for_older_vintages() -> None:
    """Years on 2010 geography must be fetched against the 2010-vintage tract.

    Denver 41.11 was created in the 2020 redistricting, so asking for it in
    2018 returns nothing. Its 2010 ancestor 41.07 is a different tract code
    that no arithmetic on the current FIPS would produce — resolving the
    parcel's point at that vintage is the only way to find it.
    """
    from app.tasks.timeline import _fetch_census

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch_decennial = AsyncMock(return_value={"total_population": 3810})
    mock_fetcher.fetch_acs5 = AsyncMock(return_value={"total_population": 6620})
    mock_fetcher.close = AsyncMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=mock_fetcher),
        patch("app.tasks.timeline.demographics_service.upsert_census_snapshot") as mock_upsert,
        patch("app.tasks.timeline.imagery_service.update_request_task"),
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "app.tasks.timeline.geocoder_service.lookup_tract_at_vintage",
            new_callable=AsyncMock,
            side_effect=lambda lat, lon, vintage, settings: (
                "08031004107" if vintage == "Census2010_Current" else "08031004111"
            ),
        ) as mock_lookup,
    ):
        await _fetch_census(
            parcel_id,
            req_id,
            "08031004111",
            latitude=39.785,
            longitude=-104.891,
        )

    # One geocoder call per distinct vintage in play, not one per year.
    assert mock_lookup.await_count == 4
    assert {c.args[2] for c in mock_lookup.await_args_list} == {
        "Census2010_Current",
        "Census2020_Current",
        "ACS2021_Current",
        "ACS2023_Current",
    }

    stored = {
        (c.kwargs["dataset"], c.kwargs["year"]): c.kwargs["tract_fips"]
        for c in mock_upsert.call_args_list
    }
    assert stored[("acs5", 2018)] == "08031004107"
    assert stored[("decennial", 2010)] == "08031004107"

    # Years on 2020 geography resolve to the same tract the parcel stores.
    assert stored[("acs5", 2023)] == "08031004111"
    assert stored[("decennial", 2020)] == "08031004111"

    # ACS 2009 is 2000 geography, which the geocoder does not serve, so it asks
    # the nearest vintage that exists. For Denver 41.11 that buys nothing —
    # 004107 is absent from 2009/acs/acs5, measured in
    # docs/audits/2026-08-racebrook/REPORT.md §4.4 — but it is never worse than
    # the 2020 tract, and it is what recovers a year whose tract never moved
    # and whose county-equivalent did.
    assert stored[("acs5", 2009)] == "08031004107"

    acs_tracts = {c.args[3] for c in mock_fetcher.fetch_acs5.await_args_list}
    assert acs_tracts == {"004107", "004111"}


@pytest.mark.asyncio
async def test_fetch_census_uses_county_tract_before_planning_regions() -> None:
    """A county-equivalent change costs years the same way a redistricting does.

    Racebrook Road, Orange CT (`2f1b332e`). Tract 1571 never moved; Connecticut
    replaced its counties with planning regions for data tabulated in 2022, so
    the same tract is 09009157100 through ACS 2021 and 09170157100 from ACS
    2022. The parcel stores the current — planning-region — FIPS, and asking
    the API for it in a pre-2022 vintage returns an empty response, which is
    what cost this parcel acs5 2009, acs5 2021 and decennial 2020.

    The vintage-keyed geocoder answers below are the live ones, measured in
    docs/audits/2026-08-racebrook/REPORT.md §2.3.
    """
    from app.tasks.timeline import _fetch_census

    parcel_id = uuid.uuid4()
    req_id = uuid.uuid4()

    county_era = {"Census2010_Current", "Census2020_Current", "ACS2021_Current"}

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    mock_fetcher = AsyncMock()
    mock_fetcher.fetch_decennial = AsyncMock(return_value={"total_population": 2604})
    mock_fetcher.fetch_acs5 = AsyncMock(return_value={"total_population": 2453})
    mock_fetcher.close = AsyncMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=mock_fetcher),
        patch("app.tasks.timeline.demographics_service.upsert_census_snapshot") as mock_upsert,
        patch("app.tasks.timeline.imagery_service.update_request_task"),
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "app.tasks.timeline.geocoder_service.lookup_tract_at_vintage",
            new_callable=AsyncMock,
            side_effect=lambda lat, lon, vintage, settings: (
                "09009157100" if vintage in county_era else "09170157100"
            ),
        ),
    ):
        await _fetch_census(
            parcel_id,
            req_id,
            "09170157100",
            latitude=41.2690529,
            longitude=-72.9999675,
        )

    asked = {("acs5", c.args[0]): c.args[2] for c in mock_fetcher.fetch_acs5.await_args_list} | {
        ("decennial", c.args[0]): c.args[2] for c in mock_fetcher.fetch_decennial.await_args_list
    }

    # Every vintage published before the change is asked under New Haven
    # County. 2012/2015/2018 and decennial 2010 already were; 2009, 2021 and
    # decennial 2020 are what this fix adds.
    for year in (2009, 2012, 2015, 2018, 2021):
        assert asked[("acs5", year)] == "009", f"acs5 {year}"
    for year in (2010, 2020):
        assert asked[("decennial", year)] == "009", f"decennial {year}"

    # ACS 2022+ is the only family published under the planning regions.
    assert asked[("acs5", 2023)] == "170"

    # Decennial 2000 keeps the stored tract: its geography predates every
    # vintage the geocoder serves, so this parcel is asked under the planning
    # region and stays absent even now that the tract width is right — the
    # one parcel in the fleet where that is true
    # (../2026-08-census-decennial/REPORT.md §1.5). Asserted so that a later
    # change to it is a deliberate one.
    assert asked[("decennial", 2000)] == "170"

    # 1990 is not asked at all: there is no 1990 decennial dataset on
    # api.census.gov, and attempting it wrote one impossible `absent` ledger
    # row per parcel per sweep.
    assert ("decennial", 1990) not in asked

    # The tract each row is labelled with follows the tract it was fetched from.
    stored = {
        (c.kwargs["dataset"], c.kwargs["year"]): c.kwargs["tract_fips"]
        for c in mock_upsert.call_args_list
    }
    assert stored[("acs5", 2021)] == "09009157100"
    assert stored[("decennial", 2020)] == "09009157100"
    assert stored[("acs5", 2023)] == "09170157100"


@pytest.mark.asyncio
async def test_fetch_census_skips_year_when_vintage_lookup_fails() -> None:
    """Z6: an exhausted geocoder retry must cost the year, not silently substitute
    the stored tract.

    Before the fix, `_VintageTracts.tract_for` caught every `GeocoderError` and
    fell back to the stored tract, so a transient failure wrote demographics
    under a tract the vintage never resolved and the ledger recorded `ok` — a
    wrong row nobody could see. Now the failure propagates: the year is
    recorded `failed` and no census row is written for it. Decennial 2000 has
    no geocoder vintage at all (`geography_vintage` returns `None`), so it
    never calls the geocoder and is unaffected — the one case that still uses
    the stored tract, per design (Racebrook, `4ce1822`).
    """
    from app.services import imagery as imagery_service
    from app.services import year_ledger
    from app.services.geocoder import GeocoderUnavailableError
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

    read_timeout = httpx.ReadTimeout("timed out")
    lookup_error = GeocoderUnavailableError("Vintage tract lookup error: ReadTimeout")
    lookup_error.__cause__ = read_timeout

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=mock_fetcher),
        patch("app.tasks.timeline.demographics_service.upsert_census_snapshot") as mock_upsert,
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "app.tasks.timeline.geocoder_service.lookup_tract_at_vintage",
            new_callable=AsyncMock,
            side_effect=lookup_error,
        ),
        patch.object(
            year_ledger.YearOutcomeLog,
            "record",
            autospec=True,
            side_effect=year_ledger.YearOutcomeLog.record,
        ) as mock_record,
    ):
        count = await _fetch_census(
            parcel_id,
            req_id,
            "08031004111",
            latitude=39.785,
            longitude=-104.891,
        )

    # Only decennial 2000 (no geocoder vintage) still resolves and is saved.
    assert count == 1
    assert mock_fetcher.fetch_decennial.await_count == 1
    assert mock_fetcher.fetch_decennial.await_args_list[0].args[0] == 2000
    assert mock_fetcher.fetch_acs5.await_count == 0
    assert {c.kwargs["tract_fips"] for c in mock_upsert.call_args_list} == {"08031004111"}
    assert "complete" in [c[0][2] for c in mock_update.call_args_list]

    failed_calls = [c for c in mock_record.call_args_list if c.args[2] == "failed"]
    assert len(failed_calls) == 8  # every year with a geocoder vintage
    decennial_2010 = next(
        c
        for c in failed_calls
        if c.args[1] == imagery_service.encode_group_key("year", 2010)
        and c.kwargs["source"] == "census_decennial"
    )
    assert decennial_2010.args[3] == "read_timeout"
    assert "Census2010_Current" in decennial_2010.args[4]
    assert "lookup_tract_at_vintage" in decennial_2010.args[4]


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
    counts = mock_update.call_args.kwargs["counts"]
    assert counts.coverage == "no_adapter"
    assert counts.queries_run == 0
    assert mock_update.call_args.kwargs["clear_items_found"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("county", "address"),
    [
        # 12804 Emerson is in Thornton, which issues its own permits; the
        # county layer's Emerson coverage stops below 84th Ave. Confirmed
        # twice — portal check and sweep — on 2026-08-27.
        ("Adams", "12804 EMERSON ST, THORNTON, CO, 80241"),
        # data.sanjoseca.gov is the City of San Jose's portal, not the
        # county's; Sunnyvale runs its own.
        ("Santa Clara", "500 W OLIVE AVE, SUNNYVALE, CA, 94086"),
    ],
)
async def test_fetch_property_outside_coverage_skips_without_asking(
    county: str, address: str
) -> None:
    """The municipality coverage gate: not_covered, and zero queries run.

    ``complete:0`` on an address the county was never the authority for reads
    as "no records at this address" forever — the same conflation the
    "no adapter for county" skip already avoids, one level down.

    Delete-the-fix: remove the ``if not adapter.covers(city)`` block from
    ``_fetch_property`` and the adapter is queried, the task reads
    ``complete`` with ``items_found`` 0, and every assertion below fails.
    """
    from app.services.county_adapters import get_adapter_for_county
    from app.tasks.timeline import _fetch_property

    adapter = get_adapter_for_county(county)
    assert adapter is not None

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=adapter),
        # Any outbound query at all is the failure this test is about.
        patch("app.services.county_adapters.query_feature_service") as mock_arcgis,
        patch("app.services.county_adapters.query_ckan_datastore") as mock_ckan,
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(uuid.uuid4(), uuid.uuid4(), county, address)

    assert count == 0
    mock_arcgis.assert_not_called()
    mock_ckan.assert_not_called()
    mock_update.assert_called_once()
    assert mock_update.call_args[0][2] == "skipped"
    counts = mock_update.call_args.kwargs["counts"]
    assert counts.coverage == "not_covered"
    assert (counts.queries_run, counts.queries_failed) == (0, 0)
    # NULL, not 0: nothing was counted because nothing was asked.
    assert mock_update.call_args.kwargs["clear_items_found"] is True
    assert mock_update.call_args.kwargs["items_found"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("county", "address"),
    [
        # Unincorporated Adams with a Brighton mailing address — the layer
        # holds York St records to 16610, so denying on the mailing city
        # would lose them (checked 2026-08-27).
        ("Adams", "16610 YORK ST, BRIGHTON, CO, 80602"),
        # Unincorporated Adams with a Denver mailing address, same shape.
        ("Adams", "8601 EMERSON CT, DENVER, CO, 80229"),
        ("Santa Clara", "200 E SANTA CLARA ST, SAN JOSE, CA, 95113"),
    ],
)
async def test_fetch_property_inside_coverage_still_queries(county: str, address: str) -> None:
    """The gate must not swallow the addresses the adapter does serve."""
    from app.services.county_adapters import get_adapter_for_county
    from app.tasks.timeline import _fetch_property

    adapter = get_adapter_for_county(county)
    assert adapter is not None

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=adapter),
        patch(
            "app.services.county_adapters.query_feature_service",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.county_adapters.query_ckan_datastore",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.tasks.timeline.property_events_service.count_property_events",
            return_value=0,
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        await _fetch_property(uuid.uuid4(), uuid.uuid4(), county, address)

    final = mock_update.call_args_list[-1]
    assert final[0][2] == "complete"
    assert final.kwargs["counts"].coverage == "covered"
    assert final.kwargs["counts"].queries_run > 0


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
        "selection_scope": "year",
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
    from app.services.county_adapters import PropertyEventData, SourceFetchResult
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
    mock_adapter.fetch_sales = AsyncMock(
        return_value=SourceFetchResult(
            events=[matching, wrong_number, no_situs],
            queries_attempted=1,
        )
    )
    mock_adapter.fetch_permits = AsyncMock(return_value=SourceFetchResult(queries_attempted=1))

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


@pytest.mark.asyncio
async def test_fetch_property_all_queries_failed_marks_task_failed() -> None:
    """A county portal outage is a failure, not 'complete with 0 items' —
    complete-with-0 reads as 'no records at this address' forever."""
    from app.services.county_adapters import SourceFetchResult
    from app.tasks.timeline import _fetch_property

    mock_adapter = MagicMock()
    mock_adapter.fetch_sales = AsyncMock(
        return_value=SourceFetchResult(queries_attempted=1, queries_failed=1)
    )
    mock_adapter.fetch_permits = AsyncMock(
        return_value=SourceFetchResult(queries_attempted=2, queries_failed=2)
    )

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=mock_adapter),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            uuid.uuid4(),
            uuid.uuid4(),
            "Denver",
            "1437 BANNOCK ST, DENVER, CO, 80202",
        )

    assert count == 0
    statuses = [c[0][2] for c in mock_update.call_args_list]
    assert statuses[-1] == "failed"
    assert "complete" not in statuses


@pytest.mark.asyncio
async def test_fetch_property_zero_rows_marks_task_complete() -> None:
    """Queries that ran fine and found nothing are 'no records here' —
    that must stay complete, not become an error."""
    from app.services.county_adapters import SourceFetchResult
    from app.tasks.timeline import _fetch_property

    mock_adapter = MagicMock()
    mock_adapter.fetch_sales = AsyncMock(return_value=SourceFetchResult(queries_attempted=1))
    mock_adapter.fetch_permits = AsyncMock(return_value=SourceFetchResult(queries_attempted=2))

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=mock_adapter),
        patch(
            "app.tasks.timeline.property_events_service.count_property_events",
            return_value=0,
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            uuid.uuid4(),
            uuid.uuid4(),
            "Denver",
            "1437 BANNOCK ST, DENVER, CO, 80202",
        )

    assert count == 0
    statuses = [c[0][2] for c in mock_update.call_args_list]
    assert statuses[-1] == "complete"
    assert "failed" not in statuses


@pytest.mark.asyncio
async def test_fetch_property_partial_failure_keeps_records_and_marks_partial() -> None:
    """One dead dataset among several shouldn't discard the records the
    others returned — and must not claim they are the whole answer.

    This test used to assert ``complete``, which is the Z3 defect written
    down as an expectation: a 429-exhausted permit layer on Denver left a
    task that read like a clean run over a thinner history. Delete-the-fix:
    revert ``status = "partial" if queries_failed else "complete"`` in
    ``_fetch_and_persist_property`` to an unconditional ``"complete"`` and
    the status assertion below fails.
    """
    from app.services.arcgis import ArcGISError
    from app.services.county_adapters import DenverAdapter
    from app.tasks.timeline import _fetch_property

    # The real Denver adapter, so this exercises the actual two-permit-layer
    # fan-out rather than a hand-made rollup: the commercial layer 429s past
    # its retry budget (Z1's terminal ArcGISError), the residential one
    # answers with one permit.
    adapter = DenverAdapter()

    async def fake_query(url: str, **kwargs: object) -> list[dict[str, object]]:
        if url == DenverAdapter.COMMERCIAL_PERMITS_URL:
            raise ArcGISError("ArcGIS rate-limited; backing off (HTTP 429)")
        return [{"ADDRESS": "1437 BANNOCK ST", "CLASS": "Building", "PERMIT_NUM": "permit-1"}]

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=adapter),
        patch("app.services.county_adapters.query_feature_service", side_effect=fake_query),
        patch("app.tasks.timeline.property_events_service.upsert_property_event"),
        patch(
            "app.tasks.timeline.property_events_service.count_property_events",
            return_value=1,
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            uuid.uuid4(),
            uuid.uuid4(),
            "Denver",
            "1437 BANNOCK ST, DENVER, CO, 80202",
        )

    assert count == 1
    statuses = [c[0][2] for c in mock_update.call_args_list]
    assert statuses[-1] == "partial"
    counts = mock_update.call_args_list[-1].kwargs["counts"]
    assert (counts.queries_run, counts.queries_failed) == (2, 1)
    # The surviving query's record is still saved and still counted.
    assert mock_update.call_args_list[-1].kwargs["items_found"] == 1


@pytest.mark.asyncio
async def test_fetch_property_records_the_address_matcher_split() -> None:
    """Z4: rows returned and rows kept are both on the task row.

    "The LIKE pulled records in and the matcher rejected every one" and "the
    portal returned nothing" were the same database state — ``complete`` with
    ``items_found`` 0 — and the split lived only in the ``"Property events
    filtered"`` log line. DC produced the live instance in the 2026-08-27
    sweep: ``raw_count 1 -> matched 0``.

    Delete-the-fix: drop the ``counts=`` argument from the terminal
    ``_set_task_status`` call in ``_fetch_and_persist_property`` and the
    ``rows_returned``/``rows_matched`` assertions fail (``counts`` is absent,
    so the row would carry NULL — "not recorded" — instead of 1 and 0).
    """
    from app.services.county_adapters import PropertyEventData, SourceFetchResult
    from app.tasks.timeline import _fetch_property

    rejected = PropertyEventData(
        event_type="sale",
        event_date=None,
        sale_price=500000,
        permit_type=None,
        permit_description=None,
        permit_valuation=None,
        description="Property sale",
        source="dc_sales",
        source_record_id="ssl-9",
        raw_data={},
        # A different building on the same street — the exact shape the broad
        # LIKE is built to pull in and the matcher is built to reject.
        situs_address="1100 MARYLAND AVENUE NE",
    )

    mock_adapter = MagicMock()
    mock_adapter.fetch_sales = AsyncMock(
        return_value=SourceFetchResult(events=[rejected], queries_attempted=1)
    )
    mock_adapter.fetch_permits = AsyncMock(return_value=SourceFetchResult(queries_attempted=7))

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = MagicMock()

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch("app.tasks.timeline.get_adapter_for_county", return_value=mock_adapter),
        patch("app.tasks.timeline.property_events_service.upsert_property_event") as mock_upsert,
        patch(
            "app.tasks.timeline.property_events_service.count_property_events",
            return_value=0,
        ),
        patch("app.tasks.timeline.imagery_service.update_request_task") as mock_update,
    ):
        count = await _fetch_property(
            uuid.uuid4(),
            uuid.uuid4(),
            "District of Columbia",
            "100 MARYLAND AVE NE, WASHINGTON, DC, 20002",
        )

    assert count == 0
    mock_upsert.assert_not_called()
    final = mock_update.call_args_list[-1]
    # Every query answered, so this is a true 'complete' — the counts are
    # what separate it from a portal that returned nothing.
    assert final[0][2] == "complete"
    counts = final.kwargs["counts"]
    assert (counts.rows_returned, counts.rows_matched) == (1, 0)
    assert (counts.queries_run, counts.queries_failed) == (8, 0)
    assert counts.coverage == "covered"


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
    mock_request.origin = "user"
    mock_request.sources = list(TimelineRequest.FULL_SCOPE)

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
            "app.tasks.timeline.topo_service.search_usgs_topo_products",
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


# ── Broker TLS configuration (audit finding M12) ──────────────────────────────


def test_broker_url_requires_certificate_verification() -> None:
    """A rediss:// broker URL gets certificate verification turned on, not off."""
    from app.tasks.celery_app import _redis_url_with_ssl

    url = _redis_url_with_ssl("rediss://default:pw@example.upstash.io:6379")

    assert "ssl_cert_reqs=CERT_REQUIRED" in url
    assert "CERT_NONE" not in url


def test_broker_url_ssl_flag_resolves_to_verify_mode() -> None:
    """kombu maps the flag we write to ssl.CERT_REQUIRED, not a bare string.

    redis-py itself only accepts 'none'/'optional'/'required', so this asserts
    the translation layer we actually depend on.
    """
    import ssl

    from kombu import Connection

    from app.tasks.celery_app import _redis_url_with_ssl

    url = _redis_url_with_ssl("rediss://default:pw@example.upstash.io:6379")

    assert Connection(url).ssl == {"ssl_cert_reqs": ssl.CERT_REQUIRED}


def test_plain_redis_url_is_untouched() -> None:
    """Non-TLS brokers (local docker-compose) get no ssl params appended."""
    from app.tasks.celery_app import _redis_url_with_ssl

    assert _redis_url_with_ssl("redis://redis:6379/0") == "redis://redis:6379/0"


def test_existing_ssl_cert_reqs_is_not_overridden() -> None:
    """An operator-supplied flag in the URL wins over the default."""
    from app.tasks.celery_app import _redis_url_with_ssl

    url = "rediss://example.upstash.io:6379?ssl_cert_reqs=required"
    assert _redis_url_with_ssl(url) == url


def test_task_results_are_not_stored() -> None:
    """Nothing reads task results, so they must not be written."""
    from app.tasks.celery_app import celery_app

    assert celery_app.conf.task_ignore_result is True


def test_time_limit_stays_under_broker_visibility_timeout() -> None:
    """acks_late redelivers past visibility_timeout (3600s) — duplicate execution."""
    from app.tasks.timeline import fetch_imagery_timeline

    assert fetch_imagery_timeline.time_limit < 3600
    assert fetch_imagery_timeline.soft_time_limit < fetch_imagery_timeline.time_limit


@pytest.mark.asyncio
async def test_fetch_usgs_topo_skips_products_without_source_id() -> None:
    """A product with no sourceId is skipped, not upserted as "".

    The upsert's conflict target is (parcel_id, stac_item_id), so every
    id-less product on a parcel would overwrite the previous one.
    """
    from app.tasks.timeline import _fetch_usgs_topo

    req_id = uuid.uuid4()
    parcel_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    items = [{"id": "with-id"}, {"id": "no-id"}]

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline.topo_service.search_usgs_topo_products",
            new_callable=AsyncMock,
            return_value=topo_service.TopoSearchResult(items=items, truncated=False),
        ),
        patch("app.tasks.timeline.topo_service.select_topo_items", return_value=items),
        patch(
            "app.tasks.timeline.topo_service.extract_geotiff_url",
            side_effect=lambda i: f"https://example.com/{i['id']}.tif",
        ),
        patch(
            "app.tasks.timeline.topo_service.extract_publication_date",
            return_value=date(1955, 1, 1),
        ),
        patch(
            "app.tasks.timeline.topo_service.extract_source_id",
            side_effect=lambda i: "" if i["id"] == "no-id" else "SRC-1",
        ),
        patch("app.tasks.timeline.topo_service.extract_bbox_wkt", return_value=None),
        patch(
            "app.tasks.timeline.imagery_service.upsert_imagery_snapshot", return_value=True
        ) as mock_upsert,
        patch("app.tasks.timeline.imagery_service.reconcile_source_snapshots"),
        patch("app.tasks.timeline.imagery_service.update_request_task"),
    ):
        count = await _fetch_usgs_topo((-105, 39, -104, 40), parcel_id, req_id)

    assert count == 1
    assert mock_upsert.call_count == 1
    assert mock_upsert.call_args.kwargs["stac_item_id"] == "SRC-1"


@pytest.mark.asyncio
async def test_fetch_usgs_topo_skips_products_with_unparseable_date(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A product whose publicationDate will not parse is skipped and logged.

    It used to be minted as 1900 and persisted, which renders on the timeline
    as a genuine 1900 sheet. The real extract_publication_date runs here — only
    the selector is stubbed, so the guard in the persistence loop is what is
    under test.
    """
    import logging

    from app.tasks.timeline import _fetch_usgs_topo

    req_id = uuid.uuid4()
    parcel_id = uuid.uuid4()

    mock_task_row = MagicMock()
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.first.return_value = mock_task_row

    items: list[dict[str, object]] = [
        {"id": "good", "sourceId": "SRC-GOOD", "publicationDate": "1965-01-01"},
        {"id": "bad", "sourceId": "SRC-BAD", "publicationDate": "n/a"},
    ]

    with (
        patch("app.db.SessionLocal", return_value=mock_db),
        patch(
            "app.tasks.timeline.topo_service.search_usgs_topo_products",
            new_callable=AsyncMock,
            return_value=topo_service.TopoSearchResult(items=items, truncated=False),
        ),
        patch("app.tasks.timeline.topo_service.select_topo_items", return_value=items),
        patch(
            "app.tasks.timeline.topo_service.extract_geotiff_url",
            side_effect=lambda i: f"https://example.com/{i['id']}.tif",
        ),
        patch("app.tasks.timeline.topo_service.extract_bbox_wkt", return_value=None),
        patch(
            "app.tasks.timeline.imagery_service.upsert_imagery_snapshot", return_value=True
        ) as mock_upsert,
        patch("app.tasks.timeline.imagery_service.reconcile_source_snapshots"),
        patch("app.tasks.timeline.imagery_service.update_request_task"),
        caplog.at_level(logging.WARNING, logger="app.tasks.timeline"),
    ):
        count = await _fetch_usgs_topo((-105, 39, -104, 40), parcel_id, req_id)

    assert count == 1
    assert mock_upsert.call_count == 1
    assert mock_upsert.call_args.kwargs["stac_item_id"] == "SRC-GOOD"
    assert mock_upsert.call_args.kwargs["capture_date"] == date(1965, 1, 1)
    assert "Skipping topo product with unparseable publicationDate" in caplog.text


# ── Selection scope agrees with the selector ─────────────────────────────────


def test_every_stac_source_scope_matches_its_selector() -> None:
    """``selection_scope`` must name the unit the source's selector groups by.

    Delete-the-fix guard for the config half of the S2 year move: a scope
    that disagrees with its selector is the one way reconciliation can
    delete rows the selector never reconsidered, or spare rows it did.
    The check is behavioural — it runs each selector over two scenes one
    quarter apart in the same year and asserts the scope's bucket agrees
    about whether they belong together.
    """
    from datetime import date as _date

    from app.services.imagery import SELECTION_SCOPES
    from app.tasks.timeline import _SOURCES

    early, late = _date(2021, 8, 14), _date(2021, 11, 2)

    def _item(d: _date, cloud: float) -> dict[str, object]:
        return {
            "id": f"item-{d}",
            "properties": {"datetime": f"{d}T00:00:00Z", "eo:cloud_cover": cloud},
            "geometry": None,
        }

    for cfg in _SOURCES:
        scope = cfg["selection_scope"]
        assert scope in SELECTION_SCOPES, cfg["source"]
        bucket = SELECTION_SCOPES[scope]
        same_bucket = bucket(early) == bucket(late)

        if cfg.get("use_viewport_filter"):
            continue  # NAIP's selector takes a viewport; year is pinned elsewhere

        groups = cfg["selector"]([_item(early, 22.0), _item(late, 1.5)])
        assert (len(groups) == 1) is same_bucket, (
            f"{cfg['source']}: selector produced {len(groups)} group(s) for two "
            f"scenes one quarter apart, but scope {scope!r} says same_bucket="
            f"{same_bucket}"
        )


def test_sentinel2_selection_scope_is_year() -> None:
    """Pinned by name as well as by behaviour — the value reconciliation reads."""
    from app.tasks.timeline import _SOURCES

    s2 = next(c for c in _SOURCES if c["source"] == "sentinel2")
    assert s2["selection_scope"] == "year"


# ── Declared scope reaches both the task rows and the fan-out ────────────────


def _orchestration_mocks(sources: list[str]) -> tuple[uuid.UUID, MagicMock, MagicMock]:
    """A mocked session whose request row declares ``sources``.

    Mirrors ``test_run_timeline_all_sources_failed_marks_request_failed``'s
    harness: the SELECTs come back request, request, parcel, then request +
    task rows.
    """
    req_id = uuid.uuid4()
    parcel_id = uuid.uuid4()

    parcel = MagicMock()
    parcel.id = parcel_id
    parcel.latitude = 39.7
    parcel.longitude = -104.9
    parcel.census_tract_id = "08031006202"
    parcel.county = "Denver"
    parcel.normalized_address = "123 MAIN ST"
    parcel.address = "123 Main St"

    request = MagicMock()
    request.id = req_id
    request.parcel_id = parcel_id
    request.status = "queued"
    request.origin = "backfill"
    request.sources = sources

    task_row = MagicMock()
    task_row.status = "complete"
    task_row.source = sources[0]

    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    calls = [0]

    def execute(_query: object) -> MagicMock:
        result = MagicMock()
        calls[0] += 1
        if calls[0] == 3:
            result.scalars.return_value.first.return_value = parcel
        else:
            result.scalars.return_value.first.return_value = request
            result.scalars.return_value.all.return_value = [task_row]
        return result

    db.execute = MagicMock(side_effect=execute)
    return req_id, db, request


@pytest.mark.asyncio
async def test_census_only_request_runs_no_imagery_and_no_reconciliation() -> None:
    """A scoped run creates task rows *and* coroutines for its sources only.

    Scoping one and not the other creates fewer task rows while still running
    every fetch, and ``_set_task_status`` then logs "No task row found for
    source" rather than failing (INVESTIGATION §1.3). The reconciliation
    assertion is the consequence that matters:
    ``reconcile_source_snapshots`` is reachable only from the imagery and
    topo coroutines, so a census-only scope cannot delete a snapshot.

    Delete the ``if source_cfg["source"] not in scoped`` guard and
    ``_fetch_source`` is called three times.
    """
    from app.tasks.timeline import _run_timeline_inner

    req_id, db, _ = _orchestration_mocks(["census"])

    settings = MagicMock()
    settings.census_api_key = None
    settings.census_api_timeout = 10
    settings.socrata_app_token = None

    with (
        patch("app.db.SessionLocal", return_value=db),
        patch("app.config.get_settings", return_value=settings),
        patch("app.tasks.timeline.stac_service.point_to_bbox", return_value=(-105, 39, -104, 40)),
        patch("app.tasks.timeline._fetch_source", new_callable=AsyncMock) as fetch_source,
        patch("app.tasks.timeline._fetch_usgs_topo", new_callable=AsyncMock) as fetch_topo,
        patch("app.tasks.timeline._fetch_census", new_callable=AsyncMock, return_value=9) as census,
        patch("app.tasks.timeline._fetch_property", new_callable=AsyncMock) as prop,
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status"),
        patch("app.tasks.timeline.imagery_service.reconcile_source_snapshots") as reconcile,
        patch("app.tasks.timeline.imagery_service.create_request_tasks") as create_tasks,
    ):
        await _run_timeline_inner(str(req_id))

    assert create_tasks.call_args.kwargs["sources"] == ["census"]
    census.assert_awaited_once()
    fetch_source.assert_not_called()
    fetch_topo.assert_not_called()
    prop.assert_not_called()
    reconcile.assert_not_called()


@pytest.mark.asyncio
async def test_declared_scope_never_outruns_parcel_eligibility() -> None:
    """Declared intent is intersected with fact, not trusted over it.

    A full-scope request on a parcel with no county still runs no property
    task — the behaviour before the column existed.
    """
    from app.tasks.timeline import _run_timeline_inner

    req_id, db, _ = _orchestration_mocks(list(TimelineRequest.FULL_SCOPE))
    settings = MagicMock()
    settings.census_api_key = None
    settings.census_api_timeout = 10
    settings.socrata_app_token = None

    with (
        patch("app.db.SessionLocal", return_value=db),
        patch("app.config.get_settings", return_value=settings),
        patch("app.tasks.timeline.stac_service.point_to_bbox", return_value=(-105, 39, -104, 40)),
        patch("app.tasks.timeline._fetch_source", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_usgs_topo", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_census", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_property", new_callable=AsyncMock, return_value=0) as prop,
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status"),
        patch("app.tasks.timeline.imagery_service.create_request_tasks") as create_tasks,
    ):
        await _run_timeline_inner(str(req_id))

    assert create_tasks.call_args.kwargs["sources"] == sorted(TimelineRequest.FULL_SCOPE)
    prop.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_failed_source_makes_the_request_partial() -> None:
    """6563dedf's shape: naip and sentinel2 failed under a 'complete' request."""
    from app.tasks.timeline import _run_timeline_inner

    req_id, db, _ = _orchestration_mocks(list(TimelineRequest.FULL_SCOPE))

    rows = []
    for source, status in (
        ("census", "complete"),
        ("landsat", "complete"),
        ("naip", "failed"),
        ("property", "skipped"),
        ("sentinel2", "failed"),
        ("usgs_topo", "complete"),
    ):
        row = MagicMock()
        row.source, row.status = source, status
        rows.append(row)

    original = db.execute.side_effect

    def execute(query: object) -> MagicMock:
        result = original(query)
        result.scalars.return_value.all.return_value = rows
        return result

    db.execute = MagicMock(side_effect=execute)

    settings = MagicMock()
    settings.census_api_key = None
    settings.census_api_timeout = 10
    settings.socrata_app_token = None

    with (
        patch("app.db.SessionLocal", return_value=db),
        patch("app.config.get_settings", return_value=settings),
        patch("app.tasks.timeline.stac_service.point_to_bbox", return_value=(-105, 39, -104, 40)),
        patch("app.tasks.timeline._fetch_source", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_usgs_topo", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_census", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline._fetch_property", new_callable=AsyncMock, return_value=0),
        patch("app.tasks.timeline.imagery_service.update_timeline_request_status") as status,
        patch("app.tasks.timeline.imagery_service.create_request_tasks"),
    ):
        result = await _run_timeline_inner(str(req_id))

    assert [c[0][2] for c in status.call_args_list] == ["processing", "partial"]
    assert status.call_args.kwargs["error_message"] is None
    assert result["status"] == "partial"
