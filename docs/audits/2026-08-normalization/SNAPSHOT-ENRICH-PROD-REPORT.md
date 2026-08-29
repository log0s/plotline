# The snapshot-scene enrichment heal against PRODUCTION

> **Attempt 1, 07:3xZ — stopped at gate 1 (the heal was never pushed).** Kept
> below unedited. **Attempt 2, 07:40–08:05Z — gates passed, dry run clean in
> its plan and non-zero in its exit code; stopped before `--execute`.** The
> second attempt is §§9–14 at the end of this file.

---

## Attempt 1 — STOPPED at gate 1

Session of 2026-08-29, ~07:3xZ. Item 1 of the prompt's eight, and the only one
that ran.

**Outcome. Nothing was measured, dry-run, predicted or written. The deploy
gate fails on all three of its checks, for one root cause: the heal was never
pushed.** `scripts/enrich_snapshot_scenes.py` and `scripts/shared/` exist only
in this machine's local `main`. `origin/main` does not contain them, no CI run
could have built them, and the deployed image does not carry them.

**Production is untouched.** This session took production **reads only** —
three `fly` metadata reads, one `fly ssh -C ls`, one unauthenticated `GET
/api/v1/health`. No `--execute`, no SQL, no write of any kind. The write
authorization the prompt granted was never exercised and is unspent.

The prompt's opening sentence — "built, locally scored 1,031 → 0 with resume
exercised under SIGKILL, **and pushed. CI has deployed.**" — is the assertion
that failed. The first half is true and verifiable in the repo; the second
half is false.

---

## 1. Gate 1, check by check

The prompt's three sub-gates, each with the command and its output.

### 1a. Health sha is the pushed head, or a descendant containing the heal commits — **FAIL**

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/health
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"18ddb8e83e3fb90307bec6bf70bd480978ab19d7",
            "built":"2026-08-29T06:37:11Z"}}
```

The serving sha is `18ddb8e`. The ancestry, both directions:

```
$ git merge-base --is-ancestor 18ddb8e HEAD && echo yes
yes                          # deployed sha IS an ancestor of local HEAD
$ git merge-base --is-ancestor 24b7e48 18ddb8e || echo no
no                           # the heal commit is NOT in the deployed sha
$ git log --oneline 18ddb8e..HEAD
c16f570 docs(audits): score the local snapshot-enrich run, and move the record
93ff05c docs(audits): prediction for the local snapshot-enrichment run
24b7e48 feat(scripts): the snapshot-scene enrichment pass
65a6d3d refactor(scripts): extract the shared STAC fetch layer
cd45e28 docs(audits): step 3's production report and the record it moves
```

The deployed sha is an ancestor of local HEAD, which is the *wrong* direction:
the gate requires the deployed sha to **contain** the heal commits, and it is
five commits behind them.

### 1b. `GH_SHA` matches on every machine of both apps — **FAIL, though internally consistent**

```
$ fly image show -a log0s-plotline-api
 825d69b7e46618 │ … │ GH_SHA=18ddb8e83e3fb90307bec6bf70bd480978ab19d7 …
 48e0de9a713918 │ … │ GH_SHA=18ddb8e83e3fb90307bec6bf70bd480978ab19d7 …
$ fly image show -a plotline-worker
 e2862966b306d8 │ … │ GH_SHA=18ddb8e83e3fb90307bec6bf70bd480978ab19d7 …
 e7845415f57728 │ … │ GH_SHA=18ddb8e83e3fb90307bec6bf70bd480978ab19d7 …
```

Four machines across two apps, **all four on `18ddb8e`**, all last updated
2026-08-29T06:37Z. Fleet consistency is not the problem — NORM-16's split-sha
class does not recur here. The problem is that the agreed-upon sha is the
wrong one. (`plotline-worker`'s `e7845415f57728` is `stopped`; it carries the
same image.)

### 1c. `scripts/shared/` exists in the deployed image — **FAIL**

Verified on the artifact, not the repo, exactly as the prompt required
(NORM-24/25 were packaging findings):

```
$ fly ssh console -a log0s-plotline-api -C "ls -la /app/scripts/"
backfill_census_housing.py    heal_county_fallback.py       requeue_parcels.py
backfill_scenes.py            ledger_gaps.py                revalidate_landsat.py
enrich_synthesized_scenes.py  remove_uncovered_snapshots.py seed.py
featured_naip_copy_…​.sql      remove_unverified_reverse_…py seed_featured.py
                              requeue_empty_property.py     snapshot_reads.py
