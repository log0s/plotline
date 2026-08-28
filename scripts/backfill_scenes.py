#!/usr/bin/env python3
"""Fill ``scenes`` and ``parcel_scenes`` from ``imagery_snapshots``.

Step 1 of docs/adr/0001-imagery-normalization.md, data half; migration 0015
is the DDL half. Additive and read-only with respect to the old table:
nothing here writes to, deletes from, or alters ``imagery_snapshots``, and no
read path has been cut over yet (step 3 owns that).

Three phases:

* **A — scenes from snapshots.** One row per distinct
  ``(stac_collection, stac_item_id)``. ``footprint`` stays NULL because
  ``imagery_snapshots`` never held item geometry; that is the gap the
  2026-08 geometry audit closed by refetching 1,239 STAC items, and it is
  not closable from the table alone. Where several snapshot rows carry the
  same item and disagree about its attributes — the denormalization cost the
  ADR exists to remove — the newest row wins and the disagreement is
  reported, never silently collapsed.

* **B — scenes synthesized from mosaic URLs.** A NAIP mosaic's additional
  tiles were only ever stored as URLs in ``additional_cog_urls``, and most of
  them were never persisted as a snapshot row of their own. ADR rule 5 makes
  every tile a first-class scene, so each unmatched URL becomes a row parsed
  out of the URL itself. No network calls: a URL that will not parse, or that
  is not a NAIP tile URL, aborts the run rather than being skipped.

  **These rows' ``item_id`` is a candidate, not a catalogued id.** The ADR
  assumed a NAIP filename *is* the STAC item id. It usually is not: the id
  normally carries a trailing publication date the filename omits, and some
  pairs spell the resolution differently (``_.6_`` in the id, ``_h_`` in the
  filename). ``provenance = 'mosaic_url'`` marks every such row so a later
  STAC pass can enumerate and correct them, and so nothing downstream mistakes
  a parsed string for a catalogued one.

* **C — parcel_scenes.** One row per ``imagery_snapshots`` row.
  ``group_key`` comes from ``encode_group_key``, the same encoder the M4
  ledger and the reconciler use — not a new encoding. ``selected_by`` is NULL
  for every backfilled row: the SHA of the selector that chose it was never
  recorded, and inventing one would make an unattributed selection look
  attributed.

Idempotent. Nothing is updated, only inserted, so a second run inserts
nothing and reports the fact. If a *changed* row is found — an existing
``parcel_scenes`` row pointing at a different scene than the snapshots now
imply — it is reported as drift and left alone; reconciling it is a
dual-write question (step 2), not a backfill one.

Refusals, all before any write:

* any duplicate ``(parcel_id, source, group_key)`` group — the ADR's change
  condition: more duplicates than expected means reconciliation has been
  failing silently, and step 2 must not be built on top of it;
* any mosaic URL that is not a parseable NAIP tile URL;
* any snapshot row whose source has no configured selection scope.

Usage (dry run is the default and writes nothing):

    docker compose exec api python scripts/backfill_scenes.py
    docker compose exec api python scripts/backfill_scenes.py --execute
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging_config import configure_script_logging
from app.services.imagery import encode_group_key

# The scope map is read from the fetch configuration rather than restated, so
# a source that changes its grouping cannot leave this script bucketing by the
# old rule. usgs_topo has no entry in _SOURCES — its decade scope is passed
# literally at app/tasks/timeline.py:961 — so it is added the same way.
from app.tasks.timeline import _SOURCES as _TIMELINE_SOURCES

logger = logging.getLogger("backfill_scenes")

SELECTION_SCOPE_BY_SOURCE: dict[str, str] = {
    str(cfg["source"]): str(cfg["selection_scope"]) for cfg in _TIMELINE_SOURCES
}
SELECTION_SCOPE_BY_SOURCE["usgs_topo"] = "decade"

# Platform prefixes that name a satellite unambiguously. Anything else is
# NULL — a platform column that guesses is worse than one that is empty.
# LT04 and S2C are here because both appear in real rows; the ADR's list
# predates Sentinel-2C's 2024 launch.
_LANDSAT_PLATFORMS = frozenset({"LT04", "LT05", "LE07", "LC08", "LC09"})
_SENTINEL_PLATFORMS = frozenset({"S2A", "S2B", "S2C"})

# NAIP filename stems end in the capture date, optionally followed by the
# publication date: ``m_4007424_ne_18_030_20230920`` or
# ``…_20230711_20231127``. The first of the two is the capture.
_NAIP_DATE_SUFFIX = re.compile(r"_(\d{8})(?:_\d{8})?$")


class BackfillError(Exception):
    """A refusal. Nothing has been written when this is raised."""


# ── Reading imagery_snapshots ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Snapshot:
    id: str
    parcel_id: str
    source: str
    capture_date: date
    stac_item_id: str
    stac_collection: str
    bbox: str | None
    cog_url: str
    additional_cog_urls: tuple[str, ...]
    thumbnail_url: str | None
    resolution_m: float | None
    cloud_cover_pct: float | None
    created_at: datetime

    @property
    def scene_key(self) -> tuple[str, str]:
        return (self.stac_collection, self.stac_item_id)


def _is_postgres(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _extra_urls(value: Any) -> tuple[str, ...]:
    """Normalise ``additional_cog_urls`` across Postgres text[] and SQLite text.

    Same shape as ``scripts/remove_uncovered_snapshots.py``'s helper — the
    test database stores the array as the literal the driver would render.
    """
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    raw = str(value).strip()
    if not raw:
        return ()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return tuple(part.strip().strip('"') for part in raw.split(",") if part.strip())


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def load_snapshots(db: Session) -> list[Snapshot]:
    """Every ``imagery_snapshots`` row, oldest first.

    ``bbox`` is read as EWKT on PostgreSQL to dodge GeoAlchemy2's ``AsEWKB``
    on a raw select, which is the same reason ``get_imagery_snapshots`` uses
    raw SQL. On SQLite the column is plain text and passes through.
    """
    bbox_expr = "ST_AsEWKT(bbox) AS bbox" if _is_postgres(db) else "bbox"
    rows = db.execute(
        text(
            "SELECT id, parcel_id, source, capture_date, stac_item_id, stac_collection,"
            f" {bbox_expr},"
            " cog_url, additional_cog_urls, thumbnail_url, resolution_m,"
            " cloud_cover_pct, created_at"
            " FROM imagery_snapshots ORDER BY created_at, id"
        )
    ).all()

    snapshots = []
    for row in rows:
        if row.source not in SELECTION_SCOPE_BY_SOURCE:
            raise BackfillError(
                f"snapshot {row.id}: source {row.source!r} has no configured selection"
                " scope, so its group_key cannot be derived. Add it to"
                " app/tasks/timeline.py's _SOURCES before backfilling."
            )
        snapshots.append(
            Snapshot(
                id=str(row.id),
                parcel_id=str(row.parcel_id),
                source=row.source,
                capture_date=_as_date(row.capture_date),
                stac_item_id=row.stac_item_id,
                stac_collection=row.stac_collection,
                bbox=row.bbox,
                cog_url=row.cog_url,
                additional_cog_urls=_extra_urls(row.additional_cog_urls),
                thumbnail_url=row.thumbnail_url,
                resolution_m=row.resolution_m,
                cloud_cover_pct=row.cloud_cover_pct,
                created_at=_as_datetime(row.created_at),
            )
        )
    return snapshots


def group_key_for(snapshot: Snapshot) -> str:
    return encode_group_key(SELECTION_SCOPE_BY_SOURCE[snapshot.source], snapshot.capture_date)


def duplicate_groups(snapshots: list[Snapshot]) -> dict[tuple[str, str, str], list[Snapshot]]:
    """Every ``(parcel_id, source, group_key)`` served by more than one row."""
    buckets: dict[tuple[str, str, str], list[Snapshot]] = defaultdict(list)
    for snapshot in snapshots:
        buckets[(snapshot.parcel_id, snapshot.source, group_key_for(snapshot))].append(snapshot)
    return {key: rows for key, rows in buckets.items() if len(rows) > 1}


# ── Phase B: parsing a NAIP tile URL ──────────────────────────────────────────


@dataclass(frozen=True)
class ParsedTile:
    collection: str
    item_id: str
    capture_date: date


def parse_naip_tile_url(url: str) -> ParsedTile:
    """Recover a collection, a candidate item id and a capture date from a URL.

    ``https://naipeuwest.blob.core.windows.net/naip/v002/nj/2023/nj_030cm_2023/
    40074/m_4007424_ne_18_030_20230920.tif`` gives collection ``naip``,
    candidate item id ``nj_m_4007424_ne_18_030_20230920`` and capture date
    2023-09-20.

    The item id is a *candidate*: the catalogued id often carries a trailing
    publication date the filename omits. The capture date is not a guess — it
    is the first of the filename's date fields either way.

    Raises ``BackfillError`` for anything that is not a parseable NAIP tile
    URL. There is no fallback: the ADR's rule is that every mosaic entry
    resolves to a scene or is reported.
    """
    parts = PurePosixPath(urlparse(url).path).parts
    if "v002" not in parts:
        raise BackfillError(f"not a NAIP v002 tile URL: {url}")
    marker = parts.index("v002")
    if marker < 1 or marker + 1 >= len(parts):
        raise BackfillError(f"not a NAIP v002 tile URL: {url}")

    collection = parts[marker - 1]
    if collection != "naip":
        raise BackfillError(f"unexpected collection {collection!r} in tile URL: {url}")

    state = parts[marker + 1]
    name = PurePosixPath(urlparse(url).path).name
    if not name.endswith(".tif"):
        raise BackfillError(f"tile URL does not name a .tif: {url}")
    stem = name.removesuffix(".tif")

    match = _NAIP_DATE_SUFFIX.search(stem)
    if not match:
        raise BackfillError(f"no capture date in tile filename: {url}")
    try:
        capture_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError as exc:
        raise BackfillError(f"unparseable capture date in tile filename: {url}") from exc

    return ParsedTile(collection=collection, item_id=f"{state}_{stem}", capture_date=capture_date)


def platform_for(item_id: str) -> str | None:
    """The satellite the item id names, or None when it does not name one."""
    if item_id[:4] in _LANDSAT_PLATFORMS:
        return item_id[:4]
    if item_id[:3] in _SENTINEL_PLATFORMS:
        return item_id[:3]
    return None


# ── Planning ──────────────────────────────────────────────────────────────────


@dataclass
class PlannedScene:
    collection: str
    item_id: str
    source: str
    capture_date: date
    bbox: str | None
    cog_url: str
    thumbnail_url: str | None
    resolution_m: float | None
    cloud_cover_pct: float | None
    platform: str | None
    provenance: str
    fetched_at: datetime


@dataclass
class PlannedParcelScene:
    parcel_id: str
    source: str
    group_key: str
    scene_key: tuple[str, str]
    mosaic_scene_keys: tuple[tuple[str, str], ...]
    selected_at: datetime


@dataclass
class Plan:
    scenes: list[PlannedScene] = field(default_factory=list)
    parcel_scenes: list[PlannedParcelScene] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    @property
    def synthesized(self) -> list[PlannedScene]:
        return [s for s in self.scenes if s.provenance == "mosaic_url"]


_COPIED_ATTRIBUTES = (
    "capture_date",
    "bbox",
    "cog_url",
    "thumbnail_url",
    "resolution_m",
    "cloud_cover_pct",
)


def _plan_snapshot_scenes(
    snapshots: list[Snapshot], plan: Plan
) -> dict[tuple[str, str], PlannedScene]:
    """Phase A. Newest snapshot row wins; every disagreement is reported."""
    by_key: dict[tuple[str, str], list[Snapshot]] = defaultdict(list)
    for snapshot in snapshots:
        by_key[snapshot.scene_key].append(snapshot)

    planned: dict[tuple[str, str], PlannedScene] = {}
    for key, rows in by_key.items():
        newest = max(rows, key=lambda s: (s.created_at, s.id))
        for attribute in _COPIED_ATTRIBUTES:
            values = {getattr(row, attribute) for row in rows}
            if len(values) > 1:
                plan.anomalies.append(
                    f"{key[0]}/{key[1]}: {len(rows)} snapshot rows disagree on"
                    f" {attribute} ({sorted(str(v) for v in values)});"
                    f" kept the newest row's value ({getattr(newest, attribute)!r})"
                )
        planned[key] = PlannedScene(
            collection=key[0],
            item_id=key[1],
            source=newest.source,
            capture_date=newest.capture_date,
            bbox=newest.bbox,
            cog_url=newest.cog_url,
            thumbnail_url=newest.thumbnail_url,
            resolution_m=newest.resolution_m,
            cloud_cover_pct=newest.cloud_cover_pct,
            platform=platform_for(newest.stac_item_id),
            provenance="snapshot",
            # When the item entered the database, not when this run read it.
            fetched_at=min(row.created_at for row in rows),
        )
    return planned


def _plan_mosaic_scenes(
    snapshots: list[Snapshot],
    planned: dict[tuple[str, str], PlannedScene],
    plan: Plan,
) -> dict[str, tuple[str, str]]:
    """Phase B. Returns the URL → scene key map phase C resolves through."""
    url_to_key: dict[str, tuple[str, str]] = {
        snapshot.cog_url: snapshot.scene_key for snapshot in snapshots
    }

    resolved: dict[str, tuple[str, str]] = {}
    for snapshot in snapshots:
        for url in snapshot.additional_cog_urls:
            if url in resolved:
                continue
            if url in url_to_key:
                resolved[url] = url_to_key[url]
                continue

            tile = parse_naip_tile_url(url)
            key = (tile.collection, tile.item_id)
            resolved[url] = key
            if key in planned:
                # The URL matched no row's cog_url, but the id it derives to
                # is one we already have. Worth saying out loud: it means the
                # same item is reachable under two different URLs.
                plan.anomalies.append(
                    f"mosaic URL matched no cog_url but derives to an existing scene"
                    f" {key[0]}/{key[1]}: {url}"
                )
                continue

            planned[key] = PlannedScene(
                collection=tile.collection,
                item_id=tile.item_id,
                source="naip",
                capture_date=tile.capture_date,
                bbox=None,
                cog_url=url,
                thumbnail_url=None,
                resolution_m=None,
                cloud_cover_pct=None,
                platform=None,
                provenance="mosaic_url",
                fetched_at=snapshot.created_at,
            )
    return resolved


def build_plan(snapshots: list[Snapshot]) -> Plan:
    """The whole intended end state, computed before anything is written."""
    plan = Plan()
    planned_scenes = _plan_snapshot_scenes(snapshots, plan)
    resolved_urls = _plan_mosaic_scenes(snapshots, planned_scenes, plan)

    plan.scenes = list(planned_scenes.values())
    for snapshot in snapshots:
        plan.parcel_scenes.append(
            PlannedParcelScene(
                parcel_id=snapshot.parcel_id,
                source=snapshot.source,
                group_key=group_key_for(snapshot),
                scene_key=snapshot.scene_key,
                mosaic_scene_keys=tuple(resolved_urls[url] for url in snapshot.additional_cog_urls),
                selected_at=snapshot.created_at,
            )
        )
    return plan


# ── Writing ───────────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    scenes_inserted: int = 0
    scenes_present: int = 0
    synthesized_inserted: int = 0
    parcel_scenes_inserted: int = 0
    parcel_scenes_present: int = 0
    drift: list[str] = field(default_factory=list)


def _existing_scene_ids(db: Session) -> dict[tuple[str, str], str]:
    rows = db.execute(text("SELECT id, collection, item_id FROM scenes")).all()
    return {(row.collection, row.item_id): str(row.id) for row in rows}


def _existing_parcel_scenes(db: Session) -> dict[tuple[str, str, str], str]:
    rows = db.execute(
        text("SELECT parcel_id, source, group_key, scene_id FROM parcel_scenes")
    ).all()
    return {(str(row.parcel_id), row.source, row.group_key): str(row.scene_id) for row in rows}


def _insert_scenes(
    db: Session, plan: Plan, known: dict[tuple[str, str], str], out: Outcome
) -> None:
    bbox_expr = "ST_GeomFromEWKT(:bbox)" if _is_postgres(db) else ":bbox"
    statement = text(
        "INSERT INTO scenes (id, source, collection, item_id, capture_date, bbox,"
        " cog_url, thumbnail_url, resolution_m, cloud_cover_pct, platform, provenance,"
        " fetched_at)"
        " VALUES (:id, :source, :collection, :item_id, :capture_date,"
        f" {bbox_expr},"
        " :cog_url, :thumbnail_url, :resolution_m, :cloud_cover_pct, :platform,"
        " :provenance, :fetched_at)"
    )
    for scene in plan.scenes:
        key = (scene.collection, scene.item_id)
        if key in known:
            out.scenes_present += 1
            continue
        scene_id = str(uuid.uuid4())
        db.execute(
            statement,
            {
                "id": scene_id,
                "source": scene.source,
                "collection": scene.collection,
                "item_id": scene.item_id,
                "capture_date": scene.capture_date.isoformat(),
                "bbox": scene.bbox,
                "cog_url": scene.cog_url,
                "thumbnail_url": scene.thumbnail_url,
                "resolution_m": scene.resolution_m,
                "cloud_cover_pct": scene.cloud_cover_pct,
                "platform": scene.platform,
                "provenance": scene.provenance,
                "fetched_at": scene.fetched_at.isoformat(),
            },
        )
        known[key] = scene_id
        out.scenes_inserted += 1
        if scene.provenance == "mosaic_url":
            out.synthesized_inserted += 1


def _insert_parcel_scenes(
    db: Session,
    plan: Plan,
    known: dict[tuple[str, str], str],
    out: Outcome,
) -> None:
    postgres = _is_postgres(db)
    mosaic_expr = "CAST(:mosaic AS uuid[])" if postgres else ":mosaic"
    statement = text(
        "INSERT INTO parcel_scenes (id, parcel_id, source, group_key, scene_id,"
        " mosaic_scene_ids, selected_at, selected_by)"
        " VALUES (:id, :parcel_id, :source, :group_key, :scene_id,"
        f" {mosaic_expr},"
        " :selected_at, NULL)"
    )
    existing = _existing_parcel_scenes(db)
    for row in plan.parcel_scenes:
        key = (row.parcel_id, row.source, row.group_key)
        scene_id = known[row.scene_key]
        if key in existing:
            out.parcel_scenes_present += 1
            if existing[key] != scene_id:
                out.drift.append(
                    f"{key[0]} {key[1]} {key[2]}: existing row serves scene"
                    f" {existing[key]}, snapshots now imply {scene_id}"
                    f" ({row.scene_key[0]}/{row.scene_key[1]}); left unchanged"
                )
            continue

        mosaic = [known[k] for k in row.mosaic_scene_keys]
        db.execute(
            statement,
            {
                "id": str(uuid.uuid4()),
                "parcel_id": row.parcel_id,
                "source": row.source,
                "group_key": row.group_key,
                "scene_id": scene_id,
                "mosaic": (mosaic or None) if postgres else _sqlite_array(mosaic),
                "selected_at": row.selected_at.isoformat(),
            },
        )
        existing[key] = scene_id
        out.parcel_scenes_inserted += 1


def _sqlite_array(values: list[str]) -> str | None:
    """The JSON encoding ParcelScene.mosaic_scene_ids' sqlite variant reads."""
    return json.dumps(values) if values else None


