#!/usr/bin/env python3
"""Replace synthesized ``scenes`` rows' candidate item ids with catalogued ones.

The STAC enrichment pass STATUS.md NORM-7 names, and the "enrichment-first"
half of `STEP1-PROD-REPORT.md` §9. Step 1's backfill synthesized one
``scenes`` row per NAIP mosaic tile URL that no ``imagery_snapshots`` row
served directly (88 rows locally, 505 in production). Each carries
``provenance = 'mosaic_url'``, an ``item_id`` parsed out of the URL, and NULL
``footprint`` / ``bbox`` / ``resolution_m``. This script fetches the real
item and fills them in, so ``(collection, item_id)`` becomes a trustworthy
key for the whole table before step 2's dual-write starts inserting against
it.

**``cog_url`` equality is the acceptance criterion, and the only one.** A row
is enriched when a catalogued item's image asset href — read with the same
``extract_cog_url`` the pipeline wrote the URL with — equals the row's
``cog_url`` *exactly*. The candidate ``item_id`` is a hint used to address a
cheap first lookup, never evidence: STEP1-REPORT F1 measured it wrong or
partial in roughly 70% of NAIP rows. There is no fuzzy matching, no
nearest-date fallback and no "close enough" tie-break; a row that cannot be
matched by ``cog_url`` is left exactly as it is and reported.

Two lookup paths per row, cheapest first:

1. **GET the item by its candidate id.** One request, one item back, and it
   settles the row whenever the candidate happens to be exact. Any non-200 —
   404 for a candidate that is a proper prefix of the real id, 403 for the
   access-restricted NAIP items the geometry audit found six of — falls
   through to (2) rather than ending the row.
2. **Search the collection** over the capture year, with the bounding box the
   pipeline itself searched with: ``point_to_bbox(parcel, 1500 m)`` around a
   parcel that references this scene through
   ``parcel_scenes.mosaic_scene_ids`` (``app/tasks/timeline.py:1570``). The
   scene has no geometry of its own yet — that is what this pass is for — so
   the referencing parcel is the only spatial handle it has. Every returned
   item's image href is compared against ``cog_url``.

Outcomes, one per queue row: ``already-exact`` (the candidate was the
catalogued id), ``id-corrected`` (the search found it under a different id),
``merged`` (the catalogued id was already held by another ``scenes`` row),
``unmatched-404`` / ``unmatched-403`` / ``unmatched-nomatch`` (left untouched,
still in the queue), ``error``.

**Merges.** ``UNIQUE (collection, item_id)`` means the catalogued id may
already belong to a different ``scenes`` row — the same physical tile reached
under two URLs, which the backfill could not detect because it matched exact
strings. Updating in place would raise; skipping would leave two rows for one
item, which is the NORM-7 shape this pass exists to remove. So the synthesized
row is merged into the existing one: every
``parcel_scenes.mosaic_scene_ids`` reference is repointed, the synthesized row
is deleted, and each merge is reported individually. A synthesized row
referenced as a ``parcel_scenes.scene_id`` is never deleted — that cannot
happen by construction, since only ``additional_cog_urls`` entries are
synthesized, so it is reported as an error instead of being handled.

Idempotent: enriched rows leave the ``provenance = 'mosaic_url'`` queue, so a
second run finds the queue smaller by exactly the enriched count and re-touches
nothing.

Usage (dry run is the default and writes nothing; both forms do fetch):

    docker compose exec api python scripts/enrich_synthesized_scenes.py \\
        --report docs/audits/2026-08-normalization/enrich-dryrun.md
    docker compose exec api python scripts/enrich_synthesized_scenes.py \\
        --report docs/audits/2026-08-normalization/enrich-run.md --execute

``--report`` is required and is written in both modes: a long production run's
stdout does not survive the ``fly ssh console`` client timeout (STATUS.md
NORM-8), and a report that only exists on a dead client's terminal is the
capture that was lost last time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging_config import configure_script_logging
from app.services.stac import (
    STAC_API,
    extract_bbox_wkt,
    extract_capture_date,
    extract_cog_url,
    extract_footprint_wkt,
    point_to_bbox,
)

logger = logging.getLogger("enrich_synthesized_scenes")

# The queue. Nothing outside it is read for enrichment and nothing outside it
# is written, except a merge's repointed parcel_scenes.mosaic_scene_ids.
QUEUE_PROVENANCE = "mosaic_url"

# What an enriched row becomes. Not 'snapshot': that value means "copied from
# an imagery_snapshots row", which an enriched row never was — see migration
# 0016's docstring for the whole argument.
ENRICHED_PROVENANCE = "enriched"

# The buffer app/tasks/timeline.py:1570 searches NAIP with. Reusing it is what
# makes the fallback search a re-run of the search that selected the tile in
# the first place, rather than a new guess about where the tile might be.
SEARCH_BUFFER_M = 1500.0

# Geometry audit precedent (docs/audits/2026-08-geometry-audit/FINDINGS.md:
# "1,239 distinct items fetched at concurrency 6 with 429 backoff").
FETCH_CONCURRENCY = 6
FETCH_ATTEMPTS = 4
FETCH_TIMEOUT_S = 30.0

# NORM-10 (docs/audits/2026-08-normalization/ENRICH-PROD-REPORT.md §5): PC
# answers a throttle on /search with 403, not 429. For the item endpoint 403
# is a permanent per-item refusal (the geometry audit's six forbidden NAIP
# items) and must fall through to search immediately rather than burn the
# retry budget on something that will never succeed. For /search the same
# 403 is the rate limiter, so it has to be retried like a 429 would be — the
# two endpoints need different sets, not one shared constant, even though a
# reader's first instinct is that "403 Forbidden" means the same thing
# everywhere.
_ITEM_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_SEARCH_RETRYABLE_STATUSES = _ITEM_RETRYABLE_STATUSES | {403}

# NORM-10: ~814 requests in 28s (~29 req/s) at concurrency 6 with no pacing
# provoked the throttle; the same six searches replayed sequentially with a
# 2s gap (0.5 req/s) all returned 200. This is a global cap on how often a
# request is *dispatched*, independent of FETCH_CONCURRENCY, which only
# bounds how many are in flight awaiting a response — concurrency alone
# doesn't limit rate when responses are fast. 5 req/s leaves ~6x margin
# under the observed throttle point while still finishing 505 rows
# (~814 requests) in a few minutes.
DEFAULT_MIN_INTERVAL_S = 0.2


# ── Reading the queue ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueueRow:
    id: str
    source: str
    collection: str
    item_id: str
    capture_date: date
    cog_url: str
    parcel_id: str | None
    latitude: float | None
    longitude: float | None
    #: True when a parcel_scenes row names this scene as its primary
    #: ``scene_id``. Impossible for a synthesized row by construction; checked
    #: because a merge deletes rows.
    is_primary_somewhere: bool


def _is_postgres(db: Session) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _id_array(value: Any) -> list[str]:
    """Normalise ``mosaic_scene_ids`` across Postgres uuid[] and SQLite JSON.

    The same split ``backfill_scenes._extra_urls`` makes for ``text[]``: the
    test database stores the array as the JSON literal
    ``ParcelScene.mosaic_scene_ids``' sqlite variant reads.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        return [str(v) for v in json.loads(raw)]
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    return [part.strip().strip('"') for part in raw.split(",") if part.strip()]


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True)
class MosaicRef:
    """One ``parcel_scenes`` row's references, as loaded."""

    id: str
    parcel_id: str
    scene_id: str
    mosaic_scene_ids: list[str]


