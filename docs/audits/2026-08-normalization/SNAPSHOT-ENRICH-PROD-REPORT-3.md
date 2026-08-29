# The snapshot-scene enrichment heal against PRODUCTION — attempt 4

Session of 2026-08-29, 18:50–19:55Z. All eight items, with one deferral (§8).

**Outcome. The heal is DONE. Queue 5,387 → 0, every row enriched, `.rc` = 0 on
both the execute and the re-run.** Four sessions after the first attempt,
NORM-7's footprint backlog, NORM-13's `scenes` arm and NORM-18's open class are
healed in production, and the served check that had gone unscored three times
is confirmed end to end through the live API.

**It took two attempts inside this session, and the reason is the session's own
instrumentation.** The first `--execute` committed 200 rows and died on batch 2
on `ReadOnlySqlTransaction` — because this arc's standard read-only probe,
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, leaks through Neon's
transaction-mode pooler and made a *shared production backend* read-only. The
probe that proved safety was the unsafe act. New finding **NORM-30**; it was
cleared under owner authorization, the pool was verified clean with
`SELECT`-only reads, and the same logical run was resumed over the 5,187 rows
that remained. **200 + 5,187 = 5,387, with no row fetched twice.**

**Three durable results, in order of how hard they were to get:**

1. **NORM-27 and NORM-29 are closed by a true positive.** The third dry run met
   the reaped connection — summary at `19:13:48.481Z`, guard at
   `19:13:48.483Z`, `.rc = 0`. The failure occurred and was absorbed. No local
   run could ever have shown this (§4).
2. **The heal landed, and every invariant was measured rather than asserted**:
   5,387 `POLYGON` footprints, 0 equal to their own `bbox`, and a `bbox`
   fingerprint byte-identical to the pre-write baseline over all 6,663 rows
   (§6d).
3. **Batching survived an unplanned production abort.** The 200 committed rows
   stayed committed and were skipped by the resume without one re-fetch — the
   first production evidence that the re-derived queue is the resume mechanism
   (§6c).

**Two things are worse than they look and are recorded as findings, not
footnotes:** NORM-30 above, which has a code site in a committed script; and
**NORM-31** — two of the written footprints are self-intersecting polygons that
every check in the pipeline passes, because they check geometry *type* and not
validity (§6e).

---

## 1. What this session was asked to do, and how far it got

| Item | Status |
|---|---|
| 1. Deploy gates, artifact-level | **PASS**, all four checks (§2) |
| 2. Spot re-verify, read-only, timestamped | **PASS**, zero deltas, queue 5,387 (§3) |
| 3. Dry run, `.rc` recipe | **PASS — profile held, `.rc` = 0, guard fired** (§4) |
| 4. Prediction committed before execute | **DONE**, `53ce6b5` (§5) |
| 5. `--execute`, one logical run | **DONE in two pieces** — 200 rows, abort, resume of the same run, 5,187 rows (§6a–§6c) |
| 6. Post-run verification | **DONE**, including the served check (§6d, §6e) |
| 7. Score the prediction | **DONE** — 16 scoreable, 15 confirmed, 1 falsified (§7) |
| 8. Record | this file, the prediction's Observed half, STATUS.md NORM-30 and NORM-31. **Step-4 readiness DEFERRED with cause** (§8) |

NORM-28's rule was followed without exception: **every `fly ssh` in this
session pinned `--machine`**, including every read of both runs' artifacts.

## 2. Item 1 — deploy gates, all four pass

### 2a. Health sha, and the fix commit as an ancestor

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/health
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"44a9eeb12baa56a546b495a17fbb1acc10694fef",
            "built":"2026-08-29T18:50:51Z"}}

