"""The selection write path: ``scenes`` and ``parcel_scenes``.

Steps 2 and 4 of the imagery-normalization ADR. Step 2 made
``reconcile_source_snapshots`` write these two tables *alongside* the
denormalized one, and this file was ``test_scene_dual_write.py``; step 4
deleted the old write, so what is left is not a dual-write and the file is
named for what it tests. Every test is written to the delete-the-fix standard:
each names the line whose removal makes it fail, and each was confirmed
failing with that line removed.

**What step 4 changed here, beyond deleting assertions.** Step 2's parity
tests compared the two shapes against each other — the strongest check
available while both existed, and worthless once one does. They are replaced
by tests that assert the served rows directly against what the fetch loop
selected, which is the property parity was standing in for.

The transactionality test at the bottom is the one that got *stronger*: it now
covers the ledger as well, because step 4 folded the ``ok`` rows into the same
commit (STATUS.md NORM-14).
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.imagery import (
    SelectedScene,
    normalize_resolution_m,
    reconcile_source_snapshots,
)

_BBOX = (-105.0, 39.0, -104.0, 40.0)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _insert_parcel(db: Session, parcel_id: uuid.UUID) -> None:
    db.execute(
        text(
            "INSERT INTO parcels (id, address, latitude, longitude)"
            " VALUES (:id, '1 Test St', 39.5, -104.5)"
        ),
        {"id": str(parcel_id)},
    )


def _scene(item_id: str, capture_date: date, **overrides: Any) -> SelectedScene:
    fields: dict[str, Any] = {
        "source": "landsat",
        "collection": "landsat-c2-l2",
        "item_id": item_id,
        "capture_date": capture_date,
        "cog_url": f"https://example.com/{item_id}.tif",
    }
    fields.update(overrides)
    return SelectedScene(**fields)


def _parcel_scene_rows(db: Session, parcel_id: uuid.UUID) -> list[Any]:
    return list(
        db.execute(
            text(
                "SELECT ps.id, ps.source, ps.group_key, ps.scene_id, ps.mosaic_scene_ids,"
                "       ps.selected_by, s.item_id, s.collection"
                " FROM parcel_scenes ps JOIN scenes s ON s.id = ps.scene_id"
                " WHERE ps.parcel_id = :p"
            ),
            {"p": str(parcel_id)},
        ).all()
    )


def _mosaic_ids(value: object) -> list[str]:
    if isinstance(value, str):
        return [str(v) for v in json.loads(value)]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


# ── Parity: the two shapes describe the same selection ────────────────────────


def _seed_request(
    factory: sessionmaker[Session],
    sources: tuple[str, ...],
) -> tuple[uuid.UUID, uuid.UUID]:
    parcel_id = uuid.uuid4()
    request_id = uuid.uuid4()
    with factory() as db:
        _insert_parcel(db, parcel_id)
        db.execute(
            text(
                "INSERT INTO timeline_requests (id, parcel_id, status)"
                " VALUES (:id, :parcel_id, 'processing')"
            ).bindparams(bindparam("id", type_=Uuid())),
            {"id": request_id, "parcel_id": str(parcel_id)},
        )
        for source in sources:
            db.execute(
                text(
                    "INSERT INTO timeline_request_tasks"
                    " (id, timeline_request_id, source, status)"
                    " VALUES (:id, :request_id, :source, 'processing')"
                ).bindparams(bindparam("id", type_=Uuid()), bindparam("request_id", type_=Uuid())),
                {"id": uuid.uuid4(), "request_id": request_id, "source": source},
            )
        db.commit()
    return parcel_id, request_id


def _naip_item(item_id: str, dt: str, bbox: tuple[float, float, float, float], gsd: float) -> Any:
    w, s, e, n = bbox
    return {
        "id": item_id,
        "properties": {"datetime": dt, "gsd": gsd},
        "assets": {"image": {"href": f"https://naip.example/{item_id}.tif"}},
        "bbox": [w, s, e, n],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
    }


def _naip_cfg() -> dict[str, Any]:
    from app.services import stac as stac_service

    return {
        "source": "naip",
        "collection": "naip",
        "start_date": "2020-01-01",
        "max_items": 50,
        "query": None,
        "selector": stac_service.select_naip_items,
        "selection_scope": "year",
        # The NORM-9 constant. Every test below that asserts a real gsd
        # reaches the database is asserting this value did *not* win.
        "resolution_m": 1.0,
        "chunk_by_year": False,
        "use_viewport_filter": True,
    }


async def _run_naip(
    factory: sessionmaker[Session],
    parcel_id: uuid.UUID,
    request_id: uuid.UUID,
    items: list[Any],
) -> int:
    """Drive the real NAIP fetch loop over a fixed item list.

    Step 2's version took a ``snapshot_writes`` mock, because
    ``additional_cog_urls`` was a PostgreSQL array SQLite could not bind and
    the mosaic test had to read the URL array off the call rather than out of
    the database. Step 4 deleted that column with its table; a mosaic is
    ``mosaic_scene_ids`` now, which SQLite stores as JSON, so the mock and the
    ``extract_bbox_wkt`` patch that went with it are both gone — the write
    path under test is PostGIS-free on SQLite by construction
    (``_ensure_scene``'s ``_is_postgres`` branch).
    """
    from app.tasks.timeline import _fetch_source

    async def mock_search(**_: object) -> list[Any]:
        return items

    patches = [
        patch("app.db.SessionLocal", factory),
        patch(
            "app.tasks.timeline._search_stac_with_retry",
            new_callable=AsyncMock,
            side_effect=mock_search,
        ),
        patch(
            "app.tasks.timeline.stac_service.filter_items_intersecting_bbox",
            side_effect=lambda raw, viewport: raw,
        ),
        patch(
            "app.tasks.timeline.stac_service.filter_groups_containing_point",
            side_effect=lambda groups, lat, lng: (groups, []),
        ),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return await _fetch_source(
            _naip_cfg(), _BBOX, _BBOX, parcel_id, request_id, lat=39.5, lng=-104.5
        )


@pytest.mark.asyncio
async def test_a_pipeline_run_writes_the_periods_it_selected(
    committing_db: sessionmaker[Session],
) -> None:
    """The fetch loop's selection reaches ``parcel_scenes``, group for group.

    Step 2 asserted this as *parity* between two shapes, which was the
    strongest check available while both existed and is not available now.
    The property parity stood in for is this one: every group the selector
    picked is a served row naming that group's item, and nothing else is.

    Delete-the-fix: remove the ``_write_selection_shapes`` call in
    ``reconcile_source_snapshots`` and ``parcel_scenes`` is empty while the
    loop reports two items saved.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))

    saved = await _run_naip(
        committing_db,
        parcel_id,
        request_id,
        [
            _naip_item("naip_2021_a", "2021-07-01T00:00:00Z", _BBOX, 0.6),
            _naip_item("naip_2022_a", "2022-07-01T00:00:00Z", _BBOX, 0.3),
        ],
    )

    with committing_db() as db:
        served = {
            (r.source, r.group_key): (r.collection, r.item_id)
            for r in _parcel_scene_rows(db, parcel_id)
        }

    assert saved == 2, "the fixture selected nothing; the test proves nothing"
    assert served == {
        ("naip", "2021"): ("naip", "naip_2021_a"),
        ("naip", "2022"): ("naip", "naip_2022_a"),
    }


