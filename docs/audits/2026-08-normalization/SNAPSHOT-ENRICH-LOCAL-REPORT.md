# The snapshot-scene enrichment heal — built, and run against the LOCAL database

Session of 2026-08-29, 07:00–07:25Z. NORM-7's deferred footprint backlog,
NORM-13's `scenes` arm and NORM-18's item-fact refresh, as the one pass
`STEP3-PROD-REPORT.md` §10 scheduled ahead of step 4.

**Outcome. The local queue is empty. 1,031 of 1,031 rows healed, zero
unmatched, zero errors.** Every `provenance = 'snapshot'` scene that has a
Planetary Computer item now carries that item's real outline; 93 NAIP rows
moved off NORM-9's constant 1.0 onto the resolution their item states; and the
class NORM-18 named is closed at its exact witness — the four parcels serving
`md_m_3807708_se_18_030_20230901_20231018` now serve **0.3**, not `1m res`.

**One prediction was falsified, in the good direction. The six NAIP items the
geometry audit could not assess because the Planetary Computer answered 403 —
Appendix C, open since 2026-08-12 — all return 200 today.** That class is
empty. It was predicted to be both the floor and the ceiling of this run's
unmatched remainder; the remainder is zero.

**Production is untouched.** This session took no production access of any
kind — no `fly ssh`, no read, no write. The production run belongs to a later
session with its own prediction.

---

## 1. What was built

| Artefact | Commit |
|---|---|
| `scripts/shared/stac_fetch.py` — the extracted PC fetch layer | `65a6d3d` |
| `scripts/enrich_snapshot_scenes.py` — the pass | `24b7e48` |
| `backend/tests/test_enrich_snapshot_scenes.py` — 21 tests | `24b7e48` |
| `PREDICTION-SNAPSHOT-ENRICH.md` — committed before any run | `93ff05c` |

`enrich_synthesized_scenes.py` keeps its behaviour and its 17 tests pass
unmodified. The full backend suite is **732 passed, 7 skipped** in the
container and **734 passed, 5 skipped** in a CI-shaped layout (§6);
`make lint` is clean and `mypy app/` reports no issues.

## 2. Design decisions, and the arguments for them

### 2a. The provenance marker: `'snapshot'` stays, `footprint IS NOT NULL` is the done-marker

The prompt recommended keeping `'snapshot'` and invited the alternative to be
argued. **The recommendation is kept, and there are three independent reasons
rather than one.**

1. **`'snapshot'` is frozen vocabulary and it is still true.** Migration 0016's
   docstring and NORM-7's row both define it as "copied from an
   `imagery_snapshots` row". An enriched-in-place row *was* copied from one;
   filling in a column the source table never had does not change where the row
   came from. `'enriched'` means the opposite thing — "this row was never in
   `imagery_snapshots`" — so the relabel would be lossy in the direction that
   matters, exactly as `ENRICH-LOCAL-REPORT.md` argued for the mosaic rows in
   reverse.
2. **NORM-7's queue definition has to stay expressible**, and a provenance flip
   would destroy it: after the flip there would be no predicate that names
   "rows the backfill copied", so the *next* question about that population
   (there will be one — the topo rows are still unhealed, §2d) would have no
   way to ask itself.
3. **A column-state marker cannot drift from the thing it marks.** A
   `provenance` flag says "we believe this row is done"; `footprint IS NOT
   NULL` says "the footprint is there". If a write half-succeeds the second one
   is still right. This matters here because there *is* a case where the pass
   writes a row and deliberately leaves the footprint NULL (a non-Polygon
   geometry, §2c): that row must stay in the queue, and with a provenance flag
   it would not.

So the queue, in full, and re-derivable by anyone with no run state:

```sql
provenance = 'snapshot' AND footprint IS NULL AND source <> 'usgs_topo'
```

**The cost, stated:** a row whose item has a non-Polygon geometry can never
leave the queue, and every future run refetches it and rewrites the same
values. The population is 0 locally and the script reports each occurrence by
name, so the class is countable rather than silent. If production turns up a
nonzero count, the fix is a `scenes.footprint` type change, not a marker
change.

**No migration.** Nothing about this decision needs DDL.

### 2b. Batch size 200, and why not one transaction

Writes commit every 200 rows. The argument is three-sided:

* **Against one transaction over the whole queue:** ~6,156 production rows at
  the default pace is ~18 minutes of a transaction held open across an
  external HTTP call per row. Against pgbouncer and Neon that is an
  idle-in-transaction window long enough to be reaped, and a kill anywhere in
  it costs every fetch the run has made. NORM-8's lesson is that a killed
  client does not roll the remote process back; the shape that respects it is
  one where progress is already durable.
