# Normalization step 2 — the dual-write, built and swept locally

Step 2 of `docs/adr/0001-imagery-normalization.md`:
`reconcile_source_snapshots` writes `scenes` and `parcel_scenes` alongside
`imagery_snapshots`, in one transaction. Step 3 (read cutover) and step 4
(retirement) were not started and no read path was touched.

**Production was not touched.** No `fly ssh`, no production credentials, no
query against Neon. Migration 0017 and the dual-write are committed and have
run against the **local** database only. A mitigation that isn't running
isn't mitigating, and none of this is running.

**Outcome: parity holds, 0 violations in either direction over 3,082 rows**,
with duplicate groups 0, duplicate `(collection, item_id)` 0, dangling mosaic
references 0, and `provenance = 'mosaic_url'` still 0 after four pipeline
runs that catalogued 21 new NAIP tiles. Nine of the eleven predicted
quantities confirmed; one had no prediction; one deviated in scope and is
explained below.

Built on `782b19f`; this batch's commits:

| Commit | Unit |
|---|---|
| `61d486b` | migration `0017_scenes_provenance_selection.py` + ORM/test DDL |
| `9526805` | the dual-write, and the three fidelity fixes riding with it |
| `17c488e` | `backend/tests/test_scene_dual_write.py` |
| `fa0840e` | `PREDICTION-STEP2.md`, **before** the sweep |
| `d9e5587` | the same file's Observed half, after it |
| *(this batch)* | this report, the ADR amendment, STATUS.md |

---

## 1. The design decisions, and the reasoning behind each

### 1a. `provenance = 'selection'` — a fourth value, not a widened one

**Flagged here as the prompt asks, because it is the decision most likely to
be second-guessed.** Migration 0017 is pure DDL against head `0016`
(`SELECT version_num FROM alembic_version` → `0016` before the run), one
CHECK dropped and recreated, upgrade → downgrade → upgrade verified clean and
the resulting `pg_get_constraintdef` read back:

```
CHECK ((provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text,
                                'enriched'::text, 'selection'::text])))
```

The alternative was widening `'snapshot'` to mean "copied from
`imagery_snapshots` *or* written by the pipeline". Rejected on the same
grounds 0016 rejected relabelling enriched rows, plus one that is specific to
this migration and stronger:

* `'snapshot'` has a meaning frozen in three documents (0015's docstring, the
  `Scene` model, the ADR's first amendment): *copied from an
  `imagery_snapshots` row*. A pipeline-written row is not a copy of anything.
* **`provenance = 'snapshot'` is a live work-queue definition, not just a
  label.** It is exactly NORM-7's deferred footprint pass — the 6,156
  production rows whose `footprint` is NULL. A `'selection'` row has a
  footprint from birth. Folding the new rows into `'snapshot'` would make
  that queue definition silently wrong the first time the pipeline ran, and
  the pass would then re-fetch items whose geometry the database already
  held.
* Both predicates readers already use survive unchanged: "is this `item_id`
  catalogued" is `provenance <> 'mosaic_url'`, and "was this copied out of
  `imagery_snapshots`" is `provenance = 'snapshot'`.

Observed after the sweep: `landsat/selection 43`, `naip/selection 21`,
`sentinel2/selection 11`, `usgs_topo/selection 5` — 80 rows the old
vocabulary could not have described honestly.

### 1b. The resolution rule (NORM-9 + NORM-11)

`normalize_resolution_m` (`app/services/imagery.py`) is the one named
function, with the NORM-11 citation adjacent to it:

> **Round the item's `gsd` to two decimals, once, at write time.**

Checked against the values that actually occur — NAIP 0.3 / 0.5 / 0.6 / 1.0,
Landsat 30, Sentinel-2 10. The closest real pair is 0.1 m apart, so rounding
cannot merge two resolutions; and it absorbs noise four orders of magnitude
larger than the ~1e-14 that `ENRICH-PROD-REPORT-2.md` F2 measured. All seven
noisy production spellings of 0.6 are in the test as literals.

**What the rule costs, stated rather than glossed:** the upstream double is
not recoverable from the column. That is the deliberate half of the choice.
`resolution_m` answers "how fine is this image", whose honest answer is a
nominal resolution; the exact `gsd` is one STAC fetch away, and the column
never held it anyway — for NAIP it held the constant `1.0`.

**Both shapes switched, in the same commit.** `imagery_snapshots.resolution_m`
now comes from the item too, via the same `SelectedScene` field the `scenes`
row is written from, so the two tables cannot disagree about a row they were
written from together. The alternative — leave `imagery_snapshots` on the
constant until step 3 — would have created a *new* disagreement between the
two shapes for every row written between now and the cutover, which is the
exact defect NORM-9 already describes between provenances. The user-visible
consequence is intended: a new NAIP row's "1m res" chip becomes "0.3m res"
where the item says 0.3, which is the fix working.

Observed: the two probe parcels' 17 new NAIP snapshot rows carry 0.3 (2), 0.6
(4), 1.0 (11). The 306 pre-existing rows are still 1.0 — see F2.

### 1c. Insert-only for `scenes`

`_ensure_scene` inserts with `ON CONFLICT (collection, item_id) DO NOTHING
RETURNING id`, falling back to a `SELECT` when nothing is returned. A present
row is left exactly as it is: re-encountering an item is not evidence its
stored facts are stale, and refreshing item facts is a separate mechanism
that does not exist yet.

`DO NOTHING` rather than check-then-insert so a concurrent worker inserting
the same item is an ordinary outcome instead of an `IntegrityError` that
aborts the reconciler's transaction — which, since the transaction now also
carries the `imagery_snapshots` deletes, would be a worse failure than it was
before.

Observed at its sharpest on the DC probe: **71 lookups, 71 hits, 0 inserts**,
because five DC parcels already served every item it selected (329 shared
`parcel_scenes` rows). One item, one row, however many parcels serve it — the
ADR's premise, measured.

### 1d. `selected_by`, and what an unchanged selection means

`selected_by` is `get_settings().git_sha` — the same value
`app/api/v1/health.py:39` reports and `create_queued_request` already writes
to `timeline_requests.deployed_sha`. Locally that is the literal `dev`, and
it is written verbatim rather than suppressed: `dev` is an honest answer and
a NULL would be indistinguishable from a backfilled row.

`_upsert_parcel_scene` leaves an **unchanged** selection completely alone — no
new `selected_at`, no `selected_by`. The reasoning: `selected_at` answers
"when did this parcel come to serve this scene for this period", and a sweep
that re-picks the same scene has not made a selection. Bumping it would turn
the column into "when did the last sweep run", which every task's
`completed_at` already says.

The consequence, which is worth being explicit about because it is
counter-intuitive: after a full sweep, a backfilled row whose selection was
re-confirmed **still has `selected_by = NULL`**. That remains true, not
misleading — NULL means "no dual-writing run has attributed this selection",
and for a backfilled row the SHA that originally chose it genuinely is not
recorded anywhere (ADR amendment, "Selection provenance is not recoverable").
After step 3 there are no backfilled rows and every row is attributed at
insert.

### 1e. Deletion mirroring, and the absent-group rule

Three cases, and only one of them deletes anything in `parcel_scenes`:

| Case | `imagery_snapshots` | `parcel_scenes` |
|---|---|---|
| Group selected this run, different item | old row deleted | row **updated in place** — same PK, new `scene_id` |
| Group absent from the selection | left alone | left alone |
| Group absent **and** this run named the item `suppressed` | row deleted | row deleted, but only if it serves *that* item |

The third is deliberately narrow: `_delete_parcel_scene_for_item` matches on
`(group_key, collection, item_id)`, so a group that has since moved to a
different scene is a selection this run said nothing about and is not
touched. The property that has to hold is "the two tables agree about which
groups exist", not "delete whatever is there".

The absent-group rule is why the mirroring is written this way rather than as
"delete the `parcel_scenes` row for every stale snapshot row": a stale row in
a *selected* group is replaced, not removed, and treating it as a removal
would leave a window in which `parcel_scenes` had lost a group
`imagery_snapshots` still had.

### 1f. What "one transaction" does and does not cover

The `imagery_snapshots` deletes, the `parcel_scenes` deletes, the `scenes`
inserts and the `parcel_scenes` upserts now share one `db.commit()` at the
end of `reconcile_source_snapshots`. A failure anywhere in that span commits
none of it, observed from a separate session in
`test_a_failure_before_the_parcel_scenes_write_commits_neither`.

**It does not cover the snapshot inserts**, which happen earlier in
`_search_and_persist_source` and commit per row inside
`upsert_imagery_snapshot`. That is unchanged from before this batch and is
recorded as F3 rather than quietly relied on.

### 1g. `SelectedScene`

One frozen dataclass carrying one item's facts to both writes, built once per
item in `timeline.py` and consumed by both the upsert and the dual-write, so
the two shapes cannot derive a field differently. `mosaic` holds the
additional tiles as `SelectedScene`s of their own — the primary is never a
member of its own mosaic, matching `parcel_scenes.mosaic_scene_ids`.

The `selected` parameter accepts `tuple[str, date] | SelectedScene`. The
tuple form writes `imagery_snapshots` only and is what a caller with no item
in hand passes; both production call sites pass `SelectedScene`s. One
parameter rather than two, so the delete-driver and the dual-write cannot be
given different selections.

**One behaviour deliberately not changed:** only the primary's item id joins
the `keep` set. A mosaic's additional tiles are not `imagery_snapshots` rows
of their own, so keeping a row whose id is this run's *second* tile would
leave two rows in one group — G3's shape. They are first-class `scenes` rows
and nothing more.

### 1h. Two helpers moved into `app/`

`platform_for` and the footprint-WKT derivation moved out of `scripts/` into
`app/services/imagery.py` and `app/services/stac.py`, with
`scripts/backfill_scenes.py` and `scripts/enrich_synthesized_scenes.py`
importing them. Three writers of the same two columns had two copies of each
rule between them; a MultiPolygon rejected by one and accepted by another
would put different geometries in one column depending on which writer
reached the item first.

## 2. Tests

Twelve tests in `backend/tests/test_scene_dual_write.py`. Full suite after
the batch: **703 passed, 7 skipped**. `ruff check`, `ruff format --check` and
`mypy app/` all clean (`Success: no issues found in 48 source files`).

**Delete-the-fix, verified by running it.** Each mutation was applied, the
covering test run, and the mutation reverted:

| Removed / changed | Covering test | Result |
|---|---|---|
| the `_write_selection_shapes` call | parity | FAILS |
| the `upsert_imagery_snapshot` call | parity | FAILS |
| `ON CONFLICT DO NOTHING` → `DO UPDATE` | insert-only | FAILS |
| the `mosaic_ids` comprehension | mosaic tiles | FAILS |
| the UPDATE branch of `_upsert_parcel_scene` | replacement | FAILS |
| the `unchanged` early return | `selected_at` stability | FAILS |
| the `_delete_parcel_scene_for_item` loop | suppressed mirror | FAILS |
| the `if group_key in groups` guard | absent-group rule | FAILS |
| `selection.resolution_m` → `source_cfg["resolution_m"]` | NAIP resolution | FAILS |
| reading `gsd` at all | NAIP resolution | FAILS |
| `db.commit()` moved above the dual-write | transactionality | FAILS |
| `selected_by` → NULL | sha + footprint | FAILS |
| `footprint` → NULL | sha + footprint | FAILS |
| `round(...)` → `float(...)` | the rounding rule | FAILS |

Fourteen mutations, fourteen failures. *(`17c488e`'s message says "Thirteen"
above a list of fourteen; the count in the message is wrong and the list is
right. Left uncorrected rather than amended, because the hash is cited here
and in STATUS.md.)* **Zero changes to any
`imagery_snapshots` read site**, which is the constraint step 3 inherits and
step 3 is the step that breaks.

The parity test runs the **real** NAIP fetch loop (`_fetch_source` with a
mocked STAC search) rather than calling the reconciler directly, so removing
either write in the pipeline — not just in the service — fails it.

## 3. The sweep

`scripts/requeue_parcels.py --skip-deploy-check --sources
naip,landsat,sentinel2,usgs_topo` over all 43 local parcels, 23:17:25–23:22:25Z:
43 queued, 0 skipped, 43 complete, **3,373 fresh ledger rows**.
`--skip-deploy-check` for the same reason step 1's sweep used it — a local
image reports `GIT_SHA=dev`, so `--require-sha` cannot be satisfied and the
script requires exactly one of the two.

### 3a. The sweep took the idempotent branch its own prediction named

Over the 43 swept parcels, **nothing moved**: `scenes` 1,262 → 1,262,
`parcel_scenes` 2,945 → 2,945, `selected_by` NULL on all 2,945, NAIP
`resolution_m` 1.0 on all 306. Every one of the 2,943 `ok` groups passed
through the dual-write, found its scene present and its selection unchanged,
and wrote nothing.

That is correct behaviour and also, by itself, weak evidence: a dual-write
that never ran would leave the same table. `PREDICTION-STEP2.md` §4 said so
in advance and named the 20 `stac_403` groups as the expected source of
insert-path coverage. **They did not supply it** — 11 landsat → 2 and 9
sentinel2 → 0, and the successes landed on items `scenes` already held,
because Landsat and Sentinel-2 scenes are shared between nearby parcels.

### 3b. So the insert path was forced, additively

Two probe parcels were **inserted** into the local database. No row was
deleted at any point in this session — a `DELETE` of one parcel's
`parcel_scenes` rows was the first idea, was refused by the harness as a
destructive action, and was replaced by the additive design rather than
retried. The additive version is the better experiment anyway: it exercises
the insert path for all four sources on a parcel that has never been served.

| Probe | Location | Result |
|---|---|---|
| `1111…5555` | 1600 Pennsylvania Ave NW, DC | 71 snapshots / 71 `parcel_scenes`, all `selected_by = 'dev'`; **0 new `scenes`** |
| `2222…6666` | 38.5 N, 98.5 W (Great Bend, KS), nearest existing parcel > 100 km | 66 snapshots / 66 `parcel_scenes`; **80 new `scenes`, all `provenance = 'selection'`** |

Both probe parcels are still in the local database and are listed in §7 so a
later measurement does not read them as organic.

### 3c. What the `selection` rows carry

| source | rows | footprint | bbox | resolution_m | platform | cloud |
|---|---|---|---|---|---|---|
| landsat | 43 | 43 | 43 | 43 (all 30) | 43 | 43 |
| naip | 21 | 21 | 21 | 21 — 0.3 (3), 0.6 (6), 1.0 (12) | 0 | 0 |
| sentinel2 | 11 | 11 | 11 | 11 (all 10) | 11 | 11 |
| usgs_topo | 5 | **0** | 5 | 0 | 0 | 0 |

All 75 STAC-sourced footprints are `ST_Polygon`. The five NULLs are exactly
the topo rows: a TNM product carries no geometry, no `gsd` and no platform,
which is the same shape the step-1 backfill wrote for topo.

**The requirement is met: a pipeline-written scene has its footprint from
birth**, so the synthesized-candidate class (STEP1-REPORT F1) cannot grow.
`provenance = 'mosaic_url'` stayed at 0 through four pipeline runs that
catalogued 21 NAIP tiles — every one of which, under the old code, would have
become a URL in an array for a later pass to guess an item id out of.

### 3d. Idempotence, observed rather than asserted

The Kansas parcel was run a second time through the full pipeline. An md5
over `(source, group_key, scene_id, mosaic_scene_ids, selected_at,
selected_by)` for all 66 of its rows is identical before and after —
`eb608d8aec7feafa9aa09f75e9992a94` — and the three table counts did not move.

### 3e. Scorecard

Full detail in `PREDICTION-STEP2.md`; the prediction half was committed
(`fa0840e`) before the sweep ran and has not been edited.

| # | Quantity | Predicted | Observed | Verdict |
|---|---|---|---|---|
| P1 | Parity violations, both directions | 0 | 0 / 0 over 3,082 rows | confirmed |
| P2 | Duplicate `(parcel_id, source, group_key)` | 0 | 0 | confirmed |
| P3 | Duplicate `(collection, item_id)` | 0 | 0 | confirmed |
| P4 | Dangling `mosaic_scene_ids` | 0 | 0 | confirmed |
| P5 | `parcel_scenes` = `imagery_snapshots` | equal | 3,082 = 3,082 | confirmed |
| P6 | `scenes` = 1,262 + N, N ∈ 0–60 | band | N = 80 | **deviation (scope)** |
| P7 | `scenes` deleted | 0 | 0 | confirmed |
| P8 | `mosaic_url` rows | 0 | 0 | confirmed |
| P9 | `selected_by` = inserted-or-changed rows | — | 137, all inserts | confirmed |
| P10 | NAIP resolution still 1.0 on old rows | yes | 306/306 | confirmed |
| P11 | `imagery_snapshots` after | none | 3,082 | — |

**P6's deviation is scope, not behaviour.** The band was derived for the 43
swept parcels; the Kansas probe did not exist when the prediction was
committed, and its 80 rows are one parcel's whole imagery history
(43+21+11+5). P6's stated mechanism — `scenes` grows only by items the table
does not already hold — held exactly. The prediction was not edited to fit.

### 3f. Parity, and one check the prediction did not name

Parity is defined on `(parcel_id, source, group_key)` → `(collection,
item_id)`, with `group_key` = `encode_group_key(scope, capture_date)`,
`scope` = `decade` for topo and `year` otherwise. `EXCEPT` in both directions
over the full tuple returns **0 and 0**.

Mosaics are checked for resolvability rather than equality, because the two
shapes represent them differently by design. But a stronger check was
available and was run: every one of the **176 references resolves to a
`scenes` row whose `cog_url` is a member of the same group's
`additional_cog_urls` array — 176 of 176**. The two representations name the
same tiles, not merely the same number of them. Row counts match too: 148
rows carrying a mosaic on each side.

### 3g. The ledger, read alongside (NORM-3)

| source | ok | other |
|---|---|---|
| landsat | 1,847 | 2 `failed`/`stac_403` |
| naip | 306 | 420 `absent`/`no_scenes`, 5 `suppressed`/`naip_no_point_coverage` |
| sentinel2 | 516 | — |
| usgs_topo | 274 | 3 `indeterminate` (TNM row cap, pre-existing) |

The two failures are single Landsat years on two parcels — Death Valley 1996
and 1600 Amphitheatre Pkwy 2004. Neither left a duplicate group and under the
absent-group rule neither cost a row in either table. **So P2 = 0 is a real
zero and not one resting on an unretried upstream failure**, which is the
reading NORM-3 requires. They remain `failed` and therefore retryable; no
retry was run, because clearing them was not this batch's job and doing so
would have changed the table the parity check had just been taken over.

## 4. Findings

### F1 — A current database cannot exercise a dual-write's insert path

**Method finding, resolved within the batch.** The local database had been
swept hours earlier, so the sweep re-selected exactly what it already served
and the dual-write correctly wrote nothing. The prediction named this branch
in advance and named the wrong escape from it (the `stac_403` retries, which
cleared onto already-catalogued items). The escape that worked was a probe
parcel in a region the database had never covered.

Worth writing down because **the same thing will happen in production**. The
production database was fully swept on 2026-08-25 and backfilled on
2026-08-28; a step-2 production sweep will find most selections unchanged and
will therefore write far less than its row counts suggest. A production
prediction that expects `parcel_scenes.selected_by` to fill in bulk would be
wrong. Recorded as STATUS.md NORM-12.

### F2 — The NORM-9 fix reaches new `imagery_snapshots` rows only

**New. Open, unfixed, and a direct consequence of this batch.**

`upsert_imagery_snapshot`'s `ON CONFLICT (parcel_id, stac_item_id) DO UPDATE`
sets `cog_url`, `additional_cog_urls` and `thumbnail_url` — and nothing else
(`app/services/imagery.py`, both branches of the statement). So a NAIP row
that already exists keeps `resolution_m = 1.0` even on a run that read the
item's real `gsd` for it. Only a row the run *inserts* carries the item's
resolution.

Measured: after a full sweep of all 43 parcels, all **306** pre-existing NAIP
snapshot rows still say 1.0; the 17 NAIP rows the two probes inserted carry
0.3 (2), 0.6 (4), 1.0 (11). The matching `scenes` rows behave the same way for
a different reason — insert-only.

This is what the prompt specified ("Old `imagery_snapshots` rows keep 1.0
either way; that is recorded, not healed here"), so it is not a defect
against the spec. It is recorded because the *shape* of the remainder is not
obvious from the fix: **the population that keeps 1.0 is not "rows written
before the deploy", it is "rows that still exist at any later time", and no
amount of sweeping shrinks it.** Clearing it needs either a heal that
rewrites `resolution_m` from `scenes`, or a widened `DO UPDATE`. Both are
decisions about what a re-run may overwrite, which is the same question
insert-only answers for `scenes`, and neither belongs in this batch.
Recorded as STATUS.md NORM-13.

### F3 — Atomicity covers the reconciler, not the whole persist loop

**Restated, not new; the boundary moved and the new boundary is worth
naming.** Within `reconcile_source_snapshots` the two shapes commit together
or not at all, tested from a separate session. Outside it,
`upsert_imagery_snapshot` still commits per row, so the sequence for a source
is: N snapshot upserts, each committing, then one transaction carrying the
deletes and the whole normalized write.

An interruption between the two therefore leaves new `imagery_snapshots` rows
with no `parcel_scenes` row. That is recoverable — the next run's reconcile
writes them — and it is the same direction the existing ordering already
chose deliberately ("an interruption leaves duplicates, which is recoverable,
rather than an empty timeline, which isn't"). Making it fully atomic means
un-committing `upsert_imagery_snapshot`, which the ledger's write ordering
also depends on; that is a larger change than step 2 and would be spent on a
window step 4 closes anyway. Recorded as STATUS.md NORM-14.

### F4 — The SQLite test database cannot hold a NAIP mosaic

**Pre-existing, restated.** `additional_cog_urls` is a PostgreSQL array that
SQLite cannot bind, and `bbox` reaches `ST_GeomFromEWKT`, which SQLite has
no function for. The existing ledger harness already patches
`extract_bbox_wkt` for the second reason; the mosaic test additionally
replaces `upsert_imagery_snapshot` with a mock for the first, and uses the
mock to assert that the URL array and the reference array name the same
tiles. The `scenes`/`parcel_scenes` writes themselves run unmocked against
SQLite in every test.

So the mosaic write path's *`imagery_snapshots` half* is covered by the local
Postgres sweep (148 rows / 176 entries, agreeing with the reference arrays)
rather than by a unit test. Noted so the coverage claim is not read as
stronger than it is.

### F5 — NORM-6's parcel duplication, seen again by accident

The DC probe was inserted at 1600 Pennsylvania Ave NW expecting fresh
coverage. The database already held **five** parcels within 60 km, two of
them the same White House address geocoded to different points
(38.899/-77.035 and 38.898/-77.037). That is NORM-6's shape, unchanged and
still unfixed; it is mentioned only because it explains why that probe wrote
0 new scenes and because it is a third independent sighting.

## 5. Deviations from the prompt

1. **Requirement 1's "commit together or not at all" is implemented at the
   reconciler, not across the whole persist loop.** F3 has the reasoning and
   the boundary. The prompt scoped the dual-write to
   `reconcile_source_snapshots`' transaction and that is where it is; the
   snapshot *inserts* were already outside any such transaction before this
   batch.

2. **The local sweep was extended past "one full sweep".** Two probe parcels
   and one idempotence re-run, for the reason F1 gives. Every extension is
   additive; nothing was deleted or updated by hand.

3. **The mosaic-tile test drives the pipeline but mocks the snapshot
   write.** F4's reasoning. The alternative was not testing multi-tile NAIP
   through the pipeline at all.

4. **`platform_for` and the footprint derivation moved into `app/`**, and two
   scripts now import them. Not asked for; §1h has the reasoning. The
   alternative was a third copy of both rules in the service layer.

5. **`selected_by` is written even when it is the literal `dev`.** The prompt
   says to populate it from the running image's SHA; locally that string is
   `dev`. Suppressing it would have made a local row indistinguishable from a
   backfilled one, which is the distinction requirement 4 exists to protect.

6. **The two `stac_403` groups were not retried.** Clearing them would have
   changed the table the parity measurement had just been taken over, and
   they cost nothing in either shape.

## 6. What this does not do

* **No read path moved.** The six production read sites carried forward in
  `STEP1-REPORT.md` §7 read `imagery_snapshots` exactly as before, and the
  full suite passes with zero changes to any of them. Step 3 owns the
  cutover.
* **No production anything.** Migration 0017 is not deployed; the dual-write
  is not deployed; no production sweep is authorized or was attempted.
* **No heal.** The 306 local (1,102 production) NAIP rows carrying the 1.0
  constant are unchanged, as are the 6,156 production `snapshot` scenes rows
  with NULL footprints (NORM-7's deferred pass).
* **The ledger is untouched** beyond what reconciliation already did. ADR
  rule 1 holds: `timeline_task_years` references neither new table, and
  nothing in this batch made it.

## 7. State left behind, locally

* `scenes`: **1,342** — 1,174 `snapshot` + 88 `enriched` + **80 `selection`**,
  0 `mosaic_url`.
* `parcel_scenes`: **3,082**, of which 137 carry `selected_by = 'dev'` and
  2,945 carry NULL; 148 carry a mosaic, 176 references, 0 dangling.
* `imagery_snapshots`: **3,082**, 0 duplicate groups.
* `alembic_version`: `0017`.
* **Two probe parcels, added by this session and still present:**
  `11111111-2222-3333-4444-555555555555` (1600 Pennsylvania Ave NW, DC) and
  `22222222-3333-4444-5555-666666666666` (38.5 N, 98.5 W, Great Bend KS).
  Both were inserted deliberately; neither is an organic geocode, and a later
  local measurement that counts parcels should know they are here. Nothing
  else was inserted and nothing was deleted.
* Two `failed`/`stac_403` ledger rows, retryable, deliberately not retried.

## 8. State of the record

* ADR `0001` gains an amendment covering the dual-write, the `'selection'`
  provenance decision, the resolution rule, and the `selected_by` semantics.
  Nothing above the amendment line was edited.
* STATUS.md: NORM-9 and NORM-11 move to resolved-in-code-pending-deploy with
  the commit; NORM-1 gains step 2's line; three new rows NORM-12, NORM-13 and
  NORM-14; the Scheduled item's step-2 entry updated; the fix-commits table
  gains this batch.
* **Deploy state, stated plainly:** migration 0017 and the dual-write are
  committed and have run against the local database only. They have not been
  deployed. Production still runs the pre-step-2 pipeline, which writes
  `imagery_snapshots` alone and writes NAIP resolution as the constant 1.0.
