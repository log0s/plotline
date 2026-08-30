# Step 4 deploy-1 — deployed, gated, swept in production

Session of 2026-08-29, **unattended**. ADR 0001 step 4's *first* deploy — the
code cutover — reached production, was verified at artifact level, and was
exercised by a staged 189-parcel fleet sweep. **The cooling span for
migration 0019 opens here.**

**Migration 0019, the DROP, is NOT deployed and was not run.** It stays local,
committed and unpushed. Nothing in this session pushed, deployed, or dropped
anything.

* **What deployed:** `03867c4` as a **prefix push** (`git push origin
  03867c4:main`), carrying the cutover `329a8a6`, the attributed probe helper
  `41f7e76`, and migration 0018's footprint CHECK `03867c4`.
* **What deliberately did not:** migration 0019 (`cb088f8`) and every record
  commit after it.
* **Production writes made:** exactly two, both
  `scripts/requeue_parcels.py --require-sha 03867c4` — a 30-parcel pilot and
  the 159-parcel remainder. Everything else in this session ran inside a
  transaction opened `SET TRANSACTION READ ONLY`, with the
  `UPDATE … WHERE false` proof executed **inside that same transaction** on a
  savepoint.

---

## 1. The deploy, and the six gates it had to pass

CI had already finished when the session opened: the first `/api/v1/health`
poll at **23:05:09Z** returned the target SHA, so item 0's 30-minute budget was
never drawn on.

| | gate | evidence | verdict |
|---|---|---|---|
| **1a** | health SHA and `GH_SHA` on every machine of both apps | `/api/v1/health` → `{"version":{"sha":"03867c4b1e531b461665d41cab7b8a8f4196c60d","built":"2026-08-29T23:04:25Z"}}`; `fly image show` labels `GH_SHA=03867c4b1e53…` on **all four** machines — API `825d69b7e46618`, `48e0de9a713918`; worker `e2862966b306d8` and the standby `e7845415f57728` | **PASS** |
| **1b** | `alembic_version` is 0018's *actual* revision id, read from the migration file (`Revision ID: 0018`), not 0019's | `SELECT version_num FROM alembic_version` → **`0018`** | **PASS** |
| **1c** | the CHECK is really there — verify the constraint, not the version row | `pg_constraint` on `public.scenes` → `ck_scenes_footprint_valid`, `CHECK (((footprint IS NULL) OR st_isvalid(footprint)))`, **`convalidated = true`** | **PASS** |
| **1d** | `imagery_snapshots` **exists** with ~12,884 rows — the gate that proves the prefix push worked and the drop did not ship | `to_regclass('public.imagery_snapshots')` → `imagery_snapshots`; `count(*)` = **12,884**; **13** columns | **PASS** |
| **1e** | process starts postdate the deploy (NORM-32: verify the restart, never assume it) | image built **23:04:25Z**; API machines booted **23:04:56Z** and **23:05:14Z**, worker **23:05:09Z**, read from `/proc/uptime` and `/proc/1` on each machine; worker process env `GIT_SHA=03867c4b1e53…` | **PASS** |
| **1f** | the deployed image contains the cutover — spot-verify the artifact, not the repo | see §1.1 | **PASS** |

Every `fly ssh console` in this session pinned `--machine` (NORM-28), including
every read of every artifact.

### 1.1 Gate 1f in full — what the deployed image actually contains

A scan of `app/` and `scripts/` **inside the running worker image**:

```
== token hits in the DEPLOYED image ==
  imagery_snapshots          -> ['scripts/snapshot_reads.py']
  upsert_imagery_snapshot    -> ['app/services/imagery.py', 'app/services/year_ledger.py', 'app/tasks/timeline.py']
  ImagerySnapshot            -> ['app/api/v1/imagery.py', 'app/schemas/imagery.py']
```

* **The table name appears in exactly one deployed file**, `snapshot_reads.py`
  — the one principled allowlist entry, where the name is a value in a
  `relname IN (…)` filter against `pg_stat_user_tables` and never a table
  reference. That is `tests/test_no_imagery_snapshots_references.py`'s pin,
  holding in the artifact rather than in the repo.