```

**Fifteen entries, no subdirectories.** No `shared/`, and no
`enrich_snapshot_scenes.py`. The script the prompt authorizes cannot be
invoked on either app: the file is not there.

This is the check that would have caught the problem even if the sha checks
had somehow passed, and it is worth noting that it is the *only* one of the
three that inspects the thing the run actually needs.

## 2. The root cause, verified

`origin/main` has not moved since the previous session:

```
$ git ls-remote origin main
cd45e28463237bac290e9da28f86576817c8a62d	refs/heads/main
$ git status -sb | head -1
## main...origin/main [ahead 4]
$ for c in 65a6d3d 24b7e48 93ff05c c16f570; do git branch -r --contains $c; done
(no output for any of the four)
```

**None of the four heal commits is reachable from any remote ref.** They are
`git fetch`-fresh readings, not a stale cache — `git fetch origin` was run
first and moved nothing.

This is the local report's own §8 still holding, unchanged: *"Nothing is
pushed. Four commits on `main`, local only."* The previous session ended
correctly — pushing is the owner's, per CLAUDE.md — and the prompt for this
session assumed a push that had not happened in between.

**A second, smaller gap, recorded because it is real and not the blocker:**
`origin/main`'s own tip `cd45e28` is also not deployed; the image is its
parent `18ddb8e`. `cd45e28` is docs-only, so no code differs, but "CI has
deployed origin/main" is false in the strict sense too. Whether that push's
workflow ran, was skipped for a docs-path filter, or failed is **not
determined here** — `gh` is not installed on this machine, and the image
labels are the authority this gate uses regardless.

## 3. What was NOT done, item by item

Every one of these is gated on item 1 and none of them ran.

| Item | Status |
|---|---|
| 2. Pre-run measurement (read-only) | **not run.** Production's queue size, its per-source arithmetic, its topo excluded count, its NAIP resolution distribution and its queue bbox-NULL count remain **unmeasured**, exactly as `SNAPSHOT-ENRICH-LOCAL-REPORT.md` §8 left them. |
| 3. Dry run | **not run.** No `snapshot-enrich-prod-dryrun.txt` exists. |
| 4. Production prediction | **not written.** `PREDICTION-SNAPSHOT-ENRICH.md` is untouched by this session and still ends at the local Observed section. |
| 5. `--execute` | **not run.** The one authorized production write is unspent. |
| 6. Post-run verification | **not run.** |
| 7. Scoring | **nothing to score.** |
| 8. Record | this file, and one STATUS.md row (NORM-26). NORM-7, NORM-13 and NORM-18 are **not** moved — their production halves are exactly where the previous session left them. |

Item 2 was deliberately not run despite being read-only. The prompt's items are
"in order, each gated on the previous", and a pre-run measurement taken against
a deploy state that cannot run the heal is a baseline with no run to anchor it
— it would have to be retaken at whatever time the real run happens, because
dual-write traffic keeps moving (the item-2 reconciliation exists precisely
because it does).

## 4. The dry run's semantics, read and stated

Recorded because item 3 required the reading and the reading is durable
whenever the run does happen: **the dry run fetches.** `--execute` is the write
flag only.

* `scripts/enrich_snapshot_scenes.py:587` — `--execute`: *"Write the rows.
  Without it this is a dry run that still fetches."*
* Module docstring, `:85` — *"Usage (dry run is the default and writes nothing;
  **both forms do fetch**)"*.

So the production sequence is two full passes over the queue at one GET per row,
not one cheap plan and one real pass. At the queue size the prompt expects
(~5,387) and the default `--min-interval-s 0.2`, that is **~18 minutes each,
~36 minutes of wall clock across the dry run and the execute**, before any
resumption. `--report` is required in both modes and is rewritten after every
batch (`:578-582`), so a killed client leaves a partial capture either way.

## 5. Findings

### F1 — a session was authorized to run a heal against a deploy state that does not exist

**New. Not a defect in any code; a defect in the handoff, and the third
member of NORM-21's family.**

NORM-21 was *"a commit prescribed for deployment was never tested at that
commit."* NORM-24 was *"a code path was never tested in the environment that
runs it."* This is **"a run was authorized against a deploy state nobody
verified had happened"** — and the prompt itself contained the antidote, in
its own list of facts to re-verify rather than inherit. The deploy claim was
not on that list; it was in the framing sentence.

**Why it did not become a production incident:** gate 1 exists, it is first,
and it is stated as STOP rather than as a warning. The cost was three metadata
reads and one `ls`. **Why it is worth a row anyway:** the failure mode it
guards against is not "the run errors out". `enrich_snapshot_scenes.py` is
absent from the image, so an unguarded attempt would have died on
`python: can't open file` — loud and harmless. The dangerous shape is the
near-neighbour where the *sha* is stale but the script happens to be present
from an earlier deploy, and the run then executes **older code than the one
that was locally scored**, writing 5,387 rows under semantics nobody tested.
That is precisely NORM-21's shape, and it is why the gate checks the artifact
(`ls /app/scripts/`) and not only the label.

