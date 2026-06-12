"""Geocode endpoints — POST /api/v1/geocode, GET /api/v1/geocode/autocomplete."""

from __future__ import annotations

import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.rate_limit import RateLimit
from app.config import Settings, get_settings
from app.db import get_db, get_redis
from app.schemas.geocode import (
    AutocompleteSuggestion,
    GeocodeRequest,
    GeocodeResponse,
)
from app.services import geocoder as geocoder_service
from app.services import imagery as imagery_service
from app.services import parcels as parcels_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Continental US bounding box (west, south, east, north)
_US_BBOX = "-125.0,24.0,-66.0,50.0"

_AUTOCOMPLETE_CACHE_TTL = 300  # 5 minutes


@router.get(
    "/geocode/autocomplete",
    response_model=list[AutocompleteSuggestion],
    summary="Address autocomplete suggestions",
    description=(
        "Returns address suggestions for typeahead search, powered by "
        "Photon (OSM). Results are bounded to the continental US."
    ),
    dependencies=[Depends(RateLimit(times=60, seconds=60))],
)
async def autocomplete(
    q: str = Query(..., min_length=3, max_length=200, description="Partial address query"),
    settings: Settings = Depends(get_settings),
) -> list[AutocompleteSuggestion]:
    """Proxy Photon geocoder for US address autocomplete."""
    cache_key = f"autocomplete:{q.lower().strip()}"

    # Check Redis cache
    try:
        cached = get_redis().get(cache_key)
        if cached is not None:
            return [AutocompleteSuggestion(**s) for s in json.loads(cached)]
    except (RedisError, OSError) as exc:
        logger.debug("Autocomplete cache read failed: %s", exc)

    try:
        async with httpx.AsyncClient(
            timeout=3,
            headers={"User-Agent": "Plotline/1.0 (address-history-app)"},
        ) as client:
            resp = await client.get(
                "https://photon.komoot.io/api",
                params={
                    "q": q,
                    "bbox": _US_BBOX,
                    "limit": 6,
                    "lang": "en",
                },
            )
            resp.raise_for_status()
    except httpx.RequestError as exc:
        logger.warning("Photon request failed", exc_info=exc)
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning("Photon returned %s", exc.response.status_code)
        return []

    results: list[AutocompleteSuggestion] = []
    seen_names: set[str] = set()
    for feature in resp.json().get("features", []):
        props = feature.get("properties", {})

        # Filter to US results only (bbox is a hint, not a hard filter)
        if props.get("countrycode", "").upper() != "US":
            continue

        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        # Build a clean display name from structured parts
        name = props.get("name", "")
        housenumber = props.get("housenumber", "")
        street = props.get("street", "")
        city = props.get("city") or props.get("town") or props.get("village") or ""
        state = props.get("state", "")
        postcode = props.get("postcode", "")

        # Assemble: "123 Main St, Denver, Colorado 80202"
        parts: list[str] = []
        if housenumber and street:
            parts.append(f"{housenumber} {street}")
        elif street:
            parts.append(street)
        elif name:
            parts.append(name)
        if city:
            parts.append(city)
        if state:
            state_part = state
            if postcode:
                state_part = f"{state} {postcode}"
            parts.append(state_part)

        display_name = ", ".join(parts) if parts else props.get("label", "")
        if not display_name:
            continue

        # Deduplicate identical display names (Photon often returns
        # multiple OSM nodes for the same address)
        if display_name in seen_names:
            continue
        seen_names.add(display_name)

        results.append(
            AutocompleteSuggestion(
                display_name=display_name,
                lat=coords[1],
                lon=coords[0],
                place_type=props.get("osm_value", props.get("type", "")),
                city=city,
                state=state,
            )
        )

        if len(results) >= 5:
            break

    # Cache results
    try:
        get_redis().set(
            cache_key,
            json.dumps([s.model_dump() for s in results]),
            ex=_AUTOCOMPLETE_CACHE_TTL,
        )
    except (RedisError, OSError) as exc:
        logger.debug("Autocomplete cache write failed: %s", exc)

    return results


@router.post(
    "/geocode",
    response_model=GeocodeResponse,
    status_code=200,
    summary="Geocode a US address",
    description=(
        "Submits an address to the US Census Geocoder, deduplicates against "
        "existing parcels within 50 m, and returns the parcel record."
    ),
    responses={
        422: {"description": "Address could not be geocoded or validation failed"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream Census Geocoder API is unavailable"},
    },
    dependencies=[Depends(RateLimit(times=10, seconds=60))],
)
async def geocode_address(
    body: GeocodeRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GeocodeResponse:
    """Geocode an address and persist the result."""
    logger.info("Geocode request received", extra={"address": body.address})

    # 1. Geocode — use reverse lookup when coordinates are already known
    #    (e.g. from autocomplete selection), forward lookup otherwise.
    try:
        if body.lat is not None and body.lon is not None:
            geocode_result = await geocoder_service.reverse_geocode(
                latitude=body.lat,
                longitude=body.lon,
                address=body.address,
                settings=settings,
            )
        else:
            geocode_result = await geocoder_service.geocode_address(
                address=body.address,
                settings=settings,
            )
    except geocoder_service.GeocoderUnavailableError as exc:
        logger.error("Census Geocoder unreachable", extra={"error": str(exc)})
        raise HTTPException(
            status_code=502,
            detail="The Census Geocoder API is currently unavailable. Please try again later.",
        ) from exc
    except geocoder_service.AddressNotFoundError as exc:
        logger.warning("Address not geocodable", extra={"address": body.address})
        raise HTTPException(
            status_code=422,
            detail="Could not match this address. Please check the spelling and include city and state.",
        ) from exc

    # Steps 2 and 3 are synchronous DB work — run them in the threadpool so
    # they don't block the event loop of this async handler.

    # 2. Deduplicate / upsert parcel
    parcel, is_new = await run_in_threadpool(
        parcels_service.get_or_create_parcel,
        db=db,
        address=body.address,
        geocode_result=geocode_result,
        settings=settings,
    )

    logger.info(
        "Geocode complete",
        extra={
            "parcel_id": str(parcel.id),
            "is_new": is_new,
            "lat": parcel.latitude,
            "lng": parcel.longitude,
        },
    )

    # 3. Kick off imagery timeline fetch (idempotent — reuses an in-flight
    #    or complete request when one exists). DB errors here are non-fatal:
    #    the geocode result is still returned, just without a timeline id.
    def _ensure_timeline_request() -> uuid.UUID | None:
        try:
            timeline_req, is_new_request = imagery_service.get_or_create_timeline_request(
                db, parcel.id
            )

            if not is_new_request:
                refetch_req = imagery_service.maybe_refetch_for_backfill(
                    db,
                    parcel,
                    timeline_req,
                )
                if refetch_req is not None:
                    timeline_req = refetch_req
                    is_new_request = True

            if is_new_request:
                imagery_service.dispatch_timeline_task(db, timeline_req)

            return timeline_req.id
        except SQLAlchemyError as exc:
            logger.error(
                "Failed to create timeline request",
                extra={"parcel_id": str(parcel.id), "error": str(exc)},
            )
            return None

    timeline_request_id = await run_in_threadpool(_ensure_timeline_request)

    return GeocodeResponse(
        parcel_id=parcel.id,
        address=parcel.address,
        normalized_address=parcel.normalized_address,
        latitude=parcel.latitude,
        longitude=parcel.longitude,
        census_tract=parcel.census_tract_id,
        is_new=is_new,
        timeline_request_id=timeline_request_id,
    )
