"""Geocode endpoints — POST /api/v1/geocode, GET /api/v1/geocode/autocomplete."""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    except Exception:
        pass  # Redis down — proceed without cache

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
    except Exception:
        pass

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
        502: {"description": "Upstream Census Geocoder API is unavailable"},
    },
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
            detail=f"Could not geocode address: {exc}",
        ) from exc

    # 2. Deduplicate / upsert parcel
    parcel, is_new = parcels_service.get_or_create_parcel(
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

    # 3. Kick off imagery timeline fetch (idempotent — returns existing if done)
    timeline_request_id = None
    try:
        timeline_req, is_new_request = imagery_service.get_or_create_timeline_request(
            db, parcel.id
        )
        timeline_request_id = timeline_req.id

        # If the existing request is complete but is missing data that we
        # can now provide (new adapter, backfilled tract FIPS), force a new
        # request so the relevant tasks run.
        if not is_new_request and timeline_req.status == "complete":
            needs_refetch = False

            # Census backfill: tract FIPS available but no census data
            if parcel.census_tract_id:
                from app.services import demographics as demographics_service

                existing_census = demographics_service.get_census_snapshots(db, parcel.id)
                if not existing_census:
                    needs_refetch = True
                    logger.info(
                        "Census data missing — will re-fetch",
                        extra={"parcel_id": str(parcel.id)},
                    )

            # Property backfill: county adapter now available but property
            # task was skipped or produced no results on the previous run.
            if parcel.county:
                from app.services.county_adapters import get_adapter_for_county

                adapter = get_adapter_for_county(parcel.county)
                if adapter:
                    from app.models.parcels import TimelineRequestTask

                    prop_task = db.execute(
                        select(TimelineRequestTask)
                        .where(TimelineRequestTask.timeline_request_id == timeline_req.id)
                        .where(TimelineRequestTask.source == "property")
                    ).scalars().first()
                    if not prop_task or prop_task.status == "skipped":
                        needs_refetch = True
                        logger.info(
                            "Property data missing/skipped — adapter now available, will re-fetch",
                            extra={"parcel_id": str(parcel.id), "county": parcel.county},
                        )

            if needs_refetch:
                from app.models.parcels import TimelineRequest

                new_req = TimelineRequest(parcel_id=parcel.id, status="queued")
                db.add(new_req)
                db.commit()
                db.refresh(new_req)
                timeline_request_id = new_req.id
                is_new_request = True
                logger.info(
                    "Created new timeline request for data backfill",
                    extra={"parcel_id": str(parcel.id), "request_id": str(new_req.id)},
                )

        if is_new_request:
            from app.tasks.timeline import fetch_imagery_timeline

            fetch_imagery_timeline.delay(str(timeline_request_id))
            logger.info(
                "Imagery timeline task dispatched",
                extra={"parcel_id": str(parcel.id), "request_id": str(timeline_request_id)},
            )
    except Exception as exc:
        # Non-fatal — geocode response is still returned
        logger.warning(
            "Failed to dispatch imagery timeline task",
            extra={"parcel_id": str(parcel.id), "error": str(exc)},
        )

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
