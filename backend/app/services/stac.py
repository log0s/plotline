"""Planetary Computer imagery: search, signing, spatial filtering, selection.

More than a client. Alongside the STAC search and the two-tier SAS signing,
this module owns the decisions the imagery pipeline makes about what to
serve: which items actually cover the parcel (tested against the footprint,
not the bbox envelope), which item represents each period for each source,
which asset to read, and whether the chosen item is servable at all.
``tasks/timeline.py`` orchestrates the sources; the rules live here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
from shapely.geometry import Point
from shapely.ops import transform

logger = logging.getLogger(__name__)

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
PC_TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token"

# Resolution in metres per source
RESOLUTION_M: dict[str, float] = {
    "naip": 1.0,
    "landsat-c2-l2": 30.0,
    "sentinel-2-l2a": 10.0,
}


# ── Bounding box ───────────────────────────────────────────────────────────────


def get_utm_epsg(lng: float, lat: float) -> int:
    """Return the UTM zone EPSG code for a given WGS-84 coordinate."""
    # lng=180 would otherwise yield zone 61 → EPSG 32661, which is UPS
    # North (polar stereographic), not a UTM zone.
    zone = min(60, max(1, int((lng + 180) / 6) + 1))
    return 32600 + zone if lat >= 0 else 32700 + zone


def point_to_bbox(
    lat: float,
    lng: float,
    buffer_m: float = 500,
) -> tuple[float, float, float, float]:
    """Create a bounding box around a point.

    Args:
        lat: Latitude (WGS-84).
        lng: Longitude (WGS-84).
        buffer_m: Buffer radius in metres.

    Returns:
        (west, south, east, north) bounding box in WGS-84 degrees.
    """
    import pyproj

    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS(f"EPSG:{get_utm_epsg(lng, lat)}")

    to_utm = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
    to_wgs = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True).transform

    point_utm = transform(to_utm, Point(lng, lat))
    buffer_wgs = transform(to_wgs, point_utm.buffer(buffer_m))

    bounds = buffer_wgs.bounds  # (minx, miny, maxx, maxy)
    return (bounds[0], bounds[1], bounds[2], bounds[3])


# ── STAC search ───────────────────────────────────────────────────────────────


# Clients are keyed by event loop: the Celery worker runs every task in
# its own asyncio.run() loop (possibly concurrently under a threaded
# pool), and httpx clients are loop-affine — sharing one across loops
# corrupts its connection pool, and one task's cleanup would close a
# client another task is still using.
_search_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}
_sign_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _get_search_client() -> httpx.AsyncClient:
    """Pooled client for STAC searches, one per running event loop.

    timeline.py issues 41 sequential year-chunk searches per parcel for
    Landsat alone; per-call client construction would mean 41 fresh TLS
    handshakes. Pooling reuses the connection.
    """
    loop = asyncio.get_running_loop()
    client = _search_clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        _search_clients[loop] = client
    return client


async def search_stac(
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_items: int = 50,
    query: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Search a STAC collection for items intersecting a bounding box.

    Args:
        collection: STAC collection ID (e.g. "naip").
        bbox: (west, south, east, north) in WGS-84.
        datetime_range: ISO 8601 interval string, e.g. "2003-01-01/2024-12-31".
        max_items: Maximum items to return (hard cap at 500).
        query: Additional property filters, e.g. {"eo:cloud_cover": {"lt": 20}}.

    Returns:
        List of GeoJSON Feature dicts (STAC items).
    """
    max_items = min(max_items, 500)

    payload: dict[str, object] = {
        "collections": [collection],
        "bbox": list(bbox),
        "datetime": datetime_range,
        "limit": min(max_items, 100),
    }
    if query:
        payload["query"] = query

    items: list[dict[str, object]] = []
    client = _get_search_client()

    resp = await client.post(f"{STAC_API}/search", json=payload)
    resp.raise_for_status()
    data = resp.json()
    items.extend(data.get("features", []))

    while len(items) < max_items:
        next_link = next(
            (lnk for lnk in data.get("links", []) if lnk.get("rel") == "next"),
            None,
        )
        if not next_link:
            break
        # POST-search pagination carries the continuation token in the link
        # body and must be re-POSTed — Planetary Computer returns
        # {"method": "POST", "body": {...original search + token...}}.
        # A GET on the href would run an unfiltered default search.
        if str(next_link.get("method", "GET")).upper() == "POST":
            body = next_link.get("body")
            next_payload = body if isinstance(body, dict) and body else payload
            if next_link.get("merge"):
                next_payload = {**payload, **next_payload}
            resp = await client.post(next_link["href"], json=next_payload)
        else:
            resp = await client.get(next_link["href"])
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("features", []))

    return items[:max_items]


# ── URL signing ───────────────────────────────────────────────────────────────


