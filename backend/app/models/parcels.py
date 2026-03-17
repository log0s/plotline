"""SQLAlchemy ORM models for parcels and timeline_requests.

Both models live in one file for Phase 1. Split into separate files
if the schema grows significantly in later phases.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
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

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'failed')",
            name="ck_timeline_requests_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<TimelineRequest id={self.id} status={self.status!r}>"
