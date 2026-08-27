# M3 build report — per-source backfill reading the ledger

**Mode: execute.** Both phases, five commits, nothing pushed. Production was
read through `fly ssh console -a log0s-plotline-api -C`, `SELECT` only, for
the prediction numbers; nothing was written to production and no heal was
run. Line citations are against the tree at `b7c9cbb`.

The design record is `../2026-08-m3-design/INVESTIGATION.md` (`448b841`); the
three acceptance-case predictions are `PREDICTION.md`, written before any run
and not edited since.

**Two premises in the prompt did not hold, and one new production defect was
found.** All three are in the registers at the end. The defect — a source
that loses *every* year records nothing, while one that loses some records
everything — is fixed in this batch and is why `PREDICTION.md` P3 predicts
Sentinel-2 staying empty on the parcel M3 exists to heal.

---

## Commits

| | | |
|---|---|---|
| `ae740cf` | A1 | migration 0012, model, conftest schema, migration tests |
| `c98de1b` | A2 | scope in the worker, `partial`, reusable-request filter, admission reserve, frontend |
| `a6c7800` | B1 | `services/ledger.py`, retry policy, ledger backfill, suppressed-delete |
| `b7c9cbb` | B2 | `requeue_parcels.py` flags, `heal_tract_vintage_gaps.py` deleted, script fallout |
| *this batch* | C | `PREDICTION.md`, this report, STATUS.md, the whole-source flush fix |

A1 was verified to stand alone: with A2–B2 stashed, the suite passes at 534.
The full suite at `b7c9cbb` is **586 passed**, run under CI's environment
(`LOG_LEVEL=WARNING`, `CI=true`, `uv sync --locked`, a real PostGIS 16
`TEST_POSTGRES_URL`). `ruff check`, `ruff format --check` and `mypy app/` are
clean; the frontend passes `tsc --noEmit`, `eslint --max-warnings 0` and 19
vitest tests.

---

## Phase A

### 1. Migration 0012

`backend/alembic/versions/0012_request_scope_and_origin.py`. Additive: two
columns, one widened CHECK, one partial index. Nothing on
`timeline_request_tasks` is referenced — M7 item 5's ORM/database name drift
lives on that table and a statement naming one of its constraints from the
ORM would fail against production. `timeline_requests` carries no such drift:
`ck_timeline_requests_status` is spelled identically in
`0001_initial.py:107` and in the ORM, which is what makes dropping and
recreating it safe. Every new constraint is named explicitly —
`ck_timeline_requests_origin`, `ck_timeline_requests_sources` — and the ORM
(`app/models/parcels.py:194-207`) and `tests/conftest.py:70-91` repeat those
names.

**Backfill counts, measured against production 2026-08-26 ~18:05Z** (the
migration has not been run there; these are what it will do):

| | |
|---|---:|
| rows getting `sources` = the full declared set | **710** |
| rows getting `origin = 'user'` | **710** |
| `complete` → `partial` | **40** |
| `complete` → `failed` | **0** |
| left `failed` as they were | 3 |

**Deviation, deliberate: `sources` is not backfilled from the task rows.**
The prompt asks for "the distinct sources of their task rows". That is the
*derived* set, and it is 4, 5 or 6 wide depending on whether the parcel has a
census tract and a county — so it cannot express "full scope" as a single
stable value, which is exactly what item 3 needs to read. Shape A's own
wording settles it ("declared intent, not derived"): a full-scope request
declares all six sources and the worker intersects that with parcel
eligibility, which is what it did before the column existed. Every pre-0012
request was full-scope by construction — nothing in application code could
create a partial one (INVESTIGATION §1.4) — so all 710 are backfilled to the
full set. This makes `cardinality(sources) = 6` a sound test, which the
CHECK's `sources <@ ARRAY[…]` half and `normalize_sources`'
dedupe-and-sort (`app/services/imagery.py:86-102`) together guarantee.

**Index: on cardinality, not on origin.** Cited from the query it serves —
`_find_reusable_request` (`app/services/imagery.py:122-144`) filters
`parcel_id`, a status set, and full scope, ordered by `created_at DESC LIMIT
1`. So:

```sql
CREATE INDEX idx_timeline_requests_parcel_full_scope
ON timeline_requests (parcel_id, created_at DESC)
WHERE cardinality(sources) = 6
```

`origin` was the alternative and does not work: `requeue_parcels.py` with no
`--sources` creates a full-scope request with `origin='heal'`, so origin does
not separate full from scoped.

**Status backfill, and what it deliberately does not touch.** A `complete`
request with ≥1 failed and ≥1 non-failed terminal task becomes `partial`; one
with *every* task failed becomes `failed`, the same rule
`aggregate_request_status` applies at runtime (production has zero of those;
the branch exists so the migration implements the whole definition rather
than two thirds of it). A request already reading `failed` is left alone even
if some of its tasks succeeded — production's three are janitor-stranded runs
(`Stranded: worker died mid-task`), and promoting one to `partial` would make
it reusable again and stop its parcel ever being re-run.

