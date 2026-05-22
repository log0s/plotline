"""Add usgs_topo to source CHECK constraints.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-22 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_imagery_snapshots_source", "imagery_snapshots", type_="check"
    )
    op.create_check_constraint(
        "ck_imagery_snapshots_source",
        "imagery_snapshots",
        "source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')",
    )

    op.drop_constraint(
        "ck_timeline_request_tasks_source", "timeline_request_tasks", type_="check"
    )
    op.create_check_constraint(
        "ck_timeline_request_tasks_source",
        "timeline_request_tasks",
        "source IN ('naip', 'landsat', 'sentinel2', 'census', 'property', 'usgs_topo')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_timeline_request_tasks_source", "timeline_request_tasks", type_="check"
    )
    op.create_check_constraint(
        "ck_timeline_request_tasks_source",
        "timeline_request_tasks",
        "source IN ('naip', 'landsat', 'sentinel2', 'census', 'property')",
    )

    op.drop_constraint(
        "ck_imagery_snapshots_source", "imagery_snapshots", type_="check"
    )
    op.create_check_constraint(
        "ck_imagery_snapshots_source",
        "imagery_snapshots",
        "source IN ('naip', 'landsat', 'sentinel2')",
    )
