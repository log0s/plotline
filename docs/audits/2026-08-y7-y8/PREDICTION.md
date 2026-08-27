# Y7 + Y8 predictions — written before deploy

Nothing in this migration has been deployed or run against production. Two
independent additive columns, landed together (STATUS.md Y7/Y8, decided
2026-08-27): `timeline_requests.deployed_sha` and `census_snapshots.updated_at`.

Fleet numbers below were read from production on **2026-08-27** via
`fly ssh console -a log0s-plotline-api -C`, `SELECT`/read-only Python only,
against deployed SHA **`70f95d3e14b9859b0e7d2fc10eb499415e8533b6`** (API and
worker both confirmed on this SHA via `/api/v1/health` and
`fly image show -a plotline-worker`'s `GH_SHA` label). This SHA carries
**none** of Y7/Y8's code — the numbers below are the pre-migration baseline,
not a post-deploy observation.

Local dev DB (the sandbox this batch's own tests ran against) already has
migration 0013 applied; production does not yet.

---

## Fleet state at prediction time (production, pre-deploy)

| | |
|---|---:|
| `timeline_requests` | 127 |
| `census_snapshots` | 330 |
| `absent/api_no_data` groups, retryable under `--include-absent-api` (fleet-wide) | **127** |
| `absent/all_cloud_filtered` groups, retryable under `--include-cloud-filtered` | **9** |

**Deviation from HEAL-3's "76 today":** HEAL-3 §4 measured 76 permanent
absences on 2026-08-27 right after the decennial-2000 sweep. The number read
just now is **127**, not 76 — the retry/ops scoring sweep and other traffic
between HEAL-3 and this prediction created new `absent/api_no_data` rows
(most plausibly ACS5 vintages the trim did not touch). This is a real fleet
change, not a query error: the query is the same `ledger.retryable_groups`
path HEAL-3 used, run against the same production database. Y7's fix does
not care which of the two figures is right — it excludes whatever the count
is once a run has already retried it under the current SHA.

---

## Y7 — the deployed-SHA gate

**Claim 1.** After deploy, every newly created `TimelineRequest.deployed_sha`
equals the health SHA (`settings.git_sha`, same env var both API and worker
read). Falsified by any new request with `deployed_sha IS NULL` or a value
that does not match `/api/v1/health`'s reported SHA at creation time.

**Claim 2.** The first `requeue_parcels.py --from-ledger --sources
census_decennial --include-absent-api --dry-run` run after deploy selects
the full current absent/api_no_data population — **127 groups**, the number
above, since every existing row's `deployed_sha` is `NULL` (pre-migration)
and a `NULL` recorded SHA is never "same" as the running SHA
(`ledger.same_deployed_sha`). Falsified by a dry-run that selects fewer than
127 or more than 127 (a fewer count would mean the NULL-counts-as-changed
rule regressed; a larger count would mean new absent groups accrued between
this prediction and the run, which is not the code under test failing — but
either way it needs a note, not a silent match).

**Claim 3.** After one real (non-dry-run) run of that command, a second
`--dry-run` of the identical command selects **zero** groups: every group
the first run touched now carries `deployed_sha` = the SHA that run's
requests were created under, so `same_deployed_sha` reads true for all of
them and `is_retryable` returns `False`. Falsified by any group still
selected on the second dry-run, unless it is a group that did not exist on
the first run (a source stays outside this claim if newly created after run
1 and before the second dry-run — worth checking for, not assuming away).

**Claim 4.** The gate touches only `absent/api_no_data` and
`absent/all_cloud_filtered` selection. `RETRY` and `RETRY_ONCE` groups
(`failed/*`, `indeterminate`) select exactly as before — `same_deployed_sha`
never enters `is_retryable`'s branches for those policies. No falsifier
measured here; this is a code-reading claim (`ledger.py:229-260`), confirmed
by the full test suite passing with no change to the non-Y7 retry-policy
tests.

**Not claimed:** that 127 is the "right" number to retry — the sweep after
this deploys still costs one Census API call per group, same as before Y7;
Y7 only stops the *second* run from re-paying that cost with nothing changed
in between.

## Y8 — `census_snapshots.updated_at`

**Claim 5.** A census heal's `updated_at` moves only on rows the heal's
upsert actually writes — rows outside the heal's scope (a different parcel,
a different dataset/year) keep their prior `updated_at`. Checkable the next
time a scoped census heal runs, against the row-count delta and, for the
already-recorded decennial 2010/2020 rows, against heal 3's stored content
checksums (`../2026-08-m3/HEAL-3-decennial-2000.md` §5.5) — an unchanged
checksum with a moved `updated_at` is exactly what Y8 exists to make
visible (a heal touched the row and reconfirmed the value, rather than
either not running or silently corrupting it).

**Claim 6.** `updated_at` moves on an idempotent re-upsert with identical
values too — this is pinned behavior (`services/demographics.py`'s
docstring and `test_upsert_bumps_updated_at_even_when_values_are_identical`),
not a bug to fix later.

**Zero imagery churn.** Neither column touches `imagery_snapshots`,
`timeline_request_tasks`, or the imagery fetch/selection path. Falsified by
any change to `imagery_snapshots` row count or checksum surfacing in the
next sweep that runs after this deploys.

---

## What would make this batch wrong

- `deployed_sha` on a *new* request reads `"unknown"` in production (i.e.
  `GIT_SHA` not baked into the deployed image) — the gate still works
  mechanically (NULL-vs-string and string-vs-string both compare correctly),
  but every group recorded under `"unknown"` becomes indistinguishable from
  every other `"unknown"`-SHA group across *any* number of deploys that also
  fail to bake `GIT_SHA`, silently reverting to pre-Y7 behavior. Falsifiable
  by checking `settings.git_sha` is not `"unknown"` in the running containers
  before relying on Claim 2/3 in production.
- A concurrent heal between the two `--include-absent-api` dry-runs in
  Claim 3 (another operator, or `maybe_refetch_for_backfill`'s self-running
  path) writes new absent rows under the new SHA, which would show up as
  selected on the second dry-run without being a Y7 regression — worth
  ruling out before treating any nonzero Claim-3 result as a falsification.
