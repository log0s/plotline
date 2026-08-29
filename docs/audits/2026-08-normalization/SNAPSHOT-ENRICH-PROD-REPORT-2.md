# The snapshot-scene enrichment heal against PRODUCTION — attempt 3

Session of 2026-08-29, 17:43–18:40Z. Items 1–4 of the prompt's nine.

**Outcome. Stopped at item 4, for the second time on the same instrument and
for a different reason than last time. The dry run is perfect and `.rc` reads
`1` again — the NORM-27 fix does not work, and the mechanism is now known
exactly: the guard catches `psycopg2.OperationalError` while SQLAlchemy raises
`sqlalchemy.exc.OperationalError`, and the two classes are disjoint.** The
prompt's item-4 gate — "`.rc` nonzero with a successful report: STOP, the fix
failed its first contact" — is met literally.

**The authorized `--execute` was not spent. It is still unspent**, for the
third session running. Production carries **zero** writes from this session:
every statement ran under `default_transaction_read_only = on`, proved rather
than asserted.

**Two things did land, both from item 3, and one of them is the best reading
this arc has taken.** NORM-22 is **confirmed in production** on all three of
its clauses, and the confirmation is not a quiet window: the deploy's own
startup mint met the exact 429 that caused the original 502 and absorbed it.
Details in `PREDICTION-NORM22.md`'s Observed half; summary at §4.

---

## 1. What this session was asked to do, and how far it got

| Item | Status |
|---|---|
| 1. Deploy gates, artifact-level | **PASS**, all four checks (§2) |
| 2. Pre-run measurement, read-only, fresh | **PASS**, zero deltas, queue 5,387 (§3) |
| 3. NORM-22 deploy-window scoring | **CONFIRMED**, full coverage (§4) |
| 4. Dry run, detached, `.rc` recipe | **RAN CLEAN, `.rc` = 1 → STOP** (§5, §6) |
| 5. Prediction before execute | not reached |
| 6. `--execute` | **not run. Authorization unspent** |
| 7. Post-run verification | not reached |
| 8. Score the heal prediction | not reached (no execute to score) |
| 9. Record | this file, `PREDICTION-NORM22.md`, STATUS.md |

NORM-28's rule was followed without exception: **every `fly ssh` in this
session pinned `--machine`**, including every read of the run's artifacts.
Machine ids appear inline throughout.

## 2. Item 1 — deploy gates, all four pass

Artifact-level, per NORM-26's lesson: the label was checked *and* then the
image was opened.

### 2a. Health sha, and both required commits as ancestors

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/health
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"174892cc8164d4df7a915db279b4c77f569e1921",
            "built":"2026-08-29T17:41:26Z"}}

$ git fetch origin && git rev-list --left-right --count origin/main...main
0	0                                     # local main IS origin/main
$ git merge-base --is-ancestor fb72aaa 174892cc… && echo ok   # NORM-27 fix
ok
$ git merge-base --is-ancestor 0f193be 174892cc… && echo ok   # NORM-22 merge
ok
```

The serving sha is the pushed head, and it is not merely a descendant — it is
`174892c` itself, this repo's HEAD at session start. **PASS.**

### 2b. `GH_SHA` on every machine of both apps

`fly image show`, both apps:

| app | machine | `GH_SHA` | digest |
|---|---|---|---|
| `log0s-plotline-api` | `48e0de9a713918` | `174892cc…` | `sha256:8135510c…` |
| `log0s-plotline-api` | `825d69b7e46618` | `174892cc…` | `sha256:8135510c…` |
| `plotline-worker` | `e2862966b306d8` | `174892cc…` | `sha256:4c4248ee…` |
| `plotline-worker` | `e7845415f57728` (standby, stopped) | `174892cc…` | `sha256:4c4248ee…` |

**4 of 4, and the digests are identical within each app**, which is the
stronger statement — the label and the bytes agree. NORM-16's split-sha class
did not recur. **PASS.**

`e7845415f57728` is a stopped standby and could not be entered by `ssh`; its
image digest matches the running worker's exactly, which is the artifact-level
evidence available without starting a machine. Stated rather than glossed.

### 2c. The image opened, not just labelled

```
$ fly ssh console -a log0s-plotline-api --machine 48e0de9a713918 -C \
    "sh -c 'ls /app/scripts/shared/ && grep -c OperationalError \
     /app/scripts/enrich_snapshot_scenes.py && grep -n \
     teardown_operational_error_after_completed_run \
     /app/scripts/enrich_snapshot_scenes.py'"
