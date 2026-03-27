"""CKAN Datastore API client.

Generic async helper for querying CKAN open data portals, used by county
adapters for jurisdictions that publish data on CKAN (e.g. San Jose).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class CKANError(Exception):
    """Raised when a CKAN Datastore query fails."""


async def query_ckan_datastore(
    domain: str,
    resource_id: str,
    *,
    q: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 100,
    offset: int = 0,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Query a CKAN Datastore resource via the datastore_search API.

    Args:
        domain: CKAN portal hostname (e.g. "data.sanjoseca.gov").
        resource_id: The resource UUID.
        q: Full-text search query (optional).
        filters: Dict of exact-match filters (optional).
        limit: Maximum rows to return (default 100).
        offset: Number of rows to skip (default 0).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of row dicts from the CKAN response.

    Raises:
        CKANError: On HTTP errors or unexpected responses.
    """
    url = f"https://{domain}/api/3/action/datastore_search"
    params: dict[str, str | int] = {
        "resource_id": resource_id,
        "limit": limit,
        "offset": offset,
    }
    if q:
        params["q"] = q
    if filters:
        import json

        params["filters"] = json.dumps(filters)

    logger.info(
        "CKAN datastore query",
        extra={"domain": domain, "resource": resource_id, "q": q},
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            resp = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise CKANError(f"Timeout querying {domain}/{resource_id}") from exc
        except httpx.RequestError as exc:
            raise CKANError(f"Request error: {exc}") from exc

        if resp.status_code != 200:
            raise CKANError(
                f"CKAN returned {resp.status_code} for {domain}/{resource_id}: "
                f"{resp.text[:200]}"
            )

        data = resp.json()
        if not data.get("success"):
            error = data.get("error", {})
            raise CKANError(f"CKAN query error: {error.get('message', error)}")

        records = data.get("result", {}).get("records", [])

        logger.info(
            "CKAN response",
            extra={"domain": domain, "resource": resource_id, "rows": len(records)},
        )
        return records
