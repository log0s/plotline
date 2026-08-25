# ADR: Normalize imagery records into scenes and per-parcel selections

**Status:** Proposed — 2026-08-25
**Deciders:** Ryan
**Sequencing:** after the M4 per-year ledger and M3 per-source backfill; before the MCP server and any new imagery source.

Numbers below are from `docs/audits/2026-08-m4-design/INVESTIGATION.md` (prod snapshot 2026-08-24) and `docs/audits/2026-08-geometry-audit/`. Anything not traceable to one of those is tagged UNVERIFIED.

## Context

`imagery_snapshots` stores one row per (parcel, served item). Every attribute of the item — `stac_item_id`, `stac_collection`, `capture_date`, `bbox`, `cog_url`, `additional_cog_urls`, `thumbnail_url`, `resolution_m`, `cloud_cover_pct` — is copied into each parcel's row. The table holds 14,534 rows across 184 parcels; the same Landsat scene serves every Denver parcel and is stored once per parcel.

Consequences observed so far:

- **Item facts are stored N times and can disagree.** A scene's geometry, cloud cover, or asset URL lives in as many copies as there are parcels serving it. The 2026-08 geometry audit had to refetch 1,239 STAC items to learn what the table already nominally knew.
- **"Which parcels serve this item?" is a full scan.** The audit's per-item findings (e.g. `nj_m_4007309_sw` served for both 350 5th Ave parcels) were discovered by sweep, not query.
- **Period uniqueness is procedural.** There is no constraint on (parcel, source, period); `reconcile_source_snapshots` enforces it at write time, and G3 (a duplicate S2 quarter group) shows it can be bypassed.
- **Selection state and item state are one row.** Per-parcel facts (which period this item fills, that it was chosen over N others, that it is a 3-tile NAIP mosaic for this viewport) share a row with item facts, so neither can change without rewriting the other.

What this is **not**: no production incident traces to the denormalization. The geometry heal ran through it with Landsat exactly conserved. This is a structural cost, not an outage source, and that is why it is sequenced after M4/M3 rather than ahead of them.

## Decision

Split the table into an item-level table and a per-parcel selection table, migrated additively.

### `scenes` — one row per catalogued item

```
scenes
  id               UUID PK
  source           TEXT NOT NULL            -- naip | landsat | sentinel2 | usgs_topo
  collection       TEXT NOT NULL            -- stac_collection today
  item_id          TEXT NOT NULL            -- stac_item_id today
  capture_date     DATE NOT NULL
  footprint        geometry(POLYGON,4326)   -- item["geometry"], not bbox (see geometry audit)
  bbox             geometry(POLYGON,4326)
  cog_url          TEXT NOT NULL
  thumbnail_url    TEXT
  resolution_m     DOUBLE PRECISION
  cloud_cover_pct  DOUBLE PRECISION
  platform         TEXT                     -- LT05/LE07/LC08/LC09, S2A/S2B; NULL for topo
  fetched_at       TIMESTAMPTZ NOT NULL
  UNIQUE (collection, item_id)
```

### `parcel_scenes` — one row per (parcel, source, period)

```
parcel_scenes
  id               UUID PK
  parcel_id        UUID NOT NULL → parcels.id ON DELETE CASCADE
  source           TEXT NOT NULL
  group_key        TEXT NOT NULL            -- same encoding as the M4 ledger
  scene_id         UUID NOT NULL → scenes.id
  mosaic_scene_ids UUID[]                   -- NAIP additional tiles; replaces additional_cog_urls
  selected_at      TIMESTAMPTZ NOT NULL
  selected_by      TEXT                     -- git SHA of the selector that chose it
  UNIQUE (parcel_id, source, group_key)
  INDEX (scene_id)
```

Design rules:

1. **The M4 ledger does not reference either table.** Ledger rows carry `(task_id, source, group_key, outcome)`; the served row for a group is looked up by `(parcel_id, source, group_key)` at read time. This is what lets normalization replace the storage without touching the ledger.
2. **`group_key` is the one shared encoding** across `parcel_scenes`, the ledger, and `SELECTION_SCOPES`. Defined once; the five inlined grouping derivations (INVESTIGATION §6) migrate to it.
3. **Period uniqueness becomes a constraint.** `UNIQUE (parcel_id, source, group_key)` makes G3's shape impossible by schema, not by reconciliation discipline.
4. **Item facts are refreshable independently.** A scene's footprint or cloud cover can be corrected in one row. The next geometry audit is a query over `scenes`, not a refetch.
5. **Mosaics are references, not URL arrays.** `additional_cog_urls` becomes `mosaic_scene_ids`; every tile in a mosaic is a first-class scene.

### Migration path

Additive, four steps, each its own commit and each with a prediction written before it runs:

1. **Create both tables; backfill from `imagery_snapshots`.** Prediction: `scenes` row count = distinct `(stac_collection, stac_item_id)` in `imagery_snapshots`; `parcel_scenes` row count = `imagery_snapshots` row count minus known duplicate groups (G3, and any others the backfill surfaces — those are findings, reported not silently collapsed). Every `additional_cog_urls` entry resolves to a scene or is reported.
2. **Dual-write.** `reconcile_source_snapshots` writes both shapes. Run one full sweep; prediction: the two tables agree row-for-row with the old table on every parcel.
3. **Cut reads over.** The listing endpoint, Titiler callback, preview renderer, and warmup read from the new tables. Delete-the-fix standard: tests fail if any read path still touches `imagery_snapshots`.
4. **Retire `imagery_snapshots`** after one cooling period with no reads (measured, not assumed — log every read; expect zero).

The old table is not dropped until step 4, and step 4 does not run in the same batch as step 3.

## Consequences

**Gains.** One copy of every item fact; "which parcels serve item X" and "which scenes does parcel P serve" are both indexed queries; period uniqueness enforced by schema; the MCP server's `get_imagery_years` gets scene-level provenance (platform, cloud, footprint) without a join back to STAC; new sources (NYC orthos, MSS) land as scenes with their own `source`, not as more columns.

**Costs.** Four migration steps and four predictions. A fifth ORM model plus a hand-written SQLite DDL block in `tests/conftest.py` (M7's known chore). Every read site of `imagery_snapshots` touched — INVESTIGATION §8 and the O1 fix commit enumerate them; count UNVERIFIED until the migration prompt's inventory item. The G8 remedy's sweep, and any other selection-changing deploy, should wait until step 3 so its wave writes the new shape once.

**Unchanged.** Selection is still per-parcel — point-in-footprint, cloud argmin, NAIP viewport mosaic all stay where they are. Normalization changes where the *result* is stored, not how it is chosen.

## Rejected

- **Rewrite in place** (drop and recreate with the new shape). Discards the working table that four audits have scored against; violates the one-structural-change-in-flight rule. The additive path costs more commits and is safer at every step.
- **Keep denormalized; add a `(parcel_id, source, period)` unique constraint only.** Fixes G3's shape and nothing else. Considered as the minimal move; rejected because the MCP server and new imagery sources both want the scene-level table, and adding the constraint now means redoing the period encoding when `group_key` lands.
- **Normalize before the M4 ledger.** The earlier ordering risk: designing per-year outcomes against a table that was about to change. Resolved by rule 1 above instead — the ledger is decoupled, so order no longer matters for correctness, and the ledger's `ok` rows make step 1's prediction writable.

## Change conditions

Revisit this decision if:

- The M4 ledger's `group_key` encoding turns out not to be shared cleanly with selection scopes (the two would then need separate keys and rule 2 fails).
- Step 1's backfill surfaces more duplicate groups than G3 — that would mean reconciliation has been failing silently and the audit record is incomplete; stop and investigate before step 2.
- A source arrives whose items are not addressable by `(collection, item_id)` — the NYC tile service (SOURCE-LANDSCAPE R1) is the candidate: it is a URL template per year, not a catalogued item, and may need a `scenes` row per year with a synthetic `item_id`, or a separate kind. Decide when R1 is scoped, not now.