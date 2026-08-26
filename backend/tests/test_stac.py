"""Tests for the STAC service — bounding box generation and item selection logic."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.stac import (
    STAC_API,
    _is_cog_asset,
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


def test_select_naip_one_group_per_year() -> None:
    """select_naip_items returns at most one group per year (legacy, no viewport)."""
    items = [
        _make_item("2020-06-01T00:00:00Z"),
        _make_item("2020-08-15T00:00:00Z"),
        _make_item("2021-07-10T00:00:00Z"),
        _make_item("2022-05-01T00:00:00Z"),
    ]
    groups = select_naip_items(items)
    # Each group is a list of one or more items; legacy mode yields 1/year
    assert len(groups) == 3
    for group in groups:
        assert len(group) == 1
    years = [date.fromisoformat(g[0]["properties"]["datetime"][:10]).year for g in groups]
    assert years == sorted(set(years))


def test_select_naip_prefers_mid_summer() -> None:
    """Among same-year items, NAIP selector picks the one closest to July 15."""
    items = [
        _make_item("2019-03-01T00:00:00Z"),  # far from mid-summer
        _make_item("2019-07-20T00:00:00Z"),  # closest to July 15
        _make_item("2019-11-01T00:00:00Z"),  # far from mid-summer
    ]
    groups = select_naip_items(items)
    assert len(groups) == 1
    assert len(groups[0]) == 1
    assert groups[0][0]["properties"]["datetime"][:10] == "2019-07-20"


# ── Landsat item selection ─────────────────────────────────────────────────────


def test_select_landsat_one_per_year() -> None:
    """select_landsat_items returns one group per year, each with a single item."""
    items = [
        _make_item("2000-06-01T00:00:00Z", cloud_cover=15.0),
        _make_item("2000-09-01T00:00:00Z", cloud_cover=5.0),
        _make_item("2001-05-01T00:00:00Z", cloud_cover=18.0),
    ]
    groups = select_landsat_items(items)
    assert len(groups) == 2
    for g in groups:
        assert len(g) == 1
    years = [date.fromisoformat(g[0]["properties"]["datetime"][:10]).year for g in groups]
    assert years == sorted(set(years))


def test_select_landsat_picks_lowest_cloud_cover() -> None:
    """Landsat selector picks the item with the lowest cloud cover."""
    items = [
        _make_item("2010-06-01T00:00:00Z", cloud_cover=18.0),
        _make_item("2010-07-01T00:00:00Z", cloud_cover=3.0),
        _make_item("2010-08-01T00:00:00Z", cloud_cover=12.0),
    ]
    groups = select_landsat_items(items)
    assert len(groups) == 1
    assert groups[0][0]["properties"]["eo:cloud_cover"] == 3.0


# ── Sentinel-2 item selection ─────────────────────────────────────────────────


def test_select_sentinel_one_per_year() -> None:
    """select_sentinel_items returns one group per calendar year.

    Delete-the-fix guard: all four items sit in 2020, in three different
    quarters. Under the old quarter key this returned 3 groups.
    """
    items = [
        _make_item("2020-01-10T00:00:00Z", cloud_cover=10.0),
        _make_item("2020-02-20T00:00:00Z", cloud_cover=5.0),  # lowest cloud — wins
        _make_item("2020-04-05T00:00:00Z", cloud_cover=8.0),
        _make_item("2020-07-15T00:00:00Z", cloud_cover=15.0),
    ]
    groups = select_sentinel_items(items)
    assert len(groups) == 1
    assert len(groups[0]) == 1
    assert groups[0][0]["properties"]["eo:cloud_cover"] == 5.0


def test_select_sentinel_picks_best_cloud_across_quarters() -> None:
    """Two scenes, same year, different quarters — only one survives.

    The tightest form of the guard: reverting to the quarter key returns
    two groups here, not one.
    """
    items = [
        _make_item("2021-08-14T00:00:00Z", cloud_cover=22.0),  # Q3
        _make_item("2021-11-02T00:00:00Z", cloud_cover=1.5),  # Q4 — wins
    ]
    groups = select_sentinel_items(items)
    assert [g[0]["properties"]["datetime"] for g in groups] == ["2021-11-02T00:00:00Z"]


def test_select_sentinel_separates_years() -> None:
    """Year grouping still keeps distinct years apart."""
    items = [
        _make_item("2020-11-02T00:00:00Z", cloud_cover=9.0),
        _make_item("2021-11-02T00:00:00Z", cloud_cover=3.0),
    ]
    groups = select_sentinel_items(items)
    assert len(groups) == 2


# ── _is_cog_asset guard ────────────────────────────────────────────────────────


def test_is_cog_asset_geotiff() -> None:
    asset = {"type": "image/tiff; application=geotiff; profile=cloud-optimized", "href": "x.tif"}
    assert _is_cog_asset(asset) is True


def test_is_cog_asset_png_rejected() -> None:
    asset = {"type": "image/png", "href": "x.png"}
    assert _is_cog_asset(asset) is False


def test_is_cog_asset_no_type_assumed_safe() -> None:
    """Assets without a type field are assumed COG for backwards-compat."""
    asset = {"href": "x.tif"}
    assert _is_cog_asset(asset) is True


# ── Asset extraction ───────────────────────────────────────────────────────────


def test_extract_cog_url_naip() -> None:
    item = {
        "assets": {
            "image": {
                "href": "https://example.com/naip.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            },
        },
        "properties": {},
    }
    assert extract_cog_url(item, "naip") == "https://example.com/naip.tif"


def test_extract_cog_url_naip_rejects_non_cog() -> None:
    """NAIP image asset that is NOT a GeoTIFF should be rejected."""
    item = {
        "assets": {"image": {"href": "https://example.com/naip.png", "type": "image/png"}},
        "properties": {},
    }
    assert extract_cog_url(item, "naip") is None


def test_extract_cog_url_landsat_returns_self_link() -> None:
    """Landsat should return the STAC item self-link, not an individual band URL."""
    self_url = "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_TEST"
    item = {
        "id": "LC09_TEST",
        "assets": {
            "rendered_preview": {"href": "https://example.com/preview.png", "type": "image/png"},
            "red": {
                "href": "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif",
                "type": "image/tiff; application=geotiff",
            },
        },
        "links": [
            {"rel": "self", "href": self_url},
            {"rel": "parent", "href": "https://example.com/parent"},
        ],
        "properties": {},
    }
    result = extract_cog_url(item, "landsat-c2-l2")
    assert result == self_url


def test_extract_cog_url_landsat_fallback_constructs_url() -> None:
    """When no self link exists, construct the URL from collection + item ID."""
    item = {
        "id": "LC09_TEST",
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif"}
        },
        "links": [],
        "properties": {},
    }
    result = extract_cog_url(item, "landsat-c2-l2")
    assert result == f"{STAC_API}/collections/landsat-c2-l2/items/LC09_TEST"


def test_extract_cog_url_landsat_no_id_returns_none() -> None:
    """Landsat item with no self link and no id returns None."""
    item = {"assets": {}, "links": [], "properties": {}}
    assert extract_cog_url(item, "landsat-c2-l2") is None


def test_extract_cog_url_sentinel2_visual() -> None:
    item = {
        "assets": {
            "visual": {
                "href": "https://example.com/tci.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            },
            "B04": {
                "href": "https://example.com/b04.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            },
        },
        "properties": {},
    }
    result = extract_cog_url(item, "sentinel-2-l2a")
    assert result == "https://example.com/tci.tif", "Should prefer visual over B04"


def test_extract_cog_url_sentinel2_b04_not_used_as_fallback() -> None:
    """B04 alone should NOT be used — its uint16 range is incompatible with TCI rescale."""
    item = {
        "assets": {
            "B04": {
                "href": "https://example.com/b04.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            },
        },
        "properties": {},
    }
    assert extract_cog_url(item, "sentinel-2-l2a") is None


def test_extract_cog_url_sentinel2_rejects_non_geotiff() -> None:
    """visual asset that isn't a GeoTIFF should be rejected."""
    item = {
        "assets": {"visual": {"href": "https://example.com/tci.png", "type": "image/png"}},
        "properties": {},
    }
    assert extract_cog_url(item, "sentinel-2-l2a") is None


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

    with patch("app.services.stac._get_search_client", return_value=mock_client):
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

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Cache miss
    mock_redis.setex.return_value = None

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=mock_redis),
    ):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == signed


