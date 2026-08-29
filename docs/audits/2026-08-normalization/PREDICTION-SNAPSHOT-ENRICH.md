# Prediction — the snapshot-scene enrichment heal, LOCAL run

Written 2026-08-29, **before** `scripts/enrich_snapshot_scenes.py` was run
against anything. Committed before the run it predicts. The Observed section
is appended after; **nothing above it is edited afterwards.**

Subject: the local development database only. No production access of any kind
is in scope for this session, and none was taken.

## §0 — Disclosure: what is blind and what is not

Honesty about this first, because `PREDICTION-STEP3.md` §0 set the standard
and the same care is owed here.

**Blind.** Every outcome quantity below — enriched count, 404 remainder, 403
remainder, resolution rewrites, capture-date disagreements, anomalies, request
count, wall time. No row of the queue had been fetched when this was written.

**Not blind, and disclosed as such:**

1. **The queue size (1,031) and the excluded topo count (143)** are direct
   `SELECT count(*)` measurements taken before writing this, not forecasts.
   They are recorded so the arithmetic below can be checked, not scored as
   predictions.
2. **Three items were fetched from the Planetary Computer while designing the
   script** — one landsat, one naip, one sentinel-2 — to settle whether each
   collection's items carry an item-level `gsd`. That measurement is what P6
   and P7 rest on, and P7 in particular (sentinel-2 carries no `gsd`) would be
   a guess without it. The three ids are named in §P7 so the overlap with the
   queue is visible rather than buried.
3. **The NAIP post-run distribution (P5) is derived from the stored `item_id`
   strings**, not from any fetch. That is a real forecast — it predicts that
   PC's `gsd` equals the resolution token in NAIP's own filename convention on
   all 194 fetchable rows — but the *inputs* were measured locally, so the
   arithmetic is auditable rather than remembered.

**Appendix C's six forbidden items were checked for presence in the local
population by query, as the prompt directed. They were not re-probed against
PC.** So P3's 6 is a forecast that a 2026-08-12 measurement still holds on
2026-08-29, not a reading of today's catalogue.

## §1 — The queue, with the arithmetic

`scenes` on the local database, before any run:

| provenance | source | rows | footprint NULL | bbox NULL |
|---|---|---|---|---|
| enriched | naip | 88 | 0 | 0 |
| selection | landsat | 43 | 0 | 0 |
| selection | naip | 21 | 0 | 0 |
| selection | sentinel2 | 11 | 0 | 0 |
| selection | usgs_topo | 5 | 5 | 0 |
| snapshot | landsat | 618 | **618** | 0 |
| snapshot | naip | 200 | **200** | 0 |
| snapshot | sentinel2 | 213 | **213** | 0 |
| snapshot | usgs_topo | 143 | **143** | 0 |

Derivation of the queue:

```
provenance = 'snapshot'                       1,174
  − source = 'usgs_topo'                      − 143   (no PC item exists)
  − footprint already non-NULL                −   0   (there are none)
  = queue                                     1,031
```

618 landsat + 200 naip + 213 sentinel2 = **1,031**, which is what the queue
query returns. **Excluded: 143** topo rows, all with NULL footprint, none of
them fetchable.

**Every one of the 1,031 rows already has a non-NULL `bbox`** — the step-1
backfill copied it from `imagery_snapshots`, which did hold the envelope even
though it never held the outline. So the "fill bbox where NULL" branch has an
empty population locally and P8 predicts zero for it. It is not dead code: the
production population is not measured here, and a `selection`-provenance row
could arrive without one.

Ordering is `ORDER BY collection, item_id`, so the queue runs
`landsat-c2-l2` (618) → `naip` (200) → `sentinel-2-l2a` (213). At the default
batch size of 200 that is **6 batches**: 1–3 pure landsat, 4 landsat+naip,
5 naip+sentinel2, 6 sentinel2.

## §2 — The runs this predicts

Three runs, in order:

* **Run A — dry run** over the whole queue. Fetches, writes nothing.
* **Run B — `--execute`, killed deliberately** partway with `SIGKILL`, to
  exercise resume for real rather than only in a unit test. The queue is
  ~3.5 minutes long at the default pace (P10), which is long enough to
  interrupt honestly.
