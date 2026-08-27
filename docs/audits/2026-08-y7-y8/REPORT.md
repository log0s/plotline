# Y7 + Y8 — deployed_sha on requests, updated_at on census snapshots

STATUS.md Y7/Y8, decided 2026-08-27. Migration 0013, three commits, none
pushed. Predictions written before any run: `PREDICTION.md`.

## Schema as landed

`backend/alembic/versions/0013_deployed_sha_and_snapshot_updated_at.py`
(`2190e57`), head `0012 → 0013`:

- `timeline_requests.deployed_sha TEXT NULL`. No backfill — pre-migration
  requests ran under an unrecorded SHA and guessing one would let a stale
  outcome look freshly verified. No index: the selection query already joins
  `timeline_task_years → timeline_request_tasks → timeline_requests`
  (`ledger._LATEST_SQL`) to rank latest outcomes; the SHA comparison happens
  in Python alongside the filtering that file already does post-query
  (`ledger.py:127-131`'s existing "filtering happens in Python on purpose"
  convention), so adding the column to that SELECT costs nothing extra to
  scan.
- `census_snapshots.updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`,
  backfilled to `created_at` — the only honest value for a row nothing has
  touched since; `now()` would claim a heal happened that didn't.

Applied to local dev Postgres and verified (`alembic upgrade head`, exit 0):
`timeline_requests.deployed_sha IS NOT NULL` count is 0 (no guessed
backfill, 127 pre-migration rows); `census_snapshots.updated_at <>
created_at` count is 0 immediately after backfill (330 rows). Downgrade path
(`drop_column` both, in reverse order) not executed against dev — read, not
run; no reason to doubt it beyond that.

Model: `backend/app/models/parcels.py` — `TimelineRequest.deployed_sha`
(`Mapped[str | None]`, `Text`, nullable) and `CensusSnapshot.updated_at`
(`Mapped[datetime]`, `DateTime(timezone=True)`, `server_default=func.now()`,
`onupdate=func.now()`). Test DDL mirrored in `backend/tests/conftest.py`
(`timeline_requests.deployed_sha TEXT`, `census_snapshots.updated_at TEXT
DEFAULT (datetime('now'))`).

## Write-path inventory (item 2)

Two production sites create a `TimelineRequest`; every script-level heal
path (`requeue_parcels.py`, and by extension `revalidate_landsat.py` /
`requeue_empty_property.py`, per their shared docstring note) routes through
the first:

| site | file:line | change |
|---|---|---|
| `_create_queued_request` | `backend/app/services/imagery.py:183-215` | `deployed_sha=settings.git_sha`, reusing the `get_settings()` call already made for `ensure_admission` |
| `_timeline_request_id` | `scripts/backfill_census_housing.py:56-73` | `deployed_sha=get_settings().git_sha` |

`get_or_create_timeline_request` (`imagery.py:275+`) only *reuses* existing
rows, never constructs one, so it needs no change. Grepped
`TimelineRequest(` across `backend/app` and `scripts/`, excluding tests —
these two are the only production instantiation sites (confirmed via
`grep -rn "TimelineRequest(" backend/app scripts | grep -v /tests/`).

`census_snapshots` has one write site, `upsert_census_snapshot`
(`backend/app/services/demographics.py:45-136`): `updated_at` added to both
the `INSERT` column list and the `ON CONFLICT (parcel_id, dataset, year) DO
UPDATE SET` clause, bound as `datetime.now(tz=UTC).isoformat()` — matching
the file's existing dialect-portable-string pattern (`raw_data` is
`json.dumps`'d the same way) rather than passing a raw Python `datetime`
object, which stdlib `sqlite3`'s adapter deprecation would warn on.

## Selection query (item 3, Y7)

`services/ledger.py`:

- `_LATEST_SQL` gains `r.deployed_sha AS recorded_sha` in the ranked CTE and
  the outer SELECT (`ledger.py:71-95`).
- `LedgerGroup` gains `recorded_sha: str | None = None`, defaulted and moved
  to the end of the dataclass so every existing keyword-only
  `LedgerGroup(...)` test construction site needed no change
  (`ledger.py:99-115`).
