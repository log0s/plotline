# Property outcomes — scoring run

Scores `PREDICTION.md` P-1 through P-5, P-7, P-8 (P-6 was scored in
`DEPLOY-WATCH.md`). One prod write: `scripts/requeue_parcels.py <32 ids>
--sources property --max-wait-minutes 30`, run once inside the `fbdc2f7`
API machine, owner-approved. Everything below is read after the run; no
further writes.

## Phase 1 — Gate

1. **Both apps on `fbdc2f7`**, confirmed before the run (`fly image show`,
   both API machines and the worker). No in-flight `timeline_requests`
   (`status IN ('queued','processing')` returned zero rows).

2. **Parcel list — deviation from the prediction's baseline.** Query:
   `SELECT lower(replace(county,' county','')), id, address FROM parcels
   WHERE lower(replace(county,' county','')) IN ('denver','adams','district
   of columbia','santa clara','new york')`. Result: Adams 1, **Denver 11**,
   DC 7, New York 6, Santa Clara 7 — **32 parcels, not the 30 (Denver 9)
   `PREDICTION.md`'s baseline table states.**

   Traced, not just flagged: Denver's all-time property task count (65,
   `PREDICTION.md`'s own number) already implied 11 parcels, not 9 — the
   prediction's per-parcel items list (`33, 13, 12, 11, 10, 2, 1` + "4 at
   0") sums to 7 nonzero + 4 zero = 11, one more than its own "9" header.
   Both Denver parcels at `1437 Bannock St, Denver, CO 80202` (`71d85fbd…`,
   `39fc3efc…`) are genuine, independent, pre-existing rows — created
   2026-04-14 and 2026-05-23, both with real property task history (5 and 6
   prior tasks respectively) — not something created by today's batch. The
   prediction's baseline table undercounted by exactly one duplicate-address
   parcel and one `items_found=0`; every other county's count matches
   exactly. **`PREDICTION.md` is not edited.** This is a baseline error in
   the document, recorded here rather than silently absorbed.

   Cupertino (`2e30825d-d4af-4451-a8d5-b1eaca2138be`) is included, as
   required.

3. **Before-state**, all 32 parcels: latest property task per parcel (all
   `complete` or the Adams historical row) and `property_events` counts —
   captured before the run, retained for the delta check in §10.

4. **Dry-run**: `--dry-run` against all 32 ids, scope `property`. Deploy
   gate passed (`fbdc2f7e0e8686dea4b4302bd0a3234b1d1eaed7`), all 32 listed
   `[property]`, zero skipped. Confirmed the real run would do exactly this
   before running it for real.

5. Worker logs captured post-run (`fly logs -a plotline-worker --no-tail`);
   stdout of the write captured to a scratch file.

## Phase 2 — Run

Ran once, 2026-08-27T23:48:18Z-23:48:34Z. **Exit 0. Queued 32, skipped 0.**
All 32 `timeline_requests` reached `status = 'complete'` by the time of the
first poll (well under the 30-minute wait budget).

## Phase 3 — Score

### 1. Hygiene

- 32 requests created, all `origin = 'heal'`, all `sources = ['property']`.
- Exactly one task per request (32 tasks total), all `source = 'property'`.
- Admission: **one wait occurred**, not none. `Admission refused
  (cap=25, depth=25, hard_cap=30, reason=queue_full)` at 23:48:28Z after 21
  of 32 requests were already queued, followed by a 5-second poll and a
  successful admission at 23:48:33Z — the remaining 11 queued normally
  after that. Not a failure (the script's designed wait-not-fail path
  worked exactly as documented), but a deviation from "expect none" —
  logged under Anomalies (§11).

### 2. P-1 — Adams

`ebe38b44…` task: `status='skipped'`, `coverage='not_covered'`,
`items_found=NULL`, `queries_run=0`, `queries_failed=0`. **Confirmed on
every field.**

Worker log: zero lines anywhere in the captured buffer mention the Adams
parcel id, `Eye_On_Adams`, or `ArcGIS` — so there is no ArcGIS Feature
Service query line for it, confirmed by absence. The specific `"Address
outside adapter coverage" city=THORNTON` line was **not captured** in the
buffer, even though the same buffer holds all four Santa Clara
not-covered lines from the same run 60-70 seconds later. This matches the
known `fly logs` capture gap already recorded in STATUS.md's Z4 row ("fly
logs dropped ~3% of this run's stream") — the DB row is unambiguous
regardless, so the claim is confirmed on the data, with the log line as
unconfirmed-but-expected rather than a deviation.

### 3. P-2 — Santa Clara

`not_covered`: `100 Forest Avenue, Palo Alto`, `352 Fulton Street, Palo
Alto`, `555 University Ave, Palo Alto`, `1600 Amphitheatre Pkwy, Mountain
View` — all four `skipped`/`not_covered`/`queries_run=0`, confirmed by
worker log lines (`county=Santa Clara`, cities `PALO ALTO` ×3, `MOUNTAIN
VIEW` ×1).

