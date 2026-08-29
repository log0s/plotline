#!/usr/bin/env python3
"""Read PostgreSQL's own access counters for ``imagery_snapshots``.

ADR 0001 step 4 retires the table "after one cooling period with no reads
(**measured, not assumed**)". Two instruments are needed for that, because
neither is sufficient alone:

* ``app/services/imagery.py``'s ``imagery_snapshots_read`` structlog event
  names *which* caller read the table. After the step-3 cutover the only
  legitimate one is ``reconcile_source_snapshots.existing_rows``. It cannot
  see a reader that does not call it.
* **This script**, which reads ``pg_stat_user_tables`` — the database's own
  count of every scan of the table, by anything, instrumented or not. It
  cannot name a caller.

Together they answer step 4's question: the counters say how many reads
happened, the log says how many of them were the reconciler, and the
difference is the population the cooling period is looking for.

**How to use it.** Take a reading at the start of the cooling period and
another at the end, and difference them::

    fly ssh console -a log0s-plotline-api -C \\
        "python scripts/snapshot_reads.py --out /tmp/reads-start.json"
    # ... cooling period ...
    fly ssh console -a log0s-plotline-api -C \\
        "python scripts/snapshot_reads.py --baseline /tmp/reads-start.json"

**What the counters mean, and their one trap.** ``seq_scan`` and ``idx_scan``
count *scans*, not rows, and they are incremented by the planner for writes
too: the ``DELETE ... WHERE id = :id`` the reconciler issues costs an
``idx_scan``, and so does the upsert's conflict probe. So a nonzero delta is
not by itself a read — it is "something touched this table", and the log is
what splits it. **The counters reset** on ``pg_stat_reset()`` and are not
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
    parser = argparse.ArgumentParser(description="Read imagery_snapshots access counters")
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