@pytest.mark.asyncio
async def test_pipeline_rows_carry_the_selecting_sha_and_a_footprint(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: ``selected_by=selected_by`` and the ``footprint`` column
    in ``_ensure_scene``'s INSERT.

    ``selected_by`` NULL is what a *backfilled* row looks like; a
    pipeline-written row knows which image chose it. The footprint is the
    reason a pipeline-written scene never needs the enrichment pass.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))
    await _run_naip(
        committing_db,
        parcel_id,
        request_id,
        [_naip_item("naip_2021_a", "2021-07-01T00:00:00Z", _BBOX, 0.6)],
    )

    with committing_db() as db:
        row = db.execute(
            text(
                "SELECT ps.selected_by, s.provenance, s.footprint, s.platform"
                " FROM parcel_scenes ps JOIN scenes s ON s.id = ps.scene_id"
                " WHERE ps.parcel_id = :p"
            ),
            {"p": str(parcel_id)},
        ).one()

    assert row.selected_by, "selected_by must carry the running image's sha"
    assert row.provenance == "selection"
    assert row.footprint is not None, "the selector had the item; the footprint is free"
    assert row.platform is None, "NAIP item ids name no satellite"


@pytest.mark.asyncio
async def test_a_multi_tile_naip_year_catalogues_every_tile(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: the ``mosaic_ids`` comprehension in
    ``_write_selection_shapes``.

    ADR rule 5 at the pipeline: every tile of a mosaic is a first-class scene,
    referenced rather than stored as a URL. This is the write that stops the
    synthesized-candidate class (STEP1-REPORT F1) from growing.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))
    west = (-105.0, 39.0, -104.5, 40.0)
    east = (-104.5, 39.0, -104.0, 40.0)

    await _run_naip(
        committing_db,
        parcel_id,
        request_id,
        [
            _naip_item("naip_2021_west", "2021-07-01T00:00:00Z", west, 0.6),
            _naip_item("naip_2021_east", "2021-07-02T00:00:00Z", east, 0.6),
        ],
    )

    with committing_db() as db:
        rows = _parcel_scene_rows(db, parcel_id)
        assert len(rows) == 1, "one year, one selection row"
        mosaic = _mosaic_ids(rows[0].mosaic_scene_ids)
        assert len(mosaic) == 1, "the second tile is an additional scene reference"
        assert str(rows[0].scene_id) not in mosaic, "the primary is not in its own mosaic"

        catalogued = {
            r.item_id
            for r in db.execute(text("SELECT item_id FROM scenes WHERE collection = 'naip'")).all()
        }
        assert catalogued == {"naip_2021_west", "naip_2021_east"}

        dangling = db.execute(
            text("SELECT COUNT(*) FROM scenes WHERE id = :id"), {"id": mosaic[0]}
        ).scalar()
        assert dangling == 1, "every mosaic reference resolves to a scene"

        referenced = db.execute(
            text("SELECT cog_url FROM scenes WHERE id = :id"), {"id": mosaic[0]}
        ).scalar()
        primary_url = db.execute(
            text("SELECT cog_url FROM scenes WHERE id = :id"), {"id": str(rows[0].scene_id)}
        ).scalar()

    # The reference resolves to the *other* tile — the one that is not the
    # primary — at its real URL. Step 2 compared this against the old shape's
    # ``additional_cog_urls``; there is one representation now, so the check
    # is that it names a real tile and not the primary again.
    assert referenced in {
        "https://naip.example/naip_2021_west.tif",
        "https://naip.example/naip_2021_east.tif",
    }
    assert referenced != primary_url