# ── sign_pc_url cache hit ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sign_pc_url_cache_hit() -> None:
    """When Redis has a cached signed URL, return it without calling the API."""
    cached = "https://example.com/asset.tif?sv=cached"

    mock_redis = AsyncMock()
    mock_redis.get.return_value = cached.encode()

    with (
        patch("app.db.get_async_redis", return_value=mock_redis),
    ):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == cached


@pytest.mark.asyncio
async def test_sign_pc_url_redis_read_failure_falls_through() -> None:
    """Redis read failure should fall through to API call."""
    from redis.exceptions import RedisError

    signed = "https://example.com/asset.tif?sv=fresh"
    mock_client, _ = _make_httpx_mock_client("get", {"href": signed})

    mock_redis = AsyncMock()
    mock_redis.get.side_effect = RedisError("connection lost")
    mock_redis.setex.return_value = None

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=mock_redis),
    ):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == signed


@pytest.mark.asyncio
async def test_sign_pc_url_redis_write_failure_still_returns() -> None:
    """Redis write failure should not prevent the signed URL from being returned."""
    from redis.exceptions import RedisError

    signed = "https://example.com/asset.tif?sv=fresh"
    mock_client, _ = _make_httpx_mock_client("get", {"href": signed})

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex.side_effect = RedisError("connection lost")

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=mock_redis),
    ):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == signed


# ── Spatial filtering ────────────────────────────────────────────────────────


# The 2026-08 geometry audit's first failing pair, captured verbatim from
# Planetary Computer: two Landsat 5 scenes of the same 1987-10-21 overpass
# over RiNo Art District, Denver (39.7690, -104.9800). WRS-2 footprints are
# rotated parallelograms, so path 033 / row 033's envelope reaches well north
# of the scene itself — its bbox contains RiNo, its footprint does not. The
# pipeline served this scene for RiNo's oldest timeline card. Row 032, the
# same overpass one row north at the same 0.0% cloud, does contain it.
_RINO = {"lat": 39.7690, "lng": -104.9800}

_LANDSAT_1987_ROW033 = {
    "id": "LT05_L2SP_033033_19871021_02_T1",
    "bbox": [-105.9983, 37.9052, -103.2388, 39.8386],
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-105.4388023, 39.8278263],
                [-105.9103781, 38.2385054],
                [-103.8334187, 37.9312614],
                [-103.3201571, 39.517015],
                [-105.4388023, 39.8278263],
            ]
        ],
    },
    "properties": {"datetime": "1987-10-21T17:05:15.359075Z", "eo:cloud_cover": 0.0},
}

_LANDSAT_1987_ROW032 = {
    "id": "LT05_L2SP_033032_19871021_02_T1",
    "bbox": [-105.565, 39.3382, -102.7497, 41.2793],
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-105.0023878, 41.2675649],
                [-105.487187, 39.6795067],
                [-103.3693913, 39.3663488],
                [-102.836767, 40.9481093],
                [-105.0023878, 41.2675649],
            ]
        ],
    },
    "properties": {"datetime": "1987-10-21T17:04:51.302075Z", "eo:cloud_cover": 0.0},
}


def test_filter_rejects_item_whose_bbox_contains_but_footprint_excludes() -> None:
    """The defect itself: a covering envelope over a non-covering footprint."""
    from app.services.stac import filter_items_containing_point

    bbox = _LANDSAT_1987_ROW033["bbox"]
    assert bbox[0] <= _RINO["lng"] <= bbox[2] and bbox[1] <= _RINO["lat"] <= bbox[3], (
        "fixture must be one the old bbox test admitted, or it proves nothing"
    )

    kept = filter_items_containing_point([_LANDSAT_1987_ROW033], **_RINO)
    assert kept == []


def test_filter_keeps_item_whose_footprint_contains_the_point() -> None:
    """The same overpass one WRS-2 row north does cover RiNo, and is kept."""
    from app.services.stac import filter_items_containing_point

    kept = filter_items_containing_point([_LANDSAT_1987_ROW033, _LANDSAT_1987_ROW032], **_RINO)
    assert [i["id"] for i in kept] == ["LT05_L2SP_033032_19871021_02_T1"]


def test_filter_falls_back_to_bbox_when_geometry_is_absent() -> None:
    """No geometry is not evidence of no coverage — never reject on that alone."""
    from app.services.stac import filter_items_containing_point

    no_geometry = {k: v for k, v in _LANDSAT_1987_ROW033.items() if k != "geometry"}
    kept = filter_items_containing_point([no_geometry], **_RINO)
    assert [i["id"] for i in kept] == ["LT05_L2SP_033033_19871021_02_T1"]

    null_geometry = {**_LANDSAT_1987_ROW033, "geometry": None}
    assert len(filter_items_containing_point([null_geometry], **_RINO)) == 1


def test_filter_items_containing_point_keeps_matching() -> None:
    from app.services.stac import filter_items_containing_point

    items = [
        {"id": "covers", "bbox": [-105.0, 39.0, -104.0, 40.0]},
        {"id": "outside", "bbox": [-100.0, 35.0, -99.0, 36.0]},
        {"id": "no-bbox"},
    ]
    result = filter_items_containing_point(items, lat=39.5, lng=-104.5)
    ids = [i["id"] for i in result]
    assert "covers" in ids
    assert "outside" not in ids
    assert "no-bbox" in ids  # items without bbox are kept


