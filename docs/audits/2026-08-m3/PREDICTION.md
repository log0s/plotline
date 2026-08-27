# M3 heal predictions — written before the runs

Three production acceptance cases for per-source, ledger-driven backfill.
Every number below was read from production on **2026-08-26 between ~18:05Z
and ~18:20Z** via `fly ssh console -a log0s-plotline-api -C`, `SELECT` only,
against deployed SHA **`b599c2519c5c29fc8b5e4ab170da1b0021f2c559`** (API
`built` 2026-08-26T17:57:51Z; worker `GH_SHA` identical).

**Nothing here has been run.** Each case names the command, what it should
do, the query that scores it, and what would falsify it. Predictions are
never edited to match an outcome — the observed result lands beside the
prediction with a verdict.

**Deploy gate.** All three need the M3 commits on the worker. The SHA to
pass to `--require-sha` is whatever `main` deploys as; it must be a
descendant of `b7c9cbb` (`feat(scripts): ledger-driven requeue`). Running any
of these against `b599c25` does something different from what is predicted
here, and in two of the three cases does nothing at all.

**Premise correction carried forward.** The M3 design investigation (§5,
2026-08-26 ~09:35Z) recorded that `e6afa9b` — the decennial-1990 drop and the
2000 tract-width trim — was **not** deployed, and scoped its numbers to a run
that could not yet happen. That has changed: `git merge-base --is-ancestor
e6afa9b b599c25` exits 0, so the trim is live on both API and worker as of
17:57:51Z. P2 below is therefore executable the moment M3 deploys, and its
population has been re-measured under the new premise rather than carried
over.

---

## Fleet state at prediction time

| | |
|---|---:|
| parcels | 187 |
| `timeline_requests` | 710 (707 `complete`, 3 `failed`) |
| requests that migration 0012 will flip `complete` → `partial` | **40** |
| requests 0012 will flip `complete` → `failed` | **0** |
| `census_snapshots` (`decennial`, 2000) | 47 |

Latest-outcome populations the retry policy would act on, fleet-wide:

| class | source | groups | parcels |
|---|---|---:|---:|
| `failed/read_timeout` — retry now | `landsat` | 17 | 2 |
| `failed/read_timeout` — retry now | `naip` | 17 | 1 |
| `absent/api_no_data` — `--include-absent-api` only | `census_decennial` | 327 | 187 |
| `absent/api_no_data` — `--include-absent-api` only | `census_acs5` | 75 | 75 |
| `indeterminate` — retry once, then a code fix | `naip` 7, `usgs_topo` 1 | 8 | 2 |

**34 groups on 3 parcels are retryable with no flag at all.** That is the
whole no-flag backlog, and P1 and P3 are 34 of it.

---

## P1 — `e513188c`, the NAIP 2023 card of the wrong place (G1)

Parcel `e513188c-7de4-435e-994e-98621d88a81b`, 350 5th Ave, New York, NY.

### Before (read 18:07Z)

Nine served NAIP rows. Eight are the parcel's own tile; the ninth is not.

```
2010-07-31  nj_m_4007309_sw_18_1_20100731
2011-07-05  ny_m_4007317_nw_18_1_20110705_20111114
2013-06-22  ny_m_4007317_nw_18_1_20130622_20130729
2015-05-22  ny_m_4007317_nw_18_.5_20150522_20151109
2017-08-09  ny_m_4007317_nw_18_1_20170809_20171207
2019-08-30  ny_m_4007317_nw_18_060_20190830_20191209
2021-11-05  ny_m_4007317_nw_18_060_20211105
2022-07-19  ny_m_4007317_nw_18_060_20220719
2023-08-20  nj_m_4007309_sw_18_030_20230820_20231019   ← the wrong place
```

Latest ledger row for `(e513188c, naip, 2023)`:

```
suppressed / naip_no_point_coverage
"selected tiles do not contain the parcel:
 nj_m_4007309_sw_18_030_20230820_20231019, nj_m_4007424_ne_18_030_20230820_20231019"
```

The served item id is the **first tile named in the suppression detail**.
That identity is the whole authority for the delete.

### Command