* **All three `upsert_imagery_snapshot` hits are prose**, printed with their
  lines: `app/services/imagery.py:1556`, `app/services/year_ledger.py:183`,
  `app/tasks/timeline.py:710` — three comments recording the history of the
  atomicity gap. No `def`, no call.
* **Both `ImagerySnapshot` hits are the API response model**
  (`ImagerySnapshotResponse`), named for the domain concept the endpoint still
  serves. `app/models/parcels.py` has **zero** hits: the ORM model is gone.
* **The reconciler diffs `parcel_scenes`.** Inside
  `reconcile_source_snapshots`' 195-line body, the only table reference is
  `" FROM parcel_scenes ps JOIN scenes s ON s.id = ps.scene_id"`.

**Stronger than a grep: the deployed files are byte-identical to the repo.**
sha256 over the image's copies matches the local worktree exactly —
`app/services/imagery.py` `a70ef9114b11d517`, `app/tasks/timeline.py`
`ad49522a77552e64`, `app/models/parcels.py` `c99fa10263e85c89`,
`app/services/year_ledger.py` `282899be8027a81d`,
`scripts/requeue_parcels.py` `1542779a92a8841a`,
`scripts/snapshot_reads.py` `f6c288f43c1e5852`,
`scripts/shared/probe.py` `1582c2848493fc70`. And
`git diff --stat 03867c4 HEAD -- backend/app scripts` reports one file changed,
so the worktree's `app/` and `scripts/` *are* `03867c4`'s except for the
addition in F-PROD-1 below.

---

## 2. Baseline — cooling **t0**

**t0 = 2026-08-29T23:11:57.497954Z** (`step4-prod-reads-t0.json`).

| table | seq_scan | seq_tup_read | idx_scan | idx_tup_fetch | ins / upd / del | n_live_tup |
|---|---|---|---|---|---|---|
| `imagery_snapshots` | 3,945 | 30,606,005 | 158,669 | 1,238,541 | 15,492 / 61,406 / 2,608 | 12,884 |
| `parcel_scenes` | 158 | 1,648,887 | 59,132 | 101,734 | 12,884 / 7 / 0 | 12,884 |
| `scenes` | 217 | 1,272,497 | 142,679 | 538,102 | 6,663 / 5,894 / 0 | 6,663 |

**Invariants** (`step4-prod-battery-t0.json`, 23:12:47Z): parcels **189**,
scenes **6,663**, parcel_scenes **12,884**; **7 of 7** zero-checks at **0**;
provenance snapshot **6,156** · enriched **505** · selection **2**; landsat
**43 on all 189 parcels, 8,127 rows**; ledger last-24h **14,770 rows, 0
`failed`**; requests complete 1,299 / failed 3 / partial 40, **none in
flight**.

**Reconciled against the last recorded state and it moved by nothing.** Every
total and the whole provenance split are **identical** to
`NORM31-PROD-REPORT.md` P15 (2026-08-29T20:39Z). There was no dual-write
traffic to explain, because there was no traffic: `imagery_snapshots`
`idx_scan` sat at **158,669** unmoved since the 06:41Z reading, sixteen hours
in which nothing exercised the imagery pipeline.

### 2.1 The one counter movement since 20:39Z, fully attributed

| table | Δ seq_scan | Δ seq_tup_read | reading |
|---|---|---|---|
| `imagery_snapshots` | **+1** | **+12,884** = 1 × 12,884 | this session's gate-1d `probe_count`, `audit_probe` logged 23:11:07Z |
| `parcel_scenes` | **+1** | **+12,884** = 1 × 12,884 | this session's gate context probe |
| `scenes` | **+2** | **+13,326** = 2 × 6,663 | one is this session's context probe; the other is **migration 0018 validating its CHECK against all 6,663 rows during the deploy** |

`imagery_snapshots` `idx_scan`, `idx_tup_fetch` and all three row counters were
**+0** across the deploy itself.

