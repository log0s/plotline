#!/usr/bin/env python3
"""Read PostgreSQL's own access counters for the imagery tables.

ADR 0001 step 4 retires the denormalized table "after one cooling period with
no reads (**measured, not assumed**)".

**This is the only instrument left, and that is the point.** Step 3 needed
two, because the table still had one legitimate reader — the reconciler's
existing-rows pull — and a bare counter delta could not tell that reader apart
from an unexpected one. So the application logged an
``imagery_snapshots_read`` event naming its caller, and this script counted
every access by anything, and the difference between them was the population
the cooling period was looking for.

Step 4's code cutover deleted the last caller. The expected count is now
**exactly zero, from anything**, which a counter can express on its own and a
per-caller log cannot improve on: there is no caller to name, and the event's
absence would prove nothing about an uninstrumented reader. The log half was
therefore deleted with the reader it named, and the claim this script supports
got stronger rather than weaker — "no application code reads it" became "the
database recorded no access at all".

**This script never touches the tables it reports on.** It reads
``pg_stat_user_tables``, so its own scans do not appear in the numbers it
prints. Ad-hoc ``count(*)`` probes *do* — that is exactly the +15 seq_scan the
step-3 reading had to explain by arithmetic (NORM31-PROD-REPORT.md §6c) — so
an audit that wants to count rows should go through
``scripts/shared/probe.probe_count``, which logs an ``audit_probe`` event
naming the table and the reason before it scans. This script emits the same
event for the statistics views it reads, so a reading is attributable by the
same grep as everything else.

**How to use it.** Take a reading at the start of the cooling period and
another at the end, and difference them::

    fly ssh console -a log0s-plotline-api -C \\
        "python scripts/snapshot_reads.py --out /tmp/reads-start.json"
    # ... cooling period ...
    fly ssh console -a log0s-plotline-api -C \\
        "python scripts/snapshot_reads.py --baseline /tmp/reads-start.json"

**What the counters mean, and their one trap.** ``seq_scan`` and ``idx_scan``
count *scans*, not rows, and they are incremented by the planner for writes
too: a ``DELETE ... WHERE id = :id`` costs an ``idx_scan``, and so does an
upsert's conflict probe. So a nonzero delta is not by itself a read — it is
"something touched this table". For ``parcel_scenes`` and ``scenes`` that
ambiguity is why ``n_tup_ins``/``upd``/``del`` are printed alongside; for the
retired table the expected value of every counter is zero and the distinction
does not arise. **The counters reset** on ``pg_stat_reset()`` and are not
guaranteed to survive a server restart, so a *smaller* number than the
baseline means the counter reset, not that reads went backwards; the script
says so rather than reporting a negative delta.

**Read-only, and scoped so it cannot leak.** Two SELECTs against the
statistics views inside a transaction opened with ``SET TRANSACTION READ
ONLY``. This script used to issue ``SET default_transaction_read_only = on``
and *commit* it, which is a session-level GUC; against Neon's
transaction-mode pooler a session GUC outlives the client that set it and
lands on whichever client borrows that backend next. It made a shared
production backend read-only and killed an authorized write mid-run
(NORM-30, ``docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT-3.md``
§6b). ``SET TRANSACTION`` applies to the current transaction only and is gone
at COMMIT, so it cannot outlive the connection's lease.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logging_config import configure_script_logging
from scripts.shared.probe import audit_probe

# ``imagery_snapshots`` stays in this list while the table exists. It is the
# subject of the cooling measurement — the whole reading is "did anything
# touch it" — and ``render`` prints "not present" rather than failing once
# migration 0019 has dropped it, which is what turns this script from the
# instrument that gates the drop into the one that confirms it.
TABLES = ("imagery_snapshots", "parcel_scenes", "scenes")

# Transaction-scoped read-only. Exported so tests/test_pooler_safe_reads.py can
# execute this exact statement against a real Postgres rather than a copy of it.
READ_ONLY_STATEMENT = "SET TRANSACTION READ ONLY"

_COUNTERS = (
    "seq_scan",
    "seq_tup_read",
    "idx_scan",
    "idx_tup_fetch",
    "n_tup_ins",
    "n_tup_upd",
    "n_tup_del",
    "n_live_tup",
)


def read_counters(db: Session) -> dict[str, Any]:
    audit_probe(
        "pg_stat_user_tables",
        purpose="ADR 0001 step-4 cooling reading",
        subjects=list(TABLES),
    )
    placeholders = ",".join(f":t{i}" for i in range(len(TABLES)))
    params = {f"t{i}": name for i, name in enumerate(TABLES)}
    rows = db.execute(
        sa_text(
            f"SELECT relname, {', '.join(_COUNTERS)}"
            f" FROM pg_stat_user_tables WHERE relname IN ({placeholders})"
        ),
        params,
    ).mappings()
    tables = {row["relname"]: {c: int(row[c] or 0) for c in _COUNTERS} for row in rows}

    reset = db.execute(
        sa_text("SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()")
    ).scalar()

    return {
        "read_at": datetime.now(UTC).isoformat(),
        "stats_reset": str(reset) if reset else None,
        "tables": tables,
    }


def render(now: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    lines = [f"pg_stat_user_tables at {now['read_at']}", f"stats_reset: {now['stats_reset']}", ""]
    if baseline is not None:
        lines[0] += f"  (delta since {baseline['read_at']})"
        if baseline.get("stats_reset") != now.get("stats_reset"):
            lines.append(
                "!! stats_reset differs from the baseline — the counters were "
                "reset in between, so the deltas below are not comparable."
            )
            lines.append("")

    width = max(len(c) for c in _COUNTERS) + 2
    for name in TABLES:
        current = now["tables"].get(name)
        if current is None:
            lines += [f"{name}: not present", ""]
            continue
        lines.append(name)
        for counter in _COUNTERS:
            value = current[counter]
            if baseline is None:
                lines.append(f"  {counter:<{width}} {value}")
                continue
            before = baseline["tables"].get(name, {}).get(counter, 0)
            delta = value - before
            note = "  (counter went backwards — reset?)" if delta < 0 else ""
            lines.append(f"  {counter:<{width}} {value}  delta {delta:+}{note}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read imagery table access counters")
    parser.add_argument("--out", help="Write the raw reading here as JSON")
    parser.add_argument("--baseline", help="An earlier --out file to difference against")
    args = parser.parse_args()

    configure_script_logging()

    baseline = None
    if args.baseline:
        with open(args.baseline) as fh:
            baseline = json.load(fh)

    with SessionLocal() as db:
        # Transaction-scoped, and it must stay that way: Postgres rejects SET
        # TRANSACTION after the first query, and a session-level equivalent
        # would leak through the pooler onto a shared backend (NORM-30).
        db.execute(sa_text(READ_ONLY_STATEMENT))
        now = read_counters(db)
        db.rollback()

    print(render(now, baseline))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(now, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