```
docker compose exec api python scripts/requeue_parcels.py \
    --require-sha <m3-sha> --sources naip \
    e513188c-7de4-435e-994e-98621d88a81b
```

### Predicted

1. One request, `origin='heal'`, `sources = ['naip']`. It is **not**
   full-scope, so it does not become the parcel's current request and
   `_find_reusable_request` keeps returning the older full run.
2. Exactly one task row (`naip`). No census, property, topo, Landsat or
   Sentinel-2 task row is created and none of those fetches runs.
3. The point-coverage gate rejects the 2023 group again — nothing about the
   collection has changed — and records `suppressed`/`naip_no_point_coverage`
   with the same two tile ids.
4. `reconcile_source_snapshots` deletes **exactly one row**: the 2023 one,
   because its item id is named in this run's suppression. Log line
   `Deleting a served snapshot this run suppressed` appears once, with
   `suppressed_deleted: 1`.
5. **NAIP snapshots go 9 → 8.** The eight surviving rows keep their `id` and
   `stac_item_id` — same items re-selected, so the supersede branch has
   nothing to do.
6. Snapshot counts for the parcel's other sources — `landsat` 43,
   `sentinel2` 12, `usgs_topo` 9, all read 18:18Z — are **unchanged, row for
   row by id**: a NAIP-scoped run never reaches their reconcile calls.
7. Request status ends `complete`.

### Scoring query

```sql
SELECT capture_date, stac_item_id, id FROM imagery_snapshots
WHERE parcel_id = 'e513188c-7de4-435e-994e-98621d88a81b' AND source = 'naip'
ORDER BY capture_date;

SELECT source, count(*) FROM imagery_snapshots
WHERE parcel_id = 'e513188c-7de4-435e-994e-98621d88a81b' GROUP BY 1;

-- latest ledger for the parcel's naip groups, expect 2023 = suppressed
```

### Falsifiers

* Any NAIP row other than 2023 disappearing. That is the item-id condition
  failing, and it is a worse outcome than not healing at all.
* 2023 surviving. Either the gate did not fire (a selection change), or the
  suppression did not reach reconcile.
* Any non-NAIP snapshot count changing. That is the scope leaking.
* Fleet-wide blast radius, re-measured 18:18Z: **nine** `suppressed` rows are
  latest, and a served-snapshot existence check is `True` for exactly one of
  them — `e513188c`/2023. The other eight (`1754635c` 2010/2013/2015/2017/2019,
  `8d9ee137` 2012/2014/2016) are `False`: the gate refused to write those and
  there is nothing to remove. So a full fleet sweep under this rule should
  delete **one row, total**. If it deletes more, the rule is wider than it
  looks and the item-id condition is not doing its job.

---

## P2 — decennial 2000, the six-character tract heal

### Command

```
docker compose exec api python scripts/requeue_parcels.py \
    --require-sha <m3-sha> --from-ledger --sources census_decennial \
    --include-absent-api --dry-run
```

### Predicted dry run: 187 parcels, 327 groups — not 80

**The command as written selects the whole fleet, and this is the honest
number rather than the one the M3 prompt anticipated.** The design
investigation's §5 counted the 80 parcels whose stored tract ends in `00`,
which is the population the trim actually fixes. `--from-ledger --sources
census_decennial --include-absent-api` selects every parcel with *any*
retryable `census_decennial` group, and the ledger holds two:

| group | latest `absent/api_no_data` rows |
|---|---:|
| `1990` | **187** (every parcel) |
| `2000` | **140** (of which 80 have a tract ending `00`) |

`--from-ledger` has no per-group flag, so the run is 187 parcels wide.

**Why the 187 `1990` rows never go away.** `e6afa9b` removed 1990 from
`DECENNIAL_YEARS` — the endpoint never existed. A re-run therefore does not
attempt 1990, writes no new ledger row for it, and the stale
`absent/api_no_data` row from the pre-trim sweep stays the latest outcome
**forever**. Every future `--include-absent-api` run re-selects all 187
parcels on the strength of a group the code will never ask about again.
This is a new mechanism, found while writing this prediction; it is filed in
STATUS.md under M3's notes, unfixed. It does not block P2 — it makes P2
wider and permanently repeatable, which is the thing to know before running
it.