**That second `scenes` scan is worth naming rather than absorbing.** A
validating CHECK constraint costs exactly one whole-table scan, and one is
exactly what the counters show. It is independent evidence — from PostgreSQL's
own statistics rather than from `alembic_version` — that 0018 really ran and
really validated, which is the failure the migration-lock incident taught us
to check for.

---

## 3. The prediction, committed blind

`1e8f133`, appended to `PREDICTION-STEP4.md` as the **Production** half. It was
written and committed **before `scripts/requeue_parcels.py` was invoked against
production in any mode, including `--dry-run`**, and neither half has been
edited since. The local Observed half above it is untouched.

Its load-bearing line, P1, is stated with the subtraction enumerated in
advance: this session issues **zero** probes against `imagery_snapshots`
between t0 and the closing reading, so the predicted delta is `+0` **raw**,
with nothing to subtract. The magnitude it is measured against is derived, not
asserted — the local old-code control moved 1.06 `idx_scan` and 1.00
`n_tup_upd` per group, so step-3 code over production's 12,884 groups would
have moved roughly **13,700** and **12,900**.

---

## 4. Stage 1 — the 30-parcel pilot

**The same 30 parcels as step 2's pilot** (`prod-step2-pilot-set.txt`), so the
two are directly comparable; every parcel the ledger marks difficult is in it.

A dry run preceded it and passed the gate — `Deploy gate passed — prod is
running 03867c4b1e531b461665d41cab7b8a8f4196c60d.`, 30 parcels listed, 0
unknown ids. `--require-sha 03867c4`, never `--skip-deploy-check`: this is the
case the gate exists for, and NORM-32 is the reason it was not waived.

Launched **detached** from `825d69b7e46618` with output to an on-machine file
and its exit code written to a file, per NORM-8:

```sh
setsid nohup sh -c 'python scripts/requeue_parcels.py --require-sha 03867c4 \
  --sources naip,landsat,sentinel2,usgs_topo <30 ids> \
  > /tmp/step4-prod-pilot.log 2>&1; echo $? > /tmp/step4-prod-pilot.rc' \
  < /dev/null > /dev/null 2>&1 &
```

Launched **23:18:08Z**, `bg-pid=669`. Enqueue finished **23:24:02Z** (5.9 min,
admission-capped at `cap=25 depth=25`, polled rather than refused). Queue
drained to **0 in flight at 23:30:09Z**.

**`.rc` read, never inferred:** `cat /tmp/step4-prod-pilot.rc` → **`0`**.
`Done — queued 30 timeline request(s), skipped 0.` 30 `queued` lines, 0
unreached.

### 4.1 The battery — every item clean

**Counters, t0 → t1 (23:30:22Z, `step4-prod-reads-t1.json`):**

```
imagery_snapshots
  seq_scan  +0   seq_tup_read  +0   idx_scan  +0   idx_tup_fetch  +0
  n_tup_ins +0   n_tup_upd     +0   n_tup_del +0   n_live_tup     +0
parcel_scenes   idx_scan +2,557   idx_tup_fetch +4,191   ins/upd/del +0/+0/+0
scenes          idx_scan +7,239   idx_tup_fetch +12,301  ins/upd/del +0/+0/+0
```

**P1 holds and its control holds with it.** `imagery_snapshots` is `+0` on all
seven while the normalized tables took **2,557** and **7,239** index scans in
the same window. The pilot was not an idle window.

**The `seq_scan` movement in that window is this session's own battery, and it
divides exactly.** `parcel_scenes` `+7` scans / `+90,188` tuples = 7 × 12,884;
`scenes` `+6` / `+39,978` = 6 × 6,663. The t0 battery ran *after* the t0
counter reading, so its probes fall inside this delta: six `parcel_scenes`
whole-table probes (fleet total, four zero-checks, landsat-per-parcel) and five
`scenes` probes (fleet total, three zero-checks, provenance), each preceded by
an `audit_probe` event. Whole scans, not partial ones — the same divisibility
argument §6c had to make, except here each scan also has an event naming it.

