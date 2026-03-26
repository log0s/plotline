"""ArcGIS Feature Service query client.

Generic async helper for querying ArcGIS REST Feature Services, used by
county adapters after Denver migrated from Socrata to ArcGIS Hub.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
        ArcGISError: On HTTP errors or unexpected responses.
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
        try:
            resp = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ArcGISError(f"Timeout querying {service_url}") from exc
        except httpx.RequestError as exc:
            raise ArcGISError(f"Request error: {exc}") from exc

        if resp.status_code != 200:
            raise ArcGISError(
                f"ArcGIS returned {resp.status_code} for {service_url}: "
                f"{resp.text[:200]}"
            )

        data = resp.json()

        if "error" in data:
            err = data["error"]
            raise ArcGISError(
                f"ArcGIS query error: {err.get('message', err)}"
            )

        features = data.get("features", [])
        rows = [f["attributes"] for f in features if "attributes" in f]

        logger.info(
            "ArcGIS response",
            extra={"url": service_url, "rows": len(rows)},
        )
        return rows