### Predicted real run

Dropping `--dry-run`:

1. 187 census-only requests, `origin='heal'`, `sources = ['census']` each.
   (`census_decennial` maps to the `census` task source; both census datasets
   are fetched, because one task row covers both.)
2. **`census_snapshots` (`decennial`, 2000) goes 47 → 111: exactly 64 new
   rows.** The 64 are the 80 ends-in-`00` parcels minus the 16 tracts that
   answer 204 even under the four-character form
   (`08031015300`, `09170157100`, `11001980000` ×3, `17031839100`,
   `17031980000`, `26019000500`, `26061000800`, `29147470400`,
   `34023009300` ×2, `36121970700`, `48453032600`, `53035940000`,
   `55079187300` — `../2026-08-census-decennial/REPORT.md` §1.5).
3. 64 ledger rows move `census_decennial`/`2000` from `absent`/`api_no_data`
   to `ok`. 76 stay `absent`/`api_no_data` (140 − 64).
4. **No `census_decennial`/`1990` ledger row changes at all** — not to `ok`,
   not to a new `absent`. The count stays 187.
5. **Zero imagery churn.** `imagery_snapshots` is identical before and after,
   row for row by id. A census-only scope creates no imagery task row and no
   imagery coroutine, and `reconcile_source_snapshots` is reachable only from
   inside those coroutines.
6. `census_acs5` rides along on every parcel — one task covers both datasets
   — so some of the 75 `census_acs5`/`absent/api_no_data` groups may move.
   **No prediction is made about how many**; acs5 2009 has its own
   vintage-resolution behaviour (`../2026-08-racebrook/REPORT.md`) and this
   run is not designed to test it. Any change there is a ride-along, and it
   can only add `census_snapshots` rows: the upsert is keyed
   `(parcel_id, dataset, year)` and there is no delete path on that table.
7. **Admission.** 187 parcels against a heal cap of 25 (cap 30 −
   `user_admission_reserve` 5). The script waits rather than abandoning its
   tail, and `inflight_depth` should never be observed above 25 during the
   run while user traffic can still reach 30. Expect many
   `Waiting for an admission slot` lines with `cap: 25`.
8. Cost: ~9 Census API calls and ~4.5 s of deliberate inter-year sleep per
   parcel. 107 of the 187 parcels will spend that and change nothing, which
   is the price of the missing per-group filter.

### Scoring queries

```sql
SELECT count(*) FROM census_snapshots WHERE dataset='decennial' AND year=2000;  -- expect 111

-- latest ledger, decennial by group and outcome; expect 1990: 187 absent,
-- 2000: 64 ok / 76 absent
```

### Falsifiers

* Any decrease in `census_snapshots`. The table has no delete path, so a
  decrease means something else is wrong.
* Any `imagery_snapshots` row changing.
* A recovery count materially away from 64. Above 64 means the 16-tract
  list is stale (it was probed 2026-08-26, earlier the same day, and has not
  been re-probed — carried as UNVERIFIED). Below 64 means the trim is not
  doing what the census report measured.
* A `census_decennial`/`1990` row moving. That would mean 1990 is still being
  attempted, i.e. `e6afa9b` is not actually the running code.

### Addendum, 2026-08-26 — Y3 fix, corrected dry-run count: 140, not 187

`docs/audits/2026-08-second-audit/STATUS.md` Y3: the 187/327 figure above
included 187 stale `census_decennial`/`1990` rows that current code will
never attempt again (`e6afa9b` dropped 1990 from `DECENNIAL_YEARS`), so
`--from-ledger` was permanently re-selecting all 187 parcels on the strength
of a group it can't retry. `services/ledger.is_stale` (paired with the new
`imagery.attempted_group_keys`) now excludes it; this is a **scored
correction of the number above, not a rewrite** — the 187/327 prediction
stands as written and was accurate to the code at the time it was made.

