# The sweep scripts and the admission cap

Written 2026-08-25, after the S2-year sweep reached 30 of 184 parcels
(`HEAL-SCORECARD.md` §2, §11.1). Investigation first, then the fix
(`d6b21b3`). Nothing here ran against production: no sweep, no writes,
no re-run. The completion sweep is Ryan's.

---

## 1. Investigation

### 1(a) Where the refusal comes from, and why 2026-08-12 never saw it

| Fact | Value | Citation |
|---|---|---|
| Refusal raised | `AdmissionRefused("queue_full", depth=depth)` | `backend/app/services/admission.py:75` |
| Also raised for the kill switch | `AdmissionRefused("kill_switch")` | `backend/app/services/admission.py:62` |
| Cap | `max_inflight_timeline_requests: int = 30` | `backend/app/config.py:92` |
| Kill switch | `accept_new_parcels: bool = True` | `backend/app/config.py:87` |
| What counts as in-flight | `status in ("queued", "processing")` | `backend/app/services/admission.py:31,44-51` |
| Where every new run passes through it | `ensure_admission(db, get_settings(), what="timeline_request")` | `backend/app/services/imagery.py:114`, inside `_create_queued_request` (`:104`) |
| Prod value, read live 2026-08-25 | `30`, `accept_new_parcels=True` | `fly ssh console -C` on `log0s-plotline-api` |

**The 2026-08-12 geometry sweep pushed 57 parcels through because the cap
did not exist yet.** `admission.py` was introduced by **`b606d18`,
"fix(security): verify client coordinates, cap and kill-switch new work",
committed 2026-08-22 17:23 −0600** — ten days after that sweep. The file
is absent at `b606d18~1` (`git cat-file -e b606d18~1:backend/app/services/admission.py`
fails), and `git log -S max_inflight_timeline_requests` returns that
commit alone. `b606d18` is an ancestor of HEAD.

So there is no puzzle to explain and nothing to stop for: the geometry
sweep ran under **no admission regime at all**, and this script has never
once been run against a cap until 2026-08-25. The defect is not a
regression in the script; it is a caller that was written before the
callee could refuse.

### 1(b) Every caller of `_create_queued_request` outside the API

| Caller | Handled `AdmissionRefused`? | What a refusal did |
|---|---|---|
| `scripts/revalidate_landsat.py:69` (pre-fix) | **No** — `except IntegrityError` only | Propagates out of `main`; every parcel after it is abandoned. This is the 30-of-184 sweep. |
| `scripts/requeue_parcels.py:245` (pre-fix) | **No** — same shape | Same: the tail of the operator's id list is silently dropped, after a traceback. |
| `scripts/requeue_empty_property.py:117` (pre-fix) | **No** — same shape | Same, and `--limit` makes a short run look deliberate. |
| `app/services/imagery.py:447-455` (backfill) | **Yes** | Logs `Backfill suppressed — admission refused` and returns `None`. Correct for optional work on a parcel that already renders. |
| `app/api/v1/geocode.py:267,305`, `app/api/v1/imagery.py:85` | **Yes** | Answers the user with `REFUSED_DETAIL`. Correct: a request-path refusal is an answer, not a wait. |

The three scripts were the entire exposure, and they shared one loop body
almost verbatim. The API and the backfill path were already right.

### 1(c) How the sweep picks parcels, and what the schema remembers

`revalidate_landsat.py` selected every parcel holding a Landsat row —
`select(ImagerySnapshot.parcel_id).where(source == "landsat").group_by(parcel_id)`,
at `scripts/revalidate_landsat.py:41-49` pre-fix (the prompt's citation is
right; it is `:84-93` after the fix, now taking a session so it can be
tested). No ordering, no filter, no notion of progress: a second run
re-runs the whole fleet.

**`timeline_requests` records no deploy identity.** Its columns are `id`,
`parcel_id`, `status`, `created_at`, `updated_at`, `completed_at`,
`error_message` (`backend/app/models/parcels.py:94-133`, `TimelineRequest`). `grep -ri sha
backend/app/models/` returns nothing but the word "Shared" in a docstring,
and no migration mentions one. So "has this parcel been swept under SHA
X?" is not a question the database can answer, which is what shapes item
3 below.

---

## 2. What changed

