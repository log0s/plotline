"""Drop ``imagery_snapshots``.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-29 00:00:00.000000 UTC

Step 4 of ``docs/adr/0001-imagery-normalization.md``, second and final deploy.
Pure DDL, and the **only** thing in its deploy.

## This migration ships ALONE

No code change may ride the same push, and this is a gate rather than a
preference. The deploy that carries this migration is the one that makes the
table stop existing, and the whole basis for running it is a cooling period
during which the deployed code demonstrably did not touch it. If a code change
rides along, the running code at the moment of the drop is not the code the
cooling period measured, and the measurement stops being about the thing that
was dropped. Recorded here and in STATUS.md so a future batch cannot fold it
into something else for convenience.

The ordering this sits in is the plan of record's amendment to
``NORM31-PROD-REPORT.md`` §6d, and it is deliberate:

1. **The code cutover deploys first** (`329a8a6`). Nothing in ``app/`` or
   ``scripts/`` reads or writes the table, so the expected access count over
   the cooling span becomes exactly **zero from anything** — an unambiguous
   measurement — rather than §6d's weaker "moving only by the reconciler's own
   pulls, accounted for row by row".
2. **The cooling span runs**, with a fleet sweep in it, against that deployed
   code. §6d's conditions in their amended form are the gate on this
   migration; STATUS.md holds them.
3. **This migration deploys**, alone.

## The downgrade recreates the schema and NOT the data

``downgrade()`` rebuilds the table exactly as migrations 0002, 0007 and 0008
left it — columns, CHECK, unique constraint, both indexes — and it comes back
**empty**. There is no backfill and there cannot be one: ``parcel_scenes``
joined to ``scenes`` holds the current selections, but a snapshot row also
carried per-parcel copies of item facts that the normalization deliberately
collapsed to one copy, and one of those copies won. Reconstructing the other
copies would mean inventing rows that say what the old table said, which is
the opposite of what the audit trail is for.

**The recovery path for the data is Neon PITR, not ``alembic downgrade``.**
Anyone reaching for the downgrade because rows are needed is reaching for the
wrong lever: it produces an empty table with the right shape, which will make
a serving read return nothing rather than fail, and that is a worse failure
than a missing table. The downgrade exists so the *revision graph* is
reversible, not so the drop is.

Nothing reads the table at this revision, so the drop blocks no query and the
downgrade unblocks none.
"""

from __future__ import annotations

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "imagery_snapshots"


def upgrade() -> None:
    # The indexes and constraints go with the table; naming them here would be
    # redundant DDL that can only disagree with what is actually there. The
    # downgrade recreates all of them explicitly, which is where the record of
    # what existed belongs.
    op.drop_table(_TABLE)


def downgrade() -> None:
    """Rebuild the schema of the dropped table. **The rows do not come back.**

    Reconstructed from 0002 (the table, its CHECK, its unique constraint and
    both indexes), 0007 (``additional_cog_urls``) and 0008 (the CHECK widened
    to admit ``usgs_topo``) — the cumulative state at 0018, not 0002's.
    """
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "parcel_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("parcels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("capture_date", sa.Date(), nullable=False),
        sa.Column("stac_item_id", sa.Text(), nullable=False),
        sa.Column("stac_collection", sa.Text(), nullable=False),
        sa.Column(
            "bbox",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("cog_url", sa.Text(), nullable=False),
        sa.Column("additional_cog_urls", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("resolution_m", sa.Double(), nullable=True),
        sa.Column("cloud_cover_pct", sa.Double(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_imagery_snapshots_source",
        _TABLE,
        "source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')",
    )
    op.create_unique_constraint(
        "uq_imagery_snapshots_parcel_stac_item",
        _TABLE,
        ["parcel_id", "stac_item_id"],
    )
    op.create_index("idx_imagery_parcel_date", _TABLE, ["parcel_id", "capture_date"])
    op.create_index("idx_imagery_bbox", _TABLE, ["bbox"], postgresql_using="gist")
