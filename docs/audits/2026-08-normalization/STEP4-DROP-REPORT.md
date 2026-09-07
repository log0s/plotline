# Step 4 deploy-2 — the DROP is deployed, and `imagery_snapshots` is gone

Session of 2026-09-07, **unattended**. ADR 0001 step 4's *second and final*
deploy. The owner pushed `main` at ~03:22Z; CI built and rolled both apps; the
API's first machine applied migration 0019 and dropped the table at
**2026-09-07T03:23:59Z**. This session verified the drop landed, confirmed
serving is unaffected, and wrote the close-out.

**Production writes made by this session: zero.** No sweep, no heal, no
requeue, no deploy. Every probe ran inside a transaction opened
`SET TRANSACTION READ ONLY`, with the `UPDATE … WHERE false` proof executed
**inside that same transaction**; every `fly ssh console` pinned `--machine`
(NORM-28).

**The cooling span closed at 8 days 3 h 16 m 40 s with `imagery_snapshots` at
`+0` on all seven counters.** The closing pre-drop reading is the owner's
(2026-09-07T02:28:37Z) and is **inherited, not re-derived** — the table no
longer exists, so those counters are unrecoverable from here. Everything else
in this report was measured in this session.

---

## 1. Deploy gates

| | gate | evidence | verdict |
|---|---|---|---|
| **1a** | health SHA == the pushed head, and it contains the drop | `GET /api/v1/health` → `{"status":"ok","db":"connected","redis":"connected","version":{"sha":"bac725c5a7d196a8cd8c7aa4f6da84c7bb063bda","built":"2026-09-07T03:23:17Z"}}`; `git merge-base --is-ancestor cb088f8 bac725c` exits **0** | **PASS** |
| **1b** | `GH_SHA` on **all four** machines of both apps | `fly image show -a log0s-plotline-api` → `GH_SHA=bac725c5a7d1…` on `825d69b7e46618` and `48e0de9a713918`; `fly image show -a plotline-worker` → same SHA on `e2862966b306d8` and the standby `e7845415f57728`. Both apps on one digest each (`sha256:2253d63e…`, `sha256:e0eee73e…`) | **PASS** |
| **1c** | `alembic_version` is 0019's **actual** revision id, read from the migration file | `backend/alembic/versions/0019_drop_imagery_snapshots.py:65` → `revision: str = "0019"`, `:66` → `down_revision = "0018"`. `SELECT version_num FROM alembic_version` → **`0019`** | **PASS** |
| **1d** | process starts postdate the build (NORM-32: a label is not a running process) | image built **03:23:17Z**. `/proc/uptime` read on each running machine: API `48e0de9a713918` boot **≈03:23:52Z** (161.55 s at 03:26:34Z), API `825d69b7e46618` boot **≈03:24:16Z** (129.67 s at 03:26:26Z), worker `e2862966b306d8` boot **≈03:23:50Z** (169.32 s at 03:26:39Z). Each machine's process env carries `GIT_SHA=bac725c5a7d1…` | **PASS, with one machine not readable — see below** |
| **1e** | the deployed image is the repo | sha256 over the **running worker's** copies matches the local worktree exactly: `app/services/imagery.py` `a70ef9114b11d517`, `app/tasks/timeline.py` `ad49522a77552e64`, `app/models/parcels.py` `c99fa10263e85c89`, `app/services/year_ledger.py` `282899be8027a81d`, `scripts/snapshot_reads.py` `f6c288f43c1e5852`, `scripts/shared/probe.py` `1582c2848493fc70`, `scripts/normalization_invariants.py` `9608c2dd182ae045` | **PASS** |
| **1f** | the read-only claim, proved rather than asserted | inside the same transaction as every probe: `UPDATE scenes SET fetched_at = fetched_at WHERE false` → `ReadOnlySqlTransaction: cannot execute UPDATE in a read-only transaction` | **PASS** |

**The standby worker `e7845415f57728` is `stopped`** (`fly status -a
plotline-worker`), so `/proc` could not be read on it. Its **image label** is
verified at `bac725c5a7d1…` and it took the same deployment tag as the running
machine, but this session did **not** observe a process on it. Stated rather
than rounded up to "all four verified at process level": deploy-1's report
could make the stronger claim because that machine was running then.

