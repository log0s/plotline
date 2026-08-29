#!/usr/bin/env python3
"""Read-only invariant battery over ``scenes`` / ``parcel_scenes``.

The checks steps 2 and 3 ran as ad-hoc SQL, written down. Two reasons they
stop being ad-hoc here:

* **Attribution.** Every whole-table scan goes through
  ``scripts/shared/probe.probe_count``, which logs an ``audit_probe`` event
  naming the table and the reason before it runs
  (``NORM31-PROD-REPORT.md`` §6d.3). A ``seq_scan`` delta over a measured
  window is then either matched by an event or it is a finding. Ad-hoc SQL
  moves the same counters and leaves no trace of who moved them, which is what
  made the step-3 reading's +15 an explanation rather than an attribution.
* **One definition per invariant.** "Duplicate group", "dangling reference"
  and "landsat conservation" were spelled out per session; a battery that
  drifts between sessions cannot support a comparison across them.

**Read-only, and scoped so it cannot leak.** Everything runs inside one
transaction opened with ``SET TRANSACTION READ ONLY`` — transaction-scoped, so
it cannot outlive the connection's lease on a transaction-mode pooler
(NORM-30). A session-level equivalent is forbidden.

Usage::

    docker compose exec api python scripts/normalization_invariants.py
    docker compose exec api python scripts/normalization_invariants.py \\
        --out docs/audits/2026-08-normalization/step4-sweep.json

Exit code is 0 when every invariant holds and 1 when any does not, so a sweep
can be gated on it rather than on reading the output.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logging_config import configure_script_logging
from scripts.shared.probe import audit_probe, probe_count

logger = logging.getLogger("normalization_invariants")

READ_ONLY_STATEMENT = "SET TRANSACTION READ ONLY"

# Each entry: (name, table, WHERE predicate or None, expected value).
# ``None`` as the expected value means "report it, do not judge it".
_ZERO_CHECKS: tuple[tuple[str, str, str | None], ...] = (
    # UNIQUE (parcel_id, source, group_key) makes this structurally
    # impossible; it is checked anyway because a constraint that is believed
    # rather than tested is how G3 lasted as long as it did.
    (
        "duplicate_groups",
        "parcel_scenes ps",
        "EXISTS (SELECT 1 FROM parcel_scenes o WHERE o.id <> ps.id"
        "  AND o.parcel_id = ps.parcel_id AND o.source = ps.source"
        "  AND o.group_key = ps.group_key)",
    ),
    # A served row whose primary scene is gone. The FK forbids it; same
    # reasoning as above.
    (
        "dangling_primary",
        "parcel_scenes ps",
        "NOT EXISTS (SELECT 1 FROM scenes s WHERE s.id = ps.scene_id)",
    ),
    # A mosaic reference to no scene. **This one is not constrained** —
    # ``mosaic_scene_ids`` is a uuid[] and PostgreSQL has no per-element
    # foreign key — so it is the check in this battery that can actually fail,
    # and the reason the battery exists rather than a comment saying the
    # constraints hold.
    (
        "dangling_mosaic",
        "parcel_scenes ps",
        "EXISTS (SELECT 1 FROM unnest(ps.mosaic_scene_ids) AS m(id)"
        "  WHERE NOT EXISTS (SELECT 1 FROM scenes s WHERE s.id = m.id))",
    ),
    # A scene naming itself as one of its own additional tiles.
    (
        "primary_in_own_mosaic",
        "parcel_scenes ps",
        "ps.scene_id = ANY(ps.mosaic_scene_ids)",
    ),
    # NORM-31's queue, and 0018's CHECK expressed as a query. Zero here and a
    # passing 0018 are two independent statements of the same fact; the CHECK
    # can only refuse new rows, this counts what is there.
    (
        "invalid_footprints",
        "scenes",
        "footprint IS NOT NULL AND NOT ST_IsValid(footprint)",
    ),
    (
        "non_polygon_footprints",
        "scenes",
        "footprint IS NOT NULL AND GeometryType(footprint) <> 'POLYGON'",
    ),
    # Every catalogued item is one row. UNIQUE (collection, item_id) covers
    # the exact-id case; this is the same statement, checked.
    (
        "duplicate_items",
        "scenes s",
        "EXISTS (SELECT 1 FROM scenes o WHERE o.id <> s.id"
        "  AND o.collection = s.collection AND o.item_id = s.item_id)",
    ),
)


def _rows(db: Session, sql: str, params: dict[str, object] | None = None) -> list[Any]:
    return list(db.execute(sa_text(sql), params or {}).mappings())


def collect(db: Session) -> dict[str, Any]:
    """Every invariant, as numbers. Judges nothing; ``verdicts`` does that."""
    out: dict[str, Any] = {
        "read_at": datetime.now(UTC).isoformat(),
        "totals": {},
        "zero_checks": {},
        "landsat_conservation": {},
        "ledger_outcomes": {},
        "provenance": {},
    }

    for table in ("parcels", "scenes", "parcel_scenes"):
        out["totals"][table] = probe_count(db, table, purpose="step-4 sweep, fleet totals")

    for name, target, predicate in _ZERO_CHECKS:
        table, _, alias = target.partition(" ")
        sql = f"SELECT count(*) FROM {table}"  # noqa: S608  # literals above
        if alias:
            sql += f" {alias}"
        if predicate:
            sql += f" WHERE {predicate}"
        audit_probe(table, purpose=f"step-4 sweep, {name}")
        out["zero_checks"][name] = int(db.execute(sa_text(sql)).scalar() or 0)

    # Landsat conservation, per parcel. The geometry heal's standard: a
    # structural change must not lose a parcel's Landsat coverage. Reported
    # per parcel rather than as a total, because a total conserves while two
    # parcels swap.
    audit_probe("parcel_scenes", purpose="step-4 sweep, landsat per parcel")
    out["landsat_conservation"] = {
        str(r["parcel_id"]): int(r["n"])
        for r in _rows(
            db,
            "SELECT parcel_id, count(*) AS n FROM parcel_scenes"
            " WHERE source = 'landsat' GROUP BY parcel_id ORDER BY parcel_id",
        )
    }

    # The ledger's outcome distribution, read per NORM-3: the latest row per
    # (parcel, source, group_key), because an earlier failure that has since
    # been retried is not a current failure.
    audit_probe("timeline_task_years", purpose="step-4 sweep, latest outcome per group")
    out["ledger_outcomes"] = {
        f"{r['source']}/{r['outcome']}": int(r["n"])
        for r in _rows(
            db,
            """
            WITH latest AS (
                SELECT DISTINCT ON (tr.parcel_id, tty.source, tty.group_key)
                       tty.source, tty.outcome
                FROM timeline_task_years tty
                JOIN timeline_request_tasks t ON t.id = tty.task_id
                JOIN timeline_requests tr ON tr.id = t.timeline_request_id
                ORDER BY tr.parcel_id, tty.source, tty.group_key, tty.created_at DESC
            )
            SELECT source, outcome, count(*) AS n
            FROM latest GROUP BY source, outcome ORDER BY source, outcome
            """,
        )
    }

    audit_probe("scenes", purpose="step-4 sweep, provenance split")
    out["provenance"] = {
        str(r["provenance"]): int(r["n"])
        for r in _rows(
            db,
            "SELECT provenance, count(*) AS n FROM scenes GROUP BY provenance ORDER BY provenance",
        )
    }
    return out


def verdicts(reading: dict[str, Any]) -> list[str]:
    """The failures, as sentences. Empty means every invariant held."""
    return [
        f"{name}: expected 0, got {value}"
        for name, value in reading["zero_checks"].items()
        if value != 0
    ]


def render(reading: dict[str, Any], failures: list[str]) -> str:
    lines = [f"normalization invariants at {reading['read_at']}", ""]
    lines.append("totals")
    for name, value in reading["totals"].items():
        lines.append(f"  {name:<16} {value}")
    lines += ["", "must be zero"]
    for name, value in reading["zero_checks"].items():
        mark = "ok " if value == 0 else "!! "
        lines.append(f"  {mark}{name:<24} {value}")
    lines += ["", "scenes by provenance"]
    for name, value in reading["provenance"].items():
        lines.append(f"  {name:<16} {value}")

    landsat = reading["landsat_conservation"]
    counts = sorted(landsat.values())
    lines += [
        "",
        f"landsat per parcel: {len(landsat)} parcels, {sum(counts)} rows,"
        f" min {counts[0] if counts else 0}, max {counts[-1] if counts else 0}",
        "",
        "ledger, latest outcome per (parcel, source, group)",
    ]
    for name, value in sorted(reading["ledger_outcomes"].items()):
        lines.append(f"  {name:<32} {value}")

    lines += [""]
    lines += [f"FAIL {f}" for f in failures] or ["every invariant holds"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only normalization invariant battery")
    parser.add_argument("--out", help="Write the raw reading here as JSON")
    args = parser.parse_args()

    configure_script_logging()

    with SessionLocal() as db:
        # Transaction-scoped read-only, and it must stay that way: a
        # session-level equivalent leaks through the pooler onto a shared
        # backend (NORM-30). Must be the transaction's first statement.
        db.execute(sa_text(READ_ONLY_STATEMENT))
        reading = collect(db)
        db.rollback()

    failures = verdicts(reading)
    print(render(reading, failures))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(reading, fh, indent=2, sort_keys=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
