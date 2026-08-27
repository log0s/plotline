#!/usr/bin/env python3
"""Report the latest per-year outcome for every (parcel, source, group).

Read-only. This is the query M3 will target, written down first so the
sweep after the M4 deploy has something to diff against.

What it answers, which nothing could answer before the ledger existed:

  * which (parcel, source, group_key) triples have *never* recorded an ``ok``
  * what the last attempt on each said, and why
  * how many times a still-failing group has been attempted, across runs

"Latest" is by the timeline request's ``created_at``, so a group healed on
run 5 reads ``ok`` even though runs 1-4 recorded failures — and a group that
was ``ok`` on run 1 and has failed ever since reads ``failed``, which is the
direction that matters.

The ledger starts at deploy and carries no history: a parcel last fetched
before then has no rows here, and shows as nothing rather than as a gap.
Absence from this report is not evidence of health until every parcel has
been swept once.

Usage (read-only, safe against production):
    docker compose exec api python scripts/ledger_gaps.py
    docker compose exec api python scripts/ledger_gaps.py --source landsat --outcome failed
    docker compose exec api python scripts/ledger_gaps.py --parcel <uuid> --all
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.services import ledger as ledger_service

# The latest-outcome query itself lives in ``app/services/ledger.py`` so this
# report, ``maybe_refetch_for_backfill`` and ``requeue_parcels.py
# --from-ledger`` cannot disagree about what "latest" means. Reading a report
# built on one definition and then healing on another is how a sweep misses
# exactly the rows the operator was looking at.

# Every reason ever recorded for a triple, so a group that failed three
# different ways is not reported as if it failed the same way three times.
_REASONS_SQL = """
SELECT r.parcel_id AS parcel_id,
       y.source    AS source,
       y.group_key AS group_key,
       y.outcome   AS outcome,
       y.reason    AS reason
