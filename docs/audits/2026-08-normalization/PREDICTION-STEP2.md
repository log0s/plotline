# Prediction — step 2's local sweep

Written and committed **before** the sweep ran, per the record rule
"predictions before actions". The Observed half is appended afterwards and
this half is never edited.

Step 2 is the dual-write: `reconcile_source_snapshots` writes `scenes` and
`parcel_scenes` alongside `imagery_snapshots`, in one transaction. The sweep
re-queues every local parcel across all four imagery sources and asks one
question: **after a full pipeline run, do the two shapes agree?**

Code under test: `61d486b` (migration 0017), `9526805` (the dual-write),
`17c488e` (tests). Local `alembic_version` = `0017`, verified. Production is
untouched and stays untouched; nothing here is a production claim.

---

## 1. The state the sweep starts from

Measured read-only against the local database at 2026-08-28, immediately
before writing this file.

| Quantity | Value |
|---|---|
| parcels with imagery | 43 |
| `imagery_snapshots` rows | 2,945 (landsat 1,849 / naip 306 / sentinel2 516 / usgs_topo 274) |
| distinct `(stac_collection, stac_item_id)` | 1,174 |
| duplicate `(parcel_id, source, group_key)` groups | 0 |
| rows carrying a mosaic / `additional_cog_urls` entries / distinct such URLs | 141 / 162 / 115 |
| `scenes` rows | 1,262 — 1,174 `snapshot` + 88 `enriched`, 0 `mosaic_url`, 0 `selection` |
| `parcel_scenes` rows | 2,945; 141 carry a mosaic; **0 carry a `selected_by`** |
| NAIP `imagery_snapshots.resolution_m` | 1.0 on all 306 rows (NORM-9's constant) |
| newest `imagery_snapshots.created_at` | 2026-08-28 16:36:26Z |
| newest `timeline_task_years.created_at` | 2026-08-28 16:39:19Z |

**The ledger this starts from**, read alongside the counts per NORM-3 — a
duplicate-group or parity measurement is only as complete as the sweep behind
it:

| source | outcome | reason | rows |
|---|---|---|---|
| landsat | ok | | 2,096 |
| landsat | **failed** | **stac_403** | **11** |
| naip | ok | | 306 |
| naip | absent | no_scenes | 420 |
| naip | suppressed | naip_no_point_coverage | 5 |
| sentinel2 | ok | | 579 |
| sentinel2 | **failed** | **stac_403** | **9** |
| usgs_topo | ok | | 274 |
| usgs_topo | indeterminate | TNM row cap | 3 |

The **20 `failed`/`stac_403` groups** matter to this prediction out of
proportion to their number: see §4.

The sweep is
`scripts/requeue_parcels.py --skip-deploy-check --sources naip,landsat,sentinel2,usgs_topo`
over all 43 parcel ids — the same shape step 1's sweep used, and
`--skip-deploy-check` for the same reason (a local image reports
`GIT_SHA=dev`, so `--require-sha` cannot be satisfied).

`GIT_SHA` is `dev` in both local containers, so `selected_by` on a row this
run writes will be the literal string `dev`. That is the value the health
endpoint would report, written verbatim rather than suppressed: a local run
saying `dev` is an honest answer, and a NULL would be indistinguishable from
a backfilled row.

## 2. The parity definition being predicted

For every `(parcel_id, source, group_key)`:

* `imagery_snapshots` holds a row iff `parcel_scenes` holds a row, and
* the `parcel_scenes` row's scene has `(collection, item_id)` equal to the
  snapshot row's `(stac_collection, stac_item_id)`.

`group_key` is `encode_group_key(scope, capture_date)` with `scope` =
`decade` for `usgs_topo` and `year` for the other three — the same derivation
`reconcile_source_snapshots` and `scripts/backfill_scenes.py` both use.

**Predicted disagreements in either direction: 0.**

## 3. The quantities

| # | Quantity | Prediction |
|---|---|---|
| P1 | Parity violations (either direction) | **0** |
| P2 | Duplicate `(parcel_id, source, group_key)` groups in `imagery_snapshots` | **0** |
| P3 | Duplicate `(collection, item_id)` pairs in `scenes` | **0** |
| P4 | Dangling `mosaic_scene_ids` references | **0** |
| P5 | `parcel_scenes` row count | **= `imagery_snapshots` row count** (P2 makes the two equal by definition) |
| P6 | `scenes` rows after | **1,262 + N**, `N` = distinct newly-selected `(collection, item_id)` not already held. `N` band **0–60**, most likely **0–25** |
| P7 | `scenes` rows deleted | **0** — the dual-write is insert-only and nothing else writes the table |
| P8 | `scenes` with `provenance = 'mosaic_url'` | **0**, unchanged — the enrichment pass emptied that queue and nothing re-fills it |
| P9 | `parcel_scenes` with `selected_by = 'dev'` | **= the number of rows this run inserted or changed**, which is **not** the number of groups it selected. See §5 |
| P10 | NAIP `imagery_snapshots.resolution_m` distribution | **still 1.0 on every pre-existing row**; a real gsd only on rows this run *inserts*. See §5 |
| P11 | `imagery_snapshots` rows after | 2,945 + (new selections) − (superseded rows reconciliation deletes). No prediction of the exact number; the ledger explains any movement |

### Deriving P6

`scenes` can only grow, and only by items the table does not already hold.
Three sources of growth, in descending expected size:

1. **The 20 `stac_403` groups retrying.** Those `(parcel, source, year)`
   groups currently hold no row at all. If a retry succeeds it selects an
   item — but Landsat and Sentinel-2 scenes are shared across nearby parcels,
   so most successes will land on an item `scenes` already holds. Upper bound
   20; expected well under that.
2. **A different item chosen for a group already served.** The Landsat and
   Sentinel-2 validation walks re-sign assets live, so a year that swapped to
   a fallback last time may not this time, or vice versa. Each such change is
   one new `scenes` row (append-only) and one `parcel_scenes` row updated in
   place. Unbounded in principle; expected single digits.
3. **A NAIP mosaic tile never catalogued.** Expected **0**, and this is the
   prediction most worth checking. The 115 distinct mosaic URLs already
   resolve to 88 `enriched` + 27 `snapshot` rows, and the enrichment pass
   replaced every candidate id with the catalogued one, verified by `cog_url`
   equality. So a tile the selector picks again is looked up by exactly the
   id Planetary Computer serves and **matches**. A nonzero count here means
   either the selector picked a genuinely different tile, or
   `(collection, item_id)` is not the key the enrichment made it — the second
   would be a finding.

New PC items published since 2026-08-28 16:36Z are counted at **0**: the
window is hours.

### Why P3 and P4 are the load-bearing ones

NORM-7 was the risk that a synthesized row and a real catalogued write become
two rows for one physical tile without tripping `UNIQUE (collection,
item_id)`. The enrichment pass closed it by making every id catalogued. **This
sweep is the first time the dual-write has ever run against a table the
enrichment pass prepared**, so P3 = 0 is the first live evidence for the
argument `ENRICH-PROD-REPORT-2.md` §9 made from the code. A nonzero P3 would
falsify it.

## 4. The honest weakness of this sweep, stated in advance

The local database was fully swept on 2026-08-28 and its selections are
current. If the sweep is perfectly idempotent — every source re-picks exactly
the items it picked before — then:

* `scenes` grows by 0,
* every `parcel_scenes` row is *unchanged* and therefore untouched,
* `selected_by` stays NULL on all 2,945 rows, and
* **the dual-write's insert path is exercised by nothing but the 20 `stac_403`
  retries.**

That is a real limit on what this sweep can prove, and it is written here
rather than discovered afterwards. The insert path is covered by the unit
tests (`tests/test_scene_dual_write.py`, twelve tests, thirteen mutations),
and the sweep's job is the property the tests cannot check: that a *full
pipeline run over a real database* leaves the two shapes in agreement. P1 = 0
over 2,945 rows is that claim, and it holds whether or not anything moved.

If P9 comes back 0, that is the idempotent branch, not a failure of the
dual-write — and the parity check still passes or fails on its own terms.

## 5. Designed divergences — stated before the run, not explained after

Four places where the two shapes will *not* look identical, by design.

1. **Mosaics are references, not a URL array.** `imagery_snapshots` stores
   `additional_cog_urls TEXT[]`; `parcel_scenes` stores `mosaic_scene_ids
   UUID[]` pointing at `scenes` rows. Parity is defined on the primary item
   (§2); the mosaic representations are checked for *resolvability*
   (P4 = 0), not for equality.

2. **`resolution_m` for NAIP will differ between old rows and new ones, in
   both shapes.** `upsert_imagery_snapshot`'s `ON CONFLICT DO UPDATE` sets
   only `cog_url`, `additional_cog_urls` and `thumbnail_url` — **not
   `resolution_m`** — so a NAIP row that already exists keeps the constant 1.0
   even though this run read a real gsd for it. Only a row this run *inserts*
   carries the item's resolution. The matching `scenes` row is insert-only for
   the same reason. So after the sweep, expect NAIP `resolution_m` still 1.0
   on the 306 pre-existing rows. **This is NORM-9 fixed going forward and not
   healed backwards, which is what the prompt specifies**; the heal is
   somebody's separate decision.

3. **`selected_by` is filled on insert and on change, not on confirmation.**
   `_upsert_parcel_scene` leaves an unchanged row completely alone, so a
   backfilled row whose selection this run re-picked keeps `selected_by =
   NULL` and its original `selected_at`. The reasoning: `selected_at` answers
   "when did this parcel come to serve this scene for this period", and a
   sweep that re-picks the same scene has not made a selection — bumping it
   would turn the column into "when did the last sweep run", which every
   task's `completed_at` already says. NULL keeps meaning "no dual-writing run
   has attributed this selection", which for a backfilled row is exactly
   true: the SHA that originally chose it is not recorded anywhere
   (ADR amendment, "Selection provenance is not recoverable"). In steady state
   after step 3 there are no backfilled rows and every row is attributed at
   insert.

4. **`scenes.provenance` will hold four values, and a NAIP tile's resolution
   depends on which.** `snapshot` (backfilled, 1.0 for NAIP, NULL footprint),
   `enriched` (STAC-corrected tile, real gsd, real footprint), `selection`
   (written by this sweep, real gsd, real footprint). `mosaic_url` stays at 0.
   Anything reading `scenes.resolution_m` across provenances is still reading
   two different things — NORM-9's consequence, unchanged by this batch for
   pre-existing rows.

## 6. Stop conditions

The sweep stops and nothing is scored if:

* **P3 > 0** — a duplicate `(collection, item_id)` means the key the whole
  design rests on is not a key. Investigate, do not re-run.
* **P2 > 0 with no `failed` ledger row explaining it** — a duplicate group
  with a clean ledger is silent reconciliation failure, which is the ADR's
  change condition. A duplicate group *with* a `failed`/`stac_403` row for
  that exact `(parcel, source, group)` is NORM-3's known shape and is cleared
  by a ledger-selected retry, as step 1's sweep did.
* **`scenes` count falls** — nothing in this code path deletes a scene.
* **A parity violation whose cause is not one of §5's four divergences.**

## 7. What this predicts nothing about

Production. Migration 0017 is not deployed, the dual-write is not deployed,
and no production sweep is authorized in this session. Every number above is
local.

---

## Observed — local sweep, 2026-08-28

*(appended after the run; the half above is unedited)*

The sweep ran 23:17:25–23:22:25Z: 43 requests queued, 43 complete, **3,373
fresh ledger rows**. It was then extended by two probe runs and one
idempotence re-run, for the reason §4 predicted would be needed. All four
runs are scored together below; the sweep's own numbers are separated where
they differ.

### Scorecard

| # | Quantity | Predicted | Observed | Verdict |
|---|---|---|---|---|
| P1 | Parity violations, both directions | 0 | **0 / 0** over 3,082 rows | confirmed |
| P2 | Duplicate `(parcel_id, source, group_key)` groups | 0 | **0** | confirmed |
| P3 | Duplicate `(collection, item_id)` in `scenes` | 0 | **0** | confirmed |
| P4 | Dangling `mosaic_scene_ids` references | 0 | **0** | confirmed |
| P5 | `parcel_scenes` = `imagery_snapshots` | equal | **3,082 = 3,082** | confirmed |
| P6 | `scenes` = 1,262 + N, N in 0–60 (likely 0–25) | band | **N = 80** | **deviation — band exceeded, cause identified, see below** |
| P7 | `scenes` rows deleted | 0 | **0** | confirmed |
| P8 | `provenance = 'mosaic_url'` | 0 | **0** | confirmed |
| P9 | `selected_by = 'dev'` = rows inserted or changed | — | **137**, all inserts; 0 changes | confirmed |
| P10 | NAIP `resolution_m` still 1.0 on pre-existing rows | yes | **all 306 still 1.0**; new rows 0.3/0.6/1.0 | confirmed |
| P11 | `imagery_snapshots` after | no prediction | 3,082 (2,945 + 137) | — |

### The sweep itself took the idempotent branch §4 named

Over the 43 swept parcels the run selected **exactly the items already
served**: `scenes` unchanged at 1,262, `parcel_scenes` unchanged at 2,945,
`selected_by` NULL on all 2,945, NAIP `resolution_m` still 1.0 on all 306.
Every one of the 2,943 `ok` groups passed through the dual-write and found
its scene present and its selection unchanged, so nothing was written. That
is the correct behaviour and it is also, on its own, weak evidence — a
dual-write that never runs produces the same table.

**So the insert path was forced, additively.** §4 anticipated needing to;
what it did not anticipate is that the 20 `stac_403` groups would not supply
it. They mostly cleared (11 landsat → 2, 9 sentinel2 → 0) and the successes
landed on items `scenes` already held, because Landsat and Sentinel-2 scenes
are shared between nearby parcels — which is the ADR's premise, observed.

Two probe parcels were **inserted** (never deleted; a delete was not
attempted):

| Probe | Location | Result |
|---|---|---|
| `1111…5555` | 1600 Pennsylvania Ave NW, DC | 71 snapshots / **71 `parcel_scenes`, all `selected_by = 'dev'`**; **0 new `scenes`** — every item was already catalogued by one of the five DC parcels the database already held, 329 shared rows |
| `2222…6666` | 38.5 N, 98.5 W (Great Bend, KS); nearest existing parcel > 100 km | 66 snapshots / **66 `parcel_scenes`**; **80 new `scenes`, all `provenance = 'selection'`** |

The DC probe is the sharper of the two: 71 lookups by `(collection,
item_id)`, 71 hits, 0 inserts. That is the insert-only rule and the
one-row-per-item promise, both observed rather than argued.

### P6's deviation, explained

80 new scenes against a predicted 0–60. The prediction's derivation was built
around the *swept* parcels and never assigned a number to a parcel that does
not exist yet — the Kansas probe was invented after the prediction was
committed, to reach the write path the sweep could not. Its 80 rows are 43
landsat + 21 naip + 11 sentinel2 + 5 usgs_topo, which is one parcel's whole
imagery history. **The prediction is not edited to fit**; the deviation is
scope, not behaviour, and P6's mechanism (`scenes` grows only by items not
already held) held exactly.

