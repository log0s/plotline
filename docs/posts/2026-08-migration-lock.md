---
status: draft
candidate_titles:
  - "The lock that rolled back every migration"
  - "Exit 0, nothing committed"
  - "A gate written for the opposite failure"
pull_quote: "A migration runner that can exit 0 after rolling back its own work is not a bug report. It is a silence."
facts_to_verify:
  - "The 01:29Z pair. What the logs show is the outcome: 48e0de9a713918 ran the real upgrade and logged a head check reading back 0011; 825d69b7e46618 pulled its image at 01:29:51Z, ten seconds after the first machine's head check at 01:29:41Z, and logged the head check with no Running upgrade line. No log line in either boot shows a lock wait, so the serialized outcome is observed and the serialization is not. STATUS.md's X1 and M10 rows now say the same (corrected c2cd239), so this is no longer a disagreement with the record — it is the limit of what the record can show. The forced-contention test, test_concurrent_boots_from_0010_converge_on_head, is where the property is actually tested. The post claims the outcome only."
  - "That this was the first boot pair in the project's history to run against committed state. X1 and M10 both assert it. It follows from the mechanism — every boot between dd99cee and edc13db either found itself at head or had its version bump rolled back — rather than from an enumeration of past deploys, and the post does not make the claim."
  - "That no production timeline request was lost. Rests on zero timeline_requests rows created between the 00:52Z deploy and the 01:36Z check, plus 0 queued and 0 processing. GATE-STOP.md §9 states it as a bound on *created* requests: nothing arrived, not that nothing could have. The post says it that way and does not upgrade the bound."
  - "SQLAlchemy version on production. GATE-STOP.md §3 says 2.0.49 and §15 says the local reproduction ran 2.0.50; nothing reconciles them. The post names neither; if a version is added, use §15."
---

# The lock that rolled back every migration

On 2026-08-26, a few minutes before 01:00Z, a session had authorization to run
a 184-parcel sweep against Plotline's production database. (Times here are UTC;
commits are stamped UTC−6, so several read 25 August.) The sweep prompt,
`SWEEP-PROMPT-1.md`, put six gate lines in front of the run, any one of which
stopped everything. Line two: "`alembic_version` on prod reads `0011`.
`timeline_task_years` exists … and holds zero rows. Otherwise stop — a
non-empty ledger before the sweep means something already ran."

The version was `0010`. The table did not exist. Seven minutes earlier — the
gate's capture clock reads 00:59:39Z, the deploy's migration lines 00:52:22Z to
00:52:45Z — the logs for that deploy, `ce307e35`, said otherwise, once per API
machine:

```
00:52:27Z app[825d69b7e46618] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:28Z app[825d69b7e46618] Migrations complete.
00:52:45Z app[48e0de9a713918] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:45Z app[48e0de9a713918] Migrations complete.
```

Both machines reported applying the migration, both exited 0, and the
containers served a schema that had not moved.

## What the lock was for

Twenty-two days earlier, an audit finding called M10 noted that `entrypoint.sh`
runs `alembic upgrade head` on every API boot: two machines booting together
would both apply the same migration, one crash-looping on duplicate DDL. The
fix, `dd99cee`, was a session-scoped `pg_advisory_lock` in `alembic/env.py`:
take the lock, migrate, release it in a `finally`. Its commit message says why
it is not a Fly release command: the worker is a separate app on a parallel CI
job, so an API-only release command would not close the window it appears to.

That reasoning was fine. What I got wrong was one layer up. M10's second half —
a worker briefly running ahead of the schema — I accepted rather than fixed:
migrations to date are additive, the window is seconds, and closing it would
mean serializing two deploy jobs to prevent a failure that has not occurred.

That is defensible about the window. What it also did was set the posture for
the whole finding: a race nobody has hit, a cheap mitigation, ship it. A
mitigation for a failure that has not occurred does not get exercised, and what
is not exercised does not get tested. For twenty-two days M10's mitigation was
strictly worse than none, and my status ledger said "partially resolved."

## The mechanism

Fourteen lines in `env.py` as it stood at `ce307e35`: open a connection,
execute `SELECT pg_advisory_lock(:key)`, configure alembic's migration context
on it, run the migrations inside `context.begin_transaction()`, unlock in a
`finally`, close.

That lock statement is the connection's first, and SQLAlchemy 2.0 autobegins a
transaction on it, so by the time `context.configure()` runs
`connection.in_transaction()` is `True` and alembic stores that as
`MigrationContext._in_external_transaction`. Then `context.begin_transaction()`
— the line that looks like it opens the migration's transaction — checks the
flag and returns a `nullcontext()`. That is correct and documented: it exists
for a caller who opened a transaction and will commit it. Alembic concludes
someone else owns the commit and declines to issue one.

There was no such caller: `env.py` had opened a transaction by accident, as a
side effect of taking a lock, and believed alembic would commit. The DDL and
the `UPDATE alembic_version` ran — the `Running upgrade` line is not the
evidence for that, since alembic prints it before executing the step. The
evidence is the local reproduction, in both directions: a real `alembic upgrade
head` against a database at `0010` printed the production transcript and left
`alembic current` at `0010`, and a harness using alembic's own
`MigrationContext` persisted its DDL with the lock statement removed and
discarded it with the statement present (GATE-STOP.md §4.1, §4.2). Then
`Connection.close()` rolled all of it back and the process exited 0.

The second machine's boot is the tell, though not the way I first read it. Its
`Running upgrade` line lands eighteen seconds after the first machine's, but it
began migrating at 00:52:40Z — twelve seconds after the first logged
`Migrations complete.` at 00:52:28Z. The two boots never overlapped, so the
lock was never contended. What the second shows is not a lock failing to
serialize but a version bump that had been rolled back: it read `0010` and ran
the whole upgrade again.