### 1.1 Condition 5, "the drop ships alone" — met in substance, **not in letter**

Migration 0019's own docstring
(`backend/alembic/versions/0019_drop_imagery_snapshots.py:11-21`) states the
gate as *"No code change may ride the same push"*, with the rationale that
otherwise *"the running code at the moment of the drop is not the code the
cooling period measured"*.

`git diff --stat 03867c4 bac725c` — what the push actually carried beyond the
migration:

| file | change | is it running code? |
|---|---|---|
| `scripts/normalization_invariants.py` | **new, +253** | a script with no `main()` on any service path; runs only when invoked by hand |
| `backend/tests/test_migrations_postgres.py` | new, +102 | tests |
| `backend/tests/test_stac.py` | +37 / −23 | tests |
| `.github/workflows/deploy.yml` | +8 | CI config |
| `docs/**`, `docs/adr/0001-…` | +7,700 | record |

**`git diff --stat 03867c4 bac725c -- backend/app` is empty.** Not one byte of
`app/` changed between the SHA the cooling span measured and the SHA that ran
the drop, and §1e re-proves that at the artifact rather than the repo. The
rule's *rationale* is therefore satisfied exactly.

The rule's *wording* is not, and it is worth naming rather than absorbing:
`scripts/normalization_invariants.py` is a new file in the deployed image. It
is also **NORM-37's fix**, and NORM-37 named this exact bundling as its plan —
*"the fix is to ship the script, shipping means a push, and a push from the
current tree deploys migration 0019 … It goes with whatever lands after that
span closes."* So the relaxation was decided in advance and recorded, not
discovered here. Scored **MET in substance, not in letter**, and STATUS.md's
gate row says so in those words.

---

## 2. The table is gone, verified three ways

`docs/audits/2026-08-normalization/step4-drop-gates.json`, read
2026-09-07T03:33:10Z (a first identical reading was taken at 03:27:17Z):

```json
"alembic_version": "0019",
"to_regclass_imagery_snapshots": null,
"pg_class_relname_like": [],
"pg_index_on_table": [],
"pg_constraint_named": [],
"pg_stat_user_tables_imagery": []
```

1. **`to_regclass('public.imagery_snapshots')` is `NULL`.** The name resolves
   to nothing.
2. **Its indexes and constraints are absent from `pg_catalog`.** `pg_class`
   joined to `pg_namespace` on `relname LIKE '%imagery_snapshot%'` returns
   **zero rows** — so neither the table, nor the two indexes, nor the sequence
   or type a dropped relation would leave behind. `pg_constraint` on
   `conname LIKE '%imagery_snapshot%' OR conrelid = to_regclass(…)` returns
   **zero rows**: the CHECK and the unique constraint 0002/0007/0008 built are
   gone with it.
3. **`pg_stat_user_tables` no longer lists it.** The full table list is now
   `alembic_version, census_snapshots, featured_locations, parcel_scenes,
   parcels, property_events, scenes, spatial_ref_sys, timeline_request_tasks,
   timeline_requests, timeline_task_years` — eleven relations, and
   `imagery_snapshots` is not among them.

**The instrument agrees, in the mode it was built for.**
`scripts/snapshot_reads.py` prints

```
imagery_snapshots: not present
```

which is the behaviour its own module docstring specifies — *"``render``
prints 'not present' rather than failing once migration 0019 has dropped it,
which is what turns this script from the instrument that gates the drop into
the one that confirms it"* (`scripts/snapshot_reads.py:79-83`). It is
confirming now.

### 2.1 The table's terminal state

**Inherited from the owner's closing pre-drop reading, 2026-09-07T02:28:37Z.**
Not re-derivable: the counters died with the relation.

| counter | value at t0 (2026-08-29T23:11:57Z) | terminal (2026-09-07T02:28:37Z) | Δ over the span |
|---|---|---|---|
| `seq_scan` | 3,945 | **3,945** | **+0** |
| `seq_tup_read` | 30,606,005 | **30,606,005** | **+0** |
| `idx_scan` | 158,669 | **158,669** | **+0** |
| `idx_tup_fetch` | 1,238,541 | **1,238,541** | **+0** |
| `n_tup_ins` | 15,492 | **15,492** | **+0** |
| `n_tup_upd` | 61,406 | **61,406** | **+0** |
| `n_tup_del` | 2,608 | **2,608** | **+0** |
| `n_live_tup` | 12,884 | **12,884** | **+0** |

