"""Tests for the M4 per-year outcome ledger.

Three kinds of test live here:

* **group_key** round-trips, so the token the ledger stores and the token a
  heal builds are the same token.
* **Recorder semantics** — upsert, vocabulary, the reset that clears a
  redelivered request's rows.
* **Delete-the-fix** — one per recorder call site in the fetch loops. Each
  asserts a row that only that call can produce, so removing the call fails
  the test. The comment on each names the line to delete.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from app.services import usgs_topo as topo_service
from app.services import year_ledger
from app.services.imagery import (
    SELECTION_SCOPES,
    decode_group_key,
    encode_group_key,
)

from .conftest import seed_served_scene

# ── group_key encoding ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("scope", "sample", "expected"),
    [
        ("year", date(1993, 6, 15), "1993"),
        ("quarter", date(1993, 8, 2), "1993Q3"),
        ("decade", date(1963, 4, 1), "1960s"),
    ],
)
def test_group_key_encodes_as_documented(scope: str, sample: date, expected: str) -> None:
    assert encode_group_key(scope, sample) == expected


def test_every_selection_scope_round_trips() -> None:
    """Encode -> decode -> encode is the identity, for every scope that exists.

    SELECTION_SCOPES is the list of groupings the reconciler knows; a scope
    the ledger cannot encode is a scope whose rows nothing could target.
    """
    sample = date(1993, 8, 2)
    for scope in SELECTION_SCOPES:
        key = encode_group_key(scope, sample)
        start, end = decode_group_key(scope, key)
        assert start <= sample <= end, f"{scope}: {key} does not cover {sample}"
        assert encode_group_key(scope, start) == key
        assert encode_group_key(scope, end) == key


def test_group_key_accepts_a_bare_year() -> None:
    """The census year lists and the topo path hold ints, not dates."""
    assert encode_group_key("year", 2015) == "2015"
    assert encode_group_key("decade", 1967) == "1960s"


@pytest.mark.parametrize(
    ("scope", "key"),
    [("year", "199"), ("year", "nope"), ("quarter", "1993"), ("decade", "1960")],
)
def test_decode_rejects_keys_the_scope_cannot_produce(scope: str, key: str) -> None:
    with pytest.raises(ValueError):
        decode_group_key(scope, key)


def test_decade_decodes_to_the_full_ten_years() -> None:
    assert decode_group_key("decade", "1960s") == (date(1960, 1, 1), date(1969, 12, 31))


# ── Fixtures: a parcel, a request and its task rows ───────────────────────────


def _seed_request(
    factory: sessionmaker[Session],
    sources: tuple[str, ...] = ("landsat",),
) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """Insert a parcel, one timeline request and its task rows.

    Returns (parcel_id, request_id, {source: task_id}).
    """
    parcel_id = uuid.uuid4()
    request_id = uuid.uuid4()
    task_ids: dict[str, uuid.UUID] = {}
    with factory() as db:
        db.execute(
            text(
                "INSERT INTO parcels (id, address, latitude, longitude)"
                " VALUES (:id, '1 Test St', 39.5, -104.5)"
            ),
            {"id": str(parcel_id)},
        )
        # Typed bindparams, because that is how the app writes these two
        # columns (create_request_tasks and the ORM alike) and SQLite renders
        # a typed UUID without dashes. A seed using str() would insert rows
        # the production lookups cannot find.
        db.execute(
            text(
                "INSERT INTO timeline_requests (id, parcel_id, status)"
                " VALUES (:id, :parcel_id, 'processing')"
            ).bindparams(bindparam("id", type_=Uuid())),
            {"id": request_id, "parcel_id": str(parcel_id)},
        )
        for source in sources:
            task_id = uuid.uuid4()
            task_ids[source] = task_id
            db.execute(
                text(
                    "INSERT INTO timeline_request_tasks (id, timeline_request_id, source, status)"
                    " VALUES (:id, :request_id, :source, 'processing')"
                ).bindparams(bindparam("id", type_=Uuid()), bindparam("request_id", type_=Uuid())),
                {"id": task_id, "request_id": request_id, "source": source},
            )
        db.commit()
    return parcel_id, request_id, task_ids


def _ledger_rows(factory: sessionmaker[Session]) -> dict[tuple[str, str], dict[str, str]]:
    """Every ledger row, keyed by (source, group_key)."""
    with factory() as db:
        rows = db.execute(
            text("SELECT source, group_key, outcome, reason, detail FROM timeline_task_years")
        ).mappings()
        return {
            (r["source"], r["group_key"]): {
                "outcome": r["outcome"],
                "reason": r["reason"],
                "detail": r["detail"],
            }
            for r in rows
        }


# ── Recorder semantics ────────────────────────────────────────────────────────


def test_record_year_outcome_writes_a_row(committing_db: sessionmaker[Session]) -> None:
    _, _, tasks = _seed_request(committing_db)
    with committing_db() as db:
        year_ledger.record_year_outcome(
            db, tasks["landsat"], "landsat", "1993", "absent", "no_scenes"
        )
    assert _ledger_rows(committing_db)[("landsat", "1993")]["reason"] == "no_scenes"


def test_a_failed_then_ok_walk_ends_ok(committing_db: sessionmaker[Session]) -> None:
    """Upsert on (task_id, group_key): the last attempt in a run is the answer.

    A validation walk that starts on a broken scene and lands on a working
    fallback must leave one ``ok`` row, not an ``ok`` beside a stale
    ``failed``.
    """
    _, _, tasks = _seed_request(committing_db)
    with committing_db() as db:
        year_ledger.record_year_outcome(
            db, tasks["landsat"], "landsat", "1993", "failed", "sign_429", "first try"
        )
        year_ledger.record_year_outcome(
            db, tasks["landsat"], "landsat", "1993", "ok", None, "served by fallback"
        )
    rows = _ledger_rows(committing_db)
    assert len(rows) == 1
    assert rows[("landsat", "1993")]["outcome"] == "ok"
    assert rows[("landsat", "1993")]["reason"] is None
    assert rows[("landsat", "1993")]["detail"] == "served by fallback"


def test_detail_is_truncated(committing_db: sessionmaker[Session]) -> None:
    _, _, tasks = _seed_request(committing_db)
    with committing_db() as db:
        year_ledger.record_year_outcome(
            db, tasks["landsat"], "landsat", "1993", "failed", "other", "x" * 900
        )
    detail = _ledger_rows(committing_db)[("landsat", "1993")]["detail"]
    assert len(detail) == year_ledger.DETAIL_MAX_CHARS


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("nonsense", None),
        ("failed", "not_a_reason"),
        ("absent", "sign_429"),
        ("ok", "no_scenes"),
        ("indeterminate", None),
    ],
)
def test_vocabulary_is_enforced(outcome: str, reason: str | None) -> None:
    """A typo in a reason is otherwise indistinguishable from "no rows match"."""
    log = year_ledger.YearOutcomeLog("landsat")
    with pytest.raises(year_ledger.LedgerVocabularyError):
        log.record("1993", outcome, reason)


def test_redelivered_request_reset_clears_prior_year_rows(
    committing_db: sessionmaker[Session],
) -> None:
    """The ON CONFLICT reset in create_request_tasks takes the ledger with it.

    A Celery redelivery resets the task row to queued. Leaving its ``ok``
    rows behind would have the ledger claiming snapshots the replacement run
    has not written.
    """
    from app.services.imagery import create_request_tasks

    _, request_id, tasks = _seed_request(committing_db, ("landsat", "census"))
    with committing_db() as db:
        year_ledger.record_year_outcome(db, tasks["landsat"], "landsat", "1993", "ok")
        year_ledger.record_year_outcome(db, tasks["census"], "census_acs5", "2021", "ok")
    assert len(_ledger_rows(committing_db)) == 2

    with committing_db() as db:
        create_request_tasks(db, request_id, ["landsat"])

    remaining = _ledger_rows(committing_db)
    assert ("landsat", "1993") not in remaining, "the reset source's rows must go"
    assert ("census_acs5", "2021") in remaining, "an untouched source's rows must stay"


# ── Driving the real fetch loops ──────────────────────────────────────────────

_BBOX = (-105.0, 39.0, -104.0, 40.0)
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _stac_item(item_id: str, dt: str, cloud: float = 5.0) -> dict[str, object]:
    return {
        "id": item_id,
        "properties": {"datetime": dt, "eo:cloud_cover": cloud},
        "assets": {"red": {"href": "https://landsateuwest.blob.core.windows.net/landsat-c2/r.tif"}},
        "bbox": [-105.0, 39.0, -104.0, 40.0],
    }


def _chunked_cfg(source: str, collection: str, start: int, end: int) -> dict[str, object]:
    from app.services import stac as stac_service

    selector = (
        stac_service.select_landsat_items
        if source == "landsat"
        else stac_service.select_sentinel_items
    )
    return {
        "source": source,
        "collection": collection,
        "start_year": start,
        "end_year": end,
        "max_items_per_year": 5,
        "query": {"eo:cloud_cover": {"lt": 40}},
        "selector": selector,
        "selection_scope": "year",
        "resolution_m": 30.0,
        "chunk_by_year": True,
        "use_viewport_filter": False,
    }


async def _run_source(
    factory: sessionmaker[Session],
    cfg: dict[str, object],
    parcel_id: uuid.UUID,
    request_id: uuid.UUID,
    mock_search,
    *,
    check=None,
    groups_filter=None,
) -> int:
    from app.tasks.timeline import _fetch_source

    async def always_valid(item: dict[str, object]) -> str | None:
        return None

    patches = [
        patch("app.db.SessionLocal", factory),
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
            "app.tasks.timeline.stac_service.filter_items_intersecting_bbox",
            side_effect=lambda items, viewport: items,
        ),
        patch("app.services.stac.check_landsat_item", side_effect=check or always_valid),
        patch("app.services.stac.check_sentinel_item", side_effect=check or always_valid),
        patch(
            "app.tasks.timeline.stac_service.extract_cog_url",
            return_value="https://example.com/cog.tif",
        ),
        patch("app.tasks.timeline.stac_service.extract_thumbnail_url", return_value=None),
        patch("app.tasks.timeline.stac_service.extract_bbox_wkt", return_value=None),
    ]
    if groups_filter is not None:
        patches.append(
            patch(
                "app.tasks.timeline.stac_service.filter_groups_containing_point",
                side_effect=groups_filter,
            )
        )

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return await _fetch_source(cfg, _BBOX, _BBOX, parcel_id, request_id, lat=39.5, lng=-104.5)


def _served_count(factory: sessionmaker[Session], parcel_id: uuid.UUID) -> int:
    """How many periods this parcel serves, in the only shape there is.

    Was ``_snapshot_count`` over the denormalized table until ADR 0001 step 4.
    The counts these tests assert are unchanged, because the two shapes always
    held one row per served period for these fixtures — the difference between
    them was where an item's *facts* lived, not how many periods there were.
    """
    with factory() as db:
        return int(
            db.execute(
                text("SELECT COUNT(*) FROM parcel_scenes WHERE parcel_id = :p"),
                {"p": str(parcel_id)},
            ).scalar()
            or 0
        )


# ── Delete-the-fix: the STAC year-chunk loop ─────────────────────────────────


@pytest.mark.asyncio
async def test_landsat_chunk_403_is_recorded_and_costs_no_rows(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `ledger.record(...)` in the chunk `except` branch.

    Acceptance case from the record: the completion sweep saw two 403s here.
    They cost no snapshot rows — reconciliation leaves absent groups alone —
    and nothing recorded that the year was never actually asked.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("landsat",))
    with committing_db() as db:
        seed_served_scene(
            db,
            parcel_id=parcel_id,
            source="landsat",
            capture_date=date(2015, 6, 1),
            stac_item_id="OLD_2015",
            stac_collection="landsat-c2-l2",
            cog_url="u",
        )
        db.commit()

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        if "2015" in str(kwargs.get("datetime_range")):
            raise httpx.HTTPStatusError("403", request=AsyncMock(), response=httpx.Response(403))
        return [_stac_item("LC08_2016", "2016-07-01T00:00:00Z")]

    await _run_source(
        committing_db,
        _chunked_cfg("landsat", "landsat-c2-l2", 2015, 2016),
        parcel_id,
        request_id,
        mock_search,
    )

    rows = _ledger_rows(committing_db)
    assert rows[("landsat", "2015")]["outcome"] == "failed"
    assert rows[("landsat", "2015")]["reason"] == "stac_403"
    assert rows[("landsat", "2016")]["outcome"] == "ok"

    with committing_db() as db:
        kept = db.execute(
            text(
                "SELECT s.item_id FROM parcel_scenes ps JOIN scenes s ON s.id = ps.scene_id"
                " WHERE ps.parcel_id = :p AND ps.group_key = '2015'"
            ),
            {"p": str(parcel_id)},
        ).scalar()
    assert kept == "OLD_2015", "a 403 year must not disturb the row a prior run landed"


@pytest.mark.asyncio
async def test_sentinel_2015_with_only_cloudy_scenes_is_cloud_filtered(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `ledger.record(key, outcome, reason)` after the probe.

    Acceptance case from O6: nine 2015 S2 gaps all had covering scenes. The
    cloud threshold is pushed into the STAC query, so the filtered search
    returns nothing and only an unfiltered probe can tell "all cloudy" from
    "no scenes".
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("sentinel2",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        if kwargs.get("query"):
            return []  # every 2015 scene is at or above the 40% threshold
        return [_stac_item("S2_2015_cloudy", "2015-08-01T00:00:00Z", cloud=88.0)]

    await _run_source(
        committing_db,
        _chunked_cfg("sentinel2", "sentinel-2-l2a", 2015, 2015),
        parcel_id,
        request_id,
        mock_search,
    )

    row = _ledger_rows(committing_db)[("sentinel2", "2015")]
    assert row["outcome"] == "absent"
    assert row["reason"] == "all_cloud_filtered"


@pytest.mark.asyncio
async def test_a_year_the_collection_never_imaged_is_no_scenes(
    committing_db: sessionmaker[Session],
) -> None:
    """The other half of the probe: nothing under the threshold, nothing over it."""
    parcel_id, request_id, _ = _seed_request(committing_db, ("sentinel2",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return []

    await _run_source(
        committing_db,
        _chunked_cfg("sentinel2", "sentinel-2-l2a", 2015, 2015),
        parcel_id,
        request_id,
        mock_search,
    )

    row = _ledger_rows(committing_db)[("sentinel2", "2015")]
    assert (row["outcome"], row["reason"]) == ("absent", "no_scenes")


# ── Delete-the-fix: the validation walk ──────────────────────────────────────


@pytest.mark.asyncio
async def test_signing_429_exhausting_the_walk_records_sign_429(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: `ledger.record(key, note.outcome, ...)` over walk_notes,
    and the `notes[key] = GroupNote("failed", ...)` that fills them in
    stac._validate_selection.

    This is N1's signature: every candidate in the year re-signs against the
    same unhealthy endpoint, so the year is lost to the signing endpoint, not
    to the scenes. "This scene is broken" used to be the same bare False.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("landsat",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return [
            _stac_item("LC08_a", "2016-06-01T00:00:00Z", cloud=5.0),
            _stac_item("LC08_b", "2016-08-01T00:00:00Z", cloud=9.0),
        ]

    async def always_429(item: dict[str, object]) -> str | None:
        return "sign_429"

    await _run_source(
        committing_db,
        _chunked_cfg("landsat", "landsat-c2-l2", 2016, 2016),
        parcel_id,
        request_id,
        mock_search,
        check=always_429,
    )

    row = _ledger_rows(committing_db)[("landsat", "2016")]
    assert (row["outcome"], row["reason"]) == ("failed", "sign_429")
    assert _served_count(committing_db, parcel_id) == 0


@pytest.mark.asyncio
async def test_a_year_rescued_by_the_fallback_ends_ok_with_the_swap_in_detail(
    committing_db: sessionmaker[Session],
) -> None:
    """The failed-then-ok path, end to end through the real walk."""
    parcel_id, request_id, _ = _seed_request(committing_db, ("landsat",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return [
            _stac_item("LC08_broken", "2016-06-01T00:00:00Z", cloud=1.0),
            _stac_item("LC08_good", "2016-08-01T00:00:00Z", cloud=9.0),
        ]

    async def broken_first(item: dict[str, object]) -> str | None:
        return "validation_failed" if item["id"] == "LC08_broken" else None

    await _run_source(
        committing_db,
        _chunked_cfg("landsat", "landsat-c2-l2", 2016, 2016),
        parcel_id,
        request_id,
        mock_search,
        check=broken_first,
    )

    row = _ledger_rows(committing_db)[("landsat", "2016")]
    assert row["outcome"] == "ok"
    assert "LC08_broken -> LC08_good" in row["detail"]


# ── Delete-the-fix: the ok row beside the row it claims ──────────────────────


@pytest.mark.asyncio
async def test_a_served_year_writes_an_ok_row_with_its_served_row(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `record_year_outcome(..., "ok", ...)` in the loop.

    The prediction's falsifiable check is "zero groups with a served row and
    no ok ledger row", so this is the pair that check counts. Since ADR 0001
    step 4 the two are one transaction rather than two ordered commits —
    ``test_scene_writes.py``'s crash test is the half that proves the ok row
    cannot outlive a rolled-back write.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("landsat",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        year = str(kwargs.get("datetime_range"))[:4]
        return [_stac_item(f"LC08_{year}", f"{year}-07-01T00:00:00Z")]

    await _run_source(
        committing_db,
        _chunked_cfg("landsat", "landsat-c2-l2", 2015, 2016),
        parcel_id,
        request_id,
        mock_search,
    )

    rows = _ledger_rows(committing_db)
    assert rows[("landsat", "2015")]["outcome"] == "ok"
    assert rows[("landsat", "2016")]["outcome"] == "ok"
    assert _served_count(committing_db, parcel_id) == 2


# ── Delete-the-fix: the NAIP point-coverage gate ─────────────────────────────


@pytest.mark.asyncio
async def test_naip_year_with_no_covering_tile_is_suppressed(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `ledger.record(suppressed_key, "suppressed", ...)`
    inside the uncovered-groups loop.

    Not "empty" and not "failed": the collection had tiles for the year and
    none of them covers the address, which is what 14b59af suppresses.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("naip",))
    tile = _stac_item("naip_nj_2023", "2023-07-01T00:00:00Z")

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return [tile]

    cfg = {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2023-01-01/2023-12-31",
        "max_items": 50,
        "query": None,
        "selector": lambda items, viewport: [[items[0]]],
        "selection_scope": "year",
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": True,
    }

    await _run_source(
        committing_db,
        cfg,
        parcel_id,
        request_id,
        mock_search,
        groups_filter=lambda groups, lat, lng: ([], list(groups)),
    )

    row = _ledger_rows(committing_db)[("naip", "2023")]
    assert (row["outcome"], row["reason"]) == ("suppressed", "naip_no_point_coverage")
    assert "naip_nj_2023" in row["detail"]
    assert _served_count(committing_db, parcel_id) == 0


# ── Delete-the-fix: USGS topo ────────────────────────────────────────────────


async def _run_topo(
    factory: sessionmaker[Session],
    parcel_id: uuid.UUID,
    request_id: uuid.UUID,
    items: list[dict[str, object]],
    *,
    truncated: bool = False,
) -> int:
    from app.tasks.timeline import _fetch_usgs_topo

    result = topo_service.TopoSearchResult(items=items, truncated=truncated)
    with (
        patch("app.db.SessionLocal", factory),
        patch(
            "app.tasks.timeline.topo_service.search_usgs_topo_products",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("app.tasks.timeline.topo_service.extract_bbox_wkt", return_value=None),
    ):
        return await _fetch_usgs_topo(_BBOX, parcel_id, request_id)


def _topo_product(source_id: str, published: str) -> dict[str, object]:
    return {
        "sourceId": source_id,
        "publicationDate": published,
        "extent": "7.5 x 7.5 minute",
        "urls": {"GeoTIFF": f"https://example.com/{source_id}.tif"},
    }


@pytest.mark.asyncio
async def test_topo_records_ok_per_decade(committing_db: sessionmaker[Session]) -> None:
    """Delete-the-fix: the `record_year_outcome(..., decade_key, "ok", ...)`
    before the topo upsert."""
    parcel_id, request_id, _ = _seed_request(committing_db, ("usgs_topo",))

    await _run_topo(
        committing_db,
        parcel_id,
        request_id,
        [_topo_product("SRC-1955", "1955-01-01"), _topo_product("SRC-1963", "1963-01-01")],
    )

    rows = _ledger_rows(committing_db)
    assert rows[("usgs_topo", "1950s")]["outcome"] == "ok"
    assert rows[("usgs_topo", "1960s")]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_topo_product_with_no_source_id_is_suppressed(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `record_year_outcome(..., "topo_no_source_id", ...)`.

    The live topo door. An id-less product would upsert as stac_item_id="",
    whose conflict target makes every id-less product on a parcel overwrite
    the last, so it is skipped — silently, until now.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("usgs_topo",))

    await _run_topo(
        committing_db,
        parcel_id,
        request_id,
        [_topo_product("", "1955-01-01")],
    )

    row = _ledger_rows(committing_db)[("usgs_topo", "1950s")]
    assert (row["outcome"], row["reason"]) == ("suppressed", "topo_no_source_id")
    assert _served_count(committing_db, parcel_id) == 0


@pytest.mark.asyncio
async def test_topo_empty_and_capped_searches_are_distinguished(
    committing_db: sessionmaker[Session],
) -> None:
    """Topo has no enumerable decade range, so the whole-search verdict is
    recorded under the whole-source key. A capped response cannot claim a
    decade was absent."""
    parcel_id, request_id, _ = _seed_request(committing_db, ("usgs_topo",))
    await _run_topo(committing_db, parcel_id, request_id, [])
    row = _ledger_rows(committing_db)[("usgs_topo", "*")]
    assert (row["outcome"], row["reason"]) == ("absent", "no_scenes")

    parcel_id2, request_id2, _ = _seed_request(committing_db, ("usgs_topo",))
    await _run_topo(
        committing_db,
        parcel_id2,
        request_id2,
        [_topo_product("SRC-1955", "1955-01-01")],
        truncated=True,
    )
    capped = _ledger_rows(committing_db)[("usgs_topo", "*")]
    assert capped["outcome"] == "indeterminate"
    assert "row cap" in capped["reason"]


# ── Delete-the-fix: census ───────────────────────────────────────────────────


async def _run_census(
    factory: sessionmaker[Session],
    parcel_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    decennial,
    acs5,
) -> int:
    from app.tasks.timeline import _fetch_census

    fetcher = AsyncMock()
    fetcher.fetch_decennial = AsyncMock(side_effect=decennial)
    fetcher.fetch_acs5 = AsyncMock(side_effect=acs5)
    fetcher.close = AsyncMock()

    with (
        patch("app.db.SessionLocal", factory),
        patch("app.tasks.timeline.CensusFetcher", return_value=fetcher),
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
    ):
        return await _fetch_census(parcel_id, request_id, "08031006202", api_key="k")


@pytest.mark.asyncio
async def test_census_empty_response_is_absent_api_no_data(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `ledger.record(key, "absent", "api_no_data", ...)`
    in the decennial `else` branch.

    The silent skip. `{}` arrives from a 204/404, a year with no decennial
    config, and every variable being dropped as unrecognised for the vintage
    — none of them counted, none of them logged at this level. The task still
    ends `complete`, and `failed_requests` is untouched, which is exactly why
    nothing could see it.
    """
    from app.services.census import ACS5_YEARS, DECENNIAL_YEARS

    async def no_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {}

    async def some_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {"total_population": 100}

    await _run_census(
        committing_db, *_ids(committing_db, "census"), decennial=no_data, acs5=some_data
    )

    rows = _ledger_rows(committing_db)
    for year in DECENNIAL_YEARS:
        row = rows[("census_decennial", str(year))]
        assert (row["outcome"], row["reason"]) == ("absent", "api_no_data")
    for year in ACS5_YEARS:
        assert rows[("census_acs5", str(year))]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_census_http_404_is_failed_http_404(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: `raise CensusHttpStatusError(...)` in `census._request`,
    and the `isinstance` branch in `_census_failure_reason`.

    A 404 is a URL that does not resolve. It used to return `None` alongside
    204, become `{}`, and land as `absent`/`api_no_data` — which is how
    `1990/dec/sf1`, an endpoint that has never existed, read as "this tract
    has no data" on all 186 parcels. Revert `_request` to
    `if resp.status_code in (204, 404)` and every row below reads `absent`.

    A real `CensusFetcher` over a mocked transport, not a mocked fetcher: the
    collapse being tested lives inside `_request`.
    """
    from app.services.census import ACS5_YEARS, DECENNIAL_YEARS, CensusFetcher
    from app.tasks.timeline import _fetch_census

    response = MagicMock()
    response.status_code = 404
    response.text = "Not Found"

    fetcher = CensusFetcher(api_key="test-key")
    fetcher.client = AsyncMock()
    fetcher.client.get = AsyncMock(return_value=response)

    parcel_id, request_id = _ids(committing_db, "census")
    with (
        patch("app.db.SessionLocal", committing_db),
        patch("app.tasks.timeline.CensusFetcher", return_value=fetcher),
        patch("app.tasks.timeline.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _fetch_census(parcel_id, request_id, "08031006202", api_key="test-key")

    rows = _ledger_rows(committing_db)
    for year in DECENNIAL_YEARS:
        row = rows[("census_decennial", str(year))]
        assert (row["outcome"], row["reason"]) == ("failed", "http_404"), year
    for year in ACS5_YEARS:
        row = rows[("census_acs5", str(year))]
        assert (row["outcome"], row["reason"]) == ("failed", "http_404"), year

    # The detail names the dataset that answered 404, never the key.
    assert "/2000/dec/sf1" in rows[("census_decennial", "2000")]["detail"]
    assert "/2023/acs/acs5" in rows[("census_acs5", "2023")]["detail"]
    assert "test-key" not in rows[("census_acs5", "2023")]["detail"]


@pytest.mark.asyncio
async def test_census_read_timeout_is_failed_read_timeout(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the `ledger.record(key, "failed", ...)` in the ACS5
    `except CensusApiError` branch.

    CensusFetcher wraps every httpx.HTTPError as CensusApiError, so the
    transport type survives only on __cause__ — which is what separates a
    timed-out request from a 500.
    """
    from app.services.census import ACS5_YEARS, CensusApiError

    async def timed_out(*args: object, **kwargs: object) -> dict[str, object]:
        raise CensusApiError("HTTP error: timed out") from httpx.ReadTimeout("timed out")

    async def some_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {"total_population": 100}

    await _run_census(
        committing_db, *_ids(committing_db, "census"), decennial=some_data, acs5=timed_out
    )

    rows = _ledger_rows(committing_db)
    for year in ACS5_YEARS:
        row = rows[("census_acs5", str(year))]
        assert (row["outcome"], row["reason"]) == ("failed", "read_timeout")


def _ids(factory: sessionmaker[Session], *sources: str) -> tuple[uuid.UUID, uuid.UUID]:
    parcel_id, request_id, _ = _seed_request(factory, sources)
    return parcel_id, request_id


# ── Indeterminate: the sites that cannot decide ──────────────────────────────


@pytest.mark.asyncio
async def test_naip_absent_year_under_a_capped_search_is_indeterminate(
    committing_db: sessionmaker[Session],
) -> None:
    """A saturated NAIP pool cannot claim a year was empty.

    NAIP sends no `sortby`, so which items survive the cap is unspecified —
    a year missing from a capped response may simply have been truncated
    away. Recording that as `absent` would send a heal after a year that was
    never actually reported on.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("naip",))
    tile = _stac_item("naip_2023", "2023-07-01T00:00:00Z")

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return [tile]

    cfg = {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2022-01-01/2023-12-31",
        "max_items": 1,  # one item back against a cap of one — saturated
        "query": None,
        "selector": lambda items, viewport: [[items[0]]],
        "selection_scope": "year",
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": True,
    }

    await _run_source(
        committing_db,
        cfg,
        parcel_id,
        request_id,
        mock_search,
        groups_filter=lambda groups, lat, lng: (list(groups), []),
    )

    rows = _ledger_rows(committing_db)
    assert rows[("naip", "2023")]["outcome"] == "ok"
    assert rows[("naip", "2022")]["outcome"] == "indeterminate"
    assert "item cap" in rows[("naip", "2022")]["reason"]


@pytest.mark.asyncio
async def test_an_uncapped_naip_year_with_nothing_back_is_absent(
    committing_db: sessionmaker[Session],
) -> None:
    """The attempted set is the query's own date range, since NAIP runs no
    per-year loop to observe it from."""
    parcel_id, request_id, _ = _seed_request(committing_db, ("naip",))

    async def mock_search(**kwargs: object) -> list[dict[str, object]]:
        return [_stac_item("naip_2023", "2023-07-01T00:00:00Z")]

    cfg = {
        "source": "naip",
        "collection": "naip",
        "datetime_range": "2021-01-01/2023-12-31",
        "max_items": 50,
        "query": None,
        "selector": lambda items, viewport: [[items[0]]],
        "selection_scope": "year",
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": True,
    }

    await _run_source(
        committing_db,
        cfg,
        parcel_id,
        request_id,
        mock_search,
        groups_filter=lambda groups, lat, lng: (list(groups), []),
    )

    rows = _ledger_rows(committing_db)
    assert [rows[("naip", y)]["reason"] for y in ("2021", "2022")] == ["no_scenes", "no_scenes"]
    assert rows[("naip", "2023")]["outcome"] == "ok"


# ── The read query M3 will use ───────────────────────────────────────────────


def test_ledger_gaps_reports_the_latest_outcome_per_group(
    committing_db: sessionmaker[Session],
) -> None:
    """Two runs on one parcel: the later run's verdict is the one reported.

    This is the query that replaces the heal scripts' bespoke selection, so
    "healed on run 2" has to read as healed and "regressed on run 2" has to
    read as broken.
    """
    import sys

    sys.path.insert(0, str(_SCRIPTS_DIR))
    import ledger_gaps

    parcel_id, _, first = _seed_request(committing_db, ("landsat",))
    with committing_db() as db:
        year_ledger.record_year_outcome(
            db, first["landsat"], "landsat", "1993", "failed", "sign_429"
        )
        year_ledger.record_year_outcome(db, first["landsat"], "landsat", "1994", "ok")

    # A second run on the same parcel, later by created_at.
    second_request = uuid.uuid4()
    second_task = uuid.uuid4()
    with committing_db() as db:
        db.execute(
            text(
                "INSERT INTO timeline_requests (id, parcel_id, status, created_at)"
                " VALUES (:id, :p, 'complete', '2099-01-01 00:00:00')"
            ).bindparams(bindparam("id", type_=Uuid())),
            {"id": second_request, "p": str(parcel_id)},
        )
        db.execute(
            text(
                "INSERT INTO timeline_request_tasks (id, timeline_request_id, source, status)"
                " VALUES (:id, :r, 'landsat', 'complete')"
            ).bindparams(bindparam("id", type_=Uuid()), bindparam("r", type_=Uuid())),
            {"id": second_task, "r": second_request},
        )
        db.commit()
        year_ledger.record_year_outcome(db, second_task, "landsat", "1993", "ok")
        year_ledger.record_year_outcome(db, second_task, "landsat", "1994", "failed", "stac_403")

    with patch.object(ledger_gaps, "SessionLocal", committing_db):
        rows = {r.group_key: r for r in ledger_gaps._fetch(None, None, None)}

    assert rows["1993"].outcome == "ok", "healed on the later run"
    assert rows["1994"].outcome == "failed", "regressed on the later run"
    assert rows["1993"].attempts == 2
    assert set(rows["1993"].reasons_seen) == {"sign_429"}


@pytest.mark.asyncio
async def test_a_source_whose_every_year_failed_still_records_them(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the ``_flush_ledger`` before ``raise last_exc``.

    Found on 2026-08-26 while gathering M3's Crawford prediction. Parcel
    ``6563dedf`` holds 16 ``failed`` Landsat years and 17 ``failed`` NAIP
    years — and **zero** Sentinel-2 rows, though its Sentinel-2 task is
    ``failed`` and it serves no Sentinel-2 snapshots. The cause is here: a
    per-year failure stages its row in the ``YearOutcomeLog``, and when
    *every* year fails the source raises out of this function before any
    persist session opens, so the whole staged log dies with the exception.

    The instrument was silent exactly where the loss was total. Losing some
    years was visible; losing all of them was not, which inverts what the
    ledger exists for and hides the one case a ledger-driven heal most needs
    to see.
    """
    parcel_id, request_id, _ = _seed_request(committing_db, ("sentinel2",))

    async def always_fails(**kwargs: object) -> list[dict[str, object]]:
        raise httpx.ReadTimeout("read timeout")

    # _fetch_source swallows the exception into a failed task row and
    # returns 0 — which is exactly why the ledger is the only record left.
    saved = await _run_source(
        committing_db,
        _chunked_cfg("sentinel2", "sentinel-2-l2a", 2015, 2017),
        parcel_id,
        request_id,
        always_fails,
    )
    assert saved == 0

    rows = _ledger_rows(committing_db)
    assert {key for _, key in rows} == {"2015", "2016", "2017"}
    assert all(r["outcome"] == "failed" for r in rows.values())
    assert all(r["reason"] == "read_timeout" for r in rows.values())
