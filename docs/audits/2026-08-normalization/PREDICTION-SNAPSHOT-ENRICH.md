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

---

# Prediction — the same heal, against PRODUCTION

Written 2026-08-29 between 07:44Z and the dry run's completion. **Everything
above this line is as committed in `93ff05c` and `c16f570` and has not been
edited**, including the local Observed half.

## §P0 — Disclosure: what is blind, and the one thing that is unusual here

The prompt orders the dry run *before* this prediction. **This section was
nonetheless written while the dry run was still in flight and before a single
byte of its output was read** — `/tmp/snapshot-enrich-prod-dryrun.log` and
`.md` were untouched on the machine when this was committed. That is stricter
than the prompt requires and it is the only way the 403 and 404 forecasts
below mean anything: read after the dry run they would be transcription, not
prediction.

**Blind.** Every outcome quantity: the 403 count, the 404 count, footprints
written, NAIP rewrites, landsat/sentinel-2 rewrites, capture-date
disagreements, geometry anomalies, wall time, exit code, and what the `h`
resolution token turns out to mean.

**Not blind, and disclosed as such** — the item-2 pre-run measurement, read
07:42:23Z under `default_transaction_read_only = on` (proved: an
`UPDATE scenes SET resolution_m = resolution_m WHERE false` raised
`ReadOnlySqlTransaction`):

1. **The queue is 5,387** and its per-source split, the topo exclusion (769),
   the queue's bbox-NULL count (0) and its NAIP resolution distribution
   (1,102 × 1.0) are `SELECT count(*)` readings, not forecasts. They are
   recorded so the arithmetic can be checked, not scored.
2. **The NAIP filename-token histogram over the queue** is a reading. What
   each token *means* to the Planetary Computer is the forecast (P5), and one
   token — `h` — has no local precedent at all.
3. **No Planetary Computer request was made by this session before the dry run
   launched.** Unlike the local prediction (§0.2, three design-time probes),
   nothing here rests on a production-era fetch. The three ids the local
   session probed are not in this queue's evidence chain.

**No document is cited as a floor for anything.** NORM-23 is binding and it is
re-derived below rather than inherited.

## §P1 — The queue, with the arithmetic

`scenes` in production, read 2026-08-29T07:42:23Z. Deltas from step 3's t0
(`2026-08-29T06:41:47.270470Z`) first, because the prompt gates on them:

| | t0 (`STEP3-PROD-REPORT.md` §2, §7) | 07:42:23Z | delta |
|---|---|---|---|
| `scenes` | 6,663 | **6,663** | **0** |
| — by provenance | 6,156 / 505 / 2 | **6,156 / 505 / 2** | **0** |
| `parcel_scenes` | 12,884 | **12,884** | **0** |
| `imagery_snapshots` | 12,884 | **12,884** | **0** |

**There is no traffic to reconcile, because there is none at all.** The
strongest form of that statement is the timestamps rather than the counts:
`max(scenes.fetched_at)` and `max(parcel_scenes.selected_at)` are both
`2026-08-29 04:41:26.056028+00`, **two hours before t0**, and `count(*)` of
rows stamped at or after t0 is **0** in both tables. `selected_by` is
non-NULL on 7 `parcel_scenes` rows, all stamped
`efa4c63a07455c5fc776c431d345284fd4082ddd` — the step-2 sweep's deploy sha,
not this session's. No selection has run since the cutover.

The queue, by the script's own definition
(`enrich_snapshot_scenes.py:165-181`, `provenance = 'snapshot' AND footprint
IS NULL AND source <> 'usgs_topo'`):

```
provenance = 'snapshot'                       6,156
  − source = 'usgs_topo'                      −  769   (TNM-sourced, no PC item)
  − footprint already non-NULL                −    0   (there are none)
  = queue                                     5,387
```

| source | collection | queue rows | bbox NULL | capture_date NULL |
|---|---|---|---|---|
| landsat | `landsat-c2-l2` | **3,174** | 0 | 0 |
| naip | `naip` | **1,102** | 0 | 0 |
| sentinel2 | `sentinel-2-l2a` | **1,111** | 0 | 0 |
| | | **5,387** | **0** | **0** |

3,174 + 1,102 + 1,111 = 5,387, and `count(DISTINCT (collection, item_id))`
over the queue is also **5,387** — one row per item, no duplicate pair.
**Excluded: 769** topo rows, every one with a NULL footprint. The prompt's
"~5,387 (6,156 minus ~769 topo)" is exact in both terms.

**Every queue row already has a `bbox`** (0 NULL), so P8's population is empty
here as it was locally. Capture-date span: landsat **1984-03-12 → 2026-08-17**,
naip **2010-04-22 → 2023-11-13**, sentinel2 **2015-08-21 → 2026-08-26**. This
queue is 5.2× the local one and reaches back four decades further.

Ordering is `ORDER BY collection, item_id`, so: `landsat-c2-l2` (3,174) →
`naip` (1,102) → `sentinel-2-l2a` (1,111). At batch size 200 that is
**27 batches** (26 full + one of 187).

## §P2 — The 403 count, predicted from nothing

**Predicted: 0.** Not "at least zero", not "the Appendix C floor" — zero, as a
central estimate, and the reasoning is built here rather than cited.

The entire evidentiary basis for a per-item 403 in this repo is one
measurement: `2026-08-geometry-audit/FINDINGS.md` Appendix C, 6 NAIP items,
2026-08-12. **That measurement was re-taken on 2026-08-29 and returned 200 on
all six** (NORM-23), by two independent methods — a 1,031-row dry run that met
zero 403s, and three direct `curl`s. A single observation that has since been
contradicted by a later observation of the same objects is not a floor; it is
a superseded reading. **Every document in this repo that quotes "the six
forbidden items" as a known remainder is quoting a class of size zero, and
none of them is load-bearing here.**

