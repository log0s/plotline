"""Tests for scripts/backfill_scenes.py and the schema it fills.

The script lives outside the backend package, so it is loaded by path the
same way ``test_remove_uncovered_snapshots.py`` loads its subject. Nothing
here touches the network: Phase B parses URLs and never fetches them, which
is the property that makes it testable at all.

Delete-the-fix, one clause per test:

* ``uq_parcel_scenes_parcel_source_group`` (migration 0015 and the mirrored
  conftest DDL) — remove it and
  ``test_second_row_for_one_period_is_rejected`` passes an insert that
  reproduces G3, two Sentinel-2 rows for one parcel-year.
* the ``if url in url_to_key`` branch in ``_plan_mosaic_scenes`` — remove it
  and ``test_matched_mosaic_url_resolves_to_the_existing_scene`` sees three
  scenes instead of two, with the mosaic pointing at a synthesized
  duplicate of a row the table already had.
* the synthesis branch below it — remove it and
  ``test_unmatched_naip_url_synthesizes_a_scene`` finds no ``mosaic_url``
  row and a mosaic reference to nothing.
* ``parse_naip_tile_url``'s raises — remove them and
  ``test_unparseable_mosaic_url_refuses_the_run`` writes rows for a URL the
  script cannot resolve, which is the silent-skip the ADR forbids.
* the duplicate-group guard in ``run`` — remove it and
  ``test_duplicate_group_refuses_the_run`` proceeds, silently collapsing
  two rows of a period into one ``parcel_scenes`` row.
* the ``if key in known`` / ``if key in existing`` skips — remove either and
  ``test_second_run_writes_nothing`` fails on a unique violation instead of
  reporting a no-op.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_HERE = Path(__file__).resolve()
_SCRIPT = next(
    p / "scripts" / "backfill_scenes.py"
    for p in _HERE.parents
    if (p / "scripts" / "backfill_scenes.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_scenes", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_scenes"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

PARCEL = "81b2d663-1851-438d-a9fa-58d665e32e25"
_NAIP_BASE = "https://naipeuwest.blob.core.windows.net/naip/v002/nj/2023/nj_030cm_2023/40074"
PRIMARY_ITEM = "nj_m_4007309_sw_18_030_20230820_20231019"
PRIMARY_URL = f"{_NAIP_BASE}/m_4007309_sw_18_030_20230820_20231019.tif"
# A neighbouring tile that no snapshot row serves directly. Its filename
# omits the publication date the item id would carry, which is the whole
# reason a synthesized item_id is a candidate rather than a catalogued id.
LONE_TILE_URL = f"{_NAIP_BASE}/m_4007424_ne_18_030_20230820.tif"
LONE_TILE_ITEM = "nj_m_4007424_ne_18_030_20230820"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _insert_parcel(db: Session, parcel_id: str = PARCEL) -> None:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude)"
            " VALUES (:id, :address, :lat, :lng)"
        ),
        {
            "id": parcel_id,
            "address": "350 5th Ave, New York, NY 10118",
            "lat": 40.75,
            "lng": -73.99,
        },
    )


def _insert_snapshot(
    db: Session,
    *,
    parcel_id: str = PARCEL,
    source: str = "naip",
    collection: str = "naip",
    capture_date: str = "2023-08-20",
    item_id: str = PRIMARY_ITEM,
    cog_url: str = PRIMARY_URL,
    extras: list[str] | None = None,
) -> str:
    snapshot_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO imagery_snapshots"
            " (id, parcel_id, source, capture_date, stac_item_id, stac_collection,"
            "  cog_url, additional_cog_urls, created_at)"
            " VALUES (:id, :parcel_id, :source, :capture_date, :item_id, :collection,"
            "  :cog_url, :extras, :created_at)"
        ),
        {
            "id": snapshot_id,
            "parcel_id": parcel_id,
            "source": source,
            "capture_date": capture_date,
            "item_id": item_id,
            "collection": collection,
            "cog_url": cog_url,
            # Postgres stores text[]; SQLite gets the literal the driver
            # would render, which _extra_urls parses either way.
            "extras": "{" + ",".join(extras) + "}" if extras else None,
            "created_at": "2026-08-01 12:00:00",
        },
    )
    return snapshot_id


def _counts(db: Session) -> tuple[int, int]:
    scenes = db.execute(text("SELECT count(*) FROM scenes")).scalar_one()
    parcel_scenes = db.execute(text("SELECT count(*) FROM parcel_scenes")).scalar_one()
    return int(scenes), int(parcel_scenes)


# ── Schema ────────────────────────────────────────────────────────────────────


def test_second_row_for_one_period_is_rejected(db: Session) -> None:
    """G3's shape — two rows for one (parcel, source, period) — cannot exist.

    The duplicate Sentinel-2 quarter group the second audit found was
    possible because uniqueness lived in reconcile_source_snapshots rather
    than in the schema. ADR rule 3 moves it into the schema; this is that
    move, asserted.
    """
    _insert_parcel(db)
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, fetched_at)"
            " VALUES (:id, 'sentinel2', 'sentinel-2-l2a', 'S2A_x', '2021-06-01', 'u',"
            " 'snapshot', :now)"
        ),
        {"id": scene_id, "now": "2026-08-01 12:00:00"},
    )
    values = {
        "parcel_id": PARCEL,
        "scene_id": scene_id,
        "now": "2026-08-01 12:00:00",
    }
    insert = text(
        "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id, selected_at)"
        " VALUES (:id, :parcel_id, 'sentinel2', '2021', :scene_id, :now)"
    )
    db.execute(insert, {"id": str(uuid.uuid4()), **values})

    with pytest.raises(IntegrityError):
        db.execute(insert, {"id": str(uuid.uuid4()), **values})


def test_group_key_must_be_one_of_the_three_encodings(db: Session) -> None:
    """The CHECK admits what encode_group_key emits, and nothing else.

    '*' is the ledger's whole-source key. A served row always has a capture
    date to bucket, so it must never appear here.
    """
    _insert_parcel(db)
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, fetched_at)"
            " VALUES (:id, 'usgs_topo', 'usgs-historical-topo', 't', '1965-01-01', 'u',"
            " 'snapshot', :now)"
        ),
        {"id": scene_id, "now": "2026-08-01 12:00:00"},
    )
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO parcel_scenes"
                " (id, parcel_id, source, group_key, scene_id, selected_at)"
                " VALUES (:id, :parcel_id, 'usgs_topo', '*', :scene_id, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "parcel_id": PARCEL,
                "scene_id": scene_id,
                "now": "2026-08-01 12:00:00",
            },
        )


# ── Phase B: mosaic URL resolution ────────────────────────────────────────────


def test_matched_mosaic_url_resolves_to_the_existing_scene(db: Session) -> None:
    """A tile that is itself a served row is referenced, not re-synthesized.

    The neighbour's URL is the realistic shape — a filename that omits the
    publication date its item id carries — so URL matching and URL parsing
    give *different* answers here. That is what makes this test able to
    fail: parsing would invent a third scene for an item the table has.
    """
    _insert_parcel(db)
    neighbour_url = LONE_TILE_URL
    neighbour_item = "nj_m_4007424_ne_18_030_20230820_20231019"
    _insert_snapshot(db, item_id=PRIMARY_ITEM, cog_url=PRIMARY_URL, extras=[neighbour_url])
    _insert_snapshot(
        db,
        source="naip",
        capture_date="2021-07-01",
        item_id=neighbour_item,
        cog_url=neighbour_url,
    )

    script.run(db, execute=True)

    scenes, parcel_scenes = _counts(db)
    assert (scenes, parcel_scenes) == (2, 2)
    assert (
        db.execute(text("SELECT count(*) FROM scenes WHERE provenance = 'mosaic_url'")).scalar_one()
        == 0
    )

    neighbour_id = db.execute(
        text("SELECT id FROM scenes WHERE item_id = :item"), {"item": neighbour_item}
    ).scalar_one()
    mosaic = db.execute(
        text("SELECT mosaic_scene_ids FROM parcel_scenes WHERE group_key = '2023'")
    ).scalar_one()
    assert str(neighbour_id) in str(mosaic)


def test_unmatched_naip_url_synthesizes_a_scene(db: Session) -> None:
    """A tile no row serves becomes a scene parsed out of its URL."""
    _insert_parcel(db)
    _insert_snapshot(db, extras=[LONE_TILE_URL])

    script.run(db, execute=True)

    row = db.execute(
        text(
            "SELECT item_id, collection, source, capture_date, cog_url, footprint,"
            " thumbnail_url, cloud_cover_pct, platform"
            " FROM scenes WHERE provenance = 'mosaic_url'"
        )
    ).one()
    assert row.item_id == LONE_TILE_ITEM
    assert row.collection == "naip"
    assert row.source == "naip"
    assert str(row.capture_date)[:10] == "2023-08-20"
    assert row.cog_url == LONE_TILE_URL
    # Nothing about the item is known beyond what the URL says.
    assert row.footprint is None
    assert row.thumbnail_url is None
    assert row.cloud_cover_pct is None
    assert row.platform is None


def test_unparseable_mosaic_url_refuses_the_run(db: Session) -> None:
    """A mosaic entry that is not a NAIP tile URL stops the whole backfill."""
    _insert_parcel(db)
    _insert_snapshot(
        db,
        extras=["https://landsateuwest.blob.core.windows.net/landsat-c2/x.TIF"],
    )

    with pytest.raises(script.BackfillError):
        script.run(db, execute=True)

    assert _counts(db) == (0, 0)


def test_capture_date_comes_from_the_first_of_two_date_fields() -> None:
    """The publication date is not the capture date."""
    parsed = script.parse_naip_tile_url(f"{_NAIP_BASE}/m_4007309_sw_18_030_20230820_20231019.tif")
    assert parsed.capture_date.isoformat() == "2023-08-20"
    assert parsed.item_id == PRIMARY_ITEM


# ── Refusals and idempotency ──────────────────────────────────────────────────


def test_duplicate_group_refuses_the_run(db: Session) -> None:
    """More duplicates than expected is the ADR's stop-and-investigate case."""
    _insert_parcel(db)
    _insert_snapshot(
        db,
        source="sentinel2",
        collection="sentinel-2-l2a",
        capture_date="2021-03-04",
        item_id="S2A_MSIL2A_20210304",
        cog_url="https://example.invalid/a.tif",
    )
    _insert_snapshot(
        db,
        source="sentinel2",
        collection="sentinel-2-l2a",
        capture_date="2021-09-04",
        item_id="S2B_MSIL2A_20210904",
        cog_url="https://example.invalid/b.tif",
    )

    with pytest.raises(script.BackfillError, match="duplicate"):
        script.run(db, execute=True)

    assert _counts(db) == (0, 0)