### What the `selection` rows carry

| source | rows | footprint | bbox | resolution_m | platform | cloud |
|---|---|---|---|---|---|---|
| landsat | 43 | 43 | 43 | 43 (all 30) | 43 | 43 |
| naip | 21 | 21 | 21 | 21 — **0.3 (3), 0.6 (6), 1.0 (12)** | 0 | 0 |
| sentinel2 | 11 | 11 | 11 | 11 (all 10) | 11 | 11 |
| usgs_topo | 5 | **0** | 5 | 0 | 0 | 0 |

All 75 STAC-sourced footprints are `ST_Polygon`. The five NULL footprints are
exactly the topo rows, which is designed: a TNM product carries no geometry
(§5.4's shape, one row further than it stated). **Requirement met: a
pipeline-written scene has its footprint from birth**, so the
synthesized-candidate class cannot grow — `mosaic_url` stayed at 0 through
four pipeline runs that catalogued 21 NAIP tiles.

### NORM-9 and NORM-11, observed end to end

New NAIP `imagery_snapshots` rows carry the item's gsd: **0.3 (2), 0.6 (4),
1.0 (11)** across the two probes — 6 of 17 are not 1.0, against a
pre-sweep table where 306 of 306 were. No noisy value appeared in this
sample, so the rounding rule was not exercised by live data here; it is
covered by `test_the_rounding_rule_normalizes_every_observed_gsd` against all
seven production spellings. The 306 pre-existing rows are unchanged, exactly
as §5.2 said they would be.

### Idempotence, observed

The Kansas parcel was run a second time through the full pipeline. An md5
over `(source, group_key, scene_id, mosaic_scene_ids, selected_at,
selected_by)` for all 66 of its rows is **identical before and after**
(`eb608d8aec7feafa9aa09f75e9992a94`), and the three table counts did not
move. A re-selection of the same scene writes nothing and does not bump
`selected_at` — §5.3's rule, observed.

### Mosaics

| | `imagery_snapshots` | `parcel_scenes` |
|---|---|---|
| rows carrying a mosaic | 148 | 148 |
| entries / references | 176 | 176 |

And a check the prediction did not name: every one of the 176 references
resolves to a `scenes` row whose `cog_url` is a member of the same group's
`additional_cog_urls` array — **176 of 176**. The two representations name
the same tiles, not merely the same count.

### The ledger, read alongside (NORM-3)

The sweep's own window: landsat 1,847 `ok` / **2 `failed`/`stac_403`**, naip
306 `ok` / 420 `absent`/`no_scenes` / 5 `suppressed`, sentinel2 516 `ok` / 0
failed, usgs_topo 274 `ok` / 3 `indeterminate` (TNM row cap, pre-existing).

The two failures are single Landsat years on two parcels — Death Valley 1996
and 1600 Amphitheatre Pkwy 2004. Neither left a duplicate group (P2 = 0), and
under the absent-group rule neither cost a row in either table. So **P2 = 0
is a real zero and not one resting on an unretried upstream failure** — the
reading NORM-3 requires.

### Stop conditions

None fired. P3 = 0, P2 = 0, `scenes` never fell, and the single deviation
(P6) is scope rather than a parity violation.
