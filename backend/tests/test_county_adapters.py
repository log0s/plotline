"""Tests for county adapter WHERE-clause construction and parallel fan-out."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.county_adapters import (
    AdamsCountyAdapter,
    DCAdapter,
    DenverAdapter,
    NewYorkCountyAdapter,
    SantaClaraAdapter,
    _escape_sql_literal,
    get_adapter_for_county,
)

# ── _escape_sql_literal ────────────────────────────────────────────────────────


def test_escape_doubles_single_quotes() -> None:
    assert _escape_sql_literal("O'Brien") == "O''Brien"


def test_escape_strips_non_printable() -> None:
    assert _escape_sql_literal("MAIN\x00ST\n") == "MAINST"


def test_escape_caps_length_at_100() -> None:
    long = "A" * 250
    assert len(_escape_sql_literal(long)) == 100


# ── DenverAdapter — escape applied + parallel residential/commercial ──────────


@pytest.mark.asyncio
async def test_denver_permits_escapes_and_fans_out() -> None:
    """fetch_permits should escape the address and gather residential +
    commercial in parallel (both URLs hit, regardless of order)."""
    adapter = DenverAdapter()
    with patch(
        "app.services.county_adapters.query_feature_service",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_permits("1437", "BANNOCK")

    assert mock_query.call_count == 2
    urls_hit = {call.args[0] for call in mock_query.call_args_list}
    assert urls_hit == {
        adapter.RESIDENTIAL_PERMITS_URL,
        adapter.COMMERCIAL_PERMITS_URL,
    }
    # Both calls share the same WHERE clause
    wheres = {call.kwargs["where"] for call in mock_query.call_args_list}
    assert wheres == {"upper(ADDRESS) LIKE '1437 %BANNOCK%'"}


@pytest.mark.asyncio
async def test_denver_permits_escapes_apostrophe_in_street_name() -> None:
    """An address like 'O'BRIEN ST' must not break the WHERE syntax."""
    adapter = DenverAdapter()
    with patch(
        "app.services.county_adapters.query_feature_service",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_permits("100", "O'BRIEN")

    where = mock_query.call_args_list[0].kwargs["where"]
    # Doubled apostrophe is the standard SQL escape
    assert "O''BRIEN" in where
    assert "'O'BRIEN'" not in where  # would-be-broken raw form


# ── DC adapter — 7-layer parallel fan-out ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dc_permits_fans_out_across_seven_layers() -> None:
    adapter = DCAdapter()
    with patch(
        "app.services.county_adapters.query_feature_service",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_permits("1300", "4TH")

    assert mock_query.call_count == len(adapter.PERMIT_LAYERS) == 7
    where = mock_query.call_args_list[0].kwargs["where"]
    assert where == "upper(FULL_ADDRESS) LIKE '1300 %4TH%'"


@pytest.mark.asyncio
async def test_dc_sales_escapes_address() -> None:
    adapter = DCAdapter()
    with patch(
        "app.services.county_adapters.query_feature_service",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_sales("1600", "PENNSYLVANIA")

    where = mock_query.call_args_list[0].kwargs["where"]
    assert where == "upper(PROPERTY_ADDRESS) LIKE '1600 %PENNSYLVANIA%'"


# ── Adams adapter ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adams_permits_where_uses_combined_address() -> None:
    adapter = AdamsCountyAdapter()
    with patch(
        "app.services.county_adapters.query_feature_service",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_permits("12345", "FOX RUN")

    where = mock_query.call_args_list[0].kwargs["where"]
    assert where == "upper(CombinedAddress) LIKE '12345 %FOX RUN%'"


# ── NYC adapter — borough filters preserved alongside escape ──────────────────


@pytest.mark.asyncio
async def test_nyc_sales_includes_borough_and_escape() -> None:
    adapter = NewYorkCountyAdapter()
    with patch(
        "app.services.county_adapters.query_socrata",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_sales("350", "5TH AVE")

    # Both sales datasets are queried: annualized history + rolling year
    assert mock_query.call_count == 2
    queried = {c.args[1] for c in mock_query.call_args_list}
    assert queried == {"w2pb-icbu", "usep-8jbt"}
    where = mock_query.call_args_list[0].kwargs["where"]
    assert "borough='1'" in where
    assert "350 5TH AVE" in where
    assert "sale_price > 0" in where


@pytest.mark.asyncio
async def test_nyc_permits_escapes_in_borough_filter() -> None:
    adapter = NewYorkCountyAdapter()
    with patch(
        "app.services.county_adapters.query_socrata",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        # Apostrophe in number is impossible but exercise on street_name
        await adapter.fetch_permits("350", "O'CONNELL")

    where = mock_query.call_args_list[0].kwargs["where"]
    assert "borough='MANHATTAN'" in where
    assert "house__='350'" in where
    # Apostrophe doubled inside the LIKE pattern
    assert "O''CONNELL" in where


# ── Santa Clara / San Jose — CKAN fan-out ─────────────────────────────────────


@pytest.mark.asyncio
async def test_san_jose_permits_fans_out_across_resources() -> None:
    adapter = SantaClaraAdapter()
    with patch(
        "app.services.county_adapters.query_ckan_datastore",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_query:
        await adapter.fetch_permits("200", "SANTA CLARA")

    assert mock_query.call_count == len(adapter.PERMIT_RESOURCES) == 3
    qs = {call.kwargs["q"] for call in mock_query.call_args_list}
    assert qs == {"200 SANTA CLARA"}


# ── Adapter registry sanity ───────────────────────────────────────────────────


def test_adapter_registry_strips_county_suffix_and_lowercases() -> None:
    assert isinstance(get_adapter_for_county("Denver County"), DenverAdapter)
    assert isinstance(get_adapter_for_county("denver"), DenverAdapter)
    assert isinstance(get_adapter_for_county("New York"), NewYorkCountyAdapter)
    assert get_adapter_for_county("Nonexistent") is None


# ── Malformed portal responses ────────────────────────────────────────────────
#
# A portal answering 200 with an HTML error page used to raise a bare
# JSONDecodeError out of resp.json(). That escaped the per-query handler
# (which catches portal-failure types only) and failed the whole property
# task, discarding other portals' successful queries with it.

_HTML_BODY = (
    "<html><head><title>502 Bad Gateway</title></head>"
    "<body><h1>502 Bad Gateway</h1><p>nginx</p></body></html>"
)


def _html_200_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = _HTML_BODY
    resp.json.side_effect = json.JSONDecodeError("Expecting value", _HTML_BODY, 0)
    return resp


def _json_200_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "{}"
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
async def test_arcgis_html_body_raises_arcgis_error() -> None:
    from app.services.arcgis import ArcGISError, query_feature_service

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_html_200_response(),
        ),
        pytest.raises(ArcGISError, match="invalid JSON"),
    ):
        await query_feature_service("https://example.com/FeatureServer/0")


def _429_response(retry_after: str | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "Rate limit exceeded"
    resp.headers = {"retry-after": retry_after} if retry_after else {}
    return resp


@pytest.mark.asyncio
async def test_arcgis_retries_a_429_then_succeeds() -> None:
    """Esri rate-limits hosted feature services; a 429 means slow down."""
    from app.services.arcgis import query_feature_service

    good = _json_200_response({"features": [{"attributes": {"PERMIT_NUM": "1"}}]})

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=[_429_response(), good],
        ) as get,
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        rows = await query_feature_service("https://example.com/FeatureServer/0")

    assert rows == [{"PERMIT_NUM": "1"}]
    assert get.await_count == 2
    assert sleep.await_count == 1


@pytest.mark.asyncio
async def test_arcgis_caps_an_absurd_retry_after() -> None:
    """A portal free to ask for minutes cannot spend the query's whole budget."""
    from app.services.arcgis import (
        _RETRY_AFTER_CAP_S,
        _RETRY_JITTER_FRACTION,
        query_feature_service,
    )

    good = _json_200_response({"features": []})

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=[_429_response(retry_after="600"), good],
        ),
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        await query_feature_service("https://example.com/FeatureServer/0")

    slept = sleep.await_args_list[0].args[0]
    assert _RETRY_AFTER_CAP_S <= slept <= _RETRY_AFTER_CAP_S * (1.0 + _RETRY_JITTER_FRACTION)


@pytest.mark.asyncio
async def test_arcgis_exhausted_429_raises_naming_the_status() -> None:
    """An unclearing 429 is a failed query, never zero rows.

    Delete-the-fix: drop the `if resp.status_code == 429` raise and the
    generic non-200 branch below it still raises — but drop the retry and a
    single throttled request fails a query that one sleep would have served.
    """
    from app.services.arcgis import _RETRY_ATTEMPTS, ArcGISError, query_feature_service

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_429_response(retry_after="1"),
        ) as get,
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(ArcGISError, match="429"),
    ):
        await query_feature_service("https://example.com/FeatureServer/0")

    assert get.await_count == _RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_arcgis_429_does_not_outlive_the_query_budget() -> None:
    """The retry lives inside the caller's 30 s timeout, it does not extend it."""
    from app.services.arcgis import ArcGISError, query_feature_service

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_429_response(retry_after="20"),
        ) as get,
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(ArcGISError, match="429"),
    ):
        await query_feature_service("https://example.com/FeatureServer/0", timeout=5.0)

    assert sleep.await_count == 0, "a 20 s backoff overshoots a 5 s query budget"
    assert get.await_count == 1


