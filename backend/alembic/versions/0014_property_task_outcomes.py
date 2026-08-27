"""Per-query counts, a task-level 'partial', and a coverage verdict.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-27 00:00:00.000000 UTC

Three "complete with zero" states in the property path, all the same shape —
a failure the database cannot tell from success (STATUS.md Z3, Z4, and the
Adams jurisdiction row). Property has no period key, so it writes no
``timeline_task_years`` rows in any circumstance (INVESTIGATION §6.1): the
task row *is* its ledger, which is why these columns land here and not there.

``queries_run`` / ``queries_failed`` (Z3) carry the ``SourceFetchResult``
rollup that until now existed only in memory. H4's rule fails a property task
only when *every* query fails, so a 429-exhausted layer on a multi-query
county — Denver's 2, DC's 7 — left the task ``complete`` with a silently
thinner ``items_found``. With the counts recorded, ``partial`` becomes
readable rather than inferred, which is why ``ck_timeline_request_tasks_status`` is widened to
admit it (the request level got ``partial`` in 0012; the task level never
did).

``rows_returned`` / ``rows_matched`` (Z4) record the address-matcher split.
The rejection count is ``rows_returned - rows_matched``; before this, a broad
``LIKE`` that pulled 40 records and kept none was indistinguishable from a
portal that returned nothing, and the only witness was one worker log line
that ``fly logs`` drops ~3% of.

``coverage`` answers "was this address inside the jurisdiction we asked?".
``no_adapter`` is the state the pipeline already had (a county with no
adapter); ``not_covered`` is new and one level down — Adams County's layer
serves unincorporated Adams, and 12804 Emerson is in Thornton, which issues
its own permits. Both are "we did not ask", which is not "we asked and there
is nothing".

``items_found`` drops NOT NULL for the same reason. A not-covered task ran
zero queries, so 0 would be a count of nothing rather than an honest absence;
NULL is the only value that isn't a claim. This widens an existing column
constraint rather than adding one — noted as a deviation in the batch report
— because the prompt's ``items_found`` NULL requirement cannot be met
otherwise. Nothing reads the column as NOT NULL: the one comparison,
``scripts/requeue_empty_property.py``'s ``items_found == 0``, evaluates to
NULL for these rows and correctly skips them.

No backfill for any of the five: history ran under code that did not measure
these things, and inferring a count from ``items_found`` would let an
unmeasured run look measured. NULL means "not recorded", and every reader
must treat it that way.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The names the database actually carries, set by 0002. The ORM spelled two
# of them ``ck_trt_*``, which is a label that never existed on any server —
# ``DROP CONSTRAINT ck_trt_status`` fails with "does not exist" against dev.
# The models were corrected to these in the same commit (STATUS.md AA1).
_STATUS_CONSTRAINT = "ck_timeline_request_tasks_status"
_COVERAGE_CONSTRAINT = "ck_timeline_request_tasks_coverage"

_STATUSES_WITHOUT_PARTIAL = "'queued', 'processing', 'complete', 'failed', 'skipped'"
_STATUSES_WITH_PARTIAL = "'queued', 'processing', 'complete', 'partial', 'failed', 'skipped'"


def upgrade() -> None:
    for column in ("queries_run", "queries_failed", "rows_returned", "rows_matched"):
        op.add_column("timeline_request_tasks", sa.Column(column, sa.Integer(), nullable=True))

    op.add_column("timeline_request_tasks", sa.Column("coverage", sa.Text(), nullable=True))
    op.create_check_constraint(
        _COVERAGE_CONSTRAINT,
        "timeline_request_tasks",
        "coverage IS NULL OR coverage IN ('covered', 'not_covered', 'no_adapter')",
    )

    op.drop_constraint(_STATUS_CONSTRAINT, "timeline_request_tasks", type_="check")
    op.create_check_constraint(
        _STATUS_CONSTRAINT,
        "timeline_request_tasks",
        f"status IN ({_STATUSES_WITH_PARTIAL})",
    )

    op.alter_column("timeline_request_tasks", "items_found", nullable=True)


def downgrade() -> None:
    # Restoring NOT NULL forces a value onto the not-covered rows; 0 is the
    # pre-0014 vocabulary's only option and is exactly the conflation this
    # migration exists to remove, so a downgrade is lossy by construction.
    # 'partial' rows have no pre-0014 equivalent at all and are not rewritten
    # — the CHECK below fails loudly on them rather than demoting a partial
    # outcome to a word old readers would trust.
    op.execute("UPDATE timeline_request_tasks SET items_found = 0 WHERE items_found IS NULL")
    op.alter_column(
        "timeline_request_tasks",
        "items_found",
        nullable=False,
        server_default="0",
    )

    op.drop_constraint(_STATUS_CONSTRAINT, "timeline_request_tasks", type_="check")
    op.create_check_constraint(
        _STATUS_CONSTRAINT,
        "timeline_request_tasks",
        f"status IN ({_STATUSES_WITHOUT_PARTIAL})",
    )

    op.drop_constraint(_COVERAGE_CONSTRAINT, "timeline_request_tasks", type_="check")
    op.drop_column("timeline_request_tasks", "coverage")
    for column in ("rows_matched", "rows_returned", "queries_failed", "queries_run"):
        op.drop_column("timeline_request_tasks", column)