# Per-URL signed hrefs (``sas:{url}``) are cached for a fixed span; it is also
# the fallback for a container token whose own ``se`` will not parse. 1200 s is
# inherited, not derived: 9ea33d9 set 600 s against a believed ~30 min token
# life, and 3b7b10e doubled it when the life was measured at 45 min. Container
# tokens no longer use it — see _container_token_ttl.
_SAS_CACHE_TTL = 1200

# Stop serving a cached container token this long before it dies.
#
# What has to fit inside the margin is the longest path from *issuing* a signed
# URL to *reading* the blob, because the token has only this much life left
# when the cache entry rotates. Every such path is a single request:
#   - Tile: the /stac callback signs, Titiler's GDAL reads the blob in the same
#     render. Bounded by the 30 s Titiler client timeout (imagery.py:324).
#   - Titiler's item LRU has no expiry, but its key carries ``?v={se}``, so a
#     cached item stops being addressed the moment this entry rotates — plus
#     one in-flight render.
#   - The /stac Cache-Control is already capped at the token's own remaining
#     life less 300 s (imagery.py:672-695), so an intermediate cache cannot
#     extend a token past its expiry either. Self-bounding, not a constraint.
#   - Worker validation and the preview renderer sign and then immediately
#     HEAD/GET, inside a 10 s client timeout.
# 300 s is ~10× the longest of those and matches _STAC_CACHE_MARGIN_S. No
# constraint found that needs the ~25 min the fixed 1200 s TTL used to leave.
_SAS_TOKEN_MARGIN_S = 300

# How long a caller is willing to spend *sleeping* between signing retries.
#
# The batch profile is the worker's: validation runs behind no user, and
# honouring a 60 s Retry-After is exactly right there — waiting beats reading a
# rate-limit reply as "this asset is broken" and dropping the year.
#
# The request profile is for anything inside an HTTP request. The tile path's
# end-to-end budget is ~30 s (the frontend's AbortSignal plus the Titiler proxy
# timeout), so a 60 s backoff cannot help it — it converts a 429 into a client
# timeout and a 502 with no message. In production on 2026-08-12 a Landsat
# scrub burst did exactly that: 23 backoffs, one of them 54 s, and a 502 storm
# while Titiler itself stayed healthy. With a 2 s budget the same 429 raises in
# ~3 s and the route answers with its curated message instead.
SIGN_WAIT_BATCH = 60.0
SIGN_WAIT_REQUEST = 2.0

_BLOB_HOST_SUFFIX = ".blob.core.windows.net"

# The one container every landsat-c2-l2 band asset lives in. The Landsat tile
# path holds only the STAC item self-link, never a blob href, so the container
# cannot be derived there without the item fetch that path is trying to avoid.
LANDSAT_BLOB_CONTAINER = ("landsateuwest", "landsat-c2")


def _get_sign_client() -> httpx.AsyncClient:
    """Pooled client (per event loop) so parallel signs share TLS connections."""
    loop = asyncio.get_running_loop()
    client = _sign_clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        _sign_clients[loop] = client
    return client


async def close_clients() -> None:
    """Close this event loop's STAC HTTP clients and release connections."""
    loop = asyncio.get_running_loop()
    search = _search_clients.pop(loop, None)
    if search is not None:
        await search.aclose()
    sign = _sign_clients.pop(loop, None)
    if sign is not None:
        await sign.aclose()
    _sign_semaphores.pop(loop, None)
    _token_flights.pop(loop, None)