**The corrected number is not from `requeue_parcels.py --dry-run`.** Neither
M3 nor this Y3 fix is deployed — `fly image show -a plotline-worker` still
reports `GH_SHA=b599c25...`, pre-`ae740cf` — so running the script against
prod would execute code that doesn't have `services/ledger.py` at all, and
the deploy gate would refuse it regardless. What was run instead is a
read-only SQL query against prod (`fly ssh console -a log0s-plotline-api -C`,
`SELECT` only, 2026-08-26) reproducing the corrected selection logic by hand
— the same latest-outcome window `ledger.py`'s `_LATEST_SQL` computes,
grouped by `group_key`/`outcome`/`reason` for `source = 'census_decennial'`:

```
('1990', 'absent', 'api_no_data', 187)
('2000', 'absent', 'api_no_data', 140)
('2000', 'ok',              None,  47)
('2010', 'ok',              None, 187)
('2020', 'ok',              None, 187)
```

Excluding the stale `1990` row (`attempted_group_keys('census_decennial')`
= `{2000, 2010, 2020}`), the corrected `--from-ledger --sources
census_decennial --include-absent-api --dry-run` selection is **140
parcels, 140 groups** — one `absent/api_no_data` row per parcel, all in
`group_key = 2000`, none new since the 18:15Z reading this session's prompt
carried forward (140 then, 140 now). This is closer to the design
investigation's ~80-parcel estimate than 187 was, though still wider than 80
— the remaining 60 are the tracts whose four-character form also happens to
answer 204 (REPORT.md §1.5's 16-tract exception list accounts for some of
the gap; the rest are simply not among the 80 that end `00`). A real dry-run
against deployed M3 code, once Ryan deploys it, is the only thing that can
confirm this number reads the same way through `requeue_parcels.py` itself;
this addendum stands until that happens.

---

## P3 — Crawford County `6563dedf`, 33 groups no self-running code could reach

Parcel `6563dedf-23b1-4719-89db-ab135ed24fb3`, Camp Grayling, Grayling
Charter Township, Michigan. Created 2026-08-26 09:14:34Z; one request,
`b1392b23-63ad-46d2-b9ab-97cd09d61a2e`, created 09:14:35Z.

### Before (read 18:12Z)

Request status **`complete`**. Task rows:

| source | status | items_found |
|---|---|---:|
| census | complete | 8 |
| landsat | complete | 27 |
| **naip** | **failed** | 0 |
| property | skipped | 0 |
| **sentinel2** | **failed** | 0 |
| usgs_topo | complete | 3 |

Served snapshots: landsat 27, usgs_topo 3, **naip 0, sentinel2 0**.

Latest ledger outcomes:

| source | outcome | reason | groups | range |
|---|---|---|---:|---|
| landsat | `failed` | `read_timeout` | **16** | 1984–1999 |
| landsat | `ok` | | 27 | 2000–2026 |
| naip | `failed` | `read_timeout` | **17** | 2010–2026 |
| census_acs5 | `ok` | | 6 | 2009–2023 |
| census_decennial | `ok` | | 2 | 2010, 2020 |
| census_decennial | `absent` | `api_no_data` | 2 | 1990, 2000 |
| usgs_topo | `ok` | | 3 | 1940s–1980s |
| **sentinel2** | — | — | **0** | — |

**Sentinel-2 has no ledger rows at all**, though its task is `failed` and it
serves nothing. That is a defect found while writing this prediction, and it
is fixed in this batch: the chunked search path raised out of
`_search_and_persist_source` when *every* year failed, without flushing the
staged `YearOutcomeLog`, so a total loss recorded nothing while a partial
loss recorded everything. The fix is a `_flush_ledger` before `raise
last_exc`, matching what the un-chunked path already did. **The fix cannot
retro-record 6563dedf's twelve lost Sentinel-2 years** — those rows were
never written and there is no history to recover them from.

### Command

```
docker compose exec api python scripts/requeue_parcels.py \
    --require-sha <m3-sha> --from-ledger \
    6563dedf-23b1-4719-89db-ab135ed24fb3
```

### Predicted

1. **Scope is `['landsat', 'naip']` — two sources, not six, and not three.**
   Sentinel-2 is *not* in scope, because the ledger holds nothing to select
   for it. The `--dry-run` listing shows 16 landsat groups and 17 naip
   groups, 33 in total, each `failed`/`read_timeout` at `attempt 1`.
