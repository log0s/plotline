# M4 ledger — first production sweep: stopped at the gate

**Written:** 2026-08-26, immediately after the stop.
**Authorised:** one full-fleet `scripts/revalidate_landsat.py` run under the
written heal exception, gated on phase 1 of the brief.
**Ran:** nothing. No production write was issued. The gate failed on its
second line and the sweep was not started.

**Verdict: the sweep cannot run, and the reason is worse than the sweep.**
Migration `0011` has never been applied to production. `timeline_task_years`
does not exist there. The cause is not the deploy, not the migration, and not
M4 — it is `backend/alembic/env.py`, where the advisory lock added by `dd99cee`
(2026-08-03) puts every migration into a transaction alembic then declines to
commit. Alembic logs the upgrade as successful and the connection rolls it back
on close. `0011` is the first migration to run under that code, and it is the
first one to be silently discarded.

The live consequence is separate from M4 and larger: with the `0011` ORM and
recorder deployed against a database that has no ledger table, **the next
timeline request in production fails.** None has arrived since the deploy, so
nothing has broken yet.

---

## 1. The gate, line by line

| # | Gate line | Result |
|---|---|---|
| 1 | `GH_SHA` on both apps = `ce307e35…`, health agrees | **PASS** |
| 2 | `alembic_version` = `0011`; `timeline_task_years` exists, empty | **FAIL** — version is `0010`; the table does not exist |
| 3 | No `queued` / `processing` timeline request | PASS (checked anyway) |
| 4 | Dry-run lists exactly 184 parcels | not run — gate 2 failed |
| 5 | Before-state capture | not run |
| 6 | Log streams started | not started |

Per the brief, gate 2 failing stops the run. It did.

### 1.1 Gate 1 — evidence

`fly image show -a plotline-worker` (machines `e2862966b306d8`,
`e7845415f57728`) and `fly image show -a log0s-plotline-api` (machines
`825d69b7e46618`, `48e0de9a713918`) all carry
`GH_SHA=ce307e352bfcbf0b81be9f444b4dc25fdecad24e`, digest
`sha256:a9815274…4aa8`.

`fly ssh console -a log0s-plotline-api -C "curl -s http://localhost:8000/api/v1/health"`:

```
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"ce307e352bfcbf0b81be9f444b4dc25fdecad24e",
            "built":"2026-08-26T00:51:55Z"}}
```

The code under prediction is deployed. Only the schema it needs is not.

### 1.2 Gate 2 — evidence

Read on the API machine through `app.db.SessionLocal`, i.e. the exact engine
the application uses, so there is no question of a second database:

```
== alembic_version
   0010
== columns            (information_schema.columns, table_name='timeline_task_years')
   <empty>
== constraints
   psycopg2.errors.UndefinedTable: relation "timeline_task_years" does not exist
```

Independently, alembic's own answer on the same machine:

```
$ fly ssh console -a log0s-plotline-api -C "sh -c 'cd /app && alembic current'"
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
0010
```

### 1.3 Gate 3 — evidence

`timeline_requests`: 519 `complete`, 3 `failed`, **0 `queued`, 0 `processing`**.
Most recent request `created_at` = `2026-08-25 22:20:00.603722+00`. Database
clock at capture: `2026-08-26 00:59:39 UTC`. **Zero requests created at or
after `2026-08-26T00:52:00Z`** — the deploy boundary.

---

## 2. The contradiction that had to be resolved

The deploy logs say the migration ran. Twice, on both API machines, each
reporting success:

```
2026-08-26T00:52:22Z app[825d69b7e46618] Running database migrations...
2026-08-26T00:52:27Z app[825d69b7e46618] INFO  [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
2026-08-26T00:52:28Z app[825d69b7e46618] Migrations complete.
2026-08-26T00:52:40Z app[48e0de9a713918] Running database migrations...
2026-08-26T00:52:45Z app[48e0de9a713918] INFO  [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
2026-08-26T00:52:45Z app[48e0de9a713918] Migrations complete.
```

Two things in that transcript are wrong on their face, and they have the same
cause. First, the database is still at `0010`. Second, **the second machine
also read `0010`** — it ran the same upgrade 18 seconds after the first
machine "succeeded". That is precisely what the advisory lock in `env.py`
exists to prevent, and it is the tell: the first machine's work never landed,
so there was nothing for the second to find.

