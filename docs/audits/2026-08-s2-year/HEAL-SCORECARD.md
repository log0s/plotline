# S2-Year Sweep — Post-Sweep Scorecard

Scored against `PREDICTION.md`, written 2026-08-25 before the change was
deployed and before anything ran. Nothing in that file was edited.

Sweep run **2026-08-25, 19:09:45Z → 19:16:43Z** against
`bc1125cd27c4c8f19cd52bb40438b07a70e818f1`.

**The sweep covered 30 of 184 parcels, not 184.** It aborted 13 s into the
invocation on an uncaught `AdmissionRefused: queue_full`. Every fleet-wide
line in the prediction is therefore unscored, and every line below states
which population it was measured over. See §2 and §11.1.

**Execution exception.** This sweep was invoked by a Claude session, not by
Ryan, under a one-time written exception in the session prompt, so that log
capture could start before the sweep rather than mid-way through — the
problem `../2026-08-geometry-audit/HEAL-SCORECARD.md` §0 records. The
exception was bounded by a four-line gate (§0); all four held. The only
production write in the session was the single `revalidate_landsat.py`
invocation.

Artefacts: before/after DB snapshots (14,534 and 14,148 rows), the continuous
worker log stream (1,045 lines), and 12 `--no-tail` polls.

---

## 0. The gate

| Gate | Required | Observed | Source |
|---|---|---|---|
| Worker image SHA | `bc1125cd…818f1` | `GH_SHA=bc1125cd27c4c8f19cd52bb40438b07a70e818f1` on both machines (`e2862966b306d8`, `e7845415f57728`) | `fly image show -a plotline-worker` |
| API health SHA | same | `"sha":"bc1125cd27c4c8f19cd52bb40438b07a70e818f1"`, built `2026-08-25T18:57:59Z` | `GET /api/v1/health` |
| No in-flight work | 0 `queued`/`processing` | 335 `complete`, 3 `failed`, **0 in flight** | DB, 19:08Z |
| Capture before the sweep | stream started first | stream `19:08:44Z`, sweep `19:09:45Z` — **61 s of margin** | local |

`revalidate_landsat.py` has **no deployed-SHA gate**; the `--require-sha` /
`--skip-deploy-check` pair lives only in `requeue_parcels.py`. Not ported —
the gate above was executed by hand instead, and this is the second heal in
a row where the operator, not the tool, carried the ordering.

### Timeline

| Time (UTC) | Event |
|---|---|
| 19:07:44 | Before-state captured — 14,534 rows (landsat 7,903 / sentinel2 4,382 / naip 1,267 / topo 982; 184 parcels) |
| 19:08:44 | Continuous `fly logs -a plotline-worker` stream starts; 60 s `--no-tail` poller starts |
| 19:09:45 | `revalidate_landsat.py` invoked (once) |
| 19:09:48 | First request created |
| 19:09:58 | **Script aborts** — `AdmissionRefused: queue_full` after 30 requests |
| 19:16:43 | Last request `complete` (415 s of worker time) |
| 19:17:14 | Terminal state confirmed by DB poll — 30/30 `complete` |
| 19:17:30 | After-state captured — 14,148 rows |
| 19:21:28 | Capture stopped |

---

## 1. Capture coverage

**No gaps.** The stream started 61 s before the sweep and ran 285 s past its
end, so the entire 19:09:45 → 19:16:43 window is continuously covered. This
is what §0 of the geometry scorecard was asking for, and it is the one thing
this run got structurally right that the last one could not.

Poll/stream reconciliation over the sweep window, deduplicated:

| | Lines |
|---|---|
| Unique lines seen by the 12 `--no-tail` polls | 790 |
| Unique lines seen by the stream | 1,044 |
| **Poll lines absent from the stream** | **0** |
| Stream lines absent from the polls | 254 |

The stream is a strict superset. The 254-line difference is the poller's
100-line buffer cap losing data between polls — the same cap that cost the
geometry sweep half its coverage, measured here against a stream that did
not lose it.

Independent log/DB reconciliation: the 31 `Replaced superseded imagery
snapshots` events in-window sum to **425 deletions (423 sentinel2 + 2
landsat)**, which is exactly the DB-measured deletion count. Log and DB
agree to the row. One swept parcel (`761bdd0c`) logged no S2 reconcile event
and deleted nothing — `reconcile_source_snapshots` returns early at `if not
stale` before the log line, so a parcel already holding exactly the new
selection is silent by design, not by loss.

