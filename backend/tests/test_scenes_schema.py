"""The constraints ``scenes`` and ``parcel_scenes`` carry, asserted directly.

These tests were written in ``test_backfill_scenes.py``, under a "Schema"
heading, because step 1 of docs/adr/0001-imagery-normalization.md created the
tables and the backfill in one batch. **They are not about the backfill**, and
step 4 deleted that script — a single-use tool whose only input table no
longer exists — so they moved here rather than dying with it. What they assert
is the schema itself, which is the thing that has to outlive every tool that
ever wrote it.

The constraints run against the mirrored SQLite DDL in ``conftest.py``, which
is why ``ck_parcel_scenes_group_key``'s POSIX regex appears there as three
GLOBs. The one constraint that cannot be mirrored is 0018's
``CHECK (ST_IsValid(footprint))``, which needs PostGIS; it is exercised in
``test_migrations_postgres.py`` against a real server, and its absence here is
stated in ``conftest.py`` at the DDL rather than left to be discovered.

Delete-the-fix, one clause per test:

* ``uq_parcel_scenes_parcel_source_group`` (migration 0015 and the mirrored
  conftest DDL) — remove it and ``test_second_row_for_one_period_is_rejected``
  passes an insert that reproduces G3, two Sentinel-2 rows for one
  parcel-year.
* ``ck_parcel_scenes_group_key`` — remove it and
  ``test_group_key_must_be_one_of_the_three_encodings`` stores the ledger's
  whole-source token as if it were a period.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.imagery import platform_for

PARCEL = "81b2d663-1851-438d-a9fa-58d665e32e25"
NOW = "2026-08-01 12:00:00"


def _insert_parcel(db: Session) -> None:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, normalized_address, latitude, longitude)"
            " VALUES (:id, :a, :a, 40.75, -73.98)"
        ),
        {"id": PARCEL, "a": "350 5th Ave, New York, NY 10118"},
    )


def _insert_scene(db: Session, *, source: str, collection: str, item_id: str, date: str) -> str:
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, fetched_at)"
            " VALUES (:id, :source, :collection, :item_id, :date, 'u', 'snapshot', :now)"
        ),
        {
            "id": scene_id,
            "source": source,
            "collection": collection,
            "item_id": item_id,
            "date": date,
            "now": NOW,
        },
    )
    return scene_id


def test_second_row_for_one_period_is_rejected(db: Session) -> None:
    """G3's shape — two rows for one (parcel, source, period) — cannot exist.

    The duplicate Sentinel-2 quarter group the second audit found was
    possible because uniqueness lived in reconcile_source_snapshots rather
    than in the schema. ADR rule 3 moves it into the schema; this is that
    move, asserted.

    Step 4 makes it load-bearing in a second way: superseding a period is now
    spelled as an upsert of *the* row for that period, so this constraint is
    what makes "the row for this group" a well-defined thing to upsert.
    """
    _insert_parcel(db)
    scene_id = _insert_scene(
        db, source="sentinel2", collection="sentinel-2-l2a", item_id="S2A_x", date="2021-06-01"
    )
    values = {"parcel_id": PARCEL, "scene_id": scene_id, "now": NOW}
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
    scene_id = _insert_scene(
        db, source="usgs_topo", collection="usgs-historical-topo", item_id="t", date="1965-01-01"
    )
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO parcel_scenes"
                " (id, parcel_id, source, group_key, scene_id, selected_at)"
                " VALUES (:id, :parcel_id, 'usgs_topo', '*', :scene_id, :now)"
            ),
            {"id": str(uuid.uuid4()), "parcel_id": PARCEL, "scene_id": scene_id, "now": NOW},
        )


def test_platform_is_derived_only_where_the_item_id_names_one() -> None:
    """``platform_for`` is the shared derivation; a guess would be worse than NULL.

    It lived in ``app.services.imagery`` and was imported by the backfill so
    the two writers could not disagree about a prefix. The backfill is gone;
    the function and this test are not, because the pipeline still calls it on
    every insert.
    """
    assert platform_for("LC08_L2SP_033033_20200101_20200823_02_T1") == "LC08"
    assert platform_for("LT04_L2SP_033033_19890101_19890823_02_T1") == "LT04"
    assert platform_for("S2C_MSIL2A_20260324T185031_R113_T10SEG_20260324T215217") == "S2C"
    assert platform_for("nj_m_4007309_sw_18_030_20230820_20231019") is None
    assert platform_for("USGS_topo_1965") is None