# Semaphores are keyed by event loop for the same reason the clients are:
# asyncio.Semaphore binds to the loop that first awaits it and raises
# "is bound to a different event loop" from any other, so a single
# module-level instance would break the second Celery task in a worker.
_sign_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _get_sign_semaphore() -> asyncio.Semaphore:
    """Bound concurrent calls to the PC SAS signing endpoint, per event loop."""
    loop = asyncio.get_running_loop()
    sem = _sign_semaphores.get(loop)
    if sem is None:
        from app.config import get_settings

        sem = asyncio.Semaphore(max(1, get_settings().pc_signing_concurrency))
        _sign_semaphores[loop] = sem
    return sem


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a Retry-After header (delta-seconds form) into seconds."""
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        # HTTP-date form: rare from PC, and a bad parse should fall back to
        # the caller's exponential backoff rather than raise.
        return None


async def _sas_get(
    url: str,
    params: dict[str, str] | None,
    *,
    wait_budget: float,
) -> httpx.Response:
    """GET a SAS API endpoint, retrying 429s within a bounded sleep budget.

    The signing API rate-limits blanket across the account, so a 429 means
    "slow down", not "this asset is broken" — retrying here keeps
    validate_landsat_item from failing an item (and burning its fallbacks
    against the same limit) over a transient burst.

    ``wait_budget`` caps the *total* time spent sleeping across retries. A
    backoff that would overshoot it is not taken: the last 429 is raised
    instead, so a caller with a deadline fails fast enough to say why rather
    than being killed mid-sleep by its own timeout. See ``SIGN_WAIT_BATCH`` /
    ``SIGN_WAIT_REQUEST``.
    """
    from app.config import get_settings

    attempts = max(1, get_settings().pc_signing_attempts)
    delay = 1.0
    spent = 0.0
    last_exc: httpx.HTTPStatusError | None = None

    for attempt in range(attempts):
        async with _get_sign_semaphore():
            resp = await _get_sign_client().get(url, params=params)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
            retry_after = _retry_after_seconds(resp)

        if attempt == attempts - 1:
            break

        wait = retry_after if retry_after is not None else delay
        if spent + wait > wait_budget:
            logger.info(
                "SAS rate-limited; backoff exceeds wait budget, giving up",
                extra={"attempt": attempt + 1, "wait_s": wait, "budget_s": wait_budget},
            )
            break

        # Sleep outside the semaphore: holding a slot while backing off
        # would idle the limiter instead of letting other callers through.
        logger.info(
            "SAS rate-limited; backing off",
            extra={"attempt": attempt + 1, "wait_s": wait},
        )
        await asyncio.sleep(wait)
        spent += wait
        delay *= 2

    assert last_exc is not None  # only reached after a 429 on every attempt
    raise last_exc


def _blob_container(url: str) -> tuple[str, str] | None:
    """Split a PC blob asset URL into (storage account, container), or None.

    Returns None for anything that is not an Azure blob href — the data-API
    preview URLs, USGS S3 hrefs — which must go through per-URL signing (or
    no signing at all) rather than a container token.
    """
    parts = urlsplit(url)
    host, _, _ = parts.netloc.partition(":")
    if not host.endswith(_BLOB_HOST_SUFFIX):
        return None
    account = host[: -len(_BLOB_HOST_SUFFIX)]
    container = parts.path.lstrip("/").split("/", 1)[0]
    if not account or not container:
        return None
    return account, container


# One in-flight mint per container, per event loop.
#
# Keyed by event loop for the same reason the semaphores are (see
# _get_sign_semaphore): a Task binds to the loop that created it, so a single
# module-level dict of tasks would break the second Celery task in a worker.
_token_flights: dict[asyncio.AbstractEventLoop, dict[str, asyncio.Task[str]]] = {}


async def _cached_container_token(cache_key: str) -> str | None:
    """Read a container token out of Redis, or None on a miss or a dead cache."""
    from redis.exceptions import RedisError

    from app.db import get_async_redis

    try:
        cached = await get_async_redis().get(cache_key)
    except (RedisError, OSError) as exc:
        logger.debug("SAS token cache read failed: %s", exc)
        return None
    if not cached:
        return None
    return cached.decode() if isinstance(cached, bytes) else cached


async def _mint_container_token(
    account: str, container: str, cache_key: str, *, wait_budget: float
) -> str:
    """Mint one container token from PC and cache it. One caller at a time."""
    from redis.exceptions import RedisError

    from app.db import get_async_redis

    # Logged per mint, not per cache write: this line is the G7 instrument, and
    # its whole point is that duplicate mints at a token boundary each appear.
    # Under the single-flight above it now fires once per cold miss.
    started = time.monotonic()
    resp = await _sas_get(f"{PC_TOKEN_URL}/{account}/{container}", None, wait_budget=wait_budget)
    token = str(resp.json()["token"])
    logger.info(
        "SAS container token minted container=%s se=%s ms=%d",
        f"{account}/{container}",
        _token_expiry(token),
        round((time.monotonic() - started) * 1000),
    )

    ttl = _container_token_ttl(token)
    if ttl > 0:
        try:
            await get_async_redis().setex(cache_key, ttl, token.encode())
        except (RedisError, OSError) as exc:
            logger.debug("SAS token cache write failed: %s", exc)

    return token


async def _container_token(account: str, container: str, *, wait_budget: float) -> str:
    """Return a cached SAS token granting read over one PC blob container.

    Planetary Computer issues container-scoped tokens (``sr=c``) valid for
    ~45 minutes, and one PC collection maps to one container — so a single
    token signs every asset of a collection instead of one signing call per
    URL. This is what keeps the signing endpoint far from its rate limit;
    the semaphore and the 429 retry above are the belt to this braces.

    Concurrent misses coalesce onto one mint. The seam is here, below the
    per-request band gather, because a single request is already concurrent
    with itself: the ``/stac`` callback signs three bands with
    ``asyncio.gather``, and on 2026-08-12 one such callback minted three
    tokens. Coalescing anywhere above the gather would not have caught that.

    The bound is one mint per process per container per boundary, not one
    globally — two API machines can still mint two. Deliberate: a Redis
    ``SET NX`` lock would add a poll loop and a Redis-down failure mode to the
    cold path to remove a second mint that measured harmless (13 concurrent
    mints on ``sentinel2-l2`` drew no 429s;
    docs/audits/2026-08-titiler-cache/BOUNDARY-BASELINE.md §3).

    A follower inherits the leader's ``wait_budget``. Harmless because
    processes are budget-homogeneous — every API call site passes
    ``SIGN_WAIT_REQUEST``, the worker and the offline preview renderer pass
    ``SIGN_WAIT_BATCH`` — so a 2 s-budget request cannot end up waiting on a
    60 s-budget mint. Mixing budgets in one process would break that.
    """
    cache_key = f"sas-token:{account}/{container}"
    cached = await _cached_container_token(cache_key)
    if cached:
        return cached

    loop = asyncio.get_running_loop()
    flights = _token_flights.setdefault(loop, {})
    flight = flights.get(cache_key)
    if flight is None:
        flight = loop.create_task(
            _mint_container_token(account, container, cache_key, wait_budget=wait_budget)
        )
        flights[cache_key] = flight
        flight.add_done_callback(lambda _t: flights.pop(cache_key, None))

    # Shielded: a follower that gives up — client disconnect, its own timeout —
    # must not cancel the mint every other follower is waiting on.
    return await asyncio.shield(flight)


def _token_expiry(token: str) -> str | None:
    """Return a SAS token query string's ``se`` (expiry) field, if it has one."""
    values = parse_qs(token).get("se")
    return values[0] if values else None


