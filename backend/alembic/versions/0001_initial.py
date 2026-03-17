"""Initial schema: parcels and timeline_requests tables.

Revision ID: 0001
Revises:
Create Date: 2026-03-16 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── parcels ──────────────────────────────────────────────────────────────
    op.create_table(
        "parcels",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("normalized_address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column(
            "point",
            geoalchemy2.Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("census_tract_id", sa.Text(), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("state_fips", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Spatial index for proximity queries
    op.create_index(
        "idx_parcels_point",
        "parcels",
        ["point"],
        postgresql_using="gist",
    )

    # Full-text search index on address
    op.execute(
        """
        CREATE INDEX idx_parcels_address
        ON parcels
        USING GIN (to_tsvector('english', address))
        """
    )

    # ── timeline_requests ────────────────────────────────────────────────────
    op.create_table(
        "timeline_requests",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "parcel_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("parcels.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_check_constraint(
        "ck_timeline_requests_status",
        "timeline_requests",
        "status IN ('queued', 'processing', 'complete', 'failed')",
    )

    op.create_index(
        "idx_timeline_requests_parcel_id",
        "timeline_requests",
        ["parcel_id"],
    )


def downgrade() -> None:
    op.drop_table("timeline_requests")
    op.drop_index("idx_parcels_address", table_name="parcels")
    op.drop_index("idx_parcels_point", table_name="parcels")
    op.drop_table("parcels")