@pytest.mark.asyncio
async def test_exhausted_429_marks_the_property_query_failed_not_empty() -> None:
    """The rollup must see a failed query, not a county with no permits.

    Denver fans out to two permit layers, so one 429-exhausted query leaves
    the task `complete` under the all-or-nothing rule at
    tasks/timeline.py:1291 — but `queries_failed` carries it, which is what
    a reader of the row and any future partial-status rule reads.
    """
    adapter = DenverAdapter()
    good = _json_200_response({"features": []})

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=[*[_429_response()] * 3, good],
        ),
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await adapter.fetch_permits("1437", "BANNOCK")

    assert result.queries_attempted == 2
    assert result.queries_failed == 1
    assert result.events == []


@pytest.mark.asyncio
async def test_every_query_429_fails_the_property_task() -> None:
    """All queries throttled is an outage, and `all_queries_failed` says so."""
    adapter = AdamsCountyAdapter()

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_429_response(),
        ),
        patch("app.services.arcgis.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await adapter.fetch_permits("100", "MAIN")

    assert result.all_queries_failed


@pytest.mark.asyncio
async def test_socrata_404_raises_rather_than_returning_zero_rows() -> None:
    """Delete-the-fix: restore `if resp.status_code == 404: return []`.

    A retired or renamed 4x4 resource id then reads as "this address has no
    records" — the complete-with-zero shape, on a path with no ledger to
    correct it later.
    """
    from app.services.socrata import SocrataError, query_socrata

    resp = MagicMock()
    resp.status_code = 404
    resp.text = "Not found"

    with (
        patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp),
        pytest.raises(SocrataError, match="404"),
    ):
        await query_socrata("data.cityofnewyork.us", "ipu4-2q9a")