def _expiry_timestamp(expiry: str | None) -> float | None:
    """Parse an ``se`` field into a POSIX timestamp, or None if unusable."""
    if expiry is None:
        return None
    try:
        return datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def token_expiry_seconds(signed_url: str) -> float | None:
    """Return a signed URL's SAS expiry as a POSIX timestamp, or None."""
    return _expiry_timestamp(_token_expiry(urlsplit(signed_url).query))


def _container_token_ttl(token: str) -> int:
    """Seconds to cache a container token: its own life, less the margin.

    Deriving the TTL from the token instead of a fixed 1200 s is what keeps the
    cache entry and the credential on the same clock. The fixed span expired
    the key ~25 min before the token it held, so ``?v`` — which names that key —
    rotated every 20 min against a 45-minute credential, and every Landsat
    ``/stac`` cache key rotated together each time (BOUNDARY-BASELINE.md §1).
    Rotations now fall roughly 40 min apart, ~2.25× less often.

    A token whose ``se`` will not parse falls back to the fixed TTL; one with
    less than the margin left is not cached at all, so the next caller mints
    rather than inheriting a token that could die mid-render.
    """
    expiry = _expiry_timestamp(_token_expiry(token))
    if expiry is None:
        return _SAS_CACHE_TTL
    return int(expiry - time.time()) - _SAS_TOKEN_MARGIN_S


async def container_token_expiry(account: str, container: str, *, wait_budget: float) -> str | None:
    """Return the expiry of the container token this process would sign with.

    Callers use it to version a URL against the token it will carry, so a
    cache keyed on that URL cannot outlive the token. It reads the same Redis
    key ``_container_token`` populates, so it costs one GET on the warm path.
    """
    token = await _container_token(account, container, wait_budget=wait_budget)
    return _token_expiry(token)


async def _request_signature(url: str, *, wait_budget: float) -> str:
    """Sign a single URL through the per-URL SAS endpoint."""
    resp = await _sas_get(PC_SIGN_URL, {"href": url}, wait_budget=wait_budget)
    return str(resp.json()["href"])


async def sign_pc_url(url: str, *, wait_budget: float = SIGN_WAIT_BATCH) -> str:
    """Sign a Planetary Computer asset URL for authenticated access.

    Blob assets are signed by appending a container-scoped token (see
    ``_container_token``); anything else falls back to the per-URL signing
    endpoint. Both are cached in Redis for ``_SAS_CACHE_TTL``.

    Concurrency against the SAS API is capped (see ``_get_sign_semaphore``)
    and 429s are retried with backoff. Both live here rather than at the call
    sites so every path that signs — validation, tile serving, thumbnails,
    preview rendering — shares one limiter. ``wait_budget`` is the one thing
    the call site must choose: pass ``SIGN_WAIT_REQUEST`` from anything
    serving an HTTP request, ``SIGN_WAIT_BATCH`` (the default) from the
    worker and offline scripts.
    """
    from redis.exceptions import RedisError

    from app.db import get_async_redis

    blob = _blob_container(url)
    if blob is not None:
        token = await _container_token(*blob, wait_budget=wait_budget)
        return f"{url}{'&' if '?' in url else '?'}{token}"

    cache_key = f"sas:{url}"
    redis = get_async_redis()
    try:
        cached = await redis.get(cache_key)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    except (RedisError, OSError) as exc:
        logger.debug("SAS cache read failed: %s", exc)

    signed = await _request_signature(url, wait_budget=wait_budget)

    try:
        await redis.setex(cache_key, _SAS_CACHE_TTL, signed.encode())
    except (RedisError, OSError) as exc:
        logger.debug("SAS cache write failed: %s", exc)

    return signed


# ── Spatial filtering ─────────────────────────────────────────────────────────