The timing is the other half. `dd99cee` landed on 4 August; migration `0010`
was committed in June and applied long before the lock existed, and no new
migration was written until 25 August, so every deploy in between found itself
at head and printed `Migrations complete.` with no upgrade line above it.
`0011` — the per-year outcome ledger — is the first migration in the project's
history to run under the advisory-lock code, and it was discarded on its first
attempt. Three weeks in production with nothing to break.

What it would have broken matters, because "nothing was lost" is a claim about
arrivals, not safety. `ce307e35` deployed the ledger's recorder against a
database with no ledger table, and the recorder sits on the mandatory path:
`_run_timeline` moves a request to `processing` and calls
`create_request_tasks`, which runs `clear_task_year_outcomes` for every source
on every request, not only on a Celery redelivery. That issues a `DELETE FROM
timeline_task_years` against a table that does not exist, and nothing catches
the `UndefinedTable` — deliberately, since a ledger row is meant to commit
atomically with its snapshot — so the task boundary marks the request `failed`
and re-raises: every timeline request reaching the worker would have failed at
its first write. None did: zero `timeline_requests` rows were created after the
deploy, and none were `queued` or `processing`. GATE-STOP.md §9 bounds that to
*created* requests, so the honest claim is that nothing arrived, not that
nothing could have. The sweep would have arrived 184 times.

## Why nothing caught it, and what did

The backend test suite builds its schema as hand-written DDL against an
in-memory SQLite engine. The migration directory is never executed — not in the
suite, not in CI, whose deploy workflow had no alembic step at all. All 522
tests passed on the commit that shipped `0011`, because their tables come from
a fixture rather than from the migration. A suite that never runs alembic
cannot fail on Postgres transaction semantics. The test was not missing; the
suite structurally could not host it.

So the pipeline was green, the deploy logs said success, and the database was
wrong. This is the failure mode my development notes call "instrument the
silences": a reflex to convert an upstream failure into a smaller success —
usually a county API outage recorded as "complete, 0 records," here a rollback
recorded as `Migrations complete.`

What caught it was a gate line, and the kind of luck matters.
`SWEEP-PROMPT-1.md`'s Phase 1 line 2 says why it is there: "a non-empty ledger
before the sweep means something already ran." That is the half I cared about.
It caught the opposite failure — nothing ever ran — because a table that does
not exist also fails a check that it is empty.

That is luck, but not random luck: every heal and sweep prompt here carries
written stop conditions, a discipline that came out of earlier runs proceeding
on unchecked assumptions. The line that fired was aimed elsewhere; the habit of
writing lines like it was not. It is still not a test, and I would rather have
had the test.

The fix, `edc13db`, is two changes closing different holes. The lock statement,
`context.configure()` and `run_migrations()` now happen inside one explicit
`connection.begin()` that `env.py` owns and commits — alembic still sees an
external transaction and hands back a `nullcontext`, but now that transaction
exists. And `pg_advisory_lock` becomes `pg_advisory_xact_lock` on the same key,
released by the commit rather than before it; a session-scoped lock released
while the version bump was still uncommitted would reopen the race M10 added it
for.

Then the part that would have caught the original: after a head-destined
upgrade, `env.py` reads the version back on a fresh connection — the engine
uses `NullPool`, so `connect()` opens a new session seeing committed state, not
the runner's own uncommitted view — compares it to the scripts' head and raises
on a mismatch. A boot that logs `Migrations complete.` against the wrong head
can no longer exit 0.

It shipped with a real-Postgres CI service (PostGIS, because migration `0001`
creates the extension), a `TEST_POSTGRES_URL` that fails rather than skips in
CI, and three tests — 525 passing, up from 522. One,
`test_concurrent_boots_from_0010_converge_on_head`, is M10's actual property,
untested until now: two real `alembic upgrade head` subprocesses from `0010`,
with the test holding the lock itself and polling `pg_locks` until both are
provably blocked before releasing, so the contention is forced rather than
hoped for.

The deploy watch: at 01:29:40Z one API machine ran the real upgrade and a
second later logged the head check reading back `0011`. The other pulled the
same image at 01:29:51Z, took the transaction-scoped lock, found the database
at head, and logged the head check with no `Running upgrade` line. That is the
outcome M10 wanted, twenty-two days after the lock was written and on the day
it was fixed — though the logs support only that: the second boot found
committed state and did nothing; no line proves it ever waited on the lock.
Zero timeline requests were created between the 00:52Z deploy and the 01:36Z
check, which spans the whole interval in which the recorder ran without its
table.

All of this was agent-written from my prompts — the lock, the migration it
discarded, the gate that caught it, the fix, the tests. The same tooling
produced the defect and the instrument that found it; what differed was not the
model but what I asked for. The lock came out of "fix M10," a request to make
something work. The gate came out of a sweep prompt whose job was to say what
would make me stop. The test came out of a prompt saying a SQLite suite
structurally cannot fail on this, so the fix does not count until it runs
against a real server. My development notes reached this from another
direction: the review stance matters more than the model version, and nobody
adopts one unless someone schedules it.

The rule I would take from this is narrower than "test your migrations." A
migration runner that can exit 0 after rolling back its own work is not a bug
report. It is a silence. And the fix for a silence is never a better log line —
the broken version was already logging success. It is an instrument that reads
back what it just wrote, on a connection that cannot see its own uncommitted
work, and refuses to exit 0 when the two disagree.

Sources. The investigation record is
`docs/audits/2026-08-m4-ledger/GATE-STOP.md` and its addenda; the gate line is
`docs/audits/2026-08-m4-ledger/SWEEP-PROMPT-1.md`, Phase 1, line 2. The lock is
commit `dd99cee` and the fix is commit `edc13db`.
