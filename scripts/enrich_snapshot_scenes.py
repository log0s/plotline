#!/usr/bin/env python3
"""Fill the item facts the ``provenance = 'snapshot'`` backfill could not copy.

One pass over three findings, because all three are the same rows:

* **NORM-7's deferred half.** Step 1's backfill built one ``scenes`` row per
  distinct ``imagery_snapshots`` item and copied what that table held. It never
  held item geometry, so every ``snapshot`` row's ``footprint`` is NULL — and
  ADR rule 4's promise, "the next geometry audit is a query over ``scenes``,
  not a refetch", is false until they are filled.
* **NORM-13's ``scenes`` arm.** NAIP ``snapshot`` rows carry the historical
  per-source constant ``resolution_m = 1.0`` (NORM-9), which the item's own
  ``gsd`` contradicts for most vintages. ``scenes`` is insert-only, so no
  sweep shrinks that population: it persists until something rewrites it.
* **NORM-18.** Since the step-3 cutover those rows are the *served* copy, so
  the stale 1.0 is what a user sees in the resolution chip. The class of
  divergence opens the first time a NAIP selection is rewritten against a
  pre-NORM-9 ``scenes`` row. This pass closes the class rather than waiting
  for it to open.

**Lookup is a direct GET by ``(collection, item_id)``, and there is no
fallback.** Unlike the mosaic-URL pass, whose ids were *parsed out of tile
URLs* and were wrong roughly 70% of the time (NORM-4), these ids were written
by the pipeline from PC's own search results. They are catalogued ids, not
candidates, so there is nothing for a search to correct and no ``cog_url``
match to make. A row whose id does not resolve is therefore a **finding** —
an id the pipeline once served that PC no longer resolves — reported per row
with the row left exactly as it is:

* ``404`` — the id is gone from the catalogue. If this population is more than
  a handful, that is a stop-and-think result, not a reason to invent fuzzy
  matching.
* ``403`` — a permanent per-item refusal, the class
  ``../docs/audits/2026-08-geometry-audit/FINDINGS.md`` Appendix C counted six
  of. Terminal per item, never retried (NORM-10's item/search split).

**What a matched row is written.**

* ``footprint`` — ``item["geometry"]``, via ``extract_footprint_wkt``, which
  since NORM-31 runs it through ``normalize_footprint``: the item's real
  outline, never its bbox envelope, and topologically valid or repaired-and-
  reported, never stored invalid. A non-Polygon geometry cannot be stored in
  ``geometry(POLYGON,4326)``; it is reported and the footprint left NULL, which
  means that row stays in the queue.
* ``bbox`` — **only where it is currently NULL.** Existing bboxes were copied
  from rows the pipeline wrote and are not in question; rewriting them would
  be churn against a column no finding names.
* ``resolution_m`` — ``normalize_resolution_m(item gsd)`` (NORM-11's rounding),
  written only when the item speaks and disagrees with the stored value. The
  rule is uniform across sources on purpose — "the item wins wherever it
  speaks", the same rule ``SelectedScene.from_stac_item`` applies — because a
  per-source write rule would put per-source resolution constants in a second
  place, which is NORM-9's original defect. What *is* per-source is the
  reporting: NAIP disagreements are the point of the pass and are counted;
  a landsat or sentinel-2 disagreement is unexpected (30.0 and 10.0 are
  correct constants) and is reported individually as a finding. Sentinel-2
  items carry no item-level ``gsd`` at all, so nothing is written for them —
  and ``None`` is never written over a stored value.
* ``capture_date`` — **never written.** A disagreement is reported, the same
  rule the mosaic pass used.
* ``provenance`` — **never written.** ``'snapshot'`` is frozen vocabulary
  meaning "copied from an ``imagery_snapshots`` row", which stays true of an
  enriched-in-place row; relabelling it ``'enriched'`` would be a lie about
  where the row came from *and* would erase NORM-7's queue definition. The
  done-marker is ``footprint IS NOT NULL``, so the queue is:

      provenance = 'snapshot' AND footprint IS NULL AND source <> 'usgs_topo'

  which is re-derivable by anyone, at any time, with no run state.

**``usgs_topo`` is excluded from the queue entirely.** Its
``stac_collection`` is ``usgs-historical-topo``, which is not a Planetary
Computer collection — those scenes come from The National Map (the geometry
audit's premise correction #2), so there is no PC item to GET. The excluded
count is stated in the report rather than left as a silent difference between
the row count and the queue size.

**Idempotent and resumable.** Rows leave the queue when their footprint lands,
and the queue is re-derived from the database on every run. A run killed
partway is resumed by re-running it: the committed rows are gone from the
queue and are not refetched. Writes commit in batches (``--batch-size``, 200
by default) rather than one transaction over the whole queue — a multi-thousand
row transaction held open for the length of the run is the wrong shape against
pgbouncer, and it would make a kill cost the entire run's fetches.

**A second mode, ``--revalidate-footprints`` (NORM-31).** Same fetch, same
pacing, same batching, same resume; only the queue and the write set change.
The queue becomes

    footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> 'usgs_topo'

— every row whose stored footprint is a polygon PostGIS will not vouch for, of
**any** provenance, since the dual-write stores ``item["geometry"]`` through
the same function this pass does. Those rows are refetched and their footprint
rewritten through ``normalize_footprint``, which repairs and reports. Nothing
else is written in this mode: those rows already have a bbox and a resolution
that some earlier pass decided.

Re-derivation is again the resume mechanism, for free: a repaired footprint is
valid, so the row is gone from the queue on the next read. **Queue 0 is a clean
run, not an error** — it is the post-sweep state, and exit is 0.

Usage (dry run is the default and writes nothing; both forms do fetch):

    docker compose exec api python scripts/enrich_snapshot_scenes.py \\
        --report docs/audits/2026-08-normalization/snapshot-enrich-dryrun.md
    docker compose exec api python scripts/enrich_snapshot_scenes.py \\
        --report docs/audits/2026-08-normalization/snapshot-enrich-run.md \\
        --execute

``--report`` is required and is rewritten after every batch, so a run whose
client dies still leaves a report of everything committed so far (STATUS.md
NORM-8: a killed client takes stdout with it and neither kills nor rolls back
the remote process). A detached production launch appends
``; echo $? > /tmp/<name>.rc`` so the exit status survives too (NORM-21's
sibling finding, STEP3-PROD-REPORT.md F3): this script exits non-zero if any
row ended in ``error``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.logging_config import configure_script_logging
from app.services.imagery import normalize_resolution_m
from app.services.stac import extract_bbox_wkt, extract_capture_date, extract_footprint_wkt
from scripts.shared.stac_fetch import DEFAULT_MIN_INTERVAL_S, FETCH_CONCURRENCY, StacLookup

logger = logging.getLogger("enrich_snapshot_scenes")

QUEUE_PROVENANCE = "snapshot"

# Not a Planetary Computer collection: usgs-historical-topo items come from
# The National Map, so a GET against PC's item endpoint would 404 every row
# for a reason that says nothing about the row.
EXCLUDED_SOURCE = "usgs_topo"

# Rows per transaction. At the default pace one batch is ~40 s of fetching,
# so a killed run loses at most that much work; 200 rows is also small enough
# that the write transaction is open for well under a second.
DEFAULT_BATCH_SIZE = 200


# ── Reading the queue ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueueRow:
    id: str
    source: str
    collection: str
    item_id: str
    capture_date: date
    resolution_m: float | None
    #: Whether ``bbox`` is currently NULL. The only rows whose bbox is written.
    bbox_is_null: bool


def _is_postgres(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


#: The two queue shapes. ``fill`` is NORM-7's: rows with no footprint at all.
#: ``revalidate`` is NORM-31's: rows whose footprint is stored but invalid.
MODE_FILL = "fill"
MODE_REVALIDATE = "revalidate"

# NORM-31. The revalidate queue is *not* restricted to `provenance =
# 'snapshot'`, unlike the fill queue. An invalid footprint is not a property of
# where the row came from: the dual-write
# (`app/services/imagery.py::_ensure_scene`) stores `item["geometry"]` through
# the same function this pass does, so a `'selection'` row can carry exactly
# the same self-intersection. Scoping the sweep to the provenance the finding
# happened to be observed in is how a class becomes two classes.
#
# `usgs_topo` is still excluded for the reason the fill queue excludes it —
# `usgs-historical-topo` is not a Planetary Computer collection, so there is no
# item to GET — and topo footprints are NULL anyway, so the exclusion is free.
_QUEUE_PREDICATE = {
    MODE_FILL: "provenance = :provenance AND footprint IS NULL AND source <> :excluded",
    MODE_REVALIDATE: "footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> :excluded",
}


def load_queue(db: Session, *, mode: str = MODE_FILL) -> list[QueueRow]:
    """The run's queue, re-derived from the database.

    ``fill``: every snapshot row still missing a footprint, topo excluded.
    ``revalidate``: every row whose stored footprint fails ``ST_IsValid``.

    Re-derived on every run and after every commit's worth of progress: this
    query *is* the resume mechanism, and it holds no state of its own. That is
    what makes the NORM-31 sweep resumable for free — a repaired row is valid,
    so it is gone from the queue, exactly as a filled row is gone from the fill
    queue.
    """
    if mode == MODE_REVALIDATE and not _is_postgres(db):
        # ST_IsValid is PostGIS. There is no SQLite answer to fake here, and a
        # sweep that silently returns an empty queue would read as "clean".
        raise RuntimeError("--revalidate-footprints requires PostGIS; this session is not Postgres")
    rows = db.execute(
        text(
            "SELECT id, source, collection, item_id, capture_date, resolution_m,"
            " bbox IS NULL AS bbox_is_null"
            " FROM scenes"
            f" WHERE {_QUEUE_PREDICATE[mode]}"
            " ORDER BY collection, item_id"
        ),
        {"provenance": QUEUE_PROVENANCE, "excluded": EXCLUDED_SOURCE},
    ).all()
    return [
        QueueRow(
            id=str(row.id),
            source=row.source,
            collection=row.collection,
            item_id=row.item_id,
            capture_date=_as_date(row.capture_date),
            resolution_m=float(row.resolution_m) if row.resolution_m is not None else None,
            bbox_is_null=bool(row.bbox_is_null),
        )
        for row in rows
    ]


def count_excluded(db: Session) -> int:
    """Topo snapshot rows with no footprint — in the finding, out of the queue."""
    return int(
        db.execute(
            text(
                "SELECT count(*) FROM scenes"
                " WHERE provenance = :provenance AND footprint IS NULL AND source = :excluded"
            ),
            {"provenance": QUEUE_PROVENANCE, "excluded": EXCLUDED_SOURCE},
        ).scalar_one()
    )


# NORM-31's other half. The invariant every prediction file in this arc
# carried — "footprints all ST_Polygon, none equal to its own bbox" — passed
# on two self-intersecting rows because it never asked about validity. It now
# asks. Kept as one query so a prediction file, a post-run check and this
# script's own verification cannot drift into asking different questions:
#
#   SELECT count(*) FILTER (WHERE GeometryType(footprint) <> 'POLYGON')  AS not_polygon,
#          count(*) FILTER (WHERE NOT ST_IsValid(footprint))             AS invalid,
#          count(*) FILTER (WHERE ST_Equals(footprint, ST_Envelope(footprint)))   AS equals_bbox
#     FROM scenes WHERE footprint IS NOT NULL;
#
# All three must be 0. `invalid` is the column the old invariant had no
# question for. `ST_Equals`, not the `~=` operator: since PostGIS 2.4 `~=`
# compares *bounding boxes*, so `footprint ~= ST_Envelope(footprint)` is true
# for every row on earth — a check of that shape reports 100% and means
# nothing, which is this finding's own mistake in a different column.
FOOTPRINT_INVARIANT_SQL = (
    "SELECT"
    " count(*) FILTER (WHERE GeometryType(footprint) <> 'POLYGON') AS not_polygon,"
    " count(*) FILTER (WHERE NOT ST_IsValid(footprint)) AS invalid,"
    " count(*) FILTER (WHERE ST_Equals(footprint, ST_Envelope(footprint))) AS equals_bbox"
    " FROM scenes WHERE footprint IS NOT NULL"
)


def check_footprint_invariants(db: Session) -> dict[str, int] | None:
    """The three counts above, or None where PostGIS is not available."""
    if not _is_postgres(db):
        return None
    row = db.execute(text(FOOTPRINT_INVARIANT_SQL)).one()
    return {
        "not_polygon": int(row.not_polygon),
        "invalid": int(row.invalid),
        "equals_bbox": int(row.equals_bbox),
    }


# ── Fetching ──────────────────────────────────────────────────────────────────


@dataclass
class Fetched:
    row: QueueRow
    #: ``ok`` | ``404`` | ``403`` | ``other-status`` | ``error``
    outcome: str
    item: dict[str, Any] | None = None
    detail: str = ""


async def fetch_row(lookup: StacLookup, row: QueueRow) -> Fetched:
    """One GET. No search fallback: the id is catalogued or it is a finding."""
    try:
        status, item = await lookup.get_item(row.collection, row.item_id)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return Fetched(row, "error", None, f"{type(exc).__name__}: {exc}")
    if item is not None:
        return Fetched(row, "ok", item)
    if status in (403, 404):
        return Fetched(row, str(status), None, f"item GET {status}")
    return Fetched(row, "other-status", None, f"item GET {status}")


async def fetch_batch(lookup: StacLookup, rows: list[QueueRow]) -> list[Fetched]:
    return list(await asyncio.gather(*(fetch_row(lookup, row) for row in rows)))


# ── Writing ───────────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    mode: str = MODE_FILL
    queue_size: int = 0
    excluded_topo: int = 0
    fetched: int = 0
    written: int = 0
    footprints: int = 0
    bboxes: int = 0
    resolutions: int = 0
    unmatched_404: int = 0
    unmatched_403: int = 0
    errors: int = 0
    #: resolution_m rewrites by source: source → Counter[(old, new)]
    resolution_changes: dict[str, Counter[tuple[float | None, float | None]]] = field(
        default_factory=dict
    )
    #: Rows whose item carried no usable ``gsd``, by source.
    no_item_gsd: Counter[str] = field(default_factory=Counter)
    findings: list[str] = field(default_factory=list)
    date_disagreements: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    #: ``check_footprint_invariants`` after the run; None off PostGIS.
    invariants: dict[str, int] | None = None

    def note_resolution(self, source: str, old: float | None, new: float | None) -> None:
        self.resolution_changes.setdefault(source, Counter())[(old, new)] += 1


def _gsd(item: dict[str, Any]) -> object:
    props = item.get("properties")
    return props.get("gsd") if isinstance(props, dict) else None


def _item_capture_date(item: dict[str, Any]) -> date | None:
    """The item's ``properties.datetime`` as a date, or None if unusable.

    An unparseable datetime is not a reason to refuse the geometry: the row's
    identity was never in question here, since the id came from the catalogue.
    """
    try:
        return extract_capture_date(item)
    except (KeyError, TypeError, ValueError):
        return None


def plan_row(fetched: Fetched, out: Outcome, *, mode: str = MODE_FILL) -> dict[str, Any]:
    """What this row would be written, and every note that falls out of deciding.

    Shared by the dry run and the write so a capture cannot describe something
    other than what ``--execute`` does — the mistake NORM-8 is about. The
    caller is the only thing that touches the database.

    In ``revalidate`` mode the plan is **footprint only**. Those rows already
    have a bbox and a resolution that some earlier pass decided; rewriting them
    under a geometry sweep would be churn against columns this finding does not
    name, and it would make the sweep's diff impossible to read. Disagreements
    are still reported — the notes are the pass's output, the writes are not.
    """
    row = fetched.row
    item = fetched.item
    assert item is not None
    plan: dict[str, Any] = {}

    footprint, complaint = extract_footprint_wkt(item)
    if footprint is not None:
        plan["footprint"] = footprint
    if complaint:
        # NORM-31: a complaint and a storable footprint are no longer mutually
        # exclusive. The repair reports a multipart discard *and* returns the
        # largest part, so the two facts are recorded separately instead of
        # the older message asserting a NULL that may not have happened.
        tail = (
            "footprint left NULL, so this row stays in the queue"
            if footprint is None
            else "footprint written as repaired"
        )
        out.anomalies.append(f"{row.collection}/{row.item_id}: {complaint}; {tail}")

    if row.bbox_is_null:
        bbox = extract_bbox_wkt(item)
        if bbox is None:
            out.anomalies.append(f"{row.collection}/{row.item_id}: item carries no bbox")
        else:
            plan["bbox"] = bbox

    raw_gsd = _gsd(item)
    resolution = normalize_resolution_m(raw_gsd)
    if resolution is None:
        out.no_item_gsd[row.source] += 1
    elif resolution != row.resolution_m:
        plan["resolution_m"] = resolution
        out.note_resolution(row.source, row.resolution_m, resolution)
        if row.source != "naip":
            out.findings.append(
                f"{row.source} {row.collection}/{row.item_id}: stored resolution_m"
                f" {row.resolution_m}, item gsd {raw_gsd} normalises to {resolution};"
                " a per-source constant was expected to be correct here"
            )

    item_date = _item_capture_date(item)
    if item_date is not None and item_date != row.capture_date:
        out.date_disagreements.append(
            f"{row.collection}/{row.item_id}: row says {row.capture_date},"
            f" item says {item_date}; row keeps its own"
        )
    if mode == MODE_REVALIDATE:
        return {"footprint": plan["footprint"]} if "footprint" in plan else {}
    return plan


def _write_row(db: Session, row: QueueRow, plan: dict[str, Any]) -> None:
    postgres = _is_postgres(db)
    assignments = []
    params: dict[str, Any] = {"id": row.id}
    for column in ("footprint", "bbox"):
        if column in plan:
            expr = f"ST_GeomFromEWKT(:{column})" if postgres else f":{column}"
            assignments.append(f"{column} = {expr}")
            params[column] = plan[column]
    if "resolution_m" in plan:
        assignments.append("resolution_m = :resolution_m")
        params["resolution_m"] = plan["resolution_m"]
    db.execute(
        text(f"UPDATE scenes SET {', '.join(assignments)} WHERE id = :id"),
        params,
    )


def apply_batch(
    db: Session, batch: list[Fetched], out: Outcome, *, execute: bool, mode: str = MODE_FILL
) -> None:
    """Record every row's outcome, and write the ones that matched."""
    for fetched in batch:
        row = fetched.row
        out.fetched += 1
        if fetched.outcome != "ok":
            if fetched.outcome == "404":
                out.unmatched_404 += 1
            elif fetched.outcome == "403":
                out.unmatched_403 += 1
            else:
                out.errors += 1
            out.findings.append(
                f"{row.source} {row.collection}/{row.item_id} (scene {row.id}):"
                f" {fetched.detail}; row left untouched"
            )
            continue

        plan = plan_row(fetched, out, mode=mode)
        if not plan:
            continue
        if execute:
            _write_row(db, row, plan)
        out.written += 1
        if "footprint" in plan:
            out.footprints += 1
        if "bbox" in plan:
            out.bboxes += 1
        if "resolution_m" in plan:
            out.resolutions += 1


