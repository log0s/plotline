"""Tests for county adapter WHERE-clause construction and parallel fan-out."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
    assert where == "upper(FULL_ADDRESS) LIKE '%1300 %4TH%'"


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
    assert where == "upper(PROPERTY_ADDRESS) LIKE '%1600 %PENNSYLVANIA%'"


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

    where = mock_query.call_args_list[0].kwargs["where"]
    assert "borough='1'" in where
    assert "350 5TH AVE" in where
    assert "sale_price > '0'" in where


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
