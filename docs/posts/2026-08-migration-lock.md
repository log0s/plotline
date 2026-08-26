---
status: draft
candidate_titles:
  - "The lock that rolled back every migration"
  - "Exit 0, nothing committed"
  - "A gate written for the opposite failure"
pull_quote: "A migration runner that can exit 0 after rolling back its own work is not a bug report. It is a silence."
facts_to_verify:
  - "Test count. GATE-STOP.md §6 and the X3 row both describe 'the 488-test suite that ships with 0011'; edc13db's message and GATE-STOP.md §13 say 3 added, 525 passing, from 522. Both numbers are in the record and they cannot both describe the same suite. The post uses 525 and does not mention 488 — confirm which is the suite total at edc13db before publishing."
  - "env.py line ranges. GATE-STOP.md §12 cites the transaction block at :141-191 and _verify_at_head at :56-95; the X1 row cites :141-194 and :52-86; the commit message says :141-194 and :36-86. The post cites no line numbers for the fix. If any are added, read them off the file at edc13db."
  - "SQLAlchemy version on production. GATE-STOP.md §3 says 2.0.49; §15 says the local repro ran 2.0.50 and production 2.0.49. The post says 2.0.49 for production and does not name the local version."
  - "'23 days' between dd99cee (2026-08-03) and the discovery (2026-08-26). Arithmetic mine, from the two dates; the STATUS.md M10 re-mark also uses 23 days, so this is consistent but both may share one source."
  - "The claim that the gate line was written to catch 'something already ran' rather than 'nothing ran'. This is my reading of the brief's intent, quoted from the gate table in GATE-STOP.md §1. The brief itself is not in the repo — if it should be quoted directly, it needs to be found."
  - "That no production timeline request was lost. Rests on zero timeline_requests rows created between 00:52Z and 01:36Z, plus 0 queued / 0 processing. GATE-STOP.md §9 bounds this to *created* requests and notes the log buffer is not proof."
  - "That the 01:29Z boot pair is the first time the advisory lock has ever serialized two boots on real state. Follows from dd99cee being the only commit to touch the lock and 0011 being the first migration under it; not independently observed for the 2026-08-03 to 2026-08-25 window, where no migration ran at all."
---

# The lock that rolled back every migration

On the night of 26 August a session had authorisation to run a 184-parcel
sweep against Plotline's production database. The brief it was working from
had six gate lines in front of the run, and the rule was that any one of them
failing stopped everything. Line two: `alembic_version` should read `0011`,
and the table `timeline_task_years` should exist and hold zero rows.

The version was `0010`. The table did not exist. Seven minutes earlier, the
deploy logs had said otherwise — twice, once per API machine:

```
00:52:27Z app[825d69b7e46618] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:28Z app[825d69b7e46618] Migrations complete.
00:52:45Z app[48e0de9a713918] Running upgrade 0010 -> 0011, Per-year outcome ledger for timeline fetches.
00:52:45Z app[48e0de9a713918] Migrations complete.
```

Two machines each reported applying the same migration, `alembic upgrade head`
exited 0 both times, `set -e` was satisfied, and the containers went on to
serve traffic against a schema that had not moved. The sweep did not run. The
reason it could not run turned out to be worse than the sweep being delayed.

## What the lock was for

Three weeks earlier, an audit finding called M10 said that `entrypoint.sh`
runs `alembic upgrade head` on every API boot, so two machines booting
together would both try to apply the same migration and one of them would
crash-loop on duplicate DDL. The fix, in `dd99cee` on 3 August, was a
session-scoped `pg_advisory_lock` in `alembic/env.py`: take the lock, run the
migrations, release it in a `finally`. Not a Fly release command, because the
worker is a separate app deployed by a parallel CI job, so a release command
on the API alone would not close the window it appears to close.

That reasoning was fine. The part I got wrong was one layer up. M10 also had a
second half — a worker briefly running ahead of the schema — which I accepted
rather than fixed, on the grounds that migrations to date are additive, the
window is seconds, and closing it would mean serializing two deploy jobs to
prevent a failure that has not occurred.

I still think that sentence is defensible about the window. What it also did,
without my noticing, was set the posture for the whole finding: this is a
race nobody has hit, the mitigation is cheap, ship it and move on. A
mitigation for a failure that has not occurred does not get exercised, and if
it does not get exercised it does not get tested. For 23 days the mitigation
for M10 was strictly worse than no mitigation at all, and the row in my status
ledger said "partially resolved."

## The mechanism

The code was six lines. It opened a connection, executed
`SELECT pg_advisory_lock(:key)`, configured alembic's migration context on
that same connection, ran the migrations inside `context.begin_transaction()`,
unlocked in a `finally`, and let the `with` block close the connection.

Under SQLAlchemy 2.0, the lock statement is the connection's first statement,
and 2.0 autobegins a transaction on it. By the time `context.configure()` is
called, `connection.in_transaction()` is already `True`. Alembic reads that at
configure time and stores it: `MigrationContext._in_external_transaction`.
Then `context.begin_transaction()` — the line that looks like it opens the
migration's transaction — checks that flag and returns a `nullcontext()`.

That behaviour is correct, and it is documented. It exists so that a caller
who has deliberately opened a transaction can run migrations inside it and
commit on their own terms. Alembic sees an external transaction, concludes
that someone else owns the commit, and declines to issue one.