@pytest.mark.asyncio
async def test_nyc_404_yields_a_failed_query_not_items_found_zero() -> None:
    """The NYC permits dataset 404ing must reach the rollup as a failure."""
    adapter = NewYorkCountyAdapter()
    resp = MagicMock()
    resp.status_code = 404
    resp.text = "Not found"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp):
        result = await adapter.fetch_permits("350", "5TH AVE")

    assert result.queries_attempted == 1
    assert result.queries_failed == 1
    assert result.all_queries_failed, "an outage, not an address with no permits"


@pytest.mark.asyncio
async def test_socrata_html_body_raises_socrata_error() -> None:
    from app.services.socrata import SocrataError, query_socrata

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_html_200_response(),
        ),
        pytest.raises(SocrataError, match="invalid JSON"),
    ):
        await query_socrata("data.cityofnewyork.us", "ipu4-2q9a")


@pytest.mark.asyncio
async def test_ckan_html_body_raises_ckan_error() -> None:
    from app.services.ckan import CKANError, query_ckan_datastore

    with (
        patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            return_value=_html_200_response(),
        ),
        pytest.raises(CKANError, match="invalid JSON"),
    ):
        await query_ckan_datastore("data.sanjoseca.gov", "some-resource-id")


@pytest.mark.asyncio
async def test_one_malformed_query_does_not_discard_the_others() -> None:
    """Denver fans out to two permit layers. One returning HTML costs one
    query, not the whole fetch."""
    adapter = DenverAdapter()
    good = _json_200_response(
        {
            "features": [
                {
                    "attributes": {
                        "PERMIT_NUM": "2024-BLD-001",
                        "ADDRESS": "1437 N BANNOCK ST",
                        "CLASS": "New Building",
                        "DATE_ISSUED": 1700000000000,
                    }
                }
            ]
        }
    )

    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=[_html_200_response(), good],
    ):
        result = await adapter.fetch_permits("1437", "BANNOCK")

    assert result.queries_attempted == 2
    assert result.queries_failed == 1
    assert not result.all_queries_failed
    # The surviving layer's record is still here
    assert [e.source_record_id for e in result.events] == ["2024-BLD-001"]