Tested against a real Postgres in
`tests/test_migrations_postgres.py:305-419`: a three-request fixture
(all-clean / Crawford-shaped / all-failed) asserts each lands in its own
status, and a second test asserts the CHECKs reject an unknown source, an
empty array and an unknown origin.

### 2. `create_request_tasks` honours `sources`

`app/services/imagery.py:399-452` was already a loop over the sources it is
given, with `clear_task_year_outcomes` *inside* it
(`app/services/year_ledger.py:207-227` keyed on `(request, source)`). So
scoping the call scopes the clear for free: **a census-only request cannot
erase landsat ledger history**, because the delete never names landsat. That
is asserted directly rather than assumed —
`tests/test_imagery.py::test_create_request_tasks_only_touches_the_named_sources`
seeds a landsat and a census ledger row, re-runs `create_request_tasks` with
`["census"]`, and requires the landsat row to survive.

The scope itself is applied in `app/tasks/timeline.py:1394-1420`:

```python
eligible = [s["source"] for s in _SOURCES] + ["usgs_topo"]
if tract_fips: eligible.append("census")
if county:     eligible.append("property")
scoped = {s for s in eligible if s in set(request.sources)}
```

and `scoped` reaches **both** `create_request_tasks` (`:1421-1425`) and the
coroutine fan-out (`:1462-1520`). INVESTIGATION §1.3 is explicit that scoping
one and not the other creates fewer task rows while still running every
fetch, and `_set_task_status` then logs "No task row found for source" rather
than failing. Declared intent never outruns eligibility: a full-scope request
on a parcel with no county still runs no property task
(`test_declared_scope_never_outruns_parcel_eligibility`).

### 3. `_find_reusable_request` selects the latest full-scope request

`app/services/imagery.py:122-144`. **Trigger-6 traced through the new query.**
Before: a census-only backfill is the parcel's newest `queued|processing|complete`
request, so `get_or_create_timeline_request` hands it to
`maybe_refetch_for_backfill`, which looks for a `usgs_topo` task row on *that
request*, finds none, sets `needs_refetch`, and dispatches a full pipeline —
on every page view, forever, because the replacement is itself scoped. After:
the scoped request fails `cardinality(sources) = 6` and is invisible to the
query, so the older full-scope request is still what the trigger inspects,
its topo task row is present, and nothing fires. Both halves are asserted —
`test_scoped_request_never_becomes_the_parcels_current_request` on the query,
`test_a_scoped_request_does_not_trigger_a_full_backfill` on the consequence.

Two things fell out of this and are worth naming:

* **Race recovery had to be split off.** `uq_timeline_requests_parcel_inflight`
  does not care about scope — a scoped backfill occupies the parcel's one
  in-flight slot like anything else — so the loser of that race must be able
  to see it. `_find_inflight_request` (`:147-166`) is unfiltered and is what
  `_create_queued_request`'s `IntegrityError` branch uses. Leaving the
  filtered lookup there turns a lost race into a re-raised `IntegrityError`;
  the test for it uses `committing_db`, because the rollback-per-test fixture
  would take the racing request with it and the race could not be staged at
  all.
* **The full-scope predicate needs two spellings.** `sources` is `TEXT[]` on
  PostgreSQL and a JSON array on the SQLite test database (the ORM column is
  `ARRAY(Text).with_variant(JSON, "sqlite")`). `full_scope_clause`
  (`:105-119`) emits `cardinality(...)` or `json_array_length(...)`
  accordingly, table-qualified so it can be reused in a query that joins
  `timeline_requests` to a subquery over it. It is shared with
  `requeue_empty_property.py:66,83` and `revalidate_landsat.py:110`, which is
  item 3's "apply the same filter" — both of those also now count `partial`
  alongside `complete`.

### 4. Request-status aggregation, and `partial`

`aggregate_request_status` (`app/services/imagery.py:474-500`) takes
`(source, status)` pairs and returns the request status plus the failed
sources. `complete` = nothing failed; `partial` = some failed and some did
not; `failed` = all failed. `skipped` is not a failure (a county with no
adapter has always kept its request complete), and a request with no task
rows stays `complete`. Wired at `app/tasks/timeline.py:1529-1557`.

**Every reader of request status was checked.** Backend:

| site | what `partial` means to it | change |
|---|---|---|
| `_find_reusable_request` | reusable, like `complete` | added to `_REUSABLE_STATUSES` |
| `_is_stale_inflight` | not in-flight, so not stale | none needed |
| `sweep_stranded_work`'s orphan join | terminal | added to `_TERMINAL_REQUEST_STATUSES` |
| `update_timeline_request_status` | sets `completed_at` | now keyed on the terminal tuple |
| `maybe_refetch_for_backfill`'s entry test | eligible for backfill | `status not in ("complete", "partial")` |
| `requeue_empty_property.find_candidates` | the run still ran property | `status.in_(("complete","partial"))` |
| `revalidate_landsat.swept_since` | the pipeline did run under the new code | same |
| `GET /timeline-requests/{id}` | passthrough | none needed |

Frontend, the M11 fix's components:

| site | before | after |
|---|---|---|
| `hooks/queries.ts:86` poll loop | `complete \|\| failed` | `isTimelineTerminal` |
| `ExplorePage.tsx:58-60` `timelineActive` | inverted the same test | `!isTimelineTerminal(...)` |
| `ExplorePage.tsx:88` imagery refetch | `=== "complete"` | `isTimelineDelivered` |
| `Timeline.tsx:129` `eventsEnabled` | `=== "complete"` | `isTimelineDelivered` |
| `ParcelInfo.tsx:286` demographics `enabled` | `=== "complete"` | `isTimelineDelivered` |
| `Timeline.tsx:326` `isFailed` | `=== "failed"` | unchanged — `partial` must not be an error |
| `ParcelInfo.tsx:239` error banner | `=== "failed"` | unchanged, same reason |

The two predicates live in `frontend/src/utils/timelineStatus.ts`. A
`partial` request that polled forever would be the worst outcome of this
change, so `isTimelineTerminal` is the one that stops the loop and
`isTimelineDelivered` is the one that unblocks dependent queries; the two
error renderers are the only places `partial` deliberately behaves like
`complete` does *not*.

**`partial` carries no `error_message`.** Both frontend renderers of
`request.error_message` are gated on `status === "failed"`, so setting one
today would be invisible — and one refactor away from becoming a red banner
over a working timeline. Which sources failed is on the task rows, which is
where `ParcelInfo`'s `unavailableSources` already reads it from. The worker
logs `Timeline request partial — some sources failed` with the source list
instead (`app/tasks/timeline.py:1539-1547`).

Two frontend tests assert the shape:
`ParcelInfo.test.tsx::"does not render a partial timeline as failed"` and
`"enables demographics for a partial timeline"`.

### 5. Admission slice

`effective_cap(settings, origin)` (`app/services/admission.py:54-69`): `user`
gets `max_inflight_timeline_requests`; anything else gets
`cap - user_admission_reserve`, clamped at zero. One extra predicate on the
same `inflight_depth` query. `ensure_admission` and `wait_for_admission_slot`
both read it, which matters — a wait on the *user* cap would return, the gate
would refuse on the *heal* cap, and the loop would spin.

The test the prompt asks for is
`test_reserve_refuses_a_heal_while_still_admitting_a_user_request`: 25 in
flight, cap 30, reserve 5 — the user request is admitted, `backfill` and
`heal` are both refused with `queue_full` at depth 25.

**One thing this uncovered.** With a reserve at or above the cap the heal
ceiling is zero, and `wait_for_admission_slot` would have spun forever
against a depth that can never fall below it. It now refuses immediately and
says why (`admission.py:130-144`). Found because the pre-existing wait tests
use `max_inflight_timeline_requests=1`, which the new default reserve of 5
drove to a cap of 0 — the suite hung rather than failed. Those tests now set
`user_admission_reserve=0` explicitly (`tests/test_admission.py:18-23`), so
they keep measuring the cap; the reserve tests set it explicitly too.

---

## Phase B

### 6. `services/ledger.py` — one selection query

`latest_outcomes` (`app/services/ledger.py:114-151`) holds the window query
that was in `scripts/ledger_gaps.py:41-64`. Three callers share it now:
`ledger_gaps.py` (the report), `maybe_refetch_for_backfill` (self-running),
and `requeue_parcels.py --from-ledger` (operator). Reading a report built on
one definition of "latest" and then healing on another is how a sweep misses
exactly the rows the operator was looking at.

**Latest is by the request's `created_at`, tie-broken by the ledger row's
own. Why not task id:** task ids are `uuid4` — `default=uuid.uuid4` in the
ORM, `gen_random_uuid()` as the server default. They are random, not
monotonic, and carry no ordering whatsoever, so sorting by one picks an
arbitrary run's answer and picks differently on every insert. The request's
`created_at` is the only column in the join that means "when this attempt
happened".

Narrowing happens in Python, not inside the CTE: the window has to see every
run of a triple to rank them, so a `WHERE` inside the CTE would change
*which row wins*, not just which rows come back.

`attempts` is now trustworthy in a way it was not. INVESTIGATION §3.3
measured 2,270 of 2,283 non-`ok` rows at `attempts = 1` because the one
in-place re-run path upserted on `(task_id, group_key)` and collapsed two
attempts into one row without moving `created_at`. That path was
`heal_tract_vintage_gaps.py`, deleted in B2 — every route now creates its own
request, so `attempts` increments. That is what makes the `indeterminate`
retry-once rule implementable at all, and it is cheap: the count is a second
window in the same query, no extra round trip.

### 7. The retry policy table

`RETRY_POLICY` (`app/services/ledger.py:167-195`), keyed on
`(outcome, reason)` with a `None` reason as the outcome-wide fallback:

| key | policy |
|---|---|
| `("failed", None)` | `RETRY` |
| `("suppressed", None)` | `NEVER` |
| `("absent", "no_scenes")` | `NEVER` |
| `("absent", "no_covering_item")` | `NEVER` |
| `("absent", "all_cloud_filtered")` | `NEEDS_CLOUD_FLAG` |
| `("absent", "api_no_data")` | `NEEDS_ABSENT_API_FLAG` |
| `("indeterminate", None)` | `RETRY_ONCE` |
| `("ok", None)` | `NEVER` |
| anything else | `NEVER`, **and logged as a policy gap** |

