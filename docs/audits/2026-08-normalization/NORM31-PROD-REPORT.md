# NORM-31 healed in production, and NORM-30's instrument read clean

Session of 2026-08-29, 20:30–20:45Z. Two jobs in one window: the two-row
footprint heal, and the step-4 cooling reading taken with the fixed instrument
for the first time since NORM-30 proved the old one poisons the pool.

**Outcome. Both done.** The invalid-footprint queue went **2 → 0**, both rows
are valid `POLYGON`s that still contain every parcel point they served, nothing
outside those two rows moved, and `.rc` read `0`. The instrument then ran
against production and **left the pool clean — 16 of 16 fresh connections
read-write across both apps.** NORM-30's own failure mode, measured on the
thing that caused it.

**The step-4 verdict is NOT YET, and the reason is not the span.** The cooling
window contains **no reconciler traffic at all**, so it cannot distinguish "the
only reader is the reconciler" from "nothing read anything" (§6c). What would
settle it is in §6d.

| Item | Status |
|---|---|
| 1. Deploy gates, artifact-level | **PASS**, four checks over four machines (§1) |
| 2. Pre-heal measurement, read-only | **PASS** — queue **2**, the two known rows, no traffic to reconcile (§2) |
| 3. Prediction committed before execute | **DONE**, `213ae77` (§3) |
| 4. Execute, one logical run, detached | **DONE** — 2 fetched, 2 written, `.rc` `0` (§4) |
| 5. Verify + score | **DONE** — 21 scoreable, **21 confirmed, 0 falsified** (§5) |
| 6. Cooling reading, fixed instrument | **DONE**, and the pool is clean (§6) |
| 7. Record | this file, STATUS.md NORM-30 / NORM-31 / step-4 readiness (§7) |

Every `fly ssh` in this session pinned `--machine` (NORM-28). Every exit code
was read from a `.rc` file, never inferred (NORM-8, F3).

---

## 1. Item 1 — deploy gates, artifact-level

### 1a. Health sha, with all three commits as ancestors

```
$ curl -s https://log0s-plotline-api.fly.dev/api/v1/health
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"92ecf19d2d6353c0e6a037ef9cc58ff5623f7a8b",
            "built":"2026-08-29T20:28:29Z"}}     # read 20:30:31Z

$ git fetch origin && git rev-list --left-right --count origin/main...main
0	0
$ for c in 71eb335 0c56d5d 3849fec; do git merge-base --is-ancestor $c 92ecf19d…; done
71eb335 ancestor-ok      # NORM-30, the script fix
0c56d5d ancestor-ok      # NORM-30, the CLAUDE.md rule
3849fec ancestor-ok      # NORM-31, the write-time rule and the heal
```

**PASS.** The serving sha is this repo's HEAD, and both findings' fixes are in it.

### 1b. `GH_SHA` on every machine of both apps

`fly image show`, both apps:

| app | machine | `GH_SHA` | digest |
|---|---|---|---|
| `log0s-plotline-api` | `48e0de9a713918` | `92ecf19d…` | `sha256:17768189…` |
| `log0s-plotline-api` | `825d69b7e46618` | `92ecf19d…` | `sha256:17768189…` |
| `plotline-worker` | `e2862966b306d8` | `92ecf19d…` | `sha256:17768189…` |
| `plotline-worker` | `e7845415f57728` (standby, stopped) | `92ecf19d…` | `sha256:17768189…` |

**4 of 4, and this time the digest is identical across *both* apps** rather
than one digest per app as in every prior gate — one image now serves API and
worker. **PASS.**

### 1c. The deployed `snapshot_reads.py`, opened rather than trusted

Pinned grep on `825d69b7e46618`, `48e0de9a713918` and the worker's
`e2862966b306d8`, identically:

```
$ grep -nE 'set_session|SET SESSION|SET default_transaction_read_only|\.commit\(\)|SET TRANSACTION READ ONLY' \
    /app/scripts/snapshot_reads.py
41:ONLY``. This script used to issue ``SET default_transaction_read_only = on``
69:READ_ONLY_STATEMENT = "SET TRANSACTION READ ONLY"
```

**The only surviving mention of the old statement is line 41, the docstring
narrating its own history.** No `set_session`, no `SET SESSION`, no
`.commit()` anywhere in the file. **PASS.**

### 1d. The deployed enrichment script has the revalidate mode