**The durable rule, and it is a handoff rule rather than a code one:** a
prompt's claim that something is pushed and deployed is a claim about *two*
systems neither of which the authoring session controlled — `git push` is the
owner's and CI is asynchronous. It is re-verified before it is relied on, in
the same breath as the facts a prompt explicitly flags. Here the check is
three commands and it is already written down as item 1; the finding is that
it needed to be item 1 for a reason that materialised on its first use.

## 6. State left behind

* **Production: unchanged and unmeasured by this session.** Reads only. The
  authorized write is unspent.
* **The repo: unchanged apart from this report and one STATUS.md row.** No
  code, no script, no prediction edited. `main` is still 4 commits ahead of
  `origin/main` before this batch, 6 after it.
* **The production run is still owed**, and its prediction is still unwritten.
  Everything `SNAPSHOT-ENRICH-LOCAL-REPORT.md` §8 listed as unknown about
  production is still unknown: queue size, topo count, the 403 population
  (NORM-23 says predict it from nothing), the 404 population (a gate that has
  still never met real data).
* **What unblocks it: a push of `main` and a CI deploy**, both the owner's.
  Once `fly image show` reports a `GH_SHA` containing `24b7e48` on all four
  machines and `ls /app/scripts/` shows `shared/`, gate 1 passes and items 2
  through 8 run as written. Nothing else about the prompt needs changing.
* **Step 4 is not started and is not closer.** The cooling period from
  t0 `2026-08-29T06:41:47Z` is unaffected by a session that wrote nothing.

---

# Attempt 2 — gates passed, dry run complete, STOPPED before `--execute`

`main` was pushed between the attempts and CI deployed it. Items 1–4 of the
prompt ran and passed; **item 3 stopped the sequence at its own gate.**

**Outcome. The dry run resolved 5,387 of 5,387 rows with zero 403s, zero 404s
and zero errors — and then exited 1.** The process died closing its database
session after the report was written and the totals were final. The plan is
clean; the exit status says otherwise, and the prompt's item 3 gate is
"Errors beyond plan: STOP, commit, report."

**`--execute` did not run. Production is unchanged and unwritten by either
attempt** — verified after the dry run, not assumed (§12). The one authorized
write is still unspent.

## 9. Deploy gates — all three pass

| Gate | Evidence | Result |
|---|---|---|
| a. Health sha contains the heal | `GET /api/v1/health` → `{"sha":"5aa24ff2706e791c41edd55e6b9e9a3ecaefd376","built":"2026-08-29T07:38:19Z"}`; `git ls-remote origin main` → the same sha; `git merge-base --is-ancestor 24b7e48 5aa24ff` and `--is-ancestor 65a6d3d 5aa24ff` both exit 0 | **pass** — the deployed sha *is* the pushed head and contains both heal commits |
| b. `GH_SHA` on every machine of both apps | `fly image show`: `log0s-plotline-api` `825d69b7e46618` + `48e0de9a713918`, `plotline-worker` `e2862966b306d8` + `e7845415f57728` — **4 of 4 on `GH_SHA=5aa24ff…`** | **pass** |
| c. `scripts/shared/` in the deployed image | `fly ssh -C "ls /app/scripts/ /app/scripts/shared/"` → `enrich_snapshot_scenes.py` present, `shared/stac_fetch.py` present. Exercised, not just listed: `python -c "import scripts.shared.stac_fetch as m; print(m.__file__)"` → `/app/scripts/shared/stac_fetch.py`, and `enrich_snapshot_scenes.py --help` prints its usage | **pass** — NORM-24's import path verified in the artifact that runs it |

## 10. Pre-run measurement — read-only, 2026-08-29T07:42:23Z

