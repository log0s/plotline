#!/usr/bin/env python3
"""Re-queue full timelines for the parcel ids given on the command line.

The general heal path. A parcel loses years to a transient upstream — a
signing-rate burst, a Census timeout — and the task still reports
``complete``, so backfill will never retry it (M4). Until per-year failures
are persisted, healing means re-running the whole pipeline for the parcels
an audit identified, and there has been a fresh set of those after every
incident. This script takes ids rather than deriving them, so it does not
need a new heuristic each time.

Parcels with a request already in flight are skipped and logged; the batch
continues, so re-running is safe.

Note on the entry point: this uses ``_create_queued_request`` rather than
``get_or_create_timeline_request``, matching ``revalidate_landsat.py`` and
``requeue_empty_property.py``. get_or_create deliberately *reuses* a
``complete`` request so a second visitor gets an instant answer — and a
damaged parcel's latest request is always complete, which is precisely the
case this script exists to re-run. It still goes through the service, so
the one-in-flight-per-parcel index is a skip rather than a crash that kills
the rest of the batch.

Usage (API + worker must be running):
    docker compose exec api python scripts/requeue_parcels.py --dry-run <id> [<id> ...]
    docker compose exec api python scripts/requeue_parcels.py <id> [<id> ...]
"""

from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.parcels import Parcel
from app.services import imagery as imagery_service


def _known_parcels(parcel_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    with SessionLocal() as db:
        rows = db.execute(select(Parcel.id).where(Parcel.id.in_(parcel_ids))).scalars().all()
    return set(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue timelines for specific parcels")
    parser.add_argument("parcel_ids", nargs="+", help="Parcel UUIDs to re-queue")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be queued without queuing anything",
    )
    args = parser.parse_args()

    try:
        parcel_ids = [uuid.UUID(raw) for raw in args.parcel_ids]
    except ValueError as exc:
        parser.error(f"not a parcel UUID: {exc}")

    known = _known_parcels(parcel_ids)
    unknown = [pid for pid in parcel_ids if pid not in known]
    for pid in unknown:
        print(f"  skipped {pid} — no such parcel")

    targets = [pid for pid in parcel_ids if pid in known]
    if not targets:
        print("Nothing to do.")
        return

    print(f"Re-queuing {len(targets)} parcel(s).")

    if args.dry_run:
        for pid in targets:
            print(f"  would re-queue: {pid}")
        return

    queued = 0
    skipped = len(unknown)
    for parcel_id in targets:
        with SessionLocal() as db:
            try:
                request, created = imagery_service._create_queued_request(db, parcel_id)
            except IntegrityError:
                skipped += 1
                print(f"  skipped {parcel_id} — could not create request")
                continue
            if not created:
                skipped += 1
                print(f"  skipped {parcel_id} — request already in flight")
                continue
            dispatched = imagery_service.dispatch_timeline_task(db, request)

        if not dispatched:
            skipped += 1
            print(f"  skipped {parcel_id} — broker unavailable")
            continue

        queued += 1
        print(f"  queued {request.id} for parcel {parcel_id}")

    print(f"\nDone — queued {queued} timeline request(s), skipped {skipped}.")


if __name__ == "__main__":
    main()