**NORM-14, measured in production.** `timeline_task_years.created_at` defaults
to `now()` = transaction start time, so distinct values among one task's `ok`
rows counts the transactions that wrote them:

| | |
|---|---|
| tasks in the window | **120** (30 parcels × 4 sources) |
| tasks with at least one `ok` row | **120** |
| total `ok` rows | **2,071** |
| distinct-`created_at` histogram | **`{1: 120}`** |
| violations | **none** |

Per source, `max_distinct` is **1** for all four: landsat 30 tasks / 1,286 `ok`
rows, naip 30 / 227, sentinel2 30 / 357, usgs_topo 30 / 201. **A Landsat task
writes ~43 `ok` rows in one transaction.** Under the pre-step-4 code the same
task wrote 43.

**Parity** (`step4-prod-battery-t1.json`, 23:32:57Z): **7 of 7** zero-checks at
**0**; totals unchanged at 189 / 6,663 / 12,884; provenance unchanged at
6,156 / 505 / 2; **landsat 43 on all 189 parcels**, min 43, max 43, 8,127 rows.

**Hygiene:** 30 / 30 requests `complete`, **120 / 120** tasks `complete`, none
in flight; the fleet's historical 3 `failed` / 40 `partial` requests unmoved.

### 4.2 Every ledger outcome in the pilot window, explained

2,363 rows: landsat ok 1,286 / failed 4; naip ok 227 / absent 270 /
indeterminate 7 / suppressed 6; sentinel2 ok 357 / absent 3; usgs_topo ok 201 /
indeterminate 2.

* **The 4 `landsat/failed`** are all `stac_403` from Planetary Computer, on two
  parcels (`1074e64b` years 2010 and 2012, `11b0f0c1` years 2007 and 2009).
  Upstream rate-limiting, the NORM-10 class. No failure names a missing table,
  a missing function, or a constraint violation, and **no ledger row in the
  window mentions the retired table at all** (`ILIKE '%imagery_snapshot%'` → 0).
