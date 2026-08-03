#!/usr/bin/env python3
"""Re-run the census fetch for parcels that already have census snapshots.

ACS rows written before B25001_001E was added to the requested variable set
have no total_housing_units, so the Housing chart filtered them out. The
census upsert refreshes on conflict, so simply re-fetching heals them in
place — no deletes, no new rows.

Usage (API + worker must be running):
    docker compose exec api python scripts/backfill_census_housing.py
    docker compose exec api python scripts/backfill_census_housing.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.models.parcels import TimelineRequest
from app.tasks.timeline import _fetch_census

# The fetch itself already sleeps 0.5s between year requests; this is the
# additional pause between parcels (14 requests each) to stay well under the
# Census API's per-key rate limit.
DEFAULT_DELAY = 2.0


def _parcels_needing_backfill() -> list[tuple[str, str]]:
    """Return (parcel_id, tract_fips) for parcels with incomplete housing data."""
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT DISTINCT c.parcel_id, p.census_tract_id
                FROM census_snapshots c
                JOIN parcels p ON p.id = c.parcel_id
                WHERE p.census_tract_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM census_snapshots c2
                      WHERE c2.parcel_id = c.parcel_id
                        AND c2.dataset = 'acs5'
                        AND c2.total_housing_units IS NULL
                  )
                ORDER BY c.parcel_id
                """
            )
        ).all()
    return [(str(r[0]), r[1]) for r in rows]


def _timeline_request_id(parcel_id: str) -> str:
    """Reuse the parcel's latest timeline request, creating one if absent."""
    with SessionLocal() as db:
        existing = db.execute(
            text(
                "SELECT id FROM timeline_requests WHERE parcel_id = :pid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"pid": parcel_id},
        ).first()
        if existing:
            return str(existing[0])

        request = TimelineRequest(parcel_id=parcel_id, status="queued")
        db.add(request)
        db.commit()
        db.refresh(request)
        return str(request.id)


def _housing_coverage() -> list[tuple[str, int, int]]:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT dataset, COUNT(*),
                       COUNT(*) FILTER (
                           WHERE total_housing_units IS NOT NULL
                             AND owner_occupied_units IS NOT NULL
                       )
                FROM census_snapshots GROUP BY dataset ORDER BY dataset
                """
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def _report(label: str) -> None:
    print(f"{label}:")
    for dataset, total, complete in _housing_coverage():
        print(f"  {dataset:<10} {complete}/{total} rows with total units + occupancy")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill census housing fields")
    parser.add_argument(
        "--dry-run", action="store_true", help="List affected parcels without fetching"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help="Seconds to pause between parcels"
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N parcels")
    args = parser.parse_args()

    targets = _parcels_needing_backfill()
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("No parcels need a census housing backfill.")
        return

    print(f"Found {len(targets)} parcel(s) with ACS rows missing total_housing_units.")

    if args.dry_run:
        for parcel_id, tract in targets:
            print(f"  would refetch: {parcel_id} (tract {tract})")
        return

    _report("Before")

    settings = get_settings()
    healed = 0
    failed = 0

    for i, (parcel_id, tract) in enumerate(targets, start=1):
        request_id = _timeline_request_id(parcel_id)
        try:
            saved = asyncio.run(
                _fetch_census(
                    parcel_id,
                    request_id,
                    tract,
                    api_key=settings.census_api_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad parcel must not end the run
            failed += 1
            print(f"  [{i}/{len(targets)}] {parcel_id} FAILED: {exc}")
        else:
            healed += 1
            print(f"  [{i}/{len(targets)}] {parcel_id} tract {tract}: {saved} snapshot(s)")

        if i < len(targets):
            asyncio.run(asyncio.sleep(args.delay))

    print(f"\nRefetched {healed} parcel(s), {failed} failed.")
    _report("After")


if __name__ == "__main__":
    main()
