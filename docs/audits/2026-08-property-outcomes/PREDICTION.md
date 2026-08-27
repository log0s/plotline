# Prediction — property outcomes (Z3, Z4, coverage gate)

Written 2026-08-27, **before** migration 0014 is deployed and before any
property task runs under the new code. Production at the time of writing is
`alembic_version = 0013` on both apps at `GH_SHA
07db132578cab59b5d86da816ed9af55c0c1fff5` (`fly image show -a
log0s-plotline-api` / `-a plotline-worker`, both identical), so none of the
five new columns exists yet and nothing here has been observed.

Per CLAUDE.md: this file is not edited to match the outcome. The observed
result lands next to each claim with a verdict.

## What scores this

No dedicated heal. The next fleet sweep re-runs property for the parcels it
touches, and the claims below are read off `timeline_request_tasks` after it.
Every claim is a `SELECT`; none needs a write.

## Baseline, read 2026-08-27 from production

Latest property task per parcel, adapter counties only
(`DISTINCT ON (p.id) … ORDER BY p.id, r.created_at DESC`):

| county | parcels | latest-task shape |
|---|---|---|
| Adams | 1 | `complete`, `items_found` 0 — `12804 Emerson Street, Thornton, Colorado 80241` |
| Denver | 9 | all `complete`; 5 with items (33, 13, 12, 11, 10, 2, 1), 4 at 0 |
| District of Columbia | 7 | all `complete`; 69, 10, 10, 5, 1, and 2 at 0 |
| New York | 6 | all `complete`; 64, 48, 37, 15, 7, and 1 at 0 |
| Santa Clara | 7 | all `complete`; 2 San Jose parcels at 1 item, 5 at 0 |

All-time property task counts for the same counties: Adams 9 tasks (all
`complete:0`), Denver 65 (64 `complete`, 1 `failed`), DC 40, NYC 28, Santa
Clara 30.

## Claims

**P-1 — the Adams parcel becomes `not_covered`, and asks nothing.**
`ebe38b44-6263-4777-a4ee-47132467a9d5` is the only Adams parcel in the fleet.
Its next property task: `status = 'skipped'`, `coverage = 'not_covered'`,
`items_found IS NULL`, `queries_run = 0`, `queries_failed = 0`. The worker log
carries `"Address outside adapter coverage"` with `city: THORNTON` and **no**
`ArcGIS Feature Service query` line for `Building_Permits_Eye_On_Adams` for
that parcel. Its nine historical `complete:0` rows are untouched.

**P-2 — four Santa Clara parcels join it; three do not.**
`not_covered`: `100 FOREST AVE, PALO ALTO`, `352 FULTON ST, PALO ALTO`,
`555 UNIVERSITY AVE, PALO ALTO`, `1600 AMPHITHEATRE PKWY, MOUNTAIN VIEW`.
`covered` and still queried: both `200 E Santa Clara St` parcels (San Jose),
**and** `Cupertino, California 95014` — that one is a city-level geocode whose
second comma component is the state, so `city_from_address` returns None and
the gate does not deny on a city it could not read. Expect it to stay
`complete:0` with `coverage = 'covered'`, `queries_run = 3`, `rows_returned =
0`. This is the deliberate weak spot; P-2 pins it rather than hiding it.

**P-3 — DC populates the counts, and `rows_returned >= rows_matched` on
every row.** All 7 DC parcels: `coverage = 'covered'`, `queries_run = 8`
(1 sales + 7 permit layers), `rows_returned` and `rows_matched` both non-NULL,
and `rows_returned >= rows_matched` with no exception. At least one task is
expected to show `rows_returned > rows_matched` — the sweep of 2026-08-27 saw
`180 → 53`, `15 → 10`, and once `1 → 0`. `2827 27TH ST NW, WASHINGTON, DC` is
the most likely carrier of a `rows_returned > 0, rows_matched = 0` row, since
it currently reads `complete:0`; that is a guess about which parcel, not about
whether the shape appears.

**P-4 — Denver stays `complete` on a normal day.** All 9 Denver parcels:
`queries_run = 2` (two permit layers; Denver's `fetch_sales` attempts none),
`queries_failed = 0`, `status = 'complete'`. A `partial` appears **only** if a
permit layer 429s past its retry budget. Z1's own scoring sweep ran 79 ArcGIS
queries with zero 429s, so the most likely observed count of `partial` tasks
in the next sweep is **0**. A `partial` that does appear is a confirmation of
Z3, not a deviation from this claim; a `complete` task with
`queries_failed > 0` would falsify it.

**P-5 — no non-property task is touched.**
`SELECT count(*) FROM timeline_request_tasks WHERE source <> 'property' AND
(coverage IS NOT NULL OR queries_run IS NOT NULL OR queries_failed IS NOT NULL
OR rows_returned IS NOT NULL OR rows_matched IS NOT NULL)` returns **0**, and
`items_found IS NULL` for a non-property task returns **0** as well.

**P-6 — no historical row is rewritten.** Immediately after `alembic upgrade
head` and before any new run: all five new columns are NULL on all 718
pre-existing task rows (dev count; production's own count is whatever it is at
migration time), `items_found IS NULL` count is 0, and no row's `status`
changes. The migration writes no `UPDATE`.

**P-7 — zero imagery and census churn.** No `imagery_snapshots` row and no
`census_snapshots` row is created, updated or deleted as a consequence of this
change. Scored by `census_snapshots.updated_at` (Y8) not moving outside
whatever the sweep's own census tasks touch, and by the imagery snapshot count
per parcel being unchanged for the Adams and four Palo Alto/Mountain View
parcels specifically — those are the parcels whose property task stops running
queries, and nothing else about their run changes.

**P-8 — the not-covered parcels stop re-dispatching.** After the Adams
parcel's task is `not_covered`, `maybe_refetch_for_backfill` returns None for
it on every subsequent visit: no new `timeline_requests` row with
`origin = 'backfill'` for `ebe38b44` appears from a property trigger. Before
this batch the task was `complete`, which also did not re-dispatch — so the
observable claim is the *absence* of a regression the new `skipped` status
would otherwise have introduced, since `skipped` is on the retry list.

## What would falsify the batch

- A property task with `coverage = 'not_covered'` and `queries_run > 0`.
- A task with `status = 'complete'` and `queries_failed > 0`.
- A task with `rows_matched > rows_returned`.
- Any Denver, DC or NYC task with `coverage <> 'covered'` — none of those three
  adapters overrides `covers()`.
- A San Jose address resolving to `not_covered`.

## Known limitation, stated before the run

The coverage rule reads the geocoder's **mailing** city, which is not a
jurisdiction. An unincorporated Adams address whose mail is addressed to
Thornton, Northglenn, Westminster, Commerce City, Federal Heights, Aurora or
Arvada will resolve to `not_covered` and never be queried. No such parcel is
in the fleet today (Adams has exactly one parcel, and it is genuinely in
Thornton), so this batch cannot observe the false negative either way. It is
recorded as an accepted risk in STATUS.md (AA2), not as a claim.