- `same_deployed_sha(group, current_sha)` (`ledger.py:229-239`): `True` only
  when `group.recorded_sha is not None and group.recorded_sha ==
  current_sha`. A `None` recorded SHA is never "same" — the mechanism that
  makes the first post-deploy run still select every pre-existing absent
  group once.
- `is_retryable(..., current_sha=None)`: for `NEEDS_CLOUD_FLAG` and
  `NEEDS_ABSENT_API_FLAG` only, the existing flag check is AND'd with `not
  same_deployed_sha(group, current_sha)`. `RETRY` and `RETRY_ONCE` are
  unchanged — the gate never reaches those branches.
- `retryable_groups(..., current_sha=None)` threads the parameter through.

`current_sha` is supplied by the caller as `settings.git_sha` (the process's
own build SHA — since these scripts run inside the API/worker image via
`docker compose exec` / `fly ssh console`, that is the same value the
sibling `/api/v1/health` reports), not fetched a second time from the health
endpoint the deploy gate already checked — the deploy gate's SHA concerns
imagery selection geometry (a different, orthogonal deploy question);
reusing `settings.git_sha` keeps Y7's gate independent of whether
`--require-sha` or `--skip-deploy-check` was passed.

`scripts/requeue_parcels.py`: `select_from_ledger(..., current_sha=None)`
threads to `retryable_groups`; `main()` passes `get_settings().git_sha`.
`imagery.py:619`'s `maybe_refetch_for_backfill` call to `retryable_groups`
passes neither flag, so the new gate never fires there regardless of
`current_sha`'s default `None` — verified by reading, not by a new test,
since the existing flag-gated tests already cover "no flag → never
selected" independent of the SHA parameter.

`scripts/ledger_gaps.py`: `LedgerRow.same_sha` — `True` only when
`outcome == "absent"` and `same_deployed_sha(group, current_sha)`, where
`current_sha = get_settings().git_sha`. Printed as a `same_sha` table column
and the process's own SHA is printed once at the top of `main()`'s output —
the exclusion Y7 makes is visible in the report an operator reads before
healing, not a silent zero in the heal's own dry-run.

## `--sources` argparse footgun (item 4)

`scripts/requeue_parcels.py`: `--sources` changed from `nargs="+"` (which
could consume a trailing positional parcel id as an invalid source — HEAL-1
§"nargs=+ on --sources greedily swallow the UUID", HEAL-2) to a single
comma-separated string value (`--sources naip,landsat`), parsed and
validated against `SELECTABLE_SOURCES` in `main()` before the deploy gate
runs. `nargs="+"` compatibility was not kept — every existing usage example
in the module passed exactly one source token, so there was no real
multi-value call site to preserve, and keeping both forms would have meant
re-adding the ambiguity the fix removes. `--groups` still uses `nargs="+"`;
out of scope here (the prompt named only `--sources`), and it is not
adjacent to a parcel-id positional in any documented invocation.

## Tests (item 5), with reversions

All run via `docker compose exec -T api python -m pytest`, full suite:
**632 passed, 7 skipped** (pre-existing skips, unrelated to this batch).
`ruff check`, `ruff format --check`, `mypy app/` all clean; `ruff check` on
the three touched scripts individually clean (a pre-existing import-sort
issue in unrelated `scripts/seed_featured.py` is untouched by this batch and
not fixed here — out of scope).

- **Y7 fixture** (`backend/tests/test_ledger_selection.py`):
  `test_absent_group_selects_only_when_recorded_under_a_different_sha` —
  two `absent/api_no_data` `census_decennial` groups, one on a request
  recorded under `"sha-current"`, one under `"sha-old"`; `retryable_groups(
  current_sha="sha-current")` selects only the `"sha-old"` group.
  **Reversion:** deleting the `not same_deployed_sha(...)` clause from
  `is_retryable`'s two flagged branches makes both select — confirmed by
  `test_absent_group_selects_for_every_group_key_without_the_sha_gate`,
  which runs the identical fixture with no `current_sha` argument (the
  gate's default-off state) and asserts both groups select. The two tests
  together are the delete-the-fix pair: reverting the code change collapses
  the first test's assertion onto the second's.
  `test_a_pre_migration_null_sha_group_selects_once` pins the `NULL`-counts-
  as-changed rule directly. `test_same_deployed_sha_helper` unit-tests the
  three-way truth table (no recorded SHA, matching, non-matching) in
  isolation from the ledger-selection machinery.
- **Y7 write path** (`backend/tests/test_imagery.py`):
  `test_create_queued_request_stamps_deployed_sha` — `_create_queued_request`
  sets `deployed_sha == get_settings().git_sha` and non-`None`. Reversion:
  removing the `deployed_sha=settings.git_sha` kwarg makes the ORM column
  default to `NULL`, failing the `is not None` assertion.
  `scripts/backfill_census_housing.py`'s write site has no test — it opens
  its own `SessionLocal()` bound to `DATABASE_URL`, which in this test
  environment points at a Postgres URL nothing is listening on (the SQLite
  in-memory fixture the rest of the suite uses is not reachable from a
  script-level `SessionLocal`), and no test existed for this script before
  this batch either. **UNVERIFIED**: confirmed by code reading only (mirrors
  the reviewed `_create_queued_request` call exactly), not by a passing
  test.
- **Y8** (`backend/tests/test_census.py`,
  `TestDemographicsService`): `test_upsert_bumps_updated_at_on_changed_values`
  and `test_upsert_bumps_updated_at_even_when_values_are_identical` both read
  `updated_at` via raw SQL before/after a second `upsert_census_snapshot`
  call and assert it moved — the second test pins the "even identical
  values bump it" decision the prompt asked to be pinned rather than left
  incidental. Reversion: dropping `updated_at = EXCLUDED.updated_at` from
  the `ON CONFLICT` clause makes both assert `second != first` fail against
  the column's `server_default`-only value, which does not change on
  `UPDATE`.
- **Argparse** (`backend/tests/test_requeue_parcels.py`):
  `test_sources_does_not_swallow_a_trailing_parcel_id`, parametrized over
  `--sources naip <id>` and `<id> --sources naip`, both asserting the dry-run
  output names the id as a re-queue target scoped to `[naip]` — before the
  fix, the first order would have raised an argparse `choices` error (the id
  is not a legal source) rather than reaching that print at all, so this is
  already a de facto delete-the-fix: reverting `--sources` to `nargs="+"`
  makes the first parametrization fail with a parser error instead of the
  assertion. `test_sources_rejects_an_unknown_value` covers the new
  comma-split validation path directly.

## Deviations from the prompt

- **Absent/api_no_data count is 127, not 76.** HEAL-3 §4 recorded 76 on
  2026-08-27 right after the decennial-2000 sweep; this batch's own
  read (same day, same query) got 127. Recorded as a deviation in
  `PREDICTION.md` rather than silently using the stale figure — fleet
  traffic between the two reads is the likely cause, not a query
  regression (see `PREDICTION.md`'s note for the reasoning).
- **`--groups` was not converted.** The prompt named only `--sources` for
  the `nargs='+'` fix; `--groups` shares the flag shape but not a documented
  positional-adjacent invocation, so it was left as-is rather than expanding
  scope beyond what was asked.

## UNVERIFIED register

1. **`scripts/backfill_census_housing.py`'s `deployed_sha` write** — code-read
   only, no passing test (see Tests section above).
2. **Migration downgrade path** — read, not executed against any database.
3. **Claims 2, 3, 5 in `PREDICTION.md`** (post-deploy dry-run counts, the
   second dry-run reading zero, a real census heal's checksum-stable
   `updated_at`) are all pending an actual deploy and heal run, which are
   Ryan's per this project's write-ownership convention — not run in this
   session.
4. **Production `settings.git_sha` staying non-`"unknown"` across deploys**
   — assumed from the current deploy (`70f95d3e14b9859b0e7d2fc10eb499415e8533b6`,
   confirmed baked via `/api/v1/health` and `GH_SHA`), not verified as a
   property that holds for every future deploy.

## Commits

1. `2190e57` — `feat(schema): migration 0013 — deployed_sha, census_snapshots.updated_at`
2. `1367302` — `feat(ledger): Y7 deployed-SHA retry gate, Y8 updated_at on upsert`
3. This commit — docs.

None pushed.
