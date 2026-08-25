"""Per-year outcome ledger for timeline fetches.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-25 00:00:00.000000 UTC

Additive only. Nothing on ``timeline_request_tasks`` is touched: the ORM and
the database disagree on that table's CHECK-constraint names (ORM
``ck_trt_source`` / ``ck_trt_status``; database
``ck_timeline_request_tasks_source`` / ``..._status``), so any statement here
that named one of them from the ORM would fail against production. See M7
item 5 in docs/audits/2026-08-second-audit/STATUS.md.

Every constraint below is named explicitly and the ORM model repeats those
exact names, so this table starts life without that drift.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timeline_task_years",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalized from the task so (source, group_key, outcome) is a
        # self-contained index — and so the census path can distinguish its
        # two datasets, which share one 'census' task row.
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["timeline_request_tasks.id"],
            name="fk_tty_task_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'failed', 'absent', 'indeterminate', 'suppressed')",
            name="ck_tty_outcome",
        ),
        sa.UniqueConstraint("task_id", "group_key", name="uq_tty_task_group"),
    )
    op.create_index(
        "idx_tty_source_group_outcome",
        "timeline_task_years",
        ["source", "group_key", "outcome"],
    )
    op.create_index("idx_tty_task", "timeline_task_years", ["task_id"])


def downgrade() -> None:
    op.drop_index("idx_tty_task", table_name="timeline_task_years")
    op.drop_index("idx_tty_source_group_outcome", table_name="timeline_task_years")
    op.drop_table("timeline_task_years")
