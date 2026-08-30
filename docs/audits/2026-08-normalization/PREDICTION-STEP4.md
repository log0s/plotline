# Prediction — step 4's local fleet sweep

Written before the sweep runs, and committed before it runs. Scored in a later
commit; this half is never edited.

---

## 0. Blindness, stated first

**This prediction is blind in the sense that matters and I will say exactly
where it is not.**

* **Not run:** the fleet sweep itself. `scripts/requeue_parcels.py` over all 45
  local parcels has not been run at this commit, in any mode, not even
  `--dry-run`. No outcome below has been observed.
* **Run, deliberately, and committed as artifacts:** two *pre-run* readings —
  `step4-pre-sweep.json` (`scripts/normalization_invariants.py`) and
  `step4-reads-t0.json` (`scripts/snapshot_reads.py`). A prediction of deltas
  needs a baseline, and every prior prediction in this arc took one the same
  way. §2 is that baseline; it is measurement, not outcome.
* **Run:** `scripts/normalization_invariants.py` exists because of this batch
  and its *first* execution was the §2 baseline. It has not been run against a
  post-sweep state.

The STEP3 §0 lesson — a prediction is worth exactly what its timing is worth —
is why this section leads. If the sweep turns out to need a fix to the battery
or to the requeue path before it can run at all, that is a deviation and it
goes at the top of the report, not in a footnote.

---

## 1. What is being run

```
docker compose exec -T api python scripts/requeue_parcels.py \
    --skip-deploy-check --sources naip,landsat,sentinel2,usgs_topo <45 parcel ids>
```

