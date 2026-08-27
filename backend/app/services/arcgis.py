"""ArcGIS Feature Service query client.

Generic async helper for querying ArcGIS REST Feature Services, used by
county adapters after Denver migrated from Socrata to ArcGIS Hub.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Esri acknowledges server-side rate limiting on hosted feature services —
# "If you receive a 429 response, the request has been rate limited"
# (developers.arcgis.com, query-features guide) — with no published number.
# Until this branch existed a 429 fell through the generic non-200 path and
# became an `ArcGISError` on the first try, which the property rollup counts
# as a failed query. Denver and Adams both run on hosted services, and R4/R5
# would add traffic to the same client.
_RETRY_ATTEMPTS = 3

# Cap on an honoured ``Retry-After``. Esri publishes no value, so a portal is
# free to ask for minutes; the whole query has ``timeout`` seconds to live and
# a longer sleep would only burn it before raising anyway.
_RETRY_AFTER_CAP_S = 20.0

_RETRY_JITTER_FRACTION = 0.25


def _retry_wait(resp: httpx.Response, fallback: float) -> float:
    """Seconds to wait before retrying a 429, from Retry-After or the backoff.

    Jitter is upward-only so a burst of parcels throttled together does not
    resume in lockstep; ``Retry-After`` is never undercut, only capped.
    """
    raw = resp.headers.get("retry-after")
    wait = fallback
    if isinstance(raw, str) and raw:
        try:
            wait = min(max(0.0, float(raw.strip())), _RETRY_AFTER_CAP_S)
        except ValueError:
            wait = fallback  # HTTP-date form: fall back to the backoff
    return wait * (1.0 + random.random() * _RETRY_JITTER_FRACTION)


class ArcGISError(Exception):
    """Raised when an ArcGIS Feature Service query fails."""


async def query_feature_service(
    service_url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    result_record_count: int = 100,
    order_by: str | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Query an ArcGIS Feature Service layer and return attribute rows.

    Args:
        service_url: Full URL to the Feature Service layer
            (e.g. "https://services1.arcgis.com/.../FeatureServer/316").
        where: SQL WHERE clause for filtering.
        out_fields: Comma-separated field names or "*".
        result_record_count: Max rows to return.
        order_by: ORDER BY clause (e.g. "DATE_ISSUED DESC").
        timeout: HTTP request timeout in seconds.

    Returns:
        List of attribute dicts (geometry stripped).

    Raises:
        ArcGISError: On HTTP errors or unexpected responses. A 429 is retried
            up to ``_RETRY_ATTEMPTS`` times within ``timeout``; one that never
            clears raises rather than returning zero rows, so the property
            rollup counts it as a failed query.
    """
    params: dict[str, str | int] = {
        "where": where,
        "outFields": out_fields,
        "resultRecordCount": result_record_count,
        "f": "json",
        "returnGeometry": "false",
    }
    if order_by:
        params["orderByFields"] = order_by

    url = f"{service_url}/query"

    logger.info(
        "ArcGIS Feature Service query",
        extra={"url": service_url, "where": where},
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # One retry branch, for 429 only. ``timeout`` is the whole query's
        # budget, sleeping included: an attempt is started only while the time
        # already spent leaves room for the wait, so a throttled query still
        # gives up inside the budget its caller already assumes rather than
        # extending it. Everything else — 5xx, a transport failure — stays
        # terminal here and is one failed query to the property rollup.
        started = time.monotonic()
        delay = 1.0
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                resp = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise ArcGISError(f"Timeout querying {service_url}") from exc
            except httpx.RequestError as exc:
                raise ArcGISError(f"Request error: {exc}") from exc

            if resp.status_code != 429 or attempt == _RETRY_ATTEMPTS - 1:
                break

            wait = _retry_wait(resp, delay)
            spent = time.monotonic() - started
            if spent + wait > timeout:
                logger.warning(
                    "ArcGIS rate-limited; backoff exceeds the query budget",
                    extra={"url": service_url, "wait_s": wait, "budget_s": timeout},
                )
                break
            logger.warning(
                "ArcGIS rate-limited; backing off",
                extra={"url": service_url, "attempt": attempt + 1, "wait_s": wait},
            )
            await asyncio.sleep(wait)
            delay *= 2

        if resp.status_code == 429:
            logger.error(
                "ArcGIS rate limit not cleared; failing the query",
                extra={"url": service_url, "where": where},
            )
            raise ArcGISError(f"ArcGIS returned 429 (rate limited) for {service_url}")

        if resp.status_code != 200:
            logger.error(
                "ArcGIS error response",
                extra={"url": service_url, "status": resp.status_code, "body": resp.text[:500]},
            )
            raise ArcGISError(f"ArcGIS returned {resp.status_code} for {service_url}")

        # A portal can answer 200 with an HTML error page or a truncated
        # body. Wrapping the decode here keeps it an ArcGISError, so the
        # caller's per-query handler fails one query instead of the task.
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            logger.error(
                "ArcGIS returned non-JSON body",
                extra={"url": service_url, "body": resp.text[:200]},
            )
            raise ArcGISError(
                f"ArcGIS returned invalid JSON for {service_url}: {resp.text[:200]}"
            ) from exc

        if not isinstance(data, dict):
            raise ArcGISError(f"Unexpected response type: {type(data).__name__}")

        if "error" in data:
            err = data["error"]
            raise ArcGISError(f"ArcGIS query error: {err.get('message', err)}")

        features = data.get("features", [])
        rows = [f["attributes"] for f in features if "attributes" in f]

        logger.info(
            "ArcGIS response",
            extra={"url": service_url, "rows": len(rows)},
        )
        if len(rows) >= result_record_count:
            logger.warning(
                "ArcGIS query hit its row cap — results are truncated",
                extra={"url": service_url, "cap": result_record_count, "where": where},
            )
        return rows
