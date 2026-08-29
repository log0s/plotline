# The snapshot-scene enrichment heal against PRODUCTION — attempt 4

Session of 2026-08-29, 18:50–19:25Z. Items 1–6 of the prompt's eight.

**Outcome, in two parts, and the second one is the finding.**

**One: the exit path is fixed and PROVEN, by a true positive.** The third
production dry run reproduced the settled profile to the row and **`.rc` read
`0`** — and not because the failure stayed away. The reaped connection
happened: the structlog summary landed at `19:13:48.481Z`, the NORM-29 guard
caught `sqlalchemy.exc.OperationalError` at `19:13:48.483Z` and logged
`teardown_operational_error_after_completed_run` with the traceback, and the
process exited **0**. The defect NORM-27 named occurred, was absorbed, and the
exit code told the truth. That is the reading three sessions chased.

**Two: `--execute` ran, wrote 200 correct rows, and was killed on batch 2 by
this session's own progress poll.** The run died on
`psycopg2.errors.ReadOnlySqlTransaction: cannot execute UPDATE in a read-only
transaction`. **The cause is the read-only probe method this whole arc has
been using as its safety proof.** Against Neon's transaction-mode pooler,
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` persists on the
*server-side* backend and is handed to the next client — so the probe does not
make the prober read-only, it makes **production** read-only. New finding
**NORM-30**.

**Production state: 200 rows healed, correctly; queue 5,187; nothing
corrupted; and the connection pool is still carrying the leaked flag as of
19:22:32Z.** The remaining 5,187 rows are **not** resumed in this session:
resuming requires clearing state the authorization does not cover, and doing
it blind would mean writing into a pool that is still poisoned. §7 states the
two decisions that are the owner's.

---

## 1. What this session was asked to do, and how far it got

| Item | Status |
|---|---|
| 1. Deploy gates, artifact-level | **PASS**, all four checks (§2) |
| 2. Spot re-verify, read-only, timestamped | **PASS**, zero deltas, queue 5,387 (§3) |
| 3. Dry run, `.rc` recipe | **PASS — profile held, `.rc` = 0, guard fired** (§4) |
| 4. Prediction committed before execute | **DONE**, `53ce6b5` (§5) |
| 5. `--execute`, one logical run | **RAN. 200 rows written, then ABORTED on batch 2** (§6) |
| 6. Post-run verification | **partial — done against the partial write** (§6c) |
| 7. Score the prediction | **not reached** — the run is incomplete, and a partial run is not a scoreable one (§8) |
| 8. Record | this file, STATUS.md NORM-30 and the touched rows |

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
**§7 shows it is the mechanism that killed the write**, and the artifact is
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

## 6. Item 5 — the execute: 200 rows, then killed by this session's own poll

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

### 6c. Item 6 — verification against the partial write, 19:22:32Z

`snapshot-enrich-prod-partial.json`, taken with **`SELECT` only — no `SET`, no
`UPDATE` probe**. The probe method was retired mid-session, at the point it was
understood, rather than after the report.

| Check | Reading | Verdict |
|---|---|---|
| Queue remaining | **5,187** | = 5,387 − 200, exact |
| Footprints written | **200 of 200** attempted | complete for what ran |
| Geometry type | **200 `POLYGON`**, 0 non-Polygon, **0 invalid** | EP10, EP12 hold so far |
| Footprints `ST_Equals` own `bbox` | **0 of 200** (0 of 707 table-wide) | **EP11 holds so far** |
| `bbox` filled / churned | 0 / **fingerprint unchanged** `f1809593…` | **EP9 holds — measured, not argued** |
| Row counts | 6,663 / 12,884 / 12,884 | unchanged; no inserts or deletes |
| Provenance split | 6,156 / 505 / 2 | unchanged |
| NAIP `resolution_m` | still **1,102 × 1.0** | expected: batch 1 is landsat |
| landsat / sentinel2 | 3,174 × 30.0 / 1,111 × 10.0 | unchanged, as predicted |
| `imagery_snapshots` NAIP | still **1,305 × 1.0** | the unhealed arm, as predicted |
| `usgs_topo` | **769**, all `footprint` and `resolution_m` NULL | untouched, still unreachable |
| Served-check subject | still `1.0`, `footprint` NULL | still queued — EP15 unscored |

**The 200 rows that landed are correct.** The queue is ordered
`collection, item_id`, so batch 1 is entirely `landsat-c2-l2` — which is why
`resolution_m` rewrites are 0 and why the run's own report says so. **Nothing
about the partial write needs undoing**, and the resume mechanism is queue
re-derivation, so a resumed run picks up exactly the 5,187 that remain.

## 7. The two decisions that are the owner's

Neither is taken in this session. Both are stated with what they cost.

**Decision 1 — clearing the leaked flag.** Backend 605 was still read-only at
19:22:32Z. While it is, **any production write routed through it fails**,
including the app's own. Clearing it means issuing `SET SESSION CHARACTERISTICS
AS TRANSACTION READ WRITE` or `DISCARD ALL` against pooled connections until
sampling reads `off` — not a data write, but a repeated mutation of shared
production session state, blind as to how many backends carry the flag. It is
not covered by this session's authorization and was not done. The alternative
is to let PgBouncer's `server_lifetime` recycle the backend, which needs no
action and no permission, but has no confirmed deadline. **A restart of the API
machines would also clear it, and restarts are the owner's.**

**Decision 2 — resuming the remaining 5,187.** The authorization contemplates
resumption ("resumption after interruption is the same run, recorded with
reason, never relaunched blind"). The reason is recorded above and the run is
resumable by design. **It was not resumed here for one reason: the pool is
still poisoned**, so a resume launched now would very likely die on its first
batch and leave a third partial state. A resume is safe once decision 1 has
landed and a `SELECT`-only sample reads `off`. **It must be launched with no
read-only-probing poll of any kind** — progress is readable from the
incremental report file and the queue count, both of which need only `SELECT`.

## 8. Item 7 — the prediction is not scored

**Deliberately.** A partial run is not a scoreable one, and scoring EP1–EP16
against 200 of 5,387 rows would put a column of "unscored" and four
"holds so far" into a file whose whole value is that its halves are written at
different times and never edited. The Observed half is left unwritten; §6c
records the readings that will feed it, in this file, where they can be
revised without touching the prediction.

What §6c does establish is that **no gate was tripped by the data**: 0 errors,
0 403s, 0 404s, 0 anomalies, 0 bbox churn, 0 footprints equal to their bbox.
Gate 5 (dry-run and execute totals must agree) is intact where they overlap —
batch 1 wrote what batch 1 planned. The run stopped on the environment, not on
the pass.

## 9. State left behind

* **Production carries 200 rows of authorized, correct write** — the first
  writes this arc's heal has ever landed. All 200 `POLYGON`, none equal to its
  own `bbox`, none invalid. **Queue 5,187.**
* **The bbox fingerprint is unchanged** at `f1809593fd050be14736aaaea4b09ed5`.
  Nothing outside `footprint` moved; no row was inserted or deleted.
* **The connection pool is still carrying `default_transaction_read_only = on`**
  as of 19:22:32Z, on the one backend observed (pid 605, 24 of 24 samples).
  **Production writes are impaired until that clears.** This session caused it
  and did not fix it, because fixing it is outside its authorization.
* **NORM-27 and NORM-29 are closed by measurement**, on a true positive rather
  than an absence.
* **NORM-7, NORM-13 and NORM-18 are 200/5,387 of the way through their
  production heal** and are annotated as partial, not resolved.
* **769 `usgs_topo` rows remain excluded and unhealed.** No mechanism exists.
* **The read-only probe method is retired** in this session's later probes and
  recorded as NORM-30. Earlier artifacts committed today still contain it and
  are left unedited.
* **Nothing is pushed.** Commits are on `main`, local only.

## 10. Deviations from the prompt

1. **The execute did not complete, and was not resumed.** §7 decision 2.
2. **Item 7 (scoring) was not done**, and item 8's step-4 readiness reading was
   not taken — the cooling-span counters are read through
   `scripts/snapshot_reads.py`, and this session stopped issuing production
   probes once it understood that its probing was the hazard. Deferred rather
   than skipped.
3. **The session poisoned the production connection pool** at 18:55:17Z,
   18:56:51Z, 19:17:33Z and 19:18:22Z, using the method inherited from prior
   sessions in this arc. Recorded as an action against production the prompt
   did not intend, not merely as a finding about a method.
4. **The 24-connection sample at 19:21:14Z** opened and disposed 24 engines
   against production to size the contamination. Reads only, and recorded
   because it is traffic the prompt did not name.
