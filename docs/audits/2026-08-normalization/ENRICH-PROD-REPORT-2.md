# STAC enrichment against production — the run that happened

Session of 2026-08-28, 22:17–22:31 UTC. The second attempt, after
`ENRICH-PROD-REPORT.md` recorded the first stopping correctly at its dry-run
gate on six search-403 errors (NORM-10) without writing anything.

**Outcome: the run completed. All 505 `provenance = 'mosaic_url'` rows are
enriched, the queue is empty, and every predicted quantity was confirmed.**
196 already-exact, 309 id-corrected, **0 merged, 0 unmatched, 0 errors, 0
403s of any kind**. Production now holds 6,156 `snapshot` / 0 `mosaic_url` /
505 `enriched` `scenes` rows. NORM-7 is resolved in production with **no
remainder** — not a residue, not a 403-blocked tail, zero.

One production write was made — `scripts/enrich_synthesized_scenes.py
--execute`, once, under the owner-authorized exception in this session's
prompt. Everything else was read-only: every DB probe opened its own
connection and called `conn.set_session(readonly=True)`. No sweep, no heal,
no requeue, no deploy, no code change.

This batch's commits:

| Commit | Unit |
|---|---|
| `83964ef` | `enrich-prod-dryrun-2.md` + `-stdout.txt` — the clean dry run |
| `f3a31e1` | `PREDICTION-ENRICH.md`, "Production, second attempt" — **before** the execute |
| `f446c11` | `enrich-prod-run.md` + `-stdout.txt` — the execute |
| `d65336d` | the same file's Observed half, scoring the prediction |
| *(this batch)* | this report, STATUS.md |

Captures are named `.md` rather than the prompt's sketched `.txt`/`.json`:
`--report` writes markdown and the script has no JSON mode (`render_report`,
`enrich_synthesized_scenes.py:634`), so the names follow the established
convention (`enrich-local-dryrun.md`, `enrich-prod-dryrun.md`). Full stdout
is captured alongside each, as `-stdout.txt`.

---

## 1. Deploy gates — all four pass

| Gate | Evidence | Result |
|---|---|---|
| a. API sha carries the NORM-10 fix | `GET https://log0s-plotline-api.fly.dev/api/v1/health` at 22:17:26Z → `{"sha":"1cc7cb77bc321f0998ca03a8c6e25536ad12e932","built":"2026-08-28T22:16:06Z"}`. `git merge-base --is-ancestor b32dd93 1cc7cb7` exits 0, and so does `--is-ancestor f2d6cc3 1cc7cb7` | pass — deployed sha is a descendant containing both the fix and its report |
| b. Image labels, both apps | `fly image show -a log0s-plotline-api` (machines `825d69b7e46618`, `48e0de9a713918`) and `-a plotline-worker` (`e2862966b306d8`, `e7845415f57728`): all four carry `GH_SHA=1cc7cb77bc321f0998ca03a8c6e25536ad12e932` | pass — both apps on the health sha |
| c. Migration head | `SELECT version_num FROM alembic_version` → `0016`, read 22:18:24Z | pass |
| d. The constraint actually admits `'enriched'` | `pg_get_constraintdef` for `ck_scenes_provenance`: `CHECK ((provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text, 'enriched'::text])))` | pass |

On (c): the revision id was read from the migration file rather than inferred
from the filename — `backend/alembic/versions/0016_scenes_provenance_enriched.py:46`
declares `revision: str = "0016"`, so prefix and revision id coincide.

On (d): queried, not assumed. "The migration ran" and "the migration applied
its intent" are different claims, and only the second one lets a row carry the
new value.

The deployed sha is `1cc7cb7` ("Keep docs out of docker build context"), one
commit past the `b32dd93` the prompt named as the floor. `scripts/` is still in
the image — the dry run and execute both ran the script from `/app` without
incident.

## 2. Pre-run measurement, read-only, 22:19:01–22:19:19Z