The gap log is the point of the fallback design: `("absent", None)` is
deliberately absent from the table, so a new `absent` reason added to
`year_ledger.REASONS` without a decision here announces itself instead of
being swept into "no". Asserted by
`test_an_unclassified_pair_is_never_and_says_so`.

Every row of the table is exercised by a parametrised test
(`tests/test_ledger_selection.py:183-206`), and the two flag-gated classes
have their own test proving the flags are not interchangeable.

**One deviation from INVESTIGATION §3.2, taken knowingly.** §3.2 argues
`failed/http_4xx` (other than 429) is *not* retryable — "a 4xx is us asking
wrong", and `http_404` on `1990/dec/sf1` was answered by stopping asking, not
by retrying. The prompt's item 7 says `failed/*` → retry, without exception,
and that is what is implemented. The reasoning for following it: the
canonical 4xx instance is gone from the code (`e6afa9b` dropped the 1990
endpoint), a 4xx retry costs one request and re-records the same row so it is
visible and self-limiting, and carving an exception into an explicit
instruction on the strength of an argument the instruction had in front of it
is not mine to do. It is recorded here so the trade-off is legible if a 4xx
population ever appears.

`RETRY_ONCE` uses `attempts <= 1`, which needs the paragraph above to be
true. If the in-place re-run pattern ever returns, this rule silently becomes
"retry forever".

### 8. Backfill reads the ledger

`maybe_refetch_for_backfill` (`app/services/imagery.py:481-620`) gains one
path: `_ledger_backfill_sources` selects retryable groups for the parcel,
folds them onto the task sources that would re-run them, and the result
becomes a **single scoped request** with `origin='backfill'` and exactly those
sources. It never selects the flag-gated classes — backfill has no way to
assert that a fix shipped, and `PREDICTION.md` P2's 187-parcel selection is
what happens when something does.

**Which existing triggers are subsumed: none, and each for its own reason.**

* *Census (missing or failed task row).* A **missing** task row means the
  source never ran, so it has no ledger rows — absence is not an outcome, and
  the ledger cannot represent it. A census task that failed before its first
  year also wrote nothing.
* *Property (missing / skipped / failed).* Property writes no
  `timeline_task_years` rows at all, in any circumstance: its axis is the
  feed, not a period (INVESTIGATION §6.1). There is nothing for the ledger to
  see.
* *Topo (no task row).* Same as census's missing-row half.

All three keep dispatching a **full-scope** request, and that is load-bearing
rather than conservative: a topo-*scoped* run would leave the parcel's
current full-scope request still lacking a topo task row, so the trigger
would fire again every cooldown, forever. Scoping them would break the
one-shot latch that makes trigger 6 terminate.

**Cooldown is per source.** `last_attempt_by_source`
(`app/services/ledger.py:243-268`) reads the latest request that *included*
each source; `_outside_cooldown` (`imagery.py:645-707`) narrows the candidate
set to those outside the window. Still dispatch-anchored — it measures time
since a request was created, not since a source was attempted — which is
unchanged and still the honest description. A full-scope trigger stays full
scope even when some of its sources are cooling: narrowing it to dodge a
cooldown would cost the topo latch and `requeue_empty_property`'s
latest-request join for the sake of a few minutes of work.

### 9. Reconciliation honours `suppressed`

`reconcile_source_snapshots` (`app/services/imagery.py:1013-1140`) takes
`suppressed: Mapping[str, set[str]]` — group key → the item ids **this run**
positively identified as unservable. A row in one of those groups whose item
id is named is deleted even though the group is absent from the selection.
Collected at the two sites that have an item id to name:
`naip_no_point_coverage` (`app/tasks/timeline.py:538-546`) and `no_cog_url`
(`:611-613`), and passed at the reconcile call (`:704`).

**`e513188c`'s 2023 row traced through it.** `keep` = the eight `ok` years'
item ids; `groups` = `{2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022}`. The
2023 row's item id is not in `keep`, and its group `"2023"` is not in
`groups`, so the supersede branch skips it — that is today's behaviour and
why the card survives. The new branch then asks whether
`nj_m_4007309_sw_18_030_20230820_20231019` is in `suppressed["2023"]`. It is:
the gate names it first in the suppression detail. Deleted, one row, logged.

**The inverse matters more, and has its own test.**
`test_reconcile_does_not_delete_on_an_absent_outcome` runs the identical
fixture with `suppressed={}` and requires zero deletions —
`naip absent/no_scenes` alone is 1,848 latest rows fleet-wide, so a rule that
deleted on absence would delete on the largest population in the ledger.
`test_reconcile_leaves_a_different_item_in_a_suppressed_group` asserts the
item-id condition: a row for the same year built from an item the gate never
judged is not the suppression's to delete.

