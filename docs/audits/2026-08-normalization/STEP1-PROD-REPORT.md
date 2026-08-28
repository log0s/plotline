# Normalization step 1 — the production backfill

Step 1 of `docs/adr/0001-imagery-normalization.md` run against production.
The build, the local run and the local scoring are `STEP1-REPORT.md`; this
report covers only production.

**Outcome: the backfill ran, once, and every predicted quantity is
confirmed.** `scenes` holds 6,661 rows and `parcel_scenes` holds 12,884.
No STOP condition fired. One finding is new (**F5**, below) and it concerns
the *capture* of the run, not its result.

Prediction committed before the write: `93ee2ff`. Captures:
`prod-backfill-dryrun.txt`, `prod-backfill-run.txt` (truncated — see F5),
`prod-backfill-recheck.txt`. Scorecard: `PREDICTION-STEP1.md`, section
"Observed — production".

Everything against production was read-only except one command:
`python scripts/backfill_scenes.py --execute`, run once. Every read probe
set `conn.set_session(readonly=True)`. No sweep, no heal, no requeue, no
deploy, and no application code was changed.

---

## 1. Deploy gates

All four passed before anything else was measured.

| Gate | Evidence | Result |
|---|---|---|
| a. API sha | `GET https://log0s-plotline-api.fly.dev/api/v1/health` → `{"sha":"4de57282c8692b9787564b62b0019fda149c2ba4","built":"2026-08-28T17:00:32Z"}`, read 17:01:34Z. `git merge-base --is-ancestor 4de5728 4de57282c…` exits 0 | pass — the deployed sha *is* `4de5728` |
| b. Image labels | `fly image show -a log0s-plotline-api` and `-a plotline-worker`: all four machines carry `GH_SHA=4de57282c8692b9787564b62b0019fda149c2ba4` | pass — both apps on the health sha |
| c. Migration head | `SELECT version_num FROM alembic_version` → `0015` | pass |
| d. Tables exist and are empty | `scenes` 0 rows, `parcel_scenes` 0 rows, both in `information_schema.tables` | pass |

On (c): the revision id was read from the migration rather than inferred
from the filename. `alembic/versions/0015_scenes_and_parcel_scenes.py:3`
declares `Revision ID: 0015`, so filename prefix and revision id coincide
here — checked, not assumed.

All ten constraints migration 0015 defines are present, including the two the
ADR turns on:

```
uq_scenes_collection_item             UNIQUE (collection, item_id)
uq_parcel_scenes_parcel_source_group  UNIQUE (parcel_id, source, group_key)
ck_scenes_provenance                  CHECK (provenance IN ('snapshot','mosaic_url'))
ck_parcel_scenes_group_key            CHECK (group_key ~ '^[0-9]{4}(Q[1-4]|s)?$')
fk_parcel_scenes_parcel_id            FK → parcels(id) ON DELETE CASCADE
fk_parcel_scenes_scene_id             FK → scenes(id)
```

## 2. Prediction inputs, with timestamps

Read-only from inside the `log0s-plotline-api` machine, immediately before
the dry run.

| UTC | Measurement | Value |
|---|---|---|
| 17:03:01 | gate probe | `0015`; `scenes` 0; `parcel_scenes` 0 |
| 17:03:37 | `count(DISTINCT (stac_collection, stac_item_id))`, `count(*)`, `max(created_at)` on `imagery_snapshots` | **6156**, **12884**, **2026-08-27T19:41:01Z** |
| 17:03:38 | duplicate `(parcel_id, source, group_key)` groups | **0** groups, 0 rows |
| 17:03:38 | the same query returning per-group detail | 0 rows |
| 17:03:41 | `additional_cog_urls` cross-reference | 613 entries over 576 rows; **578 distinct URLs**, **73 matched**, **505 unmatched**, **0 unmatched non-NAIP** |
| 17:03:41 | `imagery_snapshots` by source | landsat 8127, naip 1305, sentinel2 2259, usgs_topo 1193 |

**The duplicate-group tripwire did not trip.** The ADR's change condition —
"step 1's backfill surfaces more duplicate groups than G3" — requires a
nonzero count; the count is zero, so the session continued as authorized.

