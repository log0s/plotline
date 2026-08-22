#!/usr/bin/env python3
"""Audit — and only with evidence, delete — parcels created on the reverse path.

Until 2026-08-22 (security audit SEC-2/SEC-5) ``POST /geocode`` accepted any
``lat``/``lon`` from the client: an unmatchable address string plus arbitrary
coordinates created a parcel anywhere and ran the full pipeline. The fix is
prospective — it refuses coordinates the backend did not itself serve — and
cannot clear rows that already exist. This is the tool for those rows.

The reverse path's signature is ``normalized_address = address`` (the
forward path stores Census's matchedAddress, which is upper-cased and never
equals the submitted text). Production held 71 such rows on 2026-08-22, all
inside CONUS and all with a census tract — indistinguishable, from the
database alone, from a legitimate autocomplete fallback. So the evidence
has to come from the geocoder the coordinates were supposed to come from:
Photon is asked for the stored address, and a row is condemned only when
*no* suggestion lands within ``--radius-m`` (default 250 m) of the stored
point. A query that fails, or returns nothing at all, is *inconclusive*,
and an inconclusive row refuses ``--execute`` for the whole run rather
than deleting on partial evidence.

Dry run (default) lists the candidates without touching Photon. ``--verify``
asks Photon (one query per row, 1 s apart). ``--execute`` additionally
deletes the condemned rows — parcels cascade to their requests, snapshots,
census rows and events — and only when every candidate was conclusive.

    docker compose exec api python scripts/remove_unverified_reverse_parcels.py
    docker compose exec api python scripts/remove_unverified_reverse_parcels.py --verify
    docker compose exec api python scripts/remove_unverified_reverse_parcels.py --verify --execute
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("remove_unverified_reverse_parcels")

PHOTON_URL = "https://photon.komoot.io/api"
# Continental US, as api/geocode.py's autocomplete bbox.
_US_BBOX = "-125.0,24.0,-66.0,50.0"


class EvidenceError(Exception):
    """The condemnation could not be proved, so nothing may be deleted."""


@dataclass
class Candidate:
    id: str
    address: str
    latitude: float
    longitude: float
    created_at: str
    nearest_m: float | None = None  # None = inconclusive (no result / query failed)
    condemned: bool = False
    note: str = ""


RADIUS_M = 250.0


def find_candidates(db: Session) -> list[Candidate]:
    rows = db.execute(
        text(
            "SELECT id, address, latitude, longitude, created_at FROM parcels"
            " WHERE normalized_address = address ORDER BY created_at"
        )
    ).all()
    return [
        Candidate(str(r.id), r.address, float(r.latitude), float(r.longitude), str(r.created_at))
        for r in rows
    ]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(a))


def photon_points(client: httpx.Client, address: str) -> list[tuple[float, float]]:
    """(lat, lon) of every US suggestion Photon returns for ``address``."""
    resp = client.get(
        PHOTON_URL, params={"q": address, "bbox": _US_BBOX, "limit": 10, "lang": "en"}
    )
    resp.raise_for_status()
    points = []
    for feature in resp.json().get("features", []):
        if feature.get("properties", {}).get("countrycode", "").upper() != "US":
            continue
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            points.append((float(coords[1]), float(coords[0])))
    return points


def assess(
    candidate: Candidate, points: list[tuple[float, float]] | None, radius_m: float = RADIUS_M
) -> Candidate:
    """Attach the nearest-suggestion distance; None points = inconclusive."""
    if not points:
        candidate.nearest_m = None
        candidate.note = (
            "inconclusive: no suggestion" if points == [] else "inconclusive: query failed"
        )
        return candidate
    candidate.nearest_m = min(
        haversine_m(candidate.latitude, candidate.longitude, lat, lon) for lat, lon in points
    )
    candidate.condemned = candidate.nearest_m > radius_m
    candidate.note = "condemned" if candidate.condemned else "matches a suggestion"
    return candidate


def verify(
    candidates: list[Candidate], radius_m: float = RADIUS_M, pause_s: float = 1.0
) -> list[Candidate]:
    with httpx.Client(timeout=10, headers={"User-Agent": "Plotline/1.0 (reverse-path audit)"}) as c:
        for i, cand in enumerate(candidates):
            try:
                points: list[tuple[float, float]] | None = photon_points(c, cand.address)
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                logger.warning("Photon query failed for %s: %s", cand.id, type(exc).__name__)
                points = None
            assess(cand, points, radius_m)
            if i < len(candidates) - 1:
                time.sleep(pause_s)
    return candidates


def run(db: Session, *, do_verify: bool, execute: bool, radius_m: float = RADIUS_M) -> int:
    candidates = find_candidates(db)
    print(f"{len(candidates)} candidate(s) with normalized_address = address")
    if do_verify:
        verify(candidates, radius_m)
    for c in candidates:
        dist = "-" if c.nearest_m is None else f"{c.nearest_m:.0f} m"
        print(
            f"  {c.id}  ({c.latitude:.5f}, {c.longitude:.5f})  {dist:>8}  {c.note:<28} {c.address!r}"
        )

    if not execute:
        print(
            "\nDry run — nothing deleted." + ("" if do_verify else " Add --verify to ask Photon.")
        )
        return 0
    if not do_verify:
        raise EvidenceError("--execute requires --verify")
    inconclusive = [c for c in candidates if c.nearest_m is None]
    if inconclusive:
        raise EvidenceError(
            f"{len(inconclusive)} candidate(s) inconclusive; refusing to delete any"
        )

    condemned = [c for c in candidates if c.condemned]
    for c in condemned:
        db.execute(text("DELETE FROM parcels WHERE id = :id"), {"id": c.id})
        logger.info("Deleted parcel %s (%s)", c.id, c.address)
    db.commit()
    return len(condemned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verify", action="store_true", help="Ask Photon about each candidate")
    parser.add_argument("--radius-m", type=float, default=RADIUS_M)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete condemned rows (requires --verify and every candidate conclusive)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            deleted = run(db, do_verify=args.verify, execute=args.execute, radius_m=args.radius_m)
        except EvidenceError as exc:
            print(f"\nREFUSED: {exc}", file=sys.stderr)
            print("Nothing was deleted.", file=sys.stderr)
            raise SystemExit(2) from exc
    if args.execute:
        print(f"\nDone — {deleted} row(s) deleted.")


if __name__ == "__main__":
    main()