Neither `alembic` nor `entrypoint.sh` can detect this. `alembic upgrade head`
exits 0, `set -e` is satisfied, and the container proceeds to serve.

---

## 3. Root cause — `backend/alembic/env.py:96-109`

```python
with connectable.connect() as connection:
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
    try:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY})
```

The chain, each link verified against the alembic installed in the production
image (`alembic 1.18.4`, `sqlalchemy 2.0.49`):

1. `connection.execute(pg_advisory_lock)` is the connection's first statement.
   SQLAlchemy 2.0 **autobegins** a transaction on it. `connection.in_transaction()`
   is now `True`.
2. `context.configure(connection=connection)` sets
   `MigrationContext._in_external_transaction = sqla_compat._get_connection_in_transaction(connection)`
   — `alembic/runtime/migration.py:158-160`. It is `True`.
3. `context.begin_transaction()` opens with
   `if self._in_external_transaction: return nullcontext()`
   — `alembic/runtime/migration.py:416-417`. Alembic concludes that a caller
   owns the transaction and **hands the commit to that caller**.
4. `run_migrations()` executes the DDL and the `UPDATE alembic_version`
   inside the autobegun transaction. It logs `Running upgrade 0010 -> 0011`
   because it genuinely ran it.
5. The `finally` unlock runs in the same transaction.
6. `with connectable.connect()` exits. `Connection.close()` **rolls back** the
   autobegun transaction. The table and the version bump go with it.

No caller ever commits. There is no such caller: `env.py` believed alembic
would.

### 3.1 Why every migration before this one survived

`dd99cee` ("fix: bound Redis waits, lock migrations, dispose worker engine")
landed **2026-08-03**. It is the only commit that has ever touched
`_MIGRATION_LOCK_KEY`. Migration `0010` was committed **2026-06-12** (`86aae50`)
and was applied before the lock existed. Between 2026-08-03 and 2026-08-25 no
new migration existed, so every deploy in that window found itself at head and
ran no upgrade — the printed transcript was `Migrations complete.` with no
upgrade line, which is exactly what the 23:18Z boots show.

`0011` (`0814d7e`, 2026-08-25) is therefore **the first migration in the
project's history to execute under the advisory-lock code**, and it failed to
persist on its first attempt. No prior migration is at risk and no data was
lost; the defect had simply never been reachable before.

---

## 4. Reproduction

Local only. Nothing in this section touched production.

### 4.1 The real code path, real alembic, local Postgres

A local `postgres` container whose volume already stood at `0010` — the same
starting state as production:

```
$ DATABASE_URL=postgresql://plotline:plotline@localhost:5432/plotline \
    .venv/bin/alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.

$ ... alembic current
0010
alembic_version: 0010
timeline_task_years exists: None
```

Byte-for-byte the production transcript, including the exit code. **Confirmed.**

### 4.2 Both directions — the lock statement is the whole cause

A standalone script (no repo file edited) that reproduces `env.py`'s structure
with alembic's own `MigrationContext`, once with the pre-`configure` lock
statement and once without:

```
A. env.py as written (advisory lock acquired before configure):
  with_lock=True  in_transaction=True  _in_external_transaction=True
  -> repro_locked persisted after close: False
B. identical, minus the pre-configure lock statement:
  with_lock=False in_transaction=False _in_external_transaction=False
  -> repro_unlocked persisted after close: True
```

Removing the one statement is the difference between discarded and durable.
This is the delete-the-fix direction, run on the cause rather than on a test.

---

## 5. Blast radius — production's timeline pipeline is broken, latently

This is not confined to a missing instrument. `ce307e35` deploys the recorder
against a database with no table to record into, and the recorder is on the
**mandatory** path, not an optional one:

- `fetch_imagery_timeline` → `_run_timeline` moves the request to
  `processing` (`timeline.py:1374`), then calls
  `imagery_service.create_request_tasks(...)` (`timeline.py:1383`).
- `create_request_tasks` runs, **for every source, on every request**, not
  only on a Celery redelivery: `clear_task_year_outcomes(db, timeline_request_id, source)`
  (`imagery.py:287-288`).
- That issues `DELETE FROM timeline_task_years …`
  (`year_ledger.py:195-217`) against a table that does not exist →
  `psycopg2.errors.UndefinedTable`.
- Nothing catches it. `record_year_outcome` and `clear_task_year_outcomes`
  have no guard, by design — the ledger row is meant to be atomic with its
  snapshot.