The grouping SQL is the encoding the script actually uses, not a parallel
implementation that happens to agree. All three entries in
`app/tasks/timeline.py`'s `_SOURCES` carry `"selection_scope": "year"`
(`timeline.py:66,78,94`), and `usgs_topo` is given `"decade"` at
`scripts/backfill_scenes.py:94`; `SELECTION_SCOPE_BY_SOURCE` is built from
`_SOURCES` (`backfill_scenes.py:91-94`) rather than restated. That is exactly
`CASE WHEN source = 'usgs_topo' THEN decade ELSE year END`.

**One input the earlier record had wrong.** The figure carried into this
session was "540 unmatched" `additional_cog_urls`. That was an *entries*
count. The distinct-URL population — which is what Phase B synthesizes from —
is **505 unmatched of 578 distinct**. The consequence is arithmetic, not
structural: D = 505, so `scenes` = 6156 + 505 = 6661. The earlier figure is
left unedited in the Production section of `PREDICTION-STEP1.md` per the
frozen-record rule and corrected in the new section below it.

## 3. Dry run

`fly ssh console -a log0s-plotline-api -C "python scripts/backfill_scenes.py"`,
17:04:03–17:04:10, exit status 0. Full capture: `prod-backfill-dryrun.txt`.

```
imagery_snapshots rows: 12884
duplicate (parcel_id, source, group_key) groups: 0

planned scenes: 6661 (505 synthesized from mosaic URLs)
planned parcel_scenes: 12884

scenes already present: 0

Dry run — would insert 6661 scene(s) and 12884 parcel_scene(s). Nothing written.
```

**Phase B did not abort**, and that is worth stating plainly because the
prompt named it as a plausible outcome: production's unmatched-URL population
is 5.7x local's (505 vs 88), and this was the first time the refusal met a
population that size. All 505 parsed as NAIP `v002` tile URLs. The script's
result and the independent SQL agree — 0 unmatched non-NAIP URLs — so
STEP1-REPORT's F3 extends from the local population to the production one.

No anomalies section was printed.

## 4. Execution

`fly ssh console -a log0s-plotline-api -C "python scripts/backfill_scenes.py --execute"`
on machine `825d69b7e46618`. Started 17:05:22 UTC. Transaction opened
17:05:26. Committed between 17:14:47 and 17:15:35 — roughly ten minutes for
19,545 row-by-row inserts through pgbouncer to Neon. **Run once.**

The run's stdout was lost; see F5. What committed was measured directly:

| Measurement (17:16:47) | Value |
|---|---|
| `scenes` | **6661** |
| — `provenance = 'snapshot'` | 6156 |
| — `provenance = 'mosaic_url'` | 505 |
| `parcel_scenes` | **12884** |
| `scenes` with `footprint IS NOT NULL` | 0 |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 |
| dangling `mosaic_scene_ids` references | 0 |
| `parcel_scenes` rows with no corresponding snapshot row | 0 |
| `parcel_scenes` carrying a mosaic / total references | 576 / 613 |
| `imagery_snapshots` rows / distinct items after | 12884 / 6156, both unchanged |
| distinct parcels in `parcel_scenes` | 189 |

`parcel_scenes` by source equals `imagery_snapshots` by source exactly:
landsat 8127, naip 1305, sentinel2 2259, usgs_topo 1193.

| source | provenance | scenes | with platform | with bbox | with resolution_m |
|---|---|---|---|---|---|
| landsat | snapshot | 3174 | 3174 | 3174 | 3174 |
| naip | mosaic_url | 505 | 0 | 0 | 0 |
| naip | snapshot | 1102 | 0 | 1102 | 1102 |
| sentinel2 | snapshot | 1111 | 1111 | 1111 | 1111 |
| usgs_topo | snapshot | 769 | 0 | 769 | 0 |

The mosaic figures match the source table exactly — 613 references over 576
rows on both sides — so ADR rule 5 holds on production with nothing dropped.
`usgs_topo`'s missing `resolution_m` is a property of `imagery_snapshots`,
which carries none for topo; the column is copied, not derived.

## 5. Idempotence

The dry run again at 17:16:10–17:16:15, immediately after the commit
(`prod-backfill-recheck.txt`):

```
planned scenes: 6661 (505 synthesized from mosaic URLs)
planned parcel_scenes: 12884
scenes already present: 6661

Dry run — would insert 0 scene(s) and 0 parcel_scene(s). Nothing written.
```

**Zero to write on both tables**, no drift reported. Nothing had to be
distinguished from live-traffic rows, because there were none: 0
`imagery_snapshots` rows created after 17:00Z.