def test_filter_items_intersecting_bbox_keeps_overlap() -> None:
    from app.services.stac import filter_items_intersecting_bbox

    viewport = (-105.0, 39.0, -104.0, 40.0)
    items = [
        {"id": "overlap", "bbox": [-104.5, 39.5, -103.0, 40.5]},
        {"id": "disjoint", "bbox": [-100.0, 35.0, -99.0, 36.0]},
        {"id": "no-bbox"},
    ]
    result = filter_items_intersecting_bbox(items, viewport)
    ids = [i["id"] for i in result]
    assert "overlap" in ids
    assert "disjoint" not in ids
    assert "no-bbox" in ids


def test_bbox_intersection_area_no_overlap() -> None:
    from app.services.stac import _bbox_intersection_area

    a = (-105.0, 39.0, -104.0, 40.0)
    b = (-100.0, 35.0, -99.0, 36.0)
    assert _bbox_intersection_area(a, b) == 0.0


def test_bbox_intersection_area_partial_overlap() -> None:
    from app.services.stac import _bbox_intersection_area

    a = (-105.0, 39.0, -104.0, 40.0)
    b = (-104.5, 39.5, -103.5, 40.5)
    area = _bbox_intersection_area(a, b)
    assert area > 0
    assert area == pytest.approx(0.5 * 0.5, rel=1e-6)


# ── extract_bbox_wkt ─────────────────────────────────────────────────────────


def test_extract_bbox_wkt_valid() -> None:
    from app.services.stac import extract_bbox_wkt

    item = {"bbox": [-105.0, 39.0, -104.0, 40.0]}
    wkt = extract_bbox_wkt(item)
    assert wkt is not None
    assert "POLYGON" in wkt
    assert "SRID=4326" in wkt


def test_extract_bbox_wkt_missing() -> None:
    from app.services.stac import extract_bbox_wkt

    assert extract_bbox_wkt({}) is None
    assert extract_bbox_wkt({"bbox": None}) is None
    assert extract_bbox_wkt({"bbox": [1, 2]}) is None


# ── extract_capture_date ─────────────────────────────────────────────────────


def test_extract_capture_date() -> None:
    from app.services.stac import extract_capture_date

    item = {"properties": {"datetime": "2021-07-15T10:30:00Z"}}
    d = extract_capture_date(item)
    assert d == date(2021, 7, 15)


# ── search_stac pagination ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_stac_follows_next_link() -> None:
    """search_stac should follow next links to paginate results."""
    from unittest.mock import MagicMock as SyncMock

    page1 = {
        "features": [{"id": "item-1"}],
        "links": [
            {"rel": "next", "href": "https://planetarycomputer.microsoft.com/api/stac/v1/page2"}
        ],
    }
    page2 = {
        "features": [{"id": "item-2"}],
        "links": [],
    }

    mock_resp_1 = SyncMock()
    mock_resp_1.raise_for_status = SyncMock()
    mock_resp_1.json = SyncMock(return_value=page1)

    mock_resp_2 = SyncMock()
    mock_resp_2.raise_for_status = SyncMock()
    mock_resp_2.json = SyncMock(return_value=page2)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp_1)
    mock_client.get = AsyncMock(return_value=mock_resp_2)

    with patch("app.services.stac._get_search_client", return_value=mock_client):
        items = await search_stac(
            collection="naip",
            bbox=(-105.0, 39.7, -104.9, 39.8),
            datetime_range="2020-01-01/2021-12-31",
            max_items=10,
        )

    assert len(items) == 2
    assert items[0]["id"] == "item-1"
    assert items[1]["id"] == "item-2"
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_search_stac_reposts_post_next_link() -> None:
    """Planetary Computer's next link is method=POST with the continuation
    token in the body — it must be re-POSTed, not fetched with GET (which
    would run an unfiltered default search)."""
    from unittest.mock import MagicMock as SyncMock

    page1 = {
        "features": [{"id": "item-1"}],
        "links": [
            {
                "rel": "next",
                "method": "POST",
                "href": "https://planetarycomputer.microsoft.com/api/stac/v1/search",
                "body": {
                    "collections": ["naip"],
                    "limit": 10,
                    "token": "next:naip:item-1",
                },
            }
        ],
    }
    page2 = {"features": [{"id": "item-2"}], "links": []}
    pages = iter([page1, page2])

    def _make_resp(*args: object, **kwargs: object) -> SyncMock:
        resp = SyncMock()
        resp.raise_for_status = SyncMock()
        resp.json = SyncMock(return_value=next(pages))
        return resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=_make_resp)
    mock_client.get = AsyncMock()

    with patch("app.services.stac._get_search_client", return_value=mock_client):
        items = await search_stac(
            collection="naip",
            bbox=(-105.0, 39.7, -104.9, 39.8),
            datetime_range="2020-01-01/2021-12-31",
            max_items=10,
        )

    assert [i["id"] for i in items] == ["item-1", "item-2"]
    mock_client.get.assert_not_called()
    assert mock_client.post.call_count == 2
    second_payload = mock_client.post.call_args_list[1].kwargs["json"]
    assert second_payload["token"] == "next:naip:item-1"


@pytest.mark.asyncio
async def test_search_stac_caps_at_max_items() -> None:
    """search_stac should not return more items than max_items."""
    mock_client, _ = _make_httpx_mock_client(
        "post",
        {
            "features": [{"id": f"item-{i}"} for i in range(5)],
            "links": [],
        },
    )

    with patch("app.services.stac._get_search_client", return_value=mock_client):
        items = await search_stac(
            collection="naip",
            bbox=(-105.0, 39.7, -104.9, 39.8),
            datetime_range="2020-01-01/2021-12-31",
            max_items=3,
        )

    assert len(items) == 3


# ── validate_landsat_item ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_landsat_item_success() -> None:
    from app.services.stac import validate_landsat_item

    item = {
        "id": "LC08_TEST",
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif"}
        },
    }

    mock_head_resp = MagicMock()
    mock_head_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=mock_head_resp)

    with (
        patch(
            "app.services.stac.sign_pc_url",
            new_callable=AsyncMock,
            return_value="https://signed.example.com/red.tif",
        ),
        patch("app.services.stac._get_search_client", return_value=mock_client),
    ):
        result = await validate_landsat_item(item)

    assert result is True


@pytest.mark.asyncio
async def test_validate_landsat_item_missing_red_band() -> None:
    from app.services.stac import validate_landsat_item

    item = {
        "id": "LC08_TEST",
        "assets": {
            "green": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/green.tif"}
        },
    }
    result = await validate_landsat_item(item)
    assert result is False


