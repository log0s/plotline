# Prediction — STAC enrichment of synthesized scenes (local)

Written and committed **before** `scripts/enrich_synthesized_scenes.py` runs
against the local database. The Observed half is appended after the run; the
prediction half is never edited (ADR record rule 4).

Subject: the **88** local `scenes` rows with `provenance = 'mosaic_url'` —
NAIP mosaic tiles synthesized from `additional_cog_urls` by step 1's backfill,
each carrying a URL-derived candidate `item_id` and NULL `footprint` / `bbox` /
`resolution_m`. STATUS.md NORM-4 and NORM-7; `STEP1-PROD-REPORT.md` §9.

**Production is out of scope for this session.** §6 carries the formula the
later production session evaluates against its own 505 rows.

## 0. What is already known, disclosed up front

The 30-minute lookup-path investigation (item 1 of the prompt, findings in
`ENRICH-LOCAL-REPORT.md` §1) probed the live Planetary Computer catalog for
**three** of the 88 rows before this prediction was written, to establish that
the two lookup paths work at all:

| Candidate id | Probe | Implied outcome |
|---|---|---|
| `ca_m_3712230_se_10_060_20180804_20190210` | item GET → 200, `assets.image.href` == the row's `cog_url` | already-exact |
| `ca_m_3712230_se_10_060_20200524` | item GET → 200, href matches | already-exact |
| `ca_m_3712230_se_10_h_20160531` | item GET → 404; year+bbox search returned 2 items, one matching, id `ca_m_3712230_se_10_.6_20160531_20161004` | id-corrected |

So 3 of 88 outcomes are foreknown and 85 are not. Everything below is derived
from `STEP1-REPORT.md` F1's measurement and from SQL over the local database —
not from further probing.

## 1. Queue

| Quantity | Predicted |
|---|---|
| Queue at start (`provenance = 'mosaic_url'`) | **88** |
| Rows enriched in place | **88** |
| Rows merged into an existing `scenes` row | **0** |
| Rows left unmatched | **0** |
| Errors | **0** |
| **Queue after the run** | **0** |

Falsified if the queue after the run is not 0 with no explanation, or if the
starting queue is not 88.

## 2. The id-outcome split

F1 measured, over the 312 local NAIP snapshot rows on 2026-08-28: the
state-prefixed filename stem **equals** the catalogued item id in 99 (31.7%),
is a **proper prefix** of it in 204 more (65.4%), and is **neither** in 8
(2.6%), because the id and the filename spell the resolution differently
(`_.6_` / `_.5_` in the id versus `_h_` in the filename).

Scaling those rates to 88:

| Outcome | Rate | Predicted | Tolerance |
|---|---|---|---|
| `already-exact` (candidate id was catalogued) | 31.7% | **28** | 12–45 |
| `id-corrected` (found by search under another id) | 65.4% | **58** | 41–74 |
| — of which the `_h_` resolution-spelling class | — | **2** | exactly 2 |

The band on the first two rows is wide on purpose, and the reason is worth
stating rather than hiding in a ±: **the queue is not the population F1
measured.** F1 measured tiles that were served as a snapshot row's primary;
the queue is the tiles that never were. There is no reason to expect the
id/filename relationship to differ between the two — it is a property of the
state-year vintage PC catalogued, not of how Plotline used the tile — but that
is an argument, not a measurement, so the point estimate is F1's rate and the
band is generous.

Two structural facts sharpen the edges:

* **12 of the 88 candidate ids already carry a trailing publication date**
  (`item_id ~ '_[0-9]{8}_[0-9]{8}$'`), because their filenames did. Those are
  exact by construction unless PC catalogues them under a third form. So
  `already-exact` ≥ 12 is close to certain, and 12 is the floor of the band.
* **The filename-shape count is a floor, not the estimate.** The probe of
  `ca_m_3712230_se_10_060_20200524` — a single-date filename — hit 200 with a
  matching href, so a vintage can catalogue an id with no publication date at
  all. The 76 single-date candidates are therefore not all corrections.
* **The `_h_` class is exactly 2 rows** (`ca_m_3712230_se_10_h_20160531`,
  `id_m_4311623_sw_11_h_20130830`). That is a count, not a rate: every member
  of F1's "neither" class has `_h_` in the filename, and the queue holds two.
  Both are predicted `id-corrected` via the search — one is already confirmed
  so by the probe above — **not** unmatched. The class is a naming mismatch,
  not an absence.

