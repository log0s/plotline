# M3 Deploy Watch — migration 0012, scope/origin/partial

Observe-only. No writes, no deploys, no alembic invoked. All commands were
`fly logs` / `fly status` / `fly image show` / `fly ssh console -C` with
`SELECT`-only SQL, plus the live `/api/v1/timeline-requests/{id}` endpoint.

## 1. Deploy

The push had not yet triggered CI at the start of this watch (both machines
still on `GH_SHA=b599c25`, the M3 base). Run `33088980652` started at
`2026-08-27T15:39:11Z` and completed `success` at `15:43:33Z`:

| job | conclusion | started | completed |
|---|---|---|---|
| changes | success | 15:39:14Z | 15:40:44Z |
| test | success | 15:40:46Z | 15:41:26Z |
| test-frontend | success | 15:40:46Z | 15:41:15Z |
| deploy-titiler | skipped | — | — |
| deploy-api | success | 15:41:28Z | 15:42:36Z |
| deploy-worker | success | 15:41:28Z | 15:42:55Z |

`test` ran and passed on head SHA `5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce`.
The `changes` job's "Determine diff base" / "Log diff base for this run"
steps ran and succeeded; the literal step-summary text could not be pulled —
no GitHub token is configured in this environment and the public
unauthenticated API 403s on job logs for this (private) repo. Not re-derived
from a lower-confidence source.

Both apps now report `GH_SHA=5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce`
(`fly image show`, confirmed on both machines of each app).

## 2. Boot sequence

API app `log0s-plotline-api`, from `fly logs`:

```
2026-08-27T15:42:11Z app[48e0de9a713918] Running database migrations...
2026-08-27T15:42:11Z app[48e0de9a713918] INFO [alembic.runtime.migration] Running upgrade 0011 -> 0012, Declared scope and origin on timeline_requests, plus the 'partial' status.
2026-08-27T15:42:12Z app[48e0de9a713918] INFO [alembic.env] Migration head check: database=['0012'] scripts=['0012']
2026-08-27T15:42:12Z app[48e0de9a713918] Migrations complete.
2026-08-27T15:42:23Z app[825d69b7e46618] Running database migrations...
2026-08-27T15:42:28Z app[825d69b7e46618] INFO [alembic.env] Migration head check: database=['0012'] scripts=['0012']
2026-08-27T15:42:28Z app[825d69b7e46618] Migrations complete.
```

Exactly one machine (`48e0de9a713918`) ran the upgrade line. The second
machine (`825d69b7e46618`) went straight from "Running database
migrations..." to the head check at `['0012']=['0012']` with no upgrade
line — it found the DB already at head. Alembic does not log a distinct
"waiting on lock" line, so that specific wait was not directly observed;
the timing (11s gap between the two machines' migration starts) and the
absence of a second upgrade attempt are consistent with the second machine
serializing behind the first via the xact lock rather than racing it.

## 3. Schema (fresh connection)

`SELECT version_num FROM alembic_version` → `0012`.

```
COLUMNS: origin (text, NOT NULL), sources (ARRAY, NOT NULL)
CONSTRAINTS:
  ck_timeline_requests_origin  CHECK (origin = ANY (ARRAY['user','backfill','heal']))
  ck_timeline_requests_sources CHECK (cardinality(sources) > 0 AND sources <@ ARRAY['census','landsat','naip','property','sentinel2','usgs_topo'])
  ck_timeline_requests_status  CHECK (status = ANY (ARRAY['queued','processing','complete','partial','failed']))
INDEXES (new): idx_timeline_requests_parcel_full_scope
  ON timeline_requests (parcel_id, created_at DESC) WHERE cardinality(sources) = 6
```

Zero rows with empty/null `sources`, zero with null `origin`.

## 4. Backfill verification

- `origin, COUNT(*)`: `('user', 710)` — all 710 existing requests, exactly
  the predicted single bucket.
- `cardinality(sources), COUNT(*)`: `(6, 710)` — every existing request is
  full-scope; none partial-scope, as expected for pre-M3 requests.
- `status = 'partial'` count: **40** — matches the `REPORT.md` prediction
  exactly.
- All 40 partial requests were pulled with their task source/status
  breakdown; every one has at least one `failed`/`complete` (or
  `failed`/`skipped`+`complete`) mix, i.e. every row satisfies the
  aggregation definition (some failed, some not). No violations found.
- Crawford County's parcel (`6563dedf-23b1-4719-89db-ab135ed24fb3`, county
  `Crawford`, Camp Grayling / Grayling Charter Township, MI) has exactly one
  request, `b1392b23-63ad-46d2-b9ab-97cd09d61a2e`, and it is among the 40:
  `census:complete, landsat:complete, naip:failed, property:skipped,
  sentinel2:failed, usgs_topo:complete`. This doubles as one of the spot
  checks (≥1 failed, ≥1 complete).

## 5. UI / API status

`GET /api/v1/timeline-requests/b1392b23-63ad-46d2-b9ab-97cd09d61a2e` → `200`,
no error banner:

```json
{"id":"b1392b23-63ad-46d2-b9ab-97cd09d61a2e","parcel_id":"6563dedf-23b1-4719-89db-ab135ed24fb3","status":"partial","created_at":"2026-08-26T09:14:35.367559Z","completed_at":"2026-08-26T09:42:25.113329Z","error_message":null,"tasks":[{"source":"census","status":"complete","items_found":8,...},{"source":"landsat","status":"complete","items_found":27,...},{"source":"naip","status":"failed","items_found":0,...,"error_message":null},{"source":"property","status":"skipped","items_found":0,"started_at":null,...,"error_message":"Property data not yet available for Crawford County"},{"source":"sentinel2","status":"failed","items_found":0,...,"error_message":null},{"source":"usgs_topo","status":"complete","items_found":3,...}]}
```

## 6. Worker

`plotline-worker` boot logs show no migration/alembic activity (workers
don't run migrations) and no errors or tracebacks. Both machines report
`GH_SHA=5f3aa7d...`, the standby machine is `stopped` (expected — takes over
only on host failure). No user request arrived during the watch window to
check `origin=user`/full-scope on a fresh dispatch; none observed, so that
sub-item is unconfirmed rather than confirmed.

## 7. Admission reserve

`Settings().user_admission_reserve` on the running API image = **5** —
matches the prediction.

## Verdict

**Confirmed, no deviations.** Migration 0012 applied cleanly on exactly one
machine, both machines converged on `0012`, the schema matches the migration
as declared, and the backfill hit the predicted 40/40 with zero anomalies.
Crawford's request — the motivating case for Y1 — now reads `partial` in
both the database and the live API with no error surfaced. `user_reserve`
matches. M3 is deployed; its three acceptance heals have not run and are out
of scope for this watch.
