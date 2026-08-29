# The snapshot-scene enrichment heal against PRODUCTION — STOPPED at gate 1

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