---

## 2. Sweep hygiene

**30 parcels of 184 (16.3 %).** `revalidate_landsat.py` queued 30 requests,
then `_create_queued_request` for the 31st raised `AdmissionRefused` from
`ensure_admission`; the script catches only `IntegrityError`, so the
exception propagated and killed the batch. Prod's
`max_inflight_timeline_requests` is **30** and the worker had drained none of
the 30 yet, so the cap was hit at exactly parcel 31 of 184.

| | Value | Source |
|---|---|---|
| Parcels queued | 30 | script stdout |
| Parcels skipped as in-flight | 0 | script stdout |
| Parcels never reached | **154** | 184 − 30 |
| Requests `complete` | 30 | DB |
| Requests `failed` | **0** | DB |
| Wall time, first create → last complete | 415 s | DB |

Tasks, all 30 requests (DB):

| Source | complete | skipped |
|---|---|---|
| census | 30 | 0 |
| landsat | 30 | 0 |
| naip | 30 | 0 |
| sentinel2 | 30 | 0 |
| usgs_topo | 30 | 0 |
| property | 3 | 27 (`No property adapter for county`) |

Clean: no failures, no in-flight skips, every imagery source ran on every
parcel it reached.

---

## 3. S2 conservation — the central prediction

**P1: confirmed, exactly, on all 30 swept parcels.**

| Statistic | Predicted | Observed (30 swept) | Source |
|---|---|---|---|
| Rows per parcel | exactly `2026 − 2014` = 12 | **min 12, median 12, max 12** | DB |
| Parcels above 12 | 0 (falsifies P1) | **0** | DB |
| Parcels below 12 | allowed; the O6 measurement | **0** | DB |
| Parcels with two rows in one calendar year | 0 | **0** | DB |

Every one of the 30 parcels holds exactly 12 S2 rows, one per calendar year
2015–2026, with no year missing and no year doubled. There is no parcel to
list under "not at 12" and no missing year to explain.

**What this says about P6.** The deficit `12 − actual` is zero on all 30.
P6 predicted most parcels at 12 with a below-12 population concentrated in
coastal/boundary-adjacent parcels; on this sample the below-12 population is
empty. The sample is not the fleet and contains none of the named
coastal parcels (§6, §7), so P6 stays open — but the first 30 parcels
measured under the new formula show no damage at all.

For contrast, the 154 unswept parcels still carry the quarter-grouped shape:
min 5, median 23, max 39 S2 rows, **154 of 154 holding at least one duplicate
calendar year**. That is the population this sweep did not reach.

---

## 4. Deletion wave, measured

Measured by diffing the before and after snapshots on `(parcel_id, source,
capture_date, stac_item_id)` — not derived from row-count arithmetic.

| Quantity | Predicted (fleet, 184) | Observed (30 swept) | Verdict |
|---|---|---|---|
| S2 rows deleted | ~2,170 (band 1,900–2,400) | **423** | **unscored** — 16.3 % of the fleet |
| S2 rows added | ~110 (band 0–200) | **6** | **unscored** |
| S2 rows after | ~2,210 | **360** on the swept 30; 3,965 fleet-wide | **unscored** |

Per-parcel, where the prediction *is* scorable:

| | Predicted | Observed | Note |
|---|---|---|---|
| Deletions per parcel | 11.8 (23.8 − 12) | **14.1** | the swept 30 averaged **25.9** S2 rows before, not the fleet's 23.8 |
| Additions per parcel | 0.6 (3 / 5 sampled) | **0.2** | 6 additions over 30 parcels |
| Final rows per parcel | 12 | **12** | exact |

The deletion count follows from the before-count and the formula with no
residual: 777 − 423 + 6 = 360 = 30 × 12. The prediction's arithmetic is
therefore intact; only its multiplier is unmeasured. Projecting the same
mechanism over the remaining 154 parcels (3,605 rows → 1,848) gives ~2,211
fleet deletions and ~37 additions — inside both bands — but that is
arithmetic on an unmeasured population, offered as a projection and not as a
score.

### Additions: recency versus selection-changing

All 6 additions fall in **2026**, the open year, as P2 predicted. Five are
genuine recency — a scene newer than every row the parcel held:

| Parcel | Added | Cloud % | Prior newest S2 | Class |
|---|---|---|---|---|
| `56677086` | 2026-08-07 | 0.0002 | 2026-07-13 | recency |
| `c24b2125` | 2026-08-12 | 1.0814 | 2026-07-23 | recency |
| `9a824cf7` | 2026-08-12 | 0.0407 | 2026-07-25 | recency |
| `d42a8170` | 2026-08-20 | 0.0084 | 2026-07-11 | recency |
| `468c534f` | 2026-08-23 | 2.4172 | 2026-07-16 | recency |
| `75c90cec` | **2026-02-06** | 0.0087 | 2026-07-01 | **selection-changing** |

`75c90cec` is the only addition that is not recency: the run picked a
February scene at 0.0087 % over the parcel's existing 2026-01-22 row at
**0.0060 %** — a lower-cloud row that was already present and was deleted.
Recorded as a measurement in §9, where it belongs; no conclusion drawn here.

### Per-parcel S2 diff, all 30

| Parcel | Before | After | Deleted | Added |
|---|---|---|---|---|
| `2fc4fa03` | 36 | 12 | 24 | 0 |
| `2003d090` | 35 | 12 | 23 | 0 |
| `6422b9f9` | 35 | 12 | 23 | 0 |
| `75c90cec` | 33 | 12 | 22 | 1 |
| `8b340207` | 33 | 12 | 21 | 0 |
| `a79522ab` | 33 | 12 | 21 | 0 |
| `099336a2` | 32 | 12 | 20 | 0 |
| `153b4e14` | 32 | 12 | 20 | 0 |
| `e3a6c640` | 32 | 12 | 20 | 0 |
| `90b3acd5` | 31 | 12 | 19 | 0 |
| `fccb0598` | 31 | 12 | 19 | 0 |
| `bb41c52d` | 30 | 12 | 18 | 0 |
| `d68ef5f5` | 28 | 12 | 16 | 0 |
| `c829ed3c` | 27 | 12 | 15 | 0 |
| `f0e0806e` | 27 | 12 | 15 | 0 |
| `71d8ea55` | 26 | 12 | 14 | 0 |
| `b0ca9bbc` | 26 | 12 | 14 | 0 |
| `d38891fc` | 26 | 12 | 14 | 0 |
| `b494f235` | 25 | 12 | 13 | 0 |
| `1247f9cf` | 24 | 12 | 12 | 0 |
| `56677086` | 22 | 12 | 11 | 1 |
| `9a824cf7` | 22 | 12 | 11 | 1 |
| `c24b2125` | 22 | 12 | 11 | 1 |
| `716885e3` | 20 | 12 | 8 | 0 |
| `d42a8170` | 18 | 12 | 7 | 1 |
| `3cca4341` | 16 | 12 | 4 | 0 |
| `97e763be` | 16 | 12 | 4 | 0 |
| `468c534f` | 14 | 12 | 3 | 1 |
| `7ef10b5c` | 13 | 12 | 1 | 0 |
| `761bdd0c` | 12 | 12 | 0 | 0 |
| **total** | **777** | **360** | **423** | **6** |

---

## 5. Collateral churn — P4

**P4 is falsified in letter and upheld in substance.** Both halves are stated
because the difference is the whole point of the prediction.

| Source | Predicted | Deleted | Added | Verdict |
|---|---|---|---|---|
| naip | 0 / 0 | **0** | **0** | **confirmed exactly** |
| landsat | 0 / 0 | **2** | **2** | **deviation** |
| usgs_topo | 0 / 0 | **0** | **31** | **deviation** |

**Landsat is exactly conserved.** All 30 swept parcels held 43 rows before
and 43 after; fleet total 7,903 → 7,903, unchanged. The two deletions are
one-for-one, same-parcel, same-year replacements, and both fall in **2026**,
the open year:

| Parcel | Deleted | Cloud % | Added | Cloud % |
|---|---|---|---|---|
| `2fc4fa03` | 2026-04-07 `LC09_L2SP_025027_20260407_02_T1` | 0.49 | 2026-06-27 `LC08_L2SP_024027_20260627_02_T1` | 0.65 |
| `3cca4341` | 2026-01-10 `LC09_L2SP_040037_20260110_02_T1` | 0.06 | 2026-04-08 `LC08_L2SP_040037_20260408_02_T1` | 0.27 |

Both swap a lower-cloud row for a higher-cloud one within the open year —
flagged in §11.4, not investigated. No closed Landsat year was touched on any
parcel.

