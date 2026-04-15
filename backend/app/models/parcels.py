"""SQLAlchemy ORM models for parcels, timeline requests, and imagery snapshots."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base — all models inherit from this."""


class Parcel(Base):
    """Represents a geocoded US address stored as a PostGIS point."""

    __tablename__ = "parcels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    point: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326),
        nullable=False,
    )
    census_tract_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    county: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_fips: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    timeline_requests: Mapped[list[TimelineRequest]] = relationship(
        "TimelineRequest",
        back_populates="parcel",
        cascade="all, delete-orphan",
    )
    imagery_snapshots: Mapped[list[ImagerySnapshot]] = relationship(
        "ImagerySnapshot",
        back_populates="parcel",
        cascade="all, delete-orphan",
        order_by="ImagerySnapshot.capture_date",
    )
    census_snapshots: Mapped[list[CensusSnapshot]] = relationship(
        "CensusSnapshot",
        back_populates="parcel",
        cascade="all, delete-orphan",
        order_by="CensusSnapshot.year",
    )
    property_events: Mapped[list[PropertyEvent]] = relationship(
        "PropertyEvent",
        back_populates="parcel",
        cascade="all, delete-orphan",
        order_by="PropertyEvent.event_date",
    )

    __table_args__ = (
        Index("idx_parcels_point", "point", postgresql_using="gist"),
    )

    def __repr__(self) -> str:
        return f"<Parcel id={self.id} address={self.address!r}>"


class TimelineRequest(Base):
    """Tracks async jobs that build the historical timeline for a parcel."""

    __tablename__ = "timeline_requests"

    VALID_STATUSES = ("queued", "processing", "complete", "failed")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="queued",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    parcel: Mapped[Parcel | None] = relationship(
        "Parcel",
        back_populates="timeline_requests",
    )
    tasks: Mapped[list[TimelineRequestTask]] = relationship(
        "TimelineRequestTask",
        back_populates="timeline_request",
        cascade="all, delete-orphan",
        order_by="TimelineRequestTask.source",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'failed')",
            name="ck_timeline_requests_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<TimelineRequest id={self.id} status={self.status!r}>"


class TimelineRequestTask(Base):
    """Tracks per-source fetch status within a timeline request."""

    __tablename__ = "timeline_request_tasks"

    VALID_SOURCES = ("naip", "landsat", "sentinel2", "census", "property")
    VALID_STATUSES = ("queued", "processing", "complete", "failed", "skipped")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    timeline_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timeline_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="queued",
    )
    items_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    timeline_request: Mapped[TimelineRequest] = relationship(
        "TimelineRequest",
        back_populates="tasks",
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('naip', 'landsat', 'sentinel2', 'census', 'property')",
            name="ck_trt_source",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'failed', 'skipped')",
            name="ck_trt_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<TimelineRequestTask source={self.source!r} status={self.status!r}>"


class ImagerySnapshot(Base):
    """A single aerial/satellite imagery scene found for a parcel."""

    __tablename__ = "imagery_snapshots"

    VALID_SOURCES = ("naip", "landsat", "sentinel2")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    capture_date: Mapped[date] = mapped_column(Date, nullable=False)
    stac_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    stac_collection: Mapped[str] = mapped_column(Text, nullable=False)
    bbox: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326),
        nullable=True,
    )
    cog_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    parcel: Mapped[Parcel] = relationship(
        "Parcel",
        back_populates="imagery_snapshots",
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('naip', 'landsat', 'sentinel2')",
            name="ck_imagery_snapshots_source",
        ),
        UniqueConstraint(
            "parcel_id",
            "stac_item_id",
            name="uq_imagery_snapshots_parcel_stac_item",
        ),
        Index("idx_imagery_parcel_date", "parcel_id", "capture_date"),
        Index("idx_imagery_bbox", "bbox", postgresql_using="gist"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImagerySnapshot source={self.source!r} "
            f"date={self.capture_date} parcel={self.parcel_id}>"
        )


class CensusSnapshot(Base):
    """A single census data point for a parcel's tract in a given year."""

    __tablename__ = "census_snapshots"

    VALID_DATASETS = ("decennial", "acs5")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
    )
    tract_fips: Mapped[str] = mapped_column(Text, nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # Demographics — nullable, not every field available every year
    total_population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    median_household_income: Mapped[int | None] = mapped_column(Integer, nullable=True)
    median_home_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    median_year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_housing_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occupied_housing_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_occupied_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    renter_occupied_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vacancy_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    median_age: Mapped[float | None] = mapped_column(Double, nullable=True)
    median_gross_rent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    parcel: Mapped[Parcel] = relationship(
        "Parcel",
        back_populates="census_snapshots",
    )

    __table_args__ = (
        CheckConstraint(
            "dataset IN ('decennial', 'acs5')",
            name="ck_census_snapshots_dataset",
        ),
        UniqueConstraint(
            "parcel_id",
            "dataset",
            "year",
            name="uq_census_snapshots_parcel_dataset_year",
        ),
        Index("idx_census_parcel_year", "parcel_id", "year"),
    )

    def __repr__(self) -> str:
        return f"<CensusSnapshot dataset={self.dataset!r} year={self.year} parcel={self.parcel_id}>"


class PropertyEvent(Base):
    """A property history event — sale, permit, zoning change, or assessment."""

    __tablename__ = "property_events"

    VALID_EVENT_TYPES = (
        "sale",
        "permit_building",
        "permit_demolition",
        "permit_electrical",
        "permit_mechanical",
        "permit_plumbing",
        "permit_other",
        "zoning_change",
        "assessment",
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Sale-specific
    sale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Permit-specific
    permit_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    permit_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permit_valuation: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # General
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    parcel: Mapped[Parcel] = relationship(
        "Parcel",
        back_populates="property_events",
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('sale', 'permit_building', 'permit_demolition', "
            "'permit_electrical', 'permit_mechanical', 'permit_plumbing', "
            "'permit_other', 'zoning_change', 'assessment')",
            name="ck_property_events_event_type",
        ),
        UniqueConstraint(
            "parcel_id",
            "source",
            "source_record_id",
            name="uq_property_events_parcel_source_record",
        ),
        Index("idx_property_events_parcel_date", "parcel_id", "event_date"),
        Index("idx_property_events_type", "parcel_id", "event_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<PropertyEvent type={self.event_type!r} "
            f"date={self.event_date} parcel={self.parcel_id}>"
        )


class FeaturedLocation(Base):
    """A curated featured location for the landing page."""

    __tablename__ = "featured_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parcels.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_stat: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    parcel: Mapped[Parcel] = relationship("Parcel")

    __table_args__ = (
        Index("idx_featured_locations_slug", "slug", unique=True),
    )

    def __repr__(self) -> str:
        return f"<FeaturedLocation name={self.name!r} slug={self.slug!r}>"
