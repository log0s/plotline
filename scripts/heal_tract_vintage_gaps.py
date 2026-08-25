#!/usr/bin/env python3
"""Re-fetch census years lost to the 2020 tract redistricting.

A parcel's census_tract_id is resolved at the current (2020) geography. Of the
six ACS vintages we query, only 2021 and 2023 are published on 2020 tracts, so
a tract created in the 2020 redistricting 404s for 2012/2015/2018 — and the
fetch skips the year silently, leaving the Housing chart with two bars.

_fetch_census now resolves the tract that contained the parcel at each year's
geography vintage, so re-running it fills those years in against the ancestor
tract. This script finds the parcels showing that signature and re-runs them.

ACS 2009 (2000 tract geography) stays missing: the geocoder's oldest vintage is
Census2010_Current. Selection deliberately ignores 2009 so healed parcels stop
matching.

Re-runnable: a healed parcel no longer matches the selection.

Usage (API must be running). Locally the dev engine echoes SQL at INFO, so the
per-parcel report is easier to read filtered:
    docker compose exec api python scripts/heal_tract_vintage_gaps.py --dry-run
    docker compose exec api python scripts/heal_tract_vintage_gaps.py
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_script_logging
from app.models.parcels import TimelineRequest
from app.tasks.timeline import _fetch_census

# Years published on 2010 tract geography that per-vintage resolution can heal.
HEALABLE_YEARS = (2012, 2015, 2018)

# Years that only exist on 2020 geography — their presence is what marks a
# parcel as having been fetched at all.
CURRENT_VINTAGE_YEARS = (2021, 2023)

# _fetch_census already sleeps 0.5s between year requests; this is the extra
# pause between parcels to stay under the Census API's per-key rate limit.
DEFAULT_DELAY = 2.0


def _parcels_with_vintage_gaps() -> list[tuple[str, str, float, float, list[int]]]:
    """Return parcels whose pre-2020-geography ACS years are missing.

    Re-runnable as-is: a healed parcel has no missing year left and drops out.
    """
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT p.id, p.census_tract_id, p.latitude, p.longitude, c.year
                FROM parcels p
                JOIN census_snapshots c ON c.parcel_id = p.id AND c.dataset = 'acs5'
                WHERE p.census_tract_id IS NOT NULL
                  AND p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
                ORDER BY p.id
                """
            )
        ).all()

    by_parcel: dict[str, tuple[str, float, float, set[int]]] = {}
    for parcel_id, tract, lat, lon, year in rows:
        entry = by_parcel.setdefault(str(parcel_id), (tract, float(lat), float(lon), set()))
        entry[3].add(year)

    targets = []
    for parcel_id, (tract, lat, lon, years) in by_parcel.items():
        if not years & set(CURRENT_VINTAGE_YEARS):
            continue
        missing = [y for y in HEALABLE_YEARS if y not in years]
        if missing:
            targets.append((parcel_id, tract, lat, lon, missing))
    return sorted(targets)


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


def _tracts_by_year(parcel_id: str) -> list[tuple[str, int, str]]:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT dataset, year, tract_fips FROM census_snapshots "
                "WHERE parcel_id = :pid ORDER BY year"
            ),
            {"pid": parcel_id},
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def _acs_year_count(parcel_id: str) -> int:
    with SessionLocal() as db:
        return int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM census_snapshots "
                    "WHERE parcel_id = :pid AND dataset = 'acs5'"
                ),
                {"pid": parcel_id},
            ).scalar()
            or 0
        )


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(description="Heal census years lost to tract redistricting")
    parser.add_argument(
        "--dry-run", action="store_true", help="List affected parcels without fetching"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help="Seconds to pause between parcels"
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N parcels")
    args = parser.parse_args()

    targets = _parcels_with_vintage_gaps()
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("No parcels show the tract-vintage gap signature.")
        return

    print(f"Found {len(targets)} parcel(s) missing ACS years published on 2010 tract geography.")
    for parcel_id, tract, _, _, missing in targets:
        gaps = ", ".join(str(y) for y in missing)
        print(f"  {parcel_id}  tract {tract}  missing {gaps}")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return

    settings = get_settings()
    healed = 0
    failed = 0

    for i, (parcel_id, tract, lat, lon, _) in enumerate(targets, start=1):
        before = _acs_year_count(parcel_id)
        request_id = _timeline_request_id(parcel_id)
        try:
            asyncio.run(
                _fetch_census(
                    parcel_id,
                    request_id,
                    tract,
                    api_key=settings.census_api_key,
                    latitude=lat,
                    longitude=lon,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad parcel must not end the run
            failed += 1
            print(f"  [{i}/{len(targets)}] {parcel_id} FAILED: {exc}")
        else:
            healed += 1
            added = _acs_year_count(parcel_id) - before
            tracts = _tracts_by_year(parcel_id)
            distinct = sorted({t for _, _, t in tracts})
            print(f"  [{i}/{len(targets)}] {parcel_id}: +{added} ACS year(s)")
            print(f"      tracts used: {', '.join(distinct)}")
            for dataset, year, row_tract in tracts:
                print(f"      {year} {dataset:<9} {row_tract}")

        if i < len(targets):
            asyncio.run(asyncio.sleep(args.delay))

    print(f"\nRefetched {healed} parcel(s), {failed} failed.")


if __name__ == "__main__":
    main()