## 3. Merges: 0, and this one is structural rather than probabilistic

A merge requires the catalogued id a row resolves to be **already held by
another `scenes` row**. Three queries say no such row exists:

1. Candidate ids that prefix-overlap any other `scenes` row's `item_id`, in
   either direction, same collection: **0 rows.**
   ```sql
   SELECT q.item_id, s.item_id, s.provenance
   FROM scenes q JOIN scenes s ON s.id <> q.id AND s.collection = q.collection
     AND (s.item_id LIKE q.item_id || '%' OR q.item_id LIKE s.item_id || '%')
   WHERE q.provenance = 'mosaic_url';
   ```
2. NAIP `scenes` rows sharing a tile **filename** with a queue row under a
   different URL — the URL-variant duplicate the backfill's exact-string match
   could not see: **0 rows.**
3. The two `_h_` rows are the only ones whose corrected id can differ from the
   candidate by more than a suffix, so they are the only residual risk. No
   `scenes` row exists for the `ca_m_3712230_se_10_*` or `id_m_4311623_sw_11_*`
   quads other than the queue rows themselves (13 rows, all
   `provenance = 'mosaic_url'`) — so neither has a merge partner either.

**0 merges is therefore a claim about the table, not a guess about the
catalog.** A nonzero count would mean a corrected id landed on an existing row
by a route none of the three queries covers, and that is a finding worth
stopping on rather than a tolerance to absorb.

## 4. Unmatched: 0, with a named way to be wrong

The geometry audit found **6 distinct NAIP items PC answers HTTP 403 for** on
the item endpoint (`FINDINGS.md` Appendix C), out of 283 assessable NAIP items
— a 2.1% rate. Checked, not guessed: **none of those six is in this queue.**

```sql
-- forbidden(item_id) = the six from Appendix C
SELECT f.item_id, q.item_id FROM forbidden f
LEFT JOIN scenes q ON q.provenance = 'mosaic_url'
  AND (f.item_id LIKE q.item_id || '%' OR q.item_id LIKE f.item_id || '%');
-- → six rows, every q.item_id NULL
```

Two reasons that does not make unmatched *impossible*, both of which would be
deviations rather than falsifications:

* At the audit's 2.1% rate, ~2 of 88 could 403 on the item endpoint anyway.
  **A 403 there is predicted to be recoverable**, because this pass falls
  through to the search on any non-200 and the audit never established that
  the *search* endpoint withholds those items — it only ever called the item
  endpoint. If a 403 turns out to hide an item from the search too, that is
  new knowledge about PC and belongs in the report.
* Three queue rows are on the `va_m_3807708_se_18` quad — the same quad four
  of the audit's six 403s sit on, at different dates
  (`_060_20210910`, `_060_20231113_20240103`, `_1_20110530`). If 403 is
  quad-scoped rather than item-scoped, those three are where it shows.
  Predicted: they enrich normally, because the audit's finding is per-item.

Predicted `unmatched-403` = 0, `unmatched-404` = 0, `unmatched-nomatch` = 0,
`error` = 0. Any nonzero value is a deviation to explain, not to smooth.

## 5. Everything else

| Quantity | Predicted | Why |
|---|---|---|
| Capture-date disagreements | **0** | F1: the capture date is the first date field under either naming, so `parse_naip_tile_url` reads it right in all 312 cases it measured. A disagreement would mean PC's `properties.datetime` differs from the filename's own capture field. |
| `scenes` rows after the run | **1262** | unchanged: 88 updates in place, 0 deletes (0 merges). |
| `parcel_scenes` rows touched | **0** | only a merge repoints one, and merges are 0. |
| Dangling `mosaic_scene_ids` references after | **0** | nothing is deleted. |
| `scenes` with `footprint IS NOT NULL` after | **88** | every enriched row gets the item's Polygon geometry. Was 0 — no step-1 row has a footprint. |
| `scenes` with `resolution_m IS NOT NULL`, NAIP | **288** | 200 snapshot rows already carry one, plus the 88 enriched. |
| Rows with `provenance = 'enriched'` | **88** | |
| PC requests | **~146** | 88 item GETs, plus one search per non-exact row (~58). No pagination: a year's NAIP items inside a 3 km box is a handful (the probe returned 2). |
| Second run: queue | **0**, nothing fetched, nothing written | the queue is the work list, so an empty queue costs zero requests. |

## 6. The production formula, for the later session

Do **not** carry these local counts to production. Evaluate this against the
505-row production queue, with the two structural queries re-run there first:

