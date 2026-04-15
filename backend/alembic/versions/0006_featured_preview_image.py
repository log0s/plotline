"""Add preview_image_url to featured_locations.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "featured_locations",
        sa.Column("preview_image_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("featured_locations", "preview_image_url")
