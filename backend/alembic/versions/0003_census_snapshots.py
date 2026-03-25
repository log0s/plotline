"""Add census_snapshots table for Phase 3 demographic data.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-25 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "census_snapshots",
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
        sa.Column("tract_fips", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        # Demographics — nullable because not every field is available every year
        sa.Column("total_population", sa.Integer(), nullable=True),
        sa.Column("median_household_income", sa.Integer(), nullable=True),
        sa.Column("median_home_value", sa.Integer(), nullable=True),
        sa.Column("median_year_built", sa.Integer(), nullable=True),
        sa.Column("total_housing_units", sa.Integer(), nullable=True),
        sa.Column("occupied_housing_units", sa.Integer(), nullable=True),
        sa.Column("owner_occupied_units", sa.Integer(), nullable=True),
        sa.Column("renter_occupied_units", sa.Integer(), nullable=True),
        sa.Column("vacancy_rate", sa.Double(), nullable=True),
        sa.Column("median_age", sa.Double(), nullable=True),
        sa.Column("median_gross_rent", sa.Integer(), nullable=True),
        # Raw API response for future use
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_census_snapshots_dataset",
        "census_snapshots",
        "dataset IN ('decennial', 'acs5')",
    )

    op.create_unique_constraint(
        "uq_census_snapshots_parcel_dataset_year",
        "census_snapshots",
        ["parcel_id", "dataset", "year"],
    )

    op.create_index(
        "idx_census_parcel_year",
        "census_snapshots",
        ["parcel_id", "year"],
    )


def downgrade() -> None:
    op.drop_index("idx_census_parcel_year", table_name="census_snapshots")
    op.drop_table("census_snapshots")