def load_mosaic_refs(db: Session) -> list[MosaicRef]:
    rows = db.execute(
        text("SELECT id, parcel_id, scene_id, mosaic_scene_ids FROM parcel_scenes")
    ).all()
    return [
        MosaicRef(
            id=str(row.id),
            parcel_id=str(row.parcel_id),
            scene_id=str(row.scene_id),
            mosaic_scene_ids=_id_array(row.mosaic_scene_ids),
        )
        for row in rows
    ]


def load_queue(db: Session) -> list[QueueRow]:
    """Every ``provenance = 'mosaic_url'`` row, with a parcel to search from.

    The parcel is the lowest ``parcel_id`` among those referencing the scene,
    chosen for determinism rather than for any spatial property: every
    referencing parcel's 1500 m search box contained this tile once, because
    that is where the tile came from.
    """
    refs = load_mosaic_refs(db)
    parcels = {
        str(row.id): (float(row.latitude), float(row.longitude))
        for row in db.execute(text("SELECT id, latitude, longitude FROM parcels")).all()
    }

    referencing: dict[str, set[str]] = {}
    primary: set[str] = set()
    for ref in refs:
        primary.add(ref.scene_id)
        for scene_id in ref.mosaic_scene_ids:
            referencing.setdefault(scene_id, set()).add(ref.parcel_id)

    rows = db.execute(
        text(
            "SELECT id, source, collection, item_id, capture_date, cog_url"
            " FROM scenes WHERE provenance = :provenance"
            " ORDER BY collection, item_id"
        ),
        {"provenance": QUEUE_PROVENANCE},
    ).all()

    queue = []
    for row in rows:
        scene_id = str(row.id)
        parcel_ids = sorted(referencing.get(scene_id, ()))
        parcel_id = parcel_ids[0] if parcel_ids else None
        point = parcels.get(parcel_id) if parcel_id else None
        queue.append(
            QueueRow(
                id=scene_id,
                source=row.source,
                collection=row.collection,
                item_id=row.item_id,
                capture_date=_as_date(row.capture_date),
                cog_url=row.cog_url,
                parcel_id=parcel_id,
                latitude=point[0] if point else None,
                longitude=point[1] if point else None,
                is_primary_somewhere=scene_id in primary,
            )
        )
    return queue