Against that, the positive evidence for zero:

* **No item-endpoint 403 has ever been observed at all**, on any run:
  1,515 production resolutions (two enrichment runs), 88 + 1,031 local ones,
  and the geometry audit's 1,239 fetches. `enrich_synthesized_scenes.py`'s
  item-403 fall-through branch has **never fired live** (NORM-7).
* **NORM-10's split is the mechanism.** The 403 this arc has actually met is a
  throttle on `/search`, at ~29 req/s. This pass makes no `/search` call at
  all — one GET per row against `/collections/{c}/items/{id}` — and is paced
  at 5 dispatches/second, a rate that has now completed 505 + 505 + 1,031 rows
  without one.
* Only **4** of Appendix C's six items are even in this queue
  (`va_m_3807708_se_18_060_20181019_20190212`,
  `…_18_1_20120511_20120709`, `…_18_1_20140927_20141126`,
  `…_18_1_20160718_20160928`; the two `ut_m_4011…` items are not in
  production). So even the dead floor, if resurrected, would be 4 rather
  than 6 — recorded to show the floor was checked against this queue and not
  transplanted.

**Any nonzero 403 count is a finding**, enumerated per item id in the report
with its collection and capture date, and — if the items are NAIP —
explicitly compared against Appendix C's list rather than assumed to be it.

## §P3 — The 404 count, and the threshold that separates a tail from a stop

**Predicted: 0.** **Stop-and-think threshold: more than 10 in total, OR any
404 outside `sentinel-2-l2a`.**

The gate has never met real data — 0 of 1,031 locally — and this is its first
real test, against ids spanning the pipeline's whole history and a catalogue
that demonstrably moves in both directions (NORM-23 is items *returning*; the
same mobility permits items *leaving*).

**What a 404 means here, precisely:** an id the pipeline once served that PC no
longer resolves. These ids were not parsed out of tile URLs (NORM-4) — they
came from PC's own search results by way of `imagery_snapshots.stac_item_id`.
So a 404 is a fact about the catalogue, never a fact about the row, and there
is no fuzzy-match fallback to reach for and none will be added. **The row is
left exactly as it is** and stays in the queue.

**Grounds for zero:** 2,020 catalogued production resolutions to date without
one; NAIP and Landsat Collection-2 item ids are stable identifiers.

**The named mechanism if it misses, stated in advance:** Sentinel-2 L2A ids
embed a processing-baseline timestamp, and PC has reprocessed parts of that
archive; a reprocessed granule is republished under a new id and the old one
can stop resolving. **1,111 of the 5,387 rows are sentinel-2, spanning
2015–2026 at 82–98 rows per year** — 82 rows from 2015 are the oldest and the
most exposed. A miss should therefore be *concentrated in `sentinel-2-l2a` and
skewed to the early years*. If instead 404s appear in `landsat-c2-l2` or
`naip`, the mechanism is something else and the run stops regardless of count.

**Why the threshold is 10 and not a fraction.** 5.2× the local queue does not
buy 5.2× the tolerance: the question the threshold asks is not "is this rate
acceptable" but "does the catalogue still contain what we served", and a
double-digit answer to that is a different investigation from a single-digit
one. **1–10 404s, all in `sentinel-2-l2a`: a tail** — each enumerated by id,
year and parcel count as a per-row finding, run continues. **11 or more, or
one anywhere else: stop**, report, do not work around.

## §P4 — Predictions

| # | Quantity | Predicted |
|---|---|---|
| PP1 | Rows fetched, dry run | **5,387** |
| PP2 | STAC requests, dry run | **5,387** |
| PP3 | Item GET **403** | **0** |
| PP4 | Item GET **404** | **0** |
| PP5 | Matched (200) | **5,387** |
| PP6 | Footprints written by `--execute` | **5,387** |
| PP7 | NAIP `resolution_m` rewritten | **527** |
| PP8 | landsat `resolution_m` rewritten | **0** |
| PP9 | sentinel2 rewritten / in the "no `gsd`" bucket | **0** / **1,111** |
| PP10 | `bbox` filled | **0** |
| PP11 | `bbox` values churned (existing bboxes moved) | **0** |
| PP12 | Capture-date disagreements | **0** |
| PP13 | Non-Polygon geometry anomalies | **0** |
| PP14 | Footprint geometry type, all written rows | **5,387 × `ST_Polygon`** |
| PP15 | Footprints `ST_Equals` their own `bbox` | **0** |
| PP16 | Errors / exit code, both runs | **0** / **0**, read from `.rc` |
| PP17 | Queue after `--execute` | **0** |
| PP18 | Batches committed | **27** |
| PP19 | Wall time, each run | **18–23 min** |
| PP20 | Served check: a NAIP parcel reads the new value | **yes** |

### PP7 and the `h` token — the prediction most likely to be wrong

The queue's 1,102 NAIP rows all store **1.0**. Their filename resolution
tokens:

| token | rows | resolution it implies | basis |
|---|---|---|---|
| `1` | 575 | 1.0 | confirmed 107/107 locally |
| `060` | 395 | 0.6 | confirmed 70/70 locally |
| `030` | 77 | 0.3 | confirmed 15/15 locally |
| `.6` | 31 | 0.6 | confirmed 5/5 locally |
| `.5` | 11 | 0.5 | confirmed 3/3 locally |
| **`h`** | **13** | **0.5 — forecast, no local precedent** | see below |
| | **1,102** | | |