* **Run C — `--execute`**, resuming whatever B left.

## §3 — Predictions

| # | Quantity | Predicted |
|---|---|---|
| P1 | Rows fetched, run A | **1,031** |
| P2 | Matched (item GET 200), run A | **1,025** |
| P3 | Unmatched — item GET **403** | **6** |
| P4 | Unmatched — item GET **404** | **0** |
| P5 | NAIP `resolution_m` rewritten | **91** |
| P6 | landsat `resolution_m` rewritten | **0** |
| P7 | sentinel2 `resolution_m` rewritten | **0** |
| P8 | `bbox` filled | **0** |
| P9 | Capture-date disagreements | **0** |
| P10 | Wall time, run A | **3.5–5 min** |
| P11 | Non-Polygon geometry anomalies | **0** |
| P12 | Errors, and exit code | **0**, exit **0** |
| P13 | Footprints written across B+C | **1,025** |
| P14 | Queue after run C | **6** |
| P15 | Rows refetched across B+C | **≤ 200** (one batch), and **0 rows written twice** |
| P16 | STAC requests, run A | **1,031** |

### P1–P2 — the queue resolves

Every one of these ids was written by the pipeline from a Planetary Computer
search result and stored in `imagery_snapshots.stac_item_id`; step 1's
backfill copied it verbatim. Unlike NORM-4's URL-parsed candidates, there is
no reason for such an id to be anything but catalogued. 1,031 fetched,
1,031 − 6 = **1,025** resolved.

### P3 — the 403 remainder is 6

`../2026-08-geometry-audit/FINDINGS.md` Appendix C names 6 distinct NAIP items
that answered HTTP 403 on 2026-08-12. **All six are present in the local
`provenance = 'snapshot'` population** — verified by query, and all six
currently carry `resolution_m = 1.0`:

```
ut_m_4011118_sw_12_1_20160627_20161017
ut_m_4011125_sw_12_060_20211105
va_m_3807708_se_18_060_20181019_20190212
va_m_3807708_se_18_1_20120511_20120709
va_m_3807708_se_18_1_20140927_20141126
va_m_3807708_se_18_1_20160718_20160928
```

Appendix C is the **floor** of the unmatched remainder, and this predicts it
is also the ceiling. The pass never retries an item 403 (NORM-10: on the item
endpoint a 403 is a permanent refusal, not the throttle), so each of the six
costs exactly one request.

**What would falsify it in the interesting direction:** a 403 on an item
outside that list, which would mean the forbidden set has grown since
2026-08-12; or fewer than 6, which would mean PC has opened access. Either is
a finding worth a STATUS.md line.

### P4 — the 404 remainder is 0, and the reasoning is the part that matters

A 404 here means *an id the pipeline once served that PC no longer resolves* —
a materially different claim from the mosaic pass's 404s, which were
mis-parsed candidates and expected.

Grounds for zero: the ids are catalogued, not derived; the two production
enrichment runs made 1,515 item resolutions against PC without meeting a
catalogued id that had disappeared; and PC's NAIP and Landsat Collection-2
item ids are stable identifiers.

**The one thing that could make this wrong, stated in advance:** Sentinel-2
L2A ids embed a processing-baseline timestamp
(`…_R127_T11SPV_20210412T073852`), and PC has reprocessed parts of that
archive. A reprocessed granule is republished under a *new* id, and the old
one can stop resolving. 213 of the 1,031 rows are sentinel-2, the oldest from
2015. If P4 misses, this is the mechanism, and the miss should be concentrated
in `sentinel-2-l2a` rather than spread across collections.

**Threshold, set before the run:** more than a handful of 404s is a
stop-and-think result. Concretely — **more than 10, or any 404 outside
`sentinel-2-l2a`, stops the run and goes in the report as a finding rather
than being worked around.** There is no fuzzy-matching fallback to reach for
and none will be added.

### P5 — the NAIP distribution after the run