Read-only proved rather than asserted: the probe set
`default_transaction_read_only = on` and **committed it**, then an
`UPDATE scenes SET resolution_m = resolution_m WHERE false` raised
**`ReadOnlySqlTransaction`**. Every probe in this session did the same.
`alembic_version` = **0017**.

### Deltas from step 3's t0 — nothing to reconcile

| | t0 (`STEP3-PROD-REPORT.md`) | 07:42:23Z | delta |
|---|---|---|---|
| `scenes` | 6,663 | 6,663 | **0** |
| — by provenance | 6,156 / 505 / 2 | 6,156 / 505 / 2 | **0** |
| `parcel_scenes` | 12,884 | 12,884 | **0** |
| `imagery_snapshots` | 12,884 | 12,884 | **0** |

**Stated in the strongest available form:** `max(scenes.fetched_at)` and
`max(parcel_scenes.selected_at)` are both `2026-08-29 04:41:26.056028+00` —
**two hours before t0** — and the count of rows stamped at or after t0 is
**0** in both tables. `selected_by` is non-NULL on exactly 7 `parcel_scenes`
rows, all stamped `efa4c63…`, the step-2 sweep's sha. **No dual-write traffic
has occurred since the cutover**, so there is no explained-or-STOP judgement
to make: there is nothing to explain.

### The queue, derived fresh by the script's own definition

```
provenance = 'snapshot'                       6,156
  − source = 'usgs_topo'                      −  769
  − footprint already non-NULL                −    0
  = queue                                     5,387
```

| source | collection | queue rows | bbox NULL | capture_date NULL |
|---|---|---|---|---|
| landsat | `landsat-c2-l2` | 3,174 | 0 | 0 |
| naip | `naip` | 1,102 | 0 | 0 |
| sentinel2 | `sentinel-2-l2a` | 1,111 | 0 | 0 |
| | | **5,387** | **0** | **0** |

`count(DISTINCT (collection, item_id))` over the queue is also **5,387** — one
row per item. **769 topo rows excluded**, all with NULL footprint. The
prompt's "~5,387 (6,156 minus ~769 topo)" is exact in both terms.

**NAIP resolution over the queue, the before for NORM-13:** 1,102 rows, **all
at 1.0**, one bucket. `imagery_snapshots` NAIP: **1,305 rows, all at 1.0**.
**bbox NULL in the queue: 0**, so no existing bbox may move.

Capture-date span: landsat 1984-03-12 → 2026-08-17, naip 2010-04-22 →
2023-11-13, sentinel2 2015-08-21 → 2026-08-26.

## 11. The dry run — 07:44:19Z to 08:02:19Z, 1,080 s

Launched detached with the PP14/F3 recipe, `.rc` included:

```sh
setsid nohup sh -c "python scripts/enrich_snapshot_scenes.py \
  --report /tmp/snapshot-enrich-prod-dryrun.md \
  > /tmp/snapshot-enrich-prod-dryrun.log 2>&1; \
  echo $? > /tmp/snapshot-enrich-prod-dryrun.rc" < /dev/null > /dev/null 2>&1 &
```

**The dry run fetches.** Read from the source before launching, as item 3
required: `--execute` is the write flag only — `enrich_snapshot_scenes.py:587`
("Without it this is a dry run that still fetches") and the module docstring at
`:85` ("both forms do fetch"). So this was a full 5,387-request pass that
planned writes and made none.

Captures committed unedited: `snapshot-enrich-prod-dryrun.md` (the report) and
`snapshot-enrich-prod-dryrun.txt` (full stdout, including the traceback).

| | |
|---|---|
| Rows fetched | **5,387** |
| STAC requests | **5,387** |
| matched (200) | **5,387** |
| unmatched — 404 | **0** |
| unmatched — 403 | **0** |
| `error` | **0** |
| `footprint` would fill | **5,387** |
| `bbox` would fill | **0** |
| `resolution_m` would rewrite | **527** |
| Queue after | **0** |
| Batches | **27** |
| Wall time | **1,080 s = 18 min 0 s** |
| **Exit code, read from `/tmp/…dryrun.rc`** | **1** |

Rewrites, all NAIP: `1.0 → 0.3` **77**, `1.0 → 0.5` **11**, `1.0 → 0.6`
**439**. Landsat: **0** rewrites over 3,174 rows. Sentinel-2: **0** rewrites,
**1,111 rows in the "no `gsd`" table** — the whole population, so PC still
publishes no item-level `gsd` for L2A. **Capture-date disagreements: none over
5,387 items.** Anomalies: none. Findings section: empty.

