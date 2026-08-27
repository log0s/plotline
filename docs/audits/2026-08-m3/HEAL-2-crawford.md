# Heal 2 — Crawford County `6563dedf`, ledger-scoped then full-scope requeue, scoring `PREDICTION.md` P3

Explicit heal exception, one parcel, two writes. Executed 2026-08-27 against
deployed SHA `5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce` (M3,
`../2026-08-m3/DEPLOY-WATCH.md`; same SHA as `HEAL-1-e513188c.md`). Prediction
under test: `../2026-08-m3/PREDICTION.md` P3.

## Phase 1 — Gate

1. **Deploy.** `fly image show` on both apps: API `48e0de9a713918` /
   `825d69b7e46618`, worker `e7845415f57728` / `e2862966b306d8`, all four
   `GH_SHA=5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce`. `GET
   /api/v1/health`: `{"status":"ok","db":"connected","redis":"connected",
   "version":{"sha":"5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce","built":
   "2026-08-27T15:41:35Z"}}`. All agree on `5f3aa7d`.
2. **In-flight.** Zero `queued`/`processing` rows fleet-wide; zero for
   `6563dedf`.
3. **Before-state**, `6563dedf` only.

   Imagery snapshots: `landsat` 27, `usgs_topo` 3, `naip` 0, `sentinel2` 0.

   Current request `b1392b23-63ad-46d2-b9ab-97cd09d61a2e`: status
   **`partial`** (migration 0012's flip, `origin=user`, full scope), task
   rows `census complete/8`, `landsat complete/27`, `naip failed/0`,
   `property skipped/0`, `sentinel2 failed/0`, `usgs_topo complete/3`.

   Ledger, no flags — `ledger_service.retryable_groups` for this parcel
   returns exactly **33**: `landsat failed/read_timeout` × 16 (1984–1999),
   `naip failed/read_timeout` × 17 (2010–2026). `sentinel2` has **zero**
   ledger rows of any outcome — confirmed by joining
   `timeline_task_years → timeline_request_tasks → timeline_requests` and
   filtering `source='sentinel2'`: empty result. Every number matches
   `PREDICTION.md`'s before-state exactly.
4. **Dry-run.** `requeue_parcels.py 6563dedf-… --from-ledger --require-sha
   5f3aa7d --dry-run` → `Deploy gate passed`, `Ledger selected 33 group(s)
   across 1 parcel(s)`, `would re-queue: 6563dedf-… [landsat,naip]`, all 33
   groups listed at `attempt 1`. One parcel, scope exactly
   `{landsat, naip}`, 33 groups — matches the gate condition.
5. `fly logs` tailing started on both apps before phase 2 (background
   capture, `heal2-api.log` / `heal2-worker.log`).

## Phase 2a — Ledger-scoped run

```
python scripts/requeue_parcels.py 6563dedf-23b1-4719-89db-ab135ed24fb3 \
    --from-ledger --require-sha 5f3aa7d
```

```
Deploy gate passed — prod is running 5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce.
Ledger selected 33 group(s) across 1 parcel(s).
Re-queuing 1 parcel(s).
Created new timeline request  origin=heal request_id=36caa352-ca35-48ab-8efd-46f395e25b57 sources=['landsat', 'naip']
Timeline task dispatched      request_id=36caa352-ca35-48ab-8efd-46f395e25b57
  queued 36caa352-ca35-48ab-8efd-46f395e25b57 for parcel 6563dedf-… [landsat,naip]
Done — queued 1 timeline request(s), skipped 0.
```

Exit 0. Created `16:37:33.135Z`, dispatched `16:37:33.971Z`, reached
`complete` at `16:38:00.883Z` (~27s).

## Phase 3a — Score P3 (scoped)

**1. Request shape.** `36caa352-…`: `origin='heal'`, `sources=['landsat',
'naip']`, status `complete`. Exactly two task rows: `landsat
complete/items_found=43`, `naip complete/items_found=6`. No census,
property, topo or sentinel2 task row. Worker log: `Timeline scope resolved
declared=['landsat', 'naip'], running=['landsat', 'naip']`. **Confirmed, no
deviation.**

**2. Ledger, 33 groups — recovery was total, not partial.** PC answered on
every group this run; there is no re-failure to report.

| source | group | outcome | reason |
|---|---|---|---|
| landsat | 1984–1999 (16) | `ok` | — |
| naip | 2012, 2014, 2016, 2018, 2020, 2022 (6) | `ok` | — |
| naip | 2010, 2011, 2013, 2015, 2017, 2019, 2021, 2023, 2024, 2025, 2026 (11) | `absent` | `no_scenes` |

Zero `failed`, zero `indeterminate`. This is *better* than either branch
`PREDICTION.md` §4 predicted both ways (full PC recovery, or a second
`read_timeout` on attempt 2) — every group resolved to a terminal, legal
outcome on the first re-attempt. NAIP's split (6 `ok` / 11 `absent`) is
inside the prediction's own honest ceiling ("14 NAIP years" upper bound,
collection extent ends 2023) but landed lower — 6, not up to 14 — which the
prediction flagged as plausible-not-guaranteed for exactly this reason.