@pytest.mark.asyncio
async def test_validate_landsat_item_sign_failure() -> None:
    from app.services.stac import validate_landsat_item

    item = {
        "id": "LC08_TEST",
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif"}
        },
    }

    with patch(
        "app.services.stac.sign_pc_url",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("sign failed"),
    ):
        result = await validate_landsat_item(item)

    assert result is False


@pytest.mark.asyncio
async def test_validate_landsat_item_head_returns_403() -> None:
    from app.services.stac import validate_landsat_item

    item = {
        "id": "LC08_TEST",
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif"}
        },
    }

    mock_head_resp = MagicMock()
    mock_head_resp.status_code = 403

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=mock_head_resp)

    with (
        patch(
            "app.services.stac.sign_pc_url",
            new_callable=AsyncMock,
            return_value="https://signed.example.com/red.tif",
        ),
        patch("app.services.stac._get_search_client", return_value=mock_client),
    ):
        result = await validate_landsat_item(item)

    assert result is False


# ── validate_landsat_selection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_landsat_selection_swaps_fallback() -> None:
    from app.services.stac import validate_landsat_selection

    bad_item = {
        "id": "bad",
        "properties": {"datetime": "2020-06-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/bad.tif"}
        },
    }
    good_fallback = {
        "id": "good",
        "properties": {"datetime": "2020-07-01T00:00:00Z", "eo:cloud_cover": 10.0},
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/good.tif"}
        },
    }

    selected_groups = [[bad_item]]
    raw_items = [bad_item, good_fallback]

    call_count = [0]

    async def mock_validate(item):
        call_count[0] += 1
        return None if item["id"] != "bad" else "validation_failed"

    with patch("app.services.stac.check_landsat_item", side_effect=mock_validate):
        result = await validate_landsat_selection(selected_groups, raw_items)

    assert len(result) == 1
    assert result[0][0]["id"] == "good"


@pytest.mark.asyncio
async def test_validate_landsat_selection_drops_year_with_no_valid() -> None:
    from app.services.stac import validate_landsat_selection

    bad_item = {
        "id": "bad",
        "properties": {"datetime": "2020-06-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {
            "red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/bad.tif"}
        },
    }

    selected_groups = [[bad_item]]
    raw_items = [bad_item]

    async def always_invalid(item):
        return "validation_failed"

    with patch("app.services.stac.check_landsat_item", side_effect=always_invalid):
        result = await validate_landsat_selection(selected_groups, raw_items)

    assert len(result) == 0


# ── validate_sentinel_selection (the Landsat twin) ───────────────────────────


def _s2_item(item_id: str, dt: str, cloud: float) -> dict:
    return {
        "id": item_id,
        "properties": {"datetime": dt, "eo:cloud_cover": cloud},
        "assets": {
            "visual": {
                "href": f"https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/{item_id}.tif"
            }
        },
    }


@pytest.mark.asyncio
async def test_validate_sentinel_selection_swaps_same_year_fallback() -> None:
    from app.services.stac import validate_sentinel_selection

    bad = _s2_item("bad", "2020-07-01T00:00:00Z", 5.0)
    good = _s2_item("good", "2020-08-01T00:00:00Z", 10.0)

    async def mock_validate(item):
        return None if item["id"] != "bad" else "validation_failed"

    with patch("app.services.stac.check_sentinel_item", side_effect=mock_validate):
        result = await validate_sentinel_selection([[bad]], [bad, good])

    assert [g[0]["id"] for g in result] == ["good"]


@pytest.mark.asyncio
async def test_validate_sentinel_selection_reaches_across_quarters() -> None:
    """The fallback walk is scoped to the year S2 selects on.

    Delete-the-fix guard for the validator half: under the old quarter key
    this Q4 candidate was invisible to a failed Q3 pick and the group was
    dropped. That is the shape of G2 — Rodanthe kept a non-covering July
    granule while its servable October sibling sat in the next quarter.
    """
    from app.services.stac import validate_sentinel_selection

    bad = _s2_item("bad", "2020-07-01T00:00:00Z", 5.0)
    other_quarter = _s2_item("q4", "2020-11-01T00:00:00Z", 1.0)

    async def mock_validate(item):
        return None if item["id"] != "bad" else "validation_failed"

    with patch("app.services.stac.check_sentinel_item", side_effect=mock_validate):
        result = await validate_sentinel_selection([[bad]], [bad, other_quarter])

    assert [g[0]["id"] for g in result] == ["q4"]


@pytest.mark.asyncio
async def test_validate_sentinel_selection_ignores_other_years() -> None:
    """The walk stops at the year boundary — a 2021 scene cannot rescue 2020."""
    from app.services.stac import validate_sentinel_selection

    bad = _s2_item("bad", "2020-07-01T00:00:00Z", 5.0)
    other_year = _s2_item("y2021", "2021-11-01T00:00:00Z", 1.0)

    async def mock_validate(item):
        return None if item["id"] != "bad" else "validation_failed"

    with patch("app.services.stac.check_sentinel_item", side_effect=mock_validate):
        result = await validate_sentinel_selection([[bad]], [bad, other_year])

    assert result == []


@pytest.mark.asyncio
async def test_validate_sentinel_selection_drops_year_with_no_valid() -> None:
    from app.services.stac import validate_sentinel_selection

    bad = _s2_item("bad", "2020-07-01T00:00:00Z", 5.0)

    async def always_invalid(item):
        return "validation_failed"

    with patch("app.services.stac.check_sentinel_item", side_effect=always_invalid):
        result = await validate_sentinel_selection([[bad]], [bad])

    assert result == []


@pytest.mark.asyncio
async def test_validate_sentinel_selection_tolerates_empty_group() -> None:
    from app.services.stac import validate_sentinel_selection

    good = _s2_item("good", "2020-07-01T00:00:00Z", 5.0)

    async def always_valid(item):
        return None

    with patch("app.services.stac.check_sentinel_item", side_effect=always_valid):
        result = await validate_sentinel_selection([[], [good]], [good])

    assert [g[0]["id"] for g in result] == ["good"]


@pytest.mark.asyncio
async def test_validate_sentinel_item_checks_the_visual_asset() -> None:
    """S2 tiles render from `visual`; a missing one is not servable."""
    from app.services.stac import validate_sentinel_item

    head_resp = MagicMock()
    head_resp.status_code = 200
    search_client = AsyncMock()
    search_client.head = AsyncMock(return_value=head_resp)

    with (
        patch(
            "app.services.stac.sign_pc_url",
            new_callable=AsyncMock,
            return_value="https://signed.example.com/visual.tif",
        ),
        patch("app.services.stac._get_search_client", return_value=search_client),
    ):
        assert await validate_sentinel_item(_s2_item("ok", "2020-07-01T00:00:00Z", 1.0)) is True

    no_visual = {
        "id": "x",
        "assets": {
            "B04": {"href": "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/B04.tif"}
        },
    }
    assert await validate_sentinel_item(no_visual) is False