Three properties keep it safe, and all three are in the docstring where
someone would go to widen the rule: this run's outcomes rather than a ledger
query (a suppression corrected since must not license a delete years later);
item ids rather than periods; and `suppressed` only — `failed` knows strictly
less than `absent`, and `indeterminate` names a site that could not decide.

**`no_cog_url` is included, and that is a decision.** INVESTIGATION §4.3 asks
for it to be decided separately from `naip_no_point_coverage`, on the grounds
that the previously-served row for that group may be a perfectly good
*different* item. The item-id condition is exactly what makes that safe, so
both are carried. Zero rows in production have ever borne this reason
(UNVERIFIED, carried from §4.3), so the decision has no measured blast
radius. Topo's suppressions are *not* carried: `topo_no_source_id` fires
precisely because the product has no id to match on.

### 10. Scripts

`requeue_parcels.py` gains `--sources`, `--from-ledger`,
`--include-cloud-filtered`, `--include-absent-api`, and a `--dry-run` that
lists parcel → scope → every group with its outcome, reason and attempt
count. `parcel_ids` became optional (`nargs="*"`); a bare invocation with
neither ids nor `--from-ledger` is an error, and the two `--include-*` flags
refuse to be passed without `--from-ledger`. The deployment gate is untouched
and still runs before any database access, dry runs included.

`--sources` names sources **the way the ledger does** — `census_decennial` is
legal and narrows selection to that dataset, while the request it creates
declares the task source that would re-run it (`census`). That reconciles the
two spellings the acceptance cases use (`--sources naip`, `--sources
census_decennial`) into one rule rather than two meanings for one flag.
Selection is scope-preserving per parcel: `select_from_ledger` builds
`{parcel: {task_source: [groups]}}`, so a parcel with only failed Landsat
years gets a Landsat-only request in the same run that gives a census-only
parcel a census-only one.

`heal_tract_vintage_gaps.py` is **deleted**. Grepped: no reference remains in
any `.py`, `.yml`, `.toml`, `.sh` or `.json` in the tree. One deliberate
mention survives as a comment in `app/services/ledger.py:67`, naming it as
the in-place re-run pattern that made `attempts` untrustworthy. The audit
documents that mention it are frozen and stay as written; STATUS.md's
references are marked historical.

`revalidate_landsat.py` keeps its fleet-sweep job unchanged — "re-run
everything under the new code" is not a ledger query — and gains
`origin='heal'` plus the full-scope filter on `swept_since`.

`requeue_empty_property.py` per item 3. **Property has no ledger source, and
what its `group_key` would be:** the *feed*, not a period —
`_fetch_and_persist_property` fans out over exactly two,
`adapter.fetch_sales` and `adapter.fetch_permits`, and then collapses them,
so sales succeeding while permits fails entirely is recorded `complete`.
A property ledger would be two rows per task, `"sales"` and `"permits"`, with
`WHOLE_SOURCE_GROUP_KEY` (`"*"`) available for an adapter-level failure that
precedes both — the same move topo already made. Not built here: it needs its
own vocabulary decision (`absent` wants a reason that is not `no_scenes`) and
nothing in M3 depends on it. It is filed in STATUS.md.

`ledger_gaps.py` now reads through `services/ledger.py` and prints the
policy's verdict per row in a new `retry` column. Its `ACTIONABLE` reporting
filter gains `suppressed` and stays deliberately **wider** than the retry
policy: `indeterminate` is a code fix and `suppressed` is reconciliation
input, but both are things a human should be looking at, and collapsing the
report onto `is_retryable` would hide the two classes that need a decision
made about them.

### 11. Tests

Beyond the per-item ones above:

* a scoped census-only request runs no imagery task, no imagery coroutine and
  no reconciliation (`test_census_only_request_runs_no_imagery_and_no_reconciliation`)
* `partial` aggregated from a six-task fixture with two failures, unit
  (`test_aggregate_request_status_partial`) and through the orchestrator
  (`test_one_failed_source_makes_the_request_partial`)
* every row of the retry table (parametrised, 13 cases) plus the policy-gap log
* the shared selection query against two runs where the second flips `failed`
  → `ok` (`test_the_second_run_wins`), and its inverse
  (`test_a_group_that_regressed_reads_failed`)
* the Crawford shape end to end in selection: 16 + 17 groups fold to exactly
  `["landsat", "naip"]`, and the flag-gated classes appear only with their
  flags (`test_crawford_shape_selects_landsat_and_naip_only`)

`tests/test_ledger_selection.py` is new; the rest are appended to
`test_imagery.py`, `test_timeline.py`, `test_admission.py`,
`test_year_ledger.py`, `test_requeue_parcels.py` and
`test_migrations_postgres.py`.

---

## Delete-the-fix — every reversion, and what it broke

Each fix was reverted in the working tree, the named tests run, and the file
restored from a backup taken before the reversion. Ten reversions, ten
failures.

