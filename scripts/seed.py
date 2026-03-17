#!/usr/bin/env python3
"""Seed script — inserts a handful of well-known addresses via the geocode API.

Usage (via Makefile):
    make seed

Usage (direct, API must be running):
    python scripts/seed.py [--api-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

SEED_ADDRESSES = [
    "1600 Pennsylvania Ave NW, Washington, DC 20500",
    "1437 Bannock St, Denver, CO 80202",
    "350 5th Ave, New York, NY 10118",
    "233 S Wacker Dr, Chicago, IL 60606",
    "1 Infinite Loop, Cupertino, CA 95014",
]


def geocode(api_url: str, address: str) -> dict:  # type: ignore[type-arg]
    """POST to /api/v1/geocode and return the response JSON."""
    url = f"{api_url}/api/v1/geocode"
    payload = json.dumps({"address": address}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Plotline with example parcels")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the Plotline API (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    print(f"Seeding {len(SEED_ADDRESSES)} addresses to {args.api_url}...\n")
    success = 0
    skipped = 0
    failed = 0

    for address in SEED_ADDRESSES:
        try:
            result = geocode(args.api_url, address)
            status = "NEW " if result.get("is_new") else "DUP "
            lat = result.get("latitude", "?")
            lng = result.get("longitude", "?")
            parcel_id = result.get("parcel_id", "?")
            print(f"  [{status}] {address}")
            print(f"         lat={lat:.5f}, lng={lng:.5f}, id={parcel_id}")
            if result.get("is_new"):
                success += 1
            else:
                skipped += 1
            # Avoid hammering the Census Geocoder
            time.sleep(0.5)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  [FAIL] {address}")
            print(f"         HTTP {e.code}: {body[:120]}")
            failed += 1
        except Exception as e:
            print(f"  [ERR ] {address}")
            print(f"         {e}")
            failed += 1

    print(f"\nDone: {success} inserted, {skipped} already existed, {failed} failed.")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