* **Against a much smaller batch:** a commit per row is ~6,156 transactions to
  save at most 0.2 s of rework.
* **For 200:** at the default 5 dispatches/second one batch is ~40 s of
  fetching, so a kill costs ≤40 s of work; the write transaction itself is
  open for well under a second; and the production queue becomes ~27 commits.
  Locally it made 6 batches, and the kill test cost exactly the in-flight
  batch (§4).

### 2c. Per-source resolution policy

The **write rule is uniform**: `normalize_resolution_m(item gsd)` is written
when the item speaks and disagrees with what is stored. Nothing is written when
the item is silent — **`None` never overwrites a value.**

A source-conditional *write* rule was considered and rejected: it would put
per-source resolution constants in a second place in the codebase, which is
NORM-9's original defect (`source_cfg["resolution_m"]` winning over the item).
"The item wins wherever it speaks" is the same rule
`SelectedScene.from_stac_item` already applies, so the heal and the write path
agree by construction.

What *is* per-source is the **reporting**, and that is where the prompt's
per-source requirement lands:

| Source | Item-level `gsd` | Policy | Local outcome |
|---|---|---|---|
| naip | yes, and it is the point | rewrite; counted, not flagged | **93 rewritten** (75 → 0.6, 15 → 0.3, 3 → 0.5) |
| landsat | yes, `30` | rewrite only on disagreement; **a disagreement is a reported finding** — 30.0 is a correct constant | **0 rewrites**, 618 agreed |
| sentinel2 | **no** — `properties.gsd` is absent; L2A carries `gsd` per asset | nothing written; the row is counted in a "no `gsd`" table | **0 rewrites**, **213 rows** counted |
| usgs_topo | n/a | **excluded from the queue** | 143 excluded |

The sentinel-2 fact was measured before the script was written, not assumed
(`PREDICTION-SNAPSHOT-ENRICH.md` §0.2). Without it the pass would have had a
plausible-looking branch that never fires and a report table that never fills.

`capture_date` is reported on disagreement and never written — the mosaic
pass's rule, kept.

### 2d. `usgs_topo` is excluded, and the count is stated