t0 is the committed baseline `step4-prod-reads-t0.json`. `stats_reset` was
**NULL at every reading**, so the counters ran continuously across the whole
span and the zeros are not a reset artifact.

**Span: 2026-08-29T23:11:57Z → 2026-09-07T02:28:37Z = 8 days 3 h 16 m 40 s**,
against a gate of ≥ 7 days.

---

## 3. Serving smoke — read-only GETs and DB probes

`step4-drop-smoke.txt`. Every call **200**.

| surface | result |
|---|---|
| `GET /api/v1/health` | 200, sha `bac725c…`, `db: connected`, `redis: connected` |
| `GET /api/v1/featured` | 200, locations rendered with `earliest_snapshot_id` / `latest_snapshot_id` populated |
| `GET /api/v1/featured/stapleton-central-park` | 200, 806 bytes |
| `GET /api/v1/parcels/4146ec5f-…/imagery` | 200, 63,298 bytes — **72 rows**: landsat 43, naip 13, sentinel2 12, usgs_topo 4 |
| `GET /api/v1/parcels/639541ac-…/imagery` | 200, 55,078 bytes — **63 rows**: landsat 43, naip 8, sentinel2 12 |
| `GET /api/v1/imagery/f955741d-…/stac` | 200, 24,054 bytes, `application/geo+json`, item `LT05_L2SP_024033_19840826_02_T1`, red/green/blue hrefs signed |
| `GET /api/v1/imagery/f955741d-…/tiles/11/506/783` | 200, **157,015 bytes**, `image/png`, PNG 256×256 RGBA, 2.89 s |

**Mosaic cardinality is intact, checked against the database rather than
eyeballed.** For parcel `4146ec5f`, a read-only probe reports 13 NAIP rows
with a non-empty `mosaic_scene_ids` and `sum(cardinality(...)) = 13`; the
listing returns **13 rows carrying `additional_cog_urls`, every one of
length 1**. The reconstruction in `get_served_scenes` therefore resolves every
reference — 13 stored ids in, 13 URLs out, none dropped and none invented.
Same shape on `639541ac`: 8 mosaic rows in the database, 8 in the response.

**The tile is a real end-to-end exercise of the `/stac` callback.** The tile
proxy routes Landsat through Titiler's STAC endpoint, which calls back to
`/api/v1/imagery/{id}/stac`; that returned a signed 24 KB item and Titiler
returned a rendered 157 KB PNG. Both halves ran against `parcel_scenes.id`
`f955741d-68d4-4223-9378-1d0faeb7529a` — an id that only exists in the
normalized shape.

**The fresh surface is genuinely fresh.** Parcel
`639541ac-1c2e-4587-ae06-92f9a1cee729` was created **2026-09-06T16:09:03Z** —
inside the cooling span, eleven hours before the drop — by an organic geocode
(`Geocode complete … is_new: true`, `step4-drop-api-boot.txt`). Its 63
`parcel_scenes` rows were written by the deploy-1 code
(`selected_by = 03867c4b1e531b461665d41cab7b8a8f4196c60d`), and its listing
serves cleanly with the table gone. That is `parcel_scenes` ⋈ `scenes` doing
the whole job for a parcel that never had an `imagery_snapshots` row.

### 3.1 The invariant battery — run as the script, in production, for the first time

`scripts/normalization_invariants.py` is in the image now, so NORM-37's
transcription workaround was not needed. `step4-drop-battery.json`, read
2026-09-07T03:27:47Z:

