"""The Planetary Computer fetch layer the enrichment passes share.

Extracted from ``scripts/enrich_synthesized_scenes.py`` when
``scripts/enrich_snapshot_scenes.py`` needed the same three things — bounded
concurrency, a global dispatch pace, and a retry policy that differs by
endpoint. Copying them would have meant two places for NORM-10's split to
regress in, which is the shape "grep for the shape before closing a bug"
rules out for infrastructure as much as for defects.

``scripts/shared`` is not an entry-point directory: nothing here has a
``main()``, and ``tests/test_script_logging.py``'s guard globs ``scripts/*.py``
non-recursively for that reason.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.services.stac import STAC_API

logger = logging.getLogger("scripts.shared.stac_fetch")

# Geometry audit precedent (docs/audits/2026-08-geometry-audit/FINDINGS.md:
# "1,239 distinct items fetched at concurrency 6 with 429 backoff").
FETCH_CONCURRENCY = 6
FETCH_ATTEMPTS = 4
FETCH_TIMEOUT_S = 30.0

# NORM-10 (docs/audits/2026-08-normalization/ENRICH-PROD-REPORT.md §5): PC
# answers a throttle on /search with 403, not 429. For the item endpoint 403
# is a permanent per-item refusal (the geometry audit's six forbidden NAIP
# items) and must not burn the retry budget on something that will never
# succeed. For /search the same 403 is the rate limiter, so it has to be
# retried like a 429 would be — the two endpoints need different sets, not one
# shared constant, even though a reader's first instinct is that "403
# Forbidden" means the same thing everywhere.
_ITEM_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_SEARCH_RETRYABLE_STATUSES = _ITEM_RETRYABLE_STATUSES | {403}

# NORM-10: ~814 requests in 28s (~29 req/s) at concurrency 6 with no pacing
# provoked the throttle; the same six searches replayed sequentially with a
# 2s gap (0.5 req/s) all returned 200. This is a global cap on how often a
# request is *dispatched*, independent of FETCH_CONCURRENCY, which only
# bounds how many are in flight awaiting a response — concurrency alone
# doesn't limit rate when responses are fast. 5 req/s leaves ~6x margin
# under the observed throttle point.
DEFAULT_MIN_INTERVAL_S = 0.2


class StacLookup:
    """The two PC calls the enrichment passes make. Replaced wholesale in tests.

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
        self.requests = 0
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
        endpoint, a 403) is an answer the caller records per row, not a
        failure of the run. ``retryable_statuses`` differs by endpoint — see
        the NORM-10 comment at the module-level constants.
        """
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(FETCH_ATTEMPTS):
            try:
                async with self._semaphore:
                    await self._pace()
                    self.requests += 1
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
