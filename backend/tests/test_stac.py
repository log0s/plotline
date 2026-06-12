"""Tests for the STAC service — bounding box generation and item selection logic."""

from __future__ import annotations

from datetime import date
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


def test_select_sentinel_one_per_quarter() -> None:
    """select_sentinel_items returns one group per calendar quarter."""
    items = [
        _make_item("2020-01-10T00:00:00Z", cloud_cover=10.0),
        _make_item("2020-02-20T00:00:00Z", cloud_cover=5.0),  # Q1 — should win
        _make_item("2020-04-05T00:00:00Z", cloud_cover=8.0),  # Q2
        _make_item("2020-07-15T00:00:00Z", cloud_cover=15.0),  # Q3
    ]
    groups = select_sentinel_items(items)
    assert len(groups) == 3
    for g in groups:
        assert len(g) == 1


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
                "href": "https://example.com/red.tif",
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
        "assets": {"red": {"href": "https://example.com/red.tif"}},
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
        "links": [{"rel": "next", "href": "https://stac.example.com/page2"}],
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
                "href": "https://stac.example.com/search",
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
        "assets": {"red": {"href": "https://example.com/red.tif"}},
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

    item = {"id": "LC08_TEST", "assets": {"green": {"href": "https://example.com/green.tif"}}}
    result = await validate_landsat_item(item)
    assert result is False


@pytest.mark.asyncio
async def test_validate_landsat_item_sign_failure() -> None:
    from app.services.stac import validate_landsat_item

    item = {"id": "LC08_TEST", "assets": {"red": {"href": "https://example.com/red.tif"}}}

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

    item = {"id": "LC08_TEST", "assets": {"red": {"href": "https://example.com/red.tif"}}}

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
        "assets": {"red": {"href": "https://example.com/bad.tif"}},
    }
    good_fallback = {
        "id": "good",
        "properties": {"datetime": "2020-07-01T00:00:00Z", "eo:cloud_cover": 10.0},
        "assets": {"red": {"href": "https://example.com/good.tif"}},
    }

    selected_groups = [[bad_item]]
    raw_items = [bad_item, good_fallback]

    call_count = [0]

    async def mock_validate(item):
        call_count[0] += 1
        return item["id"] != "bad"

    with patch("app.services.stac.validate_landsat_item", side_effect=mock_validate):
        result = await validate_landsat_selection(selected_groups, raw_items)

    assert len(result) == 1
    assert result[0][0]["id"] == "good"


@pytest.mark.asyncio
async def test_validate_landsat_selection_drops_year_with_no_valid() -> None:
    from app.services.stac import validate_landsat_selection

    bad_item = {
        "id": "bad",
        "properties": {"datetime": "2020-06-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {"red": {"href": "https://example.com/bad.tif"}},
    }

    selected_groups = [[bad_item]]
    raw_items = [bad_item]

    async def always_invalid(item):
        return False

    with patch("app.services.stac.validate_landsat_item", side_effect=always_invalid):
        result = await validate_landsat_selection(selected_groups, raw_items)

    assert len(result) == 0


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