# ── close_clients ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_clients() -> None:
    import asyncio

    import app.services.stac as stac_mod

    mock_search = AsyncMock()
    mock_sign = AsyncMock()

    loop = asyncio.get_running_loop()
    stac_mod._search_clients[loop] = mock_search
    stac_mod._sign_clients[loop] = mock_sign

    await stac_mod.close_clients()

    mock_search.aclose.assert_called_once()
    mock_sign.aclose.assert_called_once()
    assert loop not in stac_mod._search_clients
    assert loop not in stac_mod._sign_clients


def test_search_client_is_per_event_loop() -> None:
    """Concurrent Celery tasks each run their own loop — they must never
    share an httpx client, and closing one task's client must not touch
    another's."""
    import asyncio

    import app.services.stac as stac_mod

    async def grab() -> object:
        return stac_mod._get_search_client()

    c1 = asyncio.run(grab())
    c2 = asyncio.run(grab())
    assert c1 is not c2

    async def cleanup() -> None:
        await c1.aclose()
        await c2.aclose()

    asyncio.run(cleanup())
    stac_mod._search_clients.clear()


# ── Landsat LE07 deprioritization ────────────────────────────────────────────


def test_select_landsat_prefers_non_le07() -> None:
    """LE07 items should only be used as fallback when no other items exist for a year."""
    items = [
        {
            "id": "LE07_2005_08_01",
            "properties": {"datetime": "2005-08-01T00:00:00Z", "eo:cloud_cover": 3.0},
        },
        {
            "id": "LT05_2005_07_15",
            "properties": {"datetime": "2005-07-15T00:00:00Z", "eo:cloud_cover": 8.0},
        },
    ]
    groups = select_landsat_items(items)
    assert len(groups) == 1
    assert groups[0][0]["id"] == "LT05_2005_07_15"


