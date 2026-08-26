# Prediction — `requeue_parcels.py 2f1b332e` on the fixed build

**Written 2026-08-25, before the run.** Fix commit `4ce1822`; report
`REPORT.md`. Not edited after the fact — the observed result goes beside each
line with a verdict (confirmed / deviation / falsified).

Parcel `2f1b332e-2b96-401c-bba6-ce89e134dbf3`, Racebrook Road, Orange CT.
Stored `census_tract_id` = `09170157100`, lat/lon 41.2690529 / -72.9999675.
The re-run does **not** re-geocode: `_run_timeline` reads the stored tract off
the parcel row (`timeline.py:1369`) and it stays `09170157100`.

**Gate:** the worker must be on a SHA that contains `4ce1822`. Verify with
`fly image show -a plotline-worker` (`GH_SHA` label) before invoking. The run
itself is Ryan's; nothing in this file has been executed.

---

## P1 — Three census rows gained, not five

`census_snapshots` for this parcel goes **5 → 8**.

| dataset | year | new row? | expected `tract_fips` | expected `total_population` | expected `total_housing_units` |
|---|---|---|---|---|---|
| acs5 | 2009 | **new** | `09009157100` | 2757 | 1154 |
| acs5 | 2021 | **new** | `09009157100` | 2453 | 1144 |
| decennial | 2020 | **new** | `09009157100` | 2604 | 1169 |
| acs5 | 2012 | existing | `09009157100` | unchanged | unchanged |
| acs5 | 2015 | existing | `09009157100` | unchanged | unchanged |
| acs5 | 2018 | existing | `09009157100` | unchanged | unchanged |
| acs5 | 2023 | existing | `09170157100` | unchanged | unchanged |
| decennial | 2010 | existing | `09009157100` | unchanged | unchanged |

Population and housing figures are the live API's answers for
`09009157100`, fetched 2026-08-25 (REPORT.md §2.1). The other ACS fields
(income, home value, rents, median age) are **not** predicted: variable
availability differs by vintage and `_request_dropping_unknown` drops what a
year rejects, so some will be null and which ones is not established here.

## P2 — The two that do not come back

decennial 1990 and decennial 2000 stay missing, and the parcel stays at 8 rows
rather than 10.

- **1990** — `api.census.gov` has no 1990 decennial dataset at all; the request
  404s (REPORT.md §4.3).
- **2000** — `2000/dec/sf1` addresses Connecticut tracts as `1571`, and we send
  `157100`, which 204s (REPORT.md §4.2).

Neither is affected by the county code, and neither is fixed by `4ce1822`.
**If either appears, this prediction is falsified** and the mechanism in §4 of
the report is wrong.

## P3 — Ledger outcomes on the new request

The re-run creates a new `timeline_request`, so a fresh set of
`timeline_task_years` rows. On that request's `census` task:

| source | group_key | expected outcome | expected reason | expected detail |
|---|---|---|---|---|
| `census_acs5` | 2009 | `ok` | — | `tract 09009157100` |
| `census_acs5` | 2012 / 2015 / 2018 | `ok` | — | `tract 09009157100` |
| `census_acs5` | 2021 | `ok` | — | `tract 09009157100` |
| `census_acs5` | 2023 | `ok` | — | `tract 09170157100` |
| `census_decennial` | 2010 | `ok` | — | `tract 09009157100` |
| `census_decennial` | 2020 | `ok` | — | `tract 09009157100` |
| `census_decennial` | 1990 | `absent` | `api_no_data` | `empty response for tract 09170157100` |
| `census_decennial` | 2000 | `absent` | `api_no_data` | `empty response for tract 09170157100` |

Ten groups, eight `ok`, two `absent`, zero `failed`, zero `indeterminate`.
The 1990/2000 detail still names `09170157100` because those two years stay
unmapped and keep the stored tract — that is the fix behaving as designed, not
a residue of the defect.

## P4 — Zero imagery churn

`imagery_snapshots` for this parcel is **identical before and after**: 43
`landsat`, 12 `sentinel2`, 6 `naip` (+11 `absent` groups), 7 `usgs_topo`, same
row ids. `4ce1822` touches only `_GEOGRAPHY_VINTAGES`; the fleet was last swept
2026-08-26 under `3a86dd69` with zero churn
(`../2026-08-m4-ledger/HEAL-SCORECARD.md` §11.2), and no selection rule has
changed since. A non-zero diff here means something other than this fix moved.

## P5 — Four geocoder calls, not one

The worker log for this request carries four `Resolved tract for vintage` lines
(`timeline.py:999`), one per distinct vintage, and no more — the per-vintage
cache holds for the whole fetch:

```
vintage=Census2010_Current  tract=09009157100  stored_tract=09170157100
vintage=ACS2021_Current     tract=09009157100  stored_tract=09170157100
vintage=Census2020_Current  tract=09009157100  stored_tract=09170157100
vintage=ACS2023_Current     tract=09170157100  stored_tract=09170157100
```

Zero `Vintage tract lookup failed, using stored tract` warnings. If one
appears, the year it covers may have fallen back to `09170157100` and P1 is
correspondingly at risk — check before scoring P1 as falsified.

## P6 — What does not change

`parcels.census_tract_id` stays `09170157100`, `parcels.county` stays
`"South Central Connecticut"`. Nothing in this batch writes either.

---

## Verification

Run inside the machine, `SELECT` only:

```
fly ssh console -a log0s-plotline-api -C "sh -c 'echo <b64> | base64 -d | python -'"
```

with:

```python
from sqlalchemy import text
from app.db import SessionLocal

PARCEL = "2f1b332e-2b96-401c-bba6-ce89e134dbf3"

snapshots = """
SELECT dataset, year, tract_fips, total_population, total_housing_units
FROM census_snapshots WHERE parcel_id = :p ORDER BY dataset, year
"""

ledger = """
SELECT y.source, y.group_key, y.outcome, y.reason, y.detail
FROM timeline_task_years y
JOIN timeline_request_tasks t ON t.id = y.task_id
JOIN timeline_requests r ON r.id = t.timeline_request_id
WHERE r.parcel_id = :p
  AND r.id = (SELECT id FROM timeline_requests
              WHERE parcel_id = :p ORDER BY created_at DESC LIMIT 1)
  AND y.source LIKE 'census%'
ORDER BY y.source, y.group_key
"""

imagery = """
SELECT source, count(*), min(capture_date), max(capture_date)
FROM imagery_snapshots WHERE parcel_id = :p GROUP BY source ORDER BY source
"""

for name, q in (("SNAPSHOTS", snapshots), ("LEDGER", ledger), ("IMAGERY", imagery)):
    print(f"--- {name} ---")
    with SessionLocal() as db:
        for row in db.execute(text(q), {"p": PARCEL}).all():
            print("|".join("" if v is None else str(v) for v in row))
```

Scoring, in order:

1. `SNAPSHOTS` has 8 rows; acs5 2009/2021 and decennial 2020 present with
   `tract_fips = 09009157100` and the populations in P1 → **P1 confirmed**.
2. No decennial 1990 or 2000 row → **P2 confirmed**. Either present →
   **P2 falsified**, and §4 of the report needs redoing.
3. `LEDGER` matches the P3 table row for row → **P3 confirmed**.
4. `IMAGERY` equals the pre-run capture → **P4 confirmed**. Capture it
   *before* the requeue; there is no after-the-fact baseline for this parcel
   alone.
5. `fly logs -a plotline-worker` (or the `fly ssh` channel) for the four
   `Resolved tract for vintage` lines → **P5**.
