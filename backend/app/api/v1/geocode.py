"""Geocode endpoint — POST /api/v1/geocode."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas.geocode import GeocodeRequest, GeocodeResponse
from app.services import geocoder as geocoder_service
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

    return GeocodeResponse(
        parcel_id=parcel.id,
        address=parcel.address,
        normalized_address=parcel.normalized_address,
        latitude=parcel.latitude,
        longitude=parcel.longitude,
        census_tract=parcel.census_tract_id,
        is_new=is_new,
    )
