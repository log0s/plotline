#!/usr/bin/env python3
"""Re-queue timeline requests for parcels with Landsat imagery.

The new band-validation logic in the ingest pipeline will replace broken
snapshots (old scenes returning 502s) with valid alternatives via
upsert_imagery_snapshot.

Usage (API + worker must be running):
    docker compose exec api python scripts/revalidate_landsat.py
    docker compose exec api python scripts/revalidate_landsat.py --dry-run
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models.parcels import ImagerySnapshot, TimelineRequest
from app.tasks.timeline import fetch_imagery_timeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue Landsat timelines")
    parser.add_argument(
        "--dry-run", action="store_true",
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
    for parcel_id in parcel_ids:
        with SessionLocal() as db:
            request = TimelineRequest(parcel_id=parcel_id, status="queued")
            db.add(request)
            db.commit()
            db.refresh(request)

        fetch_imagery_timeline.delay(str(request.id))
        queued += 1
        print(f"  queued {request.id} for parcel {parcel_id}")

    print(f"\nDone — queued {queued} timeline request(s).")


if __name__ == "__main__":
    main()