@pytest.mark.asyncio
async def test_naip_resolution_is_the_items_gsd_not_the_source_constant(
    committing_db: sessionmaker[Session],
) -> None:
    """NORM-9 and NORM-11 at the pipeline, both shapes.

    Delete-the-fix: drop ``normalize_resolution_m`` from ``from_stac_item``,
    or make ``default_resolution_m`` win over the item's ``gsd`` there, and
    this fails. The fixture's gsd is the exact noisy double Planetary Computer
    served for ``az_m_3311151_nw_12_.6_20170604_20171128``.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))
    await _run_naip(
        committing_db,
        parcel_id,
        request_id,
        [_naip_item("naip_2021_a", "2021-07-01T00:00:00Z", _BBOX, 0.6000000000000011)],
    )

    with committing_db() as db:
        scene_res = db.execute(
            text("SELECT resolution_m FROM scenes WHERE collection = 'naip'")
        ).scalar()

    assert scene_res == 0.6, "the constant 1.0 must not win over the item's gsd"


def test_the_rounding_rule_normalizes_every_observed_gsd() -> None:
    """NORM-11's rule, against the values production actually holds.

    The seven noisy spellings are ENRICH-PROD-REPORT-2.md F2's, verbatim.
    """
    assert normalize_resolution_m(0.5999999999999901) == 0.6
    assert normalize_resolution_m(0.5999999999999975) == 0.6
    assert normalize_resolution_m(0.5999999999999994) == 0.6
    assert normalize_resolution_m(0.6000000000000011) == 0.6
    assert normalize_resolution_m(0.6000000000000012) == 0.6
    assert normalize_resolution_m(0.600000000000007) == 0.6
    assert normalize_resolution_m(0.6000000000000097) == 0.6

    # And it leaves every real resolution alone: nothing merges.
    for nominal in (0.3, 0.5, 0.6, 1.0, 10.0, 30.0):
        assert normalize_resolution_m(nominal) == nominal
    assert normalize_resolution_m(None) is None
    assert normalize_resolution_m("0.6") is None


def test_an_item_without_gsd_keeps_the_source_constant() -> None:
    """The fallback, stated as a test so removing it is visible.

    Landsat and Sentinel-2 items that carry no item-level ``gsd`` keep the
    30 m / 10 m the source config has always written.
    """
    item: dict[str, object] = {
        "id": "LC08_2020",
        "properties": {"datetime": "2020-07-01T00:00:00Z"},
        "bbox": [-105.0, 39.0, -104.0, 40.0],
    }
    selection = SelectedScene.from_stac_item(
        item,
        source="landsat",
        collection="landsat-c2-l2",
        cog_url="https://example.com/x.tif",
        default_resolution_m=30.0,
    )
    assert selection.resolution_m == 30.0
    assert selection.platform == "LC08"
    assert selection.footprint_wkt is None, "no geometry is a NULL footprint, not a refusal"


# ── Insert-only, replacement, and the absent-group rule ───────────────────────


def test_re_encountering_an_item_does_not_rewrite_its_scene(db: Session) -> None:
    """Insert-only. Delete-the-fix: change ``ON CONFLICT DO NOTHING`` to
    ``DO UPDATE`` in ``_ensure_scene``.

    The pipeline meets the same Landsat scene once per parcel serving it.
    Re-encountering an item is not evidence its stored facts are stale, and
    refreshing them is a separate mechanism that does not exist yet.
    """
    parcel_id, other_parcel = uuid.uuid4(), uuid.uuid4()
    _insert_parcel(db, parcel_id)
    _insert_parcel(db, other_parcel)

    first = _scene(
        "LC08_2020", date(2020, 7, 1), cloud_cover_pct=5.0, resolution_m=30.0, thumbnail_url="a"
    )
    reconcile_source_snapshots(db, parcel_id, "landsat", [first])

    second = _scene(
        "LC08_2020",
        date(2020, 7, 1),
        cog_url="https://example.com/CHANGED.tif",
        cloud_cover_pct=90.0,
        resolution_m=1.0,
        thumbnail_url="b",
    )
    reconcile_source_snapshots(db, other_parcel, "landsat", [second])

    rows = db.execute(
        text("SELECT cog_url, cloud_cover_pct, resolution_m, thumbnail_url FROM scenes")
    ).all()
    assert len(rows) == 1, "one item, one scene, however many parcels serve it"
    assert rows[0].cog_url == "https://example.com/LC08_2020.tif"
    assert rows[0].cloud_cover_pct == 5.0
    assert rows[0].resolution_m == 30.0
    assert rows[0].thumbnail_url == "a"

    # Both parcels serve it, which is the point of the split.
    assert len(_parcel_scene_rows(db, parcel_id)) == 1
    assert len(_parcel_scene_rows(db, other_parcel)) == 1


def test_a_changed_selection_updates_the_row_in_place(db: Session) -> None:
    """Replacement. Delete-the-fix: drop the UPDATE branch of
    ``_upsert_parcel_scene`` and the row keeps pointing at the old scene.

    UNIQUE (parcel, source, group_key) makes replacement an update, so the
    selection row keeps its primary key; the superseded *scene* survives,
    because scenes are the catalogue and a catalogue does not forget.
    """
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    reconcile_source_snapshots(db, parcel_id, "landsat", [_scene("LT05_A_1987", date(1987, 6, 1))])
    before = _parcel_scene_rows(db, parcel_id)[0]

    # The Landsat re-validation case: a different item for the same year.
    superseded = reconcile_source_snapshots(
        db, parcel_id, "landsat", [_scene("LT05_B_1987", date(1987, 7, 4))]
    )

    after_rows = _parcel_scene_rows(db, parcel_id)
    assert superseded == 1
    assert len(after_rows) == 1
    after = after_rows[0]
    assert str(after.id) == str(before.id), "same selection row, not delete-and-reinsert"
    assert str(after.scene_id) != str(before.scene_id)
    assert after.item_id == "LT05_B_1987"

    surviving = {r.item_id for r in db.execute(text("SELECT item_id FROM scenes")).all()}
    assert surviving == {"LT05_A_1987", "LT05_B_1987"}, "scenes are append-only here"


def test_an_unchanged_selection_leaves_selected_at_alone(db: Session) -> None:
    """Delete-the-fix: drop the ``unchanged`` early return in
    ``_upsert_parcel_scene``.

    ``selected_at`` means "when this parcel came to serve this scene for this
    period". A sweep that re-picks the same scene has not made a selection.
    """
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    selection = _scene("LC08_2020", date(2020, 7, 1))
    reconcile_source_snapshots(db, parcel_id, "landsat", [selection])
    first = db.execute(text("SELECT selected_at FROM parcel_scenes")).scalar()

    reconcile_source_snapshots(db, parcel_id, "landsat", [selection])
    second = db.execute(text("SELECT selected_at FROM parcel_scenes")).scalar()

    assert first == second


def test_a_group_absent_from_the_selection_survives(db: Session) -> None:
    """The absent-group rule. Delete-the-fix: drop the ``if group_key in
    groups`` guard in ``reconcile_source_snapshots`` and the 1987 row is
    counted superseded, so the run reports 1 rather than 0.

    A year missing from a run usually means that chunk's search failed
    (NORM-3), and deleting — or now, silently repointing — on that basis turns
    a transient upstream error into permanent loss.
    """
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    reconcile_source_snapshots(
        db,
        parcel_id,
        "landsat",
        [_scene("LT05_1987", date(1987, 6, 1)), _scene("LC08_2015", date(2015, 6, 1))],
    )
    assert len(_parcel_scene_rows(db, parcel_id)) == 2

    # Only 2015 came back this run.
    superseded = reconcile_source_snapshots(
        db, parcel_id, "landsat", [_scene("LC08_2015", date(2015, 6, 1))]
    )

    assert superseded == 0
    assert {r.item_id for r in _parcel_scene_rows(db, parcel_id)} == {"LT05_1987", "LC08_2015"}
    assert {r.group_key for r in _parcel_scene_rows(db, parcel_id)} == {"1987", "2015"}


def test_a_suppressed_group_loses_its_served_row(db: Session) -> None:
    """Delete-the-fix: drop the ``_delete_parcel_scene_for_item`` loop.

    The NAIP point-coverage gate is the only thing that may remove a served
    row for a group this run did not select, and since step 4 this is the
    **only** delete the reconciler issues at all — every other supersession is
    an update in place.
    """
    parcel_id = uuid.uuid4()
    _insert_parcel(db, parcel_id)
    reconcile_source_snapshots(
        db,
        parcel_id,
        "naip",
        [
            SelectedScene(
                source="naip",
                collection="naip",
                item_id="naip_2023_tile",
                capture_date=date(2023, 8, 1),
                cog_url="https://example.com/naip_2023_tile.tif",
            )
        ],
    )
    assert len(_parcel_scene_rows(db, parcel_id)) == 1

    # This run selected nothing and positively identified the tile as not
    # covering the parcel.
    superseded = reconcile_source_snapshots(
        db,
        parcel_id,
        "naip",
        [],
        suppressed={"2023": {"naip_2023_tile"}},
    )

    assert superseded == 1
    assert _parcel_scene_rows(db, parcel_id) == []
    # The scene itself stays catalogued: it exists, it just does not serve
    # this parcel.
    assert db.execute(text("SELECT COUNT(*) FROM scenes")).scalar() == 1


# ── Transactionality: NORM-14, closed ─────────────────────────────────────────


def test_a_failure_before_the_parcel_scenes_write_commits_nothing(
    committing_db: sessionmaker[Session],
) -> None:
    """Delete-the-fix: move ``db.commit()`` above ``_write_selection_shapes``.

    Observed from a *separate* session, so "not committed" means not visible
    to anyone rather than merely not flushed.
    """
    parcel_id = uuid.uuid4()
    with committing_db() as db:
        _insert_parcel(db, parcel_id)
        reconcile_source_snapshots(
            db, parcel_id, "landsat", [_scene("LT05_A_1987", date(1987, 6, 1))]
        )

    boom = RuntimeError("the selection write failed")
    with (
        pytest.raises(RuntimeError, match="selection write"),
        patch("app.services.imagery._write_selection_shapes", side_effect=boom),
        committing_db() as db,
    ):
        reconcile_source_snapshots(
            db,
            parcel_id,
            "landsat",
            [_scene("LT05_A_1987", date(1987, 6, 1))],
            suppressed={"1987": {"LT05_A_1987"}},
        )

    with committing_db() as db:
        rows = _parcel_scene_rows(db, parcel_id)
        assert [r.item_id for r in rows] == ["LT05_A_1987"], (
            "the suppressed delete must have rolled back with the failed write"
        )


@pytest.mark.asyncio
async def test_a_crash_in_the_persist_loop_commits_no_ok_ledger_row(
    committing_db: sessionmaker[Session],
) -> None:
    """The NORM-14 resolution, asserted end to end through the fetch loop.

    **What this replaces.** Until ADR step 4 the persist loop committed once
    per group, inside ``upsert_imagery_snapshot``, and the ``ok`` ledger row
    was written uncommitted just before it so the two landed together. That
    made ``ok`` honest about *its own group* and left a window between the
    loop and the reconcile: a crash there committed ``ok`` rows and snapshot
    rows for the groups already done, with no ``parcel_scenes`` row for any of
    them. NORM-14 accepted that window because the next run repaired it.

    Step 4 deleted the per-row write and its commit. The ``ok`` rows now ride
    the reconciler's transaction — the same one that writes the served rows —
    so the window is not narrowed, it is **gone**: a crash anywhere before that
    commit leaves the source exactly as the run found it.

    Delete-the-fix: put a ``db.commit()`` back in the persist loop after
    ``record_year_outcome`` and the ``ok`` row survives the crash, with no
    served row to justify it — which is precisely the state the ledger must
    never be able to reach.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))

    boom = RuntimeError("the selection write failed")
    with patch("app.services.imagery._write_selection_shapes", side_effect=boom):
        # _fetch_source catches, marks the task failed and returns 0; the
        # session's transaction is never committed.
        saved = await _run_naip(
            committing_db,
            parcel_id,
            request_id,
            [
                _naip_item("naip_2021_a", "2021-07-01T00:00:00Z", _BBOX, 0.6),
                _naip_item("naip_2022_a", "2022-07-01T00:00:00Z", _BBOX, 0.3),
            ],
        )

    assert saved == 0
    with committing_db() as db:
        assert _parcel_scene_rows(db, parcel_id) == []
        outcomes = [
            r.outcome
            for r in db.execute(
                text(
                    "SELECT tty.outcome FROM timeline_task_years tty"
                    " JOIN timeline_request_tasks t ON t.id = tty.task_id"
                    " WHERE t.timeline_request_id = :r"
                ).bindparams(bindparam("r", type_=Uuid())),
                {"r": request_id},
            ).all()
        ]
    assert "ok" not in outcomes, "an ok row committed for work that was rolled back"