@pytest.mark.asyncio
async def test_validate_landsat_selection_tolerates_empty_group() -> None:
    """An empty selected group must not fail the whole Landsat source.

    The gather comprehension filters empty groups; zipping the *unfiltered*
    list against the results raised ValueError under strict=True the first
    time any selector emitted one.
    """
    from app.services.stac import validate_landsat_selection

    good_item = {
        "id": "good",
        "properties": {"datetime": "2020-06-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {"red": {"href": "https://planetarycomputer.microsoft.com/api/data/v1/good.tif"}},
    }

    selected_groups: list[list[dict[str, object]]] = [[], [good_item]]

    async def mock_validate(item: dict[str, object]) -> str | None:
        return None

    with patch("app.services.stac.check_landsat_item", side_effect=mock_validate):
        result = await validate_landsat_selection(selected_groups, [good_item])

    assert len(result) == 1
    assert result[0][0]["id"] == "good"


# ── SAS signing: 429 throttling ──────────────────────────────────────────────


def _sign_response(status: int, href: str = "", retry_after: str | None = None) -> MagicMock:
    """Build a mock SAS signing response with a real integer status_code."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"retry-after": retry_after} if retry_after else {}
    resp.json = MagicMock(return_value={"href": href})
    if status >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(f"{status}", request=MagicMock(), response=resp)
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _cache_miss_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get.return_value = None
    redis.setex.return_value = None
    return redis


@pytest.mark.asyncio
async def test_sign_pc_url_retries_429_then_succeeds() -> None:
    """Two 429s followed by a 200 should return the signed href, not raise."""
    signed = "https://example.com/red.tif?sv=signed"
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[
            _sign_response(429),
            _sign_response(429),
            _sign_response(200, signed),
        ]
    )

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        result = await sign_pc_url("https://example.com/red.tif")

    assert result == signed
    assert mock_client.get.await_count == 3
    # Exponential: 1s then 2s
    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_sign_pc_url_honours_retry_after_header() -> None:
    """A Retry-After header takes precedence over the exponential delay."""
    signed = "https://example.com/red.tif?sv=signed"
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[_sign_response(429, retry_after="7"), _sign_response(200, signed)]
    )

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        result = await sign_pc_url("https://example.com/red.tif")

    assert result == signed
    assert sleep.await_args_list[0].args[0] == 7.0


@pytest.mark.asyncio
async def test_sign_pc_url_raises_after_exhausting_429_retries() -> None:
    """Persistent 429s still surface as an HTTPStatusError once attempts run out."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_sign_response(429))

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await sign_pc_url("https://example.com/red.tif")


@pytest.mark.asyncio
async def test_landsat_item_validates_through_429_burst() -> None:
    """A 429 burst during signing must not fail the item over to a fallback.

    This is the production defect: 21 consecutive signing 429s dropped 20 of
    43 Landsat years because a rate-limit reply was read as "asset broken".
    """
    from app.services.stac import validate_landsat_selection

    signed = "https://example.com/red.tif?sv=signed"
    sign_client = AsyncMock()
    sign_client.get = AsyncMock(
        side_effect=[
            _sign_response(429),
            _sign_response(429),
            _sign_response(200, signed),
        ]
    )

    head_resp = MagicMock()
    head_resp.status_code = 200
    search_client = AsyncMock()
    search_client.head = AsyncMock(return_value=head_resp)

    selected = {
        "id": "selected",
        "properties": {"datetime": "1994-06-01T00:00:00Z", "eo:cloud_cover": 5},
        "assets": {"red": {"href": "https://planetarycomputer.microsoft.com/api/data/v1/red.tif"}},
    }
    fallback = {
        "id": "fallback",
        "properties": {"datetime": "1994-08-01T00:00:00Z", "eo:cloud_cover": 40},
        "assets": {"red": {"href": "https://planetarycomputer.microsoft.com/api/data/v1/red2.tif"}},
    }

    with (
        patch("app.services.stac._get_sign_client", return_value=sign_client),
        patch("app.services.stac._get_search_client", return_value=search_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await validate_landsat_selection([[selected]], [selected, fallback])

    assert len(result) == 1
    assert result[0][0]["id"] == "selected", "should retry, not fail over to the fallback"


@pytest.mark.asyncio
async def test_sign_pc_url_caps_concurrency_at_semaphore_limit() -> None:
    """No more than PC_SIGNING_CONCURRENCY signing calls may be in flight."""
    import asyncio as _asyncio

    from app.services import stac as stac_module

    limit = 4
    in_flight = 0
    peak = 0

    async def slow_get(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await _asyncio.sleep(0.01)
            return _sign_response(200, "https://example.com/signed.tif")
        finally:
            in_flight -= 1

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=slow_get)

    settings = MagicMock()
    settings.pc_signing_concurrency = limit
    settings.pc_signing_attempts = 4

    stac_module._sign_semaphores.clear()
    try:
        with (
            patch("app.services.stac._get_sign_client", return_value=mock_client),
            patch("app.config.get_settings", return_value=settings),
            patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        ):
            await _asyncio.gather(
                *(sign_pc_url(f"https://example.com/asset-{i}.tif") for i in range(20))
            )
    finally:
        stac_module._sign_semaphores.clear()

    assert mock_client.get.await_count == 20
    assert peak <= limit, f"{peak} concurrent signing calls exceeded the cap of {limit}"
    assert peak > 1, "sanity: the gather should actually have run calls in parallel"


# ── SAS signing: wait budgets by context ─────────────────────────────────────


def _token_response(status: int, token: str = "", retry_after: str | None = None) -> MagicMock:
    """Mock a container-token response (or a 429 from that endpoint)."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"retry-after": retry_after} if retry_after else {}
    resp.json = MagicMock(return_value={"token": token, "msft:expiry": "2026-08-12T03:50:01Z"})
    if status >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(f"{status}", request=MagicMock(), response=resp)
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_request_context_gives_up_rather_than_sleeping_60s() -> None:
    """A 429 with Retry-After: 60 must raise inside the request budget.

    The tile path's end-to-end budget is ~30 s, so honouring a 60 s
    Retry-After there converts every 429 into a client timeout and an
    unexplained 502. Production, 2026-08-12: a 54 s backoff mid-storm.
    """
    from app.services.stac import SIGN_WAIT_REQUEST

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_token_response(429, retry_after="60"))

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(httpx.HTTPStatusError),
    ):
        await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif",
            wait_budget=SIGN_WAIT_REQUEST,
        )

    assert sleep.await_count == 0, "a 60s Retry-After overshoots the 2s request budget"
    assert mock_client.get.await_count == 1, "one attempt, then raise — no long backoff"


@pytest.mark.asyncio
async def test_request_context_still_takes_a_short_retry() -> None:
    """Within budget, the request profile does retry — it is fast, not brittle."""
    from app.services.stac import SIGN_WAIT_REQUEST

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[_token_response(429, retry_after="1"), _token_response(200, "sv=tok")]
    )

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        result = await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/red.tif",
            wait_budget=SIGN_WAIT_REQUEST,
        )

    assert result.endswith("?sv=tok")
    assert [c.args[0] for c in sleep.await_args_list] == [1.0]


@pytest.mark.asyncio
async def test_batch_context_still_honours_a_long_retry_after() -> None:
    """The worker's profile is unchanged: waiting beats dropping the year."""
    from app.services.stac import SIGN_WAIT_BATCH

    signed = "https://example.com/red.tif?sv=signed"
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[_sign_response(429, retry_after="54"), _sign_response(200, signed)]
    )

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
        patch("app.services.stac.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        result = await sign_pc_url("https://example.com/red.tif", wait_budget=SIGN_WAIT_BATCH)

    assert result == signed
    assert [c.args[0] for c in sleep.await_args_list] == [54.0]


# ── SAS signing: container tokens ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blob_urls_sign_from_one_container_token() -> None:
    """Every asset in a container is signed by a single token request."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_token_response(200, "se=2026&sig=abc"))

    redis = _cache_miss_redis()
    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=redis),
    ):
        first = await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/red.tif"
        )
        # Second call reads the token Redis cached on the first.
        redis.get.return_value = b"se=2026&sig=abc"
        second = await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/green.tif"
        )

    assert first.endswith("red.tif?se=2026&sig=abc")
    assert second.endswith("green.tif?se=2026&sig=abc")
    assert mock_client.get.await_count == 1, "the second asset must reuse the container token"
    assert (
        "/api/sas/v1/token/landsateuwest/landsat-c2" in mock_client.get.await_args_list[0].args[0]
    )


@pytest.mark.asyncio
async def test_non_blob_urls_still_use_per_url_signing() -> None:
    """USGS S3 and data-API hrefs have no container token; sign them per URL."""
    from app.services.stac import PC_SIGN_URL

    signed = "https://example.com/asset.tif?sv=signed"
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_sign_response(200, signed))

    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
    ):
        result = await sign_pc_url("https://example.com/asset.tif")

    assert result == signed
    assert mock_client.get.await_args_list[0].args[0] == PC_SIGN_URL


@pytest.mark.asyncio
async def test_container_token_mint_logs_once_per_pc_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A mint logs a greppable line; a warm cache read does not."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        return_value=_token_response(200, "se=2026-08-12T05:00:40Z&sr=c&sig=abc")
    )

    redis = _cache_miss_redis()
    with (
        caplog.at_level(logging.INFO, logger="app.services.stac"),
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=redis),
    ):
        await sign_pc_url("https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/red.tif")
        mints = [r for r in caplog.records if "SAS container token minted" in r.getMessage()]
        assert len(mints) == 1
        assert "container=landsateuwest/landsat-c2" in mints[0].getMessage()
        assert "se=2026-08-12T05:00:40Z" in mints[0].getMessage()

        caplog.clear()
        redis.get.return_value = b"se=2026-08-12T05:00:40Z&sr=c&sig=abc"
        await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/green.tif"
        )
        assert "SAS container token minted" not in caplog.text


# ── SAS signing: single-flight on a cold container token (G7) ────────────────

# (account, container, one band href in it) for two of the three containers the
# 2026-08-12 baseline saw minting: sentinel2-l2 fanned out to 13 tokens in one
# cold window, landsat-c2 to 6. The fix is per-container, not Landsat-specific.
_SINGLE_FLIGHT_CONTAINERS = [
    (
        "landsateuwest/landsat-c2",
        "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/{band}.tif",
    ),
    (
        "sentinel2l2a01/sentinel2-l2",
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/tiles/{band}.tif",
    ),
]


def _slow_token_client(token: str) -> AsyncMock:
    """A token endpoint that takes a tick to answer, so callers really overlap.

    The production fan-out window is the mint latency (670–830 ms observed):
    every caller arriving inside it finds no cached token. An instant mock
    would close that window before the second caller ran and pass with or
    without the fix.
    """

    async def _get(*_args: object, **_kwargs: object) -> MagicMock:
        await asyncio.sleep(0.05)
        return _token_response(200, token)

    client = AsyncMock()
    client.get = AsyncMock(side_effect=_get)
    return client


@pytest.mark.parametrize(("container", "href"), _SINGLE_FLIGHT_CONTAINERS)
@pytest.mark.asyncio
async def test_concurrent_misses_mint_one_container_token(
    container: str, href: str, caplog: pytest.LogCaptureFixture
) -> None:
    """N concurrent requests on a cold container mint exactly one token.

    Delete the single-flight in ``_container_token`` and this fails at 8 PC
    calls and 8 mint log lines instead of 1 — the 6-mint production signature
    of BOUNDARY-BASELINE.md §3, in a harness.
    """
    token = "se=2026-08-12T21:02:06Z&sr=c&sig=abc"
    client = _slow_token_client(token)

    with (
        caplog.at_level(logging.INFO, logger="app.services.stac"),
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
    ):
        signed = await asyncio.gather(*(sign_pc_url(href.format(band=f"b{i}")) for i in range(8)))

    assert all(u.endswith(f"?{token}") for u in signed)
    assert client.get.await_count == 1, "concurrent misses must coalesce onto one mint"
    mints = [r for r in caplog.records if "SAS container token minted" in r.getMessage()]
    assert len(mints) == 1
    assert f"container={container}" in mints[0].getMessage()


@pytest.mark.parametrize(("container", "href"), _SINGLE_FLIGHT_CONTAINERS)
@pytest.mark.asyncio
async def test_one_requests_band_signings_mint_one_container_token(
    container: str, href: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The 19:56Z shape: one request's three band signings race each other.

    A single ``/stac`` callback gathers red/green/blue and minted three tokens
    on 2026-08-12 — a request concurrent with itself. This is why the seam is
    inside ``_container_token`` and not above the gather.
    """
    token = "se=2026-08-12T21:02:06Z&sr=c&sig=abc"
    client = _slow_token_client(token)

    with (
        caplog.at_level(logging.INFO, logger="app.services.stac"),
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
    ):
        signed = await asyncio.gather(
            *(sign_pc_url(href.format(band=b)) for b in ("red", "green", "blue"))
        )

    assert len({u.split("?")[1] for u in signed}) == 1, "all three bands carry one token"
    assert client.get.await_count == 1
    mints = [r for r in caplog.records if "SAS container token minted" in r.getMessage()]
    assert len(mints) == 1
    assert f"container={container}" in mints[0].getMessage()


@pytest.mark.asyncio
async def test_single_flight_is_per_container() -> None:
    """Two containers missing at once still mint one token each, not one total."""
    client = _slow_token_client("se=2026-08-12T21:02:06Z&sr=c&sig=abc")

    with (
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
    ):
        await asyncio.gather(
            *(sign_pc_url(href.format(band="red")) for _, href in _SINGLE_FLIGHT_CONTAINERS)
        )

    assert client.get.await_count == len(_SINGLE_FLIGHT_CONTAINERS)


@pytest.mark.asyncio
async def test_failed_mint_does_not_wedge_the_container() -> None:
    """A mint that raises propagates to every follower and clears the flight."""
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=[
            httpx.ConnectError("signer down"),
            _token_response(200, "se=2026-08-12T21:02:06Z&sr=c&sig=abc"),
        ]
    )
    href = "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/{band}.tif"

    with (
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=_cache_miss_redis()),
    ):
        results = await asyncio.gather(
            *(sign_pc_url(href.format(band=b)) for b in ("red", "green")),
            return_exceptions=True,
        )
        assert all(isinstance(r, httpx.ConnectError) for r in results)

        # The next caller mints afresh rather than awaiting a dead future.
        retried = await sign_pc_url(href.format(band="blue"))

    assert retried.endswith("?se=2026-08-12T21:02:06Z&sr=c&sig=abc")


# ── SAS signing: container-token cache TTL tracks the token's own expiry ─────


def _se(seconds_from_now: float) -> str:
    stamp = datetime.fromtimestamp(time.time() + seconds_from_now, UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.asyncio
async def test_container_token_cached_until_shortly_before_its_expiry() -> None:
    """The TTL is the token's remaining life less the margin, never more."""
    from app.services.stac import _SAS_TOKEN_MARGIN_S

    token = f"se={_se(45 * 60)}&sr=c&sig=abc"
    client = AsyncMock()
    client.get = AsyncMock(return_value=_token_response(200, token))
    redis = _cache_miss_redis()

    with (
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=redis),
    ):
        await sign_pc_url("https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/red.tif")

    _key, ttl, _value = redis.setex.await_args.args
    # A full-life token: ~45 min less the margin, and well past the old fixed
    # 1200 s — this is the 2.25× cadence reduction, asserted.
    assert 45 * 60 - _SAS_TOKEN_MARGIN_S - 5 <= ttl <= 45 * 60 - _SAS_TOKEN_MARGIN_S
    assert ttl > 1200


@pytest.mark.asyncio
async def test_container_token_ttl_never_outlives_the_token() -> None:
    """A short-lived token is cached for less, not for the fixed span."""
    from app.services.stac import _SAS_TOKEN_MARGIN_S, _container_token_ttl

    for remaining in (45 * 60, 20 * 60, 10 * 60, _SAS_TOKEN_MARGIN_S + 60):
        ttl = _container_token_ttl(f"se={_se(remaining)}&sr=c&sig=abc")
        assert ttl <= remaining - _SAS_TOKEN_MARGIN_S
        assert ttl > 0


@pytest.mark.asyncio
async def test_expiring_container_token_is_not_cached() -> None:
    """A token with less than the margin left is used once and not cached.

    Caching it would hand the next caller a credential that can die inside a
    tile render — the failure cf0df2b exists to prevent.
    """
    token = f"se={_se(60)}&sr=c&sig=abc"
    client = AsyncMock()
    client.get = AsyncMock(return_value=_token_response(200, token))
    redis = _cache_miss_redis()

    with (
        patch("app.services.stac._get_sign_client", return_value=client),
        patch("app.db.get_async_redis", return_value=redis),
    ):
        signed = await sign_pc_url(
            "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/red.tif"
        )

    assert signed.endswith(f"?{token}")
    redis.setex.assert_not_called()


def test_container_token_ttl_falls_back_when_se_is_unusable() -> None:
    """An absent or unparseable ``se`` keeps the inherited fixed TTL."""
    from app.services.stac import _SAS_CACHE_TTL, _container_token_ttl

    assert _container_token_ttl("sr=c&sig=abc") == _SAS_CACHE_TTL
    assert _container_token_ttl("se=not-a-date&sr=c&sig=abc") == _SAS_CACHE_TTL


def test_blob_container_parses_account_and_container() -> None:
    from app.services.stac import _blob_container

    assert _blob_container(
        "https://naipeuwest.blob.core.windows.net/naip/v002/ny/m_4007309.tif"
    ) == ("naipeuwest", "naip")
    assert _blob_container("https://prd-tnm.s3.amazonaws.com/topo.tif") is None
    assert _blob_container("https://planetarycomputer.microsoft.com/api/data/v1/x") is None


# ── SAS token expiry ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_container_token_expiry_reads_se_from_cached_token() -> None:
    """The expiry comes off the cached token — no signing call."""
    from app.services.stac import LANDSAT_BLOB_CONTAINER, container_token_expiry

    redis = AsyncMock()
    redis.get.return_value = b"st=2026-08-11T04:15:40Z&se=2026-08-12T05:00:40Z&sr=c&sig=abc"

    mock_client = AsyncMock()
    with (
        patch("app.services.stac._get_sign_client", return_value=mock_client),
        patch("app.db.get_async_redis", return_value=redis),
    ):
        expiry = await container_token_expiry(*LANDSAT_BLOB_CONTAINER, wait_budget=2.0)

    assert expiry == "2026-08-12T05:00:40Z"
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_container_token_expiry_none_when_token_lacks_se() -> None:
    """A token with no expiry field yields None rather than raising."""
    from app.services.stac import LANDSAT_BLOB_CONTAINER, container_token_expiry

    redis = AsyncMock()
    redis.get.return_value = b"st=2026-08-11T04:15:40Z&sr=c&sig=abc"

    with patch("app.db.get_async_redis", return_value=redis):
        expiry = await container_token_expiry(*LANDSAT_BLOB_CONTAINER, wait_budget=2.0)

    assert expiry is None


def test_token_expiry_seconds_parses_signed_url() -> None:
    from app.services.stac import token_expiry_seconds

    epoch = token_expiry_seconds("https://x.blob.core.windows.net/c/b.tif?se=2026-08-12T05:00:40Z")
    assert epoch == datetime(2026, 8, 12, 5, 0, 40, tzinfo=UTC).timestamp()
    assert token_expiry_seconds("https://x.blob.core.windows.net/c/b.tif") is None
    assert token_expiry_seconds("https://x.blob.core.windows.net/c/b.tif?se=not-a-date") is None


# ── NAIP point-coverage gate ─────────────────────────────────────────────────

# The three items Planetary Computer returns for NAIP 2023 over Midtown
# Manhattan, captured verbatim. Every one is a New Jersey quad, and none
# contains 350 5th Ave — there is no covering 2023 tile in the collection, so
# the viewport selector served a mosaic of the wrong state. Hudson Yards, half
# a mile west, *is* contained by nj_m_4007416_se: same year, same three
# candidates, opposite verdict. That is the whole gate in one fixture.
_NAIP_2023_4007309_SW = {
    "id": "nj_m_4007309_sw_18_030_20230820_20231019",
    "bbox": [-74.001268, 40.749189, -73.936174, 40.813311],
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-73.937188, 40.749189],
                [-73.936174, 40.812737],
                [-74.000316, 40.813311],
                [-74.001268, 40.749761],
                [-73.937188, 40.749189],
            ]
        ],
    },
    "properties": {"datetime": "2023-08-20T00:00:00Z"},
}

