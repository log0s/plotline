#!/usr/bin/env python3
"""Seed featured locations for the Plotline landing page.

This script:
1. Geocodes each featured address via the API
2. Waits for the timeline to complete
3. Creates a FeaturedLocation record linking to the parcel

Usage:
    python scripts/seed_featured.py [--api-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

FEATURED_LOCATIONS = [
    {
        "address": "8340 Northfield Blvd, Denver, CO 80238",
        "name": "Stapleton / Central Park",
        "subtitle": "Airport to neighborhood — the largest urban redevelopment in US history",
        "slug": "stapleton-central-park",
        "key_stat": "Former airport site, 4,700-acre master-planned community",
        "description": (
            "Denver's Stapleton International Airport closed in 1995 and was replaced "
            "by one of the most ambitious urban redevelopment projects in the country. "
            "NAIP imagery from 2003 shows demolition; by 2023, it's a dense neighborhood."
        ),
        "display_order": 1,
    },
    {
        "address": "2901 Blake St, Denver, CO 80205",
        "name": "RiNo Art District",
        "subtitle": "Industrial warehouses to breweries and condos in under a decade",
        "slug": "rino-art-district",
        "key_stat": "Denver's fastest-appreciating neighborhood, 2014-2020",
        "description": (
            "River North was an industrial corridor of rail yards and warehouses. "
            "Starting around 2014, it transformed into Denver's trendiest neighborhood "
            "with art galleries, breweries, and new construction."
        ),
        "display_order": 2,
    },
    {
        "address": "4900 E 48th Ave, Denver, CO 80216",
        "name": "Green Valley Ranch",
        "subtitle": "Prairie to planned community in 15 years of explosive growth",
        "slug": "green-valley-ranch",
        "key_stat": "Population grew thousands of percent since 2000",
        "description": (
            "The area east of Denver near E-470 was open prairie and farmland in the "
            "early 2000s. NAIP imagery shows the rapid development of subdivisions, "
            "schools, and commercial centers that now house tens of thousands."
        ),
        "display_order": 3,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed featured locations")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the Plotline API",
    )
    args = parser.parse_args()
    api = args.api_url.rstrip("/")

    client = httpx.Client(timeout=60.0)

    for loc in FEATURED_LOCATIONS:
        print(f"\n{'='*60}")
        print(f"Seeding: {loc['name']} ({loc['address']})")
        print(f"{'='*60}")

        # Step 1: Geocode
        print("  Geocoding...", end=" ", flush=True)
        resp = client.post(f"{api}/api/v1/geocode", json={"address": loc["address"]})
        if resp.status_code not in (200, 201):
            print(f"FAILED ({resp.status_code}): {resp.text}")
            continue
        geocode_data = resp.json()
        parcel_id = geocode_data["parcel_id"]
        timeline_request_id = geocode_data.get("timeline_request_id")
        print(f"OK (parcel_id={parcel_id})")

        # Step 2: Wait for timeline (if new)
        if timeline_request_id and geocode_data.get("is_new", False):
            print("  Waiting for timeline...", end=" ", flush=True)
            for attempt in range(120):  # max ~4 minutes
                resp = client.get(f"{api}/api/v1/timeline-requests/{timeline_request_id}")
                if resp.status_code != 200:
                    break
                status = resp.json().get("status", "unknown")
                if status in ("complete", "failed"):
                    print(f"{status.upper()}")
                    break
                time.sleep(2)
            else:
                print("TIMEOUT")
        else:
            print("  Timeline already exists, skipping wait.")

        # Step 3: Create featured location record
        print("  Creating featured record...", end=" ", flush=True)
        # Use direct DB insert via a small helper endpoint isn't available,
        # so we'll use the DB directly
        try:
            from app.db import SessionLocal
            from app.models.parcels import FeaturedLocation as FeaturedLocationModel
            from sqlalchemy import select

            db = SessionLocal()
            try:
                # Check if already exists
                existing = db.scalars(
                    select(FeaturedLocationModel).where(
                        FeaturedLocationModel.slug == loc["slug"]
                    )
                ).first()
                if existing:
                    print("ALREADY EXISTS, updating...")
                    existing.parcel_id = parcel_id  # type: ignore[assignment]
                    existing.name = loc["name"]
                    existing.subtitle = loc["subtitle"]
                    existing.key_stat = loc["key_stat"]
                    existing.description = loc["description"]
                    existing.display_order = loc["display_order"]
                    db.commit()
                else:
                    featured = FeaturedLocationModel(
                        parcel_id=parcel_id,
                        name=loc["name"],
                        subtitle=loc["subtitle"],
                        slug=loc["slug"],
                        key_stat=loc["key_stat"],
                        description=loc["description"],
                        display_order=loc["display_order"],
                    )
                    db.add(featured)
                    db.commit()
                    print("OK")
            finally:
                db.close()
        except Exception as exc:
            print(f"FAILED: {exc}")
            continue

    print(f"\n{'='*60}")
    print("Featured location seeding complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