def filter_items_containing_point(
    items: list[dict[str, object]],
    lat: float,
    lng: float,
) -> list[dict[str, object]]:
    """Keep only STAC items whose *footprint* contains the given point.

    Called by the Landsat and Sentinel-2 paths (timeline.py), whose searches
    use a buffered bbox and so return scenes that merely intersect the search
    area. Containment is tested against ``item["geometry"]``, not the bbox:
    a STAC bbox is the envelope of the geometry, so for a rotated WRS-2
    parallelogram or a part-filled MGRS quarter it overstates coverage and
    admits granules whose real footprint excludes the address. The 2026-08
    geometry audit measured 33 such rows — 29 Landsat, 4 S2 — serving a
    scene that does not contain the parcel.

    Items with no usable geometry fall back to the bbox test. An item is
    never rejected merely for lacking geometry: the audit found 17 rows
    whose items PC would not serve at all, and a missing field is not
    evidence of missing coverage.
    """
    from shapely.geometry import shape

    point = Point(lng, lat)
    result = []
    for item in items:
        geometry = item.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type"):
            try:
                if shape(geometry).contains(point):
                    result.append(item)
                continue
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                logger.debug(
                    "Unparseable STAC geometry; falling back to bbox",
                    extra={"item_id": item.get("id"), "error": str(exc)},
                )
        else:
            logger.debug(
                "STAC item has no geometry; falling back to bbox",
                extra={"item_id": item.get("id")},
            )

        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            result.append(item)  # no bbox either — keep it, can't verify
            continue
        w, s, e, n = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        if w <= lng <= e and s <= lat <= n:
            result.append(item)
    return result


def filter_groups_containing_point(
    groups: list[list[dict[str, object]]],
    lat: float,
    lng: float,
) -> tuple[list[list[dict[str, object]]], list[list[dict[str, object]]]]:
    """Split selected mosaic groups into (covering, non-covering).

    The NAIP path selects tiles by how much of the *viewport* they cover and
    never asks whether any of them covers the address. When a year has no
    covering tile in the collection, that optimises happily over the nearest
    neighbours: the 2026-08 audit found both 350 5th Ave parcels served a
    2023 mosaic composed entirely of New Jersey quads for a Midtown
    Manhattan address, because PC has no covering 2023 tile at all.

    A group survives only if at least one of its tiles contains the point.
    The caller suppresses the rest — a missing year is honest, the wrong
    state is not.
    """
    covering: list[list[dict[str, object]]] = []
    missing: list[list[dict[str, object]]] = []
    for group in groups:
        if group and filter_items_containing_point(group, lat, lng):
            covering.append(group)
        elif group:
            missing.append(group)
    return covering, missing