@pytest.mark.asyncio
async def test_a_successful_run_commits_its_ok_rows_with_its_served_rows(
    committing_db: sessionmaker[Session],
) -> None:
    """The other half: the transaction that rolls back together commits together.

    A test that only proves "nothing is written on failure" is also passed by
    code that never writes anything. This is the control.
    """
    parcel_id, request_id = _seed_request(committing_db, ("naip",))

    await _run_naip(
        committing_db,
        parcel_id,
        request_id,
        [
            _naip_item("naip_2021_a", "2021-07-01T00:00:00Z", _BBOX, 0.6),
            _naip_item("naip_2022_a", "2022-07-01T00:00:00Z", _BBOX, 0.3),
        ],
    )

    with committing_db() as db:
        served = {r.group_key for r in _parcel_scene_rows(db, parcel_id)}
        ok_groups = {
            r.group_key
            for r in db.execute(
                text(
                    "SELECT tty.group_key FROM timeline_task_years tty"
                    " JOIN timeline_request_tasks t ON t.id = tty.task_id"
                    " WHERE t.timeline_request_id = :r AND tty.outcome = 'ok'"
                ).bindparams(bindparam("r", type_=Uuid())),
                {"r": request_id},
            ).all()
        }

    assert served == {"2021", "2022"}
    assert ok_groups == served, "every ok row names a group that is actually served"