_NAIP_2023_4007416_SE = {
    "id": "nj_m_4007416_se_18_030_20230820_20231019",
    "bbox": [-74.063709, 40.749223, -73.998731, 40.813276],
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-73.999684, 40.749223],
                [-73.998731, 40.812738],
                [-74.062817, 40.813276],
                [-74.063709, 40.749761],
                [-73.999684, 40.749223],
            ]
        ],
    },
    "properties": {"datetime": "2023-08-20T00:00:00Z"},
}

_EMPIRE_STATE = {"lat": 40.7484, "lng": -73.9857}  # 350 5th Ave
_HUDSON_YARDS = {"lat": 40.7539, "lng": -74.0019}  # 500 W 33rd St


def test_naip_year_suppressed_when_no_tile_covers_the_point() -> None:
    """A mosaic can cover the viewport and still be the wrong place entirely."""
    from app.services.stac import filter_groups_containing_point

    mosaic = [_NAIP_2023_4007309_SW, _NAIP_2023_4007416_SE]
    covering, missing = filter_groups_containing_point([mosaic], **_EMPIRE_STATE)

    assert covering == [], "no 2023 tile contains 350 5th Ave — suppress the year"
    assert len(missing) == 1


def test_naip_year_kept_when_one_mosaic_tile_covers_the_point() -> None:
    """The same mosaic, half a mile west: one tile covers, so the year stays."""
    from app.services.stac import filter_groups_containing_point

    mosaic = [_NAIP_2023_4007309_SW, _NAIP_2023_4007416_SE]
    covering, missing = filter_groups_containing_point([mosaic], **_HUDSON_YARDS)

    assert len(covering) == 1, "the second tile contains Hudson Yards — this is the mosaic working"
    assert missing == []


