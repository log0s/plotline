"""Unique task rows, one in-flight request per parcel, BIGINT money columns,
geography dedup index, parcel_id NOT NULL.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-12 00:00:00.000000 UTC

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Dedupe timeline_request_tasks left behind by Celery redeliveries,
    #    then enforce one row per (request, source).
    op.execute(
        """
        DELETE FROM timeline_request_tasks a
        USING timeline_request_tasks b
        WHERE a.timeline_request_id = b.timeline_request_id
          AND a.source = b.source
          AND a.id < b.id
        """
    )
    op.create_unique_constraint(
        "uq_trt_request_source",
        "timeline_request_tasks",
        ["timeline_request_id", "source"],
    )

    # 2. Fail any request stuck in flight (lost worker, dispatch failure),
    #    keep at most one in-flight row per parcel, then enforce it.
    op.execute(
        """
        UPDATE timeline_requests
        SET status = 'failed',
            error_message = 'Worker never completed the request'
        WHERE status IN ('queued', 'processing')
          AND updated_at < now() - interval '45 minutes'
        """
    )
    op.execute(
        """
        UPDATE timeline_requests a
        SET status = 'failed',
            error_message = 'Superseded by a newer request'
        FROM timeline_requests b
        WHERE a.parcel_id = b.parcel_id
          AND a.id <> b.id
          AND a.status IN ('queued', 'processing')
          AND b.status IN ('queued', 'processing')
          AND (a.created_at, a.id) < (b.created_at, b.id)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_timeline_requests_parcel_inflight "
        "ON timeline_requests (parcel_id) "
        "WHERE status IN ('queued', 'processing')"
    )

    # 3. Requests without a parcel are meaningless — remove and forbid.
    op.execute("DELETE FROM timeline_requests WHERE parcel_id IS NULL")
    op.alter_column("timeline_requests", "parcel_id", nullable=False)

    # 4. Manhattan sale prices exceed the int32 range ($2.1B+ recorded sales).
    op.alter_column("property_events", "sale_price", type_=sa.BigInteger())
    op.alter_column("property_events", "permit_valuation", type_=sa.BigInteger())

    # 5. The parcel dedup query casts the point column to geography, which
    #    the geometry GIST index can't serve — give it an expression index.
    op.execute(
        "CREATE INDEX idx_parcels_point_geog ON parcels USING gist ((point::geography))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_parcels_point_geog")
    op.alter_column("property_events", "permit_valuation", type_=sa.Integer())
    op.alter_column("property_events", "sale_price", type_=sa.Integer())
    op.alter_column("timeline_requests", "parcel_id", nullable=True)
    op.execute("DROP INDEX uq_timeline_requests_parcel_inflight")
    op.drop_constraint("uq_trt_request_source", "timeline_request_tasks")
