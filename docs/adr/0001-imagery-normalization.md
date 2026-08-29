# ADR: Normalize imagery records into scenes and per-parcel selections

**Status:** Accepted — 2026-08-28 (proposed 2026-08-25)
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
---

## Amendment — 2026-08-28, accepting the ADR and building step 1

Added when the status moved Proposed → Accepted and step 1 was built and run
locally. Everything above this line is the 2026-08-25 record and is unedited;
this section carries the corrections. Sources: the pre-flight verification
`docs/audits/2026-08-normalization-pre/VERIFICATION.md`, and step 1's own
report `docs/audits/2026-08-normalization/STEP1-REPORT.md` with its scored
prediction `.../PREDICTION-STEP1.md`.

Commits: `822faca` (migration 0015), `0fc0f64` (ORM models + test DDL),
`b3f8e94` (`scripts/backfill_scenes.py`), `ea98325` (prediction),
`d13026e` (scoring), `382329e` (tests).

### Context numbers have moved

The Context section's **14,534 rows across 184 parcels** is a 2026-08-24
snapshot. Read-only on **2026-08-28** production holds **12,884 rows** across
**6,156 distinct `(stac_collection, stac_item_id)` pairs**, with **zero**
duplicate `(parcel_id, source, group_key)` groups and 613
`additional_cog_urls` entries (73 matching some row's `cog_url`, 540 not).
The drop is consistent with the G8 completion sweep's Sentinel-2
quarter-deduplication deletions. The original figure stands as written; this
is the current one.

### Rule 2 had already shipped

`encode_group_key` / `decode_group_key` (`app/services/imagery.py:1023-1048`)
is the single encoding and all five sites INVESTIGATION §6 found hand-inlining
the rules now call it. So rule 2 is not work this migration does:
`parcel_scenes.group_key` only has to *store* the string that function already
produces. Migration 0015's CHECK admits exactly its three outputs — `'YYYY'`,
`'YYYYQn'`, `'YYYYs'` — and deliberately excludes `WHOLE_SOURCE_GROUP_KEY`
(`'*'`), which is a ledger token for an untimed whole-source search and can
never describe a served row.

### Synthesized scenes, and why `provenance` exists

Rule 5 says every tile in a mosaic is a first-class scene. Most tiles were
never persisted as their own row — 88 of 115 distinct mosaic URLs locally, 540
of 613 entries in production — so step 1 synthesizes a `scenes` row for each
unmatched URL by parsing it. No network calls; a URL that will not parse, or
is not a NAIP tile URL, refuses the whole run.

**The premise that a NAIP filename is the STAC item id is wrong.** Measured
across 312 local NAIP rows on 2026-08-28: the state-prefixed filename stem
equals the item id in **99**, is a proper prefix of it in **204** more (the id
carries a trailing publication date the filename omits), and in **8** is
neither, because the id and the filename spell the resolution differently
(`_.6_` / `_.5_` versus `_h_`). A synthesized `item_id` is therefore a
*candidate*, not a catalogued identifier. Its `capture_date` is not a guess —
it is the first of the filename's date fields under either naming.

`scenes` consequently gains a column the schema block above does not list:

```
  provenance       TEXT NOT NULL  -- 'snapshot' | 'mosaic_url'
```

`'snapshot'` means the row was copied from an `imagery_snapshots` row and its
`item_id` is catalogued. `'mosaic_url'` means it was parsed out of a tile URL
and its `item_id` has never been checked against a catalog.

The obvious alternative — enumerate synthesized rows by `footprint IS NULL` —
does not work, and the reason is worth stating because it looks like it should.
Nothing in `imagery_snapshots` holds item geometry (the finding behind the
geometry audit's 1,239-item refetch), so **every** row step 1 writes has a
NULL footprint, Phase A included. `footprint IS NULL` selects the whole table,
not the synthesized part of it. A "does any snapshot row carry this item id"
query would work today and stop working at step 4, when `imagery_snapshots` is
retired. A column is the only form of the answer that survives its own
migration path.

`footprint` is nullable for the same reason. A later STAC enrichment pass
fills it, and `WHERE provenance = 'mosaic_url'` is that pass's work queue.

### `mosaic_scene_ids` includes synthesized rows

`mosaic_scene_ids` stays `UUID[]` as written, and **every entry references a
`scenes` row, synthesized ones included**. There is no second array, no
fallback to a URL, and no null-padding for a tile that lacks a catalogued
identity: a tile the pipeline served is a scene, and a tile whose id is a
URL-derived candidate is a scene with `provenance = 'mosaic_url'`. Locally
this is 141 rows carrying 162 references, matching the 141 snapshot rows and
162 `additional_cog_urls` entries exactly, with zero dangling references.

The array holds the *additional* tiles only; the primary is `scene_id` and is
not repeated in it.

### Step 1's prediction, as actually written

The migration-path text predicts `parcel_scenes` = `imagery_snapshots` row
count "minus known duplicate groups (G3, and any others the backfill
surfaces)". In practice the backfill does not collapse duplicates at all — it
**refuses to run** while any exist, because `UNIQUE (parcel_id, source,
group_key)` cannot represent them and quietly keeping one row of each is the
silent collapse this ADR's change condition forbids. Duplicates are cleared
by a sweep first, and then `parcel_scenes` = the row count exactly. That is
how step 1 ran locally: 269 duplicate groups → sweep → 0 → backfill.

### Selection provenance is not recoverable

`selected_by` is NULL on every backfilled row. The SHA of the selector that
chose a given snapshot is not recorded anywhere in the database or the audit
trail, and synthesizing one — the deploy SHA at backfill time, say — would
make an unattributed selection look attributed. Step 2's dual-write is where
the column starts carrying a real value.


---

## Amendment — 2026-08-28, step 1 in production

Appended the day step 1's backfill ran against production. Everything above
is unedited. Source: `docs/audits/2026-08-normalization/STEP1-PROD-REPORT.md`
and the "Observed — production" section of `.../PREDICTION-STEP1.md`.
Commits: `93ee2ff` (prediction, before the write) and the scoring commit
alongside it.

**Step 1 is done.** Migration 0015 deployed and applied;
`scripts/backfill_scenes.py --execute` ran once, 17:05–17:15 UTC, writing
**6,661 `scenes`** (6,156 from distinct `(stac_collection, stac_item_id)` +
505 synthesized) and **12,884 `parcel_scenes`** over 189 parcels. Every
predicted quantity confirmed; the immediate re-run plans the identical
totals and writes zero.

**The change condition did not trip.** "Step 1's backfill surfaces more
duplicate groups than G3" required a nonzero count; production measured
**0** duplicate `(parcel_id, source, group_key)` groups, against a 24-hour
ledger window carrying **zero `failed`** outcomes — so it is a real zero and
not one resting on an unretried upstream failure (the NORM-3 reading rule).

**A units correction to the amendment above.** That section says "540 of 613
entries in production" for unmatched mosaic URLs. 613 is an *entries* count;
Phase B synthesizes from *distinct* URLs, of which production has **578, with
505 unmatched**. So production holds 505 `provenance = 'mosaic_url'` rows,
not 540. The earlier sentence is left as written.

**Rule 5 held at production scale.** 613 mosaic references across 576
`parcel_scenes` rows — matching `imagery_snapshots`' 613 entries across 576
rows exactly, with zero dangling references.

**A step 2 precondition the ADR did not anticipate.** `UNIQUE (collection,
item_id)` does not protect against the collision the synthesized rows set
up. A synthesized `item_id` is a URL-derived candidate (the amendment above,
F1), so a later dual-write of the *real* catalogued item for the same
physical tile differs in `item_id`, satisfies the constraint, and lands a
second `scenes` row for one item silently. The constraint is on the wrong
key: it catches duplicate ids, and this failure is one item under two ids.
**Step 2 must either reconcile by `cog_url` before insert** — the tile's
actual address, and the key the backfill matched on — **or run the STAC
enrichment pass over `WHERE provenance = 'mosaic_url'` first**, so
`(collection, item_id)` is trustworthy table-wide before dual-write begins.
Enrichment-first is the more durable choice. Recorded as STATUS.md NORM-7.


---

## Amendment — 2026-08-28, the enrichment pass, run locally

Appended after `scripts/enrich_synthesized_scenes.py` was built and run
against the local database. Everything above is unedited. Sources:
`docs/audits/2026-08-normalization/ENRICH-LOCAL-REPORT.md` and the "Observed"
section of `.../PREDICTION-ENRICH.md`. Commits: `aa23709` (migration 0016),
`008d7b2` (script + tests), `ce810d5` (prediction, before the run).

**`provenance` now has three values, not two.** The block in the first
amendment reads `-- 'snapshot' | 'mosaic_url'` and is left as written; the
current vocabulary is:

```
  provenance       TEXT NOT NULL  -- 'snapshot' | 'mosaic_url' | 'enriched'
```

`'enriched'` means the row was synthesized from a tile URL and a catalogued
STAC item whose image asset href equals its `cog_url` *exactly* has since
replaced the candidate id and filled `footprint`, `bbox` and `resolution_m`.
It is a third value rather than a flip to `'snapshot'` because `'snapshot'`
means "copied from an `imagery_snapshots` row", which an enriched row never
was — it exists precisely because no snapshot row carried that tile's URL as
its own `cog_url`. The reader's question, "is this `item_id` catalogued", is
`provenance <> 'mosaic_url'` under either vocabulary. Migration 0016 is pure
DDL: one CHECK dropped and recreated.

**`cog_url` equality is the acceptance criterion, and the candidate id is
never evidence.** The pass addresses a first lookup with the candidate id
because it is cheap and sometimes right — 31 of 88 locally — but accepts an
item only when `extract_cog_url(item, collection)` equals the row's `cog_url`.
On any non-200, and on a 200 whose href does not match, it falls back to a
search over the capture year with the same `point_to_bbox(parcel, 1500 m)` the
NAIP pipeline searched with. No fuzzy matching, no nearest-date fallback: an
unmatchable row stays as it is and is reported.

**Local result:** queue 88 → 0. 31 already-exact, 57 id-corrected, 0 merged,
0 unmatched, 0 errors, 0 capture-date disagreements; 88 footprints written,
all `ST_Polygon`; `parcel_scenes` untouched; the re-run fetches nothing and
writes nothing. Every predicted quantity confirmed.

**What this does *not* yet do.** Production is untouched — 505 rows still
carry candidate ids and NULL footprints, and 0016 is not deployed, so the
step-2 collision the previous amendment describes is still live there.
And the 6,156 `provenance = 'snapshot'` production rows (1,174 local) still
have NULL footprints: **rule 4's "the next geometry audit is a query over
`scenes`, not a refetch" is not true yet**, and the pass that makes it true
is a separate one over a different population. STATUS.md NORM-7.

**One finding the pass surfaced about the pipeline, not about `scenes`.**
NAIP `resolution_m` has always been the per-source constant `1.0`
(`app/tasks/timeline.py:67,712`), never the item's `gsd`. The enriched rows
carry the real values — 0.3 m (9), 0.5 m (1), 0.6 m (30), 1.0 m (48) — so 40
of 88 tiles were recorded at a resolution they do not have, as is every NAIP
row in `imagery_snapshots`. Until it is fixed, NAIP `scenes` rows disagree
about resolution by provenance. STATUS.md NORM-9; the fix belongs with step
2's dual-write.


---

## Amendment — 2026-08-28, step 2's dual-write, built and swept locally

Appended after `reconcile_source_snapshots` was made to write both shapes and
a full local sweep scored a prediction. Everything above is unedited.
Sources: `docs/audits/2026-08-normalization/STEP2-REPORT.md` and the
"Observed" half of `.../PREDICTION-STEP2.md`. Commits: `61d486b`
(migration 0017), `9526805` (the dual-write), `17c488e` (tests), `fa0840e`
(prediction, before the sweep), `d9e5587` (scoring).

**Not deployed.** Step 2 is committed and has run against the local database
only. Production still runs the pre-step-2 pipeline.

### `provenance` now has four values

The first amendment's block reads `-- 'snapshot' | 'mosaic_url'`, the third
widened it to include `'enriched'`; both are left as written. The current
vocabulary is:

```
  provenance       TEXT NOT NULL  -- 'snapshot' | 'mosaic_url' | 'enriched' | 'selection'
```

`'selection'` means the row was written by the pipeline at selection time,
from the STAC item itself. It is a fourth value rather than a widening of
`'snapshot'` for a reason stronger than vocabulary hygiene: **`provenance =
'snapshot'` is a live work-queue definition**, not just a label — it is
exactly the deferred footprint pass over the rows the backfill copied
(STATUS.md NORM-7). A `'selection'` row carries `footprint` from birth, so
folding the new rows into `'snapshot'` would have made that queue definition
silently wrong the first time the pipeline ran. Migration 0017 is pure DDL:
one CHECK dropped and recreated. Both existing predicates are unchanged —
"is this `item_id` catalogued" is `provenance <> 'mosaic_url'`, "was this
copied out of `imagery_snapshots`" is `provenance = 'snapshot'`.

### Rule 5 now holds at write time, so the F1 class stops growing

The selector holds the real STAC items, so every tile of a NAIP mosaic is
catalogued as a first-class scene *when it is selected* — with its own
footprint, bbox, `gsd` and capture date — rather than being written as a URL
in an array for a later pass to parse an item id out of. Observed: four local
pipeline runs catalogued 21 new NAIP tiles and `provenance = 'mosaic_url'`
stayed at **0**. The synthesized-candidate class the first amendment
describes is now closed for new rows; only the 6,156 backfilled `snapshot`
rows still need the deferred footprint pass.

### `resolution_m` comes from the item, rounded (NORM-9, NORM-11)

The pipeline wrote NAIP's `resolution_m` as the per-source constant `1.0`
regardless of what the item said. It now writes the item's `properties.gsd`
wherever the item carries one, falling back to the constant only when it does
not — and **both shapes switched in the same commit**, from the same field of
the same object, so `imagery_snapshots` and `scenes` cannot disagree about a
row they were written from together.

`gsd` is rounded to two decimals by `normalize_resolution_m`, one named
function with the NORM-11 citation next to it. Two decimals is chosen against
the resolutions that occur (NAIP 0.3/0.5/0.6/1.0, Landsat 30, Sentinel-2 10):
the closest real pair is 0.1 m apart, so rounding cannot merge two
resolutions, and it absorbs noise four orders of magnitude larger than the
~1e-14 Planetary Computer actually serves. The cost is that the upstream
double is not recoverable from the column, which is accepted: the column
answers "how fine is this image", and it never held the exact `gsd` anyway.

**Old rows are not healed.** `upsert_imagery_snapshot`'s `ON CONFLICT DO
UPDATE` does not touch `resolution_m`, and `scenes` is insert-only, so a row
that already exists keeps the constant however many times it is re-selected.
The population that keeps 1.0 is therefore not "rows written before the
deploy" but "rows that still exist", and no sweep shrinks it. STATUS.md
NORM-13.

### `selected_by` starts carrying a value, and what NULL means

`selected_by` is the running image's `GIT_SHA` — the value the health
endpoint reports. It is written when a `parcel_scenes` row is inserted or
when its selection changes; an **unchanged** selection leaves the row
completely alone, `selected_at` included, because a sweep that re-picks the
same scene has not made a selection and bumping the timestamp would turn the
column into "when did the last sweep run".

So NULL keeps meaning "no dual-writing run has attributed this selection",
which for a backfilled row is exactly true. After step 3 there are no
backfilled rows and every row is attributed at insert.

### The two shapes commit together — inside the reconciler

`reconcile_source_snapshots`' single transaction now carries the
`imagery_snapshots` deletes, the mirrored `parcel_scenes` deletes, the
`scenes` inserts and the `parcel_scenes` upserts. It does **not** carry the
snapshot *inserts*, which happen earlier in the persist loop and commit per
row, unchanged from before. An interruption between them leaves new snapshot
rows with no `parcel_scenes` row, which the next run's reconcile writes — the
same recoverable direction the existing persist-then-reconcile ordering
already chose. STATUS.md NORM-14.

Deletion mirroring follows the old shape's rules exactly, absent-group rule
included: a group absent from a run's selection is never deleted in either
table, and the one exception — a `suppressed` item this run positively
identified as unservable — removes the `parcel_scenes` row only when it
actually serves that item.

### Step 2's prediction, as it actually ran

The migration-path text says "Run one full sweep; prediction: the two tables
agree row-for-row with the old table on every parcel." They do: **0 parity
violations in either direction over 3,082 rows**, 0 duplicate groups, 0
duplicate `(collection, item_id)`, 0 dangling mosaic references, and 176 of
176 mosaic references resolving to a scene whose `cog_url` is a member of the
same group's `additional_cog_urls`.

What the text did not anticipate is that **a current database cannot exercise
a dual-write's insert path**. The local database had been swept hours
earlier, so the sweep re-selected exactly what it already served and the
dual-write correctly wrote nothing — same table, whether or not the code
runs. Coverage came from two probe parcels inserted for the purpose, one of
which (already-catalogued region) did 71 lookups with 71 hits and 0 inserts,
and one of which (100 km from anything) wrote 80 `'selection'` scenes, 75
with an `ST_Polygon` footprint. **The same will be true of a production step-2
sweep**, and a prediction for it should not expect `selected_by` to fill in
bulk. STATUS.md NORM-12.

### The change conditions still hold

Rule 1 is untouched: `timeline_task_years` references neither table and this
batch did not make it. Rule 2's `group_key` is the same `encode_group_key`
string in both shapes — the parity check joins on it. Rule 3's uniqueness held
through a 43-parcel sweep. Rule 4 remains true only of the `enriched` and
`selection` rows; the `snapshot` rows' footprints are still NULL.


---

## Amendment — 2026-08-29, step 3's read cutover, built locally

Appended after the five serving reads were moved from `imagery_snapshots` to
`parcel_scenes` joined to `scenes` and a field-by-field parity harness scored
a prediction. Everything above is unedited. Sources:
`docs/audits/2026-08-normalization/STEP3-REPORT.md` and the "Observed" half of
`.../PREDICTION-STEP3.md`, with the capture `.../step3-parity-local.md`.
Commits: `0181c54` (both paths alive + the harness), `dad8502` (prediction),
`160e7ba` (scoring), `33d952a` (shape freeze + tests), `b1acf9a` (the
cutover).

**Not deployed.** Step 3 is committed and has run against the local database
only. Production still serves from `imagery_snapshots` and reads neither new
table.

### The migration text says "the listing endpoint, Titiler callback, preview renderer, and warmup"; the list that moved is five sites

Step 4's text above enumerates read sites informally. The scope actually used
is `STEP1-REPORT.md` §7 — the inventory `VERIFICATION.md` item 3 derived and
step 1 carried forward verbatim — of which five are *serving* reads:
`get_imagery_snapshots`, `get_snapshot_by_id`, `count_imagery_snapshots`, the
featured-parcels query, and `revalidate_landsat.py`'s parcel selection. The
tile proxy and `/warmup` are consumers of `get_snapshot_by_id` rather than
sites of their own.

**The sixth site did not move and must not be read as an oversight.**
`reconcile_source_snapshots`' existing-rows pull still reads
`imagery_snapshots`, because the dual-write continues until step 4 and the
reconciler legitimately diffs against the old table. So step 3's
delete-the-fix standard is **"no serving path touches `imagery_snapshots`"**;
step 4 inherits "no code does". That distinction is written into
`tests/test_read_cutover.py`'s docstring.

### No feature flag, recorded as a decision

The cutover is a code change and its rollback is reverting the deploy — CI
deploys on push and `/api/v1/health` reports the running sha, both proven
cheap through this arc. A flag would have to keep the old serving reads alive
to have anything to fall back to, which is exactly what the delete-the-fix
standard forbids: there would be nothing to delete and no test that could
fail.

### The served id is now `parcel_scenes.id`

`parcel_scenes.id` is a fresh UUID per row and is never equal to the
`imagery_snapshots.id` for the same served period, so the API hands out a
different id at `/parcels/{id}/imagery` and `/featured` and resolves the same
new space at `/imagery/{id}/tiles`, `/warmup` and `/stac`. Both ends moved in
one commit. The substitution is well-defined and was measured, not assumed:
**12,373 id pairs across four sites resolved to exactly 3,082 distinct old
ids and 3,082 distinct new ids**, with no inconsistency and no collision.

Two costs are accepted: a browser holding a page across the deploy has stale
ids until it refetches, and every `stac:{snapshot_id}` Redis key is cold once.
Nothing durable stored a snapshot id.

### `additional_cog_urls` is reconstructed in Python, in array order

Rule 5 made mosaics references; the read turns them back into the URL array
the response contract carries. The resolution is one batched query plus a
Python loop rather than `unnest(...) WITH ORDINALITY`, because the SQLite test
database cannot express the SQL form and the order is the property most worth
a test that runs on both. A reference resolving to no `scenes` row is logged
and dropped rather than failing the listing — the primary still renders, and
neither database has ever held a dangling reference.

### Item facts can still disagree, and the cutover decides which copy wins

The Context section's first consequence — "item facts are stored N times and
can disagree" — is what the parity run measured, and it is the only class of
divergence it found. `scenes` is insert-only and the snapshot upsert never
rewrites `resolution_m`, so the two shapes agree about any row they were
written together from and can disagree about one written twice. Locally, one
NAIP item served by four parcels has three copies saying `1.0` (pre-NORM-9)
and one saying the item's real `0.3`; the backfill collapsed them to one
`scenes` row whose tie-break kept a `1.0`, and **after the cutover all four
parcels serve 1.0**.

That is rule 4's promise — item facts refreshable in one row — being *needed*
rather than merely available: nothing implements the refresh yet, so the
surviving copy is whichever was written first. Production had no such
disagreement on 2026-08-29 (all 1,305 NAIP snapshot rows and all 1,102 NAIP
`snapshot` scenes rows at 1.0), so the class is not open there today.
STATUS.md NORM-18.

### Step 4's "measured, not assumed" needs two instruments, not one

Step 4 above says "log every read; expect zero". A log names *which* caller
read the table and cannot see a reader that does not call it — which is the
failure mode "expect zero" is most exposed to. So the batch built both halves:
`log_imagery_snapshots_read` (one event per reconcile pull, ~4 per
parcel-run) names the one legitimate reader, and `scripts/snapshot_reads.py`
differences `pg_stat_user_tables` across the cooling period, counting every
access by anything without naming any of them. The counters are incremented by
writes too and reset on `pg_stat_reset`, both of which the script says rather
than leaving to be rediscovered.

### The production sequence is not "deploy HEAD"

The harness needs both read paths alive, so it can only run against
production from `160e7ba`. A production session deploys that, runs
`scripts/compare_read_paths.py` read-only with a prediction written first, and
only then deploys the cutover. `STEP3-REPORT.md` §9.