| | |
|---|---|
| totals | parcels **192**, scenes **6,743**, parcel_scenes **13,082** |
| zero checks | **7 of 7 at 0** — `duplicate_groups`, `dangling_primary`, `dangling_mosaic`, `primary_in_own_mosaic`, `invalid_footprints`, `non_polygon_footprints`, `duplicate_items` |
| landsat conservation | **192 parcels, min 43, max 43**, 8,256 rows — the histogram is `{43: 192}` |
| provenance | `snapshot` **6,156** (unmoved since step 1), `enriched` **505** (unmoved), `selection` **82** |
| ledger, latest outcome per group | landsat ok 8,252 / failed 4; naip ok 1,326 / absent 1,922 / indeterminate 7 / suppressed 9; sentinel2 ok 2,295 / absent 9; usgs_topo ok 1,205 / absent 8 / indeterminate 2; census_acs5 ok 1,103 / absent 49; census_decennial ok 497 / absent 266 |

**Landsat conservation now covers 192 parcels, not 189.** The three parcels
added during the cooling span each carry the full 43, so the conservation
statement widened rather than diluted.

**The hard clause still holds.** `naip/indeterminate` **7** and
`usgs_topo/indeterminate` **2** are unchanged from the deploy-1 fleet reading
of 2026-08-30 — the same NAIP item-cap and TNM row-cap markers on the same
three parcels (NORM-3). The 4 `landsat/failed` are the same `stac_403` pair of
parcels. Nothing new failed across the span or the drop.

**The exit code is derived, not read.** `main()` returns 0 iff `verdicts()` is
empty, and `verdicts()` is empty iff every `zero_checks` value is 0
(`scripts/normalization_invariants.py:246-252`); all seven are 0 in the
captured JSON. The `RC=` line from the battery invocation scrolled out of the
captured output and re-running it would have cost thirteen more whole-table
scans for a fact already in the artifact.

### 3.2 Footprint coverage by source — ADR rule 4, measured

Read-only probe, 2026-09-07T03:36:10Z:

| source | scenes | with `footprint` | NULL |
|---|---|---|---|
| landsat | 3,217 | **3,217** | 0 |
| naip | 1,623 | **1,623** | 0 |
| sentinel2 | 1,132 | **1,132** | 0 |
| **usgs_topo** | 771 | **0** | **771** |

ADR rule 4 says *"The next geometry audit is a query over `scenes`, not a
refetch."* For three sources that is now true with no exceptions — 5,972 of
5,972 rows carry a polygon, and `invalid_footprints` and
`non_polygon_footprints` are both 0. For `usgs_topo` there is nothing to query:
TNM sheets are not STAC items with a geometry member, so the column is NULL by
design rather than by omission. This is the measurement behind the ADR
close-out amendment's first named leftover, and it is why NORM-35's cheaper
condemnation path cannot simply replace the network fetch — a topo row falls
straight through it.

### 3.3 Counters, t0 → post-drop

`step4-prod-reads-t0.json` → `step4-drop-reads-post.json`
(2026-09-07T03:27:37Z). `stats_reset` NULL at both ends.

| table | seq_scan | seq_tup_read | idx_scan | idx_tup_fetch | ins | upd | del | n_live_tup |
|---|---|---|---|---|---|---|---|---|
| `imagery_snapshots` | — | — | — | — | — | — | — | **not present** |
| `parcel_scenes` | +32 | +412,486 | **+19,114** | +42,181 | **+198** | +1 | +0 | +198 → **13,082** |
| `scenes` | +58 | +387,059 | **+50,878** | +68,612 | **+80** | +0 | +0 | +80 → **6,743** |

