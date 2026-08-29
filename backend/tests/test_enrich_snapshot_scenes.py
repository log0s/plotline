"""Tests for scripts/enrich_snapshot_scenes.py.

Loaded by path the way ``test_enrich_synthesized_scenes.py`` loads its
subject. **No network:** the STAC layer is one injected object with a
``get_item`` and an ``aclose``, and every test supplies a fake whose catalogue
is a dict.

Delete-the-fix, one clause per test:

* the ``source <> 'usgs_topo'`` filter in ``load_queue`` — remove it and
  ``test_topo_rows_are_excluded_from_the_queue`` fetches a
  ``usgs-historical-topo`` id against the Planetary Computer, which has no such
  collection, and records a 404 finding for every topo row in the table.
* the ``footprint IS NULL`` marker in ``load_queue`` — remove it and
  ``test_second_run_on_a_done_queue_issues_no_requests`` re-fetches and
  re-writes every row the first run finished.
* the ``row.bbox_is_null`` guard in ``plan_row`` — remove it and
  ``test_existing_bbox_is_not_churned`` rewrites a bbox no finding names.
* the ``resolution is None`` branch in ``plan_row`` — remove it (write the
  normalised value unconditionally) and
  ``test_item_without_gsd_leaves_resolution_alone`` nulls out a correct
  stored resolution.
* the ``resolution != row.resolution_m`` guard — remove it and
  ``test_landsat_resolution_is_untouched_when_the_item_agrees`` counts a
  rewrite that changes nothing, which is the churn the NORM-13 heal is
  supposed to avoid.
* the ``normalize_resolution_m`` call — replace it with the raw ``gsd`` and
  ``test_naip_resolution_is_normalised_not_raw`` writes NORM-11's float noise
  back into the column.
* the ``fetched.outcome != "ok"`` early continue in ``apply_batch`` — remove
  it and ``test_404_and_403_leave_the_row_untouched`` raises on a None item
  instead of reporting two distinct findings.
* the ``extract_footprint_wkt`` complaint branch — remove it and
  ``test_multipolygon_item_is_reported_and_stays_in_the_queue`` writes a
  MultiPolygon into a ``geometry(POLYGON,4326)`` column.
* the per-batch ``db.commit()`` — remove it and ``test_each_batch_commits``
  sees no commits, which is a run that holds one transaction open over
  thousands of paced fetches and loses all of them to a kill. (The kill test
  below cannot carry this clause: it reads through the same session that did
  the writing, which sees uncommitted rows too.)
* the per-batch ``_write_report`` — remove it and
  ``test_report_is_written_after_every_batch`` finds no report at all after a
  kill, which is the capture NORM-8 is about.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from psycopg2 import OperationalError
from sqlalchemy import text
from sqlalchemy.orm import Session

_HERE = Path(__file__).resolve()
_SCRIPT = next(
    p / "scripts" / "enrich_snapshot_scenes.py"
    for p in _HERE.parents
    if (p / "scripts" / "enrich_snapshot_scenes.py").exists()
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("enrich_snapshot_scenes", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["enrich_snapshot_scenes"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]],
}
MULTIPOLYGON = {"type": "MultiPolygon", "coordinates": [POLYGON["coordinates"]]}

NAIP_ITEM = "md_m_3807708_se_18_030_20230901_20231018"
LANDSAT_ITEM = "LC08_L2SP_013030_20130930_02_T1"
S2_ITEM = "S2A_MSIL2A_20150909T183316_R127_T11SPV_20210412T073852"


def _item(
    item_id: str,
    *,
    capture: str = "2023-09-01",
    gsd: float | None = 0.3,
    geometry: dict[str, Any] | None = None,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {"datetime": f"{capture}T00:00:00Z"}
    if gsd is not None:
        properties["gsd"] = gsd
    return {
        "id": item_id,
        "geometry": POLYGON if geometry is None else geometry,
        "bbox": [-74.0, 40.7, -73.9, 40.8] if bbox is None else bbox,
        "properties": properties,
    }


class FakeStac:
    """The one PC call this pass makes, served from a dict. Counts requests."""

    def __init__(
        self,
        *,
        items: dict[str, dict[str, Any]] | None = None,
        statuses: dict[str, int] | None = None,
    ) -> None:
        self.items = items or {}
        self.statuses = statuses or {}
        self.gets: list[str] = []
        self.closed = False

    @property
    def requests(self) -> int:
        return len(self.gets)

    async def get_item(self, collection: str, item_id: str) -> tuple[int, dict[str, Any] | None]:
        self.gets.append(item_id)
        if item_id in self.items:
            return 200, self.items[item_id]
        return self.statuses.get(item_id, 404), None

    async def aclose(self) -> None:
        self.closed = True


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _insert_scene(
    db: Session,
    *,
    item_id: str,
    source: str = "naip",
    collection: str = "naip",
    provenance: str = "snapshot",
    capture_date: str = "2023-09-01",
    resolution_m: float | None = 1.0,
    footprint: str | None = None,
    bbox: str | None = None,
) -> str:
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, resolution_m, footprint, bbox, fetched_at)"
            " VALUES (:id, :source, :collection, :item_id, :capture_date, :cog_url,"
            " :provenance, :resolution_m, :footprint, :bbox, :now)"
        ),
        {
            "id": scene_id,
            "source": source,
            "collection": collection,
            "item_id": item_id,
            "capture_date": capture_date,
            "cog_url": f"https://example.invalid/{item_id}.tif",
            "provenance": provenance,
            "resolution_m": resolution_m,
            "footprint": footprint,
            "bbox": bbox,
            "now": "2026-08-01 12:00:00",
        },
    )
    return scene_id


def _run(
    db: Session,
    stac: Any,
    tmp_path: Path,
    *,
    execute: bool = True,
    batch_size: int = script.DEFAULT_BATCH_SIZE,
) -> Any:
    return script.run(
        db,
        execute=execute,
        report_path=tmp_path / "report.md",
        lookup=stac,
        batch_size=batch_size,
    )


def _scene(db: Session, scene_id: str) -> Any:
    return db.execute(
        text(
            "SELECT item_id, capture_date, footprint, bbox, resolution_m, provenance"
            " FROM scenes WHERE id = :id"
        ),
        {"id": scene_id},
    ).first()


# ── The matched path ──────────────────────────────────────────────────────────


def test_matched_row_gets_footprint_and_normalised_resolution(db: Session, tmp_path: Path) -> None:
    """The NORM-7 + NORM-13 heal, on one row: geometry in, 1.0 → the item's gsd."""
    scene_id = _insert_scene(db, item_id=NAIP_ITEM, bbox="SRID=4326;POLYGON((0 0,1 0,1 1,0 0))")
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM, gsd=0.3)})

    out = _run(db, stac, tmp_path)

    row = _scene(db, scene_id)
    assert row.footprint is not None
    assert "POLYGON" in row.footprint and "MULTI" not in row.footprint
    assert row.resolution_m == 0.3
    assert row.provenance == "snapshot"
    assert (out.written, out.footprints, out.resolutions) == (1, 1, 1)