| Measurement | Value | Expected |
|---|---|---|
| `scenes` by provenance | `mosaic_url` **505**, `snapshot` **6156**, `enriched` **0** (value absent) | exactly as required — no drift |
| `scenes` total | 6661 | |
| `parcel_scenes` total | **12884** | merge-accounting baseline |
| `parcel_scenes` carrying a mosaic / total mosaic references | **576 / 613** | |
| dangling `mosaic_scene_ids` references | 0 | |
| queue by source/collection | naip/naip 505 | all NAIP |
| queue rows with no referencing parcel | 0 | every row has a bbox to search with |
| queue `footprint` / `bbox` / `resolution_m` non-NULL | 0 / 0 / 0 | untouched since step 1 |
| queue distinct `cog_url` | 505 of 505 | |
| `imagery_snapshots` rows / distinct `stac_item_id` | 12884 / 6156 | unchanged |
| newest `imagery_snapshots.created_at` | 2026-08-27T19:41:01.190156Z | unchanged since step 1 |
| newest `timeline_task_years.created_at` | 2026-08-27T22:00:44.961932Z | unchanged |

**Zero drift.** Every number is identical to the first attempt's reading at
21:20:55Z on the same day, so the STOP condition on unexplained writes did not
fire. Nothing in production writes these tables yet, and nothing did.

The two structural merge queries, re-run against production as a precondition
rather than a formality:

| Query | Production |
|---|---|
| candidate ids prefix-overlapping another `scenes` row's `item_id`, same collection | **0** |
| queue rows whose `cog_url` is also held by another `scenes` row | **0** |

So 0 merges was the structural expectation, and remained so.

Two counts taken rather than scaled: the `_h_` resolution-spelling class is
**22** rows, and **55** candidates already carry a trailing publication date.

## 3. The dry run — clean

Started detached per NORM-8 / F5 so the ssh client's timeout could not orphan
it, pinned to one machine because `fly` otherwise picks a machine per
invocation and the report lives on the machine that wrote it:

```
fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C \
  "sh -c 'cd /app && nohup python scripts/enrich_synthesized_scenes.py \
     --report /tmp/enrich-prod-dryrun-2.md \
     > /tmp/enrich-prod-dryrun-2-stdout.txt 2>&1 & echo started pid \$!'"
```

pid 658, started 22:19:29Z, script clock 22:19:32Z, finished 22:22:16Z —
**~3.4 minutes**, against the first attempt's 28 s. That is the pacing, and it
is the point: `--min-interval-s 0.2` was left at its default. Polled read-only
(`ls`, `/proc/658`) rather than re-run; both files retrieved with
`fly ssh sftp get --machine 825d69b7e46618`.

| Outcome | Rows |
|---|---|
| already-exact | **196** |
| id-corrected | **309** |
| merged | **0** |
| unmatched | **0** |
| error | **0** |
| would enrich in place | 505 |
| queue after | 0 |

Capture-date disagreements: **0**. Anomalies section: absent. Requests:
505 item GETs + 309 searches ≈ **814**.

**All 309 non-exact rows returned `item GET 404`** — the same single detail
shape the first dry run produced, with no other status appearing anywhere in
the report. The string `403` does not occur in the capture at all.

The six rows the first attempt recorded as errors resolved as `id-corrected`,
each to exactly the id the sequential replay in `ENRICH-PROD-REPORT.md` §5 had
named:

```
pa_m_4007563_ne_18_1_20130605   → …_20130729
pa_m_4007563_se_18_1_20170612   → …_20171207
sc_m_3508254_ne_17_1_20110430   → …_20110705
sc_m_3508254_ne_17_1_20150424   → …_20150714
tn_m_3508959_se_16_060_20180804 → …_20190131
tx_m_3009743_nw_14_1_20141014   → …_20141201
```

Six for six. That is the direct confirmation that NORM-10 was a rate defect
and never a property of those rows.