stac_fetch.py
2
632:        logger.error("teardown_operational_error_after_completed_run", exc_info=True)
```

Identical output on `825d69b7e46618` and on `plotline-worker`'s
`e2862966b306d8`. `scripts/shared/` is present; the NORM-27 fix is in the
deployed file at line 632. **PASS.**

**And this is the gate's own limitation, worth naming now that §6 is known.**
The gate proved the fix's *text* is deployed. It could not prove the fix
*works* — that took running it. An image-inspection gate answers "is this
commit here", never "is this commit correct".

## 3. Item 2 — pre-run measurement, read-only, 2026-08-29T17:45:53Z

**Read-only proved, not asserted.** The probe set
`default_transaction_read_only = on` and committed it, then
`UPDATE scenes SET resolution_m = resolution_m WHERE false` raised
`psycopg2.errors.ReadOnlySqlTransaction: cannot execute UPDATE in a read-only
transaction`. Every probe in this session did the same.
`alembic_version` = **0017**. Full output committed:
`snapshot-enrich-prod-prerun-2.json`.

### Deltas — a deploy sat between the readings and moved nothing

| | t0 (06:41:47Z) | 07:42:23Z (`261f6af`) | **17:45:53Z** | delta from t0 |
|---|---|---|---|---|
| `scenes` | 6,663 | 6,663 | **6,663** | **0** |
| — snapshot / enriched / selection | 6,156 / 505 / 2 | same | **6,156 / 505 / 2** | **0** |
| `parcel_scenes` | 12,884 | 12,884 | **12,884** | **0** |
| `imagery_snapshots` | 12,884 | 12,884 | **12,884** | **0** |

**There is no traffic to reconcile.** `max(scenes.fetched_at)` and
`max(parcel_scenes.selected_at)` are both `2026-08-29 04:41:26.056028+00` —
unchanged from the 07:42Z reading, now **13 hours** stale — and the count of
rows stamped at or after t0 is **0** in both tables. `selected_by` is non-NULL
on exactly **7** `parcel_scenes` rows, all `efa4c63a…`, the step-2 sweep's
sha. No selection has run since the cutover, and the `174892cc` deploy did not
change that. **0 dangling `parcel_scenes`.**

### The queue, re-derived by the script's own definition

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

`count(DISTINCT (collection, item_id))` over the queue is also **5,387**.
**769 topo rows excluded**, every one with a NULL `footprint` *and* a NULL
`resolution_m`. `provenance = 'snapshot' AND footprint IS NOT NULL` is **0**,
so the queue is the whole non-topo snapshot population.

**The before, for NORM-13:** queue NAIP `resolution_m` is **1,102 × 1.0**, one
bucket. Landsat **3,174 × 30.0**, sentinel2 **1,111 × 10.0**.
`imagery_snapshots` NAIP is **1,305 × 1.0**.

**The invariant baselines**, taken so item 7 could have been a comparison
rather than an assertion: existing footprints **507, all `POLYGON`, 0
`ST_Equals` their own `bbox`**; and a fingerprint over every `bbox` in the
table — `md5(string_agg(id || '|' || ST_AsText(bbox) ORDER BY id))` over all
6,663 rows = **`f1809593fd050be14736aaaea4b09ed5`**. That value is the
pre-write reading a later session compares against to score PP11 (bbox churn)
by measurement rather than by re-reading the guard.

Capture-date span over the queue: landsat **1984-03-12 → 2026-08-17**, naip
**2010-04-22 → 2023-11-13**, sentinel2 **2015-08-21 → 2026-08-26**.

The NAIP filename-token histogram over the queue is **identical to the
07:42:23Z reading** — `1`:575, `060`:395, `030`:77, `.6`:31, `h`:13, `.5`:11.

**No STOP condition. Nothing to explain, because nothing moved.**

## 4. Item 3 — NORM-22 scored, confirmed, and the window contained its own trigger

Scored in full in `PREDICTION-NORM22.md`'s appended Observed section; the
prediction half is untouched. Log capture committed unedited:
`norm22-deploy-window.txt`. Summary:

The `174892cc` deploy (built 17:41:26Z) **is** the "next production deploy"
that prediction defers to — it carries `06f8f59` by way of the merge
`0f193be`. Anchors: `825d69b7e46618` `Plotline API starting` 17:41:59.371Z,
`48e0de9a713918` 17:42:17.957Z; N = 10 min.

| Clause | Result |
|---|---|
| 1. Mint lines present, per container, per machine | **6 of 6 `"SAS startup mint succeeded"`**, 0 failures, all three container labels on both machines, every one landing before its window |
| 2. Zero cold-cache 502s | **0** — and not vacuous: see below |
| 3. Zero re-mint 429s exceeding budget | **0** `"retry exceeds wait budget, giving up"` |

**Clause 2 was made non-vacuous on purpose.** A quiet window on a low-traffic
app proves nothing, so the request path was exercised inside it: a Landsat
tile — `GET /api/v1/imagery/cc8292b9-eafb-4509-a306-055084b04542/tiles/8/47/102`,
scene `LC09_L2SP_037037_20260817_02_T1` — at **17:47:22Z, 5 min 23 s after
`825d69b7e46618` booted**, returned **HTTP 200, 76,732 bytes, 4.18 s**. Same
route, same source, same signing path as the 06:39:42Z 502.

**The finding that is worth more than the three zeros.** At 17:41:59.793Z —
0.42 s after `Application startup complete` — `825d69b7e46618`'s startup mint
for `landsateuwest/landsat-c2` drew `429 Too Many Requests` on the same
`…/sas/v1/token/landsateuwest/landsat-c2` endpoint as the original incident,
backed off `wait_s=8.43`, drew a **second** 429 at 17:42:08.840Z, backed off
`wait_s=1.11`, and minted at 17:42:10.111Z with `ms=10563`.

**Ten and a half seconds of throttled signing, on the exact container and
endpoint of the incident NORM-22 was written about, absorbed with no
user-visible effect** — because a startup mint spends `SIGN_WAIT_BATCH`
(60 s), not the request path's `SIGN_WAIT_REQUEST` (2.0 s), and 10.56 s fits
the first and exceeds the second by 5×. **Pre-fix, that same 429 arriving on
the first post-deploy Landsat tile is the 502.** The window did not merely
avoid the failure mode; it contained the trigger and converted it into a
ten-second boot delay nobody could observe. `48e0de9a713918`, minting 19 s
later, met no 429 at all.

**Coverage is complete, and was proved rather than assumed.**
`fly logs --no-tail` returns a capped 100-line page; on this app that page
spans 07:54:34Z → the buffer head continuously, containing every line either
machine emitted in either window. The buffer was proved *live* by taking a
probe `ssh` at 17:54:09Z and re-capturing: the new line appeared, establishing
that the empty span 17:47:16Z → 17:54:09Z is **no lines emitted**, not lines
not yet retrieved. So this is a count, not a floor — the HEAL-SCORECARD §0
distinction, resolved in the good direction for once.

**Scope, restated so the confirmation is not over-read:** this is the
deploy-triggered instance of the class, not the class. The 429 absorbed here
arrived *at boot*. A sustained 429 storm mid-traffic still meets the 2.0 s
wall — O1 act two / G4, untouched by the fix and untouched by this
observation. And "confirmed" means the observable window was clean, which is
true under either candidate mechanism; this session did not discriminate
between them and did not try to.

## 5. Item 4 — the dry run: perfect, and reported as a failure

Launched detached from `825d69b7e46618` with the PP14 recipe, output to file
and `; echo $? > …rc`:

```sh
setsid nohup sh -c 'python scripts/enrich_snapshot_scenes.py \
  --report /tmp/snapshot-enrich-prod-dryrun-2.md \
  > /tmp/snapshot-enrich-prod-dryrun-2.log 2>&1; \
  echo $? > /tmp/snapshot-enrich-prod-dryrun-2.rc' \
  < /dev/null > /dev/null 2>&1 &