# ── Reporting ─────────────────────────────────────────────────────────────────


def render_report(
    out: Outcome,
    *,
    execute: bool,
    started: datetime,
    finished: datetime | None,
    requests: int,
    batch_size: int,
) -> str:
    mode = "execute" if execute else "dry run"
    verb = "Wrote" if execute else "Would write"
    pass_name = (
        "footprint revalidation" if out.mode == MODE_REVALIDATE else "snapshot-scene enrichment"
    )
    queue_note = (
        (
            f"Queue at start: **{out.queue_size}** rows"
            f" (`{_QUEUE_PREDICATE[MODE_REVALIDATE]}`, with `:excluded` = `'usgs_topo'`),"
            f" batch size {batch_size}. NORM-31's sweep: every row whose stored"
            " footprint fails `ST_IsValid`, of any provenance, refetched and"
            " rewritten through `normalize_footprint`. Footprint only — no `bbox`"
            " and no `resolution_m` is written in this mode."
        )
        if out.mode == MODE_REVALIDATE
        else (
            f"Queue at start: **{out.queue_size}** rows"
            f" (`provenance = 'snapshot' AND footprint IS NULL AND source <> 'usgs_topo'`),"
            f" batch size {batch_size}. Excluded from the queue: **{out.excluded_topo}**"
            f" `usgs_topo` rows — `usgs-historical-topo` is not a Planetary Computer"
            " collection, so those scenes have no item to fetch."
        )
    )
    state = (
        f"Finished {finished.isoformat(timespec='seconds')}"
        f" ({(finished - started).total_seconds():.0f} s)."
        if finished is not None
        else "**Incomplete — this report was written after a batch, not at the end.**"
    )
    lines = [
        f"# {pass_name.capitalize()} — {mode}",
        "",
        f"Started {started.isoformat(timespec='seconds')}. {state}",
        "",
        queue_note,
        "",
        f"Rows fetched: **{out.fetched}**. STAC requests issued: **{requests}**.",
        "",
        "## Totals",
        "",
        "| Outcome | Rows |",
        "|---|---|",
        f"| matched and written | {out.written} |",
        f"| unmatched — item GET 404 | {out.unmatched_404} |",
        f"| unmatched — item GET 403 | {out.unmatched_403} |",
        f"| error | {out.errors} |",
        "",
        "| Column | Rows |",
        "|---|---|",
        f"| `footprint` {'rewritten' if out.mode == MODE_REVALIDATE else 'filled'}"
        f" | {out.footprints} |",
        f"| `bbox` filled (was NULL) | {out.bboxes} |",
        f"| `resolution_m` rewritten | {out.resolutions} |",
        "",
        f"{verb} {out.written} row(s). Queue after this run:"
        f" **{out.queue_size - out.footprints}**."
        + ("" if execute else " Dry run — nothing written."),
        "",
    ]

    lines += ["## `resolution_m` rewrites, by source", ""]
    if out.resolution_changes:
        lines += ["| Source | Stored | Item | Rows |", "|---|---|---|---|"]
        for source in sorted(out.resolution_changes):
            for (old, new), count in sorted(
                out.resolution_changes[source].items(), key=lambda kv: kv[0][1] or 0
            ):
                lines.append(f"| {source} | {old} | {new} | {count} |")
    else:
        lines.append("None: every fetched item agreed with the value already stored.")
    lines.append("")

    lines += ["## Items carrying no `gsd`", ""]
    if out.no_item_gsd:
        lines += ["| Source | Rows |", "|---|---|"]
        lines += [f"| {source} | {count} |" for source, count in sorted(out.no_item_gsd.items())]
        lines.append("")
        lines.append(
            "`resolution_m` was left as stored for these rows. `None` is never written"
            " over a value."
        )
    else:
        lines.append("None.")
    lines.append("")

    lines += ["## Capture-date disagreements", ""]
    if out.date_disagreements:
        lines += [f"- {note}" for note in out.date_disagreements]
    else:
        lines.append("None. Every matched item's `datetime` equals the row's `capture_date`.")
    lines.append("")

    lines += ["## Anomalies", ""]
    lines += [f"- {note}" for note in out.anomalies] if out.anomalies else ["None."]
    lines.append("")

    lines += [
        "## Footprint invariants, after the run",
        "",
        "All three must be `0`. The third is NORM-31's addition: every prediction"
        " in this arc asked the first two and none asked whether the polygon was"
        " *valid*, which is how two self-intersecting rows passed three layers of"
        " checks.",
        "",
    ]
    if out.invariants is None:
        lines.append("Not checked: PostGIS is not available on this connection.")
    else:
        lines += ["| Check | Rows |", "|---|---|"]
        lines += [
            f"| footprint not `POLYGON` | {out.invariants['not_polygon']} |",
            f"| footprint equal to its own bbox | {out.invariants['equals_bbox']} |",
            f"| footprint fails `ST_IsValid` | {out.invariants['invalid']} |",
        ]
        lines.append("")
        lines.append(f"Query: `{FOOTPRINT_INVARIANT_SQL}`")
    lines.append("")

    lines += [
        "## Findings",
        "",
        "Unresolved ids and unexpected resolutions, one line each. Every row named"
        " here was left exactly as it was.",
        "",
    ]
    lines += [f"- {note}" for note in out.findings] if out.findings else ["None."]
    lines.append("")
    return "\n".join(lines)


