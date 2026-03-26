"""Pydantic schemas for featured locations."""

from __future__ import annotations

from pydantic import BaseModel


class FeaturedLocationResponse(BaseModel):
    """A single featured location for the landing page."""

    id: str
    parcel_id: str
    name: str
    subtitle: str
    slug: str
    key_stat: str | None
    description: str | None
    earliest_thumbnail: str | None
    latest_thumbnail: str | None

    model_config = {"from_attributes": True}


class FeaturedListResponse(BaseModel):
    """List of featured locations."""

    locations: list[FeaturedLocationResponse]
