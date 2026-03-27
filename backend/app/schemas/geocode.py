"""Pydantic schemas for the geocode endpoint."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


class GeocodeRequest(BaseModel):
    """Request body for POST /api/v1/geocode."""

    address: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Full US street address to geocode",
        examples=["1600 Pennsylvania Ave NW, Washington, DC 20500"],
    )
    lat: float | None = Field(
        default=None,
        description="Latitude from autocomplete — skips Census address lookup when provided with lon",
    )
    lon: float | None = Field(
        default=None,
        description="Longitude from autocomplete — skips Census address lookup when provided with lat",
    )

    @field_validator("address")
    @classmethod
    def strip_address(cls, v: str) -> str:
        return v.strip()


class AutocompleteSuggestion(BaseModel):
    """A single address autocomplete suggestion from Nominatim."""

    display_name: str = Field(description="Full formatted address")
    lat: float
    lon: float
    place_type: str = Field(default="", description="OSM place type (house, street, etc.)")
    city: str = Field(default="")
    state: str = Field(default="")


class GeocodeResponse(BaseModel):
    """Response body for POST /api/v1/geocode."""

    parcel_id: uuid.UUID
    address: str = Field(description="Original address as submitted")
    normalized_address: str | None = Field(
        default=None,
        description="Cleaned/matched address returned by the Census Geocoder",
    )
    latitude: float
    longitude: float
    census_tract: str | None = Field(
        default=None,
        description="11-digit FIPS census tract identifier",
    )
    is_new: bool = Field(
        description="True if a new parcel was created; False if a nearby existing parcel was returned"
    )
    timeline_request_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the queued or existing imagery timeline request — poll for status",
    )