## 12. Production is unchanged, verified after the dry run

Read-only at 08:04:57Z, every figure identical to the 07:42:23Z reading:

| | 07:42:23Z | 08:04:57Z |
|---|---|---|
| queue | 5,387 | **5,387** |
| — by source | 3,174 / 1,102 / 1,111 | **3,174 / 1,102 / 1,111** |
| `scenes` total | 6,663 | **6,663** |
| footprints non-NULL | 507 | **507** |
| NAIP `snapshot` `resolution_m` | 1,102 × 1.0 | **1,102 × 1.0** |
| queue bbox NULL | 0 | **0** |
| topo excluded | 769 | **769** |
| `parcel_scenes` | 12,884 | **12,884** |
| `max(scenes.fetched_at)` | 04:41:26Z | **04:41:26Z** |

**The dry run wrote nothing, and that is a reading rather than an inference
from the flag.**

## 13. Findings

### F2 — the dry run succeeded and exited 1: a completed run that reports as failed

**New. The reason the sequence stopped. Script defect; NOT fixed in this
session** (the prompt's constraint: script bugs against prod data are
stop-and-report).

**Resolved:** `fb72aaa`, 2026-08-29 (local; not pushed, not deployed).
`main()` catches `OperationalError` around the session block and only
suppresses it when `run()` has already returned — teardown failure after a
completed run no longer overrides the outcome-derived exit code. Details,
tests, and deploy status: `SNAPSHOT-ENRICH-EXIT-FIX-REPORT.md`.

The sequence in `snapshot-enrich-prod-dryrun.txt`, in order:

1. `batch 27: 5387/5387 fetched, 5387 written, 0 unmatched, 0 error(s)`
2. the full report rendered to `/tmp/snapshot-enrich-prod-dryrun.md`
3. `08:02:19.536691Z [info] Enriched snapshot scenes … errors=0 footprints=5387
   queue=5387 resolutions=527 unmatched_403=0 unmatched_404=0 written=5387`
4. then:

```
psycopg2.OperationalError: SSL connection has been closed unexpectedly
  … the direct cause of …
  File "/app/scripts/enrich_snapshot_scenes.py", line 628, in <module>  main()
  File "/app/scripts/enrich_snapshot_scenes.py", line 614, in main
    with SessionLocal() as db:
  … sqlalchemy/orm/session.py … close → _close_impl → transaction.close()
  … engine/base.py _connection_rollback_impl → _rollback_impl
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) SSL connection has been closed unexpectedly
```

**The mechanism.** `main` opens one session at `:614` and holds it for the
whole run. In dry-run mode **nothing is ever committed**, so that connection
sits idle for the full 18 minutes of fetching while the pass talks only to the
Planetary Computer. Neon/pgbouncer reaps it. The work is already done and
reported; the failure is in `Session.__exit__`'s rollback on a socket that is
no longer there.

**Why the exit code is the finding and not the traceback.** `main` ends with

```python
sys.exit(1 if out.errors else 0)   # :622
```

and **that line was never reached** — the exception propagates out of the
`with` block first, so the process exits 1 from an unhandled traceback. The
script's own contract, stated in its docstring at `:99` ("this script exits
non-zero if any row ended in `error`"), is therefore violated in the direction
that matters: **`errors=0` and `.rc` says `1`.**

This is STATUS.md's *"'complete with zero' and 'failed' are different states"*
norm meeting its mirror image. The arc has spent three sessions establishing
that a detached run's exit status must be **read, not inferred** (PP14,
`STEP3-PROD-REPORT.md` F3) — and the first production run to read one read a
**false** one. A reader with only the `.rc` would conclude the pass failed; a
reader with only the report would conclude it succeeded; **both files are
this run's own output and they disagree.** The report is the one telling the
truth, and knowing that required the stdout capture, which is the third
artifact and the only place the traceback appears.

**Why it blocks `--execute` rather than being a nuisance.** Not because
`--execute` would corrupt anything — batching means committed rows stay
committed (exercised under SIGKILL locally) and a re-derived queue is the
resume mechanism. It blocks because **the run's success signal is now known to
be unreliable**, and `--execute` is the one authorized production write. Its
`.rc` is exactly how this session was told to distinguish "finished" from
"died partway", and that instrument has just been observed lying. Deciding to
write 5,387 production rows while the completion signal is broken is a
decision to spend the authorization on a run whose outcome must be
reconstructed from the database afterwards rather than reported.

