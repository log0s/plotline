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