2. `census`, `property`, `usgs_topo` and `sentinel2` get no task row, are not
   fetched, and their snapshots and ledger rows are untouched.
3. **The parcel still serves 0 Sentinel-2 snapshots after this run.** Making
   Sentinel-2 visible needs a *full-scope* run under the flush fix — a page
   view will now produce one, because the topo/census/property task-row
   triggers are all satisfied and the ledger trigger will not fire for a
   source with no rows. Concretely: this parcel needs
   `requeue_parcels.py --require-sha <m3-sha> 6563dedf-…` (no
   `--from-ledger`) as a second, separate run. That is a deliberate gap in
   this prediction, not an oversight.
4. **The recovery itself is genuinely uncertain and is predicted both ways.**
   The 33 losses were `read_timeout` against Planetary Computer in a burst on
   the morning of 2026-08-26. Nothing in this batch makes PC faster.
   * *If PC answers*: up to 16 Landsat years (1984–1999) and up to 17 NAIP
     years (2010–2026) become `ok`, with matching snapshots. NAIP will not
     produce 17 — the collection's own extent ends 2023, so 2024/2025/2026
     should come back `absent`/`no_scenes` as they do on every other parcel,
     and the honest upper bound is **14 NAIP years**. Landsat 1984–1999 over
     rural Michigan is plausible at high yield but is not guaranteed:
     `absent`/`all_cloud_filtered` and `absent`/`no_scenes` are both legal
     answers for individual years.
   * *If PC times out again*: the same groups re-record
     `failed`/`read_timeout`, `attempts` goes to **2**, they stay retryable,
     and the per-source cooldown allows another attempt in six hours rather
     than blocking the whole parcel. This is a *success* of the instrument,
     not a failure of the heal — the distinguishing evidence is the
     `attempts` column, which could not increment before M3 because the only
     in-place re-run path (`heal_tract_vintage_gaps.py`) overwrote rather
     than added, and that path is deleted in this batch.
5. **Request status.** `complete` if both tasks finish; `partial` if exactly
   one fails; `failed` if both do. Not `complete` with a failed task
   underneath it — that state no longer exists.
6. The parcel's *current* request stays `b1392b23` (full scope), which
   migration 0012 will have rewritten from `complete` to **`partial`** — it
   is one of the 40. The scoped heal request never becomes current.

### Scoring queries

```sql
SELECT source, count(*) FROM imagery_snapshots
WHERE parcel_id = '6563dedf-23b1-4719-89db-ab135ed24fb3' GROUP BY 1;

-- latest ledger by source/outcome/reason, plus attempts, for the parcel
-- request row: status, sources, origin
```

### Falsifiers

* Any census, topo or property task row appearing on the heal request. The
  scope leaked.
* `sentinel2` appearing in the heal request's scope. Selection invented a
  source with no ledger rows.
* Landsat 2000–2026 (27 `ok` groups) losing rows. Reconciliation deleted
  something it was not entitled to.
* The request reading `complete` with a `failed` task row under it. That is
  the aggregation not working, and it is the defect this case exists for.

---

## What none of these three tests

* **The self-running backfill path.** All three go through
  `requeue_parcels.py`. `maybe_refetch_for_backfill`'s new ledger trigger
  fires only on a page view of a parcel with retryable groups and an expired
  per-source cooldown; after P1 and P3 run, the fleet's no-flag backlog is
  either healed or on cooldown, so the first live exercise of that path will
  be whatever breaks next. It is covered by tests, not by a prediction.
* **The admission reserve under real contention.** P2 is the only run large
  enough to hit the cap, and it will show the heal ceiling at 25 — but no
  user traffic is being generated against it, so "a user request still gets
  in at depth 25" stays a unit-tested claim, not a measured one.
* **`partial` in the browser.** Migration 0012 creates 40 `partial` requests,
  but a request is only rendered while a page holds its id. The claim that
  `partial` renders as a working timeline rather than an error banner is
  covered by `ParcelInfo.test.tsx`; it is not observed in production by any
  of these three.
