"""Declared scope and origin on timeline_requests, plus the 'partial' status.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26 00:00:00.000000 UTC

Additive: two new columns, one widened CHECK, one new index. Nothing on
``timeline_request_tasks`` is touched — the ORM and the database disagree on
that table's CHECK-constraint names (M7 item 5 in
docs/audits/2026-08-second-audit/STATUS.md), so a statement here naming one of
them from the ORM would fail against production. ``timeline_requests`` carries
no such drift: ``ck_timeline_requests_status`` is spelled the same in
``0001_initial.py:107`` and in the ORM, which is why this migration may drop
and recreate it.

``sources`` is **declared intent, not derived**. A full-scope request names
every source in the vocabulary; the worker intersects that with what the
parcel is actually eligible for (census needs a tract, property needs a
county), exactly as it did before this column existed. That is what makes
"is this the parcel's current request" a stable cardinality test rather than a
parcel-conditional one — see ``_find_reusable_request`` in
``app/services/imagery.py``.

Backfill deviates from the M3 prompt on one clause and the reason is here:
the prompt asks for ``sources`` = the distinct sources of each request's task
rows. That is the *derived* set, which is 4, 5 or 6 wide depending on whether
the parcel has a tract and a county, so it cannot express "full scope" as a
single value — and every pre-0012 request was full-scope by construction
(nothing in application code could create a partial one; INVESTIGATION §1.4).
So every existing row is backfilled to the full declared set.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Repeated rather than imported from app.models: a migration must keep
# describing the schema it wrote even after the model moves on.
_FULL_SCOPE = ("census", "landsat", "naip", "property", "sentinel2", "usgs_topo")
_ORIGINS = ("user", "backfill", "heal")

_FULL_SCOPE_SQL = "ARRAY[" + ", ".join(f"'{s}'" for s in _FULL_SCOPE) + "]::text[]"
_ORIGINS_SQL = ", ".join(f"'{o}'" for o in _ORIGINS)


def upgrade() -> None:
    # 1. Add both columns nullable so the backfill has something to write to.
    op.add_column("timeline_requests", sa.Column("sources", sa.ARRAY(sa.Text()), nullable=True))
    op.add_column("timeline_requests", sa.Column("origin", sa.Text(), nullable=True))

    # 2. Backfill. Every pre-0012 request was created by the full pipeline
    #    path, from a page view or a heal script that re-ran everything.
    op.execute(f"UPDATE timeline_requests SET sources = {_FULL_SCOPE_SQL} WHERE sources IS NULL")
    op.execute("UPDATE timeline_requests SET origin = 'user' WHERE origin IS NULL")

    op.alter_column("timeline_requests", "sources", nullable=False)
    op.alter_column("timeline_requests", "origin", nullable=False)
    op.execute(f"ALTER TABLE timeline_requests ALTER COLUMN sources SET DEFAULT {_FULL_SCOPE_SQL}")
    op.execute("ALTER TABLE timeline_requests ALTER COLUMN origin SET DEFAULT 'user'")

    op.create_check_constraint(
        "ck_timeline_requests_origin",
        "timeline_requests",
        f"origin IN ({_ORIGINS_SQL})",
    )
    # Containment plus non-emptiness, not set equality: the cardinality test
    # that decides "full scope" is only sound if the array holds no duplicate
    # and no unknown source. Duplicates are ruled out at the one write site
    # (``_create_queued_request`` normalizes), which this cannot express in a
    # CHECK without a subquery.
    op.create_check_constraint(
        "ck_timeline_requests_sources",
        "timeline_requests",
        f"cardinality(sources) > 0 AND sources <@ {_FULL_SCOPE_SQL}",
    )

    # 3. 'partial': terminal, at least one source failed, at least one did not.
    #    Crawford County parcel 6563dedf reads 'complete' today with two failed
    #    task rows and zero NAIP/Sentinel-2 snapshots served.
    op.drop_constraint("ck_timeline_requests_status", "timeline_requests", type_="check")
    op.create_check_constraint(
        "ck_timeline_requests_status",
        "timeline_requests",
        "status IN ('queued', 'processing', 'complete', 'partial', 'failed')",
    )
    #
    #    Only rows currently reading 'complete' are rewritten. A request that
    #    already reads 'failed' stays failed even if some of its tasks
    #    succeeded: those three rows in production are janitor-stranded runs
    #    (``Stranded: worker died mid-task``), and promoting one to 'partial'
    #    would make it reusable again and stop its parcel ever being re-run.
    #    A 'complete' request whose tasks *all* failed becomes 'failed', which
    #    is the same rule ``aggregate_request_status`` now applies at runtime;
    #    production has zero of those today.
    op.execute(
        """
        WITH shaped AS (
            SELECT r.id,
                   count(t.id) FILTER (WHERE t.status = 'failed') AS failed,
                   count(t.id) FILTER (
                       WHERE t.status NOT IN ('complete', 'failed', 'skipped')
                   ) AS still_open,
                   count(t.id) AS total
            FROM timeline_requests r
            JOIN timeline_request_tasks t ON t.timeline_request_id = r.id
            WHERE r.status = 'complete'
            GROUP BY r.id
        )
        UPDATE timeline_requests r
        SET status = CASE WHEN s.failed = s.total THEN 'failed' ELSE 'partial' END
        FROM shaped s
        WHERE r.id = s.id AND s.failed > 0 AND s.still_open = 0
        """
    )

    # 4. The index ``_find_reusable_request`` reads: latest full-scope request
    #    for a parcel. Partial on cardinality rather than on ``origin`` —
    #    ``requeue_parcels.py`` with no ``--sources`` creates a full-scope
    #    request with origin='heal', so origin does not separate the two.
    op.execute(
        "CREATE INDEX idx_timeline_requests_parcel_full_scope "
        "ON timeline_requests (parcel_id, created_at DESC) "
        f"WHERE cardinality(sources) = {len(_FULL_SCOPE)}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_timeline_requests_parcel_full_scope")
    op.execute("UPDATE timeline_requests SET status = 'complete' WHERE status = 'partial'")
    op.drop_constraint("ck_timeline_requests_status", "timeline_requests", type_="check")
    op.create_check_constraint(
        "ck_timeline_requests_status",
        "timeline_requests",
        "status IN ('queued', 'processing', 'complete', 'failed')",
    )
    op.drop_constraint("ck_timeline_requests_sources", "timeline_requests", type_="check")
    op.drop_constraint("ck_timeline_requests_origin", "timeline_requests", type_="check")
    op.drop_column("timeline_requests", "origin")
    op.drop_column("timeline_requests", "sources")