# ── The STAC layer ────────────────────────────────────────────────────────────


class StacLookup:
    """The two PC calls this pass makes. Replaced wholesale in tests.

    Concurrency and backoff live here rather than at the call sites so both
    paths share one limiter, the way ``stac.py``'s signing does.
    """

    def __init__(
        self,
        *,
        concurrency: int = FETCH_CONCURRENCY,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    ) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._min_interval_s = min_interval_s
        self._pace_lock = asyncio.Lock()
        self._next_dispatch_at = 0.0
        self._client = httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_S,
            limits=httpx.Limits(
                max_connections=concurrency * 2, max_keepalive_connections=concurrency
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _pace(self) -> None:
        """Space out request dispatches to at most ``1 / min_interval_s`` per second.

        Global across every in-flight request, not per-worker: concurrency
        bounds how many requests are outstanding, this bounds how often a new
        one is sent, which is what NORM-10 needed and concurrency alone does
        not provide.
        """
        if self._min_interval_s <= 0:
            return
        async with self._pace_lock:
            now = asyncio.get_event_loop().time()
            wait = self._next_dispatch_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = self._next_dispatch_at
            self._next_dispatch_at = now + self._min_interval_s

    async def _request(
        self,
        url: str,
        *,
        json_body: dict[str, Any] | None,
        retryable_statuses: frozenset[int],
    ) -> httpx.Response:
        """One request, retrying the given statuses and transport errors with backoff.

        ``Retry-After`` is honoured when the server sends one — PC's rate
        limiter does — and doubling backoff is the fallback. The last response
        is returned rather than raised for status: a 404 (and, on the item
        endpoint, a 403) is an answer this pass records per row, not a
        failure of the run. ``retryable_statuses`` differs by endpoint — see
        the NORM-10 comment at the module-level constants.
        """
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(FETCH_ATTEMPTS):
            try:
                async with self._semaphore:
                    await self._pace()
                    if json_body is None:
                        resp = await self._client.get(url)
                    else:
                        resp = await self._client.post(url, json=json_body)
                if resp.status_code not in retryable_statuses:
                    return resp
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
                wait = _retry_after_seconds(resp)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                wait = None
            if attempt == FETCH_ATTEMPTS - 1:
                break
            sleep_for = wait if wait is not None else delay
            logger.info(
                "STAC request failed; backing off",
                extra={"attempt": attempt + 1, "wait_s": sleep_for, "error": str(last_exc)},
            )
            await asyncio.sleep(sleep_for)
            delay *= 2
        assert last_exc is not None  # only reached after a retryable failure
        raise last_exc

    async def get_item(self, collection: str, item_id: str) -> tuple[int, dict[str, Any] | None]:
        """``(status, item)`` for the item endpoint. ``item`` is None off 200."""
        resp = await self._request(
            f"{STAC_API}/collections/{collection}/items/{item_id}",
            json_body=None,
            retryable_statuses=_ITEM_RETRYABLE_STATUSES,
        )
        if resp.status_code != 200:
            return resp.status_code, None
        return 200, dict(resp.json())

    async def search(
        self,
        collection: str,
        bbox: tuple[float, float, float, float],
        datetime_range: str,
    ) -> list[dict[str, Any]]:
        """One page of a bbox+datetime search. No pagination: see the caller."""
        resp = await self._request(
            f"{STAC_API}/search",
            json_body={
                "collections": [collection],
                "bbox": list(bbox),
                "datetime": datetime_range,
                "limit": 100,
            },
            retryable_statuses=_SEARCH_RETRYABLE_STATUSES,
        )
        resp.raise_for_status()
        return [dict(feature) for feature in resp.json().get("features", [])]


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """``Retry-After`` in delta-seconds form, or None. Twin of stac.py's."""
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


# ── Resolution: one queue row → one catalogued item, or nothing ───────────────


@dataclass
class Resolution:
    row: QueueRow
    #: ``already-exact`` | ``id-corrected`` | ``unmatched-404`` |
    #: ``unmatched-403`` | ``unmatched-nomatch`` | ``error``. ``merged`` is
    #: decided at write time, not here.
    outcome: str
    item: dict[str, Any] | None = None
    detail: str = ""


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id", ""))


async def resolve_row(lookup: StacLookup, row: QueueRow) -> Resolution:
    """Find the catalogued item whose image href equals ``row.cog_url``."""
    get_status: int | None = None
    note = ""
    try:
        get_status, item = await lookup.get_item(row.collection, row.item_id)
        if item is not None:
            if extract_cog_url(item, row.collection) == row.cog_url:
                return Resolution(row, "already-exact", item)
            # The candidate id names a real item, but not this tile. Not a
            # match — that is the whole point of the cog_url criterion — and
            # worth saying out loud, because it is the one shape where a naive
            # id-based enrichment would have written another item's facts onto
            # this row.
            note = " (candidate id names a different item)"

        if row.latitude is None or row.longitude is None:
            return Resolution(
                row,
                _unmatched_outcome(get_status),
                None,
                f"item GET {get_status}{note}; no parcel references this scene, so there"
                " is no bbox to search with",
            )

        bbox = point_to_bbox(row.latitude, row.longitude, buffer_m=SEARCH_BUFFER_M)
        year = row.capture_date.year
        items = await lookup.search(
            row.collection, bbox, f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z"
        )
        for candidate in items:
            if extract_cog_url(candidate, row.collection) == row.cog_url:
                return Resolution(
                    row,
                    "id-corrected",
                    candidate,
                    f"item GET {get_status}{note}; found by search as {_item_id(candidate)}",
                )
        return Resolution(
            row,
            _unmatched_outcome(get_status),
            None,
            f"item GET {get_status}{note}; search over {year} returned {len(items)}"
            " item(s), none whose image href equals this row's cog_url",
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        return Resolution(row, "error", None, f"item GET {get_status}; {type(exc).__name__}: {exc}")


def _unmatched_outcome(get_status: int | None) -> str:
    if get_status == 404:
        return "unmatched-404"
    if get_status == 403:
        return "unmatched-403"
    return "unmatched-nomatch"


async def resolve_all(lookup: StacLookup, queue: list[QueueRow]) -> list[Resolution]:
    return list(await asyncio.gather(*(resolve_row(lookup, row) for row in queue)))


# ── Writing ───────────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    enriched: int = 0
    already_exact: int = 0
    id_corrected: int = 0
    merged: int = 0
    unmatched: int = 0
    errors: int = 0
    #: One line per row, in queue order: (item_id, outcome, detail).
    rows: list[tuple[str, str, str]] = field(default_factory=list)
    merges: list[str] = field(default_factory=list)
    date_disagreements: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)


def _footprint_ewkt(item: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(ewkt, complaint)`` for ``item["geometry"]`` as a POLYGON.

    Delegates to ``stac.extract_footprint_wkt``, which the step-2 dual-write
    also calls: a MultiPolygon rejected here and accepted there would put two
    different geometries in one column depending on which writer got to the
    item first. The identity of an enriched row is established by ``cog_url``
    regardless of the geometry's shape, so a complaint leaves the footprint
    NULL and does not drop the enrichment.
    """
    return extract_footprint_wkt(item)


def _item_capture_date(item: dict[str, Any]) -> date | None:
    """The item's ``properties.datetime`` as a date, or None if unusable.

    ``extract_capture_date`` raises on an item with no parseable datetime.
    Such an item is not a reason to refuse a match — the match was made on
    ``cog_url`` — so the row keeps the date the filename gave it, which is the
    one field STEP1-REPORT F1 found the filename gets right every time.
    """
    try:
        return extract_capture_date(item)
    except (KeyError, TypeError, ValueError):
        return None


def _gsd(item: dict[str, Any]) -> float | None:
    props = item.get("properties")
    if not isinstance(props, dict):
        return None
    value = props.get("gsd")
    return float(value) if isinstance(value, (int, float)) else None


def _existing_scene_ids(db: Session) -> dict[tuple[str, str], str]:
    rows = db.execute(text("SELECT id, collection, item_id FROM scenes")).all()
    return {(row.collection, row.item_id): str(row.id) for row in rows}


def _update_scene(db: Session, resolution: Resolution, out: Outcome) -> None:
    row = resolution.row
    item = resolution.item
    assert item is not None
    footprint, complaint = _footprint_ewkt(item)
    if complaint:
        out.anomalies.append(f"{row.collection}/{_item_id(item)}: {complaint}; footprint left NULL")

    capture_date = _item_capture_date(item) or row.capture_date
    footprint_expr = "ST_GeomFromEWKT(:footprint)" if _is_postgres(db) else ":footprint"
    bbox_expr = "ST_GeomFromEWKT(:bbox)" if _is_postgres(db) else ":bbox"
    db.execute(
        text(
            "UPDATE scenes SET item_id = :item_id, capture_date = :capture_date,"
            f" footprint = {footprint_expr}, bbox = {bbox_expr},"
            " resolution_m = :resolution_m, provenance = :provenance"
            " WHERE id = :id"
        ),
        {
            "item_id": _item_id(item),
            "capture_date": capture_date.isoformat(),
            "footprint": footprint,
            "bbox": extract_bbox_wkt(item),
            "resolution_m": _gsd(item),
            "provenance": ENRICHED_PROVENANCE,
            "id": row.id,
        },
    )


def _merge_scene(db: Session, resolution: Resolution, target_id: str, out: Outcome) -> None:
    """Repoint every mosaic reference from the synthesized row, then delete it."""
    row = resolution.row
    item = resolution.item
    assert item is not None

    postgres = _is_postgres(db)
    repointed = 0
    for ref in load_mosaic_refs(db):
        if row.id not in ref.mosaic_scene_ids:
            continue
        merged: list[str] = []
        for scene_id in ref.mosaic_scene_ids:
            replacement = target_id if scene_id == row.id else scene_id
            # A parcel_scenes row that already referenced the target keeps one
            # reference, not two: the array names distinct tiles.
            if replacement not in merged:
                merged.append(replacement)
        db.execute(
            text(
                "UPDATE parcel_scenes SET mosaic_scene_ids ="
                f" {'CAST(:mosaic AS uuid[])' if postgres else ':mosaic'}"
                " WHERE id = :id"
            ),
            {
                "mosaic": (merged or None)
                if postgres
                else (json.dumps(merged) if merged else None),
                "id": ref.id,
            },
        )
        repointed += 1

    db.execute(text("DELETE FROM scenes WHERE id = :id"), {"id": row.id})
    out.merges.append(
        f"{row.collection}/{row.item_id} (scene {row.id}) merged into"
        f" {row.collection}/{_item_id(item)} (scene {target_id});"
        f" {repointed} parcel_scenes row(s) repointed; synthesized row deleted"
    )


def apply_resolutions(
    db: Session, resolutions: list[Resolution], out: Outcome, *, execute: bool
) -> None:
    """Decide what happens to every row, and do it when ``execute``.

    Dry run and execute share this function rather than having one each: a
    dry run whose plan can drift from what the write does is the capture that
    tells you the wrong thing, which is the mistake NORM-8 is about. The only
    branches on ``execute`` are the three statements that touch the database.
    """
    known = _existing_scene_ids(db)
    for resolution in resolutions:
        row = resolution.row
        item = resolution.item
        if item is None:
            out.rows.append((row.item_id, resolution.outcome, resolution.detail))
            if resolution.outcome == "error":
                out.errors += 1
            else:
                out.unmatched += 1
            continue

        catalogued_id = _item_id(item)
        item_date = _item_capture_date(item)
        if item_date is not None and item_date != row.capture_date:
            out.date_disagreements.append(
                f"{row.collection}/{catalogued_id}: row says {row.capture_date},"
                f" item says {item_date}; row takes the item's"
            )

        collision = known.get((row.collection, catalogued_id))
        if collision is not None and collision != row.id:
            if row.is_primary_somewhere:
                out.rows.append(
                    (
                        row.item_id,
                        "error",
                        f"catalogued id {catalogued_id} is already scene {collision}, but this"
                        " synthesized row is a parcel_scenes.scene_id; not merged, not deleted",
                    )
                )
                out.errors += 1
                continue
            if execute:
                _merge_scene(db, resolution, collision, out)
            out.merged += 1
            out.rows.append((row.item_id, "merged", f"into {catalogued_id} (scene {collision})"))
            continue

        if execute:
            _update_scene(db, resolution, out)
        known.pop((row.collection, row.item_id), None)
        known[(row.collection, catalogued_id)] = row.id
        out.enriched += 1
        if resolution.outcome == "already-exact":
            out.already_exact += 1
        else:
            out.id_corrected += 1
        out.rows.append((row.item_id, resolution.outcome, resolution.detail))


# ── Reporting ─────────────────────────────────────────────────────────────────


def render_report(out: Outcome, *, queue_size: int, execute: bool, started: datetime) -> str:
    mode = "execute" if execute else "dry run"
    lines = [
        f"# STAC enrichment of synthesized scenes — {mode}",
        "",
        f"Started {started.isoformat(timespec='seconds')}. Queue at start:"
        f" **{queue_size}** rows with `provenance = 'mosaic_url'`.",
        "",
        "## Totals",
        "",
        "| Outcome | Rows |",
        "|---|---|",
        f"| already-exact (candidate id was catalogued) | {out.already_exact} |",
        f"| id-corrected (found by search under another id) | {out.id_corrected} |",
        f"| merged into an existing scenes row | {out.merged} |",
        f"| unmatched (left in the queue) | {out.unmatched} |",
        f"| error | {out.errors} |",
        "",
        f"Rows enriched in place: **{out.enriched}**. Queue after this run:"
        f" **{queue_size - out.enriched - out.merged}**.",
        "",
    ]

    lines += ["## Capture-date disagreements", ""]
    if out.date_disagreements:
        lines += [f"- {note}" for note in out.date_disagreements]
    else:
        lines.append("None. Every matched item's `datetime` equals the date parsed from")
        lines.append("the tile filename.")
    lines.append("")

    lines += ["## Merges", ""]
    if out.merges:
        lines += [f"- {note}" for note in out.merges]
    else:
        lines.append("None.")
    lines.append("")

    if out.anomalies:
        lines += ["## Anomalies", ""] + [f"- {note}" for note in out.anomalies] + [""]

    lines += ["## Per row", "", "| Candidate item id | Outcome | Detail |", "|---|---|---|"]
    for item_id, outcome, detail in out.rows:
        lines.append(f"| `{item_id}` | {outcome} | {detail or ''} |")
    lines.append("")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────


def run(db: Session, *, execute: bool, report_path: Path, lookup: StacLookup) -> Outcome:
    started = datetime.now(UTC)
    queue = load_queue(db)
    print(f"queue (provenance = '{QUEUE_PROVENANCE}'): {len(queue)} row(s)")
    if not queue:
        print("Nothing to enrich.")
        out = Outcome()
        _write_report(
            report_path, render_report(out, queue_size=0, execute=execute, started=started)
        )
        return out

    orphans = [row for row in queue if row.parcel_id is None]
    if orphans:
        print(f"note: {len(orphans)} queue row(s) have no referencing parcel; item GET only")

    resolutions = asyncio.run(_resolve(lookup, queue))

    out = Outcome()
    apply_resolutions(db, resolutions, out, execute=execute)
    if execute:
        db.commit()

    report = render_report(out, queue_size=len(queue), execute=execute, started=started)
    _write_report(report_path, report)
    print()
    print(report)
    verb = "Wrote" if execute else "Would write"
    print(
        f"{verb}: {out.enriched} enriched, {out.merged} merged,"
        f" {out.unmatched} unmatched, {out.errors} error(s)."
        + ("" if execute else " Dry run — nothing written.")
    )
    print(f"Report: {report_path}")
    logger.info(
        "Enriched synthesized scenes",
        extra={
            "execute": execute,
            "queue": len(queue),
            "enriched": out.enriched,
            "already_exact": out.already_exact,
            "id_corrected": out.id_corrected,
            "merged": out.merged,
            "unmatched": out.unmatched,
            "errors": out.errors,
        },
    )
    return out


async def _resolve(lookup: StacLookup, queue: list[QueueRow]) -> list[Resolution]:
    try:
        return await resolve_all(lookup, queue)
    finally:
        await lookup.aclose()


def _write_report(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> None:
    configure_script_logging()

    parser = argparse.ArgumentParser(
        description="Replace synthesized scenes' candidate item ids with catalogued ones"
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Where to write the run report. Required in both modes: a killed"
        " ssh client takes stdout with it (STATUS.md NORM-8).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the rows. Without it this is a dry run that still fetches.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=FETCH_CONCURRENCY,
        help=f"Max in-flight STAC requests (default {FETCH_CONCURRENCY}).",
    )
    parser.add_argument(
        "--min-interval-s",
        type=float,
        default=DEFAULT_MIN_INTERVAL_S,
        help="Minimum seconds between dispatching successive STAC requests,"
        f" regardless of concurrency (default {DEFAULT_MIN_INTERVAL_S}, NORM-10)."
        " 0 disables pacing.",
    )
    args = parser.parse_args()

    from app.db import SessionLocal

    lookup = StacLookup(concurrency=args.concurrency, min_interval_s=args.min_interval_s)
    with SessionLocal() as db:
        run(db, execute=args.execute, report_path=args.report, lookup=lookup)


if __name__ == "__main__":
    main()