against the local PostGIS database at migration **0018** (0019 is committed
and **not applied** — the local table still physically exists, which is
deploy-1's production state exactly), with the code cutover `329a8a6` in
place. Then, once the worker drains:

```
docker compose exec -T api python scripts/normalization_invariants.py --out …
docker compose exec -T api python scripts/snapshot_reads.py \
    --baseline /tmp/step4-reads-t0.json --out …
```

The census and property sources are out of scope: they write neither table,
and including them would spend upstream calls on a question this sweep is not
asking.

## 2. Baseline, read 2026-08-29T21:45–21:46Z

`step4-pre-sweep.json`:

| quantity | value |
|---|---|
| `parcels` | **45** |
| `scenes` | **1,342** |
| `parcel_scenes` | **3,082** |
| every zero-check | **0** (7 of 7) |
| `scenes` by provenance | snapshot 1,174 · enriched 88 · selection 80 |
| landsat per parcel | **43**, on all 45 parcels (1,935 rows) |

Ledger, latest outcome per (parcel, source, group): landsat ok 1,933 / failed
2; naip ok 323 / absent 437 / suppressed 5; sentinel2 ok 539 / absent 1;
usgs_topo ok 285 / indeterminate 3.

`step4-reads-t0.json`, the counters this sweep is differenced against:

| table | seq_scan | idx_scan | ins / upd / del |
|---|---|---|---|
| `imagery_snapshots` | 794 | 48,352 | 3,764 / 10,066 / 682 |
| `parcel_scenes` | 272 | 55,325 | 3,082 / 0 / 0 |
| `scenes` | 982 | 73,110 | 1,342 / 1,119 / 0 |

Migration 0018 applied cleanly against this database at 21:44Z, which is
itself a measurement: a validating CHECK is refused while any row fails it, so
all 1,342 `scenes` rows already satisfy `footprint IS NULL OR
ST_IsValid(footprint)`.

---

## 3. The load-bearing prediction

**P1. `imagery_snapshots` takes ZERO reads and ZERO writes across the whole
sweep.** Every counter delta is exactly `+0`: `seq_scan`, `seq_tup_read`,
`idx_scan`, `idx_tup_fetch`, `n_tup_ins`, `n_tup_upd`, `n_tup_del`.

This is the prediction the batch exists to make. It is not "small" or "only
the reconciler" — it is zero, from anything, and **any nonzero value is a
finding**, not a rounding.

*Why it should hold:* no file under `app/` or `scripts/` names the table
(`tests/test_no_imagery_snapshots_references.py`), the two audit instruments
read `pg_stat_user_tables` and the normalized tables only, and nothing else
runs against this database during the window.

*The one way it could move without being a finding, named in advance so it
cannot be invented afterwards:* an autovacuum or ANALYZE on the table. Neither
increments `seq_scan` (they are not query-plan scans) and autovacuum has no
work with zero writes, so I predict this does not happen either — but if
`n_live_tup` moves while every scan counter stays 0, that is the explanation
and it is a deviation, not a falsification of P1.

**P1 is falsified by any nonzero delta on any of the seven counters.**

## 4. The sweep's own shape

**P2. The sweep writes almost nothing, and that is correct.** NORM-12: a
*current* database cannot exercise an insert path. This database was swept
during step 2 and has not been touched since, so nearly every group will
re-select the item it already serves and `_upsert_parcel_scene`'s `unchanged`
early return will fire.

* **P2a.** `parcel_scenes.n_tup_ins` delta **0–20**. I predict **0** as the
  single most likely value; anything above 20 means upstream published items
  for periods this fleet did not previously serve, which is possible and would
  be reported rather than treated as an error.
* **P2b.** `parcel_scenes.n_tup_del` delta **exactly 0**. A delete now requires
  a `suppressed` outcome naming a served item, and the baseline's 5 naip
  suppressions are already reflected in the current state.
* **P2c.** `scenes.n_tup_ins` delta **0–40**, most likely **0**. Bounded above
  by P2a plus mosaic tiles.
* **P2d.** `parcel_scenes.n_tup_upd` delta **0–10**. An update means a period
  changed which item it serves — Landsat re-validation picking a different
  scene is the live case.

**P3. `parcel_scenes` and `scenes` both take substantial index traffic.**
`parcel_scenes.idx_scan` delta **> 3,000** and `scenes.idx_scan` delta
**> 3,000**. This is the control on P1: a window in which nothing read
anything proves nothing about which table is read, and §6d called that out as
the weakness of the step-3 reading. If P1 holds and P3 fails, the sweep did
not happen and P1 is worthless.

## 5. Invariants after the sweep

**P4. All seven zero-checks are still 0.** duplicate_groups,
dangling_primary, dangling_mosaic, primary_in_own_mosaic, invalid_footprints,
non_polygon_footprints, duplicate_items.

`invalid_footprints` is the one with a live mechanism behind it: every
pipeline-written footprint goes through `normalize_footprint`, and 0018's
CHECK would refuse the insert if one did not. A nonzero value here would mean
0018 is not doing what its docstring says, which is the strongest single
finding this sweep could produce.

**P5. Landsat is conserved per parcel: 43 rows on all 45 parcels, 1,935
total.** Per parcel, not in aggregate — a total conserves while two parcels
swap. A parcel that *gains* a Landsat year is not a violation and would be
reported; a parcel that loses one is.

**P6. `parcels` stays 45 and `parcel_scenes` is ≥ 3,082**, equal to 3,082 +
P2a. It cannot shrink: P2b says zero deletes.

**P7. `scenes` provenance keeps `mosaic_url` at 0.** The class the step-1
backfill created is closed for new rows (step 2's amendment); `snapshot` stays
at exactly **1,174** and `enriched` at exactly **88**, because both are
historical populations no writer produces. Any growth in `selection` equals
P2c.

## 6. The ledger

**P8. The outcome distribution is stable in shape.** Read per NORM-3 (latest
row per parcel/source/group), I predict:

* `landsat/ok` **≥ 1,930** and `landsat/failed` **≤ 5**. The baseline's 2
  failures are a single parcel-year class; a re-run may clear them or
  reproduce them, and both are ordinary.
* `naip/absent` **within ±40 of 437** — this is the largest population in the
  ledger and the one most sensitive to upstream, and a rule that treated its
  movement as a defect would treat NAIP's actual coverage as a defect.
* `usgs_topo/indeterminate` **stays at 3 or falls**. It must not rise: an
  `indeterminate` is a confession that a group reached the end of the persist
  loop with no verdict, and the step-4 rewrite of that loop is exactly the
  kind of change that could introduce one.

**P8 has a hard clause:** `indeterminate` rising above 3 on any source is a
**finding against this batch**, because the loop that emits it is the loop
this batch rewrote.

**P9. No source's task ends `failed` for a reason attributable to the
rewrite.** Upstream 403/429/timeout are ordinary and expected in a 45-parcel
sweep. A `failed` whose message names a missing table, a missing function, or
a NOT NULL/CHECK violation on `scenes`/`parcel_scenes` is a finding.

## 7. After 0019 is applied locally

Run only once §3–§6 have been scored.

**P10. The suite is green with the table gone**, and the count is unchanged
from the pre-0019 run: 749 passed, 12 skipped. No test constructs the table,
so dropping it should be invisible to every one of them — and if any test goes
red here, it was reaching the table through a path the reference-pinning test
does not cover, which is a finding about the pin.

**P11. A second invariant battery after the drop is identical to the first**
on every quantity except that `snapshot_reads.py` reports `imagery_snapshots:
not present`. `scenes` and `parcel_scenes` counters continue from where they
were; the battery never read the dropped table, so nothing in it changes.

**P12. The 0019 downgrade/upgrade round trip leaves the database at head with
the table absent**, and the intermediate downgraded state has the table
present with **0 rows** — the migration's central claim, exercised against the
real local database rather than only against a throwaway.

---

## 8. What would make me stop rather than report

* **P1 nonzero.** The cooling measurement's premise is that the code cannot
  touch the table. A nonzero delta means it can, and the deploy-2 gate is not
  met by anything this session produced.
* **P4's `invalid_footprints` nonzero.** 0018 would be admitting rows it
  claims to refuse.
* **P8's `indeterminate` above 3.** The rewritten loop dropping a group
  silently is the failure mode the ADR's own norms name first.

---

# Observed — local, 2026-08-29T21:47–22:16Z

Appended after the runs. **Nothing above this line is edited.**

## 0. The deviation that comes first: the sweep ran twice

**The first sweep ran against the OLD code and falsified P1 outright.** It is
reported here rather than discarded, because a run that happened is part of
the record whatever it measured.

`scripts/requeue_parcels.py` was run at 21:50Z over all 45 parcels and drained
by 22:01Z. Delta from `step4-reads-t0.json` to `step4-reads-t1.json`:

| `imagery_snapshots` | delta |
|---|---|
| `seq_scan` | +0 |
| `idx_scan` | **+3,265** |
| `n_tup_ins` | **+8** |
| `n_tup_upd` | **+3,069** |
| `n_tup_del` | **+8** |

**Cause, diagnosed rather than assumed.** The `worker` service bind-mounts
`./backend:/app`, so its *files* were current, but Celery does not reload
modules and the running processes had been up for 29 hours — since before the
cutover commit. The pipeline that ran was the pre-step-4 pipeline, and these
counters are exactly what it does: 3,069 `ON CONFLICT DO UPDATE` refreshes for
re-selected rows, 8 inserts, 8 deletes.

Confirmed after restarting the worker (`entrypoint.sh` skips migrations for
`celery`, so the restart could not apply 0019 and did not — `alembic current`
read `0018` before and after):

```
upsert_gone: True          # app.services.imagery has no upsert_imagery_snapshot
model_gone: True           # app.models.parcels has no ImagerySnapshot
reconciler_reads_parcel_scenes: True
```

**This is a method finding and it is not small.** `requeue_parcels.py` carries
a deploy gate — `--require-sha` against `/api/v1/health` — written for exactly
this failure in production: re-queueing through code that predates the fix
heals a parcel back into the defect. `--skip-deploy-check` was passed because
the local image reports `GIT_SHA=dev` and the gate cannot check it, and the
local equivalent of "is the worker running your code" turns out to be a
restart nobody had written down. Recorded as **STATUS.md NORM-32**.

The first sweep's counters are also a **control the prediction did not think
to ask for**: they are the same measurement, over the same fleet, on the same
day, under the old code — and they are loudly nonzero. P1's zero on the second
run is therefore not "an idle window", which is precisely the weakness
NORM31-PROD-REPORT §6d identified in the step-3 reading.

## 1. Scorecard

The scored run is the **second** sweep, 22:03–22:08Z, worker on `329a8a6`,
baseline `step4-reads-t2.json` → `step4-reads-t3.json`,
`step4-pre-sweep-2.json` → `step4-post-sweep.json`.

| # | Prediction | Observed | Verdict |
|---|---|---|---|
| **P1** | `imagery_snapshots` all seven counters **+0** | seq_scan +0, seq_tup_read +0, idx_scan +0, idx_tup_fetch +0, ins +0, upd +0, del +0 | **CONFIRMED** |
| P2a | `parcel_scenes.n_tup_ins` 0–20, likely 0 | **+0** | CONFIRMED |
| P2b | `parcel_scenes.n_tup_del` exactly 0 | **+0** | CONFIRMED |
| P2c | `scenes.n_tup_ins` 0–40, likely 0 | **+0** | CONFIRMED |
| P2d | `parcel_scenes.n_tup_upd` 0–10 | **+0** | CONFIRMED |
| **P3** | `parcel_scenes.idx_scan` > 3,000 and `scenes.idx_scan` > 3,000 | **+3,787** and **+8,081** | **CONFIRMED** |
| P4 | all seven zero-checks 0 | 7 of 7 at **0** | CONFIRMED |
| P5 | landsat 43 on all 45 parcels, 1,935 total | 45 parcels, min 43, max 43, 1,935 | CONFIRMED |
| P6 | `parcels` 45, `parcel_scenes` = 3,082 + P2a | 45 and **3,082** | CONFIRMED |
| P7 | `mosaic_url` 0; snapshot 1,174; enriched 88 | 0 / 1,174 / 88, selection 80 | CONFIRMED |
| P8 | `landsat/ok` ≥ 1,930, `landsat/failed` ≤ 5 | **1,923 / 12** | **DEVIATION** |
| P8 | `naip/absent` within ±40 of 437 | **437**, unmoved | CONFIRMED |
| P8 | `usgs_topo/indeterminate` stays at 3 or falls | **3** | CONFIRMED (hard clause holds) |
| P9 | no `failed` attributable to the rewrite | 12 landsat + 2 sentinel2, **all `stac_403`** | CONFIRMED |
| P10 | suite green, 749 passed / 12 skipped | **749 passed**, 16 skipped | CONFIRMED on passes, **DEVIATION** on skips |
| P11 | second battery identical, `not present` for the dropped table | identical; `imagery_snapshots: not present` | CONFIRMED |
| P12 | round trip: table absent at head, present-and-empty at 0018 | confirmed both ways | CONFIRMED |

**17 scoreable, 14 confirmed, 3 deviations, 0 falsified** — plus P1 falsified
on a run that was not the predicted run, reported in §0.

## 2. The deviations

**P8's Landsat count.** `landsat/failed` went 3 → 12 and `landsat/ok` 1,932 →
1,923 (the §2 baseline's 2 had already become 3 during the first sweep). Every
one of the 12 is `stac_403` with detail `Client error '403 Forbidden' for url
'https://planetarycomputer.microsoft.com/api/stac/v1/search'` — Planetary
Computer rate-limiting a 45-parcel burst, the NORM-10 class. The first sweep,
on the old code, produced the same class in the same window, which is the
evidence that it is upstream and not the rewrite. The prediction's ceiling of
5 was simply too tight for three consecutive fleet sweeps inside 30 minutes;
the ceiling was wrong, the mechanism was not.

**P10's skip count.** 12 → 16 is caused by this batch's own four new
`@requires_postgres` tests (two for 0018, two for 0019), which skip when
`TEST_POSTGRES_URL` is unset. The prediction was written when the count was
12 and did not account for tests it had itself added. Not caused by the drop:
with `TEST_POSTGRES_URL` set, the same tree runs **762 passed, 3 skipped**.

**One observation the prediction did not cover, reported rather than scored.**
`scenes.seq_scan` moved **+43** (57,706 tuples ÷ 1,342 rows = exactly 43 whole
scans) during the sweep, with zero writes. No `audit_probe` event falls in
that window — both batteries ran outside it — so this is application traffic,
and the honest reading is that PostgreSQL's planner prefers a sequential scan
on a 1,342-row table for some shape the pipeline issues. It concerns `scenes`,
a live serving table, not the retired one, and P1 is untouched by it. Noted so
that a future reading of `scenes` counters starts from a known figure.

## 3. The NORM-14 resolution, measured in the data rather than argued

Unplanned, and the strongest single piece of evidence in this run.
`timeline_task_years.created_at` defaults to `now()`, which in PostgreSQL is
**transaction start time** — so the count of distinct `created_at` values
among one task's `ok` rows *is* the number of transactions that wrote them.

Six Landsat tasks from each sweep, 43 `ok` rows each:

| sweep | code | `ok` rows per task | distinct `created_at` |
|---|---|---|---|
| 21:50–22:01Z | pre-step-4 | 43 | **43** |
| 22:03–22:08Z | `329a8a6` | 43 | **1** |

Forty-three commits became one. That is the NORM-14 window closing, visible in
the rows themselves rather than inferred from the diff.

## 4. The `sentinel2/indeterminate` that appeared after the drop, investigated

The third sweep (post-drop, 22:12–22:16Z) produced one
`sentinel2/indeterminate` where there had been none. P8's hard clause names
`indeterminate` as the outcome the rewritten loop could introduce, so it was
traced rather than counted.

It is **not** the persist loop's silent-drop path. Its reason reads:

> cloud-probe failed at `timeline._classify_empty_chunk`; cannot tell
> `no_scenes` from `all_cloud_filtered`: Client error '403 Forbidden'

That is a named, pre-existing site with an explicit refusal to guess — an
honest "I could not decide", which is what `indeterminate` is for — and its
cause is the same upstream 403 as P8's. The loop's own silent-drop reason
("attempted group reached the end of `timeline._search_and_persist_source`
with no outcome") appears **zero** times across all three sweeps.

## 5. After the drop

Migration 0019 applied to the local database at 22:09Z.

* Suite: **749 passed, 16 skipped** (762 passed / 3 skipped with
  `TEST_POSTGRES_URL` set). No test needed the table.
* `snapshot_reads.py`: `imagery_snapshots: not present`; `scenes` and
  `parcel_scenes` counters continue unbroken.
* Third fleet sweep, table gone: all 45 parcels, **7 of 7** zero-checks at 0,
  landsat 43 × 45 = 1,935, `parcel_scenes` 3,082, `scenes` 1,342 — every
  quantity identical to the pre-drop state.
* Round trip: `downgrade 0018` recreates the table with **0 rows**, all 13
  columns including `additional_cog_urls`, and all four indexes
  (`imagery_snapshots_pkey`, `uq_imagery_snapshots_parcel_stac_item`,
  `idx_imagery_parcel_date`, `idx_imagery_bbox`). `upgrade head` removes it
  again; `scenes` 1,342 and `parcel_scenes` 3,082 untouched throughout.

**The local database is at 0019 with the table dropped. Production is not.**

---

# Production — step 4's deploy-1 fleet sweep

Written and **committed before the pilot invocation runs**, in an unattended
session. Nothing above this line is edited, including the local Observed half.
The Observed section for this half is appended later and this half is never
edited to match it.

## P0. Blindness, stated first

* **Not run:** `scripts/requeue_parcels.py` against production, in any mode,
  including `--dry-run`. No sweep outcome below has been observed.
* **Run, and reported as measurement rather than outcome:** the six deploy
  gates of §PB below, and the two baseline readings
  `step4-prod-reads-t0.json` and `step4-prod-battery-t0.json`. A prediction of
  deltas needs a baseline; every prediction in this arc took one the same way.
* **Known before writing this:** the local scored sweep
  (`PREDICTION-STEP4.md` Observed, 45 parcels), the local old-code control
  (§0 of that half), the step-2 production sweep over the same 189 parcels and
  the same 30-parcel pilot set (`STEP2-PROD-REPORT.md`), and STATUS.md
  NORM-12, NORM-15 and NORM-17. These are priors and they are cited where they
  move a number. They are not observations of this sweep.

## PB. The baseline this is differenced against

**Deploy.** Image `03867c4b1e531b461665d41cab7b8a8f4196c60d` built
**2026-08-29T23:04:25Z**; API machines booted 23:04:56Z and 23:05:14Z, worker
23:05:09Z. Six gates verified at artifact level before any of this was
written: health SHA, `GH_SHA` on all four machines, `alembic_version = 0018`,
`ck_scenes_footprint_valid` present and `convalidated = true` in
`pg_constraint`, `imagery_snapshots` present with **12,884 rows / 13
columns**, process starts postdating the build, and the deployed
`app/`+`scripts/` byte-identical to the repo at `03867c4`.

**Counters, `step4-prod-reads-t0.json`, read 2026-08-29T23:11:57.497954Z —
this timestamp is cooling **t0**:**

| table | seq_scan | seq_tup_read | idx_scan | idx_tup_fetch | ins / upd / del | n_live_tup |
|---|---|---|---|---|---|---|
| `imagery_snapshots` | 3,945 | 30,606,005 | 158,669 | 1,238,541 | 15,492 / 61,406 / 2,608 | 12,884 |
| `parcel_scenes` | 158 | 1,648,887 | 59,132 | 101,734 | 12,884 / 7 / 0 | 12,884 |
| `scenes` | 217 | 1,272,497 | 142,679 | 538,102 | 6,663 / 5,894 / 0 | 6,663 |

**Invariants, `step4-prod-battery-t0.json`, read 23:12:47.640332Z:** parcels
**189**, scenes **6,663**, parcel_scenes **12,884**; **7 of 7** zero-checks at
**0**; provenance snapshot **6,156** · enriched **505** · selection **2**;
landsat **43 on all 189 parcels, 8,127 rows**; ledger last-24h **14,770 rows,
0 `failed`**; requests complete 1,299 / failed 3 / partial 40, **none in
flight**. Every total and the provenance split are **identical** to the last
recorded production state (`NORM31-PROD-REPORT.md` P15, 2026-08-29T20:39Z), so
there is no unexplained drift to account for and the sweep starts from a quiet
fleet.

**The one non-zero delta since that last recorded state, and its
attribution.** From `reads-t2.json` (20:39:20Z) to t0: `imagery_snapshots`
`seq_scan` **+1** / `seq_tup_read` **+12,884** — exactly one whole-table scan,
which is this session's gate-1d `probe_count`, logged as an `audit_probe`
event at 23:11:07Z. `parcel_scenes` **+1** scan / **+12,884** tuples — this
session's context probe. `scenes` **+2** scans / **+13,326** tuples = exactly
two whole scans: one is this session's context probe, the other is **migration
0018 validating its CHECK against all 6,663 rows during the deploy**, which is
what a validating CHECK costs and is independent evidence that 0018 really
ran. `imagery_snapshots` `idx_scan`, `idx_tup_fetch` and all three row
counters are **unmoved since 06:41Z** — sixteen hours in which nothing
exercised the imagery pipeline at all.

**That last fact is why P3 is load-bearing and is stated here, not in the
scoring.** A window with no traffic cannot distinguish "the code no longer
reads the table" from "nothing ran". The sweep is the traffic.

---

## P1. The load-bearing prediction — `imagery_snapshots` takes ZERO access

**All seven counters — `seq_scan`, `seq_tup_read`, `idx_scan`,
`idx_tup_fetch`, `n_tup_ins`, `n_tup_upd`, `n_tup_del` — are `+0` from t0
across the entire sweep window**, pilot and remainder together, and
`n_live_tup` stays **12,884**.

**Modulo this session's own attributed probe scans, which are enumerated here
in advance and, by design, are none.** Between t0 and the closing reading this
session issues **zero** probes against `imagery_snapshots`: the invariant
battery probes only `parcels`, `scenes`, `parcel_scenes`,
`timeline_task_years` and `timeline_requests`, and `snapshot_reads.py` reads
`pg_stat_user_tables` and never the tables it reports on. **The enumerated set
is empty and the subtraction is therefore zero**, so the predicted delta is
exactly `+0` with nothing subtracted. If that plan changes, each probe is
named with its `audit_probe` timestamp and subtracted by count, and the
statement becomes `+0` net rather than `+0` raw.

**The magnitude this zero is measured against, derived rather than asserted.**
The local old-code control (Observed §0) put **3,082 groups** through the
step-3 pipeline and moved `idx_scan` **+3,265** and `n_tup_upd` **+3,069** —
1.06 and 1.00 per group. Production's sweep puts **12,884 groups** through the
same shape, so the step-3 code would have moved `idx_scan` by **≈13,700** and
`n_tup_upd` by **≈12,900**. **P1 predicts zero where the prior code predicts
roughly thirteen thousand.** That gap, not the zero on its own, is the
measurement.

**P1 is falsified by any nonzero delta on any of the seven counters.** The one
movement that would be a deviation rather than a falsification is named in
advance, as it was locally: an autovacuum or ANALYZE moving `n_live_tup` while
every scan counter stays 0. With zero writes autovacuum has no work, so I
predict this does not happen either.

## P2. The control — the normalized tables take heavy traffic in the same window

The local scored sweep moved `parcel_scenes.idx_scan` **+3,787** and
`scenes.idx_scan` **+8,081** over 3,082 groups: 1.23 and 2.62 per group.
Scaled to 12,884 groups that is ≈15,800 and ≈33,800.

* **P2a, pilot** (2,075 groups): `parcel_scenes.idx_scan` **> 1,000** and
  `scenes.idx_scan` **> 1,000**.
* **P2b, fleet** (12,884 groups): `parcel_scenes.idx_scan` **> 8,000** and
  `scenes.idx_scan` **> 8,000**.

**If P1 holds and P2 fails, the sweep did not happen and P1 is worthless.**

## P3. The write arms, and the pilot's honest limit

NORM-12: a database whose selections are current cannot exercise an insert
path. Production was fully swept 19 hours ago (03:50–04:50Z), and NORM-15
found the churn between fleet sweeps is a measure of Planetary Computer's
health rather than of selection drift — the 2026-08-29 sweep changed **7
groups out of 12,884**, all Sentinel-2 `2026` recency, zero historic years.

* **P3a.** `parcel_scenes.n_tup_ins` delta **0–10**, point estimate **0**. An
  insert needs a genuinely new `group_key`; Sentinel-2 recency lands on the
  existing `2026` row and is an update, not an insert.
* **P3b.** `parcel_scenes.n_tup_upd` delta **0–40**, point estimate **8**.
  This is the arm that changed shape in step 4 — superseding a group is now an
  upsert of one row where it used to be a DELETE — and it has **zero**
  production exercises before this sweep.
* **P3c.** `parcel_scenes.n_tup_del` delta **0**, band **0–5**. A delete now
  requires a `suppressed` outcome naming a served item; the baseline's 9 NAIP
  suppressions are already reflected in the current state.
* **P3d.** `scenes.n_tup_ins` delta **0–25**, point estimate **4**. Bounded
  above by P3a + P3b plus mosaic tiles.
* **P3e, the decomposition, committed in advance.** Every new `scenes` row is
  reported with its collection, item id and the `group_key` of the
  `parcel_scenes` row referencing it, and classified as **recency**
  (`group_key` = `2026`, the current year) or **anything else**. I predict
  **100% recency**. *Any insert on a historic period is "anything else" and is
  a finding*, decomposed against NORM-15's hypothesis that historic-year churn
  tracks upstream signing failures rather than better selections.

**P3f — the pilot's write arms are predicted INERT, and the decision rule for
that is written here rather than after the fact.** The same 30 parcels in the
step-2 production sweep wrote **nothing at all** over 2,075 groups
(NORM-12: *"a pilot proves a write path only if it writes"*). I therefore
predict the pilot's `parcel_scenes` ins/upd/del are **0 / 0 / 0**.

**The rule, in advance:** an all-zero pilot write reading is NORM-12's
expected branch on a current database. It is neither a pass nor a failure of
the write arms — it is an **absence**, and passing a gate on absence is the
mistake NORM-17 exists to prevent. So the pilot is gated on the read path and
the ledger, which it *can* discharge (P2a, P5, P6), and the write-arm question
moves to the fleet reading, where the remaining 159 parcels are the widening.
**If the fleet reading is also all-zero on writes, this sweep exercised the
new upsert arm zero times in production and NORM-17 is updated to say exactly
that** — never "fleet-scale insert-path evidence", which is the misreading
NORM-17 was written to block.

## P4. NORM-17 — the expected exercise counts, derived from group counts

Every group now takes the step-4 write path: the reconciler diffs
`parcel_scenes ⋈ scenes` and `_upsert_parcel_scene` decides. Derived from the
baseline ledger's per-source `ok` counts (landsat 8,127 + naip 1,305 +
sentinel2 2,259 + usgs_topo 1,153 = **12,844**) and 189 parcels × 4 imagery
sources:

| arm | expected count, fleet | expected count, pilot |
|---|---|---|
| `reconcile_source_snapshots` invocations (one per task, one transaction each) | **756** | **120** |
| `_upsert_parcel_scene` exercises (one per selected group) | **12,700–12,950**, point **12,844** | **2,000–2,120**, point **2,075** |
| …of which the `unchanged` early return | **≥ 12,700** (≥ 99%) | **≥ 2,000** |
| …of which the superseding **upsert** arm (was a DELETE before step 4; **0** prior production exercises) | **0–40**, point **8** | **0**, band 0–5 |
| `_ensure_scene` lookup arm | **≈ 12,844** | **≈ 2,075** |
| `_ensure_scene` INSERT arm | **0–25**, point **4** | **0**, band 0–3 |
| suppressed-delete arm | **0**, band 0–5 | **0** |

**What this sweep can and cannot add to NORM-17.** It can establish that the
reconciler's new `parcel_scenes` diff and the single-transaction commit ran
**756 times over 12,884 groups** — the first fleet-scale exercise of either,
since step 2's sweep ran the *old* reconciler against `imagery_snapshots`. It
**cannot** turn a handful of recency inserts into fleet-scale insert-path
evidence, and the row will say so.

## P5. NORM-14 in production — one `created_at` per task

`timeline_task_years.created_at` defaults to `now()`, which in PostgreSQL is
**transaction start time**, so the number of distinct `created_at` values
among one task's `ok` rows is the number of transactions that wrote them.

**Every task in the sweep window with at least one `ok` row has exactly ONE
distinct `created_at` across all of its `ok` rows.** Measured per task across
all 756 tasks, not on a sample. Locally this went 43 → 1 for Landsat tasks
under the cutover; production is the same code at 189-parcel scale.

**P5 is falsified by any task whose `ok` rows carry more than one distinct
`created_at`.** If one appears it is decomposed rather than counted: a second
value could mean a second reconcile call by design for that source, or it
could mean the persist loop regained a commit of its own, and those are
different findings.

## P6. Parity after the sweep

* **P6a.** All **7** zero-checks at **0** — `duplicate_groups`,
  `dangling_primary`, `dangling_mosaic`, `primary_in_own_mosaic`,
  `invalid_footprints`, `non_polygon_footprints`, `duplicate_items`.
  `invalid_footprints` is the one with a live mechanism behind it and 0018's
  CHECK now enforces it; a nonzero value means 0018 is admitting rows it
  claims to refuse, which is the strongest single finding this sweep could
  produce.
* **P6b.** Landsat conserved **per parcel**: **43 on all 189 parcels, 8,127
  rows**, min 43, max 43. Per parcel, not in aggregate — a total conserves
  while two parcels swap. A parcel that *gains* a Landsat period is reported,
  not failed; a parcel that **loses** one is a failure.
* **P6c.** `parcels` stays **189**; `parcel_scenes` = **12,884 + P3a**;
  `scenes` = **6,663 + P3d**.
* **P6d.** Provenance: `mosaic_url` stays **0**, `snapshot` stays exactly
  **6,156**, `enriched` stays exactly **88 + 417 = 505**. Both are historical
  populations no writer produces. All growth is in `selection`, which goes
  from **2** to **2 + P3d**.

## P7. The ledger, read per NORM-3

Latest row per (parcel, source, group_key), over the sweep window.

* **P7a.** `landsat/ok` **≥ 8,100**; `landsat/failed` **≤ 20**, point
  estimate **0**. Step 2's fleet sweep over these same parcels produced
  **14,770 rows and 0 `failed`**; the local 403 storm was three sweeps inside
  30 minutes, which this staging does not reproduce.
* **P7b.** `naip/absent` within **±60 of 1,892** — the largest population in
  the ledger and the one most sensitive to upstream. A rule treating its
  movement as a defect would treat NAIP's real coverage as a defect.
* **P7c, the hard clause.** `naip/indeterminate` **stays at 7 or falls** and
  `usgs_topo/indeterminate` **stays at 2 or falls**. An `indeterminate` is a
  confession that a group reached the end of the persist loop with no verdict,
  and **this batch rewrote that loop**. A rise on any source is a **finding
  against this batch** until traced to a named pre-existing refusal site
  (`_classify_empty_chunk`'s cloud probe is the one the local run found).
* **P7d.** The persist loop's own silent-drop reason — "attempted group
  reached the end of `timeline._search_and_persist_source` with no outcome" —
  appears **zero** times.
* **P7e.** No task ends `failed` for a reason attributable to the rewrite.
  Upstream 403/429/timeout are ordinary. A `failed` naming a **missing table**,
  a missing function, or a NOT NULL/CHECK violation on `scenes` /
  `parcel_scenes` is a finding — and a message naming `imagery_snapshots`
  would mean a reader survived the cutover.

## P8. Sweep hygiene

* **P8a.** Pilot: **30 queued, 0 skipped, 0 unreached**; `.rc` = **0**, read
  from `/tmp/step4-prod-pilot.rc` on a pinned machine, never inferred.
* **P8b.** Remainder: **159 queued, 0 skipped, 0 unreached**; `.rc` = **0**,
  read the same way.
* **P8c.** **189 of 189 requests reach `complete`**, **0 `failed`**, **0
  `partial`**, none in flight at the terminal reading. The baseline's 3
  `failed` and 40 `partial` are historical rows for earlier requests and are
  not expected to change.
* **P8d.** The deploy gate is satisfied by `--require-sha 03867c4` and logs
  `Deploy gate passed`. `--skip-deploy-check` is **not** used: this is the
  case the gate exists for, and NORM-32 is the reason it is not waived.
* **P8e.** The remainder's enqueue takes **longer than the pilot's** and is
  bounded by the admission cap polling rather than refusing — step 2's
  remainder took 38.5 minutes for the same 159 parcels. Predicted **20–60
  minutes** to enqueue, **≤ 90 minutes** to drain.

## P9. What would make me stop rather than report

* **P1 nonzero.** The cooling measurement's premise is that the deployed code
  *cannot* touch the table. A nonzero delta means it can, the cooling span
  does not start, and the deploy-2 gate is not met by anything this session
  produced.
* **P6a's `invalid_footprints` nonzero.** 0018 admitting rows it claims to
  refuse.
* **P7c's `indeterminate` above baseline** with no named pre-existing site.
* **The pilot failing P2a or P5 or P6** — the remainder does not run.

---

# Observed — production, 2026-08-29T23:11Z → 2026-08-30T00:17Z

Appended after both runs. **Nothing above this line is edited** — neither the
local half nor the production prediction half.

## 1. Scorecard

Sweep window: pilot launched **23:18:08Z**, drained **23:30:09Z**; remainder
launched **23:34:45Z**, enqueue done **~00:07:5xZ**, drained **00:13:57Z**.
Counters differenced t0 (`step4-prod-reads-t0.json`, 23:11:57.497954Z) → t2
(`step4-prod-reads-t2.json`, 00:14:31.842120Z).

| # | Prediction | Observed | Verdict |
|---|---|---|---|
| **P1** | `imagery_snapshots` **all seven counters +0**, attributed probe set enumerated in advance and empty | seq_scan **+0**, seq_tup_read **+0**, idx_scan **+0**, idx_tup_fetch **+0**, n_tup_ins **+0**, n_tup_upd **+0**, n_tup_del **+0**; `n_live_tup` **+0** at 12,884. Nothing to subtract | **CONFIRMED** |
| P2a | pilot: `parcel_scenes.idx_scan` > 1,000 **and** `scenes.idx_scan` > 1,000 | **+2,557** and **+7,239** | CONFIRMED |
| **P2b** | fleet: both > 8,000 | **+15,925** and **+42,614** (the derivation predicted ≈15,800 and ≈33,800) | **CONFIRMED** |
| P3a | `parcel_scenes.n_tup_ins` 0–10, point 0 | **+0** | CONFIRMED |
| P3b | `parcel_scenes.n_tup_upd` 0–40, point 8 | **+1** | CONFIRMED (band), point high |
| P3c | `parcel_scenes.n_tup_del` 0 | **+0** | CONFIRMED |
| P3d | `scenes.n_tup_ins` 0–25, point 4 | **+1** | CONFIRMED (band), point high |
| P3e | **100% of new `scenes` rows are recency**, `group_key` = 2026 | 1 of 1: `S2C_MSIL2A_20260828T183921_R070_T11TMM_20260828T233712`, `sentinel-2-l2a`, capture 2026-08-28, referenced at `group_key` **`2026`**. Zero historic-period inserts | CONFIRMED |
| P3f | the **pilot's** write arms are inert: 0 / 0 / 0 | **0 / 0 / 0**; `Replaced superseded served scenes` absent from the pilot's worker log, as NORM-12 said it would be | CONFIRMED |
| P4 | 756 reconcile invocations; 12,700–12,950 upsert exercises; superseding-upsert arm 0–40; `_ensure_scene` INSERT 0–25; suppressed-delete 0 | **756** tasks / **12,880** `ok` groups; superseding-upsert **1**; INSERT **1**; suppressed-delete **0** | CONFIRMED |
| **P5** | every task's `ok` rows share **one** `created_at`, across all 756 | histogram **`{1: 756}`** — 756 of 756 tasks, **12,880 `ok` rows**, `max_distinct` 1 on all four sources, **zero violations** | **CONFIRMED** |
| P6a | 7 zero-checks at 0 | **7 of 7 at 0** | CONFIRMED |
| P6b | landsat 43 on all 189 parcels, 8,127 rows | 189 parcels, min **43**, max **43**, **8,127** rows | CONFIRMED |
| P6c | parcels 189; parcel_scenes 12,884 + P3a; scenes 6,663 + P3d | **189** / **12,884** / **6,664** | CONFIRMED |
| P6d | `mosaic_url` 0, `snapshot` 6,156, `enriched` 505, `selection` 2 + P3d | 0 / **6,156** / **505** / **3** | CONFIRMED |
| P7a | `landsat/ok` ≥ 8,100; `landsat/failed` ≤ 20, point 0 | **8,123** / **4** | CONFIRMED (band), point high |
| P7b | `naip/absent` within ±60 of 1,892 | **1,892**, unmoved | CONFIRMED |
| P7c | **hard clause** — `naip/indeterminate` ≤ 7, `usgs_topo/indeterminate` ≤ 2 | **7** and **2**, on the **same three parcels** as step 2, from the same two named truncation sites | CONFIRMED |
| P7d | the persist loop's silent-drop reason appears 0 times | **0** | CONFIRMED |
| P7e | no failure attributable to the rewrite, none naming the retired table | 4 × `stac_403`; **0** ledger rows mention the table, and **0** of 3,335 worker-log lines do | CONFIRMED |
| P8a | pilot rc 0, 30 queued, 0 skipped, 0 unreached | rc **0**, **30**, **0**, **0** | CONFIRMED |
| P8b | remainder rc 0, 159 queued, 0 skipped, 0 unreached | rc **0**, **159**, **0**, **0** | CONFIRMED |
| P8c | 189/189 requests complete, none in flight; historical 3 failed / 40 partial unmoved | 189 `complete`, **756/756** tasks `complete`, 0 in flight; requests 1,299 → **1,488**; failed **3**, partial **40** unmoved | CONFIRMED |
| P8d | `--require-sha 03867c4` passes; `--skip-deploy-check` not used | `Deploy gate passed — prod is running 03867c4b1e53…` on all four invocations (two dry runs, two runs) | CONFIRMED |
| P8e | remainder enqueue 20–60 min, drain ≤ 90 min | enqueue **33 min**, fully drained **39 min** after launch | CONFIRMED |

**25 scoreable, 25 confirmed, 0 deviations, 0 falsified.**

## 2. What the zero is worth — the counterfactual, restated against the result

P1's derivation predicted that step-3 code over production's 12,884 groups
would have moved `imagery_snapshots` `idx_scan` by **≈13,700** and `n_tup_upd`
by **≈12,900**. The sweep put **12,884 groups** through the pipeline —
confirmed by the ledger's 14,803 window rows and by 756 completed tasks — and
moved both by **0**, while `parcel_scenes` and `scenes` took **15,925** and
**42,614** index scans in the same window.

The zero is not an idle window and this is not an argument: `parcel_scenes` and
`scenes` are the control, and they moved by roughly fifty-eight thousand.

## 3. The ledger reconciles to the row, and the absent-group rule is visible in it

12,880 `ok` rows + **4** `landsat/failed` = **12,884** — exactly the
`parcel_scenes` row count. The four failed groups (`1074e64b` 2010 and 2012,
`11b0f0c1` 2007 and 2009, all `stac_403`) **kept their served rows**: landsat
stays at 43 on all 189 parcels. That is `reconcile_source_snapshots`' absent-
group rule doing precisely what its unedited docstring says — refusing to turn
a transient upstream error into permanent data loss — observed in production
rather than asserted.

## 4. The single write, in full

One group changed across 12,884. The worker log names it (23:57:56Z):

```json
{"event": "Replaced superseded served scenes", "logger": "app.services.imagery",
 "parcel_id": "b4838b92-f07c-4ee0-8e2e-e830029fe9a9", "source": "sentinel2",
 "replaced": 1, "suppressed_deleted": 0, "scope": "year",
 "groups": ["2015", ..., "2026"]}
```

`replaced: 1, suppressed_deleted: 0` matches the counters exactly:
`parcel_scenes.n_tup_upd` **+1**, `n_tup_del` **+0**, `scenes.n_tup_ins` **+1**.
The new `parcel_scenes` row carries `selected_by =
03867c4b1e531b461665d41cab7b8a8f4196c60d` — the deployed SHA, written by the
code the gate verified.

**This is the step-4 superseding-upsert arm's first production execution.**
Before step 4 the same change was spelled as a DELETE plus an insert; here it is
one upsert of one row, and it is the only one there was.

## 5. Deviations from the point estimates, recorded because NORM-15 is about exactly this

**Bands held everywhere; three point estimates were high.** P3b predicted 8
changed groups and got 1; P3d predicted 4 new scenes and got 1; P7a predicted 0
landsat failures and got 4.

The first two were sized on step 2's sweep, which changed 7 groups nineteen
hours earlier. **This is NORM-15's warning applying to my own numbers**: the
sweep-to-sweep churn measures Planetary Computer's health, not selection drift,
and a healthy PC produces almost nothing. Across 3,335 lines of worker log
there are **4** upstream failures and **2** TNM row caps in the entire fleet
run. The right lesson is the one NORM-15 already states — *this quantity is not
a forecastable property of the fleet* — and the band, not the point, was the
prediction.

## 6. `imagery_snapshots` took +0 in four separate windows, one of them a control

Not only across the sweep. The table was `+0` on all seven counters across
t0→t2 (the sweep), t2→t3 (instruments only, no sweep), and an **isolated
battery run** measured on its own. That last one is the control on the
"enumerated probe set is empty" claim: it shows the invariant battery costs
`parcel_scenes` **+7** and `scenes` **+6** whole-table scans and
`imagery_snapshots` **+0** — the subtraction is empty by measurement, not
merely by intent.
