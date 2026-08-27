"""deployed_sha on timeline_requests; updated_at on census_snapshots.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-27 00:00:00.000000 UTC

Two independent additive columns, one migration because both were decided
together (STATUS.md Y7/Y8, 2026-08-27) and both exist to make a heal
provable rather than assumed:

``timeline_requests.deployed_sha`` is the build SHA running when the request
was created (the same value ``/api/v1/health`` reports — ``settings.git_sha``,
baked into the image at build time). It answers "did the code change since
this outcome was recorded", which is what turns ``absent/api_no_data`` from
"permanent" into "retryable once the fix lands" (HEAL-3 §5.4). Nullable, no
backfill: a pre-migration request ran under an unrecorded SHA, and guessing
one would let a stale outcome look freshly verified. NULL is handled by the
selection rule (``services/ledger.py``) as "changed", so it is excluded from
this CHECK deliberately having none — free text, no vocabulary to enforce.

No index: the selection query already joins
``timeline_task_years -> timeline_request_tasks -> timeline_requests`` to
rank latest outcomes (``ledger._LATEST_SQL``), and the SHA comparison happens
in Python alongside the other post-query filtering that file already does —
adding ``deployed_sha`` to that SELECT costs nothing extra to scan.

``census_snapshots.updated_at`` exists because the upsert
(``services/demographics.py``) rewrites values in place on conflict, and
before this column a heal's completeness could only be checked by row
existence, not by whether the row's values actually changed (HEAL-3 §5:
content checksums were the interim substitute). Backfilled to ``created_at``
— the only honest value for a row nothing has touched since; ``now()`` would
claim a heal happened that didn't.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("timeline_requests", sa.Column("deployed_sha", sa.Text(), nullable=True))

    op.add_column(
        "census_snapshots",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE census_snapshots SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column(
        "census_snapshots",
        "updated_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("census_snapshots", "updated_at")
    op.drop_column("timeline_requests", "deployed_sha")
