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
