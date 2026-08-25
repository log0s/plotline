#!/usr/bin/env python3
"""Delete named imagery_snapshots rows whose imagery does not cover the parcel.

The NAIP path selects tiles by how much of the *viewport* they cover, so a
year with no covering tile in the collection is served as the nearest
neighbours: the 2026-08 geometry audit found both 350 5th Ave parcels
serving a 2023 mosaic made entirely of New Jersey quads for a Midtown
Manhattan address. 14b59af closes that going forward — it drops an
uncovered year from the selection — but the gate is prospective only.
``reconcile_source_snapshots`` deliberately never deletes an *absent*
group, because absence usually means a failed search rather than a retired
scene, so a re-run cannot clear a wrong card that already exists. Those
rows have to be deleted directly, and this is the tool that does it.

It is deliberately narrow. There is no pattern matching, no "all parcels"
mode and no source-wide mode: it condemns rows named on the command line,
and only after live evidence that they are wrong. Dry run is the default;
``--execute`` additionally requires that every tile in each target row's
mosaic be fetched from Planetary Computer and shown *not* to contain the
parcel point. Anything unresolvable — a tile URL that does not map to an
item id, an item PC will not serve — refuses the whole run rather than
deleting on partial evidence.

Usage (API must be running; --parcel-id/--source/--year pair up in order):

    docker compose exec api python scripts/remove_uncovered_snapshots.py \\
        --parcel-id 81b2d663-1851-438d-a9fa-58d665e32e25 --source naip --year 2023 \\
        --parcel-id d2a82e6b-f55c-475d-996f-714b28522b77 --source naip --year 2023

    ... same command with --execute to delete.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging_config import configure_script_logging
from app.services import stac as stac_service

logger = logging.getLogger("remove_uncovered_snapshots")


class EvidenceError(Exception):
    """The condemnation could not be proved, so nothing may be deleted."""


@dataclass(frozen=True)
class Target:
    parcel_id: str
    source: str
    year: int


@dataclass
class Row:
    id: str
    parcel_id: str
    address: str
    latitude: float
    longitude: float
    source: str
    year: int
    capture_date: str
    stac_item_id: str
    stac_collection: str
    cog_url: str
    additional_cog_urls: list[str]


# ── Row lookup ────────────────────────────────────────────────────────────────


def _extra_urls(value: Any) -> list[str]:
    """Normalise ``additional_cog_urls`` across Postgres text[] and SQLite text."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return [part.strip().strip('"') for part in raw.split(",") if part.strip()]


def find_target_rows(db: Session, target: Target) -> list[Row]:
    """Rows for one (parcel, source, year), newest capture first."""
    rows = db.execute(
        text(
            "SELECT i.id, i.parcel_id, i.source, i.capture_date, i.stac_item_id,"
            " i.stac_collection, i.cog_url, i.additional_cog_urls, i.created_at,"
            " p.address, p.latitude, p.longitude"
            " FROM imagery_snapshots i JOIN parcels p ON p.id = i.parcel_id"
            " WHERE i.parcel_id = :parcel_id AND i.source = :source"
            " AND i.capture_date >= :start AND i.capture_date < :end"
            " ORDER BY i.capture_date DESC"
        ),
        {
            "parcel_id": target.parcel_id,
            "source": target.source,
            "start": f"{target.year}-01-01",
            "end": f"{target.year + 1}-01-01",
        },
    ).all()

    found = []
    for row in rows:
        found.append(
            Row(
                id=str(row.id),
                parcel_id=str(row.parcel_id),
                address=row.address,
                latitude=float(row.latitude),
                longitude=float(row.longitude),
                source=row.source,
                year=target.year,
                capture_date=str(row.capture_date),
                stac_item_id=row.stac_item_id,
                stac_collection=row.stac_collection,
                cog_url=row.cog_url,
                additional_cog_urls=_extra_urls(row.additional_cog_urls),
            )
        )
        print(
            f"  {row.id}  {target.source} {target.year}"
            f"  capture_date={row.capture_date}"
            f"  stac_item_id={row.stac_item_id}"
            f"  created_at={row.created_at}"
        )
        for url in _extra_urls(row.additional_cog_urls):
            print(f"      + mosaic tile {url}")
    return found


# ── Evidence: every tile in the row's mosaic must exclude the parcel point ────


def naip_item_id_from_url(url: str) -> str:
    """Recover a NAIP STAC item id from its blob URL.

    NAIP item ids are the file stem prefixed with the state:
    ``.../naip/v002/nj/2023/nj_030cm_2023/40074/m_4007424_ne_18_030_….tif``
    is ``nj_m_4007424_ne_18_030_…``. The derivation is checked against the
    row's own ``stac_item_id`` before it is trusted for the extra tiles.
    """
    path = PurePosixPath(urlparse(url).path)
    parts = path.parts
    if "v002" not in parts:
        raise EvidenceError(f"cannot derive a STAC item id from {url}")
    state = parts[parts.index("v002") + 1] if len(parts) > parts.index("v002") + 1 else ""
    stem = path.name.removesuffix(".tif")
    if not state or not stem:
        raise EvidenceError(f"cannot derive a STAC item id from {url}")
    return f"{state}_{stem}"