`stac_collection = 'usgs-historical-topo'` is not a Planetary Computer
collection: those scenes come from The National Map (the geometry audit's
premise correction #2). A GET against PC's item endpoint would 404 every one
of them for a reason that says nothing about the row, and 143 spurious
findings would bury six real ones.

**143 local rows excluded**, all with a NULL footprint. They are reported in
every run's header rather than left as a silent gap between "1,174 snapshot
rows" and "1,031 queued". **Topo footprints remain unhealed and this pass does
not heal them** — a TNM-sourced geometry backfill is separate work, and
STATUS.md now says so rather than letting the empty queue read as "every
snapshot row has a footprint".

### 2e. Lookup is a direct GET, and an unresolved id is a finding

No search fallback, no `cog_url` matching. These ids came from the pipeline's
own PC search results by way of `imagery_snapshots.stac_item_id`, not from
parsing a tile URL (NORM-4), so there is nothing for a search to correct. A
404 would mean *an id the pipeline once served that PC no longer resolves* —
a finding, reported per row, row untouched.

The prediction set the stop-and-think threshold before the run: more than 10
404s, or any 404 outside `sentinel-2-l2a`, stops the run. **0 occurred**, so
the gate was never tested against real data. It stands for the production run.

### 2f. The extraction, and the two traps it walked into

`StacLookup`, its constants and `_retry_after_seconds` moved to
`scripts/shared/stac_fetch.py`; the NORM-10 comment moved with the retry sets,
so the item-403/search-403 split now has one definition instead of two.
`enrich_synthesized_scenes.py` re-exports the four names its tests bind.

Two traps, both caught before commit and both worth recording because neither
is visible from a green local test run:

* **`scripts/lib/` would never have been committed.** `.gitignore` carries the
  Python-packaging boilerplate rule `lib/`, which matches at any depth. The
  module was staged, `git add` refused it, and the directory is now
  `scripts/shared/`. Had the rule been `/lib/` instead, the file would have
  been silently absent from the commit and from `Dockerfile.fly`'s
  `COPY scripts/`.
* **The import would have failed in CI.** See §6.

`scripts/shared/` is a directory rather than a `scripts/*.py` module because
`tests/test_script_logging.py`'s entry-point guard globs `scripts/*.py`
non-recursively. Nothing in `scripts/shared/` has a `main()`, and the module
docstring says so.

## 3. The runs

| Run | Mode | Started | Ended | Result |
|---|---|---|---|---|
| A | dry run | 07:11:33Z | 07:15:07Z (214 s) | 1,031 fetched, 1,031 would write, 0 unmatched, 0 errors |
| B | `--execute`, SIGKILLed | 07:15:34Z | 07:17:50Z | 600 committed, then killed mid-batch-4 |
| C | `--execute`, resumed | 07:18:14Z | 07:19:44Z (90 s) | 431 fetched, 431 written, queue 0 |
| D | dry run | 07:20Z | — | **0 fetched, 0 requests** |

Captures committed unedited: `snapshot-enrich-local-dryrun.md`,
`snapshot-enrich-local-killed.md`, `snapshot-enrich-local-resumed.md`.

**Before → after, `scenes`:**

| | before | after |
|---|---|---|
| `snapshot`, non-topo, NULL footprint | 1,031 | **0** |
| footprint geometry type | — | **1,031 × `ST_Polygon`** |
| footprints equal to their own `bbox` | — | **0** |
| `snapshot` naip `resolution_m` | 200 × 1.0 | **107 × 1.0, 75 × 0.6, 15 × 0.3, 3 × 0.5** |
| `snapshot` landsat / sentinel2 `resolution_m` | 618 × 30, 213 × 10 | **unchanged** |
| `snapshot` usgs_topo | 143, NULL footprint | **143, NULL footprint** |
| provenance counts (snapshot/enriched/selection) | 1,174 / 88 / 80 | **1,174 / 88 / 80** |
| `parcel_scenes` | 3,082, 0 dangling | **3,082, 0 dangling** |

**The footprints are outlines, not envelopes.** Zero of the 1,031 written
footprints are `ST_Equals` to the row's own `bbox`, and 69 sentinel-2 outlines
have more than five vertices. That is the geometry audit's whole distinction,
measured on the result rather than asserted from the code.

**NORM-18's witness, closed.** `md_m_3807708_se_18_030_20230901_20231018` now
carries 0.3 and all four parcels serving it read 0.3. Across the local
database **139 served NAIP rows** moved off the 1.0 chip
(`frontend/src/components/MapView.tsx:298-301`) to a true value; 177 stay at
1.0 because 1.0 is what their items say.

## 4. The kill-and-resume, exercised for real

The run is ~3.5 minutes at the default pace, which is long enough to interrupt
honestly, so it was — `SIGKILL` to every process whose `cmdline` matched the
script, at 07:17:50Z, with three batches committed and batch 4 in flight.

| Check | Value |
|---|---|
| Committed by B | **600** rows (3 × 200, all `landsat-c2-l2`) |
| Queue immediately after the kill | **431** = 1,031 − 600 |
| — composition | 18 landsat + 200 naip + 213 sentinel2 |
| B's report on disk after the kill | present, marked **"Incomplete"**, totals 600 |
| C's re-derived queue | **431** |
| C fetched | **431** |
| Rows written twice | **0** |
| Queue after C | **0** |

The in-flight batch rolled back whole — 600 healed, not 600-and-some. The
unit test `test_a_killed_run_does_not_refetch_committed_rows` carries the same
property against a fake catalogue; this is the live reading of it.

**The exit code survived the detached launch.** Run C was launched with
`STEP3-PROD-REPORT.md` F3's prescribed recipe —

```sh
setsid nohup sh -c "python scripts/enrich_snapshot_scenes.py \
  --report /tmp/snapshot-enrich-C.md --execute \
  > /tmp/snapshot-enrich-C.log 2>&1; echo \$? > /tmp/snapshot-enrich-C.rc" \
  < /dev/null > /dev/null 2>&1 &
```

— and `/tmp/snapshot-enrich-C.rc` contains `0`. **This is the first exit
status this arc has read rather than inferred** (PP14 was scored *unobserved*
in the step-3 production run for exactly the missing line). Run B has no `.rc`
because the deliberate kill killed the wrapping `sh -c` too, which is a
harder kill than the client timeout the recipe defends against.

## 5. Findings

### F1 — Appendix C's HTTP 403 class is empty. The six forbidden NAIP items now resolve

**New. Not a defect; an upstream state change, and it falsifies a committed
prediction.**

`../2026-08-geometry-audit/FINDINGS.md` Appendix C recorded **17 rows across 6
distinct NAIP items, years 2012–2021, unassessable because the Planetary
Computer answered HTTP 403.** They were counted as unassessed, not as passes.
The class has been quoted since as the floor of every subsequent pass's
unmatched remainder, and `PREDICTION-SNAPSHOT-ENRICH.md` P3 predicted it would
also be the ceiling here.

**All six returned 200.** The dry run resolved 1,031 of 1,031 with zero 403s,
and three of the six were then probed directly with `curl`
(`ut_m_4011118_sw_12_1_20160627_20161017`,
`va_m_3807708_se_18_1_20120511_20120709`,
`ut_m_4011125_sw_12_060_20211105`) — 200 each. All six now carry a real
`ST_Polygon` footprint in `scenes`, and the two whose filename token is `060`
were corrected from 1.0 to 0.6.

**What this does and does not establish.** It establishes that the access
restriction was transient or has been lifted, and that those six items are
assessable today. It does **not** re-run the geometry audit: whether those
items' footprints actually cover the parcels serving them is a separate
question, still unanswered. It is now answerable by a query over `scenes`
rather than a refetch, which is ADR rule 4's promise arriving — for the
non-topo `snapshot` population, locally.

**Second-order consequence worth naming:** every prediction in this repo that
cites "the six forbidden items" as a known floor is now citing a class of size
zero. `enrich_synthesized_scenes.py`'s item-403 fall-through branch — recorded
in NORM-7 as *never exercised live, 0 occurrences across 88 local + 1,515
production resolutions* — has still never fired, and now has one fewer
population that could ever fire it.

### F2 — a shared module under `scripts/` is invisible to CI's import path, and green locally either way

**New. Resolved in the same batch (`65a6d3d`). Method finding, and it
generalises past this script.**

`scripts/` is a **sibling** of `backend/`, not a child. In the container that
distinction does not exist — `PYTHONPATH=/app` and `docker-compose.yml` mounts
`./scripts` at `/app/scripts`, so `import scripts.shared.stac_fetch` resolves.
**CI runs `cd backend && uv run pytest`**, where the repo root is one level up
and on nobody's path, so the two enrichment script tests fail *at collection*
with `ModuleNotFoundError: No module named 'scripts.shared'`.

Every local signal was green: the full suite in the container, `make lint`,
`mypy`. The failure is only visible in a layout no local command produces.

Verified in both directions against a clean `git ls-files` export run with
`PYTHONPATH` unset from `/repo/backend`: **734 passed** with the fix,
**2 collection errors** without it. The fix is four lines in
`backend/tests/conftest.py` putting the repo root on `sys.path` when it is not
already there, keyed on `scripts/seed.py` existing — a file, not the
directory, because a stray empty root-owned `backend/scripts/` mountpoint
exists on this machine and a directory test would have matched it.

**This is NORM-21's shape one layer down.** NORM-21 was "a commit prescribed
for deployment was never tested at that commit"; this is "a code path was
never tested in the environment that runs it". The durable rule: *a change to
how a script resolves its imports has to be exercised in CI's layout, not only
in the container's, and the two are not the same filesystem.*

### F3 — `.gitignore`'s `lib/` rule silently claims `scripts/lib/`

**New. Resolved in the same batch (`65a6d3d`) by not using the name. Minor,
and the near-miss is the point.**

The shared module was first written to `scripts/lib/stac_fetch.py`. `git add`
refused it: `.gitignore` line 13 is the Python-packaging boilerplate `lib/`,
which matches at **any** depth, not just the repo root. The refusal was loud
because `git add` names the path explicitly — but `git add -A` or `git commit
-a` would have been silent, and the result would have been a commit whose
tests pass locally, whose CI fails on import, and whose deployed image is
missing a file `Dockerfile.fly`'s `COPY scripts/ /app/scripts/` would
otherwise have carried.

Recorded rather than fixed: narrowing the rule to `/lib/` is a change to a
shared ignore file for one directory's benefit, and `scripts/shared/` costs
nothing.

### F4 — the topo footprint backlog is now the whole of what NORM-7 has left

**Not new; sharpened.** 143 local `usgs_topo` `snapshot` rows still have a
NULL `footprint` and a NULL `resolution_m`, and this pass cannot fill them:
`usgs-historical-topo` is TNM-sourced and has no PC item. Five
`selection`-provenance topo rows are in the same state.

**This matters for how "the queue is empty" is read.** After this pass ADR
rule 4 — "the next geometry audit is a query over `scenes`" — is true for
naip, landsat and sentinel2, and **still false for usgs_topo**. Filling those
footprints needs a TNM-sourced geometry pass, which is separate work and does
not exist. STATUS.md records it as the remaining half rather than letting an
empty queue imply a complete table.

## 6. Verification

| Check | Result |
|---|---|
| Backend suite, container | **732 passed, 7 skipped** |
| Backend suite, CI-shaped clean export (`PYTHONPATH` unset, run from `/repo/backend`) | **734 passed, 5 skipped** |
| `make lint` (ruff check, ruff format, mypy) | clean |
| `ruff check` / `format --check` on the three script files | clean |
| `enrich_synthesized_scenes.py`'s own 17 tests, unmodified | **pass** |
| Delete-the-fix: 11 clauses removed one at a time, each named test | **11 red, 11 of 11** |
| Re-run over the finished queue | **0 rows, 0 STAC requests** |

The delete-the-fix pass was mechanical rather than argued: each clause named in
the test module's docstring was removed from the script, the named test was
run, and the result recorded. The first attempt scored one clause GREEN — the
mutation had replaced the queue definition in the *module docstring* instead of
the SQL, because the same text appears in both. That is itself the standard
working: a mutation that does not change behaviour must not be reported as
evidence.

## 7. Deviations from the prompt

1. **`scripts/shared/`, not `scripts/lib/`.** F3. `.gitignore` claims the
   latter.
2. **`backend/tests/conftest.py` was modified**, which the prompt did not
   anticipate. F2: without it the extraction fails in CI. It adds a `sys.path`
   entry and asserts nothing, so `enrich_synthesized_scenes.py`'s tests still
   pass unmodified in what they assert.
3. **The report is rewritten after every batch**, not only at the end. The
   prompt required report-to-file (F5/NORM-8); this goes further so a killed
   run leaves a partial capture rather than nothing. `snapshot-enrich-local-
   killed.md` is that capture, and it is marked **"Incomplete"** in its own
   header so it cannot be mistaken for a finished run.
4. **The kill test used `SIGKILL` on the process, not a client timeout.** A
   harder kill than the failure mode NORM-8 describes, chosen because it is
   the one this session could produce deterministically. Its cost is that run
   B has no `.rc` file; run C's reading is unaffected.
5. **The prompt's phrasing "landsat/sentinel2 write it only if the normalized
   value differs from stored" is implemented as a uniform rule with per-source
   reporting** (§2c). The behaviour is identical to a source-conditional
   write; the reasoning for not conditioning the *write* is that it would
   re-create NORM-9's defect.
6. **No ADR amendment.** No design requirement was beaten with reasoning, so
   nothing in `docs/adr/0001-imagery-normalization.md` changes. Rule 4's
   promise is now true of the non-topo local `snapshot` population, which is a
   fact for STATUS.md, not a change to the decision.

## 8. State left behind

* **The local database's non-topo `snapshot` footprint backlog is zero.**
  1,031 rows, all `ST_Polygon`, none equal to their own bbox.
* **NORM-13's local `scenes` arm is healed**: 93 of 200 NAIP `snapshot` rows
  moved off 1.0; the other 107 are correctly 1.0.
* **NORM-18's local divergence class is closed at its witness**, and 139
  served NAIP rows now show a true resolution.
* **`imagery_snapshots` was not touched.** NORM-13's *other* arm — 1,305
  production NAIP `imagery_snapshots` rows at 1.0, and their local equivalent
  — is unchanged, and this pass has no opinion about it. After step 4 that
  table is gone and the question is moot; until then the two tables now
  **disagree**, measured: **93 distinct `scenes` rows spanning 136
  `imagery_snapshots` rows** hold different NAIP resolutions, with `scenes`
  holding the true value and being the one that serves. (317 of the 323 local
  NAIP `imagery_snapshots` rows still say 1.0.) That disagreement is NORM-13's
  unhealed arm made visible, not a new defect — and it is only observable
  because the heal ran on one side.
* **usgs_topo footprints are still NULL** (143 `snapshot` + 5 `selection`),
  and no mechanism exists to fill them. F4.
* **Production is untouched and unmeasured by this session.** The production
  queue size, its topo count and its 404/403 populations are all unknown here.
  The production run needs its own prediction, and P3's falsification means
  the Appendix C floor cannot be carried into it.
* **Nothing is pushed.** Four commits on `main`, local only: `65a6d3d`,
  `24b7e48`, `93ff05c`, and this batch's record commit.