NAIP filenames carry the product resolution as a token before the capture
date (`…_18_030_20230901…` = 30 cm, `…_11_.6_20160704…` = 0.6 m). Grouping
the 200 NAIP snapshot rows by that token, with the six forbidden items broken
out:

| token | resolution it implies | rows | of which forbidden | fetchable |
|---|---|---|---|---|
| `1` | 1.0 | 107 | 4 | 103 |
| `060` | 0.6 | 70 | 2 | 68 |
| `030` | 0.3 | 15 | 0 | 15 |
| `.6` | 0.6 | 5 | 0 | 5 |
| `.5` | 0.5 | 3 | 0 | 3 |

All 200 currently store **1.0** — NORM-9's constant, and NORM-13's
population. So the predicted rewrites are every fetchable row whose token is
not `1`:

```
68 (060) + 15 (030) + 5 (.6) + 3 (.5) = 91
```

and the predicted distribution afterwards:

| `resolution_m` | rows | why |
|---|---|---|
| 1.0 | **109** | 103 fetchable `1`-token rows confirmed at 1.0, + 6 forbidden left at 1.0 |
| 0.6 | **73** | 68 + 5 |
| 0.3 | **15** | |
| 0.5 | **3** | |
| | **200** | |

The prior is the local `enriched` pass's distribution over 88 NAIP rows —
0.3 ×9, 0.5 ×1, 0.6 ×30, 1.0 ×48 — which establishes that all four values
occur in this dataset and that ~45% of enriched NAIP rows legitimately stay at
1.0. The predicted 109/200 ≈ 55% staying at 1.0 is the same shape.

**This is the prediction most likely to be wrong in a small way**, because it
assumes PC's `gsd` equals the filename token on every one of the 194 fetchable
rows. A handful of exceptions would be a finding about NAIP metadata, not
about the pass.

### P6 — landsat rewrites: 0

All 618 landsat rows store `resolution_m = 30`, and `landsat-c2-l2` is the
TM/ETM+/OLI product at 30 m throughout (MSS lives in `landsat-c2-l1`, which
this table does not reference). `normalize_resolution_m(30)` is `30.0`, equal
to stored, so nothing is written. **A landsat rewrite is a reported finding,
not a routine outcome** — the script emits one line per occurrence.

### P7 — sentinel2 rewrites: 0, and 213 rows in the "no `gsd`" bucket

Sentinel-2 L2A items on PC carry `gsd` per *asset*, not at item level:
`properties.gsd` is absent. `normalize_resolution_m(None)` returns `None`, and
the pass never writes `None` over a stored value, so all 213 keep 10.0 and all
213 land in the report's "items carrying no `gsd`" table.

Measured directly while designing the script (the §0.2 disclosure), on
`S2A_MSIL2A_20150909T183316_R127_T11SPV_20210412T073852` — a row that **is**
in this queue — which returned 200 with `properties.gsd` absent. The other two
probes were `LC08_L2SP_013030_20130930_02_T1` (`gsd` 30, in the queue) and
`ca_m_3611633_se_11_.6_20160704_20161004` (`gsd` 0.6, in the queue). So three
of the 1,031 rows have already been shown to resolve; P1 forecasts the other
1,028.

### P8 — bboxes filled: 0

No queue row has a NULL `bbox` (§1). Predicting zero here is predicting that
the pass does not churn a column no finding names — the guard is
`row.bbox_is_null`, and its unit test fails when the guard is removed.

### P9 — capture-date disagreements: 0

The mosaic pass's rate is the prior: **0 disagreements over 88 local and 505
production resolutions**, twice. These rows' `capture_date` came from the
pipeline reading `properties.datetime` off the same items, so agreement is
near-tautological — the interesting case would be an item whose `datetime` has
been *revised* since it was first read.

### P10 — wall time and P16 — requests

One GET per row, no search, no retries: **1,031 requests**. Paced at the
default `--min-interval-s 0.2` — 5 dispatches/second, globally, regardless of
concurrency 6 — the floor is `1031 × 0.2 = 206 s = 3 min 26 s`. Response
latency overlaps the pacing at concurrency 6, so the pace dominates. Predicted
**3.5–5 minutes**.

