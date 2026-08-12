"""Imagery timeline API endpoints.

POST /api/v1/parcels/{parcel_id}/timeline  — trigger a new fetch
GET  /api/v1/timeline-requests/{request_id} — poll status
GET  /api/v1/parcels/{parcel_id}/imagery    — list snapshots (signed URLs)
GET  /api/v1/imagery/{snapshot_id}/tiles/{z}/{x}/{y} — tile proxy
GET  /api/v1/imagery/{snapshot_id}/stac     — signed STAC item (Landsat)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi import Response as FastAPIResponse
from fastapi.responses import Response
from redis.exceptions import RedisError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.rate_limit import RateLimit
from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.imagery import (
    ImageryListResponse,
    ImagerySnapshotResponse,
    TimelineRequestResponse,
    TimelineRequestTaskResponse,
    TriggerTimelineResponse,
)
from app.services import imagery as imagery_service
from app.services import stac as stac_service
from app.services.imagery import ImagerySnapshotRow

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/parcels/{parcel_id}/timeline",
    response_model=TriggerTimelineResponse,
    status_code=202,
    summary="Trigger imagery timeline fetch",
    description=(
        "Creates a new timeline request for the given parcel and kicks off "
        "an async job to search for NAIP, Landsat, and Sentinel-2 imagery."
    ),
    responses={
        404: {"description": "Parcel not found"},
        429: {"description": "Rate limit exceeded"},
    },
    dependencies=[Depends(RateLimit(times=20, seconds=60))],
)
def trigger_timeline(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TriggerTimelineResponse:
    """Trigger a new imagery timeline fetch for an existing parcel."""
    from sqlalchemy import text as sa_text

    from app.models.parcels import Parcel

    row = db.execute(
        sa_text("SELECT id FROM parcels WHERE id = :id"),
        {"id": str(parcel_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Parcel {parcel_id} not found")

    request, is_new = imagery_service.get_or_create_timeline_request(db, parcel_id)

    if not is_new:
        parcel = db.get(Parcel, parcel_id)
        if parcel:
            refetch_req = imagery_service.maybe_refetch_for_backfill(
                db,
                parcel,
                request,
            )
            if refetch_req is not None:
                request = refetch_req
                is_new = True

    if is_new:
        imagery_service.dispatch_timeline_task(db, request)

    return TriggerTimelineResponse(timeline_request_id=request.id)


@router.get(
    "/timeline-requests/{request_id}",
    response_model=TimelineRequestResponse,
    summary="Get timeline request status",
    description="Returns the overall status and per-source task breakdown.",
    responses={
        404: {"description": "Timeline request not found"},
    },
)
def get_timeline_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TimelineRequestResponse:
    """Return timeline request status including per-source tasks."""
    request = imagery_service.get_timeline_request(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Timeline request {request_id} not found")

    tasks = [TimelineRequestTaskResponse.model_validate(t) for t in request.tasks]
    return TimelineRequestResponse(
        id=request.id,
        parcel_id=request.parcel_id,
        status=request.status,
        created_at=request.created_at,
        completed_at=request.completed_at,
        error_message=request.error_message,
        tasks=tasks,
    )


_PC_PREVIEW_PATH = "/api/data/v1/item/preview.png"
# Timeline thumbnails render in a 64px box; 128 covers 2x displays.
_THUMBNAIL_MAX_SIZE = "128"


def _is_pc_preview(url: str) -> bool:
    return urlparse(url).path == _PC_PREVIEW_PATH


def _bounded_preview_url(url: str) -> str:
    """Cap a Planetary Computer rendered_preview at thumbnail size.

    Unbounded, preview.png renders the whole scene: ~1 MB and ~2.4s of
    server-side render per thumbnail, for a 64px card. With max_size the
    same preview is ~19 KB and under a second.
    """
    parts = urlparse(url)
    params = parse_qs(parts.query, keep_blank_values=True)
    if "max_size" in params or "width" in params or "height" in params:
        return url
    params["max_size"] = [_THUMBNAIL_MAX_SIZE]
    return urlunparse(parts._replace(query=urlencode(params, doseq=True)))


@router.get(
    "/parcels/{parcel_id}/imagery",
    response_model=ImageryListResponse,
    summary="List imagery snapshots for a parcel",
    description=(
        "Returns all available imagery snapshots for the given parcel, "
        "sorted chronologically. COG URLs are signed at response time."
    ),
    responses={
        404: {"description": "Parcel not found"},
    },
)
async def list_imagery(
    parcel_id: uuid.UUID,
    response: FastAPIResponse,
    source: str | None = Query(
        default=None, description="Filter by source: naip, landsat, sentinel2, usgs_topo"
    ),
    start_date: date | None = Query(default=None, description="Filter by start date (inclusive)"),
    end_date: date | None = Query(default=None, description="Filter by end date (inclusive)"),
    db: Session = Depends(get_db),
) -> ImageryListResponse:
    """Return imagery snapshots with signed COG URLs."""
    from sqlalchemy import text as sa_text

    # Sync DB work runs in the threadpool — this handler is async (for the
    # parallel URL signing below) and must not block the event loop.
    def _load_snapshots() -> list[ImagerySnapshotRow] | None:
        row = db.execute(
            sa_text("SELECT id FROM parcels WHERE id = :id"),
            {"id": str(parcel_id)},
        ).first()
        if not row:
            return None
        return imagery_service.get_imagery_snapshots(
            db,
            parcel_id=parcel_id,
            source=source,
            start_date=start_date,
            end_date=end_date,
        )

    snapshots = await run_in_threadpool(_load_snapshots)
    if snapshots is None:
        raise HTTPException(status_code=404, detail=f"Parcel {parcel_id} not found")

    # Sign COG URLs at response time (SAS tokens are short-lived).
    # Landsat cog_url is a STAC item link (public, no signing needed).
    # Collect every URL that needs signing, then run them in parallel —
    # a parcel can have 80+ URLs (e.g. Rodanthe with full Sentinel-2 stack)
    # and serial awaits compound to tens of seconds even with Redis cache.
    # usgs_topo COG URLs are public S3 — no Planetary Computer signing needed.
    _NO_SIGN_SOURCES = {"landsat", "usgs_topo"}
    urls_to_sign: set[str] = set()
    for snap in snapshots:
        if snap.source not in _NO_SIGN_SOURCES:
            urls_to_sign.add(snap.cog_url)
            if snap.additional_cog_urls:
                urls_to_sign.update(snap.additional_cog_urls)
        # rendered_preview thumbnails are data-API URLs that sign themselves
        # server-side — the SAS endpoint hands them back unchanged, so signing
        # one is a wasted round-trip per snapshot on a cold cache.
        if snap.thumbnail_url and not _is_pc_preview(snap.thumbnail_url):
            urls_to_sign.add(snap.thumbnail_url)

    url_list = list(urls_to_sign)
    results = await asyncio.gather(
        *(
            stac_service.sign_pc_url(u, wait_budget=stac_service.SIGN_WAIT_REQUEST)
            for u in url_list
        ),
        return_exceptions=True,
    )
    # Unsignable URLs are left out of the map rather than mapped to their
    # unsigned selves: a private blob href that reached the browser could
    # only fail, so a snapshot missing its signature is dropped below.
    signed_map: dict[str, str] = {
        u: r for u, r in zip(url_list, results, strict=False) if isinstance(r, str)
    }
    unsignable = len(url_list) - len(signed_map)
    if unsignable:
        logger.warning(
            "Dropping imagery whose URLs could not be signed",
            extra={"parcel_id": str(parcel_id), "unsigned_urls": unsignable},
        )

    snapshot_responses: list[ImagerySnapshotResponse] = []
    for snap in snapshots:
        if snap.source in _NO_SIGN_SOURCES:
            signed_cog = snap.cog_url
            signed_extras: list[str] | None = snap.additional_cog_urls
        else:
            if snap.cog_url not in signed_map:
                continue
            signed_cog = signed_map[snap.cog_url]
            # A mosaic component that didn't sign is dropped from the group;
            # the remaining tiles still render, just with a gap.
            signed_extras = (
                [signed_map[u] for u in snap.additional_cog_urls if u in signed_map]
                if snap.additional_cog_urls
                else None
            )

        signed_thumb: str | None
        if not snap.thumbnail_url:
            signed_thumb = None
        elif _is_pc_preview(snap.thumbnail_url):
            signed_thumb = _bounded_preview_url(snap.thumbnail_url)
        else:
            # Thumbnails are optional in the UI — an unsigned one is a broken
            # <img>, a missing one is the placeholder the Timeline already has.
            signed_thumb = signed_map.get(snap.thumbnail_url)

        snapshot_responses.append(
            ImagerySnapshotResponse(
                id=snap.id,
                source=snap.source,
                capture_date=snap.capture_date,
                cog_url=signed_cog,
                additional_cog_urls=signed_extras,
                bbox=list(snap.bbox) if snap.bbox else None,
                thumbnail_url=signed_thumb,
                resolution_m=snap.resolution_m,
                cloud_cover_pct=snap.cloud_cover_pct,
                stac_item_id=snap.stac_item_id,
                stac_collection=snap.stac_collection,
            )
        )

    response.headers["Cache-Control"] = "no-cache"

    return ImageryListResponse(parcel_id=parcel_id, snapshots=snapshot_responses)


# ── Snapshot cache ────────────────────────────────────────────────────────────

_snapshot_cache: OrderedDict[uuid.UUID, tuple[float, ImagerySnapshotRow]] = OrderedDict()
_SNAPSHOT_CACHE_TTL = 300
_SNAPSHOT_CACHE_MAX = 500


def _get_cached_snapshot(snapshot_id: uuid.UUID) -> ImagerySnapshotRow | None:
    entry = _snapshot_cache.get(snapshot_id)
    if entry and time.monotonic() - entry[0] < _SNAPSHOT_CACHE_TTL:
        return entry[1]
    return None


def _put_cached_snapshot(snapshot_id: uuid.UUID, snap: ImagerySnapshotRow) -> None:
    _snapshot_cache[snapshot_id] = (time.monotonic(), snap)
    _snapshot_cache.move_to_end(snapshot_id)
    while len(_snapshot_cache) > _SNAPSHOT_CACHE_MAX:
        _snapshot_cache.popitem(last=False)


# ── Tile proxy helpers ────────────────────────────────────────────────────────

_COG_PARAMS: dict[str, dict[str, object]] = {
    "naip": {"bidx": [1, 2, 3], "rescale": "0,255"},  # 4-band uint8 RGBI
    "sentinel2": {"bidx": [1, 2, 3], "rescale": "0,255"},  # 3-band uint8 TCI
    "usgs_topo": {"bidx": [1, 2, 3], "rescale": "0,255"},  # scanned RGB map
}

_titiler_client: httpx.AsyncClient | None = None
_stac_fetch_client: httpx.AsyncClient | None = None


def _get_titiler_client() -> httpx.AsyncClient:
    global _titiler_client
    if _titiler_client is None:
        _titiler_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=30),
        )
    return _titiler_client


# Only Landsat snapshots reach the STAC fetch, and for Landsat cog_url holds
# the Planetary Computer item self-link — every row in the table is on this
# host. (The blob hosts that serve NAIP and Sentinel-2 COGs are not included:
# those sources never take this path.) Without the check, a cog_url written
# by a compromised upstream would make the API fetch an attacker-chosen URL
# from inside the network. Second-order, but the check is nearly free.
_ALLOWED_STAC_HOSTS = frozenset({"planetarycomputer.microsoft.com"})


def _is_allowed_stac_host(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in _ALLOWED_STAC_HOSTS


def _get_stac_fetch_client() -> httpx.AsyncClient:
    global _stac_fetch_client
    if _stac_fetch_client is None:
        _stac_fetch_client = httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _stac_fetch_client


async def close_clients() -> None:
    global _titiler_client, _stac_fetch_client
    if _titiler_client is not None:
        await _titiler_client.aclose()
        _titiler_client = None
    if _stac_fetch_client is not None:
        await _stac_fetch_client.aclose()
        _stac_fetch_client = None


# Unbounded z/x/y rode straight through to Titiler, which turned z=50 or a
# negative index into a 500 and then into our 502 path. 24 is past the
# resolution of any source we serve. x/y get one generous static bound rather
# than the exact per-zoom 2**z - 1: anything inside the bound but outside the
# COG's extent already comes back as a transparent tile, so a tighter check
# would buy nothing the existing path doesn't handle.
_MAX_ZOOM = 24
_MAX_TILE_INDEX = 2**24 - 1

# 1x1 transparent PNG (68 bytes) — returned for out-of-bounds tile requests
# so MapLibre doesn't log 404 errors for edge tiles.
_TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _fetch_titiler(
    titiler_url: str,
    params: dict[str, Any] | list[tuple[str, str]],
    snapshot_id: uuid.UUID,
) -> Response:
    """Forward a tile request to Titiler and return the response."""
    try:
        upstream = await _get_titiler_client().get(titiler_url, params=params)  # type: ignore[arg-type]  # params values are httpx-compatible primitives (str, int, list[str])
    except httpx.RequestError as exc:
        logger.error("Titiler request failed", exc_info=exc)
        raise HTTPException(status_code=502, detail="Titiler upstream unreachable") from exc

    if upstream.status_code >= 500:
        logger.error(
            "Titiler returned %s for snapshot %s",
            upstream.status_code,
            snapshot_id,
            extra={"titiler_body": upstream.text[:500]},
        )
        raise HTTPException(status_code=502, detail="Titiler upstream error")

    # Return a transparent tile for out-of-bounds requests instead of 404,
    # so MapLibre doesn't log errors for edge tiles outside the COG extent.
    # Short TTL: a 404 can also be transient upstream trouble (blob
    # re-staging, expired token), and "immutable" would freeze the hole
    # in browser caches for a day.
    if upstream.status_code == 404:
        return Response(
            content=_TRANSPARENT_PNG,
            status_code=200,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # Other 4xx from Titiler (bad band index, malformed COG, ...) must not
    # be passed through with cache headers — browsers would pin the error.
    if upstream.status_code != 200:
        logger.warning(
            "Titiler returned %s for snapshot %s",
            upstream.status_code,
            snapshot_id,
            extra={"titiler_body": upstream.text[:500]},
        )
        raise HTTPException(status_code=502, detail="Titiler upstream error")

    return Response(
        content=upstream.content,
        status_code=200,
        media_type=upstream.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


async def _proxy_cog_tile(
    snap: ImagerySnapshotRow,
    z: int,
    x: int,
    y: int,
    settings: Settings,
    *,
    cog_index: int = 0,
    sign: bool = True,
) -> Response:
    """Proxy a tile for single-file COG sources (NAIP, Sentinel-2, USGS Topo).

    ``cog_index`` selects which COG to render: 0 = primary (``cog_url``),
    1+ = ``additional_cog_urls[cog_index - 1]`` (mosaic components).
    ``sign`` controls Planetary Computer SAS signing (False for public URLs).
    """
    if cog_index == 0:
        source_url = snap.cog_url
    else:
        extras = snap.additional_cog_urls or []
        if cog_index - 1 >= len(extras):
            raise HTTPException(status_code=404, detail="cog index out of range")
        source_url = extras[cog_index - 1]

    if sign:
        try:
            signed_url = await stac_service.sign_pc_url(
                source_url, wait_budget=stac_service.SIGN_WAIT_REQUEST
            )
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            # Never fall back to the unsigned href: Planetary Computer's blob
            # storage is private, so an unsigned read is rejected with a 409
            # that Titiler surfaces as a 500 and the user sees as a broken
            # tile. sign_pc_url has already retried 429s within the request
            # wait budget, so a failure here is terminal for this request —
            # 502 it while the client is still listening, and let it retry the
            # tile against a signer that may have recovered.
            logger.warning(
                "Tile signing failed after retries",
                extra={"snapshot_id": str(snap.id), "source": snap.source, "error": str(exc)},
                exc_info=exc,
            )
            raise HTTPException(
                status_code=502, detail="Could not sign imagery for this tile"
            ) from exc
    else:
        signed_url = source_url

    band_params = _COG_PARAMS.get(snap.source, {"bidx": [1, 2, 3], "rescale": "0,255"})
    params: dict[str, Any] = {"url": signed_url, **band_params}
    titiler_url = f"{settings.titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
    return await _fetch_titiler(titiler_url, params, snap.id)


# Fallback granularity when the token's own expiry is unavailable. Shorter
# than the ~25 min of margin a cached token is guaranteed to have left
# (~45 min lifetime less the 20 min _SAS_CACHE_TTL holds it).
_STAC_URL_BUCKET_S = 600


async def _landsat_stac_url(snapshot_id: uuid.UUID, settings: Settings) -> str:
    """Build the STAC callback URL Titiler fetches for a Landsat snapshot.

    ``v`` is the expiry of the container token ``get_signed_stac_item`` will
    embed in the band hrefs, so the URL — which is what Titiler keys its item
    cache on — changes exactly when the token it pins does. A constant URL let
    Titiler serve an item whose token had expired, which GDAL reports as an
    unsupported format and Titiler as a 500.

    Never raises: this computes a cache key, and a signer or Redis that is
    down must not fail a tile the callback could still serve. The callback
    signs freshly and 502s honestly if it cannot.
    """
    version: str | None = None
    try:
        version = await stac_service.container_token_expiry(
            *stac_service.LANDSAT_BLOB_CONTAINER,
            wait_budget=stac_service.SIGN_WAIT_REQUEST,
        )
    except (httpx.RequestError, httpx.HTTPStatusError, RedisError, OSError) as exc:
        logger.warning(
            "Landsat SAS token expiry unavailable; falling back to a time bucket",
            extra={"snapshot_id": str(snapshot_id), "error": str(exc)},
        )

    if version is None:
        version = f"t{int(time.time()) // _STAC_URL_BUCKET_S}"

    base = f"{settings.api_internal_url}/api/v1/imagery/{snapshot_id}/stac"
    return f"{base}?{urlencode({'v': version})}"


async def _proxy_landsat_tile(
    snap: ImagerySnapshotRow,
    z: int,
    x: int,
    y: int,
    settings: Settings,
) -> Response:
    """Proxy a Landsat tile via Titiler's STAC endpoint for RGB compositing.

    Landsat bands are separate single-band COGs, so we point Titiler at our
    ``/imagery/{id}/stac`` endpoint which serves the STAC item JSON with
    freshly signed asset URLs.  Titiler reads the red/green/blue COGs and
    composites them into a single RGB tile.
    """
    stac_item_url = await _landsat_stac_url(snap.id, settings)
    # Landsat C2 L2 surface reflectance: uint16, nodata=0,
    # scale=2.75e-05, offset=-0.2.  Typical land DNs are 7000–20000.
    # rescale 7000,14000 gives good contrast for most land surfaces.
    params: dict[str, Any] = {
        "url": stac_item_url,
        "assets": ["red", "green", "blue"],
        "asset_as_band": True,
        "nodata": 0,
        "rescale": ["7000,14000", "7000,14000", "7000,14000"],
    }
    titiler_url = f"{settings.titiler_url}/stac/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
    return await _fetch_titiler(titiler_url, params, snap.id)


@router.get(
    "/imagery/{snapshot_id}/tiles/{z}/{x}/{y}",
    summary="Proxy a tile through Titiler with fresh signed URLs",
    description=(
        "Routes to Titiler's COG or STAC tile endpoint depending on the "
        "imagery source. SAS tokens are generated at request time so they "
        "never expire in the browser's tile URL template."
    ),
    responses={
        404: {"description": "Snapshot not found"},
        502: {"description": "Titiler upstream error"},
    },
)
async def proxy_imagery_tile(
    snapshot_id: uuid.UUID,
    z: int = Path(ge=0, le=_MAX_ZOOM, description="Web Mercator zoom level"),
    x: int = Path(ge=0, le=_MAX_TILE_INDEX, description="Tile column"),
    y: int = Path(ge=0, le=_MAX_TILE_INDEX, description="Tile row"),
    cog: int = Query(default=0, ge=0, description="Mosaic tile index (0 = primary)"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Dispatch to the correct Titiler endpoint based on imagery source."""
    snap = _get_cached_snapshot(snapshot_id)
    if snap is None:
        snap = await run_in_threadpool(imagery_service.get_snapshot_by_id, db, snapshot_id)
        if not snap:
            raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
        _put_cached_snapshot(snapshot_id, snap)
    db.close()

    if snap.source == "landsat":
        return await _proxy_landsat_tile(snap, z, x, y, settings)
    if snap.source == "usgs_topo":
        return await _proxy_cog_tile(snap, z, x, y, settings, cog_index=cog, sign=False)
    return await _proxy_cog_tile(snap, z, x, y, settings, cog_index=cog)