# ── Entry point ───────────────────────────────────────────────────────────────


def run(db: Session, *, execute: bool) -> Outcome:
    snapshots = load_snapshots(db)
    print(f"imagery_snapshots rows: {len(snapshots)}")

    duplicates = duplicate_groups(snapshots)
    if duplicates:
        print(f"\n{len(duplicates)} duplicate (parcel_id, source, group_key) group(s):")
        for (parcel_id, source, group_key), rows in sorted(duplicates.items()):
            items = ", ".join(sorted(r.stac_item_id for r in rows))
            print(f"  {parcel_id}  {source}  {group_key}  n={len(rows)}  [{items}]")
        raise BackfillError(
            f"{len(duplicates)} duplicate (parcel_id, source, group_key) group(s)."
            " parcel_scenes cannot represent them and the ADR's change condition"
            " says to stop and investigate rather than collapse them."
        )
    print("duplicate (parcel_id, source, group_key) groups: 0")

    plan = build_plan(snapshots)
    print(
        f"\nplanned scenes: {len(plan.scenes)}"
        f" ({len(plan.synthesized)} synthesized from mosaic URLs)"
    )
    print(f"planned parcel_scenes: {len(plan.parcel_scenes)}")

    if plan.anomalies:
        print(f"\nanomalies ({len(plan.anomalies)}):")
        for note in plan.anomalies:
            print(f"  {note}")

    known = _existing_scene_ids(db)
    print(f"\nscenes already present: {len(known)}")

    if not execute:
        missing_scenes = sum(1 for s in plan.scenes if (s.collection, s.item_id) not in known)
        existing_ps = _existing_parcel_scenes(db)
        missing_ps = sum(
            1 for r in plan.parcel_scenes if (r.parcel_id, r.source, r.group_key) not in existing_ps
        )
        print(
            f"\nDry run — would insert {missing_scenes} scene(s) and"
            f" {missing_ps} parcel_scene(s). Nothing written."
        )
        return Outcome(scenes_present=len(known), parcel_scenes_present=len(existing_ps))

    out = Outcome()
    _insert_scenes(db, plan, known, out)
    _insert_parcel_scenes(db, plan, known, out)
    db.commit()

    logger.info(
        "Backfilled scenes and parcel_scenes",
        extra={
            "scenes_inserted": out.scenes_inserted,
            "scenes_present": out.scenes_present,
            "synthesized_inserted": out.synthesized_inserted,
            "parcel_scenes_inserted": out.parcel_scenes_inserted,
            "parcel_scenes_present": out.parcel_scenes_present,
            "drift": len(out.drift),
        },
    )

    print("\nWritten:")
    print(
        f"  scenes inserted:        {out.scenes_inserted}"
        f" (of which synthesized: {out.synthesized_inserted})"
    )
    print(f"  scenes already present: {out.scenes_present}")
    print(f"  parcel_scenes inserted: {out.parcel_scenes_inserted}")
    print(f"  parcel_scenes present:  {out.parcel_scenes_present}")
    if out.drift:
        print(f"\ndrift ({len(out.drift)}) — reported, not rewritten:")
        for note in out.drift:
            print(f"  {note}")
    return out


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(
        description="Backfill scenes and parcel_scenes from imagery_snapshots"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the rows. Without it this is a dry run.",
    )
    args = parser.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            run(db, execute=args.execute)
        except BackfillError as exc:
            print(f"\nREFUSED: {exc}", file=sys.stderr)
            print("Nothing was written.", file=sys.stderr)
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
