# Prediction — step 3's local parity run

Written before `scripts/compare_read_paths.py` is run as the scored evidence
for ADR 0001's step-3 cutover, and committed before that run. Scored in a
later commit; this half is never edited.

---

## 0. The blindness this prediction does not have, stated first

**The harness was run twice against the local database before this document
existed.** Both runs were development runs — the first to find out whether the
new reads worked at all, the second to check that a fix landed — and both
surfaced divergences that are described below. So this is **not** a blind
prediction, and the run it predicts cannot be scored as one.

The honest thing is to say what each run is worth rather than to dress this
one up:

* **What is lost.** The strong prior the step-3 prompt names — "if you predict
  zero, say why, and any nonzero diff at run time is a finding" — cannot be
  tested here. I have seen the nonzero diff. The two classes below are
  reported as findings on their own merits, not because a prediction caught
  them.
* **What is still worth running.** The scored run is against *committed* code
  (`0181c54`), reproducible by anyone, and it tests three things this
  prediction can still get wrong: that the committed state and the debugged
  state are the same state, that every quantity below is exactly right rather
  than approximately remembered, and that no class other than the two named
  appears. **Any divergence class not named in §3 is a finding.**
* **The rule that still binds.** This file is committed before the scored run
  and is not edited afterwards. The Observed half lands beside it.

The sequencing error was mine: the prompt's item 4 puts the prediction before
the local parity run, and I ran the harness while building it. Recorded here
rather than in a footnote because a prediction's value is entirely in when it
was written.

---

## 1. What is being run

```
docker compose exec -T -e APP_ENV=production api \
    python scripts/compare_read_paths.py --out <capture>
```

against the local PostGIS database at `0181c54`, with both read paths alive.
`APP_ENV=production` only silences SQLAlchemy's statement echo
(`app/db.py:29`); it changes no behaviour the script exercises.

Five sites, in the harness's own terms: `listing` (unfiltered), `listing[source=…]`
×4, `listing[start_date]`, `listing[end_date]`, `by_id`, `count`, `featured`,
`revalidate_landsat`, plus a population-level item-fact disagreement tally.

## 2. Local database state, read 2026-08-29 05:20Z

`imagery_snapshots` **3,082** · `parcel_scenes` **3,082** · `scenes` **1,342**
· `parcels` **45** · `featured_locations` **6**. `parcel_scenes` by source:
landsat 1,935, sentinel2 539, naip 323, usgs_topo 285. 148 `parcel_scenes`
rows carry a mosaic.

## 3. The prediction

### 3a. Volumes

| # | Quantity | Predicted |
|---|---|---|
| P1 | parcels visited | **45** |
| P2 | rows, old path | **3,082** |
| P3 | rows, new path | **3,082** |
| P4 | row/count comparisons | **12,560** |
| P5 | id pairs recorded | **12,373** |
| P6 | distinct old ids / distinct new ids | **3,082 / 3,082** |
| P7 | fields compared per row pair | **12** |

P4 and P5 differ because `count` and `featured` comparisons increment the
comparison counter without producing an id pair.

### 3b. Divergences — **12**, of exactly one class

| # | Claim |
|---|---|
| P8 | **Total divergences: 12.** |
| P9 | All twelve are `field = resolution_m`. |
| P10 | All twelve are on parcel `11111111-2222-3333-4444-555555555555` (1600 Pennsylvania Ave NW), keys `naip/2018`, `naip/2021`, `naip/2023`. |
| P11 | Old values 0.6, 0.6, 0.3; new values 1.0, 1.0, 1.0. |
| P12 | They are **3 rows seen from 4 sites**: `listing` 3, `listing[source=naip]` 3, `listing[start_date]` 3, `by_id` 3. |
| P13 | `count` divergences: **0** over 180 comparisons (45 parcels × 4 sources). |
| P14 | `featured` divergences: **0** over 6 parcels. |
| P15 | `revalidate_landsat` divergences: **0**. |
| P16 | `row_order` divergences: **0**. |
| P17 | `missing_from_old` / `missing_from_new` / `*_duplicate_group` / `id_map_*` / `no_id_mapping` / `row_absent`: **0** of each. |

### 3c. Non-divergences that will still be reported

| # | Claim |
|---|---|
| P18 | Same-date reorderings: **20**. Not a divergence — the two shapes agree on the chronological sequence and differ only in how they arrange rows sharing one date, which neither query ever defined. |
| P19 | The item-fact disagreement table names **one** field: `resolution_m`, **3 served rows over 3 distinct scenes**. `capture_date`, `cog_url`, `thumbnail_url` and `cloud_cover_pct` are absent from it. |