$ git fetch origin && git rev-list --left-right --count origin/main...main
0	0
$ git merge-base --is-ancestor 1b59af7 44a9eeb12baa… && echo ok
ok
```

The serving sha is `44a9eeb`, this repo's HEAD at session start, and the
NORM-29 fix `1b59af7` is its parent. **PASS.**

### 2b. `GH_SHA` on every machine of both apps

| app | machine | `GH_SHA` | digest |
|---|---|---|---|
| `log0s-plotline-api` | `48e0de9a713918` | `44a9eeb1…` | `sha256:e362534b…` |
| `log0s-plotline-api` | `825d69b7e46618` | `44a9eeb1…` | `sha256:e362534b…` |
| `plotline-worker` | `e2862966b306d8` | `44a9eeb1…` | `sha256:f791d98d…` |
| `plotline-worker` | `e7845415f57728` (standby, stopped) | `44a9eeb1…` | `sha256:f791d98d…` |

**4 of 4, digests identical within each app.** **PASS.**

### 2c. The image opened, not just labelled

On `825d69b7e46618`, `48e0de9a713918` and `plotline-worker`'s
`e2862966b306d8`, identically:

```
116:from sqlalchemy.exc import OperationalError
625:    except OperationalError:
631:        # this catches ``sqlalchemy.exc.OperationalError`` (the psycopg2 error
636:        logger.error("teardown_operational_error_after_completed_run", exc_info=True)
```

`grep -c psycopg2` over the deployed file is **1**, and that one hit is inside
the NORM-29 comment at `:631` — the import is gone. This is the gate NORM-26
requires and the one `SNAPSHOT-ENRICH-PROD-REPORT-2.md` §2c said could prove
text but not correctness; §4 is where correctness got proved. **PASS.**

## 3. Item 2 — pre-run measurement, 2026-08-29T18:55:17Z

Committed as `snapshot-enrich-prod-prerun-3.json` (`2a00acc`).

**On the read-only proof in that file: it is the defect.** The probe set
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, committed it, and
recorded `ReadOnlySqlTransaction` from `UPDATE scenes SET resolution_m =
resolution_m WHERE false`. At the time that was this arc's standard evidence.
**§6b shows it is the mechanism that killed the write**, and the artifact is
committed unedited with this note attached rather than retro-fitted.

### Deltas — nothing moved, for the third measurement running

| | t0 (06:41:47Z) | 17:45:53Z | **18:55:17Z** | delta from t0 |
|---|---|---|---|---|
| `scenes` | 6,663 | 6,663 | **6,663** | **0** |
| — snapshot / enriched / selection | 6,156 / 505 / 2 | same | **6,156 / 505 / 2** | **0** |
| `parcel_scenes` | 12,884 | 12,884 | **12,884** | **0** |
| `imagery_snapshots` | 12,884 | 12,884 | **12,884** | **0** |

`max(scenes.fetched_at)` and `max(parcel_scenes.selected_at)` are both
`2026-08-29 04:41:26.056028+00`, unchanged and now 14 hours stale; rows stamped
at or after t0 are **0** in both tables; `selected_by` is non-NULL on exactly
**7** rows, all `efa4c63a…`. **No traffic to reconcile.**

### The queue, re-derived by the script's own definition

```
provenance = 'snapshot'                       6,156
  − source = 'usgs_topo'                      −  769
  − footprint already non-NULL                −    0
  = queue                                     5,387
```

| source | collection | queue rows | bbox NULL | capture_date NULL |
|---|---|---|---|---|
| landsat | `landsat-c2-l2` | **3,174** | 0 | 0 |
| naip | `naip` | **1,102** | 0 | 0 |
| sentinel2 | `sentinel-2-l2a` | **1,111** | 0 | 0 |
| | | **5,387** | **0** | **0** |

`count(DISTINCT (collection, item_id))` = **5,387**. 769 topo excluded, every
one NULL in both `footprint` and `resolution_m`. NAIP queue resolution is
**1,102 × 1.0**; landsat **3,174 × 30.0**; sentinel2 **1,111 × 10.0**;
`imagery_snapshots` NAIP **1,305 × 1.0**. Existing footprints **507, all
`POLYGON`, 0 `ST_Equals` their own `bbox`**. NAIP token histogram identical to
both prior readings: `1`:575, `060`:395, `030`:77, `.6`:31, `h`:13, `.5`:11.

**The bbox fingerprint reproduced the recorded baseline exactly** —
`f1809593fd050be14736aaaea4b09ed5` over all 6,663 rows — which also settles a
loose end: the baseline's `string_agg` delimiter is a comma. Four candidate
delimiters were computed and only the comma matched, so the comparison is a
match rather than a coincidence of formatting.

## 4. Item 3 — the dry run, and the reading this arc has been chasing

Launched detached from `825d69b7e46618` with the PP14 recipe:

```sh
setsid nohup sh -c 'python scripts/enrich_snapshot_scenes.py \
  --report /tmp/snapshot-enrich-prod-dryrun-3.md \
  > /tmp/snapshot-enrich-prod-dryrun-3.log 2>&1; \
  echo $? > /tmp/snapshot-enrich-prod-dryrun-3.rc' \
  < /dev/null > /dev/null 2>&1 &
