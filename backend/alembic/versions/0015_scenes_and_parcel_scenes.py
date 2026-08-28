"""Item-level ``scenes`` and per-parcel ``parcel_scenes``.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-28 00:00:00.000000 UTC

Step 1 of docs/adr/0001-imagery-normalization.md, DDL half. Pure schema: the
tables land empty and ``scripts/backfill_scenes.py`` fills them, so the
migration is safe to run against a database whose rows are still being
written by the old path. Nothing reads either table yet — step 3 owns the
read cutover — and ``imagery_snapshots`` is untouched.

Three details are worth reading before changing anything here.

**``parcel_scenes.group_key`` is not a new encoding.** It stores exactly the
string ``app/services/imagery.py``'s ``encode_group_key`` already produces
for the ledger and the reconciler: ``"1993"`` (year), ``"1993Q3"``
(quarter), ``"1960s"`` (decade). The CHECK below admits those three shapes
and nothing else. ``WHOLE_SOURCE_GROUP_KEY`` (``"*"``) is deliberately not
admitted: it is a ledger token meaning "this source's one untimed search",
and a *served* row always has a capture date to bucket, so it can never
legitimately appear here.

**``footprint`` is nullable, and its NULL-ness is not a provenance flag.**
Nothing in ``imagery_snapshots`` holds item geometry — that is the finding
the 2026-08 geometry audit had to refetch 1,239 STAC items to work around —
so every row the step-1 backfill writes has ``footprint IS NULL``. The
column that says where a row came from is ``provenance``.

**``provenance`` is an addition to the ADR's schema.** The ADR assumed
unmatched ``additional_cog_urls`` entries could be turned into scenes by
parsing the URL, on the premise that a NAIP filename *is* the STAC item id.
Measured against local data (312 NAIP rows, 2026-08-28) that premise holds
for 99 of them: the item id usually carries a trailing publication date the
filename omits (``…_20140927_20141126`` vs ``m_…_20140927.tif``), and eight
rows encode resolution differently in each (``_.6_`` vs ``_h_``). So a
synthesized row's ``item_id`` is a URL-derived candidate, not a catalogued
identifier, and without a column saying so it would be indistinguishable
from the real thing. ``provenance = 'mosaic_url'`` is the enumeration for
the later STAC enrichment pass, and survives the retirement of
``imagery_snapshots`` in step 4, which a "does any snapshot row carry this
item id" query would not.
"""

from __future__ import annotations

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCES = "'naip', 'landsat', 'sentinel2', 'usgs_topo'"

# 'YYYY' | 'YYYYQn' (n in 1-4) | 'YYYYs' — the three shapes encode_group_key
# emits, and no others.
_GROUP_KEY_FORMAT = r"group_key ~ '^[0-9]{4}(Q[1-4]|s)?$'"


def upgrade() -> None:
    # ── scenes ────────────────────────────────────────────────────────────────
    op.create_table(
        "scenes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("capture_date", sa.Date(), nullable=False),
        # The item's real geometry, not its bbox envelope. NULL until a STAC
        # pass fills it; see the module docstring.
        sa.Column(
            "footprint",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column(
            "bbox",
            geoalchemy2.Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("cog_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("resolution_m", sa.Double(), nullable=True),
        sa.Column("cloud_cover_pct", sa.Double(), nullable=True),
        # LT05/LE07/LC08/LC09, S2A/S2B. NULL for topo, for NAIP, and wherever
        # the item id does not name one unambiguously.
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"source IN ({_SOURCES})", name="ck_scenes_source"),
        sa.CheckConstraint(
            "provenance IN ('snapshot', 'mosaic_url')",
            name="ck_scenes_provenance",
        ),
        sa.UniqueConstraint("collection", "item_id", name="uq_scenes_collection_item"),
    )
    op.create_index("idx_scenes_footprint", "scenes", ["footprint"], postgresql_using="gist")
    op.create_index("idx_scenes_source_capture", "scenes", ["source", "capture_date"])

    # ── parcel_scenes ─────────────────────────────────────────────────────────
    op.create_table(
        "parcel_scenes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("parcel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Additional tiles only — the primary scene is `scene_id`, not a
        # member of this array. Every entry references a scenes row,
        # including the synthesized ones.
        sa.Column("mosaic_scene_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        # Git SHA of the selector that chose this row. NULL for backfilled
        # rows: history did not record it, and inventing one would make an
        # unattributed selection look attributed.
        sa.Column("selected_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parcel_id"],
            ["parcels.id"],
            name="fk_parcel_scenes_parcel_id",
            ondelete="CASCADE",
        ),
        # No ON DELETE: a scene still being served must not be deletable.
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["scenes.id"],
            name="fk_parcel_scenes_scene_id",
        ),
        sa.CheckConstraint(f"source IN ({_SOURCES})", name="ck_parcel_scenes_source"),
        sa.CheckConstraint(_GROUP_KEY_FORMAT, name="ck_parcel_scenes_group_key"),
        # ADR rule 3: G3's shape — two rows for one (parcel, source, period)
        # — becomes impossible by schema rather than by reconciliation
        # discipline.
        sa.UniqueConstraint(
            "parcel_id",
            "source",
            "group_key",
            name="uq_parcel_scenes_parcel_source_group",
        ),
    )
    op.create_index("idx_parcel_scenes_scene", "parcel_scenes", ["scene_id"])


def downgrade() -> None:
    op.drop_index("idx_parcel_scenes_scene", table_name="parcel_scenes")
    op.drop_table("parcel_scenes")
    op.drop_index("idx_scenes_source_capture", table_name="scenes")
    op.drop_index("idx_scenes_footprint", table_name="scenes")
    op.drop_table("scenes")
