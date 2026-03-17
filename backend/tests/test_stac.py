"""Tests for the STAC service — bounding box generation and item selection logic."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services.stac import (
    extract_cog_url,
    extract_thumbnail_url,
    point_to_bbox,
    search_stac,
    select_landsat_items,
    select_naip_items,
    select_sentinel_items,
    sign_pc_url,
)


# ── Bounding box ───────────────────────────────────────────────────────────────


def test_point_to_bbox_returns_four_floats() -> None:
    """point_to_bbox should return a 4-tuple of floats."""
    bbox = point_to_bbox(lat=39.7392, lng=-104.9903, buffer_m=500)
    assert len(bbox) == 4
    west, south, east, north = bbox
    assert isinstance(west, float)
    assert west < east, "west must be less than east"
    assert south < north, "south must be less than north"


def test_point_to_bbox_contains_original_point() -> None:
    """The buffered bbox must contain the original lat/lng."""
    lat, lng = 39.7392, -104.9903
    west, south, east, north = point_to_bbox(lat, lng, buffer_m=500)
    assert west <= lng <= east
    assert south <= lat <= north


def test_point_to_bbox_buffer_size() -> None:
    """A 1000m buffer should produce a larger bbox than a 100m buffer."""
    small = point_to_bbox(39.7392, -104.9903, buffer_m=100)
    large = point_to_bbox(39.7392, -104.9903, buffer_m=1000)
    # Width (east - west)
    assert (large[2] - large[0]) > (small[2] - small[0])


def test_point_to_bbox_southern_hemisphere() -> None:
    """Works correctly in the southern hemisphere (UTM zone 7xx)."""
    bbox = point_to_bbox(lat=-33.8688, lng=151.2093, buffer_m=500)
    west, south, east, north = bbox
    assert west < east
    assert south < north


# ── NAIP item selection ────────────────────────────────────────────────────────


def _make_item(dt: str, cloud_cover: float | None = None) -> dict:
    props: dict = {"datetime": dt}
    if cloud_cover is not None:
        props["eo:cloud_cover"] = cloud_cover
    return {"id": f"item-{dt}", "properties": props, "assets": {}, "bbox": None}


def test_select_naip_one_per_year() -> None:
    """select_naip_items returns at most one item per year."""
    items = [
        _make_item("2020-06-01T00:00:00Z"),
        _make_item("2020-08-15T00:00:00Z"),
        _make_item("2021-07-10T00:00:00Z"),
        _make_item("2022-05-01T00:00:00Z"),
    ]
    selected = select_naip_items(items)
    years = [date.fromisoformat(i["properties"]["datetime"][:10]).year for i in selected]
    assert years == sorted(set(years)), "Should have exactly one item per year"
    assert len(selected) == 3


def test_select_naip_prefers_mid_summer() -> None:
    """Among same-year items, NAIP selector picks the one closest to July 15."""
    items = [
        _make_item("2019-03-01T00:00:00Z"),  # far from mid-summer
        _make_item("2019-07-20T00:00:00Z"),  # closest to July 15
        _make_item("2019-11-01T00:00:00Z"),  # far from mid-summer
    ]
    selected = select_naip_items(items)
    assert len(selected) == 1
    assert selected[0]["properties"]["datetime"][:10] == "2019-07-20"


# ── Landsat item selection ─────────────────────────────────────────────────────


def test_select_landsat_one_per_year() -> None:
    """select_landsat_items returns one item per year."""
    items = [
        _make_item("2000-06-01T00:00:00Z", cloud_cover=15.0),
        _make_item("2000-09-01T00:00:00Z", cloud_cover=5.0),
        _make_item("2001-05-01T00:00:00Z", cloud_cover=18.0),
    ]
    selected = select_landsat_items(items)
    years = [date.fromisoformat(i["properties"]["datetime"][:10]).year for i in selected]
    assert years == sorted(set(years))
    assert len(selected) == 2


def test_select_landsat_picks_lowest_cloud_cover() -> None:
    """Landsat selector picks the item with the lowest cloud cover."""
    items = [
        _make_item("2010-06-01T00:00:00Z", cloud_cover=18.0),
        _make_item("2010-07-01T00:00:00Z", cloud_cover=3.0),
        _make_item("2010-08-01T00:00:00Z", cloud_cover=12.0),
    ]
    selected = select_landsat_items(items)
    assert len(selected) == 1
    assert selected[0]["properties"]["eo:cloud_cover"] == 3.0


# ── Sentinel-2 item selection ─────────────────────────────────────────────────


def test_select_sentinel_one_per_quarter() -> None:
    """select_sentinel_items returns one item per calendar quarter."""
    items = [
        _make_item("2020-01-10T00:00:00Z", cloud_cover=10.0),
        _make_item("2020-02-20T00:00:00Z", cloud_cover=5.0),  # Q1 — should win
        _make_item("2020-04-05T00:00:00Z", cloud_cover=8.0),  # Q2
        _make_item("2020-07-15T00:00:00Z", cloud_cover=15.0),  # Q3
    ]
    selected = select_sentinel_items(items)
    assert len(selected) == 3


# ── Asset extraction ───────────────────────────────────────────────────────────


def test_extract_cog_url_naip() -> None:
    item = {
        "assets": {"image": {"href": "https://example.com/naip.tif"}},
        "properties": {},
    }
    assert extract_cog_url(item, "naip") == "https://example.com/naip.tif"


def test_extract_cog_url_landsat_rendered_preview() -> None:
    item = {
        "assets": {
            "rendered_preview": {"href": "https://example.com/preview.png"},
            "red": {"href": "https://example.com/red.tif"},
        },
        "properties": {},
    }
    result = extract_cog_url(item, "landsat-c2-l2")
    assert result == "https://example.com/preview.png"


def test_extract_cog_url_missing() -> None:
    item = {"assets": {}, "properties": {}}
    assert extract_cog_url(item, "naip") is None


def test_extract_thumbnail_rendered_preview() -> None:
    item = {"assets": {"rendered_preview": {"href": "https://example.com/thumb.png"}}}
    assert extract_thumbnail_url(item) == "https://example.com/thumb.png"


def test_extract_thumbnail_none_when_missing() -> None:
    item = {"assets": {}}
    assert extract_thumbnail_url(item) is None


# ── STAC search (mocked HTTP) ─────────────────────────────────────────────────


def _make_httpx_mock_client(method: str, response_data: dict) -> tuple:
    """Build an httpx.AsyncClient mock for async context manager usage.

    httpx response methods (json, raise_for_status) are synchronous.
    Only the HTTP method calls (get, post) are async.
    """
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=response_data)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    setattr(mock_client, method, AsyncMock(return_value=mock_resp))

    return mock_client, mock_resp


@pytest.mark.asyncio
async def test_search_stac_returns_items() -> None:
    """search_stac parses the features array from the STAC API response."""
    mock_response = {
        "features": [
            {"id": "item-1", "properties": {"datetime": "2020-06-01T00:00:00Z"}},
            {"id": "item-2", "properties": {"datetime": "2021-07-01T00:00:00Z"}},
        ],
        "links": [],
    }

    mock_client, _ = _make_httpx_mock_client("post", mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        items = await search_stac(
            collection="naip",
            bbox=(-105.0, 39.7, -104.9, 39.8),
            datetime_range="2020-01-01/2021-12-31",
            max_items=10,
        )

    assert len(items) == 2
    assert items[0]["id"] == "item-1"


@pytest.mark.asyncio
async def test_sign_pc_url() -> None:
    """sign_pc_url appends the signed href from the API response."""
    signed = "https://example.com/asset.tif?sv=signed"
    mock_client, _ = _make_httpx_mock_client("get", {"href": signed})

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == signed