Same pinned read, `/app/scripts/enrich_snapshot_scenes.py`: the mode flag at
`:752`, the queue predicate at `:202`
(`footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> :excluded`),
the PostGIS refusal at `:221`, `FOOTPRINT_INVARIANT_SQL` at `:275`, and
`def normalize_footprint` present once in `/app/app/services/stac.py`. **PASS.**

---

## 2. Item 2 — pre-heal measurement, 2026-08-29T20:33:59Z

`norm31-preheal.json`, committed unedited at `213ae77`.

**The read-only proof is the new shape, and it is the point.** One transaction:
`SET TRANSACTION READ ONLY` as its first statement, then — **inside that same
transaction**, on a savepoint so the probe does not abort the reads that follow
— `UPDATE scenes SET resolution_m = resolution_m WHERE false`:

```
"session_state": [{"txn_ro": "on", "default_ro": "off", "backend_pid": 659}],
"write_probe": "ReadOnlySqlTransaction: cannot execute UPDATE in a read-only transaction"
```

`txn_ro` is `on` and `default_ro` is `off` **at the same instant**: the
guarantee is real and its scope is the transaction. That pair is exactly what
the old probe could not show, because the old probe's `on` *was* `default_ro`.

### The queue, by the script's own definition

```
footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> 'usgs_topo'   =  2
```

| id | item_id | reason | npoints | fp area | provenance |
|---|---|---|---|---|---|
| `6d456449-2ffb-4f3f-aa3f-ba69a502481d` | `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` | `Self-intersection[-71.00403 41.90664113]` | 28 | 0.76542450 | snapshot |
| `6b114490-1bd7-47e7-a195-f5d92686559b` | `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | `Self-intersection[-86.75983 39.91487413]` | 22 | 1.03875393 | snapshot |

**Both ids, both item ids, both reasons and both point counts match
`snapshot-enrich-prod-invalid-footprints.json` exactly.** The count did not
move, so there is no growth to reconcile — but the check that would have caught
growth was run rather than assumed:

* **Fleet invariant, no source filter:** `invalid` **2**, `not_polygon` **0**,
  `equals_bbox` **0**, over **5,894** rows with a footprint. The two are the
  whole population, not the snapshot-provenance slice of it.
* **Dual-write traffic since the finding: none.** `max(scenes.fetched_at)` and
  `max(parcel_scenes.selected_at)` are both `2026-08-29 04:41:26.056028+00`,
  unchanged; **0** rows carry `fetched_at` at or after the 19:52:27Z post-run
  reading; counts are 6,663 / 12,884 / 12,884 and the provenance split
  6,156 / 505 / 2, all identical to the post-run artifact. Both `selection`
  rows carry a footprint and **both are valid**.
* **Baseline fingerprints**, for §5's "nothing else moved" test:
  `bbox` **`f1809593fd050be14736aaaea4b09ed5`** (6,663 rows — the same value
  this arc has reproduced three times), footprints outside the queue
  **`b605a050fb49731dd45175d13e89ac9c`** (6,661 rows), `resolution_m`
  **`b30a4fc5c7b6ff36aae6573714e049ec`** (6,663 rows).

### The serving reference, computed before the write

The three `parcel_scenes` rows behind the two scenes resolve to three parcel
points. Whether the **raw** ring contained them was answered by an even-odd ray
cast in Python over the stored WKT — arithmetic, not shapely, so the library
that performs the repair does not also grade it (`NORM31-REPORT.md` §5's
method). All three: **true**. `norm31-raw-ring-containment.json`, committed at
`213ae77` before the write.

---

## 3. Item 3 — the prediction, committed before the write

`PREDICTION-NORM31-HEAL.md` at **`213ae77`**, P1–P22, with its §E0 disclosing
that almost nothing about the plan is blind after the local build and naming
the four things that are. Stop conditions are written as outcomes.

---

## 4. Item 4 — the execute

**One read-only dry run first, which the prompt did not ask for.** It issues no
write, and it bought the one thing three checks could not: proof that the
deployed mode meets the *real* items before a write depends on it. Launched
detached 20:35:55Z, finished 20:35:58Z, `.rc` **`0`**:

```
queue=2 footprints=2 written=2 unmatched_403=0 unmatched_404=0 errors=0
invariants={'not_polygon': 0, 'invalid': 2, 'equals_bbox': 0} mode=revalidate execute=False
```

`invalid: 2` is correct for a dry run — nothing was written, so the invariant
still sees the unhealed rows. Both repairs were computed and **logged**:

```
footprint_repaired_invalid_geometry  repaired=True polygon_parts=1
  footprint_repair_discarded_area=0.0
  invalidity_reason='Self-intersection[-71.00403 41.90664113]'
  stac_item_id=S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747
