# The NORM-27 exit-code fix, corrected — NORM-29's fix

Local-only session. No production access. Fixes the exception class the
NORM-27 guard catches and the test premise that let an inert fix score
green; nothing else moved.

## 1. The fix

`scripts/enrich_snapshot_scenes.py:115` was `from psycopg2 import
OperationalError`. SQLAlchemy does not raise that class from
`Session.__exit__` — it catches the DBAPI error and re-raises its own
wrapper, `sqlalchemy.exc.OperationalError`, carrying the psycopg2 error as
`__cause__`. The two classes are disjoint in both directions
(`SNAPSHOT-ENRICH-PROD-REPORT-2.md` §6 verified this against the live
container). The guard at what was line 625 could therefore never match.

Changed the import to `from sqlalchemy.exc import OperationalError`. The
`except OperationalError:` clause at the teardown seam is otherwise
unchanged; a comment there now names the wrapping behavior and cites
NORM-29.

**Grep for other psycopg2 exception references in the script** (NORM-24's
sibling rule — grep for the shape elsewhere before closing a bug):

```
$ grep -n "psycopg2" scripts/enrich_snapshot_scenes.py
```

returned nothing after the fix — line 115 was the only reference. A
repo-wide grep for `psycopg2` found three other files (`backend/app/config.py`,
`backend/alembic/env.py`, `scripts/backfill_census_housing.py`); all three
hits are comments about connection-string/URL coercion, not exception
imports, and none is in this script's call path.

## 2. The test premise, corrected at the layer boundary

`backend/tests/test_enrich_snapshot_scenes.py:57` imported the same wrong
class and constructed teardown errors as bare `OperationalError("message")`
— which the guard's `except psycopg2.OperationalError` matched, so the
tests confirmed the wrong premise rather than testing against it.

Corrected two ways:

* **The existing NORM-27 test group** now builds the teardown error the way
  SQLAlchemy actually builds one — its own `OperationalError`, constructed
  with `orig` set to a `psycopg2.OperationalError`, and `__cause__` set to
  that `orig` to mirror what `Session.__exit__` leaves behind. This is
  `_sqlalchemy_operational_error()` in the test file.
* **A new test, `test_wrapped_error_matches_a_real_session_exit_failure`**,
  pins the premise itself rather than asserting it. It does not hand-build
  the exception at all: it opens a real SQLAlchemy `Session` against a
  SQLite connection whose driver-level `rollback()` is overridden to raise
  `sqlite3.OperationalError`, then lets a real `with session: pass` trigger
  a real `Session.__exit__` teardown failure. SQLAlchemy's own error
  translation — not the test — converts that into `sqlalchemy.exc
  .OperationalError` with the driver error attached as `__cause__`, which is
  the same wrapper class the guard imports. The test asserts that class
  match and that the result is *not* a `psycopg2.OperationalError`.

  A live Postgres/psycopg2 connection severed mid-teardown (what production
  actually did) was not available locally; the SQLite reproduction exercises
  the same SQLAlchemy translation layer that would run against psycopg2 —
  the layer is driver-agnostic — so this is the strongest local
  approximation rather than the floor-level isinstance check the prompt
  named as a fallback. The test's docstring records this limitation.

## 3. Delete-the-fix, run honestly

Reverted the import to `from psycopg2 import OperationalError` (the
pre-fix state) with the corrected tests left in place, and ran the suite:

```
$ docker compose exec -T api python -m pytest tests/test_enrich_snapshot_scenes.py -q
...
FAILED tests/test_enrich_snapshot_scenes.py::test_teardown_operational_error_after_success_exits_zero
FAILED tests/test_enrich_snapshot_scenes.py::test_run_errors_and_teardown_error_both_exit_nonzero
FAILED tests/test_enrich_snapshot_scenes.py::test_wrapped_error_matches_a_real_session_exit_failure
3 failed, 23 passed, 1 warning in 0.62s
```

All three failures are `sqlalchemy.exc.OperationalError` escaping
uncaught through `with session:` / `main()`'s `try` — the exact production
shape. This is the scored mutation: the corrected tests go red specifically
because the guard's class no longer matches what SQLAlchemy raises, which
is proof the premise now travels with the fix (NORM-29's rule, restated
below). The import was restored to `sqlalchemy.exc.OperationalError`
immediately after this check; no other change was made to score it.

## 4. Local verification

```
$ docker compose exec -T api python -m pytest tests/test_enrich_snapshot_scenes.py -q
26 passed, 1 warning in 0.49s

$ docker compose exec -T api sh -c "cd /app && ruff check tests/test_enrich_snapshot_scenes.py scripts/enrich_snapshot_scenes.py && ruff format --check tests/test_enrich_snapshot_scenes.py scripts/enrich_snapshot_scenes.py && mypy scripts/enrich_snapshot_scenes.py"
All checks passed!
2 files already formatted
Success: no issues found in 1 source file

$ docker compose exec -T api python scripts/enrich_snapshot_scenes.py --report /tmp/enrich_snapshot_local_verify.md
queue (provenance = 'snapshot', footprint IS NULL, source <> 'usgs_topo'): 0 row(s); 143 topo row(s) excluded
...
$ echo $?
0
```

Queue is 0 locally (as before this fix — the local queue was already
drained by the earlier snapshot-enrichment heal), so this run does not by
itself exercise the reaped-connection path; that is exactly the gap NORM-29
names as uncatchable by any local run of this script. What it does confirm
is that the corrected import doesn't change the script's ordinary behavior:
report renders, `.rc` reads `0`, no regression.

## 5. NORM-29's rule, verbatim, for the pattern collection

> An exception handler's test must obtain the exception from the layer that
> raises it, not from an import the handler and the test agree on.

This session's cross-layer test (§2, `test_wrapped_error_matches_a_real_session_exit_failure`)
is the applied form of that rule: it does not import the exception class at
all, it derives it from a forced real teardown failure and asserts the
guard's imported class matches what came out.

## 6. State left behind

* **The fix is corrected and tested locally.** Not deployed — this session
  had no production access and did not push. `git log --oneline -1` at the
  time of writing: `1b59af7`.
* **`--execute` remains unspent.** This session did not touch production
  and made no claim about it beyond what git and local pytest/ruff/mypy
  output show.
* **The reaped-connection failure mode remains unverifiable by any local
  run of this script** (local queue is 0; the failure needs an ~18-minute
  idle session against a real database that reaps it). The cross-layer test
  in §2 is the closest available substitute, not a replacement for a
  production dry run.
* **Before this fix can supersede NORM-27's status**, it needs: push, CI
  deploy, NORM-26's image-inspection gate confirming the new import is what
  is running, and then a production dry run whose `.rc` is read after an
  idle-enough dry run to have a chance of hitting `Session.__exit__`'s
  teardown path at all. That is unchanged from what NORM-27's superseded
  entry already required, restated because it still applies.