`covered`: both San Jose parcels (`queries_run=3`, `rows_returned=1,
rows_matched=1` each — real data, unchanged from before) and Cupertino
(`coverage='covered'`, `queries_run=3`, `rows_returned=0`,
`rows_matched=0`, `items_found=0`). **All confirmed, weak spot pinned
exactly as predicted** — the city-level geocode still resolves through the
gate as `covered` because `city_from_address` returns `None` for it.

### 4. P-3 — DC

All 7 DC parcels: `coverage='covered'`, `queries_run=8`, both
`rows_returned`/`rows_matched` non-NULL, `rows_returned >= rows_matched`
with **zero** exceptions. At least one row shows `rows_returned >
rows_matched`: four do —

| parcel | rows_returned → rows_matched |
|---|---|
| `1300 4th St SE` | 180 → 53 |
| `1600 Pennsylvania Ave NW, 20500` | 15 → 10 |
| `1600 Pennsylvania Ave NW` (no zip) | 15 → 10 |
| `2827 27th St NW` | 1 → 0 |

`2827 27th St NW, Washington, DC` carries the `1 → 0` row — **exactly the
parcel `PREDICTION.md` guessed**, and its guess is stated as a guess, not
a claim; the claim (the shape appears) is confirmed regardless. **P-3
confirmed on every clause.**

### 5. P-4 — Denver

All 11 Denver parcels (see §Phase-1-item-2 for the count deviation):
`queries_run=2`, `queries_failed=0`, `status='complete'` on all 11.
**Zero `partial` tasks** — matches the prediction's "most likely 0", and
no `complete` task shows `queries_failed > 0` (checked fleet-wide, not
just Denver — see falsifiers below). **P-4 confirmed**, unaffected by the
parcel-count deviation since the claim is per-parcel, not "9 of 9".

### 6. P-5

`SELECT count(*) FROM timeline_request_tasks WHERE source <> 'property'
AND (coverage IS NOT NULL OR queries_run IS NOT NULL OR queries_failed IS
NOT NULL OR rows_returned IS NOT NULL OR rows_matched IS NOT NULL)` → **0**.
`items_found IS NULL` for a non-property task → **0**. **P-5 confirmed**,
fleet-wide, not just this batch's tasks.

### 7. P-7

No `imagery_snapshots` row created after the run started (23:48:00Z):
**0**. No `census_snapshots` row created or updated after the run started:
**0** and **0**. `imagery_snapshots` has no `updated_at` column (insert-
only table), so the created-at check is the whole story for it. **P-7
confirmed** — this run touched nothing outside the 32 `property` task rows
and their `property_events`.

### 8. P-8

Adams parcel's request history, newest first: this run's `79051e5d…`
(`origin='heal'`, `complete`), then `4a4a5803…` (`origin='heal'`,
2026-08-27T18:48Z — pre-migration, historical), then three `origin='user'`
requests going back to 2026-08-12. **No `origin='backfill'` request exists
for this parcel anywhere in its history**, before or after this run's
`not_covered` task. `maybe_refetch_for_backfill` has not re-dispatched it.
**P-8 confirmed** — checked by full history rather than "twice", which is
the stronger form of the same claim.

### 9. Falsifiers — all four checked, none triggered

| Falsifier | Query result |
|---|---|
| `coverage='not_covered' AND queries_run > 0` | **0** |
| `status='complete' AND queries_failed > 0` | **0** |
| `rows_matched > rows_returned` | **0** |
| Denver/DC/NYC task with `coverage <> 'covered'` | **0** (checked against this run's 32 requests) |
| San Jose address resolving `not_covered` | **0** |

**None of the five falsifying conditions occurred.**

### 10. `property_events` delta

Post-run counts per parcel are **identical** to the pre-run snapshot
(§Phase-1-item-3) for all 32 parcels — same counts, same values, no
parcel gained or lost a row. Consistent with `ON CONFLICT DO NOTHING`
(M8): every event this run's queries returned was either already present
or newly matched-and-inserted at the same final count as before (the
adapters re-queried the same live portals and got the same current
state). **Zero net churn, add-only semantics upheld.**

### 11. Anomalies

1. **Denver parcel-count baseline error** — `PREDICTION.md` states 9
   Denver parcels; there are 11. Traced to the prediction's own item list
   (§Phase-1-item-2); not a fleet change since the prediction was written.
   Does not affect any claim's truth, only its stated population.
2. **One admission wait** during the write, `cap=25/hard_cap=30`, resolved
   in 5 seconds with no operator action needed — the script's designed
   behavior, not a failure, but worth recording since the run instructions
   expected none.
3. **Adams `"Address outside adapter coverage"` log line not captured** —
   DB-confirmed regardless (§P-1); attributed to the known `fly logs`
   capture gap (STATUS.md Z4).

No other anomalies. All 32 requests reached `complete`; zero `failed`,
zero `partial`, zero unreached.

## Summary

Every falsifiable claim in P-1 through P-5, P-7, P-8 confirmed, zero
deviations from the predicted *shape* of any outcome. The one real
deviation is in the prediction's own baseline count (Denver 9 vs 11),
called out rather than silently corrected. `DEPLOY-WATCH.md` already
scored P-6. All eight claims in `PREDICTION.md` are now scored, all
confirmed.
