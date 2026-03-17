"""Parcels endpoint — GET /api/v1/parcels/{parcel_id}."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.parcels import Parcel
from app.schemas.parcels import ParcelResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/parcels/{parcel_id}",
    response_model=ParcelResponse,
    summary="Get parcel by ID",
    description="Returns the full parcel record for the given UUID.",
    responses={
        404: {"description": "Parcel not found"},
    },
)
def get_parcel(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ParcelResponse:
    """Retrieve a single parcel by its UUID."""
    parcel = db.query(Parcel).filter(Parcel.id == parcel_id).first()
    if parcel is None:
        logger.warning("Parcel not found", extra={"parcel_id": str(parcel_id)})
        raise HTTPException(status_code=404, detail=f"Parcel {parcel_id} not found")

    return ParcelResponse.model_validate(parcel)