**This is the traffic contrast the `+0` is measured against.** Over the same
span in which the retired table took **zero** accesses of every kind, the two
live tables took **69,992** index scans between them and wrote 278 new rows.
The span was not an idle window: a 189-parcel fleet sweep ran in its first
hour (deploy-1's report), and organic traffic added 3 parcels, 80 scenes and
198 `parcel_scenes` rows after it.

---

## 4. Migration hygiene

**0019 applied once, under the advisory lock, cleanly.** The boot logs of both
API machines, `step4-drop-api-boot.txt`:

```
03:23:54Z app[48e0de9a713918]  Running database migrations...
03:23:58Z app[48e0de9a713918]  INFO [alembic.runtime.migration] Context impl PostgresqlImpl.
03:23:59Z app[48e0de9a713918]  INFO [alembic.runtime.migration] Running upgrade 0018 -> 0019, Drop ``imagery_snapshots``.
03:23:59Z app[48e0de9a713918]  INFO [alembic.env] Migration head check: database=['0019'] scripts=['0019']
03:23:59Z app[48e0de9a713918]  Migrations complete.

03:24:17Z app[825d69b7e46618]  Running database migrations...
03:24:22Z app[825d69b7e46618]  INFO [alembic.runtime.migration] Context impl PostgresqlImpl.
03:24:22Z app[825d69b7e46618]  INFO [alembic.env] Migration head check: database=['0019'] scripts=['0019']
03:24:22Z app[825d69b7e46618]  Migrations complete.
```

**The evidence is the second machine's silence.** `48e0de9a713918` rolled
first, took `pg_advisory_xact_lock`, applied the upgrade and committed.
`825d69b7e46618` rolled 23 seconds later, took the same lock, found itself
already at head, and printed **no `Running upgrade` line at all** — which is
exactly the behaviour `backend/alembic/env.py:141-150` describes: *"The
advisory lock serializes them: the second waits, then finds itself already at
head and does nothing."* Duplicate DDL would have crash-looped it; a
transaction handed to a caller that does not exist (X1) would have rolled the
DROP back and still exited 0. Neither happened, and the table's absence in §2
is the independent confirmation that the commit stuck.

**No lock-wait or rollback signatures.** `grep -inE
"error|exception|traceback|5[0-9][0-9]|critical"` over the captured API log
returns 11 lines, **all of them before the deploy** (2026-09-06T16:38Z through
2026-09-07T01:57Z) and all the same Fly-edge class —
`blocked by NAW: rsc_exploit_attempt` on `request.url="/"`, scanner traffic
refused at the proxy, never reaching the app. **Zero at or after
2026-09-07T03:23:40Z.** The same grep over the worker log returns **zero lines
for the whole buffer**, including `rollback` and `lock`.

**Boot-mint lines present on both API machines** — NORM-22's instrument,
observed incidentally rather than tested for:

```
03:24:03Z app[48e0de9a713918]  SAS startup mint succeeded  container=landsateuwest/landsat-c2
03:24:03Z app[48e0de9a713918]  SAS startup mint succeeded  container=naipeuwest/naip
03:24:03Z app[48e0de9a713918]  SAS startup mint succeeded  container=sentinel2l2a01/sentinel2-l2
03:24:26Z app[825d69b7e46618]  SAS startup mint succeeded  ×3, same containers
```

Three containers, both machines, ~1 s after `Application startup complete`.
The worker came up clean too: `Janitor found no stranded work`,
`celery@e2862966b306d8 ready.` at 03:24:01Z.

**The CHECK from 0018 survived 0019 — verified in `pg_constraint`, not
assumed.** `SELECT conname, contype, convalidated, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid = 'public.scenes'::regclass` returns five
rows, `ck_scenes_footprint_valid` among them:

```
ck_scenes_footprint_valid   c   convalidated=true
  CHECK (((footprint IS NULL) OR st_isvalid(footprint)))
```

with `ck_scenes_provenance`, `ck_scenes_source`, `scenes_pkey` and
`uq_scenes_collection_item` all present and validated. The battery's
`invalid_footprints = 0` is the same fact stated as a count, from the other
side.

**The deploy did not wedge.** `fly releases`: API **v86 (Aug 29) → v87**,
worker **v78 → v79**, both `complete`. Image built 03:23:17Z, last machine
updated 03:24:17Z — a **~60 s** roll, inside the 61–72 s norm NORM-39
measured, and the first API release since Aug 29. NORM-39's split-production
state (worker on `cebc70f`, API stuck on `03867c4`) is **resolved**: both apps
are on `bac725c`.

---

## 5. Findings

### F-DROP-1 — a `.sql` file in `scripts/` still names the dropped table, and the pin does not cover it

`scripts/featured_naip_copy_2026-08-13.sql:31` reads

```sql
JOIN imagery_snapshots i ON i.parcel_id = f.parcel_id
```

`tests/test_no_imagery_snapshots_references.py` walks `_APP` and `_SCRIPTS`
with `root.rglob("*.py")` (`:66-73`), so a `.sql` file in the same directory is
outside its rule. The test is green and the reference is real.

**Not live, and the shape was searched for.** A repo-wide grep excluding
`docs/` returns sixteen files: seven `alembic/versions/*.py` (the create and
the drop must spell it), six `tests/*.py` (prose, plus
`test_migrations_postgres.py` exercising 0019 up and down),
`prompts/PHASE_2_PROMPT.md`, `scripts/snapshot_reads.py` (allowlisted, and the
name is a value in a `relname IN (…)` filter), and this one. The `.sql` file
is a dated, owner-executed one-off from 2026-08-13 whose header says *"Not run
from here. Owner-executed."*; nothing invokes it and its STEP 1 is read-only.

**Why it is still worth a row.** It would now fail with `relation
"imagery_snapshots" does not exist` if anyone re-ran it, and the guarantee the
pin advertises — *"no application or script file names the retired table"* —
is narrower than it reads. **Not fixed here**, because the choice is a real
one and this batch did not scope it: widen the pin to `*.sql` and then decide
what to do with the file (delete a finished one-off, or annotate it), versus
leave the pin at `*.py` and annotate. Recorded as STATUS.md **NORM-40**.

### F-DROP-2 — the standby worker was verified by label only

`e7845415f57728` is `stopped`, so `/proc` could not be read and this session
observed no process on it. Its image label and deployment tag match the
running machine's. Deploy-1's report verified all four at process level
because that machine was running then; this one cannot, and says so rather
than inheriting the earlier sentence. **Nothing to fix** — a stopped standby
takes the new image when it starts — but "GH_SHA on all four machines"
(item 1) is met at label level on four and at process level on three.

### F-DROP-3 — `audit_probe` still does not reach `fly logs` (NORM-36, observed again)

Every probe in this session emitted `audit_probe` events, and they appear only
in the captured stdout (`step4-drop-gates.txt` carries four of them inline
with the JSON). They are absent from `fly logs` for the same reason NORM-36
records. **Unchanged and unfixed**; noted because the row predicted the next
reading would hit it and the next reading did.

---

## 6. State left behind

* **ADR 0001 is complete in production.** All four steps deployed:
  step 1 `4de5728`, step 2 `efa4c63`, step 3 `c96dbf8`/`18ddb8e`, step 4
  deploy-1 `03867c4` and deploy-2 `bac725c`.
* **`imagery_snapshots` does not exist.** Dropped 2026-09-07T03:23:59Z by
  migration 0019 (`cb088f8`). Terminal row count 12,884; terminal counters in
  §2.1.
* **Production is on `bac725c5a7d196a8cd8c7aa4f6da84c7bb063bda`**, built
  2026-09-07T03:23:17Z, alembic **0019**, all four machines of both apps.
* **Production data:** 192 parcels, 6,743 scenes, 13,082 `parcel_scenes`,
  7 of 7 invariants at 0, landsat 43 × 192, provenance 6,156 / 505 / 82.
* **Serving is unaffected.** Seven surfaces smoked, all 200, including a
  rendered Landsat tile through the `/stac` callback and a parcel created
  inside the cooling span.
* **Nothing was pushed, deployed, healed or written.** This session's only
  effects on production are read-only queries and three files under `/tmp` on
  one API machine.
* **This session's commits are local and unpushed**, per CLAUDE.md — the
  record rides the owner's next push.

## 7. Deviations from the prompt

1. **The standby worker's process could not be checked** — F-DROP-2. Item 1's
   "GH_SHA on all four machines" is met; the NORM-32 process check is met on
   three of four, and the fourth is stopped.
2. **The battery's exit code is derived from its own artifact, not read** —
   §3.1. It scrolled out of the captured output and re-running costs thirteen
   whole-table scans.
3. **The gate probe ran twice** (03:27:17Z and 03:33:10Z, identical results).
   The first run's output went only to the terminal; the second was written to
   a file so the artifact is a capture rather than a transcription.
4. **The closing pre-drop counter reading is inherited, not re-verified**, as
   the prompt directed — and it is the one number in this report that cannot
   be re-derived, so §2.1 labels it at the top rather than in a footnote.