This recheck does double duty. It is the idempotence result, and — because
its plan (6661 / 505 / 12884) is identical to the pre-run plan and it finds
all 6,661 scenes already present — it is an independent confirmation that
what committed equals what was planned, established without the lost stdout.

## 6. Scorecard

Full version in `PREDICTION-STEP1.md`, "Observed — production". Predictions
were committed as `93ee2ff` before the write and have not been edited.

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| `scenes` rows | 6661 | 6661 | confirmed |
| — `provenance = 'snapshot'` | 6156 | 6156 | confirmed |
| — `provenance = 'mosaic_url'` | 505 | 505 | confirmed |
| `parcel_scenes` rows | 12884 | 12884 | confirmed |
| duplicate groups encountered | 0 | 0 | confirmed |
| `scenes` with `footprint IS NOT NULL` | 0 | 0 | confirmed |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 | 0 | confirmed |
| mosaic URLs that failed to parse | 0 | 0 | confirmed |
| `imagery_snapshots` rows after the run | 12884 | 12884 | confirmed |
| dangling `mosaic_scene_ids` references | 0 | 0 | confirmed |
| anomalies reported | 0 | 0 (inferred — F5) | confirmed, indirectly |

**Every line confirmed. No deviations.**

### The drift assumption, checked rather than assumed

The prediction conditioned `parcel_scenes = 12884` on no intervening writes
and named what would have to account for an overshoot. There was none, and
the window was quiet by measurement:

* `imagery_snapshots` rows created at or after 17:00Z: **0**.
* `timeline_task_years` rows created at or after 17:00Z: **0**.
* Newest `timeline_task_years` row overall: 2026-08-27T22:00:44Z.
* Newest `imagery_snapshots` row overall: 2026-08-27T19:41:01Z — unchanged
  from the 17:03:37 reading.

The 17:03:37 measurement and the 17:15 commit describe the same table.

### Reading the ledger alongside the count, per NORM-3

NORM-3 says a duplicate-group count measured after a sweep is only as
complete as that sweep's upstream success rate — a `failed` period is one
reconciliation could not collapse, so it can hide a duplicate a later retry
would expose. The last 24 hours of `timeline_task_years`:

| outcome | rows |
|---|---|
| ok | 15179 |
| absent | 2181 |
| indeterminate | 9 |
| suppressed | 9 |
| **failed** | **0** |

**Zero `failed` rows.** The 0 duplicate groups at 17:03:38 is a real zero,
not one standing on an unretried upstream failure. The 9 `indeterminate`
rows are `usgs_topo` whole-source (`'*'`) keys — the same shape as the three
the local run examined, which carry no duplicate groups and no bearing on the
backfill.

## 7. Findings

### F5 — The execute run's own output was lost to a client-side timeout, and is unrecoverable

**New. Operational, not a data defect. Open — the fix belongs to whoever runs
the next long production script.**

The local `fly ssh console` client was killed by a 2-minute client-side
timeout at 17:07:22, about two minutes into a ten-minute run. **The remote
process was not killed.** It continued as pid 655 and committed normally.
Everything the script printed after the connection banner went to the dead
client's stdout and is gone, including the `Written:` block and the structlog
summary at `scripts/backfill_scenes.py:622` — `fly logs -a
log0s-plotline-api` carries the app's main uvicorn process, not an SSH
session's output.

**What was done instead of re-running.** The run was *not* re-run: re-running
is not consequence-free, the authorization covered exactly one write, and the
state was recoverable by reading. Read-only probes from inside the machine
established what was happening while it was still happening:

```
17:07:50  scenes 0, parcel_scenes 0        (uncommitted, not empty)
17:08:31  /proc: pid=655 state=S cmd=python scripts/backfill_scenes.py --execute
          pg_stat_activity: 'idle in transaction', xact_start 17:05:26.297067+00,
            query "INSERT INTO scenes (id, source, collection, item_id, ..."
          pg_locks: RowExclusiveLock on scenes, granted
17:08:53  same transaction, query now "INSERT INTO parcel_scenes (..."
17:09:14 .. 17:14:47  pid 655 alive, same transaction, both tables still 0
17:15:35  pid 655 gone; scenes 6661, parcel_scenes 12884; no open transaction
```

