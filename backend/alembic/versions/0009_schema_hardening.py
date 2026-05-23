"""Add updated_at to timeline_requests, coordinate CHECK constraints, null source_record_id index.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-22 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add updated_at to timeline_requests
    op.add_column(
        "timeline_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 2. Add coordinate CHECK constraints to parcels
    op.create_check_constraint(
        "ck_parcels_latitude",
        "parcels",
        "latitude >= -90 AND latitude <= 90",
    )
    op.create_check_constraint(
        "ck_parcels_longitude",
        "parcels",
        "longitude >= -180 AND longitude <= 180",
    )

    # 3. Partial unique index for property_events with null source_record_id
    op.execute(
        "CREATE UNIQUE INDEX uq_property_events_null_source_record "
        "ON property_events (parcel_id, source, event_type, event_date) "
        "WHERE source_record_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "uq_property_events_null_source_record",
        table_name="property_events",
    )
    op.drop_constraint("ck_parcels_longitude", "parcels", type_="check")
    op.drop_constraint("ck_parcels_latitude", "parcels", type_="check")
    op.drop_column("timeline_requests", "updated_at")