```
queue                     = 505                       (STEP1-PROD-REPORT §4)
already-exact   ≈ 0.317 × 505 ≈ 160   (band 60-260, same F1 caveat)
id-corrected    ≈ 0.654 × 505 ≈ 330   (band 230-430)
_h_ class       = SELECT count(*) FROM scenes
                  WHERE provenance='mosaic_url' AND item_id LIKE '%\_h\_%';
                  -- a count to take, not a rate to scale
merges          = 0 ONLY IF the two queries in §3 return 0 rows there.
                  Production has 6,156 snapshot rows against local's 1,174,
                  so the chance of a URL-variant partner is materially higher
                  and the queries are a precondition, not a formality.
unmatched       ≤ 6 + (403 rate 2.1% × 505 ≈ 11 item-GET 403s, most of them
                  expected to be recovered by the search).
                  First check whether any of Appendix C's six ids is in the
                  production queue — locally none were, and that is a local
                  fact, not a production one.
requests        ≈ 505 + (505 - already-exact) ≈ 850
```

The production run must also, per NORM-8, write its report to a file inside
the Fly machine and be read back from there — `--report` is required for
exactly that reason, and a ~850-request run will outlive the ssh client's
2-minute timeout.

## 7. What would stop the run

* The starting queue is not 88 — something changed the table since step 1.
* A merge is planned when §3 predicted none, and the three queries above do
  not explain it.
* A capture-date disagreement, which contradicts F1's strongest claim.
* Any `error` outcome: a transport failure surviving four attempts with
  Retry-After backoff is an unhealthy endpoint, and the honest response is to
  stop and report rather than to run the remainder against it.

---

## Observed — local run, 2026-08-28

Appended after the run. The prediction half above is unedited. Captures:
`enrich-local-dryrun.md` (18:03:28Z) and `enrich-local-run.md` (18:03:52Z),
both written by the script itself. Report: `ENRICH-LOCAL-REPORT.md`.

### Scorecard

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| Queue at start | 88 | **88** | confirmed |
| Rows enriched in place | 88 | **88** | confirmed |
| Rows merged | 0 | **0** | confirmed |
| Rows unmatched | 0 | **0** | confirmed |
| Errors | 0 | **0** | confirmed |
| Queue after the run | 0 | **0** | confirmed |
| `already-exact` | 28 (band 12–45) | **31** | confirmed, inside the band |
| `id-corrected` | 58 (band 41–74) | **57** | confirmed, inside the band |
| — `_h_` resolution class, `id-corrected` | exactly 2 | **2** | confirmed |
| `unmatched-403` / `unmatched-404` / `unmatched-nomatch` | 0 / 0 / 0 | **0 / 0 / 0** | confirmed |
| Capture-date disagreements | 0 | **0** | confirmed |
| `scenes` rows after | 1262 | **1262** | confirmed |
| `parcel_scenes` rows touched | 0 | **0** (2,945, unchanged) | confirmed |
| Dangling `mosaic_scene_ids` after | 0 | **0** | confirmed |
| `footprint IS NOT NULL` after | 88 | **88**, all `ST_Polygon` | confirmed |
| NAIP `resolution_m IS NOT NULL` after | 288 | **288** | confirmed |
| `provenance = 'enriched'` | 88 | **88** | confirmed |
| PC requests | ~146 | **145** (88 GETs + 57 searches) | confirmed |
| Second run: queue 0, nothing fetched, nothing written | yes | **yes** | confirmed |

**Every line confirmed. No deviations, no falsifications.** One new finding
the prediction did not anticipate, in the "not predicted, not contradicted"
sense: `ENRICH-LOCAL-REPORT.md` F2, on `resolution_m`.

### The three predictions that could have been wrong

**The split (§2).** 31 exact / 57 corrected against 28 / 58 predicted. The
measured exact rate is 35.2% against F1's 31.7% — a 3.5-point difference over
88 rows, which is inside the noise and says nothing on its own. The two
structural sub-claims both held exactly:

* all **12** pubdate-carrying candidates were `already-exact`, as predicted by
  construction;
* **19 of the 76** single-date candidates (25.0%) were `already-exact` too —
  the shape the `ca_m_3712230_se_10_060_20200524` probe warned about, so the
  filename-shape floor of 12 was indeed a floor and not the estimate.

**Merges (§3).** 0, as the three structural queries said. Nothing arrived at
an id another row already held, by any route.