```

Launched 18:55:46Z, `bg-pid=664`, verified live by `/proc` scan (`/proc/664`
the wrapper, `/proc/665` the run — the image still has no `ps`).
**18:55:49Z → 19:13:48Z, 1,079 s = 17 min 59 s.** Captures committed unedited:
`snapshot-enrich-prod-dryrun-3.md`, `snapshot-enrich-prod-dryrun-3.txt`.

### The profile, three runs deep

| Quantity | dry 1 (`261f6af`) | dry 2 (`174892cc`) | **dry 3 (`44a9eeb`)** |
|---|---|---|---|
| Queue at start / topo excluded | 5,387 / 769 | 5,387 / 769 | **5,387 / 769** |
| Fetched / STAC requests / matched | 5,387 | 5,387 | **5,387** |
| item GET **403** / **404** / errors | 0 / 0 / 0 | 0 / 0 / 0 | **0 / 0 / 0** |
| `footprint` filled / `bbox` filled | 5,387 / 0 | 5,387 / 0 | **5,387 / 0** |
| `resolution_m` rewritten | 527 | 527 | **527** |
| — `→ 0.3` / `→ 0.5` / `→ 0.6` | 77 / 11 / 439 | 77 / 11 / 439 | **77 / 11 / 439** |
| sentinel2 with no `gsd` | 1,111 | 1,111 | **1,111** |
| Capture-date disagreements / anomalies | 0 / none | 0 / none | **0 / none** |
| Batches | 27 | 27 | **27** |
| Wall time | 1,080 s | 1,081 s | **1,079 s** |
| **`.rc`** | **1** | **1** | **0** |

Summary line: `bboxes=0 errors=0 excluded_topo=769 execute=False
footprints=5387 queue=5387 resolutions=527 unmatched_403=0 unmatched_404=0
written=5387`.

**NORM-23 is confirmed a third time**: 0 × 403 over another 5,387 catalogued
ids, and 0 × 404 for the third time. `enrich_synthesized_scenes.py`'s item-403
fall-through branch has still never fired live, now across
1,515 + 88 + 1,031 + 5,387 + 5,387 + 5,387 resolutions.

### `.rc` = 0, and it is a true positive rather than a quiet path

```
$ fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C \
    "cat /tmp/snapshot-enrich-prod-dryrun-3.rc"
0
```

The distinction matters, because a `0` from a run that never met the failure
would prove nothing — that is precisely what
`SNAPSHOT-ENRICH-EXIT-FIX-REPORT-2.md` §4 disclosed about the local check.
**This run met it.** From `snapshot-enrich-prod-dryrun-3.txt`:

```
19:13:48.481353Z [info ] Enriched snapshot scenes  … errors=0 footprints=5387 …
19:13:48.483207Z [error] teardown_operational_error_after_completed_run
Traceback (most recent call last):
  …
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) SSL connection
has been closed unexpectedly
```

Two milliseconds after the summary, the same reaped-connection failure that
produced `.rc = 1` at 08:02Z and 18:14Z was raised — and this time the guard
caught it, logged it once with its traceback, and `sys.exit(1 if out.errors
else 0)` was reached with `out.errors = 0`. **NORM-27's defect occurred and was
absorbed. NORM-29's fix is confirmed in production against the exception the
runtime actually raises**, which is exactly what NORM-29's own rule demanded
and what no local run could deliver.

## 5. Item 4 — the prediction, committed before the write

`53ce6b5`, appended to `PREDICTION-SNAPSHOT-ENRICH.md` below the untouched
local and dry-run halves (the first 921 lines were diffed byte-for-byte
against their pre-append state; identical). EP1–EP16.

Its §E0 is a disclosure that after three dry runs almost nothing about the
*plan* is blind, and names what is: whether the write lands what the plan said,
the post-write geometry invariants, and the served check. EP14 **records rather
than predicts** the NORM-29 reading, because §4 had already taken it. EP15
names the served-check subject in advance — parcel
`a79522ab-0681-4629-a4fe-935ab4d856c2`, item
`ny_m_4007306_sw_18_.5_20150522_20151109`, predicted `1.0 → 0.5` — chosen
read-only at 18:56:51Z so it could not be selected after the fact.

## 6. Item 5 — the execute: aborted at 200 rows, resumed, completed

### 6a. What ran

```sh
setsid nohup sh -c 'python scripts/enrich_snapshot_scenes.py --execute \
  --report /tmp/snapshot-enrich-prod-run.md \
  > /tmp/snapshot-enrich-prod-run.log 2>&1; \
  echo $? > /tmp/snapshot-enrich-prod-run.rc' \
  < /dev/null > /dev/null 2>&1 &