**The topo additions are on parcels that had no topo at all.** All 31 rows
land on four parcels holding **zero** `usgs_topo` rows before the sweep:

| Parcel | Topo before | Topo after |
|---|---|---|
| `761bdd0c` | 0 | 10 |
| `c24b2125` | 0 | 9 |
| `3cca4341` | 0 | 7 |
| `71d8ea55` | 0 | 5 |

Map years span 1888–1995. Nothing was deleted. This is a first fetch on a
source that had never been populated for these parcels — P4's clause reads
"what an unchanged-code sweep would do — which for a re-run over an
already-swept parcel is 0", and these four parcels were not, for topo,
already swept.

**So: the leak reading is not supported.** P4's stated failure mode was "the
change leaked outside S2 — the most serious outcome available here". Zero
non-S2 rows were deleted outside the open year, NAIP churn is exactly zero,
Landsat is conserved parcel-by-parcel, and the topo movement is additive
backfill on empty sources. The literal zero is falsified; the claim it was
written to test is not.

---

## 6. G2 — Rodanthe: **unscored, unchanged**

Rodanthe (`cf46ed63`) was **not among the 30 parcels the sweep reached**. Its
S2 rows are byte-identical before and after: 34 rows, unchanged.

The 2015 pair that P5 predicted would resolve is both still present:

| Capture | Cloud % | Item |
|---|---|---|
| 2015-07-26 | **25.037** | `S2A_MSIL2A_20150726T160236_R054_T18SVE_20210411T162645` |
| 2015-10-21 | 1.007 | `S2A_MSIL2A_20151021T155022_R011_T18SVE_20210412T184030` |

2017 still holds **four** rows (2017-02-12, 05-03, 09-20, 12-14). The
featured card that was wrong is still wrong. P5's Rodanthe half is neither
confirmed nor falsified — the parcel was never re-run.

## 7. G3 — Green Valley Ranch: **unscored, unchanged**

GVR (`2a4ca7b9`) was also not among the 30. 22 S2 rows before and after,
unchanged, and 2026 still holds **four**:

| Capture | Cloud % |
|---|---|
| 2026-03-08 | 0.052 |
| 2026-03-26 | 3.287 |
| 2026-06-29 | 0.104 |
| 2026-07-11 | 0.0002 |

P5 predicted one 2026 row dated 2026-08-20 at 0.00 %. Untested. Note that
`d42a8170` — a different parcel, in the swept set — did take
`S2C_MSIL2A_20260820T173901_R098_T13TDE…` at 0.0084 %, the same acquisition
date P5 named for GVR from the same Denver-area tile, which is weak
corroboration for the replay and nothing more.

## 8. Featured pages: **no change, because none were swept**

None of the six featured parcels are in the 30. Every S2 row on every
featured parcel is identical before and after; no served item changed for any
year.

| Featured parcel | S2 cards before | after | Rows changed |
|---|---|---|---|
| Stapleton / Central Park | 16 | 16 | 0 |
| RiNo Art District | 16 | 16 | 0 |
| Green Valley Ranch | 22 | 22 | 0 |
| Navy Yard / Capitol Riverfront | 23 | 23 | 0 |
| Rodanthe, Outer Banks | 34 | 34 | 0 |
| Hudson Yards | 23 | 23 | 0 |

All six still carry duplicate calendar years — the condition the change
exists to remove. **The user-visible half of this change has not shipped to
any featured page.**

## 9. Cap-truncation signature — measurement for G8, no conclusion

Month of capture of surviving S2 rows, the 30 swept parcels, before (777
rows) and after (360 rows):

| Month | Before | After |
|---|---|---|
| Jan | 7 | 1 |
| Feb | 19 | 6 |
| Mar | 26 | 3 |
| Apr | 21 | 4 |
| May | 39 | 7 |
| Jun | 64 | 4 |
| Jul | 57 | 20 |
| Aug | 53 | 20 |
| Sep | 164 | 43 |
| Oct | 135 | 95 |
| Nov | 114 | 96 |
| Dec | 78 | 61 |

| Quarter | Before | After |
|---|---|---|
| Q1 | 52 (6.7 %) | 10 (2.8 %) |
| Q2 | 124 (16.0 %) | 15 (4.2 %) |
| Q3 | 274 (35.3 %) | 83 (23.1 %) |
| Q4 | **327 (42.1 %)** | **252 (70.0 %)** |

