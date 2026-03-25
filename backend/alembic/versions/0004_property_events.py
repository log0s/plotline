"""Add property_events table for Phase 4 property history.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-25 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_events",
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
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        # Sale-specific
        sa.Column("sale_price", sa.Integer(), nullable=True),
        # Permit-specific
        sa.Column("permit_type", sa.Text(), nullable=True),
        sa.Column("permit_description", sa.Text(), nullable=True),
        sa.Column("permit_valuation", sa.Integer(), nullable=True),
        # General
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=True),
        sa.Column("raw_data", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_property_events_event_type",
        "property_events",
        "event_type IN ('sale', 'permit_building', 'permit_demolition', "
        "'permit_electrical', 'permit_mechanical', 'permit_plumbing', "
        "'permit_other', 'zoning_change', 'assessment')",
    )

    op.create_unique_constraint(
        "uq_property_events_parcel_source_record",
        "property_events",
        ["parcel_id", "source", "source_record_id"],
    )

    op.create_index(
        "idx_property_events_parcel_date",
        "property_events",
        ["parcel_id", "event_date"],
    )

    op.create_index(
        "idx_property_events_type",
        "property_events",
        ["parcel_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_property_events_type", table_name="property_events")
    op.drop_index("idx_property_events_parcel_date", table_name="property_events")
    op.drop_table("property_events")