def _write_report(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ── Entry point ───────────────────────────────────────────────────────────────


def run(
    db: Session,
    *,
    execute: bool,
    report_path: Path,
    lookup: StacLookup,
    batch_size: int = DEFAULT_BATCH_SIZE,
    mode: str = MODE_FILL,
) -> Outcome:
    started = datetime.now(UTC)
    queue = load_queue(db, mode=mode)
    out = Outcome(mode=mode, queue_size=len(queue), excluded_topo=count_excluded(db))
    if mode == MODE_REVALIDATE:
        print(
            f"queue (footprint IS NOT NULL AND NOT ST_IsValid(footprint),"
            f" source <> '{EXCLUDED_SOURCE}'): {len(queue)} row(s)"
        )
    else:
        print(
            f"queue (provenance = '{QUEUE_PROVENANCE}', footprint IS NULL,"
            f" source <> '{EXCLUDED_SOURCE}'): {len(queue)} row(s);"
            f" {out.excluded_topo} topo row(s) excluded"
        )

    def report(finished: datetime | None) -> str:
        return render_report(
            out,
            execute=execute,
            started=started,
            finished=finished,
            requests=getattr(lookup, "requests", 0),
            batch_size=batch_size,
        )

    async def process() -> None:
        """Every batch on one event loop.

        One loop for the whole run, not one per batch: the client's connection
        pool and the pacer's ``loop.time()`` baseline both belong to the loop
        they were created on, and a fresh loop per batch would silently
        discard the first and corrupt the second.
        """
        try:
            for start in range(0, len(queue), batch_size):
                batch = queue[start : start + batch_size]
                fetched = await fetch_batch(lookup, batch)
                apply_batch(db, fetched, out, execute=execute, mode=mode)
                if execute:
                    db.commit()
                _write_report(report_path, report(None))
                print(
                    f"batch {start // batch_size + 1}: {out.fetched}/{len(queue)} fetched,"
                    f" {out.written} written,"
                    f" {out.unmatched_404 + out.unmatched_403} unmatched,"
                    f" {out.errors} error(s)"
                )
        finally:
            await lookup.aclose()

    asyncio.run(process())

    # Post-run verification, in both modes and both dry run and execute: the
    # invariant is a property of the table, not of this run's writes, and a dry
    # run that reports it is how the production queue gets measured before
    # anything is written.
    out.invariants = check_footprint_invariants(db)

    body = report(datetime.now(UTC))
    _write_report(report_path, body)
    print()
    print(body)
    print(f"Report: {report_path}")
    logger.info(
        "Enriched snapshot scenes",
        extra={
            "execute": execute,
            "mode": mode,
            "queue": out.queue_size,
            "excluded_topo": out.excluded_topo,
            "written": out.written,
            "footprints": out.footprints,
            "bboxes": out.bboxes,
            "resolutions": out.resolutions,
            "unmatched_404": out.unmatched_404,
            "unmatched_403": out.unmatched_403,
            "errors": out.errors,
            "invariants": out.invariants,
        },
    )
    return out


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(
        description="Fill footprint / bbox / resolution_m on provenance='snapshot' scenes"
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Where to write the run report. Required in both modes, and rewritten"
        " after every batch: a killed ssh client takes stdout with it (NORM-8).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the rows. Without it this is a dry run that still fetches.",
    )
    parser.add_argument(
        "--revalidate-footprints",
        action="store_true",
        help="NORM-31 sweep instead of the fill pass: the queue becomes every row"
        " whose stored footprint fails ST_IsValid (any provenance, topo excluded),"
        " refetched and rewritten through normalize_footprint. Footprint only —"
        " no bbox and no resolution_m is written. Requires PostGIS.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per transaction (default {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=FETCH_CONCURRENCY,
        help=f"Max in-flight STAC requests (default {FETCH_CONCURRENCY}).",
    )
    parser.add_argument(
        "--min-interval-s",
        type=float,
        default=DEFAULT_MIN_INTERVAL_S,
        help="Minimum seconds between dispatching successive STAC requests,"
        f" regardless of concurrency (default {DEFAULT_MIN_INTERVAL_S}, NORM-10)."
        " 0 disables pacing.",
    )
    args = parser.parse_args()

    from app.db import SessionLocal

    lookup = StacLookup(concurrency=args.concurrency, min_interval_s=args.min_interval_s)
    out: Outcome | None = None
    try:
        with SessionLocal() as db:
            out = run(
                db,
                execute=args.execute,
                report_path=args.report,
                lookup=lookup,
                batch_size=args.batch_size,
                mode=MODE_REVALIDATE if args.revalidate_footprints else MODE_FILL,
            )
    except OperationalError:
        # An idle dry-run session can be reaped by the DB mid-teardown
        # (NORM-27): the run already finished and `out` was assigned before
        # `Session.__exit__` raised. That is a teardown failure, not a run
        # failure, and must not turn a completed run into a reported one.
        # SQLAlchemy wraps the DBAPI error rather than raising it directly, so
        # this catches ``sqlalchemy.exc.OperationalError`` (the psycopg2 error
        # lands on ``__cause__``, but is not this class and is not a
        # superclass of it) — NORM-29.
        if out is None:
            raise
        logger.error("teardown_operational_error_after_completed_run", exc_info=True)
    # The exit status a detached run's `; echo $? > /tmp/<name>.rc` captures.
    # 404s and 403s are findings about the catalogue, not failures of the run.
    sys.exit(1 if out.errors else 0)


if __name__ == "__main__":
    main()