P7 predicted the Q4 skew would **sharpen**, and set falsification at "not at
least as Q4-weighted as the pre-sweep one". Q4 goes 42.1 % → 70.0 %:
**P7 confirmed** on the swept 30.

Two selection events sit alongside this measurement, reported without
interpretation:

- `75c90cec` 2026: picked 2026-02-06 (0.0087 %) while 2026-01-22 (0.0060 %)
  was an existing row and was deleted.
- `56677086` 2026: picked 2026-08-07 (0.0002 %) while 2026-07-13 (0.0001 %)
  was an existing row and was deleted.

In both cases the selected scene carries higher cloud than a row the same
year already held. No conclusion drawn.

## 10. Signing behaviour

| Signal | Count in window | Source |
|---|---|---|
| `SAS rate-limited; backoff exceeds wait budget, giving up` | **0** | worker stream |
| `Band signing failed after retries` | **0** | worker stream |
| `SAS container token minted` | 3 (1 sentinel2, 2 landsat) | worker stream |
| Titiler 5xx | **0** | `fly logs -a plotline-titiler --no-tail` |
| Request-path overlap | **none** | API + Titiler logs |

Titiler emitted **no log lines at all** during the sweep — its `--no-tail`
buffer's newest line is 01:47:01Z, seventeen hours earlier. The API's 14
in-window lines are this session's own SSH connections and nothing else. No
one was browsing.

So G4's pattern — batch-path signing load starving the request path — had no
opportunity to appear, and the zeros above are evidence of an idle request
path, **not** evidence that the pattern is fixed. Coverage caveat: Titiler
and API were read from the 100-line `--no-tail` buffer, not a stream; the API
buffer spans 01:43 → 19:17 and so covers the window, and Titiler's ends
before it, which is itself the finding.

## 11. Anomalies

Flagged, not investigated.

1. **`revalidate_landsat.py` cannot sweep a fleet larger than the admission
   cap.** It catches `IntegrityError` around `_create_queued_request` but not
   `AdmissionRefused`, so the first refusal aborts the batch instead of
   backing off or skipping. With `max_inflight_timeline_requests = 30` and a
   worker that drains ~2 parcels per 27 s, the script can never queue more
   than ~30 parcels in one run. The docstring's claim that "the batch
   continues" holds only for the in-flight skip, not for the cap. **154
   parcels are unswept and the S2-year change is unrealised for them.**
2. **Two `STAC year chunk failed after retries; skipping` — landsat 2016 and
   2017, `403 Forbidden` from Planetary Computer**, both at 19:12:59Z, on one
   of the two requests started at 19:12:43/19:12:44 (`ef73d7dd`,
   `d8be3336`); the log line carries no parcel id. No rows were lost: the
   absent-group rule left both years alone and every parcel ended at 43
   Landsat rows. This is M4's shape again — a per-year failure inside a task
   that reported `complete`.
3. **31 topo rows appeared on four parcels that had none** (§5). Whether
   those parcels ever had a successful topo fetch before is not recoverable
   from the record.
4. **Both Landsat replacements traded down on cloud cover** (§5), inside the
   open year.
5. **Fleet-wide, one unswept parcel (`bd70afa6`) holds 34 Landsat rows, not
   43**, and one unswept parcel holds 5 S2 rows. Both pre-date this sweep.

---

## Verdict

**Confirmed on every prediction the 30-parcel sample can reach; the
fleet-wide half is unscored, and the two named defects are untouched.**

P1 is confirmed exactly — 30 of 30 parcels at precisely 12 S2 rows, one per
calendar year, zero duplicates, zero deficits — and the log and the database
agree on the deletion count to the row, on a capture with no gaps. P7 is
confirmed: the Q4 skew sharpened from 42.1 % to 70.0 %. P4 is falsified in
letter by 2 Landsat swaps in the open year and 31 topo backfill rows, and
upheld in substance: nothing leaked outside S2, NAIP churn was exactly zero,
and Landsat is conserved parcel-by-parcel.

P2, P3, P5 and P6 are **unscored**, not confirmed and not falsified. The
sweep reached 16.3 % of the fleet and none of the six featured parcels, so
Rodanthe still serves the 25.04 % granule, Green Valley Ranch still holds
four 2026 rows, and every featured timeline still shows duplicate years. The
mechanism is proven; the heal is one sixth done.