**3. Snapshot churn.** `landsat` 27 → 43 (**+16**, target the 16 missing
years, confirmed by `created_at` split: 27 rows with `created_at` older
than this run, 16 with `created_at` inside it, capture years matching
1984–1999 exactly). `naip` 0 → 6 (**+6**, target "up to 17"). No closed group
was touched — the pre-existing 27 Landsat rows are the same 27 rows
(untouched by this run's `created_at`). `usgs_topo` 3, `census_snapshots` 8
(`acs5`×6, `decennial`×2), `sentinel2` 0 — all read again after the run,
**byte-identical** to before-state. **Confirmed, no deviation.**

**4. Timeline.** Landsat: 43 years now (was 27). NAIP: 6 cards now (was 0).

**5. Admission.** `origin=heal` admitted immediately — worker received the
Celery task 0.7s after creation; zero `Waiting for an admission slot` lines
in either log capture. **Confirmed.**

**6. Anomalies.** None.

## Phase 2b — Full-scope run

No anomaly in 3a changed the plan. Dry-run first:

```
requeue_parcels.py 6563dedf-… --require-sha 5f3aa7d --dry-run
  → Deploy gate passed. Re-queuing 1 parcel(s). would re-queue: 6563dedf-… [all]
```

Real run:

```
python scripts/requeue_parcels.py 6563dedf-23b1-4719-89db-ab135ed24fb3 \
    --require-sha 5f3aa7d
```

```
Deploy gate passed — prod is running 5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce.
Re-queuing 1 parcel(s).
Created new timeline request  origin=heal request_id=69ec4ac8-cf56-48c4-ad9f-76b873e545a0 sources=['census', 'landsat', 'naip', 'property', 'sentinel2', 'usgs_topo']
Timeline task dispatched      request_id=69ec4ac8-cf56-48c4-ad9f-76b873e545a0
  queued 69ec4ac8-cf56-48c4-ad9f-76b873e545a0 for parcel 6563dedf-… [census,landsat,naip,property,sentinel2,usgs_topo]
Done — queued 1 timeline request(s), skipped 0.
```

Exit 0. Created `16:40:17.528Z`, dispatched `16:40:18.757Z`, reached
`complete` at `16:40:48.494Z` (~30s).

## Phase 3b — Score P3 (full)

**1. Request shape.** `69ec4ac8-…`: `origin='heal'`, full six-source scope,
status `complete`. All six task rows terminal: `census complete/9`,
`landsat complete/43`, `naip complete/6`, `property skipped/0`, `sentinel2
complete/12`, `usgs_topo complete/3`.

**2. Sentinel-2 gets its first ledger rows: 12/12 `ok`, zero `failed`.**

```
2015 ok    2016 ok    2017 ok    2018 ok
2019 ok    2020 ok    2021 ok    2022 ok
2023 ok    2024 ok    2025 ok    2026 ok
```

Predicted "mostly `ok`, any `failed` reported with reason" — actual is a
clean sweep, no reason to report.

**3. Sentinel-2 snapshot rows.** 0 → **12**, one per year 2015–2026, exactly
the target.

**4. Landsat/NAIP hold, no regression.** Re-checked against this run's own
ledger: `landsat` 43/43 `ok`, `naip` 6 `ok` / 11 `absent`(`no_scenes`) —
identical split to 3a, confirmed by re-querying `imagery_snapshots` after
this run: `landsat` 43, `naip` 6, unchanged from Phase 3a's after-state.
`usgs_topo` 3, unchanged.

**Census changed, and per the prediction's own falsifier design ("any
change is a finding") that change is recorded here: `census_snapshots`
`decennial` 2 → 3.** The new row is **`decennial`/2000**, which moved
`absent`/`api_no_data` → `ok` — a ride-along from the M3 decennial tract-width
trim (`e6afa9b`, deployed as part of this same SHA), not from anything this
heal targeted. `decennial`/1990 is unaffected (still absent, no ledger row
from this run — 1990 is no longer attempted, per Y3). `acs5` unchanged at 6
rows. This is the same mechanism `PREDICTION.md` P2 describes for the fleet
at large, observed here for the first time on a single parcel as a
side-effect of a full-scope re-run rather than a `--from-ledger
--sources census_decennial` sweep.

**5. Final status and card counts.** Request `69ec4ac8-…` `complete`.
Parcel `6563dedf` now serves: `landsat` 43, `naip` 6, `sentinel2` 12,
`usgs_topo` 3, `census_snapshots` 9 (`acs5` 6, `decennial` 3). It is the
parcel's current request, superseding `b1392b23` (`partial`).

**6. Anomalies.** None. Worker log for both runs shows no error, no retry,
no admission wait; `Timeline scope resolved` matches declared scope on both
requests.

## Verdict

**Confirmed, and the recovery landed at the optimistic end of a
double-sided prediction.** Scope was exactly `{landsat, naip}` on the
ledger-scoped run and never invented `sentinel2`; no census/property/topo
task row leaked into it; the pre-existing 27 Landsat rows were untouched by
id; the request aggregated `complete` with no failed task underneath, which
is the defect P3 existed to prove fixed. All 33 groups resolved on the
first re-attempt — 16 Landsat `ok`, 6 NAIP `ok`, 11 NAIP `absent/no_scenes`
— zero re-failures, zero `indeterminate`. The full-scope run gave
Sentinel-2 its first-ever ledger rows, 12/12 `ok`, with zero regression on
Landsat/NAIP and a legitimate one-row census ride-along from the deployed
decennial trim. Crawford County is fully healed: 43 Landsat years, 6 NAIP
years (14-year ceiling not reached — NAIP simply had no scene for most of
the retried years), 12 Sentinel-2 years, 3 USGS topo decades, 9 census
snapshot rows.
