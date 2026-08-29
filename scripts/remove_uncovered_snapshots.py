#!/usr/bin/env python3
"""Delete named served rows whose imagery does not cover the parcel.

Reads ``parcel_scenes`` joined to ``scenes`` and deletes the ``parcel_scenes``
row; the ``scenes`` rows are left alone, because a scene that does not cover
*this* parcel is a perfectly good catalogued item that other parcels may
legitimately serve — the wrong thing is the selection, not the item. ADR 0001
step 4 moved this off the denormalized table it was written against; the
condemnation rule and the evidence standard below are unchanged.

**A cheaper evidence path now exists and this script deliberately does not
take it.** ``scenes.footprint`` holds real item geometry for every row written
since step 2 and for the enriched backfill, so ``ST_Contains(footprint,
point)`` could condemn a row without a network call. That is a different tool
with a different failure mode — it trusts stored geometry, where this one
re-derives the answer from Planetary Computer — and swapping the evidence
standard inside a deletion tool is not a migration. Recorded as a follow-up in
STATUS.md rather than built here.

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
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging_config import configure_script_logging
from app.services import stac as stac_service
from app.services.imagery import decode_mosaic_scene_ids

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


def _mosaic_urls(db: Session, mosaic_scene_ids: object) -> list[str]:
    """The ``cog_url`` of each additional tile, in ``mosaic_scene_ids`` order.

    The normalized shape stores references where the old one stored a URL
    array, so the array this script condemns against is reconstructed the same
    way the serving read reconstructs it (``imagery._mosaic_cog_urls``): one
    query, then ordered in Python. Order matters here only for the printed
    dry-run output, but a reference that resolves to no row is a **refusal**
    rather than a dropped entry — the serving path can render a mosaic with a
    tile missing, and a deletion tool cannot condemn one on partial evidence.
    """
    ids = decode_mosaic_scene_ids(mosaic_scene_ids)
    if not ids:
        return []
    placeholders = ",".join(f":s{i}" for i in range(len(ids)))
    params = {f"s{i}": sid for i, sid in enumerate(ids)}
    by_id = {
        str(sid): url
        for sid, url in db.execute(
            text(f"SELECT id, cog_url FROM scenes WHERE id IN ({placeholders})"),  # noqa: S608
            params,
        ).all()
    }
    missing = [sid for sid in ids if sid not in by_id]
    if missing:
        raise EvidenceError(f"mosaic references resolve to no scenes row: {', '.join(missing)}")
    return [by_id[sid] for sid in ids]


def find_target_rows(db: Session, target: Target) -> list[Row]:
    """Rows for one (parcel, source, year), newest capture first."""
    rows = db.execute(
        text(
            "SELECT ps.id, ps.parcel_id, ps.source, ps.group_key, ps.selected_at,"
            " ps.mosaic_scene_ids, s.capture_date, s.item_id, s.collection, s.cog_url,"
            " p.address, p.latitude, p.longitude"
            " FROM parcel_scenes ps"
            " JOIN scenes s ON s.id = ps.scene_id"
            " JOIN parcels p ON p.id = ps.parcel_id"
            " WHERE ps.parcel_id = :parcel_id AND ps.source = :source"
            " AND s.capture_date >= :start AND s.capture_date < :end"
            " ORDER BY s.capture_date DESC"
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
        mosaic = _mosaic_urls(db, row.mosaic_scene_ids)
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
                stac_item_id=row.item_id,
                stac_collection=row.collection,
                cog_url=row.cog_url,
                additional_cog_urls=mosaic,
            )
        )
        print(
            f"  {row.id}  {target.source} {target.year}"
            f"  capture_date={row.capture_date}"
            f"  group_key={row.group_key}"
            f"  stac_item_id={row.item_id}"
            f"  selected_at={row.selected_at}"
        )
        for url in mosaic:
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
    """Delete every condemned row in one transaction, logging each.

    Deletes the ``parcel_scenes`` row only. Its ``scenes`` row stays: the item
    is catalogued and may be legitimately served elsewhere, and orphaning
    ``scenes`` rows on a per-parcel deletion is how the one-row-per-item
    promise gets quietly broken.
    """
    for row, reason in condemned:
        db.execute(
            text("DELETE FROM parcel_scenes WHERE id = :id"),
            {"id": row.id},
        )
        logger.info(
            "Deleted uncovered served scene",
            extra={
                "parcel_scene_id": row.id,
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
