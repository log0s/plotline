"""The serving reads come from parcel_scenes joined to scenes.

ADR 0001 step 3. **Scope, stated precisely because "every read site" is
wrong:** these tests are about the *serving* reads —

* ``get_served_scenes`` (the listing endpoint, the preview renderer)
* ``get_served_scene_by_id`` (the Titiler ``/stac`` callback, the tile proxy,
  warmup)
* ``count_served_scenes`` (``items_found``)
* ``served_scene_bounds`` (the featured cards)
* ``parcels_serving_source`` (``scripts/revalidate_landsat.py``)

**What step 4 took away from this file, and why that is not a weakening.**
Step 3's standard was *no serving path touches the denormalized table*, and
the fixture proved it by seeding rows on one side only, in both directions: a
read that had silently kept its old source would have served the old-side-only
row and missed the new-side-only one. Step 4 deleted the last code path to
that table, so the old-side-only half of the fixture cannot be written any
more — there is nothing to write it to. That direction of the proof is
**frozen in the step-3 commits** (``b1acf9a``, and
``docs/audits/2026-08-normalization/step3-parity-local.md``) and is not
re-derivable here; re-deriving it was never the plan, because a cutover is
proved once, while it is happening.

What replaces it is a stronger and differently-shaped guard:
``test_no_imagery_snapshots_references.py`` asserts that no file under
``app/`` or ``scripts/`` so much as names the table. Step 3 needed a
behavioural test because the table was still legitimately in use; step 4 can
assert absence directly.

The new-side-only row stays, and still earns its place: it is the row a read
must produce, and a read pointed anywhere else cannot.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import imagery as imagery_service

PARCEL_ID = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")

# A scene id per fixture item, fixed so the golden file below is stable.
SCENE_LANDSAT = "bbbbbbbb-0000-4000-8000-000000000001"
SCENE_NAIP = "bbbbbbbb-0000-4000-8000-000000000002"
SCENE_TILE_A = "bbbbbbbb-0000-4000-8000-000000000003"
SCENE_TILE_B = "bbbbbbbb-0000-4000-8000-000000000004"
SCENE_TOPO = "bbbbbbbb-0000-4000-8000-000000000005"
SCENE_NEW_ONLY = "bbbbbbbb-0000-4000-8000-000000000006"

PS_LANDSAT = "cccccccc-0000-4000-8000-000000000001"
PS_NAIP = "cccccccc-0000-4000-8000-000000000002"
PS_TOPO = "cccccccc-0000-4000-8000-000000000003"
PS_NEW_ONLY = "cccccccc-0000-4000-8000-000000000004"

# The id space the API hands out is ``parcel_scenes.id``. This one belongs to
# no row at all, and is what "an id from somewhere else" looks like now that
# the somewhere-else table is gone.
UNKNOWN_SERVED_ID = "dddddddd-0000-4000-8000-000000000001"

GOLDEN = Path(__file__).parent / "fixtures" / "step3_served_shape.json"


def _scene(db: Session, scene_id: str, **kw: object) -> None:
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date,"
            " bbox, cog_url, thumbnail_url, resolution_m, cloud_cover_pct,"
            " platform, provenance, fetched_at)"
            " VALUES (:id, :source, :collection, :item_id, :capture_date,"
            " :bbox, :cog_url, :thumbnail_url, :resolution_m, :cloud_cover_pct,"
            " :platform, :provenance, :fetched_at)"
        ),
        {
            "id": scene_id,
            "bbox": None,
            "thumbnail_url": None,
            "resolution_m": None,
            "cloud_cover_pct": None,
            "platform": None,
            "provenance": "snapshot",
            "fetched_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            **kw,
        },
    )


def _parcel_scene(
    db: Session,
    ps_id: str,
    *,
    source: str,
    group_key: str,
    scene_id: str,
    mosaic: list[str] | None = None,
) -> None:
    db.execute(
        text(
            "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id,"
            " mosaic_scene_ids, selected_at, selected_by)"
            " VALUES (:id, :parcel_id, :source, :group_key, :scene_id,"
            " :mosaic, :selected_at, NULL)"
        ),
        {
            "id": ps_id,
            "parcel_id": str(PARCEL_ID),
            "source": source,
            "group_key": group_key,
            "scene_id": scene_id,
            "mosaic": json.dumps(mosaic) if mosaic else None,
            "selected_at": datetime(2026, 2, 2, tzinfo=UTC).isoformat(),
        },
    )


@pytest.fixture
def served(db: Session) -> Session:
    """A parcel whose two shapes deliberately disagree, in both directions."""
    db.execute(
        text(
            "INSERT INTO parcels (id, address, normalized_address, latitude, longitude)"
            " VALUES (:id, :a, :a, 39.7, -105.0)"
        ),
        {"id": str(PARCEL_ID), "a": "1 Cutover St, Denver, CO 80202"},
    )

    _scene(
        db,
        SCENE_LANDSAT,
        source="landsat",
        collection="landsat-c2-l2",
        item_id="LC08_L2SP_2020",
        capture_date="2020-07-04",
        cog_url="https://example.com/landsat-2020.json",
        resolution_m=30.0,
        cloud_cover_pct=3.5,
    )
    _scene(
        db,
        SCENE_NAIP,
        source="naip",
        collection="naip",
        item_id="co_m_naip_2021",
        capture_date="2021-08-01",
        cog_url="https://example.com/naip-2021-primary.tif",
        thumbnail_url="https://example.com/naip-2021.png",
        resolution_m=0.6,
    )
    _scene(
        db,
        SCENE_TILE_A,
        source="naip",
        collection="naip",
        item_id="co_m_naip_2021_tile_a",
        capture_date="2021-08-01",
        cog_url="https://example.com/naip-2021-tile-a.tif",
    )
    _scene(
        db,
        SCENE_TILE_B,
        source="naip",
        collection="naip",
        item_id="co_m_naip_2021_tile_b",
        capture_date="2021-08-01",
        cog_url="https://example.com/naip-2021-tile-b.tif",
    )
    _scene(
        db,
        SCENE_TOPO,
        source="usgs_topo",
        collection="usgs-topo",
        item_id="CO_Denver_1965",
        capture_date="1965-01-01",
        cog_url="https://example.com/topo-1965.tif",
    )
    # A served period that exists only because ``parcel_scenes`` says so.
    _scene(
        db,
        SCENE_NEW_ONLY,
        source="sentinel2",
        collection="sentinel-2-l2a",
        item_id="S2A_new_only_2024",
        capture_date="2024-05-05",
        cog_url="https://example.com/s2-2024.tif",
        resolution_m=10.0,
    )

    _parcel_scene(db, PS_LANDSAT, source="landsat", group_key="2020", scene_id=SCENE_LANDSAT)
    _parcel_scene(
        db,
        PS_NAIP,
        source="naip",
        group_key="2021",
        scene_id=SCENE_NAIP,
        mosaic=[SCENE_TILE_A, SCENE_TILE_B],
    )
    _parcel_scene(db, PS_TOPO, source="usgs_topo", group_key="1960s", scene_id=SCENE_TOPO)
    _parcel_scene(db, PS_NEW_ONLY, source="sentinel2", group_key="2024", scene_id=SCENE_NEW_ONLY)

    db.flush()
    return db


# ── The five serving sites, each against a fixture that separates the tables ──


def test_the_listing_serves_every_parcel_scenes_row_in_capture_order(served: Session) -> None:
    rows = imagery_service.get_served_scenes(served, PARCEL_ID)

    ids = [str(r.id) for r in rows]
    assert ids == [PS_TOPO, PS_LANDSAT, PS_NAIP, PS_NEW_ONLY], "capture_date ASC"
    assert "S2A_new_only_2024" in {r.stac_item_id for r in rows}


def test_the_listing_filters_read_the_new_tables_columns(served: Session) -> None:
    by_source = imagery_service.get_served_scenes(served, PARCEL_ID, source="naip")
    assert [str(r.id) for r in by_source] == [PS_NAIP]

    windowed = imagery_service.get_served_scenes(
        served, PARCEL_ID, start_date=date(2020, 1, 1), end_date=date(2021, 12, 31)
    )
    assert [str(r.id) for r in windowed] == [PS_LANDSAT, PS_NAIP]


def test_by_id_resolves_a_parcel_scenes_id_and_nothing_else(served: Session) -> None:
    row = imagery_service.get_served_scene_by_id(served, uuid.UUID(PS_NEW_ONLY))
    assert row is not None
    assert row.stac_item_id == "S2A_new_only_2024"

    # The Titiler callback resolves the same id space the listing hands out,
    # and an id from outside it is None rather than an error.
    assert imagery_service.get_served_scene_by_id(served, uuid.UUID(UNKNOWN_SERVED_ID)) is None


def test_count_counts_served_periods_not_scenes(served: Session) -> None:
    # A mosaic is one row, not three — the same semantics the old count had,
    # where the extra tiles lived in additional_cog_urls rather than in rows.
    assert imagery_service.count_served_scenes(served, PARCEL_ID, "naip") == 1
    assert len(imagery_service.get_served_scenes(served, PARCEL_ID, source="naip")) == 1

    assert imagery_service.count_served_scenes(served, PARCEL_ID, "landsat") == 1
    assert imagery_service.count_served_scenes(served, PARCEL_ID, "sentinel2") == 1


def test_featured_bounds_come_from_parcel_scenes(served: Session) -> None:
    bounds = imagery_service.served_scene_bounds(served, [str(PARCEL_ID)])
    # Earliest is the 1965 topo row and latest the 2024 sentinel2 row.
    assert bounds[str(PARCEL_ID)] == (PS_TOPO, PS_NEW_ONLY)


def test_parcels_serving_source_comes_from_parcel_scenes(served: Session) -> None:
    assert imagery_service.parcels_serving_source(served, "landsat") == [PARCEL_ID]
    assert imagery_service.parcels_serving_source(served, "sentinel2") == [PARCEL_ID]
    assert imagery_service.parcels_serving_source(served, "naip") == [PARCEL_ID]


# ── Mosaic order ──────────────────────────────────────────────────────────────


def test_mosaic_urls_come_back_in_mosaic_scene_ids_order(served: Session) -> None:
    (naip,) = imagery_service.get_served_scenes(served, PARCEL_ID, source="naip")
    assert naip.additional_cog_urls == [
        "https://example.com/naip-2021-tile-a.tif",
        "https://example.com/naip-2021-tile-b.tif",
    ]

    # Reversing the stored array reverses the reconstructed list. Resolving
    # the ids without preserving their order passes the assertion above by
    # accident and fails this one.
    served.execute(
        text("UPDATE parcel_scenes SET mosaic_scene_ids = :m WHERE id = :id"),
        {"m": json.dumps([SCENE_TILE_B, SCENE_TILE_A]), "id": PS_NAIP},
    )
    (naip,) = imagery_service.get_served_scenes(served, PARCEL_ID, source="naip")
    assert naip.additional_cog_urls == [
        "https://example.com/naip-2021-tile-b.tif",
        "https://example.com/naip-2021-tile-a.tif",
    ]


def test_a_row_with_no_mosaic_has_no_additional_cog_urls(served: Session) -> None:
    (landsat,) = imagery_service.get_served_scenes(served, PARCEL_ID, source="landsat")
    assert landsat.additional_cog_urls is None


# ── Shape freeze ──────────────────────────────────────────────────────────────


def _freeze(rows: list[imagery_service.ServedSceneRow]) -> list[dict[str, object]]:
    """A served row as JSON, with the one field the cutover changes tokenised.

    ``id`` is the predicted divergence: it is ``parcel_scenes.id`` after the
    cutover where it was ``imagery_snapshots.id`` before, so freezing the
    literal value would freeze the very thing that had to change. Everything
    else is compared verbatim.
    """
    out = []
    for row in rows:
        d = asdict(row)
        d["id"] = "<served-id>"
        d["parcel_id"] = str(d["parcel_id"])
        d["capture_date"] = d["capture_date"].isoformat()
        out.append(d)
    return out


def test_the_served_row_shape_is_byte_identical_to_the_frozen_capture(
    served: Session,
) -> None:
    """The row shape is unchanged by the cutover, field for field.

    ``tests/fixtures/step3_served_shape.json`` was captured from the **old**
    read path — ``get_imagery_snapshots`` over an ``imagery_snapshots``
    mirror of this fixture — in the commit before the old reads were deleted,
    which is the only moment at which it could be. It is the contract the
    listing endpoint, the preview renderer and the Titiler callback all build
    their responses out of.
    """
    frozen = json.loads(GOLDEN.read_text())
    assert _freeze(imagery_service.get_served_scenes(served, PARCEL_ID)) == frozen


# ── The measurement hook that used to be here ─────────────────────────────────
#
# ``test_the_reconcilers_read_of_imagery_snapshots_is_logged`` asserted that
# the one legitimate reader left after step 3 named itself, so a cooling period
# could count it. Step 4's cutover deleted that reader, and the event with it:
# there is no caller to name, and an event that never fires is not a
# measurement. The counter half — ``scripts/snapshot_reads.py`` over
# ``pg_stat_user_tables`` — is what carries the cooling claim now, and it is
# stronger unaided than it was as half of a pair, because the expected value it
# reports is zero from anything rather than "only the reconciler".