## 4. The prediction

Written into `PREDICTION-ENRICH.md` as "Production, second attempt" and
committed as `f3a31e1` **before** `--execute` was issued. It is derived from
this session's dry run — the first production resolution under the paced
client — with the first attempt's split cited as corroboration rather than
basis. It names the `parcel_scenes` invariant explicitly (a merge repoints an
array element and deletes the synthesized `scenes` row, so `parcel_scenes`
stays at 12,884 unconditionally while the mosaic-reference total can only fall
below 613 if a merge de-duplicates), and it names both never-run branches with
zero as the prediction and nonzero as expected territory rather than
deviation.

## 5. The execute — once, detached

```
fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C \
  "sh -c 'cd /app && nohup python scripts/enrich_synthesized_scenes.py \
     --execute --report /tmp/enrich-prod-run.md \
     > /tmp/enrich-prod-run-stdout.txt 2>&1 & echo started pid \$!'"
```

pid 671, started 22:25:19Z, script clock 22:25:22Z, structlog summary
22:28:22Z — **~3.2 minutes**. Polled read-only once at 22:29:23Z: pid gone,
both files written. No client-side interruption occurred; had one, the
response would have been to check `/proc` and the queue count, never to
re-run.

```
| already-exact | 196 |  | merged    | 0 |
| id-corrected  | 309 |  | unmatched | 0 |
                          | error     | 0 |

Wrote: 505 enriched, 0 merged, 0 unmatched, 0 error(s).
```

**The execute's per-row table is byte-identical to the dry run's.** `diff` over
the per-row sections of both reports is empty across all 505 rows — same
outcome, same detail string, same corrected id. These were two separate
conversations with Planetary Computer three minutes apart, ~814 requests each.
The dry run and the execute share one `apply_resolutions`, so an identical
*plan* is by construction; an identical *fetch* is not, and it is the strongest
available evidence that the resolution is a property of the catalog rather
than of a moment.

## 6. Post-run verification, read-only, 22:30:08Z

| Check | Result |
|---|---|
| `scenes` by provenance | **6156 `snapshot` + 505 `enriched`, 0 `mosaic_url`** |
| `scenes` total | 6661 — unchanged, nothing deleted |
| `enriched` rows with non-NULL `footprint` / `bbox` / `resolution_m` | **505 / 505 / 505** |
| footprint geometry type | **`POLYGON` on all 505** — no MultiPolygon, the column's type held at 5.7x the local population |
| remaining `mosaic_url` rows | **0** — so there is no remainder needing a reported reason |
| `parcel_scenes` total | 12884 — unchanged |
| `parcel_scenes` carrying a mosaic / total mosaic refs | 576 / 613 — unchanged |
| dangling `mosaic_scene_ids` references | **0** |
| duplicate `(collection, item_id)` pairs, all 6,661 rows | **0** |
| `imagery_snapshots` | 12884 rows / 6156 distinct `stac_item_id`, `max(created_at)` still 2026-08-27T19:41:01.190156Z — neither read nor written |
| `snapshot` rows with a footprint | **0**, unchanged — the deferred full-table pass was not started by accident |

The last two rows are checks the prediction did not name, taken because they
are what a skeptical reader asks after a 505-row id rewrite: the rewrite did
not create a collision it then failed to notice, and it did not quietly widen
its own scope.

**Dry re-run**, 22:30:22Z: `queue (provenance = 'mosaic_url'): 0 row(s)` /
`Nothing to enrich.` The queue is the work list, so an empty queue costs zero
PC requests and re-touches nothing. Idempotence observed, not asserted.

### NORM-9 at production scale

`resolution_m` over the 505 enriched rows, against the 1,102 NAIP `snapshot`
rows:

| `resolution_m` | `snapshot` (NAIP) | `enriched` |
|---|---|---|
| 0.3 | 0 | 38 |
| 0.5 | 0 | 6 |
| 0.6 (incl. the 8 noisy spellings, F2 below) | 0 | 200 |
| 1.0 | **1102** | 261 |

**244 of 505 enriched rows (48.3%) are not 1.0 m**, while every NAIP snapshot
row still says 1.0 m — the constant `app/tasks/timeline.py:712` writes.
NORM-9's claim, previously measured over 88 local rows, now holds at
production scale. **Nothing was fixed here**, per the prompt: recorded,
not repaired. The consequence stands — an enriched NAIP row's `resolution_m`
is the item's `gsd` and a snapshot NAIP row's is the source constant, so
anything reading the column across both is reading two different things.

## 7. Findings

### F1 — the two never-exercised branches are *still* never-exercised

Both finished at zero, exactly as predicted, and **neither is upgraded to
proven**.

* **403-on-item-GET falls through to search.** Zero item-GET 403s across 505
  requests in the dry run and 505 in the execute; `grep -c 'item GET 403'` → 0
  in both captures. Every non-exact row 404'd. The branch has now gone 88
  local + 1,515 production resolutions without being entered. The geometry
  audit's six forbidden NAIP items remain outside this queue, so this
  population never had the chance to exercise it. **Tested by unit tests,
  never observed live.**
* **Collision-merge.** 0 merges, on the structural grounds production's own
  queries confirmed in §2. `_merge_scene` has still never run outside its
  tests. The `parcel_scenes` invariant the prediction stated held trivially
  rather than being tested — 12,884 rows and 576/613 references unchanged is
  what 0 merges implies — so **that invariant is still an argument from the
  code (`enrich_synthesized_scenes.py:580-625`), not an observation.**

Recording this precisely matters more than it looks: a run this clean invites
the summary "the merge path works in production", and it does not say that. It
says the merge path was not needed in production.

### F2 — PC's `gsd` carries float-representation noise, and `= 0.6` misses rows

**New. Open, unfixed. Recorded as STATUS.md NORM-11.**

`SELECT resolution_m, count(*) FROM scenes WHERE provenance = 'enriched'
GROUP BY 1` returns **11 buckets, not 4**. Eight of the 200 0.6 m rows carry a
value near 0.6 but not equal to it:

```
0.5999999999999901  mi_m_4408631_nw_16_h_20160722, mi_m_4508560_nw_16_h_20160725
0.5999999999999975  mi_m_4408418_sw_16_h_20160809
0.5999999999999994  ne_m_4109549_nw_15_.6_20160720_20161019
0.6000000000000011  az_m_3311151_nw_12_.6_20170604_20171128
0.6000000000000012  mo_m_4009441_ne_15_h_20160615
0.600000000000007   ct_m_4107348_se_18_.6_20160721_20160913
0.6000000000000097  vt_m_4407330_se_18_h_20160804
```

**This is upstream data faithfully stored, not a conversion artifact.** `_gsd`
(`scripts/enrich_synthesized_scenes.py:544`) reads `properties["gsd"]`
verbatim into a `Double` column (`app/models/parcels.py:474`), and a `Double`
holding 0.6 reads back as 0.6 — a *different* double means a different source
value. Confirmed directly rather than argued, read-only from inside the
machine at 22:31Z:

```
GET .../api/stac/v1/collections/naip/items/az_m_3311151_nw_12_.6_20170604_20171128
→ 200, properties.gsd = 0.6000000000000011
```

**Why it matters later rather than now.** Nothing reads `scenes.resolution_m`
yet. The two obvious future readers both fail quietly: an equality filter
(`WHERE resolution_m = 0.6` silently misses 8 of 200 rows) and a
`GROUP BY resolution_m` (spurious buckets), and the UI chip at
`frontend/src/components/MapView.tsx:298-301` would render
`0.5999999999999901 m` verbatim.