Five of the six tokens were confirmed by the local run at 200 of 200 rows —
the filename token *is* the item's `gsd`, measured, not assumed. **`h` did not
occur in the local queue at all.** All 13 are 2016 NAIP over IN, MI, MO, NH and
VT, in the older single-date filename form
(`in_m_3808620_nw_16_h_20160618`, `nh_m_4207107_sw_19_h_20160706`, …) — 6
underscores rather than 7, of which the queue holds 295 rows overall.

**`h` is read as "half metre" — 0.5.** It is the only reading that makes the
token a resolution field at all, which is what position 6 is in every other
row. **This is a genuine forecast about a 13-row class nobody in this arc has
measured**, and the alternatives are named so a miss is legible rather than
retrofitted: `1.0` (the token means something other than resolution and these
are ordinary 1 m tiles) or `0.6`. **A miss here moves at most 13 rows between
buckets and falsifies nothing else** — and whatever PC's `gsd` says is what
lands, because the item wins wherever it speaks.

Predicted rewrites: every row whose token is not `1` —

```
395 (060) + 77 (030) + 31 (.6) + 11 (.5) + 13 (h) = 527
```

and the predicted NAIP `snapshot` distribution afterwards:

| `resolution_m` | rows | from |
|---|---|---|
| 1.0 | **575** | token `1`, unchanged |
| 0.6 | **426** | 395 + 31 |
| 0.5 | **24** | 11 + 13 (`h`) |
| 0.3 | **77** | |
| | **1,102** | |

**This is NORM-13's `scenes` arm, before and after, in one table:** 1,102 rows
at 1.0 → 575 at 1.0 and **527 moved onto the value their item states**. The
`imagery_snapshots` arm — 1,305 NAIP rows, all 1.0 — is deliberately not
healed and will still be 1,305 × 1.0 afterwards, so the two tables will
**disagree** on 527 items with `scenes` holding the true value and being the
one that serves. That disagreement is the unhealed arm made visible, and it is
predicted, not a defect.

### PP8, PP9 — landsat and sentinel-2

3,174 landsat rows all store 30.0 and `landsat-c2-l2` is 30 m throughout;
`normalize_resolution_m(30)` is `30.0`, equal to stored, nothing written.
**A landsat rewrite is a reported finding, not a routine outcome** — and with
3,174 rows spanning 1984–2026 this is the first time the claim meets the
Thematic Mapper era at scale.

Sentinel-2 L2A items carry no item-level `properties.gsd` (measured
2026-08-29 on a queue member, local §0.2), so `normalize_resolution_m(None)`
is `None`, `None` is never written over a stored value, and all 1,111 rows
keep 10.0 and land in the "no `gsd`" table. **PP9's second number is the one
that would catch a change upstream:** if fewer than 1,111 rows land in that
bucket, PC has started publishing item-level `gsd` for L2A and that is a
finding.

### PP11, PP14, PP15 — the invariants, promoted to predicted quantities

* **`bbox` churn 0.** The guard is `row.bbox_is_null`; the queue has 0 NULL
  bboxes, so the branch has an empty population and **no existing bbox may
  move**. Verified after the run by counting rows whose `bbox` differs from
  the pre-run reading, not by re-reading the guard.
* **All 5,387 footprints `ST_Polygon`.** `scenes.footprint` is
  `geometry(POLYGON,4326)`; a non-Polygon is reported and leaves the footprint
  NULL, so a nonzero PP13 also shows up as PP17 > 0.
* **Zero footprints `ST_Equals` their own `bbox`.** Locally 0 of 1,031 — the
  geometry audit's whole distinction between an outline and an envelope,
  measured on the result. Production's 507 existing footprints already read 0.
  **This is the invariant the whole pass exists to establish**, and predicting
  it as a quantity rather than asserting it from the code is the point.

### PP19 — wall time, from the local run's pacing

