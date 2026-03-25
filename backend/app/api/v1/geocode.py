"""Geocode endpoint — POST /api/v1/geocode."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.geocode import GeocodeRequest, GeocodeResponse
from app.services import geocoder as geocoder_service
from app.services import imagery as imagery_service
from app.services import parcels as parcels_service

logger = logging.getLogger(__name__)
router = APIRouter()


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

    # 1. Call Census Geocoder
    try:
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

        # If the existing request is complete but has no census data, and we
        # now have a tract FIPS (backfilled), force a new request so the
        # census task runs.
        if (
            not is_new_request
            and timeline_req.status == "complete"
            and parcel.census_tract_id
        ):
            from app.services import demographics as demographics_service

            existing_census = demographics_service.get_census_snapshots(db, parcel.id)
            if not existing_census:
                from app.models.parcels import TimelineRequest

                new_req = TimelineRequest(parcel_id=parcel.id, status="queued")
                db.add(new_req)
                db.commit()
                db.refresh(new_req)
                timeline_request_id = new_req.id
                is_new_request = True
                logger.info(
                    "Created new timeline request for census backfill",
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
