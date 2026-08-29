# NORM-27 — exit path fix

Scope: `scripts/enrich_snapshot_scenes.py`'s exit path only, per the prompt's
constraints. No production access; no pacing, retry, batch, resume, or
NORM-22 changes.

## What was wrong

`STATUS.md` NORM-27 and the session capture at `261f6af`: the production dry
run on 2026-08-29 matched and wrote all 5,387 rows, 0 errors, report
rendered, structlog summary emitted — then `main()`'s
`with SessionLocal() as db:` (`scripts/enrich_snapshot_scenes.py:614`, before
this fix) raised `psycopg2.OperationalError: SSL connection has been closed
unexpectedly` out of `Session.__exit__`, because the single session held for
the whole run sat idle and uncommitted for 18 minutes (dry run commits
nothing) and Neon reaped it. `sys.exit(1 if out.errors else 0)` at the old
`:622` never ran; the process exited 1 from the unhandled traceback instead.
`errors=0` and `.rc` said `1`.

## The fix

`fb72aaa`: `main()` wraps the `with SessionLocal() as db: out = run(...)`
block in `try/except OperationalError`. `out` is only assigned once `run()`
returns, so:

- an `OperationalError` raised **during** `run()` leaves `out` unset and is
  re-raised unchanged — a failed run still exits nonzero, unhandled, exactly
  as before this fix;
- an `OperationalError` raised at teardown **after** `run()` returned is
  caught, logged once as a distinct `structlog`/`logging` event
  (`teardown_operational_error_after_completed_run`), and does not change the
  exit code, which is still `1 if out.errors else 0`.

No restructuring to session-per-batch: batching already commits every
~200 rows and the resume mechanism is queue re-derivation, not the exit
code, so a teardown-only catch closes the gap without touching the tested
kill/resume semantics (`test_a_killed_run_does_not_refetch_committed_rows`,
`test_each_batch_commits`).

## Tests — delete-the-fix standard

`backend/tests/test_enrich_snapshot_scenes.py`, four new cases exercising
`main()` with `SessionLocal` and `run` mocked (no DB, no network):

- `test_teardown_operational_error_after_success_exits_zero` — outcome
  `errors=0`, teardown raises `OperationalError` → exit `0`, log event
  present. **Fails without the fix** (verified: reverting
  `scripts/enrich_snapshot_scenes.py` to its pre-`fb72aaa` state and
  re-running this test raises `OperationalError` uncaught instead of exiting
  0).
- `test_failure_during_the_run_still_exits_nonzero` — `run()` itself raises
  `OperationalError` → it propagates, unhandled (a failure during the run is
  not a teardown failure and must not be swallowed).
- `test_run_errors_exit_nonzero_regardless_of_teardown` — outcome
  `errors=3`, no teardown error → exit `1`.
- `test_run_errors_and_teardown_error_both_exit_nonzero` — outcome
  `errors=1` **and** teardown raises → exit `1`. **Fails without the fix**
  (same revert-and-rerun check): the unhandled teardown exception replaces
  the run's own nonzero signal with a bare traceback instead of the exit
  code being derived from `out.errors`.

`docker compose exec -T api python -m pytest tests/test_enrich_snapshot_scenes.py -q`:
25 passed (21 pre-existing + 4 new).

`make lint` (ruff check, ruff format --check, mypy): clean, including
`mypy scripts/enrich_snapshot_scenes.py` run directly (`make lint` only
covers `app/`).

## Local verification

Local queue is 0 (the snapshot-enrichment heal already ran here per
`SNAPSHOT-ENRICH-LOCAL-REPORT.md`), so this is the exit path executing
end to end with zero fetches, not a re-proof of the matching logic:

```
docker compose exec -T api sh -lc \
  "cd /app && python scripts/enrich_snapshot_scenes.py --report /tmp/norm27-verify.md; \
   echo \$? > /tmp/norm27-verify.rc"
```

Report: queue 0, 143 topo excluded, 0 fetched, 0 errors, dry run, nothing
written. `.rc`: `0`.

## Deploy state

Fixed and tested locally, `fb72aaa`, on `main`, not pushed this session
(commit-only, per prompt). Not deployed. Production is unchanged: the
authorized `--execute` on the 5,387-row queue is still unspent, and NORM-27
in `STATUS.md` stays open until a push, a CI deploy, and NORM-26's
image-inspection gate (not the label) confirm `fb72aaa` is what
`plotline-worker` is running.

## Pattern for the collection

A completion signal must be derived from the work's own outcome, not from
whether the process's last breath was clean — teardown is not the run.
