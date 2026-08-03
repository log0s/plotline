#!/usr/bin/env python3
"""Re-queue timelines whose property task completed with zero events.

Before the outage-detection fix, a county portal being unreachable produced
the same result as an address with no records: property task 'complete',
0 items, never retried. The two can't be told apart after the fact, so this
re-runs every candidate — a genuinely empty address simply completes at 0
again, while an outage victim picks up its records.

Only parcels in counties with an adapter are considered, and only the
parcel's most recent timeline request is inspected.

Usage (worker must be running):
    docker compose exec api python scripts/requeue_empty_property.py --dry-run
    docker compose exec api python scripts/requeue_empty_property.py
    docker compose exec api python scripts/requeue_empty_property.py --county Denver
"""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.parcels import Parcel, TimelineRequest, TimelineRequestTask
from app.services import imagery as imagery_service
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
    args = parser.parse_args()

    candidates = find_candidates(args.county)
    if not candidates:
        print("No parcels with an empty property task found.")
        return

    print(f"Found {len(candidates)} parcel(s) with property complete-with-0.")

    if args.dry_run:
        for parcel_id, county in candidates:
            print(f"  would re-queue: {parcel_id} ({county})")
        return

    queued = 0
    skipped = 0
    for parcel_id, county in candidates:
        if args.limit is not None and queued >= args.limit:
            break

        with SessionLocal() as db:
            try:
                request, created = imagery_service._create_queued_request(db, parcel_id)
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


if __name__ == "__main__":
    main()