FROM timeline_task_years y
JOIN timeline_request_tasks t ON t.id = y.task_id
JOIN timeline_requests r      ON r.id = t.timeline_request_id
WHERE y.reason IS NOT NULL
"""

# Outcomes a heal would act on. Deliberately *not* the retry policy: this is
# a reporting filter, and it is wider on purpose. ``indeterminate`` is a code
# fix rather than a retry, and ``suppressed`` is reconciliation input rather
# than either — but all three are things a human should be looking at, and
# collapsing the report onto ``ledger.is_retryable`` would hide the two
# classes that need a decision made about them. The ``retry`` column below is
# where the policy's own answer appears, row by row.
ACTIONABLE = ("failed", "indeterminate", "suppressed")


@dataclass(frozen=True)
class LedgerRow:
    """One (parcel, source, group) triple's latest recorded outcome.

    ``same_sha`` is only meaningful for ``outcome == "absent"``: it marks a
    group ``requeue_parcels.py --from-ledger`` excludes from
    ``--include-absent-api`` / ``--include-cloud-filtered`` selection because
    it was already recorded under the SHA this process is running (Y7) — the
    exclusion is visible here rather than a silent zero in the heal's dry-run.
    """

    parcel_id: str
    source: str
    group_key: str
    outcome: str
    reason: str
    attempts: int
    reasons_seen: tuple[str, ...]
    policy: str
    stale: bool
    same_sha: bool


def _fetch(source: str | None, parcel: str | None, outcome: str | None) -> list[LedgerRow]:
    current_sha = get_settings().git_sha
    with SessionLocal() as db:
        groups = ledger_service.latest_outcomes(db)
        reason_rows = db.execute(text(_REASONS_SQL)).mappings().all()

    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for raw in reason_rows:
        seen[(str(raw["parcel_id"]), str(raw["source"]), str(raw["group_key"]))].add(
            str(raw["reason"])
        )

    result: list[LedgerRow] = []
    for group in groups:
        key = (str(group.parcel_id), group.source, group.group_key)
        if source and key[1] != source:
            continue
        if parcel and key[0] != parcel:
            continue
        if outcome and group.outcome != outcome:
            continue
        result.append(
            LedgerRow(
                parcel_id=key[0],
                source=key[1],
                group_key=key[2],
                outcome=group.outcome,
                reason=group.reason or "",
                attempts=group.attempts,
                reasons_seen=tuple(sorted(seen.get(key, ()))),
                policy=ledger_service.retry_policy(group.outcome, group.reason),
                stale=ledger_service.is_stale(group),
                same_sha=(
                    group.outcome == "absent"
                    and ledger_service.same_deployed_sha(group, current_sha)
                ),
            )
        )
    return result


def _print_table(rows: list[LedgerRow]) -> None:
    if not rows:
        print("No ledger rows match.")
        return

    headers = (
        "parcel",
        "source",
        "group",
        "outcome",
        "reason",
        "n",
        "retry",
        "same_sha",
        "reasons seen",
    )
    table = [
        (
            r.parcel_id[:8],
            r.source,
            r.group_key,
            r.outcome,
            r.reason,
            str(r.attempts),
            r.policy,
            "same" if r.same_sha else "",
            ",".join(r.reasons_seen) if r.outcome in ACTIONABLE else "",
        )
        for r in rows
    ]
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    print("  ".join("-" * w for w in widths))
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


def _print_stale(rows: list[LedgerRow]) -> None:
    """Groups current code will never attempt again — the Y3 bucket.

    Never selected by ``ledger_service.retryable_groups`` regardless of
    outcome or flags; listed here instead of silently excluded, because the
    ledger's job is to show, not to hide (census 1990/api_no_data after
    ``e6afa9b`` is the instance this exists for).
    """
    stale = [r for r in rows if r.stale]
    if not stale:
        return

    print()
    print(f"{len(stale)} stale (parcel, source, group) triple(s) — never selected, any flag:")
    by_source_group: dict[tuple[str, str], int] = defaultdict(int)
    for r in stale:
        by_source_group[(r.source, r.group_key)] += 1
    for (src, group_key), count in sorted(by_source_group.items()):
        print(f"  {src:<18} {group_key:<8} {count}")


def _print_summary(rows: list[LedgerRow]) -> None:
    by_outcome: dict[str, int] = defaultdict(int)
    by_source_outcome: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        by_outcome[r.outcome] += 1
        by_source_outcome[(r.source, r.outcome)] += 1

    print()
    print(f"{len(rows)} (parcel, source, group) triples with a recorded outcome.")
    for outcome in sorted(by_outcome):
        print(f"  {outcome:<14} {by_outcome[outcome]}")
    print()
    for src, out in sorted(by_source_outcome):
        print(f"  {src:<18} {out:<14} {by_source_outcome[(src, out)]}")


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(description="Per-year ledger gaps, latest outcome per group")
    parser.add_argument("--source", default=None, help="Filter to one ledger source")
    parser.add_argument("--parcel", default=None, help="Filter to one parcel id")
    parser.add_argument("--outcome", default=None, help="Filter to one outcome")
    parser.add_argument(
        "--all",
        action="store_true",
        help="List every row, not only the actionable (failed / indeterminate) ones",
    )
    parser.add_argument("--limit", type=int, default=None, help="Print at most N rows")
    args = parser.parse_args()

    print(f"Current deployed SHA (this process): {get_settings().git_sha}")

    rows = _fetch(args.source, args.parcel, args.outcome)

    listed = rows if (args.all or args.outcome) else [r for r in rows if r.outcome in ACTIONABLE]
    if args.limit is not None and len(listed) > args.limit:
        print(f"Listing {args.limit} of {len(listed)} matching rows (--limit).")
        listed = listed[: args.limit]

    _print_table(listed)
    _print_summary(rows)
    _print_stale(rows)


if __name__ == "__main__":
    main()