| File | Change |
|---|---|
| `backend/app/services/admission.py:78-140` | New `wait_for_admission_slot`. Polls `inflight_depth` — the same query `ensure_admission` gates on (`:44-51`), so wait and gate cannot disagree about "full" — until depth is below the cap or a deadline passes. Returns `bool`. Never waits out `kill_switch`. |
| `backend/app/services/imagery.py:137-173` | New `create_queued_request_waiting`. Wraps `_create_queued_request`; identical return contract and `IntegrityError` behaviour; `queue_full` becomes a wait, and the original `AdmissionRefused` is re-raised once the budget is spent so the caller can report the parcel as unreached. |
| `backend/app/services/deploy.py` (new) | `fetch_deployed_version` → `DeployedVersion(sha, built)`. The health-endpoint read that `requeue_parcels.py` already did, lifted so two callers share one implementation. |
| `scripts/revalidate_landsat.py` | Waits instead of aborting (`:235-241`); `--max-wait-minutes` (`:166`, default 60); `--skip-swept-since` / `--since` (`:179-190`); unreached report to stderr and `sys.exit(1)` (`:262-273`); `landsat_parcels` and `swept_since` take a session so they are testable. |
| `scripts/requeue_parcels.py` | Same wait and `--max-wait-minutes` (`:213, :255-262`); `_fetch_deployed_sha` now delegates to `app.services.deploy` (`:111-119`). |
| `scripts/requeue_empty_property.py` | Same wait, flag and report (`:110, :143-150`). |

### The wait, precisely

Poll every 5 s (`WAIT_POLL_SECONDS`, `admission.py:78`), log each wait with
depth, cap and remaining budget, and stop at `--max-wait-minutes`
(default 60). On exhaustion the script prints every parcel it did not
reach, to stderr, and exits 1 — so a half-run sweep cannot be read as a
complete one from an exit code, which is how the 2026-08-25 run's
truncation was only discovered by counting rows afterwards.

The kill switch is deliberately not waited out. It is off because an
operator turned it off, and a script that waits an hour on it is a script
that hides a deliberate stop.

### Item 3, and where it deviates

`--skip-swept-since <sha>` excludes parcels whose **most recent
`complete`** request was created at or after a cutoff. "Most recent"
rather than "any": a parcel swept under the new code and re-run under
something older has not been swept.

Since 1(c) found no SHA in the schema, the SHA is resolved the way the
prompt directed — against the running API's `/api/v1/health`, the same
endpoint `requeue_parcels.py`'s gate reads — and the cutoff is that
image's `built` time. Two things follow, both stated in the script's
docstring rather than left to the operator:

1. **It only resolves the SHA that is currently deployed.** A mismatch is
   a refusal, not a warning: skipping parcels against a deploy that is not
   running would silently drop them from the sweep.
2. **`built` is the image build time, not the rollout time.** CI stamps it
   at `docker build` (`.github/workflows/deploy.yml:119`,
   `Dockerfile.fly:39-42`); the machine starts serving minutes later. A
   request created in that gap ran against the *previous* code and will
   still be skipped.

**Deviation:** the prompt offered `--since <ISO timestamp>` as the
fallback "if you cannot make this reliable"; both are implemented, as a
mutually exclusive pair. `--skip-swept-since` is the ergonomic path and
`--since` is the exact one, because the gap in (2) is real and unfixable
from inside the container — nothing the process can read distinguishes
build time from rollout time. Offering only the convenient flag would
have buried a known unsoundness behind the flag most likely to be used.

**Deviation:** the shared wait lives in `app/services/`, not in a
`scripts/` sibling module. Scripts are loaded by path in tests
(`test_requeue_parcels.py:25-40`), so a sibling import would not resolve
under pytest; and `wait_for_admission_slot` belongs next to the
`inflight_depth` it must agree with.

**Deviation:** an early draft rolled the session back before each depth
poll, to guarantee a fresh snapshot. It made two tests fail by discarding
the fixture's committed rows, and the guarantee was unnecessary:
observing another process's commits mid-transaction is a READ COMMITTED
property, which is Postgres's default and what production runs. The
rollback is gone and the assumption is a comment at the poll site
(`admission.py:114-120`) — if the isolation level ever changes, that loop
spends its whole budget without ever seeing the drain.

---

## 3. Tests

**483 passed**, 14 added (471 → 485 collected).