The script's single `db.commit()` is at `scripts/backfill_scenes.py:620`,
after both `_insert_scenes` and `_insert_parcel_scenes`, so the write is
all-or-nothing. The observed 0 → 6661/12884 step is that transaction landing.

**What this costs.** Row counts and distributions are fully verified — direct
measurement is stronger evidence than a printout. What is *not* directly
verified is the `anomalies` and `drift` lists the script would have printed.
Both are predicted zero and the indirect evidence is good: an anomaly (a
snapshot-attribute disagreement, or a synthesized id colliding with a Phase A
key) reduces the scene total below plan, and the total is exactly the planned
6661; `drift` is empty by construction on a first run into empty tables,
since it reports only pre-existing `parcel_scenes` rows that disagree, and
there were none. Recorded rather than smoothed over, because "the capture is
incomplete" is precisely the thing that must not be quietly rounded to "the
capture is fine".

**The general shape, for next time.** A `fly ssh console -C` session is not a
supervisor: killing the client leaves the remote process running, so a
timeout is neither an abort nor a rollback, and treating it as either would
be wrong in both directions — re-running risks a double write, and reporting
failure would have been false. Any production script expected to run longer
than the client's timeout should either write its own report to a file inside
the machine, or log through a channel `fly logs` carries. `prod-backfill-run.txt`
carries this note inline so the truncated capture cannot be misread later.

### F1 (STEP1-REPORT) — confirmed at production scale

Not new; the production numbers are. **505 production `scenes` rows carry a
URL-derived candidate `item_id` rather than a catalogued one**, all NAIP, all
`provenance = 'mosaic_url'`, all with NULL `footprint` and NULL
`resolution_m`. The earlier record said 540; that counted entries, and the
distinct-row figure is 505. `WHERE provenance = 'mosaic_url'` is the
enrichment pass's work queue. Nothing may treat those `item_id`s as
catalogued identifiers until that pass runs. STATUS.md NORM-4, updated.

### F3 (STEP1-REPORT) — extended to the production population

No mosaic URL failed to parse and none was non-NAIP, across all 505 unmatched
production URLs — checked twice, by the script (which would have refused on
the first exception) and by independent SQL. Local checked 88; production
checked 505.

## 8. What was left behind

No STOP fired, so there is no partial state to describe. Production now
holds:

* `scenes` — 6,661 rows, 6,156 `provenance='snapshot'` and 505
  `provenance='mosaic_url'`, every `footprint` NULL.
* `parcel_scenes` — 12,884 rows over 189 parcels, every `selected_by` NULL,
  576 rows carrying 613 mosaic references, none dangling.
* `imagery_snapshots` — 12,884 rows, unchanged. Nothing read from it moved,
  and `reconcile_source_snapshots` is unmodified: **nothing in production
  reads either new table.** Steps 2 and 3 own that.

Migration 0015 was already deployed and applied before this session began;
this session added rows, not schema.

## 9. Forward risk for step 2

**Synthesized scenes carry candidate item ids, and `UNIQUE (collection,
item_id)` will not catch the collision that follows.**

505 production `scenes` rows have an `item_id` parsed from a tile URL. Per
F1, such an id equals the catalogued id only sometimes — it is far more often
a proper prefix, and occasionally neither. So when step 2's dual-write
inserts a scene for a *real* catalogued NAIP item that is physically the same
tile as one of these 505, the two rows will differ in `item_id`, the unique
constraint will be satisfied, and production will hold **two `scenes` rows for
one physical item** with no error raised.

The constraint is not the defence here, because the constraint is on the
wrong key: it protects against duplicate *ids*, and the failure mode is one
item under two different ids.

Two workable defences, either of which step 2 must adopt before it writes:

1. **Reconcile by `cog_url` before insert.** `cog_url` is the tile's actual
   address and is the key the backfill itself matched on (Phase B synthesizes
   only for URLs no row's `cog_url` carries). A dual-write that looks up by
   `cog_url` first finds the synthesized row and updates it in place.
2. **Enrich before dual-write.** Run the STAC pass over
   `WHERE provenance = 'mosaic_url'` first, replacing candidate ids with
   catalogued ones and filling `footprint`, so that by the time step 2 writes,
   `(collection, item_id)` is a trustworthy key for the whole table.

Option 2 is the more durable one — it removes the class of problem rather
than routing around it — and it is work the ADR already anticipates. Option 1
is what step 2 needs regardless if the enrichment pass has not run first.
Recorded as STATUS.md NORM-7.