**The 403s (§4).** **Zero item-GET 403s across all 88 requests** — the string
`item GET 403` does not appear in the run report. The three
`va_m_3807708_se_18` rows on the quad carrying four of the geometry audit's
six 403s all enriched normally, all `already-exact`. So **403 is item-scoped,
not quad-scoped**, on the one quad in this queue that could have shown
otherwise.

The consequence for the production session: the branch predicted in §4 — "a
403 on the item endpoint is recoverable, because the search does not
necessarily withhold the item" — was **never exercised**, because no 403
occurred. It remains an untested prediction, not a confirmed one, and
production's 505-row queue is where it gets tested.

### Nothing was left behind

One transaction, committed once, then a re-run that found an empty queue,
issued zero PC requests and wrote nothing. `imagery_snapshots` was neither
read nor written (2,945 rows, unchanged); `parcel_scenes` was not touched
(2,945 rows, 0 dangling references); the 1,174 `provenance = 'snapshot'` rows
are unchanged, footprints still NULL — that full-table enrichment is a
separate pass and is explicitly deferred (STATUS.md NORM-7).

---

## Prediction — production, second attempt, 2026-08-28

Written and committed **before** `--execute` runs against production. The
local prediction above and the local Observed section are untouched; so is
`ENRICH-PROD-REPORT.md`, which records the first attempt's STOP.

This prediction is derived from **this session's own dry run**
(`enrich-prod-dryrun-2.md`, 22:19:29–22:22:59Z, pid 658 on machine
`825d69b7e46618`) — the first production resolution under the NORM-10 fix
(`f2d6cc3`, deployed as `1cc7cb7`): split retry policy plus
`--min-interval-s 0.2` pacing. The first attempt's dry run
(196 / 303 / 0 / 0 / **6 error**) is corroborating evidence, not the basis:
it ran under the unpaced client whose throttle NORM-10 describes.

The dry run and the execute share one `apply_resolutions`
(`enrich_synthesized_scenes.py:628`), so a plan that differs from the write
would be a bug, not a surprise. What the execute does *not* share is the
fetch: it re-issues all ~814 requests against the live catalog. Every number
below is therefore a prediction about a **second** conversation with
Planetary Computer, not a replay of the first.

### 1. The run

