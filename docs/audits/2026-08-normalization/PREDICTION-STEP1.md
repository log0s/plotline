# Prediction — normalization step 1 backfill

Written **2026-08-28**, before `scripts/backfill_scenes.py --execute` has
been run against any database. Step 1 of
`docs/adr/0001-imagery-normalization.md`: create `scenes` and
`parcel_scenes` (migration `0015`, commit `822faca`) and backfill them from
`imagery_snapshots`.

Per the project's prediction rule, the Observed section below is appended
after the run and this half is never edited to match it.

---

## Local database

### State the prediction is made against

The local sweep (this batch's item 1) ran first, so local's duplicate state
matches production's. Post-sweep, `alembic_version = 0015`:

```sql
SELECT count(*) AS snapshot_rows,
       count(DISTINCT (stac_collection, stac_item_id)) AS distinct_items
FROM imagery_snapshots;
```

| snapshot_rows | distinct_items |
|---|---|
| 2945 | 1174 |

```sql
WITH e AS (SELECT DISTINCT unnest(additional_cog_urls) u FROM imagery_snapshots
           WHERE additional_cog_urls IS NOT NULL AND array_length(additional_cog_urls,1) > 0)
SELECT count(*) AS distinct_mosaic_urls,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)) AS matched,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)) AS unmatched,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)
                          AND u NOT LIKE 'https://naipeuwest.blob.core.windows.net/naip/v002/%') AS unmatched_non_naip
FROM e;
```

| distinct_mosaic_urls | matched | unmatched | unmatched_non_naip |
|---|---|---|---|
| 115 | 27 | 88 | 0 |

```sql
WITH g AS (
  SELECT parcel_id, source,
    CASE WHEN source = 'usgs_topo'
         THEN ((EXTRACT(YEAR FROM capture_date)::int / 10) * 10)::text || 's'
         ELSE EXTRACT(YEAR FROM capture_date)::int::text END AS group_key
  FROM imagery_snapshots)
SELECT count(*) FROM (
  SELECT count(*) FROM g GROUP BY parcel_id, source, group_key HAVING count(*) > 1) d;
```

→ **0** duplicate groups (269 before the sweep).

### Predicted

| Quantity | Predicted | Derivation |
|---|---|---|
| `scenes` rows | **1262** | 1174 distinct `(stac_collection, stac_item_id)` + 88 distinct unmatched mosaic URLs |
| — of which `provenance = 'snapshot'` | **1174** | one per distinct catalogued item |
| — of which `provenance = 'mosaic_url'` | **88** | one per distinct unmatched mosaic URL |
| `parcel_scenes` rows | **2945** | one per `imagery_snapshots` row |
| duplicate groups encountered | **0** | the sweep cleared all 269; a nonzero count aborts the run before any write |
| `scenes` with `footprint IS NOT NULL` | **0** | `imagery_snapshots` holds no item geometry, Phase A or B |
| `parcel_scenes` with `selected_by IS NOT NULL` | **0** | history never recorded the selecting SHA |
| mosaic URLs that fail to parse | **0** | all 88 unmatched are `naip/v002` tile URLs with a date-suffixed filename |

**Two ways `scenes` could come out below 1262, both of which the script
reports rather than swallows.** A synthesized `(collection, item_id)` could
collide with a Phase A key — the URL matched no row's `cog_url` but derives
to an item some row already carries — or two distinct unmatched URLs could
derive to the same candidate id. Either would make the total smaller by the
number of collisions and would appear in the run's anomalies list. Neither
is predicted to occur.

**Nothing is predicted to change in `imagery_snapshots`.** The script only
reads it; the row count after the run must still be 2945.

**Disclosure about how these numbers were reached.** The script was run in
its dry-run mode before this file was written, and its planner reported the
same 1262 / 88 / 2945. The table above is nevertheless derived from the SQL
shown, independently of the script, precisely so the prediction is not
merely a restatement of the code under test. A disagreement between the two
would itself have been the finding.

---

## Production

Not run this session — production is untouched, and the inputs below were
derived read-only on 2026-08-28 and given to this session rather than
measured by it.

| Input | Value |
|---|---|
| distinct `(stac_collection, stac_item_id)` | 6,156 |
| `imagery_snapshots` rows | 12,884 |
| duplicate `(parcel_id, source, group_key)` groups | 0 |
| `additional_cog_urls` entries | 613 total, 73 matched, 540 unmatched |

Predicted, when the production backfill runs:

* `scenes` = **6,156 + D**, where D is the count of *distinct* unmatched
  mosaic URLs. D ≤ 540, since 540 counts entries and not distinct URLs — the
  local ratio was 88 distinct out of 112 entries, so D well under 540 is the
  expectation, but the exact value is derived at run time and is not
  predicted here.
* `parcel_scenes` = **12,884**.
* duplicate groups encountered = **0**.

**The `parcel_scenes` figure assumes no intervening writes, and that
assumption is not safe.** Production keeps taking traffic: every timeline
request that fetches imagery inserts and reconciles `imagery_snapshots`
rows, so 12,884 is a 2026-08-28 reading, not a constant. The production
prediction to score is therefore "`parcel_scenes` equals the
`imagery_snapshots` row count read in the same transaction as the backfill",
and the run must record that count rather than compare against 12,884. A
difference from 12,884 alone is drift, not a deviation.

The ADR's context section says 14,534 rows / 184 parcels from a 2026-08-24
snapshot. Prod is now 12,884; the delta is consistent with the G8 completion
sweep's Sentinel-2 quarter-deduplication deletions. The original figure is
left in place and the update is recorded in the ADR's dated amendment, per
the frozen-record rule.

---

## Observed

**Local, 2026-08-28.** `docker compose exec api python
scripts/backfill_scenes.py --execute`, against the post-sweep database at
`alembic_version = 0015`, script at commit `b3f8e94`:

```
imagery_snapshots rows: 2945
duplicate (parcel_id, source, group_key) groups: 0

planned scenes: 1262 (88 synthesized from mosaic URLs)
planned parcel_scenes: 2945

scenes already present: 0

Written:
  scenes inserted:        1262 (of which synthesized: 88)
  scenes already present: 0
  parcel_scenes inserted: 2945
  parcel_scenes present:  0
```

No anomalies were reported: no snapshot rows disagreed about an item's
attributes, no mosaic URL derived to an already-known item, and no URL
failed to parse.

### Scorecard

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| `scenes` rows | 1262 | 1262 | confirmed |
| — `provenance = 'snapshot'` | 1174 | 1174 | confirmed |
| — `provenance = 'mosaic_url'` | 88 | 88 | confirmed |
| `parcel_scenes` rows | 2945 | 2945 | confirmed |
| duplicate groups encountered | 0 | 0 | confirmed |
| `scenes` with `footprint IS NOT NULL` | 0 | 0 | confirmed |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 | 0 | confirmed |
| mosaic URLs that failed to parse | 0 | 0 | confirmed |
| `imagery_snapshots` rows after the run | 2945 | 2945 | confirmed |

**Every line confirmed; no deviations to explain.**

### Checks run after the write

```sql
SELECT count(*) FROM (SELECT unnest(mosaic_scene_ids) sid FROM parcel_scenes
                      WHERE mosaic_scene_ids IS NOT NULL) m
WHERE NOT EXISTS (SELECT 1 FROM scenes s WHERE s.id = m.sid);
```
→ **0** dangling mosaic references. 141 `parcel_scenes` rows carry a mosaic,
162 references in total — matching the 141 snapshot rows and 162
`additional_cog_urls` entries exactly, so ADR rule 5 ("every tile in a mosaic
is a first-class scene") holds with nothing dropped.

```sql
SELECT count(*) FROM parcel_scenes ps WHERE NOT EXISTS (
  SELECT 1 FROM imagery_snapshots i
  JOIN scenes s ON s.collection = i.stac_collection AND s.item_id = i.stac_item_id
  WHERE i.parcel_id = ps.parcel_id AND i.source = ps.source AND s.id = ps.scene_id);
```
→ **0** `parcel_scenes` rows that do not correspond to a snapshot row.

`platform` per source and provenance:

| source | provenance | scenes | with platform | with bbox |
|---|---|---|---|---|
| landsat | snapshot | 618 | 618 | 618 |
| naip | mosaic_url | 88 | 0 | 0 |
| naip | snapshot | 200 | 0 | 200 |
| sentinel2 | snapshot | 213 | 213 | 213 |
| usgs_topo | snapshot | 143 | 0 | 143 |

Every Landsat and Sentinel-2 scene got a platform and no NAIP or topo scene
did, which is the intended outcome: those two are the only sources whose
item ids name a satellite.

### Re-run

The script was run a second time with `--execute`, unchanged:

```
scenes inserted:        0 (of which synthesized: 0)
scenes already present: 1262
parcel_scenes inserted: 0
parcel_scenes present:  2945
```

No drift reported and both row counts unchanged, so the idempotency claim is
observed rather than asserted.

---

## Production prediction

Written **2026-08-28**, after the production dry run and **before**
`scripts/backfill_scenes.py --execute` has been run against production. This
section is committed before the execute step and is never edited afterwards;
the production Observed section is appended below it.

The Production section further up this file was written on 2026-08-28 from
figures *given* to the previous session. Everything here was measured by this
session, read-only, against production. Where the two differ the measured
value governs and the earlier one is left in place unedited.

### Deploy gates (all passed before any of this was measured)

| Gate | Evidence |
|---|---|
| API sha | `GET /api/v1/health` → `sha 4de57282c8692b9787564b62b0019fda149c2ba4`, `built 2026-08-28T17:00:32Z`. `git merge-base --is-ancestor 4de5728 4de5728…` → 0 |
| `log0s-plotline-api` image | `fly image show` — both machines label `GH_SHA=4de57282c8692b9787564b62b0019fda149c2ba4` |
| `plotline-worker` image | `fly image show` — both machines label the same SHA |
| migration head | `SELECT version_num FROM alembic_version` → `0015`, which is the `revision` id declared in `alembic/versions/0015_scenes_and_parcel_scenes.py:3`, not an assumption from the filename |
| tables exist and are empty | `scenes` 0 rows, `parcel_scenes` 0 rows; all ten constraints from 0015 present, including `uq_scenes_collection_item` and `uq_parcel_scenes_parcel_source_group` |

### Measured inputs, with timestamps

Every query below ran read-only (`conn.set_session(readonly=True)`) inside
the `log0s-plotline-api` Fly machine.

| Timestamp (UTC) | Query | Result |
|---|---|---|
| 17:03:01 | gate probe (alembic, table existence, row counts, constraints) | `0015`; `scenes` 0; `parcel_scenes` 0 |
| 17:03:37 | `count(DISTINCT (stac_collection, stac_item_id)), count(*), max(created_at)` on `imagery_snapshots` | **6156**, **12884**, `2026-08-27T19:41:01Z` |
| 17:03:38 | duplicate `(parcel_id, source, group_key)` groups, VERIFICATION 6b encoding | **0** groups, 0 rows |
| 17:03:38 | the same query returning group detail | 0 rows |
| 17:03:41 | `additional_cog_urls` cross-reference | 613 entries over 576 rows; **578 distinct URLs**, **73 matched**, **505 unmatched**, **0 unmatched non-NAIP** |
| 17:03:41 | rows by source | landsat 8127, naip 1305, sentinel2 2259, usgs_topo 1193 |
| 17:04:03–17:04:10 | dry run, `python scripts/backfill_scenes.py` | see `prod-backfill-dryrun.txt` |

Two of these correct the figures the earlier Production section carried. The
duplicate-group count is 0 as given, so the ADR's change condition (step 1
surfacing more duplicate groups than G3) did **not** trip. But the "540
unmatched" figure was an *entries* count; the distinct-URL population is
**505 unmatched of 578 distinct**, and 505 is what Phase B synthesizes from.
D — left unpredicted by the earlier section, deliberately — is therefore
**505**.

The grouping SQL is the same encoding the script uses, not a parallel
reimplementation that happens to agree: all three entries in
`app/tasks/timeline.py`'s `_SOURCES` carry `"selection_scope": "year"`
(`timeline.py:66,78,94`) and `usgs_topo` is given `"decade"` at
`scripts/backfill_scenes.py:94`, which is exactly `CASE WHEN source =
'usgs_topo' THEN decade ELSE year END`.

### Dry run

```
imagery_snapshots rows: 12884
duplicate (parcel_id, source, group_key) groups: 0

planned scenes: 6661 (505 synthesized from mosaic URLs)
planned parcel_scenes: 12884

scenes already present: 0

Dry run — would insert 6661 scene(s) and 12884 parcel_scene(s). Nothing written.
```

Exit status 0, no anomalies section printed. **Phase B did not abort.** All
505 unmatched URLs parsed as NAIP `v002` tile URLs — the prompt's plausible
STOP (prod's unmatched population being 5x local's and finally exercising the
refusal) did not fire, and the SQL agrees with the script: 0 unmatched
non-NAIP URLs. F3's local finding extends to the production population.

### Predicted

| Quantity | Predicted | Derivation |
|---|---|---|
| `scenes` rows | **6661** | 6156 distinct `(stac_collection, stac_item_id)` + 505 distinct unmatched mosaic URLs |
| — of which `provenance = 'snapshot'` | **6156** | one per distinct catalogued item |
| — of which `provenance = 'mosaic_url'` | **505** | one per distinct unmatched mosaic URL |
| `parcel_scenes` rows | **12884** | one per `imagery_snapshots` row |
| duplicate groups encountered | **0** | measured 0 at 17:03:38; a nonzero count aborts before any write |
| `scenes` with `footprint IS NOT NULL` | **0** | `imagery_snapshots` holds no item geometry, Phase A or B |
| `parcel_scenes` with `selected_by IS NOT NULL` | **0** | history never recorded the selecting SHA |
| mosaic URLs that fail to parse | **0** | the dry run parsed all 505 without refusing |
| `imagery_snapshots` rows after the run | **12884** | the script only reads that table |
| dangling `mosaic_scene_ids` references | **0** | every entry, synthesized included, is a `scenes` row (ADR amendment, rule 5) |
| anomalies reported | **0** | no attribute disagreement, no synthesized-id collision |

`scenes` can come out **below** 6661 in two ways the script reports rather
than swallows: a synthesized `(collection, item_id)` colliding with a Phase A
key, or two distinct unmatched URLs deriving to the same candidate id. Given
F1 — a NAIP filename is a *prefix* of its item id far more often than it
equals it — both are likelier here than locally, where neither occurred over
88 URLs. 505 URLs is a 5.7x larger population. Neither is predicted, but a
shortfall accompanied by an anomalies list is an explained deviation, and a
shortfall without one is a finding.

### The no-intervening-writes assumption, stated explicitly

`parcel_scenes = 12884` assumes `imagery_snapshots` does not change between
the 17:03:37 reading and the execute step. That assumption is **not**
guaranteed: production takes live traffic, and any timeline request that
fetches imagery inserts and reconciles rows in that table.

Two things bound the risk, and neither eliminates it:

* The newest `created_at` in `imagery_snapshots` at 17:03:37 was
  **2026-08-27T19:41:01Z** — 21 hours before the reading. No imagery row had
  been written that day.
* The measurement-to-execution window is minutes, and the script re-reads
  `imagery_snapshots` itself at execute time; it does not replay the 12884.

So the quantity actually being scored is: **`parcel_scenes` equals the
`imagery_snapshots` row count the execute run reads and prints in its own
header.** If that header prints 12884, the prediction is confirmed outright.

If it prints more, that is an **overshoot**, and scoring treats it as
explainable drift **if and only if** the ledger and request records for the
17:03:37 → execute window account for it: new `imagery_snapshots` rows whose
`created_at` falls inside the window, matched by `timeline_task_years` rows
for the same parcels and sources. An overshoot the record cannot account for
is a finding, not drift. A count *below* 12884 is a deviation in either
direction — the script never deletes, so rows disappearing means something
else did.

---

## Observed — production

**2026-08-28.** `python scripts/backfill_scenes.py --execute` inside
`log0s-plotline-api` machine `825d69b7e46618`, image
`GH_SHA=4de57282c8692b9787564b62b0019fda149c2ba4`. Started 17:05:22 UTC,
transaction opened 17:05:26, committed between 17:14:47 and 17:15:35 — about
ten minutes for 19,545 row-by-row inserts through pgbouncer. Run **once**.

### The run's own stdout was lost, and the outcome is reconstructed

Stated before the numbers because it changes what the numbers rest on. The
local `fly ssh console` client was killed by a 2-minute client-side timeout at
17:07:22. The remote process was not: it continued as pid 655 and committed
normally. Its printed report and its structlog summary
(`scripts/backfill_scenes.py:622`) both went to the dead client's stdout and
are unrecoverable — `fly logs` carries the app's main uvicorn process, not an
SSH session's output.

So this scorecard is **not** a transcription of the script's own report. It is
measured from the database afterwards, plus the read-only observations taken
while the run was still in flight, all recorded in
`prod-backfill-run.txt`'s appended note. Two consequences worth being explicit
about:

* **What is fully verified:** every row count, every distribution, and the
  idempotence result. These are direct measurements and are stronger evidence
  than the script's own printout would have been.
* **What is not directly verified:** the `anomalies` and `drift` lists the
  script would have printed. Predicted zero for both. The evidence for that
  prediction is indirect but not weak — an anomaly (a snapshot-attribute
  disagreement, or a synthesized id colliding with a Phase A key) reduces the
  scene total below plan, and the total came out at exactly the planned 6661;
  `drift` is empty by construction on a first run into empty tables, since it
  reports only pre-existing `parcel_scenes` rows that disagree, and there were
  none. Recorded as finding **F5** in `STEP1-PROD-REPORT.md`, because "the
  capture is incomplete" is exactly the thing that must not be smoothed over.

The run was **not** re-run to recover the output. Re-running is not free of
consequence, the prompt authorized exactly one write, and the state was
already recoverable by reading.

### Scorecard

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| `scenes` rows | 6661 | **6661** | confirmed |
| — `provenance = 'snapshot'` | 6156 | **6156** | confirmed |
| — `provenance = 'mosaic_url'` | 505 | **505** | confirmed |
| `parcel_scenes` rows | 12884 | **12884** | confirmed |
| duplicate groups encountered | 0 | **0** | confirmed |
| `scenes` with `footprint IS NOT NULL` | 0 | **0** | confirmed |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 | **0** | confirmed |
| mosaic URLs that failed to parse | 0 | **0** | confirmed |
| `imagery_snapshots` rows after the run | 12884 | **12884** | confirmed |
| dangling `mosaic_scene_ids` references | 0 | **0** | confirmed |
| anomalies reported | 0 | **0 (inferred, see above)** | confirmed, indirectly |

**Every line confirmed. No deviations.**

### The drift assumption held, and it was checked rather than assumed

The prediction made `parcel_scenes = 12884` conditional on no intervening
writes and named the evidence that would have to account for an overshoot.
There was no overshoot, and the window was genuinely quiet:

```sql
SELECT count(*) FROM imagery_snapshots
WHERE created_at >= TIMESTAMPTZ '2026-08-28 17:00:00+00';        -- 0

SELECT outcome, count(*) FROM timeline_task_years
WHERE created_at >= TIMESTAMPTZ '2026-08-28 17:00:00+00'
GROUP BY outcome;                                                 -- 0 rows

SELECT max(created_at) FROM timeline_task_years;   -- 2026-08-27 22:00:44+00
SELECT count(*), max(created_at) FROM imagery_snapshots;
                                       -- 12884, 2026-08-27 19:41:01+00
```

No `imagery_snapshots` row and no M4 ledger row was written during the
execution window. The newest row in either table predates the run by 19 and 21
hours respectively, so the 17:03:37 measurement and the 17:15 commit describe
the same table.

**Reading the ledger alongside the count, per NORM-3.** The last 24 hours of
`timeline_task_years` are 15,179 `ok`, 2,181 `absent`, 9 `indeterminate`, 9
`suppressed` — and **zero `failed`**. NORM-3's warning is that a duplicate-group
count measured after a sweep is only as complete as that sweep's upstream
success rate: a `failed` year is a period reconciliation could not collapse, so
it can hide a duplicate that a later retry would expose. There are no `failed`
rows behind this measurement. The 0 duplicate groups at 17:03:38 is therefore a
real zero, not a zero standing on an unretried failure, and the ADR's change
condition ("step 1's backfill surfaces more duplicate groups than G3") did not
trip. The 9 `indeterminate` rows are `usgs_topo` whole-source (`'*'`) keys — the
same shape as local's three, which the local run established carry no duplicate
groups and no bearing on the backfill.

### Post-write checks

| Check | Result |
|---|---|
| `scenes` with `footprint IS NOT NULL` | 0 of 6661 |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 of 12884 |
| dangling `mosaic_scene_ids` references | 0 |
| `parcel_scenes` rows with no corresponding snapshot row | 0 |
| `parcel_scenes` rows carrying a mosaic / total references | 576 / 613 |
| `imagery_snapshots` rows, and distinct items, after the run | 12884 / 6156 — both unchanged |
| distinct parcels in `parcel_scenes` | 189 |

The mosaic figures match the source table exactly: `imagery_snapshots` holds
613 `additional_cog_urls` entries across 576 rows, and `parcel_scenes` holds
613 references across 576 rows. ADR rule 5 holds on production with nothing
dropped and nothing invented.

`parcel_scenes` by source equals `imagery_snapshots` by source, row for row:
landsat 8127, naip 1305, sentinel2 2259, usgs_topo 1193.

| source | provenance | scenes | with platform | with bbox | with resolution_m |
|---|---|---|---|---|---|
| landsat | snapshot | 3174 | 3174 | 3174 | 3174 |
| naip | mosaic_url | 505 | 0 | 0 | 0 |
| naip | snapshot | 1102 | 0 | 1102 | 1102 |
| sentinel2 | snapshot | 1111 | 1111 | 1111 | 1111 |
| usgs_topo | snapshot | 769 | 0 | 769 | 0 |

Every Landsat and Sentinel-2 scene got a platform and no NAIP or topo scene
did — the same result as local, and the intended one: those two are the only
sources whose item ids name a satellite. Synthesized NAIP rows carry neither
bbox nor `resolution_m`, as designed (STEP1-REPORT §6 item 8).

`usgs_topo`'s 769 rows having no `resolution_m` is a property of the source
data, not of the backfill — the column is copied straight from
`imagery_snapshots`, which does not carry one for topo.

### Idempotence

Immediately after the commit, the dry run again (`prod-backfill-recheck.txt`,
17:16:10–17:16:15):

```
imagery_snapshots rows: 12884
duplicate (parcel_id, source, group_key) groups: 0

planned scenes: 6661 (505 synthesized from mosaic URLs)
planned parcel_scenes: 12884

scenes already present: 6661

Dry run — would insert 0 scene(s) and 0 parcel_scene(s). Nothing written.
```

**Zero to write on both tables**, and no drift reported. The plan is identical
to the pre-run plan (6661 / 505 / 12884), which is the second, independent
confirmation that what committed is exactly what was planned — the check does
not depend on the lost stdout. No live-traffic rows had to be distinguished
from re-run non-idempotence, because there were none: 0 `imagery_snapshots`
rows created after 17:00Z.