def test_footprint_is_the_item_geometry_not_its_bbox(db: Session, tmp_path: Path) -> None:
    """The geometry audit's rule: the outline, never the envelope."""
    # A five-point non-rectangular polygon whose bbox envelope is a different shape.
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[-74.0, 40.7], [-73.9, 40.72], [-73.85, 40.8], [-74.0, 40.78], [-74.0, 40.7]]
        ],
    }
    scene_id = _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(
        items={NAIP_ITEM: _item(NAIP_ITEM, geometry=geometry, bbox=[-74.0, 40.7, -73.85, 40.8])}
    )

    _run(db, stac, tmp_path)

    footprint = _scene(db, scene_id).footprint
    assert "-73.85 40.8" in footprint  # a vertex only the geometry has
    assert footprint != script.extract_bbox_wkt(stac.items[NAIP_ITEM])


def test_naip_resolution_is_normalised_not_raw(db: Session, tmp_path: Path) -> None:
    """NORM-11: PC's float noise is rounded once, at write time."""
    scene_id = _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM, gsd=0.5999999999999901)})

    _run(db, stac, tmp_path)

    assert _scene(db, scene_id).resolution_m == 0.6


def test_existing_bbox_is_not_churned(db: Session, tmp_path: Path) -> None:
    """A bbox copied from a served row is not in question and is left alone."""
    stored = "SRID=4326;POLYGON((0 0,1 0,1 1,0 1,0 0))"
    scene_id = _insert_scene(db, item_id=NAIP_ITEM, bbox=stored)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})

    out = _run(db, stac, tmp_path)

    assert _scene(db, scene_id).bbox == stored
    assert out.bboxes == 0