| Quantity | Predicted | Basis |
|---|---|---|
| Queue at start | **505** | measured 22:19:01Z, and again by the dry run at 22:19:32Z |
| `already-exact` | **196** | dry run |
| `id-corrected` | **309** | dry run |
| — of which `_h_` spelling class | **17** of the queue's 22 (`5` are `already-exact`) | dry run; refines `ENRICH-PROD-REPORT.md` §7 |
| `merged` | **0** | dry run, and both structural queries return 0 in production (§3's form, re-run 22:19:01Z) |
| `unmatched` | **0** | dry run |
| `error` | **0** | dry run |
| Rows enriched in place | **505** | |
| **Queue after the run** | **0** | |
| Capture-date disagreements | **0** | dry run; F1's strongest claim, now measured over 505 rows |
| PC requests | **~814** | 505 item GETs + 309 searches |
| Wall time | **3–5 min** | dry run took 3.4 min at 0.2 s pacing; the execute adds one `commit()` over 505 UPDATEs |

Falsified if the queue after the run is not 0 with no explanation, or if the
starting queue is not 505.

### 2. Post-run state

| Quantity | Before (22:19:01Z) | Predicted after |
|---|---|---|
| `scenes` `provenance = 'snapshot'` | 6156 | **6156** — untouched, not this pass's queue |
| `scenes` `provenance = 'mosaic_url'` | 505 | **0** |
| `scenes` `provenance = 'enriched'` | 0 (value absent) | **505** |
| `scenes` total | 6661 | **6661** — 505 updates in place, 0 deletes because 0 merges |
| `enriched` rows with non-NULL `footprint` / `bbox` / `resolution_m` | 0 / 0 / 0 | **505 / 505 / 505** |
| footprint geometry type | — | `ST_Polygon` on all 505, as locally |
| `parcel_scenes` total | 12884 | **12884** |
| `parcel_scenes` carrying a mosaic / total mosaic refs | 576 / 613 | **576 / 613** |
| Dangling `mosaic_scene_ids` references | 0 | **0** |
| `imagery_snapshots` | 12884 rows / 6156 distinct `stac_item_id` | **unchanged** — this pass neither reads nor writes it |

**The `parcel_scenes` invariant, stated because it is the one a reader is
most likely to get wrong: 12884 is unchanged even if merges are nonzero.** A
merge deletes the *synthesized `scenes` row* and rewrites the offending
`parcel_scenes.mosaic_scene_ids` **array element** to point at the surviving
scene (`_merge_scene`, `enrich_synthesized_scenes.py:580-625`). It repoints
references; it never deletes a `parcel_scenes` row. The count that *can* move
under a merge is the **total mosaic references** (613), because the merge
de-duplicates: if one `parcel_scenes` row already referenced both the
synthesized row and its merge target, the two collapse to one
(`if replacement not in merged`). So: `parcel_scenes` rows **= 12884
unconditionally**; mosaic references **= 613 given 0 merges**, and ≤ 613 if
merges occur.

### 3. The two branches that have never run

Both are predicted **zero**, and both being nonzero is **expected territory,
not a deviation** — this is the largest population either has ever faced.

**a. 403-on-item-GET falls through to search.** Predicted **0 occurrences**.
Zero across 88 local rows, zero across the first production dry run's 505,
and zero across this dry run's 505: all 309 non-exact rows returned `item GET
404`, and the 196 exact ones returned 200. The branch would enter 1,098 rows
without being taken. The geometry audit's six forbidden NAIP items are not in
this queue (checked locally in §4; production's queue is all-NAIP but none of
the six ids appear in the dry run's per-row table). A nonzero count here is
**new knowledge**, not a failure: it would be the first live evidence that the
design assumption "a 403 on the item endpoint is recoverable via the search"
holds — or, if such a row lands `unmatched-403`, the first evidence it does
not. Either way it gets reported, not smoothed.

**b. Collision-merge.** Predicted **0**. `_merge_scene` has never run outside
its unit tests. Production's own structural queries return 0 (both re-run
22:19:01Z: candidate ids prefix-overlapping another `scenes` row's `item_id`
in the same collection → 0; queue `cog_url` also held by another `scenes` row
→ 0; and all 505 queue `cog_url`s are distinct). The dry run planned 0 merges
over the same 505 rows. This is a claim about the table, not a guess about the
catalog. A nonzero merge would mean a corrected id landed on an existing row
by a route none of those queries covers — worth stopping to explain, per §7
above.

**If both finish at zero, neither is upgraded to "proven".** They stay
"tested by unit tests, never observed live," and that is what the record will
say.

### 4. NORM-9 — the `resolution_m` distribution this run finally measures

`gsd` reaches `scenes.resolution_m` only through an enrichment write, so this
run produces production's first real NAIP resolution numbers. Predicted, by
scaling the local 88-row distribution (`ENRICH-LOCAL-REPORT.md` F2) to 505:

| `resolution_m` | Local (of 88) | Predicted prod (of 505) | Band |
|---|---|---|---|
| 0.3 | 9 (10.2%) | ~52 | 15–120 |
| 0.5 | 1 (1.1%) | ~6 | 0–30 |
| 0.6 | 30 (34.1%) | ~172 | 100–260 |
| 1.0 | 48 (54.5%) | ~275 | 180–360 |

The bands are wide on purpose and the point estimates are weak: resolution is
a property of the **state-year vintage**, and production's queue spans far
more states than the local one (which is heavily CA/ID). The one claim worth
falsifying is the qualitative one: **`1.0` will no longer be the universal
value**, and materially more than zero rows will carry 0.6 or 0.3 — which is
what makes NORM-9's "every NAIP snapshot row says 1.0 m and most are wrong"
true at production scale. The 6,156 `snapshot` rows are **not** corrected by
this run and will still all say 1.0; that disagreement-by-provenance is
NORM-9's open consequence, not this run's defect. Nothing here is fixed by
this pass.

### 5. What would stop the run

Unchanged from §7 above, restated for this attempt:

* The starting queue is not 505.
* Any `error` outcome. The NORM-10 class specifically should not recur — a
  search 403 now retries — so an `error` in the execute is either a genuinely
  permanent search 403 (a 403 surviving four paced attempts) or something new.
  Either is a finding.
* A capture-date disagreement, after 593 rows and two production dry runs
  produced none.
* A merge the three structural queries do not explain.

A STOP here is an outcome, not a failure. But note the asymmetry the execute
introduces and the dry run did not have: **the write commits once, at the
end** (`enrich_synthesized_scenes.py:763`). There is no partial state to stop
into — the run either commits all 505 or raises and rolls back. So "stop"
after `--execute` starts means "observe and report", not "intervene".