```

Launched **19:16:27Z**, `bg-pid=797`, verified live (`/proc/797` wrapper,
`/proc/798` run). Started 19:16:29Z. **Batch 1 committed 200 rows.** Confirmed
by a read at **19:17:33Z**: queue `5387 → 5187`, footprints `0 → 200`.

Then batch 2's `UPDATE` raised, and `.rc` read **1**:

```
batch 1: 200/5387 fetched, 200 written, 0 unmatched, 0 error(s)
Traceback (most recent call last):
  …
  File "/app/scripts/enrich_snapshot_scenes.py", line 347, in _write_row
sqlalchemy.exc.InternalError: (psycopg2.errors.ReadOnlySqlTransaction)
cannot execute UPDATE in a read-only transaction
[SQL: UPDATE scenes SET footprint = ST_GeomFromEWKT(%(footprint)s) WHERE id = %(id)s]
```

**`.rc = 1` with a dirty report is EP14's outcome 3, not outcome 2** — the
report is not clean, the process died from a real exception, and no third
exit-path failure mode is implied. The exit path behaved correctly; what
failed is upstream of it.

**The script's incremental report is why this is legible at all.** It rewrites
`--report` after every batch and labels the file
`**Incomplete — this report was written after a batch, not at the end.**`
`snapshot-enrich-prod-run.md` therefore records exactly what landed: 200
fetched, 200 written, queue after 5,187 — a partial run reported as partial,
which is the "complete with zero and failed are different states" norm holding
in the third possible state.

### 6b. Why it happened — NORM-30

**The API's `DATABASE_URL` points at Neon's pooler endpoint:**

```
postgresql://***@ep-little-dust-akf7ke0y-pooler.c-3.us-west-2.aws.neon.tech/neondb
```

`-pooler` is PgBouncer in transaction mode: a client's transaction is assigned
a server-side backend and released back to a shared pool at commit. **Session
GUCs set by one client therefore outlive that client and are handed to the
next.** `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` is exactly such
a GUC.

Measured on a **fresh** `SessionLocal` that issued no `SET` of any kind, at
19:19:46Z:

```
default_transaction_read_only = on   (source = session, reset_val = off)
transaction_read_only        = on
pg_is_in_recovery()          = false
pg_db_role_setting           = (empty)
pg_roles.rolconfig           = (empty)
```

**Nothing persistent is configured read-only**, and the database is not a
replica. The flag's source is `session` on a connection this session never
configured — i.e. it arrived with the pooled backend. Twenty-four sequential
fresh connections at 19:21:14Z all landed on backend pid **605** and all read
`on`: **24 of 24 read-only, 1 distinct backend.**

**The timing identifies the culprit precisely.** Batch 1's transaction
committed before 19:17:33Z and succeeded. This session then issued read-only
progress polls at **19:17:33Z** and **19:18:22Z**, each one setting the GUC and
committing. Batch 2 — the run's next transaction, on a backend re-assigned
from the pool — failed. **The progress poll poisoned the write it was
polling.**

**The finding generalises past this run, and that is the serious half.** This
probe method is what every session in this arc has used as its proof of
read-only safety, on the strength of `ReadOnlySqlTransaction` being raised.
The proof was real about the prober and false about everything else: the
statement does not make a session read-only, it makes a *shared server backend*
read-only, for whoever gets it next — the API, the Celery worker, or an
authorized heal. It is a **write disguised as a read-only safety measure**, and
it has been running against production since at least 07:42Z.

**What it did not do:** no data was altered by it, nothing was corrupted, and
`fly logs --no-tail` on both apps shows **0** occurrences of
`ReadOnlySqlTransaction` in the retrievable buffer — a floor, not a count, on
a capped 100-line page. The only observed victim is this session's own write.

### 6c. The resume — the same logical run, not a relaunch

NORM-30's flag was cleared under owner authorization (§6f), and the pool was
verified clean with `SELECT`-only reads from **both** apps at 19:30:49Z and
19:30:57Z: **0 of 8 connections read-only**, from `log0s-plotline-api` and
`plotline-worker` alike.

Launched **19:31:24Z**, `bg-pid=1048`, same recipe, same pinned machine.
**19:31:26Z → 19:51:21Z, 1,195 s = 19 min 55 s.**

```
Queue at start: 5187 … Rows fetched: 5187. STAC requests issued: 5187.
matched and written 5187 | 404 0 | 403 0 | error 0
footprint filled 5187 | bbox filled 0 | resolution_m rewritten 527
naip 1.0 → 0.3  77 | 1.0 → 0.5  11 | 1.0 → 0.6  439
sentinel2 carrying no gsd: 1111
Capture-date disagreements: None.  Anomalies: None.  Findings: None.
Wrote 5187 row(s). Queue after this run: 0.
```

`bboxes=0 errors=0 excluded_topo=769 execute=True footprints=5187 queue=5187
resolutions=527 unmatched_403=0 unmatched_404=0 written=5187`, and **`.rc` read
`0`**.

**It opened on 5,187, not 5,387.** The queue is re-derived on every run and
after every commit's worth of progress, so the 200 rows attempt 1 had already
written were simply not in it. **5,187 fetched for 5,187 remaining: not one row
was fetched twice, and not one was skipped.** `200 + 5,187 = 5,387`.

**This is the first production evidence for a claim the script's docstring has
been making since it was written** — "this query *is* the resume mechanism, and
it holds no state of its own" — and it was earned by an abort nobody planned.
The kill/resume semantics were SIGKILL-tested locally
(`test_a_killed_run_does_not_refetch_committed_rows`, `test_each_batch_commits`);
they have now met an unplanned production failure and behaved identically.

### 6d. Item 6 — post-run verification, 19:52:27Z, `SELECT` only

`snapshot-enrich-prod-postrun.json`. **No `SET`, no `UPDATE`-probe** — the
method was retired mid-session, at the point it was understood. The probe's own
session state is recorded in the artifact and reads `default_ro: off`, which is
both a check on NORM-30's remediation and the honest replacement for the
ceremony that used to stand there.

| Check | Prediction | Reading | Verdict |
|---|---|---|---|
| Queue remaining | 0 | **0** | confirmed |
| Footprints written | 5,387 | **5,387 of 5,387** | confirmed |
| Geometry type | 5,387 × `ST_Polygon` | **5,387 POLYGON** (5,894 table-wide) | confirmed |
| `ST_Equals` own `bbox` | 0 | **0 of 5,387**, 0 of 5,894 | confirmed |
| `ST_IsValid` | *not predicted* | **2 invalid** | **NORM-31, §6e** |
| `bbox` filled / churned | 0 / 0 | 0 / **fingerprint unchanged** | confirmed by measurement |
| Row counts | unchanged | 6,663 / 12,884 / 12,884 | confirmed |
| Provenance split | unchanged | 6,156 / 505 / 2 | confirmed |
| NAIP `resolution_m` | 575 / 439 / 11 / 77 | **575 × 1.0, 439 × 0.6, 11 × 0.5, 77 × 0.3** | confirmed |
| landsat / sentinel2 | unchanged | 3,174 × 30.0 / 1,111 × 10.0 | confirmed |
| `imagery_snapshots` NAIP | 1,305 × 1.0 | **1,305 × 1.0** | confirmed — the unhealed arm |
| `usgs_topo` | untouched | **769**, `footprint` and `resolution_m` both NULL | confirmed |

**The `bbox` fingerprint is the load-bearing one.** `f1809593fd050be14736aaaea4b09ed5`
before the write and after it, over all 6,663 rows, from the identical
`string_agg` expression. **5,387 rows were updated and not one `bbox` moved** —
gate 6 answered by measurement, not by re-reading the guard.

**The served check, EP15 — NORM-18's first production observation.** The subject
was named in the prediction at `53ce6b5`, *before* the write, so it could not be
selected after the fact:

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/parcels/a79522ab-…/imagery?source=naip
   2015-05-22  res= 0.5  item= ny_m_4007306_sw_18_.5_20150522_20151109
HTTP/2 200 ; cache-control: no-cache
```