def test_null_bbox_is_filled(db: Session, tmp_path: Path) -> None:
    scene_id = _insert_scene(db, item_id=NAIP_ITEM, bbox=None)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})

    out = _run(db, stac, tmp_path)

    assert (
        _scene(db, scene_id).bbox
        == "SRID=4326;POLYGON((-74.0 40.7,-73.9 40.7,-73.9 40.8,-74.0 40.8,-74.0 40.7))"
    )  # noqa: E501
    assert out.bboxes == 1


# ── Per-source resolution policy ──────────────────────────────────────────────


def test_landsat_resolution_is_untouched_when_the_item_agrees(db: Session, tmp_path: Path) -> None:
    """30.0 is a correct constant; a heal that rewrites it is churn, not a fix."""
    scene_id = _insert_scene(
        db,
        item_id=LANDSAT_ITEM,
        source="landsat",
        collection="landsat-c2-l2",
        resolution_m=30.0,
        capture_date="2013-09-30",
    )
    stac = FakeStac(items={LANDSAT_ITEM: _item(LANDSAT_ITEM, capture="2013-09-30", gsd=30)})

    out = _run(db, stac, tmp_path)

    row = _scene(db, scene_id)
    assert row.resolution_m == 30.0
    assert row.footprint is not None  # the footprint still lands
    assert (out.resolutions, out.footprints) == (0, 1)
    assert out.findings == []


def test_landsat_resolution_disagreement_is_a_reported_finding(db: Session, tmp_path: Path) -> None:
    """The item still wins — and a disagreement here is worth a human's attention."""
    scene_id = _insert_scene(
        db,
        item_id=LANDSAT_ITEM,
        source="landsat",
        collection="landsat-c2-l2",
        resolution_m=30.0,
        capture_date="2013-09-30",
    )
    stac = FakeStac(items={LANDSAT_ITEM: _item(LANDSAT_ITEM, capture="2013-09-30", gsd=15)})

    out = _run(db, stac, tmp_path)

    assert _scene(db, scene_id).resolution_m == 15.0
    assert len(out.findings) == 1
    assert "landsat" in out.findings[0] and "30.0" in out.findings[0]


def test_item_without_gsd_leaves_resolution_alone(db: Session, tmp_path: Path) -> None:
    """Sentinel-2 items carry no item-level gsd. None never overwrites a value."""
    scene_id = _insert_scene(
        db,
        item_id=S2_ITEM,
        source="sentinel2",
        collection="sentinel-2-l2a",
        resolution_m=10.0,
        capture_date="2015-09-09",
    )
    stac = FakeStac(items={S2_ITEM: _item(S2_ITEM, capture="2015-09-09", gsd=None)})

    out = _run(db, stac, tmp_path)

    row = _scene(db, scene_id)
    assert row.resolution_m == 10.0
    assert row.footprint is not None
    assert out.no_item_gsd["sentinel2"] == 1
    assert out.resolutions == 0


# ── Scope ─────────────────────────────────────────────────────────────────────


def test_topo_rows_are_excluded_from_the_queue(db: Session, tmp_path: Path) -> None:
    """usgs-historical-topo is TNM-sourced: there is no PC item to fetch."""
    topo = _insert_scene(
        db,
        item_id="topo_MD_Baltimore_1890",
        source="usgs_topo",
        collection="usgs-historical-topo",
        resolution_m=None,
        capture_date="1890-01-01",
    )
    naip = _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})

    out = _run(db, stac, tmp_path)

    assert stac.gets == [NAIP_ITEM]
    assert out.queue_size == 1
    assert out.excluded_topo == 1
    assert _scene(db, topo).footprint is None
    assert _scene(db, naip).footprint is not None


def test_enriched_and_selection_rows_are_not_in_the_queue(db: Session, tmp_path: Path) -> None:
    """Those rows were written with real item facts; only 'snapshot' is queued."""
    _insert_scene(db, item_id="enriched-item", provenance="enriched")
    _insert_scene(db, item_id="selection-item", provenance="selection")
    stac = FakeStac()

    out = _run(db, stac, tmp_path)

    assert (out.queue_size, stac.gets) == (0, [])


# ── Unresolved ids ────────────────────────────────────────────────────────────


def test_404_and_403_leave_the_row_untouched(db: Session, tmp_path: Path) -> None:
    """Both are findings about the catalogue, counted apart and written nowhere."""
    gone = _insert_scene(db, item_id="gone_item")
    forbidden = _insert_scene(db, item_id="va_m_3807708_se_18_1_20120511_20120709")
    stac = FakeStac(
        statuses={"gone_item": 404, "va_m_3807708_se_18_1_20120511_20120709": 403},
    )

    out = _run(db, stac, tmp_path)

    assert (out.unmatched_404, out.unmatched_403, out.written) == (1, 1, 0)
    assert _scene(db, gone).footprint is None
    assert _scene(db, gone).resolution_m == 1.0
    assert _scene(db, forbidden).footprint is None
    assert len(out.findings) == 2
    report = (tmp_path / "report.md").read_text()
    assert "item GET 404" in report and "item GET 403" in report