# ── Outbound host allowlist (security audit P5) ─────────────────────────────


def test_allowed_upstream_hosts_match_production_rows() -> None:
    """Every host a stored or upstream-supplied URL may point at, and no other.

    The set was read from production on 2026-08-22 (REMEDIATION-1.md §4); a
    suffix match or a look-alike must not pass.
    """
    from app.services.stac import is_allowed_upstream_url

    for url in (
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/naip/items/x",
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2021/x.tif?st=a&sig=b",
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/x/TCI.tif",
        "https://landsateuwest.blob.core.windows.net/landsat-c2/level-2/x_SR_B4.TIF",
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/x.tif",
    ):
        assert is_allowed_upstream_url(url), url

    for url in (
        "https://evil.example.com/x.tif",
        "http://169.254.169.254/latest/meta-data/",
        "https://naipeuwest.blob.core.windows.net.evil.test/x.tif",
        "/etc/hostname",
        "",
    ):
        assert not is_allowed_upstream_url(url), url


@pytest.mark.asyncio
async def test_validate_asset_refuses_non_allowlisted_href() -> None:
    """An item whose band href names an unknown host is never signed or HEADed."""
    from app.services.stac import validate_landsat_item

    item = {"id": "LC08_TEST", "assets": {"red": {"href": "https://evil.example.com/red.tif"}}}
    mock_client = AsyncMock()

    with (
        patch("app.services.stac.sign_pc_url", new_callable=AsyncMock) as sign,
        patch("app.services.stac._get_search_client", return_value=mock_client),
    ):
        assert await validate_landsat_item(item) is False

    sign.assert_not_awaited()
    mock_client.head.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_stac_stops_at_non_allowlisted_next_link() -> None:
    """A next link pointing off Planetary Computer ends pagination instead of being fetched."""
    from unittest.mock import MagicMock as SyncMock

    page1 = {
        "features": [{"id": "item-1"}],
        "links": [{"rel": "next", "href": "https://evil.example.com/page2"}],
    }
    mock_resp = SyncMock()
    mock_resp.raise_for_status = SyncMock()
    mock_resp.json = SyncMock(return_value=page1)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock()

    with patch("app.services.stac._get_search_client", return_value=mock_client):
        items = await search_stac(
            collection="naip",
            bbox=(-105.0, 39.7, -104.9, 39.8),
            datetime_range="2020-01-01/2021-12-31",
            max_items=10,
        )

    assert [i["id"] for i in items] == ["item-1"]
    mock_client.get.assert_not_awaited()
    assert mock_client.post.await_count == 1