footprint_repaired_invalid_geometry  repaired=True polygon_parts=1
  footprint_repair_discarded_area=0.0
  invalidity_reason='Self-intersection[-86.75983 39.91487413]'
  stac_item_id=S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018
```

`polygon_parts=1` and a zero discard on production geometry, matching the local
catalogue measurement (`NORM31-REPORT.md` §2) item for item. Captures:
`norm31-dryrun.md`, `norm31-dryrun.txt`.

**The execute**, launched detached from `825d69b7e46618` with the PP14 recipe:

```sh
setsid nohup sh -c 'python scripts/enrich_snapshot_scenes.py --revalidate-footprints \
  --execute --report /tmp/norm31-run.md > /tmp/norm31-run.log 2>&1; \
  echo $? > /tmp/norm31-run.rc' < /dev/null > /dev/null 2>&1 &
```

Launched **20:36:42Z**, `bg-pid=759`. **20:36:43Z → 20:36:45Z, 2 s.** One
logical run, one batch, no abort and no resume.

```
queue=2 footprints=2 written=2 unmatched_403=0 unmatched_404=0 errors=0
invariants={'not_polygon': 0, 'invalid': 0, 'equals_bbox': 0} mode=revalidate execute=True
```

```
$ fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C "cat /tmp/norm31-run.rc"
0
```

Captures: `norm31-run.md`, `norm31-run.txt`, `norm31-run.rc`.

---

## 5. Item 5 — verification and the score

`norm31-postheal.json`, 20:38:12Z, same per-transaction read-only shape, same
`ReadOnlySqlTransaction` from the in-transaction write probe.

| # | Predicted | Observed | Verdict |
|---|---|---|---|
| P1 | queue 2, the two named ids | 2, both | confirmed |
| P2 | 2 fetched / 2 STAC requests | 2 / 2 | confirmed |
| P3 | 404 / 403 / errors 0 | 0 / 0 / 0 | confirmed |
| P4 | 2 written, queue after 0 | 2, **0** | confirmed |
| P5 | `ST_IsValid` true on both | true, both (`ST_IsValidReason` = `Valid Geometry`) | confirmed |
| P6 | `POLYGON` on both | `POLYGON`, both | confirmed |
| P7 | area 0.76542450 / 1.03875393 | **0.76542450 / 1.03875393** | confirmed |
| P8 | all 3 parcel points contained | `ST_Contains` **true** on 3 of 3 (`ST_Covers` likewise) | confirmed |
| P9 | 2 repair events, reasons, parts 1, discard 0 | exactly that, in both runs | confirmed |
| P10 | invariants 0 / 0 / 0 over 5,894 | **0 / 0 / 0**, 5,894 | confirmed |
| P11 | footprints outside the queue unchanged | **`b605a050fb49731dd45175d13e89ac9c`**, 6,661 rows | confirmed |
| P12 | all-row footprint fingerprint changed | `54a1a8a5…` → `76527ace…`; row md5s `5ccd9329…`→`58a63f50…`, `ecbad666…`→`3a9e1c4a…` | confirmed |
| P13 | `bbox` fingerprint unchanged | **`f1809593fd050be14736aaaea4b09ed5`**, 6,663 rows; both `bbox_wkt` byte-identical | confirmed |
| P14 | `resolution_m` fingerprint unchanged | **`b30a4fc5c7b6ff36aae6573714e049ec`**; both rows still 10.0 | confirmed |
| P15 | counts and provenance split unchanged | 6,663 / 12,884 / 12,884; 6,156 / 505 / 2 | confirmed |
| P16 | `.rc` 0 | **0**, read from the file | confirmed |
| P17 | under 60 s | **2 s** | confirmed |
| P18 | dry re-run: queue 0, 0 fetches, `.rc` 0 | queue **0**, fetched **0**, requests **0**, `.rc` **0** | confirmed |
| P19 | instrument exits 0 | **0** (§6) | confirmed |
| P20 | 0 of 8 fresh connections read-only | **0 of 16**, both apps (§6b) | confirmed |
| P21 | reconciler accounts for 0 of any delta | `idx_scan` delta **0** (§6c) | confirmed |
| P22 | log observations are a floor | stated as one, and the floor is 0 over ~11 min (§6c) | confirmed |

**21 scoreable, 21 confirmed, 0 falsified.**

**Three things worth naming beyond the table.**

1. **`ST_NPoints` fell 28 → 27 and 22 → 21.** Not predicted, and it is the
   repair's signature: `make_valid` pinched off the zero-area spike, so the
   duplicate vertex at the self-intersection is gone. Area is preserved to
   8 dp in both rows, so no coverage went with it.
2. **`fetched_at` did not move** — `2026-08-20 11:31:23` and
   `2026-08-12 00:43:12`, the values the rows already had. The mode writes the
   footprint column and nothing else, and the timestamps prove it independently
   of the fingerprints.
3. **The database's own write counter agrees.** `scenes.n_tup_upd` has moved
   **+5,389** since the step-3 cooling t0 (§6): 5,387 from the big heal and
   **exactly 2** from this one. Nothing updated a `scenes` row that this arc
   has not accounted for.

---

## 6. Item 6 — the cooling reading, taken with the fixed instrument

### 6a. The instrument ran, and it exited 0

```
$ python scripts/snapshot_reads.py --baseline /tmp/reads-t0.json --out /tmp/reads-t2.json
pg_stat_user_tables at 2026-08-29T20:39:20.439155+00:00  (delta since 2026-08-29T06:41:47.270470+00:00)
stats_reset: None
...
rc=0
```

`stats_reset` is `None` at both ends, so the deltas are comparable rather than
a reset in disguise. Reading committed as `reads-t2.json`. **Cooling span:
t0 `06:41:47.270470Z` → t2 `20:39:20.439155Z` = 13 h 57 m 33 s.**

### 6b. The instrument no longer poisons what it measures

This is the scored half. **After** the instrument ran, from a *separate
process*, eight sequential fresh engines were opened and disposed from **each**
app:

| app | fresh connections | `default_transaction_read_only` | `pg_settings.source` | distinct backends |
|---|---|---|---|---|
| `log0s-plotline-api` | 8 | `off` × 8 | `default` × 8 | pid **659** |
| `plotline-worker` | 8 | `off` × 8 | `default` × 8 | pid **659** |

**0 of 16 read-only.** `source = default` on every sample — not "reset to off",
but *never set at all* on that backend. And the sample is not a lucky miss:
all sixteen landed on backend **659**, which is the same backend
`norm31-preheal.json`, `norm31-postheal.json` and the instrument itself
borrowed. **The connection that carried the read-only transaction is the
connection that was checked, and it came back clean.** Under the old statement
this is precisely the reading that came back `on` 24 times out of 24
(`SNAPSHOT-ENRICH-PROD-REPORT-3.md` §6b).

NORM-30 is now resolved in production, not merely in the repo.

### 6c. The reading, and what it will and will not carry

Deltas from the step-3 cooling t0:

| table | `seq_scan` | `seq_tup_read` | `idx_scan` | `idx_tup_fetch` | ins / upd / del |
|---|---|---|---|---|---|
| **`imagery_snapshots`** | **+15** | +193,260 | **+0** | **+0** | **0 / 0 / 0** |
| `parcel_scenes` | +34 | +438,056 | +1,684 | +674 | 0 / 0 / 0 |
| `scenes` | +70 | +466,410 | +5,558 | +347,137 | 0 / **+5,389** / 0 |

**`imagery_snapshots` has not been touched by an indexed read or by any write
in 13 h 57 m.** That is the load-bearing number, because the only application
reader left — `reconcile_source_snapshots`' existing-rows pull
(`app/services/imagery.py:1577`) — filters `WHERE parcel_id = :parcel_id AND
source = :source` against `idx_imagery_parcel_date`. Three independent signals
agree that it never ran: `idx_scan` **+0**, `n_tup_ins/upd/del` **+0** (the
reconciler deletes and upserts when it acts), and
`max(parcel_scenes.selected_at)` still `2026-08-29 04:41:26+00`, which is
*before* t0.

**The +15 sequential scans are audit traffic, and the arithmetic says so.**
193,260 ÷ 12,884 = **exactly 15** — fifteen whole-table scans, no partial ones.
`count(*) FROM imagery_snapshots` is exactly that shape, and it is what every
pre-run and post-run probe in this arc issues, including this session's two.
No artifact names each of the fifteen individually, so this is an explanation
consistent with the evidence, not an attribution: what is *measured* is that
every touch was a full scan with no index use and no row modification, which is
not the shape the reconciler makes.

**Meanwhile the serving path was demonstrably busy elsewhere**: `scenes` and
`parcel_scenes` took +5,558 and +1,684 index scans in the same window (the heal
accounts for 5,389 of the `scenes` figure; the rest, and all of
`parcel_scenes`, is read traffic). Reads happened, and none of them went to
`imagery_snapshots`.

**The `imagery_snapshots_read` instrument contributes almost nothing yet, and
its coverage is stated as a floor.** `fly logs --no-tail` on both apps returns
a **capped 100-line page**: the API's page spans `20:28:52Z → 20:39:53Z`
(≈11 minutes, the machine's whole life since the 20:28 deploy) and the worker's
ends `20:40:06Z`. **0 occurrences of `imagery_snapshots_read`** in that page —
a floor of zero over eleven minutes of a fourteen-hour window, which is nearly
no coverage at all. The counters are carrying this reading; the log is not.

### 6d. Step-4 readiness: NOT YET, and the span is not the reason

**The window contains no reconciler traffic.** `max(selected_at)` predates t0,
`imagery_snapshots` took zero writes, and no timeline request ran. The cooling
period's question is "is the reconciler the *only* reader" — and a window in
which the reconciler itself never ran cannot separate that from "nothing read
anything". Fourteen hours of an idle fleet is a weaker statement than it looks,
and 14 h is also simply short for "one cooling period".

**What would support drafting step 4**, concretely:

1. **A span containing real fleet traffic** — at least one 189-parcel
   reconcile sweep, or enough timeline requests to exercise every source — with
   `imagery_snapshots.idx_scan` still moving *only* by the reconciler's own
   pulls, and its `n_tup_ins/upd/del` accounted for row by row.
2. **Log coverage that is a span rather than a page.** `fly logs --no-tail`
   cannot supply it. Every `imagery_snapshots_read` event over the window has
   to be captured from inside the machines or from a drain, so the count is a
   count and not a floor of zero over eleven minutes.
3. **A seq-scan story that is attributed rather than explained.** Once the
   audit probes stop issuing `count(*)` against the table — or issue it from a
   named, logged path — a nonzero `seq_scan` delta becomes a finding instead of
   a footnote.
4. **Then, a span of at least seven days** with (1) and (2) holding.

**Step 4 was not started.** The prompt says so and nothing here argues
otherwise.

---

## 7. State left behind

* **NORM-31 is resolved in production.** Queue 2 → 0; both rows valid
  `POLYGON`s; area preserved to 8 dp; all three parcel points still contained,
  scored against a reference committed before the write. The write-time rule
  has been deployed since `92ecf19`, so both write paths now validate.
* **NORM-30 is resolved in production.** The fixed instrument ran and left
  16 of 16 fresh connections read-write across both apps, on the very backend
  it borrowed.
* **Nothing outside the two rows moved.** Footprint fingerprint over the other
  6,661 rows, `bbox` fingerprint over all 6,663, `resolution_m` fingerprint
  over all 6,663 — all three byte-identical across the write. `fetched_at`
  unchanged on both healed rows.
* **`usgs_topo` remains excluded and unhealed**, 769 rows, `footprint` and
  `resolution_m` both NULL. Unchanged by this session and by design.
* **Step 4 is not started and is not yet supported** (§6d).
* **Open and still undecided:** whether `CHECK (ST_IsValid(footprint))` should
  now follow the heal. Its precondition — the two rows fixed — is met as of
  this session; the decision is not this session's to make and stays in
  STATUS.md.
* **Nothing is pushed.** Commits are on `main`, local only.

## 8. Deviations from the prompt

1. **A read-only dry run preceded the execute** (§4). Not in the prompt's item
   list. It writes nothing; it exercises the deployed mode against the real two
   items and produced the repair-event evidence for P9 twice rather than once.
2. **The pool check sampled both apps, 8 connections each**, where the
   prediction said 8. The extra 8 are reads; they make the claim symmetric with
   the 19:30Z verification the record already holds.
3. **The `imagery_snapshots_read` half of the cooling reading is effectively
   uncovered** (§6c). The event count is 0 over an ~11-minute page, and it is
   reported as a floor with its span stated rather than as a zero.
4. **`ps` still does not exist in the image**; the dry run's liveness check
   used a `/proc/*/cmdline` scan. The execute finished inside one poll interval,
   so its liveness was established by the `.rc` file rather than by `/proc`.