**Why 0.2 s is kept rather than lowered for a queue 2× the mosaic pass's.**
The throttle NORM-10 measured is a function of *rate*, not of total count:
~29 req/s provoked it, 0.5 req/s did not, and 5 req/s has now completed two
full 505-row production runs and the geometry audit's 1,239 fetches without a
single 403 on a paced request. Halving the interval would halve a 3.5-minute
local run to under 2 minutes and halve the margin under a throttle whose only
observed cost is a stopped production run. **For production the same default
gives ~5,400 fetchable rows ≈ 18 minutes** (6,156 snapshot rows minus a topo
population this session cannot measure), which is well inside what a detached
run handles. Twenty minutes of margin is worth more than eighteen minutes of
saved wall clock.

### P11 — non-Polygon geometry: 0

`scenes.footprint` is `geometry(POLYGON,4326)`. NAIP tiles, Landsat scenes and
Sentinel-2 granules over CONUS are single Polygons; a MultiPolygon would need
an antimeridian crossing or a split granule. A complaint leaves the footprint
NULL and **keeps that row in the queue**, so a nonzero P11 also shows up as
P14 being larger than 6.

### P12 — errors 0, exit code 0

`error` means a transport failure or an exhausted retry budget, not a 404 or a
403. The exit code is 0 unless `errors > 0` — the value a detached production
run's `; echo $? > /tmp/<name>.rc` would capture (STEP3-PROD-REPORT.md F3).
Any `error` outcome stops the sequence and goes in the report, the same gate
`PREDICTION-ENRICH.md` §7 set.

### P13–P15 — the kill-and-resume

Run B is killed with `SIGKILL` mid-run. Predictions:

