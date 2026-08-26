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

---

# Addendum, 2026-08-26 — the runner is fixed (`edc13db`)

Written after the fix, in the same session as the stop above. Nothing in
§1–§10 is edited. **Committed, not deployed: production is still at `0010`
with no `timeline_task_years` as of this writing, so §5's blast radius stands
in full.** The sweep is still not runnable.

The hotfix was scoped to the migration path. Migration `0011`, the ledger code
and `scripts/ledger_gaps.py` are untouched — the migration was always correct;
the runner was not.

## 11. Reproduction, before and after

Same local database, standing at `0010` — the same starting state as
production. Same command both times.

**Before** (`ce307e35`'s `env.py`):

```
$ DATABASE_URL=postgresql://plotline:plotline@localhost:5432/plotline \
    .venv/bin/alembic current
0010
$ ... alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
exit=0
$ ... alembic current
0010
alembic_version = 0010
timeline_task_years = None
```

**After** (`edc13db`):

```
$ ... alembic upgrade head
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.env] Migration head check: database=['0011'] scripts=['0011']
exit=0
$ ... alembic current
0011 (head)
alembic_version = 0011
timeline_task_years = timeline_task_years
```

The new `alembic.env` line is the readback. It is the only thing in the
transcript that distinguishes a real success from the one production got, and
before this commit there was nothing there at all.

## 12. What changed

All in `backend/alembic/env.py`.

**The transaction and the lock (`:141-191`).** The lock statement,
`context.configure()` and `context.run_migrations()` now run inside one
explicit `with connection.begin():` (`:179`) that `run_migrations_online`
owns and commits, and `pg_advisory_lock` becomes `pg_advisory_xact_lock` on
the same key (`:181`). The paired `pg_advisory_unlock` in the old `finally` is
gone — the commit releases the lock.

Both halves are load-bearing and they close different holes:

- The **explicit transaction** is what makes anything commit. Alembic still
  reads `_in_external_transaction` as `True` and still returns a `nullcontext`
  from `begin_transaction()` — that behaviour is unchanged and correct. The
  difference is that the external transaction it defers to now exists.
- The **transaction-scoped lock** makes the release simultaneous with the
  version bump becoming visible. A session-scoped lock released before the
  commit would let a second booter acquire it and read a stale
  `alembic_version`, which is the race M10 added the lock for.

`context.begin_transaction()` is deliberately absent from the new block.
Inside an owned transaction it can only be a `nullcontext`, and its presence
is precisely what made the original look like it committed.

**Ordering, verified rather than assumed.** The lock is taken before
`context.run_migrations()`, which is where alembic reads the current revision:
`MigrationContext.run_migrations` → `heads = self.get_current_heads()`,
`alembic/runtime/migration.py:488` (alembic 1.18.4). `context.configure()`
issues no read of its own. Both facts are now stated in the comment at the
site.

**The readback (`_verify_at_head`, `:56-95`; called at `:190-191`).** After a
head-destined upgrade the version is read on a **fresh** connection — the
engine is `poolclass=pool.NullPool`, so `connect()` opens a new session and
sees committed state, not the runner's own uncommitted view — and compared to
`ScriptDirectory.get_heads()`. Both are logged at INFO through the `alembic`
logger the ini already configures; a mismatch raises. **A boot that logs
`Migrations complete.` against the wrong head can no longer exit 0.**

**Scoping (`_destination_is_head`, `:37-53`).** `alembic current`, `stamp` and
`downgrade` run this same `env.py`, and for them a database behind head is the
expected state, not an error. The first version of the readback was
unconditional and broke `alembic current` — found by running the commands, not
by reasoning about them, and recorded here because the reasoning had not
predicted it. The gate resolves the destination revision
(`context.get_revision_argument()`, which turns `head` into a concrete
revision and raises `KeyError` when a command has no destination) and verifies
only when it is a script head.

`.github/workflows/deploy.yml:56-96`: the `test` job gains a
`postgis/postgis:16-3.4-alpine` service and `TEST_POSTGRES_URL`. PostGIS
rather than plain Postgres because migration `0001` creates the extension.

## 13. Tests

`backend/tests/test_migrations_postgres.py`, 3 added, **525 passing** (from
522). Each test creates a throwaway database, migrates that, and drops it;
the database `TEST_POSTGRES_URL` names is never migrated or modified, so a
developer pointing it at their working database loses nothing.

| Test | What it asserts | Result |
|---|---|---|
| `test_upgrade_head_commits_the_schema_and_the_version` (`:160`) | after `upgrade head`, `alembic_version == [head]` and `timeline_task_years` exists, read on connections the test owns | pass |
| `test_concurrent_boots_from_0010_converge_on_head` (`:184`) | two real boots from `0010`, both exit 0, no duplicate DDL, one version row at head | pass |
| `test_postgres_migration_tests_are_not_silently_skipped` (`:58`) | fails rather than skips when `CI` is set and the URL is not | pass |

**The concurrency test is M10's actual property, and it had never been
tested.** The contention is forced rather than hoped for: the test holds the
migration advisory lock on its own connection, starts both
`python -m alembic upgrade head` subprocesses, polls `pg_locks` until two
waiters are provably blocked on that key, and only then releases. Without
that, process startup jitter is an order of magnitude longer than the
migration and the two would usually never overlap. Two processes rather than
two threads because `alembic.context` is a process-global proxy — two
in-process `command.upgrade` calls would contend on alembic's own state rather
than on the database's.

**Gating, verified three ways:**

| Environment | Result |
|---|---|
| `TEST_POSTGRES_URL` set, `CI=true` | `3 passed` |
| no URL, no `CI` (a local checkout) | `1 passed, 2 skipped` |
| no URL, `CI=true` | `1 failed` — `TEST_POSTGRES_URL is not set, so the migration tests would skip.` |

### 13.1 Delete-the-fix, both ways

| Reversion | Failure |
|---|---|
| **A — the explicit transaction only** (restore `pg_advisory_lock` + `try/finally`, keep the readback) | `RuntimeError: Migrations reported success but the database is not at head: database=[], scripts=['0011']. The upgrade did not commit.` |
| **B — transaction and readback** (`env.py` exactly as at `HEAD`) | `AssertionError: assert [] == ['0011']` |

Neither fails on a connection error, which is what makes it a test of the
commit rather than of the harness. The concurrency test fails under both
reversions too, at its `0010` precondition (`assert [] == ['0010']`) — under
the old runner even the setup migration does not commit.

## 14. Deviations from the brief

1. **`ScriptDirectory.get_heads()` rather than `get_current_head()`.** The
   brief named the singular form. `get_current_head()` raises when the tree
   has multiple heads, which would turn a verification into a crash with a
   misleading message on a branchy tree; the set comparison says the same
   thing for a single-head repo and degrades honestly. `_script_head()` in the
   test still asserts there is exactly one.
2. **The readback is scoped to head-destined upgrades, not run
   unconditionally.** The brief says "after `run_migrations()` returns". Run
   unconditionally it breaks `alembic current` and `alembic downgrade`, both
   of which execute this `env.py` — observed, not predicted. §12 has the
   mechanism. Consequence to be aware of: `alembic upgrade <rev>` aimed at a
   revision that is *not* head is not verified.
3. **One new lint warning left in place.** `ruff` reports `SIM117` ("use a
   single `with`") on the nested `connect()` / `begin()` pair. Combining them
   would put the twenty-line comment explaining why the transaction is
   explicit above a compound statement and make the two-step structure harder
   to read. `alembic/` is outside the project's lint scope
   (`Makefile:54-57` runs `ruff` over `app/ tests/`), and `ruff check app/
   tests/`, `ruff format --check app/ tests/` and `mypy app/` are all clean.
   The pre-existing `I001` on `env.py`'s import block is unchanged and was
   there at `HEAD`.

## 15. UNVERIFIED

- **That the fix works on production.** It is committed and not deployed.
  Everything in §11–§13 is measured against a local PostGIS 16 container and
  against `alembic 1.18.4` / `SQLAlchemy 2.0.50`; production runs the same
  alembic and `SQLAlchemy 2.0.49`. The mechanism does not depend on the patch
  version, but the claim is inference until a real boot logs its head check.
- **That the concurrency test would catch a lock regression.** It confirms the
  lock works; it does not prove it *fails* without one. Removing the lock
  entirely may well leave the test green — whether two boots collide on
  duplicate DDL depends on timing the test does not control, and no reversion
  was run for that half. What the test does close is the reverse direction:
  the lock as written cannot silently discard the migration any more.
- **Whether any other local or CI database is stranded at `0010`.** The one
  used here was, and is now at `0011`. No others were checked.
- **The `WITH (FORCE)` drop.** Requires PostgreSQL 13+. Both the local
  container and the CI service are 16; a maintenance URL pointing at anything
  older would fail on teardown rather than on the assertion.

---

# Addendum, 2026-08-26 — `edc13db` deployed; X2 closed

Observe-only deploy watch. Nothing in this session issued a write; every claim
below is read from `fly logs`, `fly status`, `fly image show`, and `SELECT`
through the app's own `app.db.engine` on a fresh connection. §1–§14 above are
unedited.

**Target:** `3a86dd69211c460cee22245d30605941fdd55168` (`git rev-parse HEAD`
at the start of this watch — the docs-only commit on top of `edc13db`).

## Deploy sequence — two boots, not one

`fly image show` at the start of this watch still showed both apps on
`ce307e35…` — the pre-fix deploy §1–§10 above describe, itself captured
mid-flight. Two full API boot cycles landed before the target SHA was
reached:

**Boot A, `ce307e35…`, ~00:52Z (pre-fix code, captured live by this
session's log tail, not by GATE-STOP.md's earlier read):**

```
00:52:27Z app[825d69b7e46618] INFO [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:28Z app[825d69b7e46618] Migrations complete.
00:52:45Z app[48e0de9a713918] INFO [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:45Z app[48e0de9a713918] Migrations complete.
```

Both machines report the upgrade; no head check exists yet to catch the
rollback. This is X1 happening, live, not inferred — the same shape §2
describes, one deploy earlier than the SHA the row was written against.
Consistent with §1's finding: production was still at `0010` when this
watch began.

**Boot B, target SHA `3a86dd6…`, 01:29Z (fixed code):**

```
01:29:35Z  runner[48e0de9a713918] Pulling container image …c839dc99…
01:29:40Z  app[48e0de9a713918] INFO [alembic.runtime.migration] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
01:29:41Z  app[48e0de9a713918] INFO [alembic.env] Migration head check: database=['0011'] scripts=['0011']
01:29:41Z  app[48e0de9a713918] Migrations complete.
01:29:44Z  app[48e0de9a713918] INFO:     Application startup complete.

01:29:51Z  runner[825d69b7e46618] (pulls the same image, boots after 48e0 already committed)
01:29:56Z  app[825d69b7e46618] INFO [alembic.runtime.migration] Context impl PostgresqlImpl.
01:29:56Z  app[825d69b7e46618] INFO [alembic.runtime.migration] Will assume transactional DDL.
01:29:56Z  app[825d69b7e46618] INFO [alembic.env] Migration head check: database=['0011'] scripts=['0011']
01:29:56Z  app[825d69b7e46618] Migrations complete.
01:29:59Z  app[825d69b7e46618] INFO:     Application startup complete.
```

`48e0de9a713918` performed the real, committed upgrade — `Running upgrade
0010 -> 0011` followed immediately by a head check that reads back `0011` on
a fresh connection. `825d69b7e46618` booted second, took the
`pg_advisory_xact_lock`, found the database already at head, and logged only
the head check — **no `Running upgrade` line**. This is the first production
observation of M10's serialization actually working: one booter mutates, the
other waits on the lock and finds nothing to do, and this time the state it
finds is real because the lock's release and the commit are the same event.
Full log capture: `docs/audits/2026-08-m4-ledger/` session (not committed —
raw `fly logs` buffer, referenced here by timestamp instead).

## Boot outcome

`fly status -a log0s-plotline-api`: both machines `started`, `LAST UPDATED`
`01:29:35Z` / `01:29:51Z`, one boot cycle each — no crash loop, no restart.
`GET /api/v1/health`:

```
{"status":"ok","db":"connected","redis":"connected",
 "version":{"sha":"3a86dd69211c460cee22245d30605941fdd55168","built":"2026-08-26T01:29:08Z"}}
```

## Schema, fresh connection, `app.db.engine`

```
$ alembic current
0011 (head)

CONSTRAINTS on timeline_task_years:
  ck_tty_outcome    CHECK (outcome = ANY (ARRAY['ok','failed','absent','indeterminate','suppressed']))
  fk_tty_task_id    FOREIGN KEY (task_id) REFERENCES timeline_request_tasks(id) ON DELETE CASCADE
  timeline_task_years_pkey  PRIMARY KEY (id)
  uq_tty_task_group UNIQUE (task_id, group_key)

INDEXES:
  timeline_task_years_pkey       btree (id)
  uq_tty_task_group              btree (task_id, group_key)
  idx_tty_source_group_outcome   btree (source, group_key, outcome)
  idx_tty_task                   btree (task_id)

COUNT: 0
```

Matches migration `0011` as written. Table is empty, as predicted — nothing
has recorded a year yet.

## X2 casualty window

```
NOW: 2026-08-26 01:36:06 UTC
timeline_requests WHERE created_at >= '2026-08-26T00:52:00Z': 0 rows
Most recent request overall: e6657b66…, complete, 2026-08-25 22:20:00.603722+00
```

Zero requests were created between the `ce307e35` deploy (`00:52Z`, the
boundary GATE-STOP.md §1.3 already established) and this check (`01:36Z`),
which spans both the broken boot and the fixed one. Nothing hit the missing
table. No casualties to record.

## Worker

`fly logs -a plotline-worker`, boot at `01:29:41Z`–`01:29:52Z`: no `alembic`
activity (`entrypoint.sh` skips migrations for `celery` — confirmed by
observing the boot, not only by reading the script, closing GATE-STOP.md
§9's second UNVERIFIED item), no `UndefinedTable`, no `does not exist`.
`Janitor found no stranded work` → `celery@e2862966b306d8 ready.`
`fly image show -a plotline-worker`: both machines `GH_SHA=3a86dd6…`.

## Verdict

**X2 closed.** `0011` is applied, `timeline_task_years` exists with the
constraints and indexes migration `0011` defines, and no request reached the
recorder while the table was missing — the window that mattered (`00:52Z`
deploy through this check) had zero arrivals. `edc13db` is deployed, not
merely committed. The M4 sweep (`../2026-08-m4-ledger/PREDICTION.md`) is now
runnable; running it is out of scope for this observe-only session.