**Not fixed here**, and the reason is not only scope: the honest fixes are to
round on write (loses the upstream value) or to compare with a tolerance /
round on read (keeps it), and choosing between them is the same decision
NORM-9's remedy must make about what the pipeline writes for resolution. It
belongs in that commit.

The local 88-row run could not have found this — none of its 30 0.6 m rows
carried a noisy value. 505 rows found what 88 could not, which is the ordinary
reason production runs earn their own report.

### F3 — the id/filename split, measured a third time

196 of 505 exact (**38.8%**), 309 corrected (61.2%). Against F1's 31.7% over
312 NAIP snapshot rows and the local queue's 35.2% over 88. Three populations,
three measurements within 7 points — enough to support F1's claim that the
relationship is a property of the catalogued vintage rather than of how
Plotline used the tile, which is the assumption the prediction's bands were
drawn around.

The `_h_` refinement from `ENRICH-PROD-REPORT.md` §7 reproduced exactly: of
the 22 `_h_` rows, **17 are `id-corrected`** and **5 are `already-exact`** —
PC catalogues those state-years with the literal `_h_`. Identical in both of
this session's runs.

## 8. State left behind

* **`scenes`: 6,661 rows — 6,156 `snapshot`, 505 `enriched`, 0 `mosaic_url`.**
  All 505 enriched rows carry a catalogued `item_id`, a `POLYGON` footprint, a
  `bbox` and a `resolution_m`.
* `parcel_scenes`: 12,884 rows, 576 carrying 613 mosaic references, 0
  dangling — not touched at all, merges being zero.
* `imagery_snapshots`: 12,884 rows, untouched, neither read nor written.
* The 6,156 `snapshot` rows are unchanged and their footprints are still NULL.
  **That full-table footprint pass is a separate, still-deferred piece of
  work** (STATUS.md NORM-7), and it is what makes ADR rule 4 — "the next
  geometry audit is a query over `scenes`, not a refetch" — actually true.
  Today it is true only of the 505.
* Migration 0016's widened CHECK is now load-bearing: 505 rows use the value
  it added.
* On machine `825d69b7e46618`: `/tmp/enrich-prod-dryrun-2.md`,
  `/tmp/enrich-prod-dryrun-2-stdout.txt`, `/tmp/enrich-prod-run.md`,
  `/tmp/enrich-prod-run-stdout.txt` (all four retrieved and committed here),
  `/tmp/enrich-prod-rerun.md` (the empty-queue re-run's report), and four
  read-only probe scripts `/tmp/probe_{gates,pre,pre2,post,gsd}.py`. Nothing
  else was created.
* No process is still running. pids 658 and 671 both exited on their own; both
  were confirmed gone by `/proc` before their files were fetched.

## 9. What this unblocks, and what it does not

**Step 2 is no longer blocked on NORM-7.** The reasoning, stated so it can be
checked rather than trusted: step 2's dual-write inserts a `scenes` row per
catalogued item it fetches, keyed `(collection, item_id)`. The collision
NORM-7 describes required a pre-existing row whose `item_id` was a *candidate*
— a string the catalog does not use — so the unique constraint could not see
the two rows as the same item. Every production `scenes` row now carries an id
the catalog actually serves, verified by `cog_url` equality against the item's
own image asset href, so a dual-write insert for that tile hits the unique
constraint and becomes an upsert rather than a silent duplicate.

There is no remainder to reason around. Had rows been left 403-blocked, the
argument would have been that PC will not serve such an item to the
dual-write either, so it could not insert a colliding row for it — but that
argument is not needed here, because the count is 0.

**What step 2 still owes**, both open and both decisions about what the
dual-write writes: NORM-9 (`resolution_m` comes from the per-source constant,
not the item's `gsd`) and NORM-11 (that `gsd` carries float noise, so the fix
has to choose between preserving the upstream value and making equality work).

**What is still deferred:** the footprint pass over the 6,156 `snapshot` rows,
tracked in NORM-7.
