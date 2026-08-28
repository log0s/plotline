"""Admit ``provenance = 'enriched'`` on ``scenes``.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-28 00:00:00.000000 UTC

Pure DDL: one CHECK constraint dropped and recreated with a third value. No
rows are read or written, and nothing else on the table changes.

**Why a third value rather than flipping enriched rows to ``'snapshot'``.**
``scripts/enrich_synthesized_scenes.py`` takes a ``provenance = 'mosaic_url'``
row — an ``item_id`` parsed out of a tile URL, with NULL footprint, bbox and
resolution — and, when a catalogued STAC item's image asset href equals the
row's ``cog_url`` exactly, replaces the candidate id with the catalogued one
and fills the item facts. That row is then trustworthy, and it has to leave
the ``WHERE provenance = 'mosaic_url'`` work queue or the queue never empties.

The available spelling was ``'snapshot'``, and it is the wrong one.
``'snapshot'`` has a meaning already written into 0015's docstring, the
``Scene`` model and the ADR's amendment: *copied from an ``imagery_snapshots``
row*. An enriched row never was an ``imagery_snapshots`` row — it exists
because no snapshot row carried that tile's URL as its own ``cog_url``, which
is precisely the condition under which the backfill synthesized it. Relabelling
it ``'snapshot'`` would make three frozen documents false and would erase, in
the only column that records it, the fact that this row's identity came from a
verified catalog lookup rather than from a copy. It is also lossy in one
direction only: once flipped, nothing can tell an enriched row from a copied
one again.

So the column keeps meaning "where did this row's facts come from", with three
honest answers, and every reader that wants "is this ``item_id`` catalogued"
writes ``provenance <> 'mosaic_url'`` — one predicate, unchanged by this
migration, correct before and after it.

Safe to run ahead of the enrichment pass: widening a CHECK rejects nothing it
used to accept, and no row carries the new value until that script writes one.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_scenes_provenance", "scenes", type_="check")
    op.create_check_constraint(
        "ck_scenes_provenance",
        "scenes",
        "provenance IN ('snapshot', 'mosaic_url', 'enriched')",
    )


def downgrade() -> None:
    # Narrowing the CHECK fails while any 'enriched' row exists, which is the
    # correct behaviour: those rows are not representable under the old
    # vocabulary, and silently rewriting them to 'snapshot' here would be the
    # relabelling the docstring above rejects.
    op.drop_constraint("ck_scenes_provenance", "scenes", type_="check")
    op.create_check_constraint(
        "ck_scenes_provenance",
        "scenes",
        "provenance IN ('snapshot', 'mosaic_url')",
    )
