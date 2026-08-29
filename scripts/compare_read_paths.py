#!/usr/bin/env python3
"""Diff the old and new serving read paths, field by field, over every parcel.

**This script is temporary by design.** It exists to produce the evidence that
authorizes ADR 0001's step-3 cutover, and it can only run while *both* read
paths are alive — the ``imagery_snapshots`` reads and the
``parcel_scenes``/``scenes`` reads. The cutover commit deletes the old reads,
at which point this script stops being runnable and should be deleted with
them (step 4, `docs/adr/0001-imagery-normalization.md`).

Five serving sites, the ones `STEP1-REPORT.md` §7 carried forward:

1. ``get_imagery_snapshots``  vs ``get_served_scenes``       — the listing
   endpoint and the preview renderer
2. ``get_snapshot_by_id``     vs ``get_served_scene_by_id``  — the Titiler
   ``/stac`` callback, the tile proxy, warmup
3. ``count_imagery_snapshots`` vs ``count_served_scenes``    — ``items_found``
4. ``featured._snapshot_ids_for_parcels`` vs ``served_scene_bounds``
5. ``revalidate_landsat.landsat_parcels`` vs ``parcels_serving_source``

**Row identity across the two shapes.** ``parcel_scenes.id`` is a fresh UUID
(``scripts/backfill_scenes.py`` minted one per row; the dual-write mints one
per insert), so it is *never* equal to the ``imagery_snapshots.id`` for the
same served period. The id is therefore excluded from field equality and
checked as a bijection instead: rows are joined on
``(source, group_key)`` — the natural key both shapes can produce — and the
old-id/new-id mapping must be one-to-one and consistent at every site that
hands an id out. Any other divergence is a finding.

Read-only, and safe for production: it opens one session, sets
``default_transaction_read_only`` on PostgreSQL, issues nothing but SELECTs
through the two read paths themselves, and never commits.

Usage:
    docker compose exec api python scripts/compare_read_paths.py
    docker compose exec api python scripts/compare_read_paths.py --out /tmp/parity.md
    fly ssh console -a log0s-plotline-api -C \\
        "python scripts/compare_read_paths.py --out /tmp/parity.md"
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.api.v1.featured import _snapshot_ids_for_parcels
from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.services import imagery as imagery_service

# The scope each source's selector groups by, which is what turns a
# capture_date into the group_key ``parcel_scenes`` stores. Not re-derived:
# these are the values the pipeline passes to reconcile_source_snapshots at
# ``app/tasks/timeline.py:66,78,94`` (``selection_scope``) and
# ``app/tasks/timeline.py:1003`` (topo's literal ``scope="decade"``).
_SCOPE_BY_SOURCE = {
    "naip": "year",
    "landsat": "year",
    "sentinel2": "year",
    "usgs_topo": "decade",
}

# Every field of ImagerySnapshotRow except ``id``, which is the one predicted
# divergence (see the module docstring) and is checked as a mapping instead.
_COMPARED_FIELDS = (
    "parcel_id",
    "source",
    "capture_date",
    "stac_item_id",
    "stac_collection",
    "cog_url",
    "additional_cog_urls",
    "thumbnail_url",
    "resolution_m",
    "cloud_cover_pct",
    "bbox",
    "created_at",
)


@dataclass(frozen=True)
class Divergence:
    site: str
    parcel_id: str
    key: str
    field: str
    old: str
    new: str


@dataclass
class Report:
    parcels: int = 0
    old_rows: int = 0
    new_rows: int = 0
    comparisons: int = 0
    id_pairs: int = 0
    within_date_reorders: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    id_map: dict[str, str] = field(default_factory=dict)
    reverse_id_map: dict[str, str] = field(default_factory=dict)
    item_fact_disagreements: dict[str, tuple[int, int]] = field(default_factory=dict)

    def diverge(
        self, site: str, parcel_id: str, key: str, name: str, old: object, new: object
    ) -> None:
        self.divergences.append(Divergence(site, parcel_id, key, name, repr(old), repr(new)))


def _group_key(source: str, captured: date) -> str:
    scope = _SCOPE_BY_SOURCE.get(source)
    if scope is None:
        raise ValueError(f"No selection scope known for source {source!r}")
    return imagery_service.encode_group_key(scope, captured)


def _row_key(row: imagery_service.ImagerySnapshotRow) -> str:
    return f"{row.source}/{_group_key(row.source, row.capture_date)}"


def _index(
    rows: list[imagery_service.ImagerySnapshotRow],
) -> dict[str, imagery_service.ImagerySnapshotRow]:
    out: dict[str, imagery_service.ImagerySnapshotRow] = {}
    for row in rows:
        out[_row_key(row)] = row
    return out


def _compare_rows(
    report: Report,
    site: str,
    parcel_id: str,
    old_rows: list[imagery_service.ImagerySnapshotRow],
    new_rows: list[imagery_service.ImagerySnapshotRow],
) -> None:
    """Field-by-field over both indexes, plus set difference and order."""
    old_index = _index(old_rows)
    new_index = _index(new_rows)

    if len(old_index) != len(old_rows):
        report.diverge(site, parcel_id, "-", "old_duplicate_group", len(old_rows), len(old_index))
    if len(new_index) != len(new_rows):
        report.diverge(site, parcel_id, "-", "new_duplicate_group", len(new_rows), len(new_index))

    for key in sorted(set(old_index) - set(new_index)):
        report.diverge(site, parcel_id, key, "missing_from_new", old_index[key].stac_item_id, None)
    for key in sorted(set(new_index) - set(old_index)):
        report.diverge(site, parcel_id, key, "missing_from_old", None, new_index[key].stac_item_id)

    # Order is part of the contract: the listing is served in the order the
    # query returns it and the frontend renders the timeline in that order.
    # Two classes, and only one of them is a divergence.
    #
    # ``row_order`` — the *chronological* sequence differs. Both queries say
    # ``capture_date ASC``, so this would mean one of them is not sorted.
    #
    # ``row_order_within_date`` — the dates agree and only the arrangement of
    # rows sharing a date differs. Neither query ever defined that order: the
    # old one left it to the plan, and the new one breaks the tie on
    # ``source`` so it is at least stable. Reported, counted, and not counted
    # as a divergence, because there is no old behaviour to have broken.
    old_order = [_row_key(r) for r in old_rows]
    new_order = [_row_key(r) for r in new_rows]
    if old_order != new_order and sorted(old_order) == sorted(new_order):
        old_dates = [r.capture_date for r in old_rows]
        new_dates = [r.capture_date for r in new_rows]
        if old_dates == new_dates:
            report.within_date_reorders += 1
        else:
            report.diverge(site, parcel_id, "-", "row_order", old_order, new_order)

    for key in sorted(set(old_index) & set(new_index)):
        old, new = old_index[key], new_index[key]
        report.comparisons += 1
        for name in _COMPARED_FIELDS:
            old_value = getattr(old, name)
            new_value = getattr(new, name)
            if old_value != new_value:
                report.diverge(site, parcel_id, key, name, old_value, new_value)
        _record_id_pair(report, site, parcel_id, key, str(old.id), str(new.id))


def _record_id_pair(
    report: Report, site: str, parcel_id: str, key: str, old_id: str, new_id: str
) -> None:
    """The predicted divergence, checked as a bijection rather than ignored."""
    report.id_pairs += 1
    seen = report.id_map.setdefault(old_id, new_id)
    if seen != new_id:
        report.diverge(site, parcel_id, key, "id_map_inconsistent", seen, new_id)
    back = report.reverse_id_map.setdefault(new_id, old_id)
    if back != old_id:
        report.diverge(site, parcel_id, key, "id_map_not_injective", back, old_id)


def _parcel_ids(db: Session) -> list[uuid.UUID]:
    rows = db.execute(sa_text("SELECT id FROM parcels ORDER BY id")).scalars().all()
    return [uuid.UUID(str(pid)) for pid in rows]


def _featured_parcel_ids(db: Session) -> list[str]:
    rows = (
        db.execute(sa_text("SELECT parcel_id FROM featured_locations ORDER BY display_order"))
        .scalars()
        .all()
    )
    return [str(pid) for pid in rows]


def run(db: Session, report: Report) -> None:
    parcel_ids = _parcel_ids(db)
    report.parcels = len(parcel_ids)

    for parcel_id in parcel_ids:
        pid = str(parcel_id)

        # Site 1 — the listing, unfiltered. This is the population every other
        # site is a projection of, so its counts are the report's row totals.
        old_all = imagery_service.get_imagery_snapshots(db, parcel_id)
        new_all = imagery_service.get_served_scenes(db, parcel_id)
        report.old_rows += len(old_all)
        report.new_rows += len(new_all)
        _compare_rows(report, "listing", pid, old_all, new_all)

        # Site 1 — every filter the endpoint exposes. A filter that reads the
        # wrong column is invisible in an unfiltered comparison.
        for source in sorted(_SCOPE_BY_SOURCE):
            _compare_rows(
                report,
                f"listing[source={source}]",
                pid,
                imagery_service.get_imagery_snapshots(db, parcel_id, source=source),
                imagery_service.get_served_scenes(db, parcel_id, source=source),
            )
        if old_all:
            captured = sorted(r.capture_date for r in old_all)
            midpoint = captured[len(captured) // 2]
            _compare_rows(
                report,
                "listing[start_date]",
                pid,
                imagery_service.get_imagery_snapshots(db, parcel_id, start_date=midpoint),
                imagery_service.get_served_scenes(db, parcel_id, start_date=midpoint),
            )
            _compare_rows(
                report,
                "listing[end_date]",
                pid,
                imagery_service.get_imagery_snapshots(db, parcel_id, end_date=midpoint),
                imagery_service.get_served_scenes(db, parcel_id, end_date=midpoint),
            )

        # Site 2 — by id, through the mapping site 1 established. Every row is
        # fetched individually on both sides, which is what the Titiler
        # callback and the tile proxy do.
        for old_row in old_all:
            new_id = report.id_map.get(str(old_row.id))
            if new_id is None:
                report.diverge("by_id", pid, _row_key(old_row), "no_id_mapping", old_row.id, None)
                continue
            old_one = imagery_service.get_snapshot_by_id(db, old_row.id)
            new_one = imagery_service.get_served_scene_by_id(db, uuid.UUID(new_id))
            if old_one is None or new_one is None:
                report.diverge("by_id", pid, _row_key(old_row), "row_absent", old_one, new_one)
                continue
            _compare_rows(report, "by_id", pid, [old_one], [new_one])

        # Site 3 — items_found. Rows, not scenes, on both sides.
        for source in sorted(_SCOPE_BY_SOURCE):
            old_count = imagery_service.count_imagery_snapshots(db, parcel_id, source)
            new_count = imagery_service.count_served_scenes(db, parcel_id, source)
            report.comparisons += 1
            if old_count != new_count:
                report.diverge("count", pid, source, "count", old_count, new_count)

    # Site 4 — the featured cards' earliest/latest ids, compared as the rows
    # they name rather than as id strings (the ids differ by construction).
    featured = _featured_parcel_ids(db)
    old_bounds = _snapshot_ids_for_parcels(db, featured)
    new_bounds = imagery_service.served_scene_bounds(db, featured)
    for pid in featured:
        report.comparisons += 1
        old_pair = old_bounds.get(pid)
        new_pair = new_bounds.get(pid)
        if (old_pair is None) != (new_pair is None):
            report.diverge("featured", pid, "-", "bounds_presence", old_pair, new_pair)
            continue
        if old_pair is None or new_pair is None:
            continue
        for label, old_id, new_id in (
            ("earliest", old_pair[0], new_pair[0]),
            ("latest", old_pair[1], new_pair[1]),
        ):
            mapped = report.id_map.get(old_id)
            if mapped is None:
                report.diverge("featured", pid, label, "no_id_mapping", old_id, new_id)
            elif mapped != new_id:
                report.diverge("featured", pid, label, "different_row", mapped, new_id)

    # Site 5 — revalidate_landsat's parcel selection.
    old_parcels = {
        str(pid)
        for pid in db.execute(
            sa_text(
                # revalidate_landsat.landsat_parcels, as ORM at
                # scripts/revalidate_landsat.py:85-93. Inlined rather than
                # imported because scripts/ is not a package.
                "SELECT parcel_id FROM imagery_snapshots"
                " WHERE source = 'landsat' GROUP BY parcel_id"
            )
        ).scalars()
    }
    new_parcels = {str(pid) for pid in imagery_service.parcels_serving_source(db, "landsat")}
    report.comparisons += 1
    for pid in sorted(old_parcels - new_parcels):
        report.diverge("revalidate_landsat", pid, "-", "missing_from_new", pid, None)
    for pid in sorted(new_parcels - old_parcels):
        report.diverge("revalidate_landsat", pid, "-", "missing_from_old", None, pid)

    _item_fact_disagreement(db, report)


# The item facts the two shapes both store, as (label, snapshot column, scene
# column). ``bbox`` is geometry and is compared per row by the sites above.
_ITEM_FACT_COLUMNS = (
    ("capture_date", "i.capture_date", "s.capture_date"),
    ("cog_url", "i.cog_url", "s.cog_url"),
    ("thumbnail_url", "i.thumbnail_url", "s.thumbnail_url"),
    ("resolution_m", "i.resolution_m", "s.resolution_m"),
    ("cloud_cover_pct", "i.cloud_cover_pct", "s.cloud_cover_pct"),
)


def _item_fact_disagreement(db: Session, report: Report) -> None:
    """Count, per field, the served rows whose two copies of a fact disagree.

    The per-row sites above find these one at a time; this is the same
    question asked as a population, because that is the form the answer has to
    take in production. It is the ADR's opening cost ("item facts are stored N
    times and can disagree") meeting the cutover: one ``scenes`` row is now the
    only copy, so wherever the copies disagree, the parcels holding the losing
    copy see their served value change.
    """
    for label, snap_col, scene_col in _ITEM_FACT_COLUMNS:
        rows = (
            db.execute(
                sa_text(
                    f"""
                SELECT count(*) AS rows, count(DISTINCT s.id) AS items
                FROM imagery_snapshots i
                JOIN parcel_scenes ps
                  ON ps.parcel_id = i.parcel_id AND ps.source = i.source
                JOIN scenes s
                  ON s.id = ps.scene_id
                 AND s.item_id = i.stac_item_id
                 AND s.collection = i.stac_collection
                WHERE {snap_col} IS DISTINCT FROM {scene_col}
                """
                )
            )
            .mappings()
            .first()
        )
        if rows and rows["rows"]:
            report.item_fact_disagreements[label] = (int(rows["rows"]), int(rows["items"]))


def render(report: Report) -> str:
    by_site: dict[str, int] = defaultdict(int)
    by_field: dict[str, int] = defaultdict(int)
    for d in report.divergences:
        by_site[d.site] += 1
        by_field[d.field] += 1

    lines = [
        "# Read-path parity — old vs new",
        "",
        f"* parcels: **{report.parcels}**",
        f"* rows, old path: **{report.old_rows}**",
        f"* rows, new path: **{report.new_rows}**",
        f"* row/count comparisons: **{report.comparisons}**",
        f"* id pairs recorded: **{report.id_pairs}**"
        f" over {len(report.id_map)} distinct old ids"
        f" and {len(report.reverse_id_map)} distinct new ids",
        f"* fields compared per row pair: **{len(_COMPARED_FIELDS)}**"
        f" ({', '.join(_COMPARED_FIELDS)})",
        f"* same-date reorderings (not a divergence; see `_compare_rows`):"
        f" **{report.within_date_reorders}**",
        "",
        f"## Divergences: **{len(report.divergences)}**",
        "",
    ]
    if not report.divergences:
        lines.append("None.")
    else:
        lines += ["| site | parcel | key | field | old | new |", "|---|---|---|---|---|---|"]
        for d in report.divergences[:200]:
            lines.append(
                f"| {d.site} | {d.parcel_id[:8]} | {d.key} | {d.field} |"
                f" {d.old[:80]} | {d.new[:80]} |"
            )
        if len(report.divergences) > 200:
            lines.append(f"| … | | | {len(report.divergences) - 200} more not listed | | |")
        lines += ["", "### By site", ""]
        lines += [f"* {site}: {n}" for site, n in sorted(by_site.items())]
        lines += ["", "### By field", ""]
        lines += [f"* {name}: {n}" for name, n in sorted(by_field.items())]

    lines += ["", "## Item facts the two shapes disagree about", ""]
    if not report.item_fact_disagreements:
        lines.append("None.")
    else:
        lines += ["| field | served rows | distinct scenes |", "|---|---|---|"]
        for name, (n_rows, n_items) in sorted(report.item_fact_disagreements.items()):
            lines.append(f"| {name} | {n_rows} | {n_items} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="Write the report here as well as to stdout")
    args = parser.parse_args()

    configure_script_logging()
    report = Report()
    with SessionLocal() as db:
        if imagery_service._is_postgres(db):
            # Provable read-only: any INSERT/UPDATE/DELETE from here on, by
            # this script or by anything it calls, fails rather than lands.
            #
            # The commit is load-bearing and is not a write: ``default_``
            # applies to transactions that *start* after it is set, so leaving
            # it inside the implicit transaction SQLAlchemy already opened
            # would set the flag and then run every query under the one
            # transaction it does not cover.
            db.execute(sa_text("SET default_transaction_read_only = on"))
            db.commit()
        run(db, report)
        db.rollback()

    text = render(report)
    print(text)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    return 1 if report.divergences else 0


if __name__ == "__main__":
    sys.exit(main())