| # | reverted | tests that failed |
|---|---|---|
| 1 | `full_scope_clause(db)` from `_find_reusable_request` | `test_scoped_request_never_becomes_the_parcels_current_request` |
| 2 | race recovery back to `_find_reusable_request` | `test_losing_the_race_to_a_scoped_request_reuses_it` |
| 3 | the `partial` branch of `aggregate_request_status` | `test_aggregate_request_status_partial`, `test_one_failed_source_makes_the_request_partial` |
| 4 | the `origin` branch of `effective_cap` | `test_reserve_refuses_a_heal_while_still_admitting_a_user_request`, `test_reserve_at_or_above_the_cap_refuses_rather_than_spins` |
| 5 | the `source not in scoped` guard in the fan-out | `test_census_only_request_runs_no_imagery_and_no_reconciliation` |
| 6 | `isTimelineDelivered` in `ParcelInfo.tsx` | `ParcelInfo.test.tsx::"enables demographics for a partial timeline"` |
| 7 | the suppressed-delete branch in `reconcile_source_snapshots` | `test_reconcile_deletes_a_group_this_run_suppressed`, `test_reconcile_can_delete_a_suppression_when_nothing_was_selected` |
| 8 | the ledger path in `maybe_refetch_for_backfill` | `test_backfill_dispatches_a_scoped_request_from_the_ledger`, `test_the_ledger_cooldown_is_per_source` |
| 9 | per-source cooldown → per-parcel max | `test_the_ledger_cooldown_is_per_source`, `test_last_attempt_is_per_source` |
| 10 | the `--include-absent-api` gate → `RETRY` | `test_the_flag_gated_classes_need_their_flag`, `test_backfill_never_selects_the_flag_gated_classes`, `test_from_ledger_needs_the_flag_to_reach_absent_api` |
| 11 | per-parcel scoping in `select_from_ledger` | `test_ledger_selection_is_scoped_per_parcel` |
| 12 | `_flush_ledger` before `raise last_exc` | `test_a_source_whose_every_year_failed_still_records_them` |

**Reversion 2 caught a bad test.** The first version of that test asserted
`_find_inflight_request` and `_find_reusable_request` directly, so reverting
the *call site* left it green — it guarded the helper, not the wiring. It was
rewritten against `_create_queued_request` on `committing_db` and then failed
as it should. Worth recording because the reversion is the only thing that
found it.

---

## The new production defect, and the fix

**A source that loses every year records nothing; a source that loses some
records everything.** Found on 2026-08-26 ~18:12Z while reading Crawford
County `6563dedf` for `PREDICTION.md` P3.

That parcel's Sentinel-2 task reads `failed`, it serves zero Sentinel-2
snapshots, and the ledger holds **zero** `sentinel2` rows for it — while the
same run's 16 lost Landsat years and 17 lost NAIP years are all recorded. The
asymmetry is in `_search_and_persist_source`: the chunked branch stages every
failed year in a `YearOutcomeLog` and then, when `failed_years ==
len(years)`, does `raise last_exc` (`app/tasks/timeline.py:419`) — before any
persist session opens. The staged log dies with the exception. The un-chunked
branch already called `_flush_ledger` before its `raise`
(`:447`); the chunked one never did.

Sentinel-2 and Landsat are the two chunked sources, so both are exposed;
NAIP's whole-search failure is on the flushing branch, which is why NAIP's 17
rows exist and Sentinel-2's twelve do not.

This inverts what the ledger is for. The instrument was silent exactly where
the loss was total, and a ledger-driven heal cannot select what was never
written. Fixed by flushing before the raise, with the reason at the site;
`test_a_source_whose_every_year_failed_still_records_them` fails with the
flush removed.

**The fix cannot recover `6563dedf`'s twelve Sentinel-2 years.** Those rows
were never written and there is no history to reconstruct them from, so P3
predicts the parcel still serving zero Sentinel-2 after its ledger-driven
heal, and names the separate full-scope run that would fix it. Fleet-wide,
how many other parcels have a `failed` task with no ledger rows under it was
not measured — it is in the UNVERIFIED register.

---

## Deviations

1. **Migration backfill of `sources`** — full declared set for every row,
   not the distinct task sources. Reasoned in Phase A item 1; the prompt's
   own shape-A wording ("declared intent, not derived") is what settles it,
   and the derived set cannot express full scope as a stable value.
2. **`failed/http_4xx` retries**, per item 7's `failed/*`, against
   INVESTIGATION §3.2's narrower reading. Reasoned in Phase B item 7.
3. **`no_cog_url` is carried into the suppressed-delete** alongside
   `naip_no_point_coverage`, which §4.3 asks to be decided separately. The
   item-id condition makes it safe; zero rows carry the reason today.
4. **The legacy triggers stay full-scope** rather than becoming scoped.
   Item 8 does not require scoping them, and scoping topo would break the
   one-shot latch. Reasoned in Phase B item 8.
5. **`requeue_parcels.py` gained no per-group filter**, so P2's command
   selects 187 parcels rather than the 80 the trim can help. Named in
   `PREDICTION.md` P2 with the cost (107 parcels doing ~9 Census calls each
   and changing nothing) rather than papered over; filed in STATUS.md as a
   follow-up.
