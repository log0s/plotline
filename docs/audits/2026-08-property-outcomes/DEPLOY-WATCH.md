# Deploy watch — migration 0014 (property task counts, partial, coverage)

Observe-only. Read-only Fly access (`fly logs`, `fly image show`, `fly ssh
console -C` with `SELECT` only). No deploys, restarts, alembic, or writes were
run. Scores P-6 from `PREDICTION.md` only; P-1 through P-5, P-7, P-8 wait on
the next fleet sweep.

## 1. SHA

`git rev-parse HEAD` = `fbdc2f7e0e8686dea4b4302bd0a3234b1d1eaed7`.

`fly image show` labels, both apps:

- `log0s-plotline-api` (machines `825d69b7e46618`, `48e0de9a713918`):
  `GH_SHA=fbdc2f7e0e8686dea4b4302bd0a3234b1d1eaed7`
- `plotline-worker` (machine `e2862966b306d8`): same SHA.

Checked 2026-08-27T23:25:32Z, deploy boot at 23:17Z — 8 minutes, inside the
20-minute bound. Both apps on HEAD; no lag this time.

## 2. Boot — migration

`fly logs -a log0s-plotline-api`, machine `825d69b7e46618`:

```
23:17:14Z  Running upgrade 0013 -> 0014, Per-query counts, a task-level 'partial', and a coverage verdict.
23:17:14Z  Migration head check: database=['0014'] scripts=['0014']
```

Machine `48e0de9a713918` (the lock-waiter):

```
23:17:31Z-23:17:32Z  Context impl PostgresqlImpl. / Will assume transactional DDL.
23:17:32Z  Migration head check: database=['0014'] scripts=['0014']
```

No `Running upgrade` line on the second machine — it applied nothing, as
predicted, and both converge on `0014` within 18 seconds of each other.

## 3. Schema, fresh connection

Queried live via `psycopg2` against `DATABASE_URL` (asyncpg not present in
the prod image; adjusted the DSN and used psycopg2, which is installed).

```
alembic_version: 0014

ck_timeline_request_tasks_status:
CHECK ((status = ANY (ARRAY['queued'::text, 'processing'::text,
  'complete'::text, 'partial'::text, 'failed'::text, 'skipped'::text])))

ck_timeline_request_tasks_coverage:
CHECK (((coverage IS NULL) OR (coverage = ANY (ARRAY['covered'::text,
  'not_covered'::text, 'no_adapter'::text]))))

columns (all nullable): coverage, items_found, queries_failed, queries_run,
  rows_matched, rows_returned
```

Both predicates match the migration exactly: `partial` is admitted on the
status CHECK, the coverage CHECK is a three-value closed set plus NULL, and
all five new/relaxed columns are nullable.

## 4. P-6

Queried `timeline_request_tasks` fleet-wide:

| Metric | Predicted | Observed | Verdict |
|---|---|---|---|
| Total tasks | — | 5,525 | — |
| Rows with any of the 5 new columns non-NULL | 0 | 0 | **confirmed** |
| `items_found IS NULL` count | 0 | 0 | **confirmed** |
| Status distribution | unchanged | `complete` 4801, `failed` 54, `skipped` 670; zero `partial`, zero `queued`/`processing` | **confirmed** |

No prior full-table status-distribution snapshot exists in the audit trail
to diff against byte-for-byte (the y7-y8 scorecard and prior deploy-watches
recorded per-run counts, not a fleet-wide baseline of this table). The
observed distribution contains exactly the pre-0014 value set — no
`partial`, no row shows a new column populated — which is the direct
evidence for "no historical row rewritten." **P-6 confirmed on all four
falsifiable clauses**, with that one caveat noted rather than silently
assumed.

## 5. Worker

`plotline-worker`, machine `e2862966b306d8`, restarted 23:17:19Z-23:17:24Z
onto the new SHA. No alembic activity in its log (worker doesn't run
migrations) and no boot errors — only the standard Celery startup banner and
task registration (`tasks.fetch_imagery_timeline`).

No request ran during the watch window. The last task activity in the log
is at 22:00Z, before the restart, and both requests then were `origin:
"heal", declared: ["census"]` — census-only, no `property` task in that
batch. **No property task has run since the new worker came up**, so there
is nothing to quote for "new columns populated on a live run" — none ran.

## 6. UI — Adams parcel (`ebe38b44-6263-4777-a4ee-47132467a9d5`)

Queried directly rather than through the rendered page (`WebFetch` returns
only the SPA's static shell — no JS execution, so it can't confirm banner
rendering visually; noted as a limitation, not skipped).

Latest property task for this parcel: `6f18d138…`, `status='complete'`,
`items_found=0`, `coverage=NULL`, completed 2026-08-27T18:55:12Z — before
this deploy, so it's the historical row `PREDICTION.md` describes. Per
`ParcelInfo.tsx`'s `TaskRow`/`SourceIssueRow` logic (Z4/coverage work,
`REPORT.md` §5), the "not covered" banner only renders for a `skipped` task
with `coverage='not_covered'`; this task is `complete` with `coverage`
still NULL, so no banner path is reachable and the panel renders its normal
`complete:0` state. **Consistent with the code path, not visually
confirmed** — the `not_covered` banner will appear only after this parcel's
next property task run, as predicted.

## Summary

All six items check out. P-6 confirmed with the baseline caveat in §4. No
anomalies, no errors, no unexpected schema state. Deploy is clean.