def mosaic_item_ids(row: Row) -> list[str]:
    """Every STAC item this row serves — the primary plus its mosaic tiles."""
    if not row.additional_cog_urls:
        return [row.stac_item_id]
    if row.source != "naip":
        raise EvidenceError(
            f"{row.id}: {row.source} row carries mosaic tiles; only NAIP tile URLs"
            " can be mapped back to item ids"
        )
    derived_primary = naip_item_id_from_url(row.cog_url)
    if derived_primary != row.stac_item_id:
        raise EvidenceError(
            f"{row.id}: URL-to-item-id derivation is unreliable here"
            f" ({derived_primary!r} != {row.stac_item_id!r})"
        )
    return [row.stac_item_id] + [naip_item_id_from_url(u) for u in row.additional_cog_urls]


async def fetch_stac_item(collection: str, item_id: str) -> dict[str, object]:
    """Read-only GET of a single STAC item from Planetary Computer."""
    url = f"{stac_service.STAC_API}/collections/{collection}/items/{item_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise EvidenceError(f"PC returned {resp.status_code} for {item_id}; cannot verify")
    item = resp.json()
    if not isinstance(item, dict) or not item.get("geometry"):
        raise EvidenceError(f"{item_id} has no geometry; cannot verify")
    return item


async def verify_uncovered(row: Row) -> str:
    """Confirm no tile this row serves contains the parcel point.

    Returns the reason string recorded with the deletion. Raises
    ``EvidenceError`` if a tile covers the point, or if any tile cannot be
    checked at all — an unverifiable row is never deleted.
    """
    item_ids = mosaic_item_ids(row)
    covering = []
    for item_id in item_ids:
        item = await fetch_stac_item(row.stac_collection, item_id)
        if stac_service.filter_items_containing_point([item], row.latitude, row.longitude):
            covering.append(item_id)

    if covering:
        raise EvidenceError(
            f"{row.id}: {', '.join(covering)} contains the parcel point"
            f" ({row.latitude}, {row.longitude}) — this row is not condemnable"
        )

    return (
        f"no tile of the {row.source} {row.year} mosaic contains the parcel point"
        f" ({row.latitude}, {row.longitude}); checked {', '.join(item_ids)}"
    )


# ── Deletion ──────────────────────────────────────────────────────────────────


def delete_rows(db: Session, condemned: list[tuple[Row, str]]) -> int:
    """Delete every condemned row in one transaction, logging each."""
    for row, reason in condemned:
        db.execute(
            text("DELETE FROM imagery_snapshots WHERE id = :id"),
            {"id": row.id},
        )
        logger.info(
            "Deleted uncovered imagery snapshot",
            extra={
                "snapshot_id": row.id,
                "parcel_id": row.parcel_id,
                "source": row.source,
                "year": row.year,
                "stac_item_id": row.stac_item_id,
                "reason": reason,
            },
        )
        print(
            f"  deleted {row.id}  parcel={row.parcel_id}  {row.source} {row.year}"
            f"  {row.stac_item_id}\n      reason: {reason}"
        )
    db.commit()
    return len(condemned)


# ── Entry point ───────────────────────────────────────────────────────────────


def parse_targets(args: argparse.Namespace) -> list[Target]:
    parcels = args.parcel_id or []
    sources = args.source or []
    years = args.year or []
    if not parcels or not sources or not years:
        raise SystemExit(
            "--parcel-id, --source and --year are all required:"
            " this tool only condemns rows named explicitly."
        )
    if not len(parcels) == len(sources) == len(years):
        raise SystemExit(
            f"--parcel-id ({len(parcels)}), --source ({len(sources)}) and"
            f" --year ({len(years)}) must be given the same number of times;"
            " they pair up in the order they appear."
        )
    return [Target(p, s, y) for p, s, y in zip(parcels, sources, years, strict=True)]


def run(db: Session, targets: list[Target], *, execute: bool) -> int:
    print(f"Targets ({len(targets)}):")
    rows: list[Row] = []
    for target in targets:
        print(f"\n{target.parcel_id}  {target.source}  {target.year}")
        found = find_target_rows(db, target)
        if not found:
            print("  (no rows)")
        rows.extend(found)

    if not rows:
        print("\nNothing matched. Nothing to delete.")
        return 0

    if not execute:
        print(f"\nDry run — {len(rows)} row(s) would be deleted. Nothing written.")
        return 0

    print("\nVerifying against live STAC footprints…")
    condemned: list[tuple[Row, str]] = []
    for row in rows:
        reason = asyncio.run(verify_uncovered(row))
        print(f"  {row.id}: {reason}")
        condemned.append((row, reason))

    print(f"\nDeleting {len(condemned)} row(s):")
    return delete_rows(db, condemned)


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(
        description="Delete named imagery snapshots whose imagery excludes the parcel"
    )
    parser.add_argument("--parcel-id", action="append", help="Parcel UUID (repeatable)")
    parser.add_argument("--source", action="append", help="Imagery source (repeatable)")
    parser.add_argument("--year", action="append", type=int, help="Capture year (repeatable)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete, after live footprint evidence. Without it this is a dry run.",
    )
    args = parser.parse_args()
    targets = parse_targets(args)

    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            deleted = run(db, targets, execute=args.execute)
        except EvidenceError as exc:
            print(f"\nREFUSED: {exc}", file=sys.stderr)
            print("Nothing was deleted.", file=sys.stderr)
            raise SystemExit(2) from exc

    if args.execute:
        print(f"\nDone — {deleted} row(s) deleted.")


if __name__ == "__main__":
    main()
