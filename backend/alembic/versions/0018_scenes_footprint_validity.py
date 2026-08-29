"""Add ``CHECK (ST_IsValid(footprint))`` to ``scenes``.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-29 00:00:00.000000 UTC

Pure DDL: one CHECK constraint added. No rows are read or written and nothing
else on the table changes. Independently revertable — the downgrade drops the
constraint and nothing else, so this can go on and come off without touching
any other part of step 4.

**Its precondition is met, and that is why it can land now.** A validating
CHECK is refused by PostgreSQL if any existing row fails it. On 2026-08-29 the
production queue — ``footprint IS NOT NULL AND NOT ST_IsValid(footprint)`` —
went 2 → 0 with the NORM-31 heal, verified against a fleet invariant over all
5,894 rows carrying a footprint: ``invalid`` 0, ``not_polygon`` 0
(``docs/audits/2026-08-normalization/NORM31-PROD-REPORT.md`` §2, §5). The two
rows were the whole population, not a slice of it. Before that heal this
migration could not have been applied at all.

**What this constraint is for, stated so it is not mistaken for the rule.**

The application rule is *repair loudly*: ``app/services/stac.py``'s
``normalize_footprint`` takes whatever a STAC item's geometry turns out to be,
repairs a self-intersection or a multipart result into a storable POLYGON, and
emits a complaint naming what it did. Every write path goes through it. A
footprint therefore arrives valid because a named function made it valid, not
because a constraint stopped an invalid one.

This CHECK is **bypass detection**. It fires only when a row reaches the table
without going through that function — a new writer, a heal script with its own
INSERT, a hand-run UPDATE. NORM-31 is exactly that history: two Sentinel-2
footprints with self-intersections, written by a path that predated the repair
rule, found by a sweep rather than by the database.

**If it ever fires, the fix is to route the writer through
``normalize_footprint`` — never to loosen the constraint.** A failing INSERT
here is the constraint doing its only job. Widening it, or dropping it to let
the write through, converts a caught bypass into an unnoticed one and puts the
next reader back where the geometry audit started.

``footprint`` stays nullable and the constraint is written to allow NULL
explicitly: ``ST_IsValid(NULL)`` is NULL, which a CHECK treats as satisfied,
but spelling the NULL case out means a reader does not have to know that rule
to know the intent. NULL footprints are a real population — ``usgs_topo`` rows
have no geometry at all (769 in production, excluded from the heal by design),
and the deferred enrichment queue is defined by it.

**Not mirrored in the SQLite test schema**, and ``tests/conftest.py`` says so
at the DDL with the reason: SQLite has no PostGIS, so any imitation of
``ST_IsValid`` there would be a predicate the test file invented, and a test
passing against it would prove only that the test file agrees with itself
(NORM-29's rule — derive the assertion from the real layer, never by agreement
with the code under test). It is exercised against a real server in
``tests/test_migrations_postgres.py``. The limitation is real: a footprint
PostGIS would reject can be inserted in the test database.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_scenes_footprint_valid"
_PREDICATE = "footprint IS NULL OR ST_IsValid(footprint)"


def upgrade() -> None:
    op.create_check_constraint(_CONSTRAINT, "scenes", _PREDICATE)


def downgrade() -> None:
    # Dropping it loses no data and blocks nothing: the application rule is
    # normalize_footprint, which is unaffected either way. This is the one
    # legitimate reason to remove the constraint — reverting the migration —
    # and it is not the same thing as loosening it to let a failing write
    # through, which the docstring above rules out.
    op.drop_constraint(_CONSTRAINT, "scenes", type_="check")
