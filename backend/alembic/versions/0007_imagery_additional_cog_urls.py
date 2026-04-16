"""Add additional_cog_urls to imagery_snapshots.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

# revision identifiers
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "imagery_snapshots",
        sa.Column("additional_cog_urls", ARRAY(sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("imagery_snapshots", "additional_cog_urls")