There was no such caller. `env.py` had opened a transaction by accident, as a
side effect of taking a lock, and believed alembic would commit. So the DDL
ran, the `UPDATE alembic_version` ran, the log line `Running upgrade 0010 ->
0011` was printed because the upgrade genuinely executed, the unlock joined
the same transaction, and then `Connection.close()` rolled all of it back. The
process exited 0.

Two details make it a story rather than a footnote. The first is that the
second machine's boot is the tell. Eighteen seconds after the first machine
"succeeded," the second machine read the database, found `0010`, and ran the
whole upgrade again — which is precisely the collision the advisory lock
exists to prevent. The lock was working exactly as designed and serializing
two boots against state that was thrown away before either could see it.

The second is the timing. `dd99cee` landed on 3 August. Migration `0010` was
committed in June and applied long before the lock existed. Between 3 August
and 25 August no new migration was written, so every deploy in that window
found itself already at head, ran no upgrade, and printed `Migrations
complete.` with nothing above it. `0011` — the per-year outcome ledger, on 25
August — is the first migration in the project's history to execute under the
advisory-lock code, and it was silently discarded on its first attempt. The
defect had been in production for three weeks with nothing to break.

## Why nothing caught it, and what did

The backend test suite builds its schema as hand-written DDL against an
in-memory SQLite engine. The migration directory is never executed — not in
the suite, not in CI, where the deploy workflow had no alembic step at all.
Every test passed on the commit that shipped `0011`, because the tables those
tests use are created by a fixture, not by the migration. A suite that never
runs alembic and never touches Postgres cannot fail on Postgres transaction
semantics. It is not that the test was missing; the suite structurally could
not host it.

So the pipeline was green, the deploy logs said success, and the database was
wrong. This is the failure mode I have written about elsewhere in this
project's development notes under the heading "instrument the silences": a
consistent reflex, in this codebase and in the tooling that wrote it, to
convert an upstream failure into a smaller success. Usually that looks like a
county API outage recorded as "complete, 0 records." Here it looked like a
rollback recorded as `Migrations complete.`

What caught it was a gate line, and I want to be precise about the kind of
luck that was. The line asserted that `timeline_task_years` exists and holds
zero rows. The "zero rows" half is the one I cared about when I wrote it: I
was guarding against starting a sweep on top of state some earlier run had
already produced. It caught the opposite failure — not "something already
ran," but "nothing ever ran" — because a table that does not exist also fails
a check that it is empty.

That is luck, but it is not random luck. The gate exists because every heal
and sweep prompt in this project carries written stop conditions, and that
discipline exists because of earlier incidents where a run proceeded on
assumptions nobody had checked. The specific line that fired was aimed
somewhere else. The habit of writing lines like it was not. It is still not a
test, and I would rather have had the test.

The fix, `edc13db`, is two changes that close different holes. The lock
statement, `context.configure()` and `run_migrations()` now happen inside one
explicit `connection.begin()` that `env.py` owns and commits — alembic still
sees an external transaction and still hands back a `nullcontext`, but now
that external transaction actually exists. And `pg_advisory_lock` becomes
`pg_advisory_xact_lock` on the same key, so the lock is released by the commit
rather than before it; a session-scoped lock released while the version bump
was still uncommitted would reopen exactly the race M10 added it for.

Then the part that would have caught the original: after a head-destined
upgrade, `env.py` reads the version back on a fresh connection — the engine
uses `NullPool`, so it is a new session that sees committed state and not the
runner's own uncommitted view — compares it to the scripts' head, logs both,
and raises on a mismatch. A boot that logs `Migrations complete.` against the
wrong head can no longer exit 0.

It shipped with a real-Postgres CI service (PostGIS, because migration `0001`
creates the extension), a `TEST_POSTGRES_URL` that fails rather than skips
when CI is set, and three tests — 525 passing, up from 522. Each migrates a
throwaway database and drops it. One of them,
`test_concurrent_boots_from_0010_converge_on_head`, is M10's actual property,
tested for the first time since M10 was filed: two real `alembic upgrade head`
subprocesses from `0010`, with the test holding the migration lock itself and
polling `pg_locks` until both are provably blocked on it before releasing, so
the contention is forced rather than hoped for.

The deploy watch is the ending I would not have scripted. At 01:29Z one API
machine ran the real upgrade and logged the head check reading back `0011`.
The other booted fifteen seconds later, waited on `pg_advisory_xact_lock`,
found the database already at head, and logged the head check with no upgrade
line above it. That is the first time the lock has ever done its job on state
that survived — on the day it was fixed, three weeks after it was written.
Zero timeline requests were created in the entire window the bug was live, so
nothing was lost.

All of this was written by an agent from my prompts: the lock, the migration
it discarded, the gate that caught it, the fix, and the tests. The same
tooling produced the defect and the instrument that found it. What differed
between them was not the model — it was what I asked for. The lock came out of
"fix M10," which is a request to make a feature work. The gate came out of a
brief whose job was to say what would make me stop. The test came out of a
prompt that said a SQLite suite structurally cannot fail on this, so the fix
does not count until it runs against a real server. That is the same thing
this project's development notes concluded from a different direction: the
review stance matters more than the model version, and nobody adopts a review
stance unless someone schedules it.

The rule I would take from this is narrower than "test your migrations." A
migration runner that can exit 0 after rolling back its own work is not a bug
report. It is a silence. And the fix for a silence is never a better log line,
because the broken version was already logging success — it is an instrument
that reads back what it just wrote, on a connection that cannot see its own
uncommitted work, and refuses to exit 0 when the two disagree.
