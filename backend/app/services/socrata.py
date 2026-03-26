"""Socrata SODA API client.

Provides a generic async function for querying any Socrata open data portal.
Used by county adapters to fetch property sales, permits, and other records.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SocrataError(Exception):
    """Raised when a Socrata API request fails."""


async def query_socrata(
    domain: str,
    resource_id: str,
    *,
    where: str | None = None,
    order: str | None = None,
    limit: int = 100,
    app_token: str | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Query a Socrata dataset via the SODA API.

    Args:
        domain: Socrata portal hostname (e.g. "data.denvergov.org").
        resource_id: The 4x4 dataset identifier (e.g. "hmrh-5s3x").
        where: SoQL WHERE clause (optional).
        order: SoQL ORDER clause (optional).
        limit: Maximum rows to return (default 100).
        app_token: Optional Socrata app token for higher rate limits.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of row dicts from the Socrata response.

    Raises:
        SocrataError: On HTTP errors or unexpected responses.
    """
    url = f"https://{domain}/resource/{resource_id}.json"
    params: dict[str, str | int] = {"$limit": limit}
    if where:
        params["$where"] = where
    if order:
        params["$order"] = order

    headers: dict[str, str] = {}
    if app_token:
        headers["X-App-Token"] = app_token

    logger.info(
        "Socrata query",
        extra={"domain": domain, "resource": resource_id, "where": where},
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            resp = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise SocrataError(f"Timeout querying {domain}/{resource_id}") from exc
        except httpx.RequestError as exc:
            raise SocrataError(f"Request error: {exc}") from exc

        if resp.status_code == 404:
            logger.warning(
                "Socrata dataset not found (404)",
                extra={"domain": domain, "resource": resource_id},
            )
            return []

        if resp.status_code != 200:
            raise SocrataError(
                f"Socrata returned {resp.status_code} for {domain}/{resource_id}: "
                f"{resp.text[:200]}"
            )

        data = resp.json()
        if not isinstance(data, list):
            raise SocrataError(f"Unexpected response type: {type(data).__name__}")

        logger.info(
            "Socrata response",
            extra={"domain": domain, "resource": resource_id, "rows": len(data)},
        )
        return data