def test_capture_date_disagreement_is_reported_never_written(db: Session, tmp_path: Path) -> None:
    scene_id = _insert_scene(db, item_id=NAIP_ITEM, capture_date="2023-09-01")
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM, capture="2023-09-02")})

    out = _run(db, stac, tmp_path)

    assert str(_scene(db, scene_id).capture_date) == "2023-09-01"
    assert len(out.date_disagreements) == 1


def test_multipolygon_item_is_reported_and_stays_in_the_queue(db: Session, tmp_path: Path) -> None:
    """scenes.footprint is geometry(POLYGON,4326); a multipart outline cannot land."""
    scene_id = _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM, geometry=MULTIPOLYGON)})

    out = _run(db, stac, tmp_path)

    row = _scene(db, scene_id)
    assert row.footprint is None
    assert row.resolution_m == 0.3  # what could be healed still was
    assert len(out.anomalies) == 1
    assert script.load_queue(db)[0].id == scene_id  # still queued


# ── Idempotence and resume ────────────────────────────────────────────────────


def test_second_run_on_a_done_queue_issues_no_requests(db: Session, tmp_path: Path) -> None:
    _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})
    _run(db, stac, tmp_path)
    assert stac.gets == [NAIP_ITEM]

    again = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})
    out = _run(db, again, tmp_path)

    assert (again.gets, out.queue_size, out.written) == ([], 0, 0)


def test_a_killed_run_does_not_refetch_committed_rows(db: Session, tmp_path: Path) -> None:
    """The kill-and-resume property, as a unit test: batch 1 commits, batch 2 dies."""
    ids = [f"naip_item_{i}" for i in range(4)]
    scenes = {item_id: _insert_scene(db, item_id=item_id) for item_id in ids}
    catalog = {item_id: _item(item_id) for item_id in ids}

    class DyingStac(FakeStac):
        async def get_item(self, collection: str, item_id: str) -> Any:
            if len(self.gets) >= 2:
                raise KeyboardInterrupt("killed mid-run")
            return await super().get_item(collection, item_id)

    with pytest.raises(KeyboardInterrupt):
        _run(db, DyingStac(items=catalog), tmp_path, batch_size=2)

    done = [i for i in ids if _scene(db, scenes[i]).footprint is not None]
    assert done == ids[:2]

    resumed = FakeStac(items=catalog)
    out = _run(db, resumed, tmp_path, batch_size=2)

    assert sorted(resumed.gets) == ids[2:]
    assert out.written == 2
    assert all(_scene(db, scenes[i]).footprint is not None for i in ids)


def test_each_batch_commits(db: Session, tmp_path: Path) -> None:
    """One transaction per batch, not one over the whole run."""
    ids = [f"naip_item_{i}" for i in range(5)]
    for item_id in ids:
        _insert_scene(db, item_id=item_id)
    stac = FakeStac(items={item_id: _item(item_id) for item_id in ids})
    commits = 0
    real_commit = db.commit

    def counting_commit() -> None:
        nonlocal commits
        commits += 1
        real_commit()

    db.commit = counting_commit  # type: ignore[method-assign]  # a spy, restored below
    try:
        _run(db, stac, tmp_path, batch_size=2)
    finally:
        del db.commit

    assert commits == 3  # 2 + 2 + 1


def test_dry_run_writes_nothing_but_still_fetches(db: Session, tmp_path: Path) -> None:
    scene_id = _insert_scene(db, item_id=NAIP_ITEM)
    stac = FakeStac(items={NAIP_ITEM: _item(NAIP_ITEM)})

    out = _run(db, stac, tmp_path, execute=False)

    assert stac.gets == [NAIP_ITEM]
    assert out.written == 1  # what it *would* write
    row = _scene(db, scene_id)
    assert row.footprint is None and row.resolution_m == 1.0
    assert "Dry run" in (tmp_path / "report.md").read_text()