```

Launched 17:56:00Z, `bg-pid=671`, verified live at 17:56:4xZ by `/proc` scan
(the image has no `ps`): `/proc/671` the wrapper, `/proc/673` the run.
17:56:01Z → 18:14:02Z, **1,081 s = 18 min 1 s**. Captures committed unedited:
`snapshot-enrich-prod-dryrun-2.md`, `snapshot-enrich-prod-dryrun-2.txt`.

### The run's own numbers, against the `261f6af` dry run

| Quantity | dry run 1 (`261f6af`) | **dry run 2** | agree? |
|---|---|---|---|
| Queue at start | 5,387 | **5,387** | yes |
| Topo excluded | 769 | **769** | yes |
| Rows fetched / STAC requests | 5,387 / 5,387 | **5,387 / 5,387** | yes |
| Matched | 5,387 | **5,387** | yes |
| item GET **403** | 0 | **0** | yes |
| item GET **404** | 0 | **0** | yes |
| Errors | 0 | **0** | yes |
| `footprint` filled | 5,387 | **5,387** | yes |
| `bbox` filled (was NULL) | 0 | **0** | yes |
| `resolution_m` rewritten | 527 | **527** | yes |
| — `1.0 → 0.3` / `→ 0.5` / `→ 0.6` | 77 / 11 / 439 | **77 / 11 / 439** | yes |
| sentinel2 rows with no `gsd` | 1,111 | **1,111** | yes |
| Capture-date disagreements | 0 | **0** | yes |
| Anomalies / findings | none | **none** | yes |
| Batches | 27 | **27** | yes |
| Wall time | 1,080 s | **1,081 s** | 1 s |
| Queue after this run would be | 0 | **0** | yes |
| **`.rc`** | **1** | **1** | **yes — and that is the problem** |

**Every catalogue quantity reproduced to the row, eighteen hours and one
deploy apart.** The structlog summary is
`bboxes=0 errors=0 excluded_topo=769 execute=False footprints=5387 queue=5387
resolutions=527 unmatched_403=0 unmatched_404=0 written=5387`.

NORM-23 is confirmed a second time in production, independently: **0 × 403
over another 5,387 catalogued ids.** The 404 gate met real data at **0** for
the second time. `enrich_synthesized_scenes.py`'s item-403 fall-through branch
has still never fired live — now across 1,515 + 88 + 1,031 + 5,387 + 5,387
resolutions.

### And `.rc` reads `1`

```
$ fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C \
    "sh -c 'cat /tmp/snapshot-enrich-prod-dryrun-2.rc'"
