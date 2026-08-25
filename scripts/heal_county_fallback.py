#!/usr/bin/env python3
"""Null out county values that are really census tract names.

Before the fallback was removed from geocoder.py, a parcel whose geocode
response carried no Counties layer got the tract's NAME as its county —
"Census Tract 62.02". That value is truthy, so parcels.py's only-if-empty
backfill never replaced it and get_adapter_for_county never matched it:
the parcel's property history was permanently and silently empty.

Setting it to NULL restores both paths. The next reverse-geocode backfill
fills in the real county if one is available.

Usage (API must be running):
    docker compose exec api python scripts/heal_county_fallback.py --dry-run
    docker compose exec api python scripts/heal_county_fallback.py
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from app.db import SessionLocal
from app.logging_config import configure_script_logging

_MATCH = "Census Tract%"


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(description="Null out tract-name county values")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report affected parcels without writing",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT id, address, county FROM parcels"
                " WHERE county LIKE :match ORDER BY created_at"
            ),
            {"match": _MATCH},
        ).all()

        if not rows:
            print("No parcels carry a tract-name county. Nothing to heal.")
            return

        print(f"Found {len(rows)} parcel(s) with a tract-name county:")
        for row in rows:
            print(f"  {row.id}  {row.county!r}  {row.address}")

        if args.dry_run:
            print("\nDry run — nothing written.")
            return

        result = db.execute(
            text("UPDATE parcels SET county = NULL WHERE county LIKE :match"),
            {"match": _MATCH},
        )
        db.commit()
        print(f"\nDone — cleared county on {result.rowcount} parcel(s).")


if __name__ == "__main__":
    main()