def test_second_run_writes_nothing(db: Session) -> None:
    _insert_parcel(db)
    _insert_snapshot(db, extras=[LONE_TILE_URL])

    first = script.run(db, execute=True)
    assert (first.scenes_inserted, first.parcel_scenes_inserted) == (2, 1)

    second = script.run(db, execute=True)
    assert (second.scenes_inserted, second.parcel_scenes_inserted) == (0, 0)
    assert (second.scenes_present, second.parcel_scenes_present) == (2, 1)
    assert second.drift == []
    assert _counts(db) == (2, 1)


# ── Copied attributes ─────────────────────────────────────────────────────────


def test_platform_is_derived_only_where_the_item_id_names_one() -> None:
    assert script.platform_for("LC08_L2SP_033033_20200101_20200823_02_T1") == "LC08"
    assert script.platform_for("LT04_L2SP_033033_19890101_19890823_02_T1") == "LT04"
    assert script.platform_for("S2C_MSIL2A_20260324T185031_R113_T10SEG_20260324T215217") == "S2C"
    assert script.platform_for(PRIMARY_ITEM) is None
    assert script.platform_for("USGS_topo_1965") is None


def test_selected_by_is_null_for_backfilled_rows(db: Session) -> None:
    """The SHA that chose these rows was never recorded; NULL is the truth."""
    _insert_parcel(db)
    _insert_snapshot(db)

    script.run(db, execute=True)

    assert (
        db.execute(
            text("SELECT count(*) FROM parcel_scenes WHERE selected_by IS NOT NULL")
        ).scalar_one()
        == 0
    )