* **The hard clause holds, and holds in the strongest available form.**
  `naip/indeterminate` **7** and `usgs_topo/indeterminate` **2** are not a
  rise: they are the *same* markers on the *same three parcels* step 2 recorded
  (`fe065e2d` naip ×7, `9c35ceb0` and `e513188c` topo ×1 each — STATUS.md
  NORM-3's "NAIP item cap ×7, TNM row cap ×2 on three parcels deliberately
  included in the pilot"). Both reasons name their site explicitly: *"naip
  search hit its item cap"*, *"TNM response hit its row cap"*.
* **The persist loop's own silent-drop reason appears zero times.** A first
  query matched 7 rows on the pattern `_search_and_persist_source` — but the
  NAIP item-cap reason *contains* that function name, so the pattern was too
  broad. The exact predicate, `'%with no outcome%'`, returns **0**, and the 7
  decompose entirely to `naip/indeterminate` item-cap markers. Recorded rather
  than quietly fixed, because a too-broad pattern that happens to hit a benign
  population is how a real silent drop would be swallowed.

### 4.3 The pilot's write arms were inert — and that was predicted, not excused

`parcel_scenes` rows written in the window: **0**. `scenes` rows fetched in the
window: **0**. `scenes` with `provenance = 'selection'`: still exactly the
**two** rows step 2's sweep wrote at 04:29:19Z and 04:41:26Z, neither new. The
reconciler's `Replaced superseded served scenes` event — which
`app/services/imagery.py:186-190` emits only when `superseded > 0` — appears
**zero** times in the captured worker log.

**P3f predicted exactly this, in advance and with its decision rule attached.**
The same 30 parcels wrote nothing at all in step 2's sweep, and NORM-12 states
the lesson: *"a pilot proves a write path only if it writes."* So the pilot was
gated on what it *can* discharge — the read path at scale (P2a), NORM-14
(P5), parity (P6), hygiene (P8) — all of which it passed, and **the write-arm
question moved to the fleet, where the remaining 159 parcels are the
widening**. Passing a write-path gate on an absence is the mistake NORM-17
exists to prevent, and it was not made here.

---

## 5. Stage 2 — the 159-parcel remainder, and the fleet result

The 159 ids were derived as *all 189 parcels minus the 30 pilot ids*, verified
by three checks before launch: 189 total, 159 remainder, **0 overlap** with the
pilot, and all 30 pilot ids present in the fleet list. The list was written to
the machine and its **sha256 verified equal** on both sides
(`2944bb70c53983bc…`) before anything ran. A dry run passed the gate and listed
exactly 159 parcels with 0 unknown ids.

Same detached recipe, same machine, `$(cat /tmp/step4-remainder-ids.txt)` in
place of the inline list. Launched **23:34:45Z**, `bg-pid=725`. Enqueue ran
**33 minutes** — the admission cap polling for slots, exactly as it did for step
2's 38.5 minutes — and the queue was **0 in flight at 00:13:57Z**.

**`.rc` read, never inferred:** `0`. `Done — queued 159 timeline request(s),
skipped 0.` 159 `queued` lines, 0 unreached.

### 5.1 The fleet reading — this is the sweep window's closing bracket

**t2 = 2026-08-30T00:14:31.842120Z**, differenced against t0:

| table | seq_scan | seq_tup_read | idx_scan | idx_tup_fetch | ins | upd | del | n_live_tup |
|---|---|---|---|---|---|---|---|---|
| **`imagery_snapshots`** | **+0** | **+0** | **+0** | **+0** | **+0** | **+0** | **+0** | **+0** |
| `parcel_scenes` | +16 | +206,144 | **+15,925** | +26,356 | +0 | **+1** | +0 | +0 |
| `scenes` | +16 | +106,608 | **+42,614** | +51,705 | **+1** | +0 | +0 | +1 |

**The load-bearing result: `imagery_snapshots` took zero reads and zero writes
of every kind while 12,884 groups went through the pipeline and the normalized
tables took 58,539 index scans between them.**

### 5.2 Parity and the ledger, fleet-wide

`step4-prod-battery-t2.json` (00:15:06Z) and `step4-prod-sweep-fleet.json`
(00:15:29Z):

* **7 of 7 zero-checks at 0.** `invalid_footprints` included, which is 0018's
  CHECK expressed as a query — the constraint and the count agree.
* **Landsat conserved per parcel:** 189 parcels, **min 43, max 43**, 8,127 rows.
* **Totals** 189 / **6,664** / 12,884; **provenance** `snapshot` 6,156
  (unmoved), `enriched` 505 (unmoved), `selection` 2 → **3**, `mosaic_url` 0.
* **189 requests `complete`, 756 tasks `complete`**, none in flight; the fleet's
  historical 3 `failed` / 40 `partial` requests unmoved.
* **Ledger window: 14,803 rows.** landsat ok 8,123 / failed 4; naip ok 1,305 /
  absent 1,892 / indeterminate 7 / suppressed 9; sentinel2 ok 2,259 / absent 9;
  usgs_topo ok 1,193 / indeterminate 2.

**It reconciles to the row.** 12,880 `ok` + 4 `failed` = **12,884** — exactly
the `parcel_scenes` count. The four failures (`1074e64b` 2010, 2012;
`11b0f0c1` 2007, 2009; all `stac_403`, all from the *pilot* stage — the
remainder produced zero) **kept their served rows**, which is the absent-group
rule refusing to convert a transient upstream error into permanent data loss,
visible in production data rather than argued from a docstring.

**The hard clause held fleet-wide.** `naip/indeterminate` **7** and
`usgs_topo/indeterminate` **2** — unchanged from baseline, on the same three
parcels step 2 recorded, from two sites that name themselves ("naip search hit
its item cap", "TNM response hit its row cap"). The persist loop's own
silent-drop reason appears **0** times, and **no** ledger row and **none** of
3,335 worker-log lines mention the retired table.

### 5.3 NORM-14 in production, at fleet scale

| | |
|---|---|
| tasks in the window | **756** (189 parcels × 4 sources) |
| tasks with at least one `ok` row | **756** |
| total `ok` rows | **12,880** |
| distinct-`created_at` histogram | **`{1: 756}`** |
| `max_distinct` per source | landsat **1**, naip **1**, sentinel2 **1**, usgs_topo **1** |
| violations | **none** |

`created_at` defaults to `now()`, which is transaction start time, so this
counts transactions. **A Landsat task writes ~43 `ok` rows in one transaction;
under the pre-step-4 code it wrote 43 transactions.** Fleet-wide, **8,123
Landsat commits became 189**.

This is the measurement the local run made on 6 tasks, made on 756 in
production. NORM-14's accepted atomicity gap is closed in the running system,
not only in the diff.

### 5.4 The single write, in full — the first production run of the new arm

One group changed out of 12,884. The worker log, captured continuously from
before the pilot, names it at **23:57:56Z**:

```json
{"event": "Replaced superseded served scenes", "logger": "app.services.imagery",
 "parcel_id": "b4838b92-f07c-4ee0-8e2e-e830029fe9a9", "source": "sentinel2",
 "replaced": 1, "suppressed_deleted": 0, "scope": "year",
 "groups": ["2015", "…", "2026"]}
```

* **`replaced: 1`** — the superseding-**upsert** arm, which step 4 substituted
  for the old DELETE-and-insert. **Its first execution in production.**
* **`suppressed_deleted: 0`** — the one remaining delete path did not run.
* The counters agree exactly: `parcel_scenes.n_tup_upd` **+1**, `n_tup_del`
  **+0**, `scenes.n_tup_ins` **+1**.
* The new scene is `S2C_MSIL2A_20260828T183921_R070_T11TMM_20260828T233712`
  (`sentinel-2-l2a`, captured 2026-08-28), referenced at `group_key` **`2026`**
  — **recency, and the decomposition predicted 100% recency**. Zero
  historic-period inserts.
* The `parcel_scenes` row carries `selected_by =
  03867c4b1e531b461665d41cab7b8a8f4196c60d`: the deployed SHA, written by the
  code the gate verified.

### 5.5 NORM-17 updated — what this sweep actually exercised

| arm | predicted | **observed** |
|---|---|---|
| `reconcile_source_snapshots` invocations, one transaction each | 756 | **756** |
| `_upsert_parcel_scene` exercises (one per `ok` group) | 12,700–12,950 | **12,880** |
| …of which the `unchanged` early return | ≥ 12,700 | **12,879** (99.992%) |
| …of which the superseding **upsert** arm | 0–40 | **1** |
| `_ensure_scene` INSERT arm | 0–25 | **1** |
| suppressed-delete arm | 0 | **0** |

**What this sweep may be cited for:** the reconciler's `parcel_scenes ⋈ scenes`
diff and the single-transaction commit ran **756 times over 12,884 groups**.
That is the first fleet-scale exercise of either, because step 2's sweep ran the
*old* reconciler against `imagery_snapshots`.

**What it may not be cited for:** insert-path evidence. The INSERT arm ran
**once** and the superseding-upsert arm ran **once**. NORM-17's original point
survives intact one migration later — "deployed and swept" is not the same
sentence as "the write path is exercised", and the correctness of those two arms
still rests on `backend/tests/test_scene_dual_write.py` and on the local probe
parcels, exactly as it did before this deploy.

### 5.6 The `seq_scan` movement, attributed by measurement rather than divisibility

§6d.4 asks that a `seq_scan` delta be *attributed*, not explained. So the cost
of the instrument was measured directly: an **isolated battery run**, bracketed
by two counter readings with no sweep and nothing else in the window, costs
**`parcel_scenes` +7** (90,188 = 7 × 12,884) and **`scenes` +6** (39,984 = 6 ×
6,664) whole-table scans — and **`imagery_snapshots` +0**.

| window | contents | `parcel_scenes` | `scenes` | residue after instruments |
|---|---|---|---|---|
| t0 → t1 | battery + **pilot sweep** | +7 | +6 | **0** and **0** |
| t1 → t2 | 2 probes + battery + **remainder sweep** | +9 | +10 | **1** and **2** |
| t2 → t3 | 2 probes + battery, **no sweep** | +8 | +8 | — (this is the probe baseline) |

**The 189-parcel sweep's own sequential-scan footprint on the live serving
tables is 1 and 2 — and on the retired table it is 0.** Every scan in the table
above is either matched by an `audit_probe` event this session emitted or falls
in that residue, which is the same planner-behaviour class the local run
recorded as `scenes.seq_scan +43`, at a far smaller magnitude here.

That last measurement is also the control on P1's subtraction: the enumerated
probe set against `imagery_snapshots` between t0 and t2 was declared empty in
advance, and the isolated battery run shows it **is** empty — the battery moves
the retired table's counters by nothing at all.

---

## 6. Cooling — the span's opening bracket

| | |
|---|---|
| **t0** | **2026-08-29T23:11:57.497954Z** (`step4-prod-reads-t0.json`) |
| **closing bracket of the sweep window** | **2026-08-30T00:14:31.842120Z** (`step4-prod-reads-t2.json`) |
| `imagery_snapshots` delta over the bracket | **+0 on all seven counters**, `n_live_tup` +0 at 12,884 |
| attributed probe scans to subtract | **none — the enumerated set is empty, and measured empty** |
| arithmetic | `0 − 0 = 0` |
| traffic inside the bracket | **189 parcels, 756 tasks, 12,884 groups, 14,803 ledger rows** |

**The span is RUNNING from t0 with a 189-parcel fleet sweep already inside it.**
That is deploy-2 condition 2's "real fleet traffic" requirement satisfied on the
span's first hour rather than at the end, which means the remaining wait is for
elapsed time and ordinary serving traffic, not for another sweep.

Deploy-2's gate, restated against what this session produced:

| condition | state |
|---|---|
| 1. deploy-1 deployed, SHA verified per machine | **MET** — §1, all four machines |
| 2. ≥ 7 days containing real fleet traffic | **RUNNING** from 2026-08-29T23:11:57Z; earliest close **2026-09-05T23:11:57Z**. The sweep is inside it |
| 3. every `imagery_snapshots` counter +0 across the span | **HOLDING** — +0 over the first hour, including the sweep |
| 4. seq-scans attributed, not explained | **MET so far** — §5.6, with the caveat in F-PROD-2 |
| 5. the drop ships alone | **not yet applicable** — `cb088f8` is local and unpushed |

## 7. Findings

### F-PROD-1 — `scripts/normalization_invariants.py` is not in the deployed image

It was added in **`87bf025`**, which is *after* `03867c4`, so the prefix push
correctly excluded it. The invariant battery therefore could not be run as a
script in production.

**What was done instead:** its check definitions were transcribed verbatim into
an inline script and executed against the **deployed** `scripts/shared/probe.py`
(sha256 `1582c2848493fc70`, byte-identical to the local file), so every scan
still emitted an `audit_probe` event and every definition is the one the local
battery uses. The local file's sha256 is `9608c2dd182ae045`, recorded so a
future reader can diff the transcription against it.

**Not fixed, and deliberately:** the fix is to ship the script, and shipping it
means a push, and a push from this tree deploys migration 0019. It goes with
whatever lands next.

### F-PROD-2 — `audit_probe` events do not reach `fly logs`

**The attribution instrument's events are invisible to the log stream in the
operating mode the project mandates.** CLAUDE.md requires production commands to
run as `fly ssh console -a <app> -C …`; a process started that way writes to the
ssh client, not to the app's log pipeline. `grep -c audit_probe` over **both**
continuously-captured streams — API and worker, 3,335 lines — returns **0**,
for a session that emitted several dozen such events.

**Why this matters and is not cosmetic.** Deploy-2 condition 4 says "a
`seq_scan` delta with no matching `audit_probe` event is an unaccounted
reader". That rule assumes the events are *findable later, by someone other
than the operator*. They are findable only in the operator's captured stdout. A
future reader grepping `fly logs` for the cooling span's probes will find
nothing and could conclude — wrongly — that unattributed scans occurred.

**Mitigation used here:** every probe invocation's stdout is captured, and the
attribution is closed arithmetically *and* by the isolated instrument-cost
measurement of §5.6, so nothing rests on the event stream. **Recorded as
STATUS.md NORM-36**, because the next cooling reading will hit it again.

### F-PROD-3 — a silent-drop query that was too broad, caught by decomposing it

The first pass counted ledger rows matching `%_search_and_persist_source%` and
returned **7**, which reads as seven silent drops. The NAIP item-cap reason
*contains* that function name. The exact predicate — `%with no outcome%`, the
loop's actual silent-drop wording — returns **0**, and all 7 decompose to
`naip/indeterminate` truncation markers.

Reported rather than quietly corrected: a pattern loose enough to swallow a
benign population is loose enough to hide a real one inside it, and the habit
that caught it — decompose a nonzero before reporting it — is the transferable
part.

### F-PROD-4 — three point estimates were high, and NORM-15 says why

P3b predicted 8 changed groups (got **1**), P3d 4 new scenes (got **1**), P7a 0
landsat failures (got **4**). All three bands held, so nothing is scored as a
deviation — but the first two were sized on step 2's 7 changed groups nineteen
hours earlier, which is **exactly the reuse NORM-15 warns against**: churn
measures Planetary Computer's health, not selection drift. Across the whole
fleet run there were 4 upstream failures and 2 TNM row caps. Recorded as another
data point on that row rather than as a new finding.

---

## 8. State left behind

* **Deploy-1 is DEPLOYED.** `03867c4b1e531b461665d41cab7b8a8f4196c60d`, built
  **2026-08-29T23:04:25Z**, serving on all four machines of both apps.
  Production is at **alembic 0018** with `ck_scenes_footprint_valid` present
  and validated.
* **`imagery_snapshots` still exists in production**, 12,884 rows, 13 columns,
  **with no readers and no writers** — verified at artifact level and measured
  at +0 across a 189-parcel sweep.
* **The cooling span is RUNNING** from **2026-08-29T23:11:57Z**, with a full
  fleet sweep already inside it. Earliest close **2026-09-05T23:11:57Z**.
* **Migration 0019 is NOT deployed.** `cb088f8` and every record commit,
  including this one, are **local and unpushed**. *A push from this tree ships
  the DROP.*
* **Production data:** 189 parcels, 6,664 scenes, 12,884 parcel_scenes, all
  7 invariants at 0, landsat 43 × 189. One scene and one attribution written by
  this sweep, both Sentinel-2 recency.
* **Nothing was pushed, deployed, or dropped.** Two production writes were made,
  both authorized `requeue_parcels.py` sweeps.

## 9. Deviations from the prompt

1. **Item 0's poll never ran.** CI had finished before the session opened; the
   first health fetch already returned the target SHA.
2. **The invariant battery ran as a transcription, not as the script** —
   F-PROD-1. The script postdates the deployed commit.
3. **A dry run preceded each stage.** Not named in the prompt's item list;
   `--dry-run` returns before any write (`scripts/requeue_parcels.py:452-460`,
   verified before use), and it is how the deploy gate and the id lists were
   checked without spending a write.
4. **An extra pair of counter readings was taken** (t3, t4) to measure the
   instrument's own scan cost in isolation, converting §5.6's attribution from
   an arithmetic argument into a measurement.
5. **The pilot's write-arm gate was discharged by the fleet, not the pilot** —
   under the decision rule committed in advance as P3f, because the pilot wrote
   nothing and NORM-12 predicted it would. The prompt's "widen it before
   proceeding" was satisfied by the remainder, which is the widening; no third
   invocation was made and none was authorized.
