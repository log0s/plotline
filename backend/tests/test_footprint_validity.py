"""NORM-31: an invalid footprint is repaired at write time, loudly.

The finding is that two of the 5,387 footprints the production snapshot heal
wrote are self-intersecting polygons — published that way by the Planetary
Computer, stored faithfully, and passed by all three checks that looked at
them, because the column type, ``extract_footprint_wkt``'s non-Polygon branch
and the heal's prediction all asked "is this a polygon" and none asked "is this
a valid one" (``docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT-3.md``
§6e).

**The fixture is one of the two real rows.** ``fixtures/norm31_invalid_footprint.json``
is `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` as the Planetary
Computer publishes it, geometry byte-for-byte. A synthetic bowtie is used
alongside it for the multipart rule, because the real rows do not exercise that
branch — they repair to a single polygon.

**SQLite/PostGIS split, per NORM-29 (state the limit, do not fake it).**
``normalize_footprint`` is pure shapely, so its half runs anywhere. The queue
half is ``NOT ST_IsValid(footprint)`` — a PostGIS predicate with no SQLite
answer worth inventing — so it runs against a real Postgres and skips without
``TEST_POSTGRES_URL``, failing rather than skipping under ``CI``.

Delete-the-fix, one clause per test:

* the ``if geometry.is_valid: return geometry, None`` early return — remove it
  and ``test_a_valid_footprint_is_returned_untouched`` sees a good geometry
  perturbed by a repair it never needed.
* the ``make_valid`` call (return the input unchanged) — remove it and
  ``test_the_real_norm31_footprint_is_repaired_to_a_valid_geometry``,
  ``test_the_repair_is_reported_with_the_reason`` and
  ``test_a_bowtie_stores_the_largest_part_and_reports_the_discard`` all go red,
  and ``test_revalidate_run_repairs_a_seeded_invalid_row`` leaves the row in
  its own queue after a full pass over it.
* the ``_polygonal_parts`` filter (keep every member of the repair) — remove it
  and ``test_the_real_norm31_footprint_is_repaired_to_a_valid_geometry``
  stores the zero-area LineString spike that the real repair pinches off.
* the ``NOT ST_IsValid(footprint)`` predicate in ``load_queue`` — remove it and
  ``test_the_revalidate_queue_finds_invalid_rows_and_ignores_valid_ones``
  sweeps every row in the table instead of the two that need it.
* the ``invalid`` column in ``FOOTPRINT_INVARIANT_SQL`` — remove it and
  ``test_the_invariant_query_counts_the_invalid_rows`` cannot tell a clean
  table from the production one, which is exactly what happened in the arc.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from shapely.geometry import Point, Polygon, shape
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.services.stac import extract_footprint_wkt, normalize_footprint

_HERE = Path(__file__).resolve()
_FIXTURE = _HERE.parent / "fixtures" / "norm31_invalid_footprint.json"
_SCRIPT = next(
    p / "scripts" / "enrich_snapshot_scenes.py"
    for p in _HERE.parents
    if (p / "scripts" / "enrich_snapshot_scenes.py").exists()
)
_MAINTENANCE_URL = os.environ.get("TEST_POSTGRES_URL")

requires_postgres = pytest.mark.skipif(not _MAINTENANCE_URL, reason="TEST_POSTGRES_URL is not set")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("enrich_snapshot_scenes", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["enrich_snapshot_scenes"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

REAL_ITEM: dict[str, Any] = json.loads(_FIXTURE.read_text())
REAL_ITEM_ID: str = REAL_ITEM["id"]

# A bowtie: the ring crosses itself, so it encloses two lobes of very different
# size. `make_valid` splits it into a MultiPolygon, which is the branch the two
# real rows do not reach.
BOWTIE = Polygon([(0, 0), (4, 4), (4, 0), (0, 4), (0, 0)])
VALID_SQUARE = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])


# ── normalize_footprint, pure shapely ─────────────────────────────────────────


def test_the_real_norm31_footprint_is_repaired_to_a_valid_geometry() -> None:
    """The production row itself: invalid in, valid Polygon out."""
    raw = shape(REAL_ITEM["geometry"])
    assert not raw.is_valid  # the premise; if PC ever fixes it, this test says so

    repaired, complaint = normalize_footprint(raw, item_id=REAL_ITEM_ID)

    assert repaired is not None
    assert repaired.is_valid
    assert repaired.geom_type == "Polygon"
    # The repair pinches off a zero-area lineal spike; no coverage is lost, so
    # there is nothing to complain about.
    assert complaint is None
    assert repaired.area == pytest.approx(raw.area, rel=1e-12)


def test_the_repaired_footprint_still_contains_the_points_the_raw_ring_did() -> None:
    """The serving property, not just validity.

    ``filter_items_containing_point`` asks point-in-footprint, and ADR rule 4
    promises the same question can be asked of ``scenes.footprint`` in SQL. So
    the test is containment, and the reference answer is computed by an
    even-odd ray cast over the raw ring — arithmetic that does not go through
    the library being tested, so a repair that quietly moved the boundary
    cannot make the reference move with it.
    """
    raw = shape(REAL_ITEM["geometry"])
    repaired, _ = normalize_footprint(raw, item_id=REAL_ITEM_ID)
    assert repaired is not None

    inside = _points_inside_by_ray_cast(list(raw.exterior.coords), steps=40)
    assert len(inside) > 100, "the sampling grid must actually land inside the footprint"
    missed = [p for p in inside if not repaired.buffer(1e-9).contains(Point(p))]
    assert not missed, f"{len(missed)} of {len(inside)} covered points lost by the repair"


def test_a_valid_footprint_is_returned_untouched(caplog: pytest.LogCaptureFixture) -> None:
    """Repair must not perturb good data, and must not report a repair it did not do.

    Geometric equality alone is too weak a claim to rest on here: shapely's
    ``make_valid`` over an already-valid polygon returns an equal polygon, so a
    version that repaired unconditionally would still pass an ``equals_exact``.
    Identity is what "untouched" actually means, and the silent log is what
    keeps the repair count in the logs honest — under an unconditional repair
    every good geometry in the fleet would emit a warning naming itself.
    """
    with caplog.at_level("WARNING", logger="app.services.stac"):
        repaired, complaint = normalize_footprint(VALID_SQUARE, item_id="valid-item")

    assert complaint is None
    assert repaired is VALID_SQUARE
    assert repaired.equals_exact(VALID_SQUARE, tolerance=0.0)
    assert not [
        r for r in caplog.records if r.getMessage() == "footprint_repaired_invalid_geometry"
    ]


def test_the_repair_is_reported_with_the_reason(caplog: pytest.LogCaptureFixture) -> None:
    """Loud, never silent: item id and shapely's explain_validity, per occurrence."""
    with caplog.at_level("WARNING", logger="app.services.stac"):
        normalize_footprint(shape(REAL_ITEM["geometry"]), item_id=REAL_ITEM_ID)

    records = [r for r in caplog.records if r.getMessage() == "footprint_repaired_invalid_geometry"]
    assert len(records) == 1
    assert records[0].stac_item_id == REAL_ITEM_ID
    assert "Self-intersection" in records[0].invalidity_reason
    assert records[0].repaired is True
    assert records[0].polygon_parts == 1
    assert records[0].footprint_repair_discarded_area == pytest.approx(0.0)