* Every batch B **committed** stays committed — a killed client neither kills
  nor rolls back what is already durable (NORM-8's inverse).
* The queue immediately after B is `1031 − (footprints B committed)`, and the
  in-flight batch's rows are **all still in it**: a batch commits whole or not
  at all.
* Run C fetches **exactly** the queue it re-derives, so the total rows fetched
  across B and C exceeds 1,031 by at most one batch (**≤ 200**, P15), and **no
  row is written twice** — a written row has a footprint and is gone from the
  queue.
* After C: **1,025 footprints** across the two runs (P13) and a queue of
  **6** (P14) — the 403 rows, which stay in the queue by design because they
  are unhealed, not because the pass forgot them.
* A fourth dry run over the finished queue issues **0 requests**.

## §4 — What is not predicted, on purpose

* **`provenance` values do not change.** Not a prediction so much as a design
  invariant: the script has no statement that writes `provenance`. The queue
  after the run is still expressible as `provenance = 'snapshot' AND footprint
  IS NULL AND source <> 'usgs_topo'`, which is the property NORM-7's row
  depends on.
* **`parcel_scenes` is untouched.** This pass has no merge branch — item ids
  never change, so `UNIQUE (collection, item_id)` cannot be violated and no
  reference needs repointing.
* **Nothing about production.** Production's queue size, its topo count, its
  403 population and its 404 population are all unmeasured by this session.
  The production run is a separate session with its own prediction.

## §5 — Gates

1. Any `error` outcome → stop, report, do not re-run blindly.
2. More than 10 404s, or any 404 outside `sentinel-2-l2a` → stop and report
   (§P4).
3. A 403 on an item not in Appendix C's six → not a stop, but a STATUS.md line.
4. The dry run's totals and the execute runs' totals must agree row for row
   where the queues overlap. They share one `plan_row`, so a disagreement is a
   defect in the pass, not in the data.

---

## Observed

*(Appended after the runs. Everything above this line is as committed in
`93ff05c` and has not been edited.)*

Three runs, 2026-08-29, local database only, network to the Planetary
Computer only.

| Run | What | Started | Ended | Rows |
|---|---|---|---|---|
| A | dry run, whole queue | 07:11:33Z | 07:15:07Z (214 s) | 1,031 fetched, 0 written |
| B | `--execute`, **SIGKILLed** | 07:15:34Z | killed 07:17:50Z | 600 committed |
| C | `--execute`, resumed | 07:18:14Z | 07:19:44Z (90 s) | 431 committed |
| D | dry run, finished queue | 07:20Z | — | 0 fetched |

Captures committed unedited: `snapshot-enrich-local-dryrun.md` (A),
`snapshot-enrich-local-killed.md` (B, the partial report the kill left
behind), `snapshot-enrich-local-resumed.md` (C).

### Scorecard

**14 of 16 confirmed. 1 falsified (P3). 1 deviation, wholly downstream of that
falsification (P5). No unpredicted class.**

| # | Predicted | Observed | Verdict |
|---|---|---|---|
| P1 | 1,031 fetched | **1,031** | confirmed |
| P2 | 1,025 matched | **1,031** | deviation — see P3 |
| P3 | 6 × item GET 403 | **0** | **FALSIFIED** |
| P4 | 0 × item GET 404 | **0** | confirmed |
| P5 | 91 NAIP rewrites | **93** | deviation — see below |
| P6 | 0 landsat rewrites | **0** | confirmed |
| P7 | 0 sentinel2 rewrites, 213 with no `gsd` | **0**, **213** | confirmed |
| P8 | 0 bboxes filled | **0** | confirmed |
| P9 | 0 capture-date disagreements | **0** | confirmed |
| P10 | 3.5–5 min, run A | **3 min 34 s** (214 s) | confirmed |
| P11 | 0 non-Polygon anomalies | **0** | confirmed |
| P12 | 0 errors, exit 0 | **0 errors**, `rc=0` **read from the file** | confirmed |
| P13 | 1,025 footprints across B+C | **1,031** | deviation — see P3 |
| P14 | queue 6 after C | **0** | deviation — see P3 |
| P15 | ≤200 refetched, 0 written twice | **0 recorded refetches**, **0 written twice** | confirmed |
| P16 | 1,031 requests, run A | **1,031** | confirmed |

### P3 — falsified: the six forbidden NAIP items are no longer forbidden

**All six Appendix C items returned HTTP 200.** The dry run resolved 1,031 of
1,031 with zero 403s, and three of the six were then probed directly with
`curl` against `…/collections/naip/items/{id}` — `ut_m_4011118_sw_12_1_…`,
`va_m_3807708_se_18_1_20120511_…`, `ut_m_4011125_sw_12_060_20211105` — each
**200**.

This is the good direction to be wrong in, and it is a fact about the
Planetary Computer, not about this pass: **Appendix C's "unassessable, HTTP
403" class, open since 2026-08-12, is empty as of 2026-08-29.** Those 17 rows
across 6 items were counted as unassessed rather than as passes; they are now
assessable, and all six carry a real footprint in `scenes`.

The prediction was explicit that this number was a forecast that a 2026-08-12
measurement still held, not a reading of today's catalogue (§0). It did not
hold. **What this does not license:** the geometry-audit conclusions those 17
rows were excluded from were never re-run, and nothing here says whether those
six items' footprints actually cover the parcels that serve them. That is a
separate question and it is now answerable by a query over `scenes` instead of
a refetch — which is exactly ADR rule 4's promise arriving.

**P2, P13 and P14 are the same falsification counted three more times**, not
independent misses: 1,025 + 6 = 1,031 matched, 1,031 footprints, queue 0.

### P5 — 93 rewrites, not 91, and the mechanism it tested held perfectly

The predicted mechanism was that PC's `gsd` equals the resolution token in
NAIP's filename convention. **It held on 200 of 200 rows.** Observed NAIP
distribution after the heal:

| `resolution_m` | predicted | observed | token count |
|---|---|---|---|
| 1.0 | 109 | **107** | `1` → 107 |
| 0.6 | 73 | **75** | `060` 70 + `.6` 5 = 75 |
| 0.3 | 15 | **15** | `030` → 15 |
| 0.5 | 3 | **3** | `.5` → 3 |
| total | 200 | **200** | 200 |

Every bucket equals its token count exactly. The 2-row deviation is precisely
the two Appendix C items whose token is `060` — predicted to stay at 1.0
because they were predicted to 403, and instead fetched and corrected to 0.6.
The other four forbidden items carry token `1` and were going to land on 1.0
either way, which is why the deviation is 2 and not 6.

So P5's numeric miss is entirely inherited from P3, and the substantive claim
it was testing — *the filename token is the resolution, on every row* — is
confirmed 200/200.

### P12 — the exit code was read, not inferred

`STEP3-PROD-REPORT.md` F3 recorded that `setsid nohup … &` discards `$?` and
prescribed appending `; echo $? > /tmp/<name>.rc`. Run C was launched with
that recipe and `/tmp/snapshot-enrich-C.rc` contains `0`. **PP14's successor
is scored confirmed-by-reading rather than unobserved**, which is the first
time this arc has had an actual exit status off a detached run.

Run B has no `.rc` file, and the reason is worth stating rather than glossing:
the deliberate kill was a `SIGKILL` of every process whose `cmdline` matched
the script — including the wrapping `sh -c` that would have written the file.
That is a harder kill than the client timeout the recipe defends against, and
it does not weaken C's reading.

### P13–P15 — resume, exercised for real

Run B was killed at 07:17:50Z with `SIGKILL`, after three batches had
committed and while batch 4 was in flight.

| Check | Value |
|---|---|
| Rows committed by B | **600** (3 × 200, all `landsat-c2-l2`) |
| Queue immediately after the kill | **431** = 1,031 − 600 |
| — composition | 18 landsat + 200 naip + 213 sentinel2 |
| B's report on disk after the kill | present, **"Incomplete"**, totals 600 |
| Rows C's re-derived queue held | **431** |
| Rows C fetched | **431** |
| Rows fetched twice and *written* twice | **0** |
| Queue after C | **0** |

The in-flight batch 4 was rolled back whole — 600 healed, not 600-and-some —
which is the batching decision doing its job. B's partial batch did dispatch
some requests before the kill that its report never counted (the counter is
rendered at batch boundaries), so the true B+C request total exceeds 1,031 by
an unrecorded amount bounded by one batch. That is P15's `≤ 200` satisfied in
shape; the exact number is not observable and is not claimed.

**Run D**, a dry run over the finished queue, fetched **0 rows and issued 0
STAC requests.** Idempotence is a reading, not an argument.

### Gates (§5)

| Gate | Result |
|---|---|
| Any `error` outcome → stop | **0 errors**, no stop |
| >10 404s or a 404 outside `sentinel-2-l2a` → stop | **0 404s** |
| A 403 outside Appendix C's six → STATUS.md line | **0 403s at all** — the inverse happened, and gets its own line |
| Dry run and execute totals must agree | **They do**: A's 93 rewrites / 1,031 footprints / 0 bboxes equal B+C's 93 / 1,031 / 0, and A's per-source tables are identical to C's |

### Final state of the local database

| | before | after |
|---|---|---|
| `snapshot` rows with NULL `footprint`, non-topo | 1,031 | **0** |
| — geometry type | — | **1,031 × `ST_Polygon`** |
| — footprints equal to their own `bbox` | — | **0** (69 sentinel-2 outlines have >5 vertices) |
| `snapshot` naip at `resolution_m = 1.0` | 200 | **107** |
| `snapshot` usgs_topo rows | 143, no footprint | **143, no footprint** (excluded by design) |
| `provenance` counts | 1,174 / 88 / 80 | **1,174 / 88 / 80** |
| `parcel_scenes` | 3,082, 0 dangling | **3,082, 0 dangling** |

**NORM-18's named witness is closed.** `md_m_3807708_se_18_030_20230901_
20231018` — the item STEP3-REPORT F1 measured serving `1m res` to four
parcels — now carries `resolution_m = 0.3`, and **all four parcels serve
0.3**. Across the whole local database, **139 served NAIP rows** moved off the
1.0 chip to a true value (29 at 0.3, 4 at 0.5, 106 at 0.6) and 177 stay at 1.0
because 1.0 is what their items say.