One GET per row at `--min-interval-s 0.2` — 5 dispatches/second globally,
regardless of concurrency 6 — so the floor is `5387 × 0.2 = 1,077 s =
17 min 57 s`. The local run's measured ratio to its own floor was
`214 / 206 = 1.039`, response latency overlapping the pacing at concurrency 6.
Scaled: `1,077 × 1.039 ≈ 1,119 s ≈ 18 min 39 s`. **Predicted 18–23 min per
run**, and **both runs fetch** — `--execute` is the write flag only
(`enrich_snapshot_scenes.py:587`, and the docstring at `:85`: "both forms do
fetch") — so the dry run and the execute together are **~37–46 minutes** of
wall clock, plus any resumption.

### PP20 — the served check

The NORM-18 fix becomes observable end to end in production for the first
time. At least one parcel whose NAIP primary moves off 1.0 must read the new
value through the listing path, not just in the table — the `1m res` chip at
`frontend/src/components/MapView.tsx:298-301` is what a user sees. Predicting
**yes** is predicting that the cutover reads `scenes` and nothing caches the
old value.

## §P5 — Gates

1. Any `error` outcome → stop, report, do not re-run blindly.
2. More than 10 404s, or any 404 outside `sentinel-2-l2a` → stop and report
   (§P3). 1–10 within `sentinel-2-l2a` → enumerate each and continue.
3. Any 403 → not a stop, but every id enumerated and a STATUS.md line
   (§P2). NORM-23 means there is no expected population to absorb it into.
4. Any landsat or sentinel-2 `resolution_m` rewrite → reported per row.
5. The dry run's totals and the execute's totals must agree row for row where
   the queues overlap. They share one `plan_row`, so a disagreement is a
   defect in the pass, not in the data.
6. Any existing `bbox` observed to have moved → stop and report. Nothing in
   this pass may touch a non-NULL bbox.

---

## Observed — production, DRY RUN ONLY

*(Appended after the dry run. Everything above this line is as committed in
`93ff05c`, `c16f570` and `82cbda9` and has not been edited.)*

**Partial by necessity: `--execute` did not run.** The dry run exited 1 and
the prompt's item-3 gate is "errors beyond plan: STOP"
(`SNAPSHOT-ENRICH-PROD-REPORT.md` F2). The quantities below are the ones the
dry run settles; **PP6, PP11, PP14, PP15, PP17, PP18, PP20 are unscored** and
stay that way until the write runs.

One run, 2026-08-29, machine `825d69b7e46618`, 07:44:19Z → 08:02:19Z (1,080 s).
Captures committed unedited: `snapshot-enrich-prod-dryrun.md`,
`snapshot-enrich-prod-dryrun.txt`.

### Scorecard — 12 scoreable, 11 confirmed, 1 falsified

| # | Predicted | Observed | Verdict |
|---|---|---|---|
| PP1 | 5,387 fetched | **5,387** | confirmed |
| PP2 | 5,387 requests | **5,387** | confirmed |
| PP3 | 0 × 403 | **0** | **confirmed** |
| PP4 | 0 × 404 | **0** | **confirmed** |
| PP5 | 5,387 matched | **5,387** | confirmed |
| PP7 | 527 NAIP rewrites | **527** | confirmed in total, **falsified in composition** — see below |
| PP8 | 0 landsat rewrites | **0** over 3,174 rows | confirmed |
| PP9 | 0 sentinel2 rewrites / 1,111 with no `gsd` | **0** / **1,111** | confirmed |
| PP10 | 0 bboxes filled | **0** | confirmed |
| PP12 | 0 capture-date disagreements | **0** over 5,387 | confirmed |
| PP13 | 0 non-Polygon anomalies | **0** | confirmed |
| PP16 | 0 errors, exit 0 | **0 errors**, **exit 1** | **errors confirmed; exit code FALSIFIED** |
| PP19 | 18–23 min | **18 min 0 s** (1,080 s) | confirmed |
| PP6, PP11, PP14, PP15, PP17, PP18, PP20 | — | **unscored** | `--execute` did not run |

### PP3 and PP4 — the two that were predicted from nothing, both zero

**403: zero over 5,387 catalogued ids.** NORM-23 is confirmed in production,
not merely locally: the class Appendix C opened on 2026-08-12 is empty against
a queue 5.2× the local one, including all four of its items that are present
here. The prediction was derived rather than inherited (§P2) and it was right;
had it been wrong, the enumeration was ready. **`enrich_synthesized_scenes.py`'s
item-403 fall-through branch has still never fired live**, now across
1,515 + 88 + 1,031 + 5,387 resolutions.

**404: zero.** **The gate has now met real data and found nothing.** 5,387
ids spanning 1984–2026, against a catalogue that demonstrably moves. The named
mechanism — Sentinel-2 L2A reprocessing republishing granules under new ids —
**did not occur on a single one of the 1,111 sentinel-2 rows**, 82 of them
from 2015. The stop-and-think threshold (>10, or any outside
`sentinel-2-l2a`) was never approached, and no id the pipeline once served has
left the catalogue.

### PP7 — 527 exactly, and the `h` token is 0.6, not 0.5

**The total is confirmed to the row. The 13-row sub-forecast is falsified.**

| `resolution_m` | predicted | planned by the dry run |
|---|---|---|
| 1.0 | 575 | **575** |
| 0.6 | 426 | **439** |
| 0.5 | 24 | **11** |
| 0.3 | 77 | **77** |
| total | 1,102 | **1,102** |

Rewrites planned: `1.0 → 0.3` **77**, `1.0 → 0.5` **11**, `1.0 → 0.6` **439**.
575 + 527 = 1,102, and 527 is the predicted number.

**`h` means 0.6, not "half metre".** All 13 rows land in the 0.6 bucket:
439 − (395 `060` + 31 `.6`) = 13, and 0.5's bucket is exactly the 11 `.5`
rows with nothing added. The reading in §PP7 — that `h` is the only token
whose plain meaning is a resolution, therefore half a metre — was wrong about
the meaning while right about the position: **it is a resolution field, and
its value is 0.6 m**, the 2016 NAIP product. The alternatives were named in
advance (1.0 or 0.6) and the outcome is one of them.

**The substantive claim PP7 was testing is confirmed at 1,102 of 1,102:** the
filename token *is* the item's `gsd`, for six distinct token spellings across
two filename conventions. The miss moved 13 rows between two buckets and
changed no total, which is why PP7's headline number survived a wrong
sub-forecast — and the sub-forecast was written down separately precisely so
this would be legible rather than absorbed.

### PP16 — errors 0, exit code 1, and the two halves disagree

**`errors=0` is confirmed. `exit 0` is falsified, and not by a row.** The run
completed batch 27, rendered its report, emitted its structlog summary
(`errors=0 footprints=5387 written=5387`) and *then* died in
`Session.__exit__` on a reaped connection —
`sqlalchemy.exc.OperationalError: SSL connection has been closed unexpectedly`
— so `sys.exit(1 if out.errors else 0)` at `enrich_snapshot_scenes.py:622` was
never reached and the process exited 1 from an unhandled traceback.

**This is the first exit status this arc has read from a production run, and
it is false.** PP16 predicted the two halves would agree; they do not. The
report says the run succeeded, the `.rc` says it failed, both are this run's
own output, and only the third artifact — the stdout capture — explains which
is right. Full mechanism and consequences: `SNAPSHOT-ENRICH-PROD-REPORT.md`
F2.

### Gates (§P5)

| Gate | Result |
|---|---|
| 1. Any `error` outcome → stop | **0 errors.** Not tripped — the stop came from the *process* exit, not from a row |
| 2. >10 404s or any outside `sentinel-2-l2a` → stop | **0 404s.** Never approached |
| 3. Any 403 → enumerate + STATUS.md line | **0 403s.** NORM-23 confirmed in production instead |
| 4. Any landsat/sentinel-2 rewrite → report per row | **0 of 3,174 landsat, 0 of 1,111 sentinel-2** |
| 5. Dry-run and execute totals must agree | **unscored** — no execute |
| 6. Any existing `bbox` moved → stop | **0 bboxes filled, 0 rows written at all**; the whole table re-read identical at 08:04:57Z |

---

# Prediction — the PRODUCTION `--execute`, written before the write

*(Appended 2026-08-29 after the third production dry run and **before**
`--execute` was invoked. Everything above this line — both local halves and
the production prediction and its dry-run Observed half — is as committed in
`93ff05c`, `c16f570`, `82cbda9` and `261f6af` and has not been edited.)*

## §E0 — Disclosure: what is blind here, and what is emphatically not

This is the fourth attempt at this write and the first prediction written with
three production dry runs already read. **Almost nothing about the plan is
blind, and pretending otherwise would be the dishonest move.** The disclosure
is therefore the substance of this section.

**Not blind — read, not forecast:**

1. **The queue is 5,387**, its per-source split, the 769 topo exclusion, the
   0 bbox-NULLs and the 1,102 × 1.0 NAIP distribution. Read read-only at
   **2026-08-29T18:55:17Z** (`snapshot-enrich-prod-prerun-3.json`), identical
   to the 17:45:53Z and 07:42:23Z readings and to t0.
2. **The whole dry-run plan**: 5,387 matched, 0 × 403, 0 × 404, 0 errors, 527
   NAIP rewrites split 77 / 11 / 439, 0 capture-date disagreements, 27
   batches. Three dry runs have now produced this same plan, the third at
   18:55:49Z → 19:13:48Z in 1,079 s.
3. **The `h` token means 0.6.** Falsified as 0.5 in the dry-run half and not
   re-predicted here.
4. **The third dry run's exit path.** `.rc = 0`, with the reaped connection
   caught and logged at 19:13:48.483Z. Read before this file was written, and
   discussed under EP14 as a reading rather than a forecast.
5. **The pre-write `bbox` fingerprint** over all 6,663 rows is
   `f1809593fd050be14736aaaea4b09ed5` (comma-delimited `string_agg`), taken at
   18:55:17Z and equal to the 17:45:53Z baseline.

**Genuinely blind, and this is what the prediction is actually about:**

* **Whether the plan and the write agree.** Every number above is what a
  fetch-and-compare pass *intends*. No production row has ever been written by
  this script. EP1–EP9 are predictions that the write lands what the plan said,
  and gate 5 (§P5) is the reason: the two modes share one `plan_row`, so a
  disagreement is a defect in the pass rather than a fact about the data.
* **The geometry invariants after a write** — EP10, EP11, EP12. Locally these
  held over 1,031 rows; production has never had them measured post-write.
* **The exit code.** EP14 is the number three sessions have chased.
* **The served check.** EP15 has been unscored across three sessions.
* **Whether the catalogue answers the same way twice in one hour.** The
  execute re-fetches every row; the dry run's 200s do not carry over.

## §E1 — Predictions

| # | Quantity | Predicted |
|---|---|---|
| EP1 | Rows fetched by `--execute` | **5,387** |
| EP2 | Item GET **403** / **404** | **0** / **0** |
| EP3 | Rows enriched (footprint written) | **5,387** = queue − 0 |
| EP4 | NAIP `resolution_m` rewrites | **527** (`1.0 → 0.3` 77, `→ 0.5` 11, `→ 0.6` 439) |
| EP5 | landsat `resolution_m` changes | **0** over 3,174 |
| EP6 | sentinel2 `resolution_m` changes / "no `gsd`" bucket | **0** / **1,111** |
| EP7 | Capture-date disagreements | **0** over 5,387 |
| EP8 | `bbox` filled (was NULL) | **0** — the population is empty |
| EP9 | `bbox` churn outside was-NULL | **0**, measured by fingerprint |
| EP10 | Footprint geometry type, all written rows | **5,387 × `ST_Polygon`** |
| EP11 | Footprints `ST_Equals` their own `bbox` | **0** of 5,387 |
| EP12 | Non-Polygon geometry anomalies | **0** |
| EP13 | Queue after the run / batches committed | **0** / **27** |
| EP14 | `.rc`, execute **and** the item-6 dry re-run | **0** and **0**, read from the file |
| EP15 | Served check: the named parcel reads the new value | **yes**, `1.0 → 0.5` |
| EP16 | Wall time, execute | **18–24 min** |

### EP3 — enriched = queue − 0, and why the remainder is zero rather than small

**The remainder is predicted as exactly 0, not "near zero".** The only two
mechanisms that leave a queue row unenriched are a 403 and a 404 on the item
endpoint, and both are predicted 0 by the same reasoning §P2 built from the
mechanism rather than inherited from a document:

* **403.** The item-403 fall-through branch has never fired live, now across
  1,515 + 88 + 1,031 + 5,387 + 5,387 + 5,387 resolutions. NORM-23 emptied the
  only class this repo ever recorded (Appendix C's six items, of which four are
  in this queue), and it has been confirmed in production three times. This
  pass makes no `/search` call — NORM-10's throttle is on a different endpoint
  — and paces one GET per row at 5 dispatches/second.
* **404.** Zero over three production dry runs of the same 5,387 ids, spanning
  1984–2026.

**A nonzero remainder is therefore a finding, and it is enumerated per row with
its id, collection and capture date — never absorbed into a smaller success.**
"Complete with zero" and "failed" are different states: if the run enriches
5,386 of 5,387, that is reported as 5,386 with one enumerated remainder, and
the queue after the run is reported as 1, not rounded to done.

### EP2's 404 threshold, restated because it now governs a write

Unchanged from §P3 and binding on the execute exactly as it was on the dry run:
**more than 10 in total, OR any 404 outside `sentinel-2-l2a` → STOP.** 1–10
within `sentinel-2-l2a` → each enumerated by id, year and parcel count as a
per-row finding, run continues. The named mechanism if it misses is Sentinel-2
L2A reprocessing republishing granules under new ids, concentrated in the early
years (82 rows from 2015). A 404 in `landsat-c2-l2` or `naip` means the
mechanism is something else, and the run stops regardless of count.

**One thing the execute adds that the dry runs could not test:** a 404 arriving
*mid-write* leaves the run partially applied. The row is left exactly as it is
and stays in the queue — there is no fuzzy-match fallback and none will be
added — so a stop after batch *n* leaves *n* batches committed and the queue
re-derivable. That is the resume mechanism, not a rollback.

### EP4 — the NAIP distribution after the write

| `resolution_m` | before | **predicted after** | from |
|---|---|---|---|
| 1.0 | 1,102 | **575** | token `1`, unchanged |
| 0.6 | 0 | **439** | 395 (`060`) + 31 (`.6`) + 13 (`h`) |
| 0.5 | 0 | **11** | `.5` |
| 0.3 | 0 | **77** | `030` |
| total | 1,102 | **1,102** | |

This is **NORM-13's `scenes` arm in one table**: 1,102 rows at 1.0 → 575 at 1.0
and **527 moved onto the value their own item states**. The `imagery_snapshots`
arm — 1,305 NAIP rows, all 1.0 at 18:55:17Z — is deliberately not healed and is
predicted to still be **1,305 × 1.0** afterwards. The two tables will then
**disagree on 527 items**, with `scenes` holding the true value and being the
one that serves. **That disagreement is predicted, not a defect**; step 4 drops
`imagery_snapshots`.

### EP5, EP6 — a landsat or sentinel-2 change is a finding, not an outcome

3,174 landsat rows store 30.0 and `landsat-c2-l2` is 30 m throughout, so
`normalize_resolution_m(30)` equals stored and nothing is written. Sentinel-2
L2A items carry no item-level `properties.gsd`, so `normalize_resolution_m(None)`
is `None` and `None` is never written over a stored value — all 1,111 rows keep
10.0 and land in the "no `gsd`" table. **EP6's second number is the one that
catches an upstream change:** fewer than 1,111 in that bucket means PC has
started publishing item-level `gsd` for L2A, and that is a finding whether or
not any value changes.

### EP9 — bbox churn, measured rather than argued

The write guard is `row.bbox_is_null` and the queue has **0** NULL bboxes, so
the branch has an empty population and **no existing bbox may move**. This is
scored by re-taking the fingerprint after the run and comparing to
`f1809593fd050be14736aaaea4b09ed5`, **not** by re-reading the guard. A changed
fingerprint with EP8 = 0 is gate 6: stop and report.

### EP10, EP11 — the invariant the whole pass exists to establish

`scenes.footprint` is `geometry(POLYGON,4326)`; a non-Polygon is reported and
leaves the footprint NULL, so a nonzero EP12 also shows up as EP13 > 0.
**Zero of 5,387 footprints may `ST_Equals` their own `bbox`** — that is the
geometry audit's whole distinction between an outline and an envelope, and
production's 507 existing footprints already read 0 of 507 at 18:55:17Z.
Predicting it as a quantity measured after the write, rather than asserting it
from the code, is the point.

### EP14 — the exit code, and what each outcome means

**Predicted `0`, twice: on the execute, and on the item-6 dry re-run over an
empty queue.** This is the prediction the last three sessions could not make
honestly, and its two halves are not the same claim:

* **The dry re-run is the harder one.** It fetches nothing (queue 0) and
  finishes in seconds, so it never idles long enough for Neon to reap the
  connection — it cannot exercise the NORM-29 guard at all. A `0` there is
  consistent with the guard working and equally consistent with it being inert
  (`SNAPSHOT-ENRICH-EXIT-FIX-REPORT-2.md` §4 says exactly this about the local
  run). **It is recorded as a non-regression check, not as evidence the fix
  works.**
* **The execute is the weaker reading, and that is the honest ordering.** It
  commits every ~200 rows, so the connection is exercised throughout and the
  18-minute idle window does not exist in that mode. If teardown never raises,
  `.rc = 0` says nothing about NORM-29 — it says the ordinary path exits
  cleanly under a write, which is worth having and is not the same claim.

**The reading that settles NORM-29 has already been taken, and it is recorded
here rather than predicted, because it happened before this file was written.**
The third dry run idled the session for eighteen minutes and Neon reaped it
exactly as it did on 2026-08-29 at 08:02Z and 18:14Z: the structlog summary
landed at 19:13:48.481Z, `teardown_operational_error_after_completed_run` was
logged with the traceback at 19:13:48.483Z, and **`.rc` read `0`**. That is a
true positive — the failure occurred, the guard caught it, the exit code told
the truth — not a quiet path that merely avoided the bug. **EP14 is therefore a
prediction about two runs that probably cannot reproduce the trigger**, and it
is scored as such.

**The three outcomes and what each means, written down before the numbers are
read so none of them can be rationalised afterwards:**

1. **`.rc = 0` on both** → predicted. Adds a write-mode and an empty-queue
   reading to the dry run's true positive; does not by itself add evidence
   about the guard.
2. **`.rc = 1` with a clean report** → **a third distinct exit-path failure
   mode. STOP and report.** Not a re-run candidate, and explicitly not a
   NORM-27/NORM-29 recurrence: that mechanism was observed firing and being
   absorbed at 19:13:48Z, on the deployed `sqlalchemy.exc.OperationalError`
   guard verified in the image at 18:54Z. A third `1` means something neither
   session found.
3. **`.rc = 1` with a dirty report** → the ordinary contract working:
   `sys.exit(1 if out.errors else 0)`. Read the errors, do not re-run blind.

### EP15 — the served check, with the subject named in advance

**Parcel `a79522ab-0681-4629-a4fe-935ab4d856c2`, group_key `2015`, scene
`1f4276e5-d41e-4c3d-8cf5-90be04b5c4fe`, NAIP item
`ny_m_4007306_sw_18_.5_20150522_20151109`** — token `.5`, currently
`resolution_m = 1.0`, predicted `0.5` after the run. Chosen read-only at
18:56:51Z and named here **before** the write so the check cannot be selected
after the fact from whatever happened to move.

The prediction is that this parcel serves `0.5` **end to end** — through the
listing path that reads `scenes` after the step-3 cutover, not merely in the
table — so the `1m res` chip at `frontend/src/components/MapView.tsx:298-301`
reads `50cm`. **This is NORM-18's first production observation**, and it is
predicting two things at once: that the cutover reads `scenes`, and that
nothing caches the old value.

### EP16 — wall time

One GET per row at `--min-interval-s 0.2` — 5 dispatches/second globally — so
the floor is `5387 × 0.2 = 1,077 s = 17 min 57 s`. Three dry runs measured
1,080 s, 1,081 s and 1,079 s. The execute adds 27 commits of
~200 rows each against Neon, which is why the band's top is raised over the dry
runs' rather than centred on them: **18–24 min**.

## §E2 — Gates on the write

1. Any `error` outcome → stop, report, do not re-run blindly.
2. More than 10 404s, or any 404 outside `sentinel-2-l2a` → stop (§P3).
3. Any 403 → not a stop, but every id enumerated and a STATUS.md line.
4. Any landsat or sentinel-2 `resolution_m` change → reported per row.
5. The dry run's totals and the execute's totals must agree row for row.
   They share one `plan_row`, so a disagreement is a defect in the pass.
6. Any existing `bbox` observed to have moved → stop and report.
7. **`.rc` nonzero with a clean report → stop and report as a new finding**
   (§EP14 outcome 2). Not a re-run candidate.
8. **Interruption is not a rollback** (NORM-8). If the ssh client dies, the
   remote process is still running: verify by `/proc` scan and queue count,
   record what was found, and resume the same logical run with the reason
   written down. Never relaunch blind.

---

## Observed — production, THE EXECUTE

*(Appended 2026-08-29 after the write completed. Everything above this line is
as committed in `93ff05c`, `c16f570`, `82cbda9`, `261f6af` and `53ce6b5` and
has not been edited.)*

**The heal ran in two pieces, and that is part of the record rather than a
footnote.** Attempt 1 (19:16:29Z) committed batch 1 — 200 rows — and died on
batch 2 when this session's own read-only progress poll leaked
`default_transaction_read_only = on` through Neon's transaction-mode pooler
(**NORM-30**). Attempt 2 (19:31:26Z → 19:51:21Z, 1,195 s) was the **same
logical run resumed**, not a relaunch: the resume mechanism is queue
re-derivation, so it opened on the 5,187 rows that remained and never re-fetched
the 200 already written. **5,187 + 200 = 5,387.** Captures committed unedited:
`snapshot-enrich-prod-run.{md,txt}`, `snapshot-enrich-prod-run-resume.{md,txt}`,
`snapshot-enrich-prod-postrun.json`.

### Scorecard — 16 scoreable, 15 confirmed, 1 falsified

| # | Predicted | Observed | Verdict |
|---|---|---|---|
| EP1 | 5,387 fetched | **200 + 5,187 = 5,387** | confirmed |
| EP2 | 0 × 403 / 0 × 404 | **0 / 0** | confirmed |
| EP3 | 5,387 enriched, remainder 0 | **5,387**, remainder **0** | confirmed |
| EP4 | 527 NAIP rewrites, 77 / 11 / 439 | **527**, **77 / 11 / 439** | confirmed |
| EP5 | 0 landsat changes | **0** over 3,174 | confirmed |
| EP6 | 0 sentinel2 changes / 1,111 no-`gsd` | **0** / **1,111** | confirmed |
| EP7 | 0 capture-date disagreements | **0** over 5,387 | confirmed |
| EP8 | 0 bboxes filled | **0** | confirmed |
| EP9 | 0 bbox churn | fingerprint **unchanged**, `f1809593fd050be14736aaaea4b09ed5` | **confirmed by measurement** |
| EP10 | 5,387 × `ST_Polygon` | **5,387 × POLYGON** | confirmed |
| EP11 | 0 footprints `ST_Equals` own `bbox` | **0 of 5,387** (0 of 5,894 table-wide) | confirmed |
| EP12 | 0 geometry anomalies | **0 by the pass's own definition; 2 invalid polygons it does not check** | **falsified — see below** |
| EP13 | queue 0 / 27 batches | **queue 0** / 1 + 26 batches across the two pieces | confirmed |
| EP14 | `.rc` 0 on execute and on the re-run | **0** and **0**, both read from the file | confirmed |
| EP15 | the named parcel serves the new value | **0.5, end to end through the API** | confirmed |
| EP16 | 18–24 min | **1,195 s = 19 min 55 s** (resume), ~20 min of fetching in total | confirmed |

### EP12 — falsified, and the pass could not have caught it

**Two of the 5,387 written footprints fail `ST_IsValid`.** Both Sentinel-2,
both self-intersecting, both served:

| item_id | capture | reason | `ST_NPoints` | fp area / bbox area | `parcel_scenes` |
|---|---|---|---|---|---|
| `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` | 2018-12-26 | `Self-intersection[-71.00403 41.90664113]` | 28 | 0.765 / 0.951 | 1 |
| `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | 2019-06-02 | `Self-intersection[-86.75983 39.91487413]` | 22 | 1.039 / 1.206 | 2 |

**The prediction and the run's report both say "0 anomalies", and both are
correct on their own terms.** The pass's anomaly check is a *geometry type*
check — a non-Polygon is reported and leaves the footprint NULL — and these are
Polygons. `geometry(POLYGON,4326)` accepts an invalid polygon; PostGIS does not
validate on insert. So the column constraint, the pass's check and the
prediction all asked "is this a polygon" and none asked "is this a valid one".

**EP12 is scored falsified rather than confirmed-with-a-note on purpose.** It
was written as "non-Polygon geometry anomalies: 0" and that number is right;
but the quantity it was standing in for — "no bad geometry landed" — is false,
and scoring the narrow reading as a pass would be the prediction grading its own
wording. **The geometry is upstream's**, faithfully stored: PC publishes these
two footprints self-intersecting, and the pass wrote what the item said. It is
recorded as **NORM-31**, unfixed.

### EP15 — the served check, first production observation of the NORM-18 fix

Subject named in advance (§EP15, committed at `53ce6b5` before the write):
parcel `a79522ab-0681-4629-a4fe-935ab4d856c2`, scene
`1f4276e5-d41e-4c3d-8cf5-90be04b5c4fe`, item
`ny_m_4007306_sw_18_.5_20150522_20151109`, predicted `1.0 → 0.5`.

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/parcels/a79522ab-…/imagery?source=naip
parcel a79522ab-0681-4629-a4fe-935ab4d856c2  snapshots 7
   2015-05-22  res= 0.5  item= ny_m_4007306_sw_18_.5_20150522_20151109
HTTP/2 200 ; cache-control: no-cache
```

**The production API serves `0.5`** — the `1m res` chip at
`frontend/src/components/MapView.tsx:298-301` now reads `50cm` for this parcel.
That is both halves of what EP15 was predicting at once: the cutover reads
`scenes`, and nothing cached the old value.

**Across the fleet, 617 served NAIP rows moved off 1.0**: 94 at 0.3, 13 at 0.5,
510 at 0.6, with 688 staying at 1.0 because 1.0 is what their items say.

### EP9 — the invariant that was measured rather than argued

The `bbox` fingerprint over all 6,663 rows reads
`f1809593fd050be14736aaaea4b09ed5` after the write — **byte-identical to the
pre-write baseline**. 5,387 rows were updated and not one `bbox` moved. This is
the reading the guard was never asked to vouch for, taken twice against the same
`string_agg` expression, and it is what makes gate 6 a measurement.

### What the two-piece run proved that a clean one would not have

**Batching survives an abort mid-run, in production, on real data.** Attempt 1's
200 rows were committed, stayed committed through a hard failure, and were
skipped by the resume without a single re-fetch — 5,187 fetched for 5,187
remaining. The kill/resume semantics that were SIGKILL-tested locally
(`test_a_killed_run_does_not_refetch_committed_rows`, `test_each_batch_commits`)
have now met an unplanned production abort and behaved identically. **The queue
*is* the resume mechanism**, as the script's docstring claims, and this is the
first production evidence for it.

### Gates (§E2)

| Gate | Result |
|---|---|
| 1. Any `error` outcome → stop | **0 errors** across both pieces |
| 2. >10 404s or any outside `sentinel-2-l2a` → stop | **0 404s.** Never approached |
| 3. Any 403 → enumerate + STATUS.md line | **0 403s.** NORM-23 confirmed a third time |
| 4. Any landsat/sentinel-2 rewrite → report per row | **0 of 3,174 landsat, 0 of 1,111 sentinel-2** |
| 5. Dry-run and execute totals must agree | **agree exactly**: 5,387 written, 527 rewrites, same 77/11/439 |
| 6. Any existing `bbox` moved → stop | **0**, by fingerprint |
| 7. `.rc` nonzero with a clean report → new finding | attempt 1 was `.rc = 1` with a **dirty** report — EP14 outcome 3, the ordinary contract. Not tripped |
| 8. Interruption is not a rollback | **exercised for real.** Process verified dead by `.rc`, queue counted at 5,187, reason recorded, same run resumed — never relaunched blind |
