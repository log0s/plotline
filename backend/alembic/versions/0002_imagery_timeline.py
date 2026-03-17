"""Add imagery_snapshots and timeline_request_tasks tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-17 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── imagery_snapshots ─────────────────────────────────────────────────────
    op.create_table(
        "imagery_snapshots",
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
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("capture_date", sa.Date(), nullable=False),
        sa.Column("stac_item_id", sa.Text(), nullable=False),
        sa.Column("stac_collection", sa.Text(), nullable=False),
        sa.Column(
            "bbox",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("cog_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("resolution_m", sa.Double(), nullable=True),
        sa.Column("cloud_cover_pct", sa.Double(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_imagery_snapshots_source",
        "imagery_snapshots",
        "source IN ('naip', 'landsat', 'sentinel2')",
    )

    op.create_unique_constraint(
        "uq_imagery_snapshots_parcel_stac_item",
        "imagery_snapshots",
        ["parcel_id", "stac_item_id"],
    )

    op.create_index(
        "idx_imagery_parcel_date",
        "imagery_snapshots",
        ["parcel_id", "capture_date"],
    )

    op.create_index(
        "idx_imagery_bbox",
        "imagery_snapshots",
        ["bbox"],
        postgresql_using="gist",
    )

    # ── timeline_request_tasks ────────────────────────────────────────────────
    op.create_table(
        "timeline_request_tasks",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "timeline_request_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("timeline_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("items_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_check_constraint(
        "ck_timeline_request_tasks_source",
        "timeline_request_tasks",
        "source IN ('naip', 'landsat', 'sentinel2', 'census', 'property')",
    )

    op.create_check_constraint(
        "ck_timeline_request_tasks_status",
        "timeline_request_tasks",
        "status IN ('queued', 'processing', 'complete', 'failed', 'skipped')",
    )

    op.create_index(
        "idx_trt_request",
        "timeline_request_tasks",
        ["timeline_request_id"],
    )


def downgrade() -> None:
    op.drop_table("timeline_request_tasks")
    op.drop_index("idx_imagery_bbox", table_name="imagery_snapshots")
    op.drop_index("idx_imagery_parcel_date", table_name="imagery_snapshots")
    op.drop_table("imagery_snapshots")