### 3d. The predicted `id` divergence, and why it is not in the table

`parcel_scenes.id` is a fresh UUID on every row — `scripts/backfill_scenes.py`
mints one per backfilled row (`:536`), `_upsert_parcel_scene` mints one per
insert (`imagery.py`) — so it is **never** equal to the `imagery_snapshots.id`
for the same served period. This is the one divergence predicted in advance
by the step-3 prompt, and the harness handles it by excluding `id` from field
equality and asserting a bijection instead (P6, P17's `id_map_*`).

**Consequence, and it is the cutover's one user-visible change of value:**
after the cutover the API hands out `parcel_scenes.id` where it used to hand
out `imagery_snapshots.id`, at `/parcels/{id}/imagery`, `/featured`, and
everything downstream of them (`/imagery/{id}/tiles`, `/warmup`, `/stac`).
Both ends move in one commit, so the ids stay internally consistent. Two
costs are accepted rather than avoided: a browser holding a page across the
deploy has stale ids until it refetches, and the `stac:{snapshot_id}` Redis
keys are all cold on the first request after (a refetch of an immutable item,
not an error).

## 4. Why the strong prior of zero is not what this predicts

The prompt's prior — zero, on the strength of step 2's both-sides fidelity
work — is right about everything the *write path* controls and wrong about
one thing it does not.

`scenes` is **insert-only** (`_ensure_scene`, ADR step-2 amendment) and
`upsert_imagery_snapshot`'s `ON CONFLICT DO UPDATE` never touches
`resolution_m` (NORM-13). So the two shapes agree perfectly for any row they
were *written together* from one `SelectedScene` — which is what step 2
proved, twice, over 12,884 production groups — and they can still disagree
about a row written at two different times, because neither table has a
mechanism for refreshing an item fact it already holds.

The local database has three such rows, and their history is the ADR's
opening paragraph in miniature. Item
`md_m_3807708_se_18_030_20230901_20231018` is served by four parcels. Three
carry `resolution_m = 1.0`, written 2026-03 under the pre-NORM-9 constant;
one carries `0.3`, written 2026-08-28 after the fix. The backfill collapsed
those four copies into **one** `scenes` row and the tie-break took a 2026-03
row, so the surviving copy says 1.0. Insert-only has kept it there since.

**After the cutover all four parcels serve 1.0** — three of them unchanged,
and the fourth changed from the item's real 0.3 m to the source constant.
That is the normalization working exactly as designed (one copy of an item
fact) and picking, in this instance, the wrong copy.

**This does not block the cutover, and the reason is a production
measurement, not an argument.** The disagreement needs a NAIP row rewritten
after the NORM-9 deploy against a `scenes` row written before it, and
production has none: on 2026-08-29 all **1,305** NAIP `imagery_snapshots`
rows and all **1,102** NAIP `provenance = 'snapshot'` `scenes` rows carried
1.0 (`STEP2-PROD-REPORT.md` §9 / NORM-13), so every copy of that fact already
agrees. What the local rows show is that the class **will** open in production
the first time a NAIP selection changes, and that the cutover is what makes it
user-visible — the `1m res` chip at `frontend/src/components/MapView.tsx:298-301`.

## 5. What would falsify this, and what each falsification would mean

* **Any divergence class not in §3b.** A finding, full stop — the harness
  compares twelve fields and this predicts one of them ever differs.
* **`missing_from_old` / `missing_from_new` anywhere.** Parity between the two
  tables has broken locally since step 2's sweep. That is a step-2 regression,
  not a step-3 one, and it stops the cutover.
* **`id_map_inconsistent` or `id_map_not_injective`.** Two served periods
  share a `parcel_scenes` row, or one maps to two. Either breaks the id
  substitution the cutover rests on.
* **`count` divergence.** `items_found` would change on a live timeline, and
  the mosaic semantics (a mosaic is one row, not N scenes) would be wrong.
* **A larger `resolution_m` population than 3 rows.** The mechanism is wider
  than the four-parcel item above, and the production claim in §4 needs
  re-deriving rather than citing.

---

## Observed — local, 2026-08-29

Appended after the run. Everything above is unedited. Command as §1, against
`0181c54` + this file's commit `dad8502`; capture committed as
`step3-parity-local.md`; script exit code 1 (it exits nonzero on any
divergence).

**Every predicted quantity confirmed — 19 of 19, no deviations, no
unpredicted class.**

| # | Predicted | Observed |
|---|---|---|
| P1 | 45 parcels | **45** |
| P2 | 3,082 old rows | **3,082** |
| P3 | 3,082 new rows | **3,082** |
| P4 | 12,560 comparisons | **12,560** |
| P5 | 12,373 id pairs | **12,373** |
| P6 | 3,082 / 3,082 distinct ids | **3,082 / 3,082** |
| P7 | 12 fields per pair | **12** |
| P8 | 12 divergences | **12** |
| P9 | all `resolution_m` | **all `resolution_m`** |
| P10 | parcel `11111111…`, keys naip/2018, naip/2021, naip/2023 | **as predicted** |
| P11 | 0.6→1.0, 0.6→1.0, 0.3→1.0 | **as predicted** |
| P12 | 3 rows × 4 sites (3/3/3/3) | **listing 3, listing[source=naip] 3, listing[start_date] 3, by_id 3** |
| P13 | 0 `count` divergences | **0** |
| P14 | 0 `featured` divergences | **0** |
| P15 | 0 `revalidate_landsat` divergences | **0** |
| P16 | 0 `row_order` | **0** |
| P17 | 0 of each structural class | **0** — no `missing_from_*`, no `*_duplicate_group`, no `id_map_*`, no `no_id_mapping`, no `row_absent` |
| P18 | 20 same-date reorderings | **20** |
| P19 | item-fact table names `resolution_m` only, 3 rows / 3 scenes | **`resolution_m`, 3 / 3; no other field present** |

**The bijection held over the whole database.** 12,373 id pairs recorded
across four sites resolved to exactly 3,082 distinct old ids and 3,082
distinct new ids, with no inconsistency and no collision — so every served
period has exactly one `parcel_scenes` row, the same one, however it is
reached. That is the property the id substitution rests on, measured rather
than assumed.

**Eleven of the twelve compared fields are exactly equal on all 3,082 rows**,
`additional_cog_urls` included — 148 mosaic rows reconstructed from
`mosaic_scene_ids` in array order, matching the stored arrays element for
element, with no dangling reference logged.

**§0 stands.** These confirmations are of a prediction written with the
answer in hand; what they establish is that the committed code behaves as the
debugged code did and that no class was missed, not that the outcome was
foreseen.

---

# Prediction — step 3's PRODUCTION parity run

Written 2026-08-29 ~06:20Z, **before** `scripts/compare_read_paths.py` is run
against production, and committed before it. Scored in a later commit; this
half is never edited. Deployed sha is
`c96dbf8fb9a6ef27a4978a4074da5d159b2c65d7` (Deploy A — `160e7ba` plus the
script-logging call CI's guard demanded), both read paths alive.

## P0. What is blind here and what is not — the same discipline as §0

The harness **has never been run against production**. Every structural and
volumetric claim below is therefore blind in the sense §0 says the local
prediction was not: no run has been seen, and the numbers are derived from
the table's contents and the harness's own control flow, not remembered from
an answer.

**One claim is not blind, and it is the most load-bearing one.** PP12 — the
NORM-18 `resolution_m` population is **0** — is derived from a direct
measurement the pre-flight already took: all 12,884 joined
`imagery_snapshots` / `parcel_scenes` pairs were compared field by field, and
every comparable item fact (`resolution_m`, `capture_date`, `cog_url`,
`thumbnail_url`, `cloud_cover_pct`, `item_id`, `collection`) diverged on **0**
rows. That query is the same question `_item_fact_disagreement` asks. So PP12
predicts that the harness reproduces a measurement already in hand; it is not
a forecast, and scoring it confirms agreement between two routes to one
number, nothing more. Stated here rather than discovered in the scoring.

## P1. Production state, read 2026-08-29 06:14–06:16Z

`scenes` **6,663** (snapshot 6,156 · enriched 505 · selection 2 · `mosaic_url`
**0**) · `parcel_scenes` **12,884** · `imagery_snapshots` **12,884** ·
`parcels` **189** · `featured_locations` **6** · `alembic_version` **0017**.
`parcel_scenes` by source: landsat 8,127, sentinel2 2,259, naip 1,305,
usgs_topo 1,193. 576 rows carry a mosaic, 613 references in total. 189 parcels
serve landsat. `max(selected_at)` **2026-08-29T04:41:26.056Z** and
`selected_by` non-NULL on **7** rows — unmoved from the 05:53Z pre-flight, so
no dual-write traffic has landed since step 2's sweep.

**The traffic-drift assumption, timestamped.** Every count below assumes the
tables are unchanged between 06:16Z and the harness's own run. Any pipeline
task between those two moments can move them, and the falsification that
follows is a count deviation, not a parity failure — which is why P1's
timestamp is recorded and not the wall clock of the run.

## P2. Volumes

| # | Quantity | Predicted | Basis |
|---|---|---|---|
| PP1 | parcels visited | **189** | `parcels` count |
| PP2 | rows, old path | **12,884** | `imagery_snapshots` |
| PP3 | rows, new path | **12,884** | `parcel_scenes` |
| PP4 | id pairs recorded | **51,725** | derivation below |
| PP5 | row/count comparisons | **52,488** | PP4 + 756 + 6 + 1 |
| PP6 | distinct old ids / distinct new ids | **12,884 / 12,884** | the bijection |
| PP7 | fields compared per row pair | **12** | `_COMPARED_FIELDS` |

**PP4's derivation, from the harness's control flow rather than from a run.**
Each served row is compared once by `listing`, once by its own
`listing[source=…]` (a row has exactly one source), and once by `by_id` —
3 × 12,884 = 38,652. The two date windows use each parcel's midpoint
`captured[n // 2]`: `start_date` takes rows `>= midpoint`, `end_date` rows
`<= midpoint`, so every row is counted once and every row **sharing its
parcel's midpoint date** is counted twice. Predicting exactly one such row per
parcel gives 12,884 + 189 = **13,073**, and 38,652 + 13,073 = **51,725**. The
same arithmetic reproduces the local run exactly (3 × 3,082 + 3,082 + 45 =
12,373 observed), which is what licenses it.

**PP4 is the most fragile number here and its failure mode is benign.** A
parcel whose midpoint date is shared by two sources contributes an extra pair.
A deviation in PP4 alone, with PP1–PP3 and every structural class holding, is
a same-date tie count, not a parity finding — §2e's phenomenon showing up in
the comparison counter.

PP5's constants: `count` contributes 189 × 4 = **756**, `featured` **6** (one
per featured location), `revalidate_landsat` **1**. These increment the
comparison counter without producing an id pair, which is why PP4 ≠ PP5.

## P3. Divergences — **0**, of any class

| # | Claim |
|---|---|
| PP8 | **Total divergences: 0.** |
| PP9 | Eleven of the twelve compared fields are exactly equal on **every one of the 12,884 rows**, `additional_cog_urls` included — the 576 mosaic rows reconstructed from `mosaic_scene_ids` in array order, matching element for element, with **no dangling reference logged** over all 613 references. |
| PP10 | The twelfth, `id`, is a **bijection**: 51,725 pairs resolving to exactly 12,884 distinct old ids and 12,884 distinct new ids, with `id_map_inconsistent`, `id_map_not_injective` and `no_id_mapping` all **0**. |
| PP11 | `count` **0** over 756 comparisons; `featured` **0** over 6; `revalidate_landsat` **0**; `missing_from_old`, `missing_from_new`, `*_duplicate_group`, `row_absent` **0** of each. |
| PP12 | **The item-fact disagreement table is empty. `resolution_m` population = 0** — NORM-18's class exists in production at size zero. **Not blind; see P0.** |
| PP13 | `row_order` divergences **0** — the §2e `capture_date ASC, source ASC` tie-break is deployed at `c96dbf8`, and mosaic order is preserved by the array-order reconstruction PP9 asserts. |
| PP14 | Script **exit code 0** (it returns 1 only on a divergence). |

## P4. Non-divergences that will still be reported

| # | Claim |
|---|---|
| PP15 | Same-date reorderings: **nonzero, and not a divergence.** Locally 20 over 45 parcels. **No point estimate is offered** — the count is a property of how many parcels have two sources landing on one capture date, which nothing measured here has counted, and inventing a number would be a guess dressed as a prediction. Any value is consistent with this prediction; only a `row_order` divergence (PP13) is not. |

## P5. What would falsify this, and what each falsification means

* **`missing_from_old` / `missing_from_new` anywhere.** Dual-write parity has
  broken since step 2's sweep. A step-2 regression, and it **stops the
  cutover**.
* **`id_map_inconsistent` / `id_map_not_injective`.** Two served periods share
  one `parcel_scenes` row, or one maps to two. Breaks the id substitution the
  cutover rests on — **stops the cutover** (NORM-19).
* **A nonzero `resolution_m` population.** PP12 falsified against a direct
  measurement taken hours earlier, which would mean either the two routes
  disagree or the data moved. **Stops this session**: per `STEP3-REPORT.md`
  §7 F1, the size of the population decides heal-before-cutover versus after,
  and that decision is the owner's, not a session's.
* **Any divergence class not named above.** A finding the local harness could
  not have seen, because the local database does not hold the shape that
  produced it. **Stops the cutover** pending the owner's read.
* **A count deviation with every structural class at 0.** Not a parity
  finding: either traffic between P1 and the run (the timestamped assumption)
  or PP4's same-date tie arithmetic. Scored as a deviation and explained, not
  as a divergence.

---

## Observed — production, 2026-08-29

Appended after the run. Everything above is unedited. Run inside the API
machine `825d69b7e46618` at the deployed sha
`c96dbf8fb9a6ef27a4978a4074da5d159b2c65d7`, detached with `--out
/tmp/parity-prod.md` per NORM-8, **06:17:0xZ → 06:32Z (~15 minutes)**;
capture committed byte-for-byte as `parity-prod.md`.

**Every predicted quantity confirmed — 13 of 13 scored, 1 unobservable, no
divergence of any class, no unpredicted class.**

| # | Predicted | Observed |
|---|---|---|
| PP1 | 189 parcels | **189** |
| PP2 | 12,884 old rows | **12,884** |
| PP3 | 12,884 new rows | **12,884** |
| PP4 | 51,725 id pairs | **51,725** |
| PP5 | 52,488 comparisons | **52,488** |
| PP6 | 12,884 / 12,884 distinct ids | **12,884 / 12,884** |
| PP7 | 12 fields per pair | **12** |
| PP8 | 0 divergences | **0** |
| PP9 | eleven fields equal on every row | **confirmed** — "Divergences: 0. None." over 12,884 rows, `additional_cog_urls` included, no dangling reference logged |
| PP10 | the id mapping a bijection | **confirmed** — 51,725 pairs → 12,884 distinct each way, no `id_map_*`, no `no_id_mapping` |
| PP11 | 0 `count` / `featured` / `revalidate_landsat` / structural | **0 of each** |
| PP12 | item-fact table empty, `resolution_m` population **0** | **"Item facts the two shapes disagree about: None."** |
| PP13 | 0 `row_order` | **0** |
| PP14 | exit code 0 | **not observed — see below** |
| PP15 | reorderings nonzero, no point estimate | **76** |

**PP4 is the result worth keeping.** It was derived from the harness's
control flow rather than from any run — 3 × 12,884 for `listing`,
`listing[source=…]` and `by_id`, plus 12,884 + 189 for the two date windows on
the prediction that **exactly one row per parcel shares that parcel's midpoint
capture date** — and it landed on the nose over 189 parcels. The stated
fragile assumption held: not one of the 189 midpoints is shared by two
sources, even though 76 same-date reorderings prove same-date pairs are common
elsewhere in the data.

**PP14 is unobservable and is scored as such rather than as confirmed.** The
run was launched `setsid nohup … &` so that a killed ssh client could not take
it with it (NORM-8), and the parent shell exited without its status. The
script returns 1 if and only if `report.divergences` is non-empty, and the
capture says 0, so the exit code was 0 — but that is an inference from the
code and the artifact, not a reading of `$?`. Recorded because "the exit code
was 0" and "the exit code must have been 0" are different claims.
**Improvement for the next detached production run:** have the launcher write
`echo $? > /tmp/<name>.rc` after the command, so the status survives the
client.

**PP15's abstention was the right call and cost nothing.** 76 reorderings
against 20 locally — 3.8× on 4.2× the parcels. Any point estimate written
before the run would have been a guess, and `row_order` divergences are **0**,
which is the claim that actually matters: §2e's `capture_date ASC, source ASC`
tie-break is deployed and deterministic over a population with far more
same-date pairs than the local database has.

**What this run establishes that the local one could not.** The local scoring
was of a prediction written with the answer in hand (§0). This one was not:
the harness had never been run against production, and every structural and
volumetric claim was derived rather than remembered. **PP12 remains the
exception disclosed in P0** — the 0 population reproduces a direct 12,884-pair
measurement taken in the pre-flight at ~05:53Z, so what it confirms is that
two routes to that number agree, and that nothing moved between 05:53Z and
06:32Z.

**NORM-18's class exists in production at size zero, measured.** The mechanism
is unchanged and the finding stays open: the class opens the first time a NAIP
selection is rewritten against a `scenes` row written before the NORM-9 fix.
Zero today is a fact about today's data, not a repair.

**The traffic-drift assumption held.** `parcel_scenes` and
`imagery_snapshots` were both 12,884 at 06:14Z and the run compared 12,884 on
each path; `max(selected_at)` was 04:41:26.056Z before the run, and no
pipeline task ran during it.
