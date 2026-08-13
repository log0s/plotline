"""Tests for the USGS Historical Topographic Maps service (TNM API)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import usgs_topo


def _product(source_id: str, pub_date: str) -> dict[str, Any]:
    return {
        "sourceId": source_id,
        "publicationDate": pub_date,
        "urls": {"GeoTIFF": f"https://example.com/{source_id}.tif"},
    }


# ── Publication date ─────────────────────────────────────────────────────────


def test_publication_date_reads_the_year() -> None:
    assert usgs_topo.extract_publication_date(_product("a", "1965-06-01")) == date(1965, 1, 1)


@pytest.mark.parametrize("pub_date", ["", "n/a", "unknown", "19"])
def test_publication_date_is_none_when_unparseable(pub_date: str) -> None:
    """No invented year. This used to return date(1900, 1, 1)."""
    assert usgs_topo.extract_publication_date(_product("a", pub_date)) is None


def test_publication_date_is_none_when_absent() -> None:
    assert usgs_topo.extract_publication_date({"sourceId": "a"}) is None


# ── Cap-hit warning ──────────────────────────────────────────────────────────


def _mock_client(items: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"items": items}
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return client


async def _search_returning(items: list[dict[str, Any]], max_items: int) -> None:
    with patch.object(usgs_topo, "_get_tnm_client", return_value=_mock_client(items)):
        await usgs_topo.search_usgs_topo((-105, 39, -104, 40), max_items=max_items)


@pytest.mark.asyncio
async def test_warns_when_tnm_returns_exactly_its_cap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    items = [_product(f"s{i}", "1965-01-01") for i in range(10)]
    with caplog.at_level(logging.WARNING, logger="app.services.usgs_topo"):
        await _search_returning(items, 10)

    assert "TNM query hit its row cap" in caplog.text
    record = next(r for r in caplog.records if "hit its row cap" in r.getMessage())
    assert record.cap == 10  # type: ignore[attr-defined]  # structlog-style extra
    assert record.resource == "Historical Topographic Maps"  # type: ignore[attr-defined]  # ditto


@pytest.mark.asyncio
async def test_no_warning_below_the_cap(caplog: pytest.LogCaptureFixture) -> None:
    items = [_product(f"s{i}", "1965-01-01") for i in range(9)]
    with caplog.at_level(logging.WARNING, logger="app.services.usgs_topo"):
        await _search_returning(items, 10)

    assert "hit its row cap" not in caplog.text


@pytest.mark.asyncio
async def test_cap_check_counts_raw_products_not_geotiff_survivors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The GeoTIFF filter runs after the cap; truncation happens upstream of it,
    so a full page whose products mostly lack a GeoTIFF is still truncated."""
    items = [_product(f"s{i}", "1965-01-01") for i in range(3)]
    items += [{"sourceId": f"n{i}", "publicationDate": "1965-01-01"} for i in range(7)]
    with caplog.at_level(logging.WARNING, logger="app.services.usgs_topo"):
        await _search_returning(items, 10)

    assert "TNM query hit its row cap" in caplog.text