def test_report_is_written_after_every_batch(db: Session, tmp_path: Path) -> None:
    """A killed client takes stdout with it (NORM-8); the file survives."""
    ids = [f"naip_item_{i}" for i in range(4)]
    for item_id in ids:
        _insert_scene(db, item_id=item_id)
    catalog = {item_id: _item(item_id) for item_id in ids}

    class DyingStac(FakeStac):
        async def get_item(self, collection: str, item_id: str) -> Any:
            if len(self.gets) >= 2:
                raise KeyboardInterrupt("killed mid-run")
            return await super().get_item(collection, item_id)

    with pytest.raises(KeyboardInterrupt):
        _run(db, DyingStac(items=catalog), tmp_path, batch_size=2)

    report = (tmp_path / "report.md").read_text()
    assert "Incomplete" in report
    assert "| matched and written | 2 |" in report


def test_closes_the_lookup_even_when_a_batch_raises(db: Session, tmp_path: Path) -> None:
    _insert_scene(db, item_id=NAIP_ITEM)

    class DyingStac(FakeStac):
        async def get_item(self, collection: str, item_id: str) -> Any:
            raise KeyboardInterrupt("killed mid-run")

    stac = DyingStac()
    with pytest.raises(KeyboardInterrupt):
        _run(db, stac, tmp_path)

    assert stac.closed


# ── Pacing carries over from the extracted module ─────────────────────────────


def test_shared_lookup_still_splits_the_retry_policy_by_endpoint() -> None:
    """NORM-10 moved with the code; both scripts read one definition of it."""
    from scripts.shared import stac_fetch

    assert 403 not in stac_fetch._ITEM_RETRYABLE_STATUSES
    assert 403 in stac_fetch._SEARCH_RETRYABLE_STATUSES
    assert script.StacLookup is stac_fetch.StacLookup


def test_pacing_spaces_out_dispatches() -> None:
    """--min-interval-s bounds dispatch rate globally, not per worker."""
    lookup = script.StacLookup(concurrency=6, min_interval_s=0.05)
    stamps: list[float] = []

    async def fake_get(url: str) -> Any:
        stamps.append(asyncio.get_event_loop().time())
        raise RuntimeError("stop here; the pacer has already run")

    lookup._client.get = fake_get

    async def drive() -> None:
        for _ in range(4):
            with pytest.raises(RuntimeError):
                await lookup.get_item("naip", "x")
        await lookup.aclose()

    asyncio.run(drive())

    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(gap >= 0.04 for gap in gaps), gaps


# ── main()'s exit path (NORM-27) ───────────────────────────────────────────────
#
# `main` opens the DB session itself and derives its exit code from the run's
# outcome. These tests mock the DB layer's teardown (`SessionLocal`'s context
# manager) and `run` itself — no network, no real database — to isolate the
# exit-path logic from the work it wraps.


class _FakeSession:
    def __init__(self, *, raise_on_exit: BaseException | None) -> None:
        self._raise_on_exit = raise_on_exit

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None and self._raise_on_exit is not None:
            raise self._raise_on_exit
        return False


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    outcome: Any,
    teardown_error: BaseException | None,
) -> None:
    import app.db

    monkeypatch.setattr(app.db, "SessionLocal", lambda: _FakeSession(raise_on_exit=teardown_error))
    if isinstance(outcome, BaseException):
        monkeypatch.setattr(script, "run", lambda *a, **k: (_ for _ in ()).throw(outcome))
    else:
        monkeypatch.setattr(script, "run", lambda *a, **k: outcome)
    monkeypatch.setattr(
        sys, "argv", ["enrich_snapshot_scenes.py", "--report", str(tmp_path / "report.md")]
    )
    script.main()


def test_teardown_operational_error_after_success_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Delete the try/except in main() and this exits 1 despite errors=0 (NORM-27)."""
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            outcome=script.Outcome(errors=0),
            teardown_error=OperationalError("SSL connection has been closed unexpectedly"),
        )

    assert exc_info.value.code == 0
    assert "teardown_operational_error_after_completed_run" in capsys.readouterr().out


def test_failure_during_the_run_still_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run that never completes must not be treated as a completed one."""
    with pytest.raises(OperationalError):
        _run_main(
            monkeypatch,
            tmp_path,
            outcome=OperationalError("connection reset mid-run"),
            teardown_error=None,
        )


def test_run_errors_exit_nonzero_regardless_of_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            outcome=script.Outcome(errors=3),
            teardown_error=None,
        )

    assert exc_info.value.code == 1


def test_run_errors_and_teardown_error_both_exit_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both bad: the teardown catch must not mask the run's own failure."""
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            tmp_path,
            outcome=script.Outcome(errors=1),
            teardown_error=OperationalError("SSL connection has been closed unexpectedly"),
        )

    assert exc_info.value.code == 1