Two failures, both pre-existing and environmental, confirmed by running
the same two tests on a stashed tree:

- `test_health.py::test_health_survives_missing_build_identity` — the dev
  compose file sets `GIT_SHA=dev`, so `Settings()` never sees "unknown".
- `test_workflow_pins.py::test_every_action_is_pinned_to_a_commit_sha` —
  `.github/` is not mounted into the API container.

`ruff check app/ tests/` clean; `ruff format --check` clean over `app/`,
`tests/` and the three changed scripts; `mypy app/` clean (46 files) and
clean over the three scripts. Five pre-existing ruff findings in
`scripts/seed_featured.py`, untouched and outside `make lint`'s scope.

### Added

| Test | Asserts |
|---|---|
| `test_wait_returns_once_a_slot_opens` | one poll, one nap, `True` once the queue drains |
| `test_wait_gives_up_when_the_budget_runs_out` | `False` after the budget, and exactly the naps the budget allowed |
| `test_wait_does_not_ride_out_the_kill_switch` | `False` immediately, zero naps |
| `test_waiting_create_retries_after_a_refusal` | **the fix, end to end**: a real refusal costs one wait, then the request is created |
| `test_waiting_create_raises_once_the_budget_is_spent` | `AdmissionRefused(reason="queue_full")` re-raised |
| `test_waiting_create_does_not_wait_out_the_kill_switch` | `kill_switch` raises with zero naps |
| `test_swept_since_excludes_only_parcels_completed_after_the_cutoff` | fixtures either side of the cutoff, including a parcel whose *latest* complete request predates it |
| `test_swept_since_ignores_requests_that_did_not_complete` | `failed` and `queued` do not count as swept |
| `test_resolve_cutoff_*` (3) | matching SHA returns `built`; mismatched SHA and missing build time both refuse with exit 1 |
| `test_wait_budget_exhausted_names_the_parcels_not_reached` | exit 1, the reached parcel absent from the report, both unreached parcels named, and the sweep stopping at the refusal rather than skipping past it |
| `test_a_sweep_that_reaches_every_parcel_exits_cleanly` | no report, no non-zero exit |
| `test_the_wait_deadline_is_passed_through_from_the_flag` | `--max-wait-minutes 90` becomes `monotonic() + 5400` |

### Delete-the-fix, both halves, actually run

| Reversion | Result |
|---|---|
| Replace the `while True` / `except AdmissionRefused` body of `create_queued_request_waiting` with a bare `return _create_queued_request(db, parcel_id)` | `test_waiting_create_retries_after_a_refusal` **fails** (`assert [] == [1.0]` — no wait was taken); 18 others pass |
| Delete the `except AdmissionRefused` arm from `revalidate_landsat.py`'s enqueue loop | `test_wait_budget_exhausted_names_the_parcels_not_reached` **fails**; 7 others pass |

Both reversions were applied to the working tree, run, and reverted.

---

## 4. UNVERIFIED register

1. **The fix has never met a real refusal.** Every admission test drives
   `AdmissionRefused` from a fixture queue or a stub. Nothing here has
   been run against production, by constraint. The first real evidence
   will be the completion sweep's log carrying `Waiting for an admission
   slot` lines with a depth of 30.
2. **The 60-minute default is a guess.** The 2026-08-25 sweep drained 30
   parcels in 415 s, so 154 parcels at that rate is ~35 min of waiting —
   the default has roughly 2× headroom. It is not calibrated against a
   slow worker, a Census stall, or a parcel that takes minutes rather
   than 27 s.
3. **`--skip-swept-since` has not been exercised against a real
   `/api/v1/health`.** The three `resolve_cutoff` tests stub
   `fetch_deployed_version`; only `requeue_parcels.py`'s pre-existing gate
   tests exercise the HTTP path, and those stub `httpx.get`.
4. **The build-to-rollout gap is unmeasured.** It is asserted to be
   "minutes" from the shape of the CI job, not from a timing.
5. **Two API machines mean two `/api/v1/health` answers.** Both run the
   same deploy in normal operation; mid-rollout they need not. The gate
   reads whichever machine answers.
6. **The polling wait competes with the request path.** A user's search
   arriving while a sweep is waiting takes the slot the sweep is waiting
   for, and the sweep waits longer. That is the correct priority, but
   it is untested and unbounded.
