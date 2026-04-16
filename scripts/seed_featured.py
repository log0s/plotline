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
        "subtitle": "Denver's closed airport became the largest urban redevelopment in US history",
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
        "subtitle": "An industrial corridor transformed into Denver's trendiest neighborhood",
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
        "address": "4800 Telluride St, Denver, CO 80249",
        "name": "Green Valley Ranch",
        "subtitle": "Open prairie east of Denver exploded into a planned community in 15 years",
        "slug": "green-valley-ranch",
        "key_stat": "Population grew thousands of percent since 2000",
        "description": (
            "The area east of Denver near E-470 was open prairie and farmland in the "
            "early 2000s. NAIP imagery shows the rapid development of subdivisions, "
            "schools, and commercial centers that now house tens of thousands."
        ),
        "display_order": 3,
    },
    {
        "address": "9311 S Cimarron Rd, Las Vegas, NV 89178",
        "name": "Southern Highlands, Las Vegas",
        "subtitle": "Empty Mojave desert became one of America's fastest-growing suburbs",
        "slug": "southern-highlands",
        "key_stat": "Open desert in 1996, 50,000+ residents by 2010",
        "description": (
            "The southwest fringe of Las Vegas near Southern Highlands was empty "
            "Mojave desert through the 1980s and 1990s. Landsat shows bare sand; "
            "by the mid-2000s NAIP reveals a grid of rooftops, golf courses, and "
            "arterial roads spreading into the valley."
        ),
        "display_order": 4,
    },
    {
        "address": "24241 Atlantic Dr, Rodanthe, NC 27968",
        "name": "Rodanthe, Outer Banks",
        "subtitle": "Decades of coastal erosion reshaped the Outer Banks barrier islands",
        "slug": "rodanthe-outer-banks",
        "key_stat": "Shoreline retreated over 200 ft since 1984",
        "description": (
            "Rodanthe sits on one of the narrowest stretches of the Outer Banks. "
            "Comparing Landsat imagery from the 1980s to recent NAIP shows the "
            "shoreline migrating westward, houses lost to the surf, and NC-12 "
            "repeatedly relocated as the barrier island rolls over itself."
        ),
        "display_order": 5,
    },
    {
        "address": "500 W 33rd St, New York, NY 10001",
        "name": "Hudson Yards",
        "subtitle": "Midtown Manhattan rail yards became the most expensive development in US history",
        "slug": "hudson-yards",
        "key_stat": "TBD — recompute after pipeline run",
        "description": (
            "The Hudson Yards site on Manhattan's far west side spent decades as "
            "an open rail yard serving Penn Station. Landsat imagery from the 1990s "
            "shows bare tracks; by the 2010s, a platform deck was constructed over "
            "the active rails and a cluster of supertall towers rose above it in "
            "the largest private real-estate development in US history."
        ),
        "display_order": 6,
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

    # Step 4: Prune featured rows whose slug is no longer in the seed list.
    from app.db import SessionLocal
    from app.models.parcels import FeaturedLocation as FeaturedLocationModel
    from sqlalchemy import select

    expected_slugs = {loc["slug"] for loc in FEATURED_LOCATIONS}
    db = SessionLocal()
    try:
        stale = db.scalars(
            select(FeaturedLocationModel).where(
                FeaturedLocationModel.slug.notin_(expected_slugs)
            )
        ).all()
        for row in stale:
            print(f"  Pruning stale featured: {row.slug!r} ({row.name!r})")
            db.delete(row)
        if stale:
            db.commit()
    finally:
        db.close()

    # Step 5: Render static preview images for all featured locations
    print(f"\n{'='*60}")
    print("Rendering static preview images (latest NAIP)...")
    print(f"{'='*60}")
    _render_featured_previews()

    print(f"\n{'='*60}")
    print("Featured location seeding complete!")
    print(f"{'='*60}")


def _render_featured_previews() -> None:
    """Render a static JPEG preview per featured location from latest NAIP."""
    import asyncio

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models.parcels import FeaturedLocation as FL
    from app.services.preview_renderer import render_preview
    from sqlalchemy import select

    settings = get_settings()

    async def _run() -> None:
        db = SessionLocal()
        try:
            locations = db.scalars(select(FL).order_by(FL.display_order)).all()
            for loc in locations:
                try:
                    rel_url = await render_preview(db, loc, settings)
                except Exception as exc:
                    print(f"  {loc.name}: FAILED ({exc})")
                    continue
                if rel_url is None:
                    print(f"  {loc.name}: no NAIP snapshot, skipping")
                    continue
                loc.preview_image_url = rel_url
                db.commit()
                print(f"  {loc.name}: {rel_url}")
        finally:
            db.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