def _bbox_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Area of the intersection of two (w, s, e, n) bboxes in degree² units."""
    w = max(a[0], b[0])
    s = max(a[1], b[1])
    e = min(a[2], b[2])
    n = min(a[3], b[3])
    if e <= w or n <= s:
        return 0.0
    return (e - w) * (n - s)


def filter_items_intersecting_bbox(
    items: list[dict[str, object]],
    viewport: tuple[float, float, float, float],
) -> list[dict[str, object]]:
    """Keep STAC items whose bbox intersects the given viewport.

    Looser than ``filter_items_containing_point`` — useful for NAIP where
    small tiles may cover only part of the display viewport but are still
    worth ingesting as mosaic components.
    """
    result = []
    for item in items:
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) < 4:
            result.append(item)
            continue
        item_bbox = (
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )
        if _bbox_intersection_area(item_bbox, viewport) > 0:
            result.append(item)
    return result


# ── Item selection (deduplication per time period) ────────────────────────────


def _capture_date(item: dict[str, object]) -> date:
    props = cast(dict[str, object], item["properties"])
    dt_str = str(props["datetime"])
    return date.fromisoformat(dt_str[:10])


def _has_capture_date(item: dict[str, object]) -> bool:
    """True if the item carries a parseable properties.datetime.

    STAC allows ``"datetime": null`` — such items would crash the selectors,
    so they're filtered out up front.
    """
    props = item.get("properties")
    if not isinstance(props, dict):
        return False
    dt = props.get("datetime")
    if not isinstance(dt, str) or len(dt) < 10:
        return False
    try:
        date.fromisoformat(dt[:10])
    except ValueError:
        return False
    return True


def _cloud_cover(item: dict[str, object]) -> float:
    """eo:cloud_cover with missing or null treated as fully cloudy."""
    val = cast(dict[str, Any], item["properties"]).get("eo:cloud_cover")
    return float(cast(float, val)) if val is not None else 100.0


def _doy(item: dict[str, object]) -> int:
    return _capture_date(item).timetuple().tm_yday


def select_naip_items(
    items: list[dict[str, object]],
    viewport: tuple[float, float, float, float] | None = None,
    *,
    max_tiles_per_year: int = 3,
    coverage_target: float = 0.95,
) -> list[list[dict[str, object]]]:
    """Select NAIP tiles per year, grouped as mosaics.

    Returns a list of groups, one per year. Each group contains 1 to
    ``max_tiles_per_year`` tiles selected greedily to maximise coverage of
    the supplied ``viewport`` bbox. If ``viewport`` is None, falls back to
    a single tile per year closest to mid-summer (legacy behaviour).

    Within a year, the first tile is the one with the largest viewport
    overlap (tie-broken by proximity to mid-summer, day 196 ≈ July 15).
    Subsequent tiles are added only if they cover a portion of the
    viewport not yet covered by already-selected tiles, and up to
    ``coverage_target`` fraction of the viewport is covered.
    """
    target_doy = 196
    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        if not _has_capture_date(item):
            continue
        by_year[_capture_date(item).year].append(item)

    groups: list[list[dict[str, object]]] = []

    for year in sorted(by_year.keys()):
        year_items = by_year[year]

        if viewport is None:
            # Legacy single-tile behaviour
            pick = min(year_items, key=lambda i: abs(_doy(i) - target_doy))
            groups.append([pick])
            continue

        viewport_area = (viewport[2] - viewport[0]) * (viewport[3] - viewport[1])
        if viewport_area <= 0:
            pick = min(year_items, key=lambda i: abs(_doy(i) - target_doy))
            groups.append([pick])
            continue

        # Greedy: pick tile with best remaining-viewport coverage, breaking
        # ties by proximity to mid-summer.
        remaining = viewport
        selected_for_year: list[dict[str, object]] = []
        candidates = list(year_items)

        while candidates and len(selected_for_year) < max_tiles_per_year:

            def score(
                item: dict[str, object],
                _remaining: tuple[float, float, float, float] = remaining,
            ) -> tuple[float, float]:
                bbox = item.get("bbox")
                if not isinstance(bbox, list) or len(bbox) < 4:
                    return (0.0, float(abs(_doy(item) - target_doy)))
                ib = (
                    float(bbox[0]),
                    float(bbox[1]),
                    float(bbox[2]),
                    float(bbox[3]),
                )
                area = _bbox_intersection_area(ib, _remaining)
                # Maximize area, minimize doy distance
                return (-area, float(abs(_doy(item) - target_doy)))

            best = min(candidates, key=score)
            best_bbox = best.get("bbox")
            if not isinstance(best_bbox, list) or len(best_bbox) < 4:
                # No bbox to reason about; just take it and stop
                selected_for_year.append(best)
                break
            best_ibox = (
                float(best_bbox[0]),
                float(best_bbox[1]),
                float(best_bbox[2]),
                float(best_bbox[3]),
            )
            gain = _bbox_intersection_area(best_ibox, remaining)
            if gain <= 0 and selected_for_year:
                break
            selected_for_year.append(best)
            candidates.remove(best)

            # Check if we've covered enough of the viewport. We approximate
            # "remaining uncovered" by shrinking the tracked rectangle to
            # the portion of the viewport not covered by the selected
            # tile's bbox. This is an approximation (a union of tiles is
            # not a rectangle), but good enough for a few-tile mosaic.
            covered_so_far = sum(
                _bbox_intersection_area(
                    (
                        float(sb[0]),
                        float(sb[1]),
                        float(sb[2]),
                        float(sb[3]),
                    ),
                    viewport,
                )
                for s in selected_for_year
                if isinstance((sb := s.get("bbox")), list) and len(sb) >= 4
            )
            if covered_so_far / viewport_area >= coverage_target:
                break

            # Update `remaining` to the sub-rectangle not covered by the
            # selected tile along the axis where the tile overlap is largest.
            tile_w, tile_s, tile_e, tile_n = best_ibox
            rw, rs, re_, rn = remaining
            # Choose the residual rectangle with the largest area: the
            # strip of remaining viewport that lies outside the tile
            # horizontally or vertically, whichever is bigger.
            residuals = []
            if tile_e < re_:
                residuals.append((max(tile_e, rw), rs, re_, rn))
            if tile_w > rw:
                residuals.append((rw, rs, min(tile_w, re_), rn))
            if tile_n < rn:
                residuals.append((rw, max(tile_n, rs), re_, rn))
            if tile_s > rs:
                residuals.append((rw, rs, re_, min(tile_s, rn)))
            if not residuals:
                break
            remaining = max(
                residuals,
                key=lambda r: max(0.0, (r[2] - r[0])) * max(0.0, (r[3] - r[1])),
            )

        groups.append(selected_for_year)

    return groups


def select_landsat_items(items: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """One Landsat item per year — lowest cloud cover within that year.

    Prefers Landsat 5/8/9 (TM, OLI-TIRS). Landsat 7 ETM+ (LE07) scenes
    are used only as a fallback because SLC-off failure since 2003
    produces diagonal stripes of missing data.

    Returns single-item groups (outer list per year, inner list always
    length 1) for shape consistency with NAIP multi-tile groups.
    """

    def is_le07(item: dict[str, object]) -> bool:
        return str(item.get("id", "")).startswith("LE07")

    by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        if not _has_capture_date(item):
            continue
        by_year[_capture_date(item).year].append(item)

    selected: list[dict[str, object]] = []
    for year_items in by_year.values():
        non_le07 = [i for i in year_items if not is_le07(i)]
        pool = non_le07 if non_le07 else year_items
        pick = min(pool, key=_cloud_cover)
        selected.append(pick)
    selected.sort(key=_capture_date)
    return [[i] for i in selected]


def select_sentinel_items(items: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """One Sentinel-2 item per calendar quarter — lowest cloud cover.

    Returns single-item groups for shape consistency with NAIP multi-tile
    groups.
    """
    by_quarter: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        if not _has_capture_date(item):
            continue
        d = _capture_date(item)
        quarter = (d.year, (d.month - 1) // 3 + 1)
        by_quarter[quarter].append(item)

    selected = [min(q_items, key=_cloud_cover) for q_items in by_quarter.values()]
    selected.sort(key=_capture_date)
    return [[i] for i in selected]


# ── Asset extraction ──────────────────────────────────────────────────────────


def _is_cog_asset(asset: dict[str, object]) -> bool:
    """Return True if the asset's STAC type indicates a GeoTIFF (COG).

    Planetary Computer uses ``image/tiff; application=geotiff; profile=cloud-optimized``
    for COGs.  Assets without a ``type`` field are assumed safe (some older STAC
    items omit it).
    """
    media_type = asset.get("type", "")
    if not media_type:
        return True  # no type declared — assume COG (backwards-compat)
    return "geotiff" in str(media_type).lower()


def extract_cog_url(item: dict[str, object], collection: str) -> str | None:
    """Extract the primary imagery URL for a STAC item.

    For **NAIP** and **Sentinel-2** this returns a direct COG href (the tile
    proxy uses Titiler's ``/cog/tiles/`` endpoint).

    For **Landsat** this returns the STAC item *self-link* URL.  Individual
    Landsat bands live in separate single-band COGs, so the tile proxy uses
    Titiler's ``/stac/tiles/`` endpoint with ``assets=red,green,blue`` for
    proper RGB compositing — which needs the full item URL, not a band URL.

    Returns None if no suitable asset / link is found.
    """
    assets: dict[str, dict[str, object]] = item.get("assets", {})  # type: ignore[assignment]  # STAC item "assets" is a dict of asset objects

    if collection == "naip":
        if "image" in assets and assets["image"].get("href") and _is_cog_asset(assets["image"]):
            return str(assets["image"]["href"])
        return None

    if collection == "landsat-c2-l2":
        # Store the STAC item self-link — the tile proxy uses Titiler's
        # /stac/tiles/ endpoint with per-asset signing at request time to
        # compose a true-colour RGB from the red, green, and blue band COGs.
        links: list[dict[str, str]] = item.get("links", [])  # type: ignore[assignment]  # STAC item "links" is a list of link objects
        self_href = next((lnk["href"] for lnk in links if lnk.get("rel") == "self"), None)
        if self_href:
            return str(self_href)
        # Fallback: construct canonical URL from collection + item ID
        item_id = item.get("id")
        if item_id:
            return f"{STAC_API}/collections/{collection}/items/{item_id}"
        return None

    if collection == "sentinel-2-l2a":
        # visual is a uint8 3-band (R/G/B) TCI COG — ideal for display.
        # B04 (single-band uint16, 0-10000) is NOT used: its data range is
        # incompatible with the rescale params configured for TCI tiles.
        if "visual" in assets and assets["visual"].get("href") and _is_cog_asset(assets["visual"]):
            return str(assets["visual"]["href"])
        return None

    return None


def extract_thumbnail_url(item: dict[str, object]) -> str | None:
    """Extract a ready-to-display thumbnail URL from a STAC item.

    Checks standard STAC thumbnail/preview asset keys.
    Returns None if none are available (caller should generate via Titiler).
    """
    assets: dict[str, dict[str, object]] = item.get("assets", {})  # type: ignore[assignment]  # STAC item "assets" is a dict of asset objects
    for key in ("rendered_preview", "thumbnail", "overview"):
        if key in assets and assets[key].get("href"):
            return str(assets[key]["href"])
    return None


def extract_capture_date(item: dict[str, object]) -> date:
    """Extract the capture date from a STAC item's datetime property."""
    return _capture_date(item)


async def _validate_asset(item: dict[str, object], asset_key: str, source: str) -> bool:
    """Sign and HEAD one asset to verify the item is actually servable."""
    assets: dict[str, dict[str, object]] = item.get("assets", {})  # type: ignore[assignment]  # STAC item "assets" is a dict of asset objects
    asset = assets.get(asset_key)
    if not asset or not asset.get("href"):
        logger.info(
            "%s item missing %s asset",
            source,
            asset_key,
            extra={"item_id": item.get("id")},
        )
        return False

    href = str(asset["href"])
    try:
        signed = await sign_pc_url(href, wait_budget=SIGN_WAIT_BATCH)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.info(
            "%s %s asset signing failed",
            source,
            asset_key,
            extra={"item_id": item.get("id"), "error": str(exc)},
        )
        return False

    try:
        resp = await _get_search_client().head(signed, follow_redirects=True)
        if resp.status_code >= 400:
            logger.info(
                "%s %s asset inaccessible",
                source,
                asset_key,
                extra={"item_id": item.get("id"), "status": resp.status_code},
            )
            return False
    except httpx.RequestError as exc:
        logger.info(
            "%s %s asset HEAD failed",
            source,
            asset_key,
            extra={"item_id": item.get("id"), "error": str(exc)},
        )
        return False

    return True


async def validate_landsat_item(item: dict[str, object]) -> bool:
    """Sign and HEAD the red band asset to verify the item is accessible.

    Older Landsat scenes (1984–1990s) sometimes have broken or expired
    assets on Planetary Computer.  A single-band canary check is enough
    because all bands share the same storage container.
    """
    return await _validate_asset(item, "red", "Landsat")


async def validate_sentinel_item(item: dict[str, object]) -> bool:
    """Sign and HEAD the visual (TCI) asset — the only one S2 tiles read."""
    return await _validate_asset(item, "visual", "Sentinel-2")


async def _validate_selection(
    selected_groups: list[list[dict[str, object]]],
    raw_items: list[dict[str, object]],
    *,
    period: Callable[[date], object],
    validate: Callable[[dict[str, object]], Awaitable[bool]],
    source: str,
) -> list[list[dict[str, object]]]:
    """Validate each selected item, swapping in same-period fallbacks.

    For each selected item, HEAD-checks its canary asset.  If it fails,
    iterates through candidates from the same period in *raw_items* (ranked
    by cloud cover) until a valid one is found.  Periods with no valid
    candidate are dropped entirely — better a gap than a 502.

    ``period`` is whatever grouping the source selects on: the year for
    Landsat, the calendar quarter for Sentinel-2, matching their selectors.
    """
    by_period: dict[object, list[dict[str, object]]] = defaultdict(list)
    for item in raw_items:
        if not _has_capture_date(item):
            continue
        by_period[period(_capture_date(item))].append(item)
    for period_items in by_period.values():
        period_items.sort(key=_cloud_cover)

    # Filter once and zip over the filtered list. Validating `if g` while
    # zipping over the unfiltered groups made strict=True raise ValueError —
    # failing the whole source — the first time any selector emitted an
    # empty group. No selector does today; that is what makes it a landmine
    # rather than a bug.
    non_empty = [g for g in selected_groups if g]

    # Validate all selected items in parallel
    valid_flags = await asyncio.gather(*(validate(g[0]) for g in non_empty))

    validated: list[list[dict[str, object]]] = []
    for group, is_valid in zip(non_empty, valid_flags, strict=True):
        item = group[0]
        if is_valid:
            validated.append(group)
            continue

        key = period(_capture_date(item))
        selected_id = item.get("id")
        logger.warning(
            "%s item failed validation; trying fallbacks",
            source,
            extra={"period": str(key), "item_id": selected_id},
        )

        found = False
        for candidate in by_period.get(key, []):
            if candidate.get("id") == selected_id:
                continue
            if await validate(candidate):
                logger.info(
                    "%s fallback found",
                    source,
                    extra={
                        "period": str(key),
                        "original_id": selected_id,
                        "fallback_id": candidate.get("id"),
                    },
                )
                validated.append([candidate])
                found = True
                break

        if not found:
            logger.warning("No valid %s item for %s; skipping", source, key)

    return validated


async def validate_landsat_selection(
    selected_groups: list[list[dict[str, object]]],
    raw_items: list[dict[str, object]],
) -> list[list[dict[str, object]]]:
    """Validate selected Landsat items and swap in same-year fallbacks."""
    return await _validate_selection(
        selected_groups,
        raw_items,
        period=lambda d: d.year,
        validate=validate_landsat_item,
        source="Landsat",
    )


async def validate_sentinel_selection(
    selected_groups: list[list[dict[str, object]]],
    raw_items: list[dict[str, object]],
) -> list[list[dict[str, object]]]:
    """Validate selected Sentinel-2 items and swap in same-quarter fallbacks.

    The twin of ``validate_landsat_selection``. S2 had no validation pass at
    all, so a quarter whose lowest-cloud granule is unservable was persisted
    anyway and became a broken tile, where the same failure on Landsat costs
    at worst a gap. Same walk, same cloud ranking, grouped by the quarter S2
    selects on rather than the year.
    """
    return await _validate_selection(
        selected_groups,
        raw_items,
        period=lambda d: (d.year, (d.month - 1) // 3 + 1),
        validate=validate_sentinel_item,
        source="Sentinel-2",
    )


def extract_bbox_wkt(item: dict[str, object]) -> str | None:
    """Extract the item bounding box as a WKT POLYGON string, or None."""
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    w, s, e, n = bbox[0], bbox[1], bbox[2], bbox[3]
    return f"SRID=4326;POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