1
```

Same file, same recipe, same machine, same value as `261f6af`. **The report
says the run succeeded; the `.rc` says it failed; both are this run's own
output.** That is precisely the state NORM-27 named and `fb72aaa` was written
to end.

**STOP, per the prompt's item-4 gate**, which anticipated this exact shape:
"`.rc` nonzero with a successful report: STOP, the fix failed its first
contact." It did.

## 6. F1 — the NORM-27 fix catches an exception the code cannot raise

**New, and it supersedes NORM-27's "FIXED LOCALLY" status. Not fixed in this
session** — the prompt's constraint is that script bugs against production
data are stop-and-report.

The traceback, from `snapshot-enrich-prod-dryrun-2.txt`, after the report
rendered and the summary was emitted:

```
  File "/app/scripts/enrich_snapshot_scenes.py", line 639, in <module>
    main()
  File "/app/scripts/enrich_snapshot_scenes.py", line 617, in main
    with SessionLocal() as db:
  File ".../sqlalchemy/orm/session.py", line 1809, in __exit__
    self.close()
  ...
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) SSL connection
has been closed unexpectedly
```

The exception escaped `main()` **through the `try` that was built to catch
it**. The guard is at `:625` in the deployed file; the raise passes it.

**The mechanism, in one line: `enrich_snapshot_scenes.py:115` is
`from psycopg2 import OperationalError`, and SQLAlchemy does not raise that
class.** SQLAlchemy catches the DBAPI exception and re-raises its own wrapper,
`sqlalchemy.exc.OperationalError`, which carries the psycopg2 error as
`__cause__` but is **not a subclass of it**:

```
$ docker compose exec -T api python -c "…"
sqlalchemy.exc.OperationalError MRO: ['OperationalError', 'DatabaseError',
  'DBAPIError', 'StatementError', 'SQLAlchemyError', 'HasDescriptionCode',
  'Exception', 'BaseException', 'object']