- The task boundary (`timeline.py:1577-1601`) marks the request `failed` with
  the exception text and re-raises.

So every timeline request that reaches the worker fails at the first write,
before any imagery, census or property fetch is attempted. The user gets a
definitive `failed` status rather than a raw 500 — the error contract holds —
but the feature does not work.

**Why nothing is on fire yet:** zero timeline requests have been created since
the deploy at `2026-08-26T00:52Z`. The evidence is the absence of arrivals, not
the absence of the fault. The `fly logs -a plotline-worker` buffer contains no
`timeline_task_years`, `UndefinedTable` or `does not exist` line — consistent
with the fault never having been exercised.

The sweep this session was authorised to run would have been the thing that
exercised it, 184 times.

---

## 6. Why nothing caught it

`.github/workflows/deploy.yml` contains **no alembic step**. `backend/tests/conftest.py`
builds its schema as hand-written DDL against an in-memory SQLite engine
(`conftest.py:33-223`), so the migration directory is never executed anywhere
in CI. A migration that runs, logs success, and persists nothing is invisible
to every check in the pipeline — including the 488-test suite that ships with
`0011`, which passes because its tables are created by `_create_test_tables()`,
not by alembic.

This is the same shape as M7 ("`conftest.py:55-190` still hand-written DDL"),
which the record already carries as an ORM/schema-drift risk. It is now also a
migration-execution risk, which that row does not say.

---

## 7. What this session did not produce, and why

- **`HEAL-SCORECARD.md`** — does not exist. There is no run to score.
- **`BASELINE.txt`** — does not exist. `ledger_gaps.py --all` against
  production today would fail on the missing table; even if it did not, an
  empty baseline captured before the ledger works is not the artefact the
  brief describes, and writing one would make later sweeps diff against a lie.
- **`PREDICTION.md` is unscored, in full.** P1–P6 all name populations the
  sweep did not create. Nothing in it is confirmed, deviated or falsified. It
  is not edited, and it remains the live prediction for whenever the sweep
  does run.
- **G9's first production verification** (the `depth`/`cap` fields on the
  admission-wait line, `b537953`) did not happen. The sweep is still its only
  planned exercise. `b537953` remains committed, deployed as of
  `2026-08-26T00:51:55Z`, and never observed in production.

---

## 8. The fix, not applied

No code was changed. For the record, the remedy is to stop the lock statement
from owning the transaction alembic wants to open. Either:

- acquire the lock on a **separate** connection held for the duration, or
- acquire it inside an explicit `connection.begin()` the env.py commits itself,
  or
- run the lock statement under `AUTOCOMMIT` execution options so no
  transaction autobegins.

Whichever is chosen, the regression test has to run alembic against a real
Postgres and assert the version moved — a SQLite/`create_all` suite structurally
cannot fail on this. That is a CI change, not just a code change.

Ordering, once fixed: the migration must land on production **before** the next
timeline request, and the current image is already the one that needs it.

---

## 9. UNVERIFIED

- **Whether any timeline request has been attempted and failed in a log window
  older than the retained buffer.** `fly logs --no-tail` shows only the
  retained buffer. The DB evidence — zero requests created after the deploy —
  is stronger and does not depend on log retention, but it bounds the claim to
  *created* requests; a request created before the deploy and picked up by the
  worker after it would not be visible this way. `timeline_requests` shows 0
  `queued` and 0 `processing`, which closes that gap for anything still in
  flight, and the 3 lifetime `failed` rows all predate the deploy.
- **Whether the same rollback affects the `worker` app.** It cannot:
  `entrypoint.sh` skips migrations when `$1` is `celery`. Verified by reading
  the script, not by observing a worker boot.
- **Whether any local developer database is also stuck at `0010`.** The one
  used for the reproduction in §4.1 is. Whether others are was not checked.

---

## 10. Anomalies

Flagged, not investigated:

1. **Both API machines ran the migration 18 s apart and both reported success.**
   Explained by §3 — but it also means the advisory lock has never actually
   serialized anything, because the state it serializes against is discarded
   before the second machine reads it. M10 is recorded as "Partially resolved
   (dd99cee)" on the strength of that lock. It is not.
2. **The 23:18Z boot pair and the 00:52Z boot pair are ~94 minutes apart on
   the same SHA.** Not investigated; the 23:18Z pair predates the `0011` image
   and shows no upgrade line, which is consistent with a `0010`-era deploy.
