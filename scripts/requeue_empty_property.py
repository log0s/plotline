#!/usr/bin/env python3
"""Re-queue timelines whose property task completed with zero events.

Before the outage-detection fix, a county portal being unreachable produced
the same result as an address with no records: property task 'complete',
0 items, never retried. The two can't be told apart after the fact, so this
re-runs every candidate — a genuinely empty address simply completes at 0
again, while an outage victim picks up its records.

Only parcels in counties with an adapter are considered, and only the
parcel's most recent timeline request is inspected.

Admission
---------
A full in-flight queue (``max_inflight_timeline_requests``, 30) is a wait,
not a failure: the script polls the same count ``ensure_admission`` gates
on until a slot opens, and gives up only when ``--max-wait-minutes``
(default 60) is spent — then it names the parcels it never reached and
exits non-zero. Catching only ``IntegrityError`` here is what made the
2026-08-25 S2-year sweep abandon 154 of 184 parcels
(``docs/audits/2026-08-s2-year/ADMISSION-FIX.md``). The kill switch is
never waited out.

Usage (worker must be running):
    docker compose exec api python scripts/requeue_empty_property.py --dry-run
    docker compose exec api python scripts/requeue_empty_property.py
    docker compose exec api python scripts/requeue_empty_property.py --county Denver
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask
from app.services import imagery as imagery_service
from app.services.admission import AdmissionRefused
from app.services.county_adapters import get_adapter_for_county


def find_candidates(county_filter: str | None) -> list[tuple[uuid.UUID, str]]:
    """Return (parcel_id, county) for parcels whose latest request recorded
    property as complete-with-0."""
    latest = (
        select(
            TimelineRequest.parcel_id.label("parcel_id"),
            func.max(TimelineRequest.created_at).label("created_at"),
        )
        .group_by(TimelineRequest.parcel_id)
        .subquery()
    )

    stmt = (
        select(Parcel.id, Parcel.county)
        .join(latest, latest.c.parcel_id == Parcel.id)
        .join(
            TimelineRequest,
            (TimelineRequest.parcel_id == latest.c.parcel_id)
            & (TimelineRequest.created_at == latest.c.created_at),
        )
        .join(
            TimelineRequestTask,
            TimelineRequestTask.timeline_request_id == TimelineRequest.id,
        )
        .where(TimelineRequest.status == "complete")
        .where(TimelineRequestTask.source == "property")
        .where(TimelineRequestTask.status == "complete")
        .where(TimelineRequestTask.items_found == 0)
        .where(Parcel.county.isnot(None))
    )

    with SessionLocal() as db:
        rows = db.execute(stmt).all()

    candidates: list[tuple[uuid.UUID, str]] = []
    for parcel_id, county in rows:
        if county_filter and county.lower() != county_filter.lower():
            continue
        # Counties without an adapter were marked skipped, not complete, but
        # filter anyway so a retired adapter doesn't get pointless work.
        if get_adapter_for_county(county) is None:
            continue
        candidates.append((parcel_id, county))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue empty property timelines")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected parcels without queuing anything",
    )
    parser.add_argument(
        "--county",
        help="Only re-queue parcels in this county (e.g. Denver)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after queuing this many requests",
    )
    parser.add_argument(
        "--max-wait-minutes",
        type=float,
        default=60.0,
        help="Total time to spend waiting for admission slots before giving "
        "up and reporting the parcels not reached (default: 60)",
    )
    args = parser.parse_args()

    if args.max_wait_minutes < 0:
        parser.error("--max-wait-minutes cannot be negative")

    candidates = find_candidates(args.county)
    if not candidates:
        print("No parcels with an empty property task found.")
        return

    print(f"Found {len(candidates)} parcel(s) with property complete-with-0.")

    if args.dry_run:
        for parcel_id, county in candidates:
            print(f"  would re-queue: {parcel_id} ({county})")
        return

    deadline = time.monotonic() + args.max_wait_minutes * 60
    queued = 0
    skipped = 0
    unreached: list[uuid.UUID] = []
    for index, (parcel_id, county) in enumerate(candidates):
        if args.limit is not None and queued >= args.limit:
            break

        with SessionLocal() as db:
            try:
                request, created = imagery_service.create_queued_request_waiting(
                    db, parcel_id, deadline=deadline
                )
            except AdmissionRefused as exc:
                unreached = [pid for pid, _ in candidates[index:]]
                print(f"  stopping at {parcel_id} — admission refused ({exc.reason})")
                break
            except IntegrityError:
                skipped += 1
                print(f"  skipped {parcel_id} ({county}) — could not create request")
                continue
            if not created:
                skipped += 1
                print(f"  skipped {parcel_id} ({county}) — request already in flight")
                continue
            dispatched = imagery_service.dispatch_timeline_task(db, request)

        if not dispatched:
            skipped += 1
            print(f"  skipped {parcel_id} ({county}) — broker unavailable")
            continue

        queued += 1
        print(f"  queued {request.id} for parcel {parcel_id} ({county})")

    print(f"\nDone — queued {queued} timeline request(s), skipped {skipped}.")

    if unreached:
        print(
            f"\n{len(unreached)} parcel(s) NOT reached — the wait budget "
            f"({args.max_wait_minutes} min) ran out:",
            file=sys.stderr,
        )
        for pid in unreached:
            print(f"  unreached: {pid}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