@router.post(
    "/imagery/{snapshot_id}/warmup",
    status_code=204,
    summary="Pre-warm Titiler's GDAL cache for a COG",
    description=(
        "Fires a lightweight /cog/info request to Titiler so it reads the "
        "COG header before tile requests arrive. Best-effort; failures are "
        "silently ignored."
    ),
    responses={
        204: {"description": "Warmup initiated (or skipped)"},
        429: {"description": "Rate limit exceeded"},
    },
    # Unauthenticated and expensive: each call makes Titiler read a COG
    # header (and, for Landsat, fetch a STAC item and sign three bands).
    # Stingier than the tile proxy because the client warms a snapshot once
    # per session, where tiles are dozens per pan. Not stingier than that: a
    # carrier NAT or an office egress puts many visitors in one bucket, and
    # refusing a warmup costs the real one a slow first tile.
    dependencies=[Depends(RateLimit(times=60, seconds=60))],
)
async def warmup_cog(
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Pre-warm Titiler's GDAL cache for faster first-tile rendering."""
    snap = _get_cached_snapshot(snapshot_id)
    if snap is None:
        snap = await run_in_threadpool(imagery_service.get_snapshot_by_id, db, snapshot_id)
        if snap:
            _put_cached_snapshot(snapshot_id, snap)
    db.close()

    if not snap:
        return Response(status_code=204)

    try:
        if snap.source == "landsat":
            stac_url = await _landsat_stac_url(snap.id, settings)
            await _get_titiler_client().get(
                f"{settings.titiler_url}/stac/info",
                params={"url": stac_url, "assets": ["red", "green", "blue"]},
            )
        else:
            source_url = snap.cog_url
            if snap.source != "usgs_topo":
                try:
                    source_url = await stac_service.sign_pc_url(
                        source_url, wait_budget=stac_service.SIGN_WAIT_REQUEST
                    )
                except (httpx.RequestError, httpx.HTTPStatusError):
                    # Warming with an unsigned href only teaches Titiler's
                    # cache a 409. Skip the warmup; the tile request will
                    # sign again (and 502 honestly if that fails too).
                    logger.info(
                        "Skipping warmup — signing failed",
                        extra={"snapshot_id": str(snap.id)},
                    )
                    return Response(status_code=204)
            await _get_titiler_client().get(
                f"{settings.titiler_url}/cog/info",
                params={"url": source_url},
            )
    except (httpx.RequestError, httpx.HTTPStatusError):
        pass

    return Response(status_code=204)


# Stop caching this far before the embedded token dies, and never advertise
# more than this, so a cached copy always has usable life left.
_STAC_CACHE_MARGIN_S = 300
_STAC_CACHE_MAX_AGE_S = 900


def _stac_cache_control(assets: dict[str, Any], bands: list[str]) -> str:
    """Freshness for a signed STAC item, bounded by its own token's expiry.

    The response carried no freshness headers at all, which lets any
    intermediate cache apply heuristic freshness to a document that goes stale
    the moment its SAS token expires.
    """
    if not bands:
        return "no-store"

    expiry = stac_service.token_expiry_seconds(assets[bands[0]]["href"])
    if expiry is None:
        return "no-store"

    max_age = min(int(expiry - time.time()) - _STAC_CACHE_MARGIN_S, _STAC_CACHE_MAX_AGE_S)
    if max_age <= 0:
        return "no-store"
    return f"private, max-age={max_age}"


@router.get(
    "/imagery/{snapshot_id}/stac",
    response_class=Response,
    summary="Return a STAC item with signed asset URLs (for Titiler STACReader)",
    description=(
        "Fetches the original STAC item JSON from Planetary Computer and signs "
        "the red, green, and blue band asset hrefs. Titiler calls this endpoint "
        "when serving Landsat tiles via /stac/tiles/."
    ),
    responses={
        404: {"description": "Snapshot not found or not a STAC-tile source"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Failed to fetch STAC item from upstream"},
    },
    # Deliberately generous. In production every legitimate call arrives from
    # Titiler's single egress IP, so this is one shared bucket for all users
    # at once, not a per-visitor budget — a tight limit here would throttle
    # real tile serving under load, not abuse. It bounds an anonymous caller
    # who fans out to Planetary Computer and the SAS signer; distinguishing
    # Titiler from the public properly needs a shared secret, not a counter.
    dependencies=[Depends(RateLimit(times=600, seconds=60))],
)
async def get_signed_stac_item(
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Serve a Landsat STAC item with freshly signed band URLs."""
    snap = await run_in_threadpool(imagery_service.get_snapshot_by_id, db, snapshot_id)
    if not snap or snap.source != "landsat":
        raise HTTPException(status_code=404, detail="Not found or not a STAC-tile source")

    # Release the DB connection before outbound HTTP calls
    db.close()

    # Try Redis cache for the raw (unsigned) STAC item JSON.
    # The item metadata is immutable; only band URLs need fresh signing.
    from app.db import get_async_redis

    cache_key = f"stac:{snapshot_id}"
    stac_item = None

    try:
        cached = await get_async_redis().get(cache_key)
        if cached:
            stac_item = json.loads(cached)
    except (RedisError, OSError) as exc:
        logger.debug("STAC item cache read failed: %s", exc)

    if stac_item is None:
        if not _is_allowed_stac_host(snap.cog_url):
            logger.error(
                "Refusing STAC fetch to a non-allowlisted host",
                extra={"snapshot_id": str(snapshot_id), "url": snap.cog_url},
            )
            raise HTTPException(status_code=502, detail="Failed to fetch STAC item")

        # Fetch the original STAC item from Planetary Computer
        try:
            resp = await _get_stac_fetch_client().get(snap.cog_url)
            resp.raise_for_status()
            stac_item = resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error("Failed to fetch STAC item from %s", snap.cog_url, exc_info=exc)
            raise HTTPException(status_code=502, detail="Failed to fetch STAC item") from exc

        # Cache the raw item (before signing) for 1 hour
        try:
            await get_async_redis().setex(cache_key, 3600, json.dumps(stac_item))
        except (RedisError, OSError) as exc:
            logger.debug("STAC item cache write failed: %s", exc)

    # Sign the band assets Titiler will read (concurrently). A band that
    # cannot be signed fails the whole item: its unsigned href is a private
    # blob URL, so serving it hands Titiler a guaranteed 409 — the shape the
    # 2026-08 ops audit traced from 12 band-signing failures to 37 Titiler
    # 500s. sign_pc_url has already retried 429s, so this is terminal.
    #
    # Request profile, and load-bearing: Titiler calls this endpoint from
    # inside its own tile render, so any sleep here is spent inside the
    # browser's tile deadline.
    assets = stac_item.get("assets", {})
    bands = [b for b in ("red", "green", "blue") if b in assets and "href" in assets[b]]
    sign_results = await asyncio.gather(
        *(
            stac_service.sign_pc_url(assets[b]["href"], wait_budget=stac_service.SIGN_WAIT_REQUEST)
            for b in bands
        ),
        return_exceptions=True,
    )
    failed_bands = [
        b for b, r in zip(bands, sign_results, strict=True) if isinstance(r, BaseException)
    ]
    if failed_bands:
        first_error = next(r for r in sign_results if isinstance(r, BaseException))
        logger.error(
            "Band signing failed after retries",
            extra={
                "bands": failed_bands,
                "snapshot_id": str(snapshot_id),
                "error": str(first_error),
            },
            exc_info=first_error,
        )
        raise HTTPException(status_code=502, detail="Could not sign imagery for this snapshot")

    for band, result in zip(bands, sign_results, strict=True):
        assets[band]["href"] = result

    return Response(
        content=json.dumps(stac_item),
        media_type="application/geo+json",
        headers={"Cache-Control": _stac_cache_control(assets, bands)},
    )