def test_a_bowtie_stores_the_largest_part_and_reports_the_discard(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The multipart rule: largest by area, and the discarded fraction said out loud.

    The column is ``geometry(POLYGON,4326)``. Storing the largest part can only
    under-claim coverage — false negatives, never the false positives the 2026-08
    geometry audit measured 33 rows of — and the discard is reported so a
    non-trivial one argues for widening the column rather than tuning this.
    """
    lopsided = Polygon([(0, 0), (4, 4), (4, 3), (0, 7), (0, 0)])
    with caplog.at_level("WARNING", logger="app.services.stac"):
        repaired, complaint = normalize_footprint(lopsided, item_id="bowtie")

    assert repaired is not None
    assert repaired.geom_type == "Polygon"
    assert repaired.is_valid

    parts = sorted((p.area for p in _valid_parts(lopsided)), reverse=True)
    assert len(parts) == 2, "the fixture must actually repair to two polygons"
    assert repaired.area == pytest.approx(parts[0])

    assert complaint is not None
    assert "repaired to 2 polygons" in complaint
    record = next(
        r for r in caplog.records if r.getMessage() == "footprint_repaired_invalid_geometry"
    )
    assert record.polygon_parts == 2
    assert record.footprint_repair_discarded_area == pytest.approx(parts[1] / sum(parts))


def test_a_repair_with_no_polygon_left_stores_nothing_and_says_so() -> None:
    """A degenerate ring repairs to a line. Nothing is stored, and it is reported."""
    degenerate = Polygon([(0, 0), (1, 1), (2, 2), (0, 0)])
    repaired, complaint = normalize_footprint(degenerate, item_id="degenerate")

    assert repaired is None
    assert complaint is not None and "no polygon at all" in complaint


def test_extract_footprint_wkt_hands_back_a_valid_polygon_for_the_real_item() -> None:
    """The one function both write paths call. The repair is not optional for either."""
    ewkt, complaint = extract_footprint_wkt(REAL_ITEM)

    assert complaint is None
    assert ewkt is not None and ewkt.startswith("SRID=4326;POLYGON")
    from shapely import wkt as shapely_wkt

    assert shapely_wkt.loads(ewkt.split(";", 1)[1]).is_valid


def _valid_parts(geometry: Polygon) -> list[Any]:
    from shapely.validation import make_valid

    repaired = make_valid(geometry)
    members = list(repaired.geoms) if hasattr(repaired, "geoms") else [repaired]
    return [m for m in members if m.geom_type == "Polygon" and not m.is_empty]


def _points_inside_by_ray_cast(ring: list[Any], *, steps: int) -> list[tuple[float, float]]:
    """Grid points the raw ring encloses, by even-odd crossing count.

    Deliberately not shapely: the reference answer for "what did the raw
    geometry cover" must not come from the same library whose repair is under
    test. Points within ``eps`` of a ring segment are dropped rather than
    classified, since a boundary point is not what this asserts.
    """
    eps = 1e-6
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    inside: list[tuple[float, float]] = []
    for i in range(1, steps):
        for j in range(1, steps):
            x = min(xs) + (max(xs) - min(xs)) * i / steps
            y = min(ys) + (max(ys) - min(ys)) * j / steps
            if _near_ring(x, y, ring, eps):
                continue
            crossings = 0
            for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                    crossings += 1
            if crossings % 2 == 1:
                inside.append((x, y))
    return inside


def _near_ring(x: float, y: float, ring: list[Any], eps: float) -> bool:
    from shapely.geometry import LineString

    return LineString(ring).distance(Point(x, y)) < eps


# ── The revalidate queue, against a real PostGIS ──────────────────────────────


def test_the_postgres_half_is_not_silently_skipped() -> None:
    """In CI the PostGIS half is required — a missing URL must fail, not skip."""
    if os.environ.get("CI") and not _MAINTENANCE_URL:
        pytest.fail(
            "TEST_POSTGRES_URL is not set, so the ST_IsValid queue tests would "
            "skip. CI must run them; see .github/workflows/deploy.yml."
        )


def test_revalidate_mode_refuses_a_session_without_postgis(db: Session) -> None:
    """No SQLite answer is invented: an empty queue would read as 'clean'."""
    with pytest.raises(RuntimeError, match="requires PostGIS"):
        script.load_queue(db, mode=script.MODE_REVALIDATE)


@contextmanager
def _postgis_session() -> Iterator[Session]:
    """A throwaway database with PostGIS and just the columns these tests read.

    The maintenance database is never touched, the same rule
    ``test_migrations_postgres.py`` follows. The table is created here rather
    than migrated because what is under test is a ``WHERE`` clause and a
    geometry column type, and running the full migration chain per test would
    buy nothing these assertions can see.
    """
    assert _MAINTENANCE_URL
    name = f"plotline_norm31_{uuid.uuid4().hex[:12]}"
    admin = create_engine(_MAINTENANCE_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = make_url(_MAINTENANCE_URL).set(database=name).render_as_string(hide_password=False)
        engine = create_engine(url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                connection.execute(
                    text(
                        "CREATE TABLE scenes ("
                        " id uuid PRIMARY KEY, source text NOT NULL, collection text NOT NULL,"
                        " item_id text NOT NULL, capture_date date NOT NULL,"
                        " cog_url text NOT NULL, provenance text NOT NULL,"
                        " resolution_m double precision,"
                        " footprint geometry(POLYGON,4326), bbox geometry(POLYGON,4326),"
                        " fetched_at timestamptz NOT NULL)"
                    )
                )
            with sessionmaker(bind=engine)() as session:
                yield session
        finally:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _insert(
    db: Session,
    *,
    item_id: str,
    wkt: str,
    source: str = "sentinel2",
    collection: str = "sentinel-2-l2a",
    provenance: str = "snapshot",
) -> str:
    scene_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO scenes (id, source, collection, item_id, capture_date, cog_url,"
            " provenance, resolution_m, footprint, bbox, fetched_at)"
            " VALUES (:id, :source, :collection, :item_id, '2018-12-26',"
            " 'https://example.invalid/x.tif', :provenance, 10.0,"
            " ST_GeomFromText(:wkt, 4326), NULL, now())"
        ),
        {
            "id": scene_id,
            "source": source,
            "collection": collection,
            "item_id": item_id,
            "provenance": provenance,
            "wkt": wkt,
        },
    )
    db.commit()
    return scene_id


_RAW_INVALID_WKT = shape(REAL_ITEM["geometry"]).wkt
_VALID_WKT = "POLYGON((0 0,1 0,1 1,0 1,0 0))"


@requires_postgres
def test_the_revalidate_queue_finds_invalid_rows_and_ignores_valid_ones() -> None:
    """Seeded invalid rows are the queue; valid ones and topo are not."""
    with _postgis_session() as db:
        invalid_snapshot = _insert(db, item_id=REAL_ITEM_ID, wkt=_RAW_INVALID_WKT)
        # Any provenance: the dual-write stores item geometry through the same
        # function, so a 'selection' row can carry the same self-intersection.
        invalid_selection = _insert(
            db, item_id="selection-row", wkt=_RAW_INVALID_WKT, provenance="selection"
        )
        _insert(db, item_id="valid-row", wkt=_VALID_WKT)
        _insert(
            db,
            item_id="topo-row",
            wkt=_RAW_INVALID_WKT,
            source="usgs_topo",
            collection="usgs-historical-topo",
        )

        queue = script.load_queue(db, mode=script.MODE_REVALIDATE)

        assert {row.item_id for row in queue} == {REAL_ITEM_ID, "selection-row"}
        assert {row.id for row in queue} == {invalid_snapshot, invalid_selection}


@requires_postgres
def test_the_invariant_query_counts_the_invalid_rows() -> None:
    """The invariant the whole arc carried, plus the question it never asked."""
    with _postgis_session() as db:
        _insert(db, item_id=REAL_ITEM_ID, wkt=_RAW_INVALID_WKT)
        _insert(db, item_id="valid-row", wkt=_VALID_WKT)

        assert script.check_footprint_invariants(db) == {
            "not_polygon": 0,
            "invalid": 1,
            "equals_bbox": 1,  # the valid square is its own envelope
        }


@requires_postgres
def test_revalidate_run_repairs_a_seeded_invalid_row(tmp_path: Path) -> None:
    """A real heal, end to end: refetch, repair, rewrite, and the queue empties."""
    with _postgis_session() as db:
        scene_id = _insert(db, item_id=REAL_ITEM_ID, wkt=_RAW_INVALID_WKT)
        stac = _FakeStac({REAL_ITEM_ID: REAL_ITEM})

        out = script.run(
            db,
            execute=True,
            report_path=tmp_path / "revalidate.md",
            lookup=stac,
            mode=script.MODE_REVALIDATE,
        )

        assert (out.queue_size, out.footprints, out.errors) == (1, 1, 0)
        # Footprint only: the sweep writes no bbox and no resolution_m.
        assert (out.bboxes, out.resolutions) == (0, 0)
        row = db.execute(
            text(
                "SELECT ST_IsValid(footprint) AS ok, bbox IS NULL AS no_bbox,"
                " resolution_m FROM scenes WHERE id = :id"
            ),
            {"id": scene_id},
        ).one()
        assert row.ok is True
        assert row.no_bbox is True
        assert row.resolution_m == 10.0
        # Re-derivation is the resume mechanism: the repaired row is gone.
        assert script.load_queue(db, mode=script.MODE_REVALIDATE) == []
        assert out.invariants == {"not_polygon": 0, "invalid": 0, "equals_bbox": 0}


@requires_postgres
def test_an_empty_revalidate_queue_is_a_clean_run(tmp_path: Path) -> None:
    """The post-heal state, and the local state. Zero rows, zero fetches, exit 0."""
    with _postgis_session() as db:
        _insert(db, item_id="valid-row", wkt=_VALID_WKT)
        stac = _FakeStac({})

        out = script.run(
            db,
            execute=True,
            report_path=tmp_path / "revalidate.md",
            lookup=stac,
            mode=script.MODE_REVALIDATE,
        )

        assert (out.queue_size, out.fetched, out.written, out.errors) == (0, 0, 0, 0)
        assert stac.gets == []
        # This is what `; echo $? > /tmp/<name>.rc` would capture.
        assert (1 if out.errors else 0) == 0
        assert (tmp_path / "revalidate.md").exists()


class _FakeStac:
    """The one PC call this pass makes, served from a dict. No network."""

    def __init__(self, items: dict[str, dict[str, Any]]) -> None:
        self.items = items
        self.gets: list[str] = []
        self.closed = False

    @property
    def requests(self) -> int:
        return len(self.gets)

    async def get_item(self, collection: str, item_id: str) -> tuple[int, dict[str, Any] | None]:
        self.gets.append(item_id)
        if item_id in self.items:
            return 200, self.items[item_id]
        return 404, None

    async def aclose(self) -> None:
        self.closed = True