issubclass(sqlalchemy.exc.OperationalError, psycopg2.OperationalError) = False
issubclass(psycopg2.OperationalError, sqlalchemy.exc.OperationalError) = False
```

**The two classes are disjoint.** `except OperationalError:` at `:625` can
never match what `Session.__exit__` raises, so the fix is inert in every
production path. It is not a partial fix or a fix with a gap — **it has no
effect at all on the failure it was written for**, and `.rc` behaves exactly
as it did before `fb72aaa`.

### Why 25 green tests and a delete-the-fix pass did not catch it

`backend/tests/test_enrich_snapshot_scenes.py:57` is
**`from psycopg2 import OperationalError`** — the same import as the script.
`_run_main(..., teardown_error=OperationalError("SSL connection has been
closed unexpectedly"))` at `:622` and `:665` therefore raises
`psycopg2.OperationalError`, which the guard *does* catch. So:

* `test_teardown_operational_error_after_success_exits_zero` passes **with**
  the fix and fails **without** it — a correct red/green delete-the-fix
  reading, of a guard that cannot fire in production.
* Same for `test_run_errors_and_teardown_error_both_exit_nonzero`.

**The test and the code share the wrong assumption, so the test can only
confirm it.** The delete-the-fix standard did its job — it proved the guard
is load-bearing for the exception the test raises. What no test asserted is
that the exception the test raises is the exception production raises.

**This is NORM-24's shape a third time, and the sharpest instance yet.**
NORM-21: a commit prescribed for deployment was never tested at that commit.
NORM-24: a code path was never tested in the environment that runs it. This:
**an exception handler was never tested against the exception the runtime
actually raises.** All three are the same failure of realism — the test's
world and the production world differ in exactly the dimension the fix is
about, and every local signal is green.

The local verification in `SNAPSHOT-ENRICH-EXIT-FIX-REPORT.md` could not have
caught it either, and the report says why without knowing it: the local queue
is 0, so the run finished in seconds, **the session never idled long enough to
be reaped, and no `OperationalError` of any class was ever raised.** `.rc`
read `0` because nothing went wrong, not because the guard worked.

### What the fix should be — stated, not applied

`except sqlalchemy.exc.OperationalError` (which, being SQLAlchemy's wrapper,
is what any session teardown against psycopg2 raises), or
`except (sqlalchemy.exc.OperationalError, psycopg2.OperationalError)` if the
raw class is thought reachable by some path. The test must raise the
SQLAlchemy class, and the delete-the-fix check must be re-run against it.
**And the durable requirement this session would put on the next one: the fix
is not verifiable by any local run of this script, because the local queue is
empty and the failure needs an 18-minute idle session.** It needs either a
test that raises what SQLAlchemy raises, or a local reproduction that idles a
real session until the connection is reaped. The first is cheap and this
session recommends it; the second is what would have caught the class error
without anyone reasoning about class hierarchies.

## 7. F2 — the `--execute` exposure is unchanged, and smaller than it looks

Recorded so the next session does not re-derive it. `--execute` commits every
~200 rows, so the connection is exercised throughout and the 18-minute idle
window that gets it reaped **does not exist in that mode**. The likely shape
of an `--execute` run today is: all 27 batches commit, the queue goes to 0,
the teardown at `:617` raises anyway or does not, and `.rc` is uninformative
either way.

**That is why this is a stop and not a "run it anyway".** The exposure is not
data corruption — it is that `.rc`, the one instrument a detached production
write has for telling "finished" from "died partway", is known to lie in one
direction and unproven in the other. Spending the authorized write on a run
whose completion signal cannot be trusted is what the previous session
declined to do, and the reason has not changed. It has only been made precise.

## 8. Step-4 readiness — the cooling span, both instruments

Taken read-only at **2026-08-29T18:36:04Z**; committed as `reads-t1.json`
against `reads-t0.json` (t0 = **2026-08-29T06:41:47Z**).

**Cooling span so far: 11 h 54 m 17 s.** `stats_reset` is `null` in both
readings, so the counters are comparable and nothing reset under them.

### Instrument 1 — `pg_stat_user_tables`, the database's own count

| table | `seq_scan` Δ | `seq_tup_read` Δ | `idx_scan` Δ | `n_tup_ins/upd/del` Δ |
|---|---|---|---|---|
| **`imagery_snapshots`** | **+7** | +90,188 | **+0** | **0 / 0 / 0** |
| `scenes` | +22 | +146,586 | +76 | 0 / 0 / 0 |
| `parcel_scenes` | +19 | +244,796 | +30 | 0 / 0 / 0 |

**`imagery_snapshots` took 7 sequential scans and zero index scans in twelve
hours, and was not written to at all.** 7 × 12,884 = 90,188 exactly, so those
are 7 whole-table scans and nothing else.

**The `idx_scan` delta of 0 is the load-bearing number**, and the script's own
docstring says why: the reconciler's `DELETE … WHERE id = :id` and its
upsert's conflict probe each cost an `idx_scan`. Zero of them means the
reconciler did not run — which the `max(fetched_at)`/`max(selected_at)` and
`n_tup_*` readings independently confirm.

**The 7 seq scans are attributable to audit sessions, and this is a
qualification rather than a claim.** This session's own probes issued three
(`count(*)`, the NAIP-resolution `GROUP BY`, and one `ORDER BY … LIMIT` while
picking a tile subject); the 07:42Z and 08:04Z probes of the previous session
issued more of the same shape. The counters **cannot name a caller** — that is
what the second instrument is for — so the honest statement is: *7 scans
occurred, no write or index access did, and the sessions that were reading the
table for audit purposes account for scans of exactly that shape.*

### Instrument 2 — the `imagery_snapshots_read` structlog event

**Zero occurrences in the log available**, and **the coverage is a floor, not
a count.** `fly logs --no-tail` returns a capped 100-line page; on this app
that page reaches back to **07:54:34Z**, so the reading covers roughly
**10 h 40 m of the 11 h 54 m span** and cannot speak to 06:41:47Z → 07:54:34Z.
Per HEAL-SCORECARD §0, that is stated as a floor rather than rounded up to the
full span.

**What the two instruments say together:** across at least 10 h 40 m of a
11 h 54 m cooling span, `imagery_snapshots` received no writes, no index
access, and no logged application read, and the only table access at all was
whole-table scans consistent with this arc's own audit queries.

**Do not start step 4.** The prompt says so and nothing here argues otherwise;
this is the reading, not a recommendation.

## 9. State left behind

* **Production is unwritten by this session.** Every statement ran under
  `default_transaction_read_only = on`, proved each time by the
  `UPDATE … WHERE false` probe raising `ReadOnlySqlTransaction`. `scenes`,
  `parcel_scenes` and `imagery_snapshots` are byte-identical to their
  17:45:53Z reading, which is identical to their t0 reading.
* **The authorized `--execute` is unspent**, for the third consecutive
  session. NORM-26 consumed one on a deploy that did not exist; NORM-27 on an
  exit code that lied; this one on the fix for that exit code being inert.
* **The queue is 5,387** and unchanged. NORM-7's footprint backlog, NORM-13's
  `scenes` arm and NORM-18's open class are all exactly where they were.
* **769 `usgs_topo` snapshot rows remain excluded and unhealed**, footprint
  and `resolution_m` both NULL. TNM-sourced, no PC item; ADR rule 4 stays
  false for topo. No mechanism to fill them exists.
* **NORM-22 is confirmed in production** and its prediction is scored. That is
  this session's one durable gain.
* **NORM-27 is not fixed.** `fb72aaa` is deployed, tested, green, and inert.
  STATUS.md now says so.
* **The bbox fingerprint `f1809593fd050be14736aaaea4b09ed5` over all 6,663
  rows** is recorded as the pre-write baseline, so whichever session finally
  runs `--execute` can score PP11 by measurement.
* **Nothing is pushed.** Commits are on `main`, local only.

## 10. Deviations from the prompt

1. **Items 5–8 did not run**, by the prompt's own item-4 gate. No prediction
   was written, because a prediction is written before an action and the
   action is not taken.
2. **Item 3 was executed partly out of order.** Its evidence — the boot log
   buffer — was captured at 17:43Z, during item 1, because the session started
   4 minutes after the deploy and the buffer is capped at 100 lines. The
   *scoring* was written after item 2, in the prompt's order. Capturing a
   perishable read early is not the same as scoring early, and the prediction
   file was untouched until item 3.
3. **A Landsat tile request was issued to production** (17:47:22Z). It is a
   read, it is the request path NORM-22 is about, and without it clause 2
   would have been vacuous on an app with no traffic. Recorded because it is
   an action against production that the prompt did not name.
4. **`ps` does not exist in the image**, so the "verify process" step used a
   `/proc/*/cmdline` scan instead. Recorded because the next session will hit
   the same missing binary when it checks a detached run.