6. **`ACTIONABLE` in `ledger_gaps.py` was widened rather than replaced by
   the retry policy.** A report that showed only retryable rows would hide
   `indeterminate` and `suppressed`, which are the two classes that need a
   human decision.

---

## UNVERIFIED register

1. **No heal has been run.** Every claim in `PREDICTION.md` is a prediction.
   The migration has not been applied to production either — the 710 / 40 / 0
   backfill counts are what the migration's own SQL would do against the
   fleet as read at 18:05Z, computed by running that shape as a `SELECT`.
2. **The 16 tracts that 204 even under the four-character form were not
   re-probed.** P2's 64 carries them from
   `../2026-08-census-decennial/REPORT.md` §1.5, probed 2026-08-26 earlier
   the same day. Re-probing is a live-API call this session did not make.
3. **How many other parcels have a `failed` task with zero ledger rows under
   it is unmeasured.** `6563dedf`'s Sentinel-2 is the instance that was found;
   the fleet was not swept for the shape.
4. **Whether `suppressed/no_cog_url` has ever fired in production is still
   unknown** — zero rows carry it, and whether that means unreachable or
   merely rare is not established. Carried unchanged from INVESTIGATION §4.3.
5. **The `partial` render is tested, not observed.** No production request
   reads `partial` yet; migration 0012 creates the first 40.
6. **The admission reserve is unit-tested, not measured.** No production run
   has contended for the cap under the new ceiling.
7. **The per-source cooldown's production behaviour is untested by any
   prediction.** All three acceptance cases go through `requeue_parcels.py`,
   which does not consult the cooldown at all.
8. **`ledger_gaps.py` was not re-run against production after being
   refactored onto `services/ledger.py`.** The query text is byte-identical
   to what it replaced, and the module is covered by tests, but the script
   itself has only been exercised locally.

---

## Premises in the prompt that I found to be wrong

1. **"`e6afa9b` is not deployed" is no longer true.** The prompt inherits
   INVESTIGATION §5's correction, which was accurate at 09:35Z against
   `4330833`. Production now runs `b599c25` (API `built`
   2026-08-26T17:57:51Z, worker `GH_SHA` identical), and `git merge-base
   --is-ancestor e6afa9b b599c25` exits 0. The decennial-2000 heal is
   therefore executable the moment M3 deploys, and P2 is written against that
   premise rather than as a dry run for a run that cannot happen.
2. **"Decennial 2000 — ~80 parcels `absent/api_no_data`" understates what
   the specified command selects.** 80 is the ends-in-`00` population the
   trim fixes, and it is right. But `--from-ledger --sources
   census_decennial --include-absent-api` selects on the *source*, not the
   group, and the ledger holds 187 stale `census_decennial`/`1990` rows for a
   year the code no longer attempts — so the command selects 187 parcels and
   327 groups. §5 predicts 64 rows and that number is unchanged; the parcel
   count is not what the prompt expected.
3. **"Crawford MI `6563dedf` — 33 `failed/read_timeout` (16 Landsat years, 17
   NAIP)" is exactly right, and the sentence after it is what is wrong.** The
   prompt and INVESTIGATION §8.3 both describe the parcel's Sentinel-2 task
   as failed, which it is — but there is no Sentinel-2 *ledger* row, so
   "unhealable by anything self-running" is true for a second reason nobody
   had noticed: not only can backfill not see it, ledger-driven selection
   cannot see it either. That is the defect above.

Everything else held. `maybe_refetch_for_backfill` did inspect no imagery
source; `reconcile_source_snapshots` did never delete an absent group and the
`e513188c` card is still served (re-confirmed 18:07Z, and it is still the
only one of the nine latest `suppressed` rows with a served snapshot);
`ledger_gaps.py` did already compute latest-outcome-per-triple; and the
request-status defect is real — `b1392b23` reads `complete` with two `failed`
task rows under it as of 18:12Z.

---

## Addendum, 2026-08-26 — Y3 fix: a group current code no longer attempts is no longer "retryable"

One commit on top of the five above. Mode: execute. Not pushed.

### The attempted set, per loop, before this fix

Nothing before this batch could answer "would current code ever attempt
group X of source Y again", so nothing could tell a genuinely-still-failing
group from one whose endpoint or year list moved out from under it. Five
loops, five different answers, none of them shared:

| source(s) | where the attempted set lives | shape |
|---|---|---|
| `census_decennial` | `census.py:91` `DECENNIAL_YEARS` | explicit year list |
| `census_acs5` | `census.py:92` `ACS5_YEARS` | explicit year list |
| `naip`, `landsat`, `sentinel2` | `timeline.py:58,70,82` (`start_date`/`start_year` on each `_SOURCES` entry) | `start_year..today` |
| `usgs_topo` | nowhere — one untimed TNM query, `timeline.py:779` | whole-source only (`WHOLE_SOURCE_GROUP_KEY`, `"*"`) |

The census loops (`timeline.py:1063` decennial, `:1123` acs5) iterate their
list directly; the imagery loops (`timeline.py:381` chunk-by-year, `:441-443`
un-chunked) build `attempted` from `start_year`/`start_date` through
`date.today()`. `e6afa9b` shrank `DECENNIAL_YEARS` by removing 1990; nothing
downstream of that change knew the ledger's pre-existing 1990 rows had gone
stale, so `is_retryable` kept saying yes forever.

