"""Admit ``provenance = 'selection'`` on ``scenes``.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-28 00:00:00.000000 UTC

Pure DDL: one CHECK constraint dropped and recreated with a fourth value. No
rows are read or written, and nothing else on the table changes.

**Why a fourth value rather than widening one of the three.** Step 2 of
``docs/adr/0001-imagery-normalization.md`` makes ``reconcile_source_snapshots``
write a ``scenes`` row for every item the pipeline selects, at selection time,
from the STAC item itself. Neither existing value can describe that row
honestly:

* ``'snapshot'`` means *copied from an ``imagery_snapshots`` row* — frozen in
  0015's docstring, the ``Scene`` model, and the ADR's first amendment. A
  pipeline-written row is not a copy of anything; it is written from the item.
* ``'mosaic_url'`` means *parsed out of a tile URL, id never checked against a
  catalog* — the opposite of a row whose facts came from the catalogued item.
* ``'enriched'`` means *was ``'mosaic_url'``, then STAC-corrected* — a history
  a pipeline-written row does not have.

So ``'selection'``: the row was written by the selector that chose the item,
from the item, and carries ``footprint`` from birth. That last part is what
makes the distinction load-bearing rather than bookkeeping — ``'selection'``
and ``'enriched'`` rows have a footprint, ``'snapshot'`` rows do not
(STATUS.md NORM-7's deferred pass is exactly ``provenance = 'snapshot'``), and
collapsing the new rows into ``'snapshot'`` would make that queue definition
silently wrong the first time the pipeline runs.

The two predicates readers already use are unchanged by this migration and
correct before and after it: "is this ``item_id`` catalogued" is
``provenance <> 'mosaic_url'``, and "was this row copied out of
``imagery_snapshots``" is ``provenance = 'snapshot'``.

Safe to run ahead of the dual-write deploy: widening a CHECK rejects nothing
it used to accept, and no row carries the new value until the reconciler
writes one.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_scenes_provenance", "scenes", type_="check")
    op.create_check_constraint(
        "ck_scenes_provenance",
        "scenes",
        "provenance IN ('snapshot', 'mosaic_url', 'enriched', 'selection')",
    )


def downgrade() -> None:
    # Narrowing the CHECK fails while any 'selection' row exists, which is the
    # correct behaviour for the same reason 0016's downgrade gives: those rows
    # are not representable under the old vocabulary, and rewriting them to
    # 'snapshot' here would assert they were copied from imagery_snapshots
    # when they were not.
    op.drop_constraint("ck_scenes_provenance", "scenes", type_="check")
    op.create_check_constraint(
        "ck_scenes_provenance",
        "scenes",
        "provenance IN ('snapshot', 'mosaic_url', 'enriched')",
    )