# ── Municipality coverage gate ───────────────────────────────────────────────


def test_covers_defaults_to_true_for_city_county_adapters() -> None:
    """Denver, DC and Manhattan have no boundary below the county to gate on."""
    from app.services.county_adapters import DCAdapter, DenverAdapter, NewYorkCountyAdapter

    for adapter in (DenverAdapter(), DCAdapter(), NewYorkCountyAdapter()):
        assert adapter.covers("ANY CITY") is True
        assert adapter.covers(None) is True


@pytest.mark.parametrize(
    ("city", "covered"),
    [
        # The confirmed instance: 12804 Emerson is Thornton's to permit.
        ("THORNTON", False),
        ("Thornton", False),
        ("  northglenn ", False),
        ("COMMERCE CITY", False),
        # Mailing cities for large unincorporated pockets the layer does
        # cover — 8601 EMERSON CT geocodes to DENVER in Adams County and
        # 16610 YORK ST to BRIGHTON, and the layer holds records for both.
        ("DENVER", True),
        ("BRIGHTON", True),
        ("STRASBURG", True),
        # Never deny on missing data.
        (None, True),
        ("", True),
    ],
)
def test_adams_covers_unincorporated_only(city: str | None, covered: bool) -> None:
    """Delete-the-fix: return True unconditionally from AdamsCountyAdapter.covers
    and the Thornton rows fail — which is the state that reported 12804 Emerson
    as complete:0 rather than not-covered."""
    from app.services.county_adapters import AdamsCountyAdapter

    assert AdamsCountyAdapter().covers(city) is covered


@pytest.mark.parametrize(
    ("city", "covered"),
    [
        ("SAN JOSE", True),
        ("san jose", True),
        ("SUNNYVALE", False),
        ("MOUNTAIN VIEW", False),
        ("CUPERTINO", False),
        (None, True),
    ],
)
def test_santa_clara_covers_san_jose_only(city: str | None, covered: bool) -> None:
    """data.sanjoseca.gov is one city's portal, not the county's."""
    from app.services.county_adapters import SantaClaraAdapter

    assert SantaClaraAdapter().covers(city) is covered