**The live API serves `0.5`** where it served `1.0` this morning — the
`1m res` chip at `frontend/src/components/MapView.tsx:298-301` reads `50cm` for
this parcel. Fleet-wide, **617 served NAIP rows moved off 1.0** (94 at 0.3, 13
at 0.5, 510 at 0.6); 688 stay at 1.0 because that is what their items say.

**The dry re-run, 19:53:37Z:** queue **0**, rows fetched **0**, STAC requests
**0**, **`.rc` = 0**. Captures: `snapshot-enrich-prod-dryrun-4.txt`.

### 6e. NORM-31 — two invalid polygons that every check passes

**Two of the 5,387 written footprints fail `ST_IsValid`.** Both Sentinel-2,
both self-intersecting, both served:

| item_id | capture | reason | `ST_NPoints` | fp / bbox area | `parcel_scenes` |
|---|---|---|---|---|---|
| `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` | 2018-12-26 | `Self-intersection[-71.00403 41.90664113]` | 28 | 0.765 / 0.951 | 1 |
| `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | 2019-06-02 | `Self-intersection[-86.75983 39.91487413]` | 22 | 1.039 / 1.206 | 2 |

Enumerated in `snapshot-enrich-prod-invalid-footprints.json`.

**Nothing in the pipeline asked the question.** The pass's anomaly check is a
geometry *type* check — a non-Polygon is reported and leaves the footprint NULL
— and these are Polygons. `geometry(POLYGON,4326)` accepts an invalid polygon;
PostGIS validates on neither insert nor constraint. So the column type, the
pass's check and the prediction all asked "is this a polygon" and **none asked
"is this a valid one"**, and all three answered correctly.

**The geometry is upstream's and was stored faithfully** — PC publishes these
two footprints self-intersecting, and rule 4's whole point is that the item
wins. This is not a defect in the heal. It is a gap in what the heal is able to
notice, and it now sits behind a GiST index (`idx_scenes_footprint`) that the
serving path will eventually query: GEOS predicates over a self-intersecting
polygon can raise `TopologyException` rather than return false. **Recorded
unfixed.** Two rows out of 5,387 is not an argument for leaving it; it is an
argument that nobody would have found it by sampling.

### 6f. NORM-30 — cleared, under authorization, and verified

The owner authorized clearing the leaked flag. On each poisoned connection:
`COMMIT`, `DISCARD ALL`, `SET SESSION CHARACTERISTICS AS TRANSACTION READ
WRITE`, over 30 sequential connections at 19:29Z. **Verified afterwards by a
`SELECT`-only sample from both apps: 0 of 8 read-only, 19:30:49Z and
19:30:57Z**, and again by the post-run probe's own session state at 19:52:27Z
(`default_ro: off`). Neither the clear nor any verification touched a data row.

**The flag is gone. The class is not.** `scripts/snapshot_reads.py:138-139` is

```python
db.execute(sa_text("SET default_transaction_read_only = on"))
db.commit()
```

— the same statement, **committed**, in a script the ADR's step-4 procedure
prescribes and which produced `reads-t0.json` and `reads-t1.json`. It is not an
ad-hoc session habit; it is checked in. Left unfixed per this session's
constraint, and it is the reason §8 defers the step-4 reading.

## 7. Item 7 — the prediction, scored

Appended to `PREDICTION-SNAPSHOT-ENRICH.md` as `## Observed — production, THE
EXECUTE`; the prediction halves were diffed byte-for-byte against their
pre-append state and are untouched. **16 scoreable, 15 confirmed, 1 falsified.**

EP1–EP11 and EP13–EP16 confirmed, several to the row: 5,387 fetched and
enriched with remainder 0, 527 rewrites split exactly 77 / 11 / 439, 0 landsat
and 0 sentinel-2 changes with all 1,111 in the no-`gsd` bucket, 0 capture-date
disagreements, 0 bbox churn by fingerprint, `.rc = 0` twice, the served check
`yes`, and 1,195 s inside the 18–24 min band.

**EP12 is scored falsified** — "non-Polygon geometry anomalies: 0" is literally
correct and the quantity it stood in for, *no bad geometry landed*, is false
(§6e). Scoring the narrow reading as a pass would be the prediction grading its
own wording.

**EP14's scope, restated so the `0`s are not over-read.** The execute commits
every ~200 rows, so it never idles long enough to be reaped, and the re-run
fetches nothing; **neither could reproduce NORM-27's trigger, and neither is
evidence about the guard.** EP14 said so before the runs. The evidence is §4's
dry run, and it is a true positive.

## 8. Item 8 — step-4 readiness: DEFERRED, with cause

**Not taken, and not skipped.** The reading requires
`scripts/snapshot_reads.py`, and §6f shows that script commits the exact GUC
that killed this session's first write. Running it would have re-poisoned the
pool immediately after clearing it, to measure a cooling period. **The
instrument is the hazard**, so the measurement waits for the script to be
fixed.

What can be said without it: `imagery_snapshots` was **not written to by this
heal** — the pass touches `scenes` only, and the table's row count is 12,884
before and after, with NAIP still 1,305 × 1.0. `max(parcel_scenes.selected_at)`
is still `2026-08-29 04:41:26+00`, so no selection has run. **The cooling span
from t0 (`2026-08-29T06:41:47Z`) to 19:52:27Z is 13 h 10 m 40 s**, and the
prior session's instrument readings through 18:36:04Z stand unchanged.

**Do not start step 4.** The prompt says so; nothing here argues otherwise; and
the readiness evidence is now one instrument short until NORM-30's code site is
fixed.

## 9. State left behind

* **The heal is complete in production.** `provenance = 'snapshot'`,
  non-topo: **5,387 of 5,387 rows carry a real `ST_Polygon` footprint**, none
  equal to its own `bbox`. Queue **0**. Dry re-run confirms 0 rows, 0 fetches,
  `.rc = 0`.
* **NORM-13's `scenes` arm is healed**: NAIP `snapshot` rows are now
  **575 × 1.0, 439 × 0.6, 11 × 0.5, 77 × 0.3**, from 1,102 × 1.0.
* **NORM-18's class is closed in production** and observed end to end: 617
  served NAIP rows moved off the 1.0 chip; the pre-named subject serves `0.5`
  through the live API.
* **`imagery_snapshots` is deliberately unhealed** — still 1,305 × 1.0, so the
  two tables now disagree on 527 items with `scenes` holding the true value and
  being the one that serves. Predicted, not a defect; step 4 drops that table.
* **769 `usgs_topo` rows remain excluded and unhealed**, `footprint` and
  `resolution_m` both NULL. No mechanism exists. ADR rule 4 stays false for
  topo.
* **Nothing outside `footprint` and NAIP `resolution_m` moved.** bbox
  fingerprint identical; row counts identical; provenance split identical.
* **NORM-27 and NORM-29 are closed by measurement.** NORM-30 is cleared in the
  pool but **unfixed in `scripts/snapshot_reads.py`**. NORM-31 is open and
  unfixed.
* **Nothing is pushed.** Commits are on `main`, local only.

## 10. Deviations from the prompt

1. **The execute ran in two pieces**, the second a resumption of the same
   logical run after an abort this session caused. Recorded with its reason in
   §6a–§6c, per the authorization's "resumption after interruption is the same
   run, recorded with reason, never relaunched blind".
2. **The session poisoned the production connection pool** at 18:55:17Z,
   18:56:51Z, 19:17:33Z and 19:18:22Z using the method inherited from prior
   sessions, and then **cleared it under an authorization obtained mid-session**
   — 30 connections issued `DISCARD ALL` and `SET … READ WRITE` at 19:29Z.
   Neither the poisoning nor the clearing was in the prompt.
3. **A 24-connection sample at 19:21:14Z** opened and disposed 24 engines
   against production to size the contamination. Reads only.
4. **One `GET /api/v1/parcels/{id}/imagery` against production** at 19:53Z for
   EP15. A read, and the whole content of the served check.
5. **Step-4 readiness was not measured** (§8), because its instrument carries
   NORM-30.
6. **`ps` still does not exist in the image**; every process check used a
   `/proc/*/cmdline` scan.