### The fix

1. **`imagery.attempted_group_keys(source) -> set[str]`**
   (`imagery.py:924-945`), the one place all four shapes above are now
   expressed. Census sources import `DECENNIAL_YEARS`/`ACS5_YEARS` directly
   rather than duplicating them. The three time-ranged imagery sources read
   their floor from `imagery.IMAGERY_SOURCE_START_YEAR`
   (`imagery.py:917-921`) — `_SOURCES` in `timeline.py:58,70,82` now builds
   `start_date`/`start_year` from that same dict, so the loop and the
   attempted-set function cannot drift apart. `usgs_topo` returns
   `{WHOLE_SOURCE_GROUP_KEY}` — the exception item 1 asked about: it has no
   per-decade attempted set (INVESTIGATION §3e), so its only attempted group
   is the whole-source key, and its per-decade rows are a *result*
   classification, never an attempted one. An unknown source raises
   `ValueError` rather than returning an empty set, so a new source with no
   entry here fails loud instead of reading every one of its groups as
   stale.
2. **`ledger.is_stale(group)`** (`ledger.py:216-226`) and its use inside
   `is_retryable` (`ledger.py:236-237`): a group outside its source's
   attempted set is never retryable, regardless of outcome or flag.
3. **`ledger_gaps.py`'s `stale` bucket** (`_print_stale`,
   `scripts/ledger_gaps.py`): a stale group's outcome is unchanged and it is
   never selected, but it is listed under its own heading rather than
   silently dropped from the report — the ledger's job is to show, not to
   hide.
4. **`--groups` on `requeue_parcels.py`** (`scripts/requeue_parcels.py`):
   operator scope on top of the retry policy, composable with `--sources`;
   explicitly not a substitute for item 2 — a stale group stays excluded
   regardless of `--groups`.

### Delete-the-fix

Reverting the two-line `is_stale` guard inside `is_retryable`
(`ledger.py:236-237`) makes
`test_a_stale_group_is_never_selected_even_with_every_flag`
(`test_ledger_selection.py`) fail exactly as expected: both the retired 1990
row and the live 2000 row select. Restored and re-verified green.

### Tests

`test_ledger_selection.py`: `attempted_group_keys` excludes a retired year
and includes a live one; an unknown source raises; a fixture with a
`census_decennial`/1990 `absent/api_no_data` row and a 2000 one selects only
2000 under `--include-absent-api`; `is_stale` agrees with
`attempted_group_keys` directly. `test_ledger_gaps.py` (new): the 1990 row
reports `stale=True`, 2000 `stale=False`; `_print_stale` lists the retired
group and is silent when nothing is stale. `test_requeue_parcels.py`:
`--groups` narrows a dry-run selection within a source; `--groups` without
`--from-ledger` refuses.

Full suite: 593 passed, 1 skipped (a pre-existing environment-dependent
skip, unrelated to this batch), plus two pre-existing environment-only
failures present identically at `ea0f640` before this batch
(`test_health.py::test_health_survives_missing_build_identity`,
`test_workflow_pins.py::test_every_action_is_pinned_to_a_commit_sha` — the
first depends on a build-identity env var this container doesn't set, the
second on a `.github/workflows` directory not mounted into it). `ruff check
app/ tests/`, `ruff format --check app/ tests/`, and `mypy app/` are clean.
Run under `CI=true LOG_LEVEL=WARNING`, `uv sync --locked --all-extras`
(`--all-extras` needed locally to pull the `dev` dependency group that
carries `pytest-socket`; CI's own `uv sync --locked` step installs it by a
different path — not investigated further, out of scope for this batch),
against a real `TEST_POSTGRES_URL` (the local `docker compose` Postgres,
not production).

**Resolved (this batch, 2026-08-26):** the two failures named above are no
longer carried as a footnote. See `STATUS.md`'s M3 section, row Y6.

### PREDICTION.md P2, corrected

Neither M3 nor this fix is deployed (`fly image show -a plotline-worker`:
`GH_SHA=b599c2519c5c29fc8b5e4ab170da1b0021f2c559`, pre-`ae740cf`), so the
corrected count could not come from running `requeue_parcels.py --dry-run`
against prod — the deploy gate would refuse it, and pre-M3 code has no
`services/ledger.py` to run in the first place. What was run instead is a
read-only SQL query against prod (`fly ssh console -a log0s-plotline-api -C`,
`SELECT` only, 2026-08-26) reproducing `ledger.py`'s own latest-outcome
window for `source = 'census_decennial'`, grouped by `group_key`/`outcome`.
**Corrected: 140 parcels, 140 groups — not 187/327.** Full addendum,
including the raw query result, is in `PREDICTION.md` under P2. This is a
scored correction of the 187/327 number, not a rewrite of it; the original
prediction stood correctly for the code as it existed when it was written.

### STATUS.md

Y3 → resolved, with the hash of the commit carrying this addendum.