**The execute's exposure is different from the dry run's, and smaller — which
is an argument for fixing rather than for ignoring.** `--execute` commits every
200 rows, roughly every 40 s, so the connection is exercised throughout and
the 18-minute idle window does not exist mid-run. The teardown path at `:614`
is identical, so the *last* moment — after batch 27 commits — remains exposed.
The likely `--execute` shape is therefore: all 27 batches commit, queue
reaches 0, and the process still exits 1. Recoverable, and unambiguous only
because the queue can be re-derived. **That is a reconstruction, not a
reading**, and item 5's whole point was to read.

**Not fixed here.** The fix is small and obvious (open the session per batch,
or catch `OperationalError` in teardown, or both) and it is still a code
change to a script mid-flight against production data, which this session is
constrained against and which would need its own tests and its own deploy.

### F3 — `fly ssh console` picks a machine arbitrarily, and a read landed on the wrong one

**New. Minor, and it nearly produced a false report.**

The app has two machines. `fly ssh console -a log0s-plotline-api -C "…"`
**chooses one**, printing `No machine specified, using <id>` — and at 08:03Z,
immediately after the run finished, it chose `48e0de9a713918` while every
previous command in this session had landed on `825d69b7e46618`. The result:

```
cat: /tmp/snapshot-enrich-prod-dryrun.rc: No such file or directory
ls: cannot access '/tmp/snapshot-enrich-prod-dryrun.*': No such file or directory
```

**Read literally, that says the run left nothing behind** — no report, no log,
no exit code, on a run that had just written all three. The correct reading is
that `/tmp` is per-machine and this was a different machine.

Every subsequent command in this session pins `--machine 825d69b7e46618`.
The durable rule: **a detached run and every read of its artifacts must name
the machine**, because the artifacts live on a filesystem that the app name
does not identify. Prior reports in this arc *record* which machine they ran
on (`ENRICH-PROD-REPORT-2.md` §8) but the launch recipe does not *pin* it, so
the guarantee has been luck. This is NORM-8's family — a killed client is not
a killed run — with the failure moved one step later: **a read on the wrong
machine is not an absent run.**

## 14. State left behind, and what the next session needs

* **Production is unchanged**, verified read-only at 08:04:57Z against the
  07:42:23Z baseline, every figure identical (§12). **The one authorized
  `--execute` is unspent.** No SQL beyond `SELECT`, and every probe ran under a
  proved read-only transaction.
* **On machine `825d69b7e46618`, `/tmp`:** `snapshot-enrich-prod-dryrun.{md,log,rc}`
  (all three retrieved and committed here) and three read-only probe scripts
  `probe_{pre,tok,post_dry}.py` with `probe_{pre,tok}.json`. Nothing else was
  created. No process is running — the dry run's pid 688 exited on its own at
  08:02:19Z.
* **The prediction is committed and unedited** (`82cbda9`), written while the
  dry run was in flight and before any of its output was read. Its dry-run half
  is scored in `PREDICTION-SNAPSHOT-ENRICH.md`; **the execute half is
  unscored** because the execute did not run.
* **What the dry run establishes, independent of the stop.** These are
  measurements of the production catalogue and they do not need re-taking:
  **0 403s and 0 404s over 5,387 catalogued ids** — NORM-23 confirmed in
  production, and the 404 gate has now met real data for the first time and
  found nothing; **0 capture-date disagreements over 5,387 items**;
  **1,111 of 1,111 sentinel-2 items still carry no item-level `gsd`**;
  **527 NAIP rewrites planned**, which is NORM-13's `scenes` arm sized exactly.
* **What unblocks item 5:** F2. Either the script's teardown is fixed,
  tested and deployed — and then the whole sequence re-runs from the dry run,
  since a re-run costs 18 minutes and buys a readable exit code — or the owner
  decides to spend the authorization on a run whose completion is verified by
  re-deriving the queue instead of by reading `.rc`, accepting that `--execute`
  will probably also exit 1 with every batch committed. **That is the owner's
  call, not this session's**, which is why this report stops here rather than
  choosing.
* **Step 4 is not started and is no closer.** The cooling period from
  t0 `2026-08-29T06:41:47.270470Z` is unaffected by a session that wrote
  nothing; both instruments named in `STEP3-PROD-REPORT.md` §7 still need their
  closing reading.
