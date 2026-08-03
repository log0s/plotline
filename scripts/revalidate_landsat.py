#!/usr/bin/env python3
"""Re-queue timelines for parcels that have Landsat imagery.

Older Landsat scenes (1984–1990s) sometimes lose asset availability on
Planetary Computer and start returning 502s from the tile server. A re-run
re-validates each selected scene's bands and swaps in the next-best
candidate for that year, then reconciliation deletes the scene it replaced
— so a parcel ends up with one working card per year rather than a working
card next to a broken one.

Parcels with a timeline request already in flight are skipped and logged;
the batch continues. Re-running the script is therefore safe.

Usage (API + worker must be running):
    docker compose exec api python scripts/revalidate_landsat.py
    docker compose exec api python scripts/revalidate_landsat.py --dry-run
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.parcels import ImagerySnapshot
from app.services import imagery as imagery_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue Landsat timelines")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected parcels without queuing anything",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        parcel_ids = (
            db.execute(
                select(ImagerySnapshot.parcel_id)
                .where(ImagerySnapshot.source == "landsat")
                .group_by(ImagerySnapshot.parcel_id)
            )
            .scalars()
            .all()
        )

    if not parcel_ids:
        print("No parcels with Landsat imagery found.")
        return

    print(f"Found {len(parcel_ids)} parcel(s) with Landsat imagery.")

    if args.dry_run:
        for pid in parcel_ids:
            print(f"  would re-queue: {pid}")
        return

    queued = 0
    skipped = 0
    for parcel_id in parcel_ids:
        with SessionLocal() as db:
            # Goes through the service so the one-in-flight-per-parcel index
            # is a skip, not a crash that kills the rest of the batch.
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
