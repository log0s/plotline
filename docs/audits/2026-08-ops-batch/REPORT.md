# Retry/ops batch — report

2026-08-27. Five upstream clients that treated a retryable error as terminal,
or converted an error into an empty success. One theme: **an exhausted retry
is a failure, and a failure is never a smaller success.**

Five commits, on `main`, **not pushed**:

| commit | item |
|---|---|
| `70437e6` | N1 — SAS signing retries 5xx and transport errors |
| `8a86fad` | N2 — census retry inside a bounded budget |
| `533bc3b` | ArcGIS 429 branch |
| `2c3f468` | Socrata 404 no longer collapses to `[]` |
| `6daf621` | N5 — topo host allowlist, verification and tests |

A sixth carries this report, `PREDICTION.md`, and the STATUS.md rows.

Deploy state: production API and worker both run `GH_SHA=5f3aa7d`
(`fly image show`, 2026-08-27). **None of the five is deployed.** Everything
below describes code, not running behaviour.

Checks, in the api container (`uv sync --locked` is what CI runs; see
*Deviations* for why the container and not the host): `ruff check`,
`ruff format --check`, `mypy app` clean; **619 passed, 7 skipped**, up from
590 at the batch's start.

---

## 1. N1 — `_sas_get` retry set aligned with the vendor's

**Before.** `stac.py` branched on `resp.status_code != 429` and called
`raise_for_status()` on the spot, and `httpx.RequestError` was never caught
inside the loop at all. A 503 from `/api/sas/v1/token/...`, or a reset
connection, failed on the **first** attempt with none of the four attempts,
the semaphore, or the wait budget applying. `_validate_asset` returned the
reason, `_validate_selection` read it as "item is broken" and walked every
same-year candidate against the same unhealthy endpoint, then dropped the
period under a task that still ended `complete`.

**The SDK policy, read from source.** `planetary_computer/sas.py`
(github.com/microsoft/planetary-computer-sdk-for-python, `main`, fetched
2026-08-27):

```python
retry = urllib3.util.retry.Retry(
    total=retry_total,                   # default 10
    backoff_factor=retry_backoff_factor, # default 0.8
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = requests.adapters.HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)
```

Mounted on both schemes, so it covers the token endpoint Plotline calls. This
matches SOURCE-LANDSCAPE §5.2 exactly; the fetch was to confirm the set and
the mount, not to discover them.

**After.** `stac.py:254` `_RETRYABLE_SIGN_STATUSES = frozenset({429, 500, 502,
503, 504})` — the vendor's set verbatim. `stac.py:259-263`
`_RETRYABLE_SIGN_TRANSPORT = (ConnectError, ReadTimeout, RemoteProtocolError)`
— deliberately narrower than `httpx.RequestError`, which would also cover
`UnsupportedProtocol` and `InvalidURL`, our own bugs. 4xx other than 429 stays
terminal. The loop is `stac.py:367-450`.

Attempt count (`pc_signing_attempts`, 4) and the budgets are unchanged: we do
not take the SDK's ten attempts, because the SDK has no deadline behind it and
a tile request does.

**Jitter.** `stac.py:269-274`, upward-only by ≤25%. Applied **after** the
budget decision and clamped to what the budget has left
(`min(_jittered(wait), wait_budget - spent)`). That ordering is not cosmetic:
jittering first turns the real production case — a 54 s `Retry-After` under
the 60 s batch budget, 2026-08-12 — into a give-up. `Retry-After` is honoured
and never undercut.

**Budget semantics changed, deliberately — see *Deviations*.** `wait_budget`
now bounds *elapsed* time (sleeping and waiting alike) rather than sleep alone.

### Worst-case request-path timing after N1

The constraint was that a request-path tile still gives up inside its ~30 s
end-to-end budget. Traced:

- `_get_sign_client` is built with `_SIGN_CLIENT_TIMEOUT_S = 10.0`
  (`stac.py:237`), now a named constant precisely so this arithmetic and the
  client cannot drift apart.
- A retry attempt is started only while `spent + wait <= wait_budget`. With
  `SIGN_WAIT_REQUEST = 2.0`, every attempt after the first begins at ≤ 2 s
  elapsed.
- The final attempt may run the full client timeout.

**Worst case in `_sas_get` on the request path = 2 s + 10 s = 12 s**, and at
most 4 attempts regardless.

| | before N1 | after N1 |
|---|---|---|
| 429 storm (fast responses) | ≈ 1–3 s | ≈ 1–3 s (unchanged) |
| 503 storm (fast responses) | ≈ 0 s, raises attempt 1 | ≈ 1–3 s |
| signer hanging (timeouts) | 10 s, raises attempt 1 | ≤ 12 s |
| *(had the budget kept counting sleep only)* | — | *up to 42 s — does not fit* |

Downstream: `_proxy_cog_tile` (`api/imagery.py:487-514`) signs, then calls
Titiler behind a 30 s client timeout. End-to-end worst case moves from
10 + 30 = 40 s to 12 + 30 = 42 s — **+2 s**, against +32 s had the budget
stayed sleep-only. The frontend's ~30 s AbortSignal already cut the 40 s case
short; nothing about that changes in kind.

### Ledger reason mapping — confirmed

`signing_failure_reason` (`stac.py:1134`) is unchanged in behaviour and now
accurate in its docstring: 429 → `sign_429`, 5xx → `sign_5xx`,
`TimeoutException` → `read_timeout`, else `connect_error`. `ReadTimeout` is a
`TimeoutException`, so a hung signer records `read_timeout`, not
`connect_error`. `RemoteProtocolError` records `connect_error`. Tested at
`tests/test_stac.py::test_signing_failure_reason_splits_429_from_5xx` and
end-to-end through `check_landsat_item` at
`::test_validation_records_sign_5xx_for_a_dead_signer`.

The reason is only reached once the retries are exhausted, which is the point:
`sign_5xx` now means "the signer stayed down for every attempt the budget
allowed", not "the signer blinked once".

### Tests

New: 503-then-200 succeeds; each of 500/502/503/504 retried (parametrised);
persistent 503 raises with `503` in the message and maps to `sign_5xx`; a 403
does not retry and does not sleep; a dropped connection retries; an
`UnsupportedProtocol` does not; a timed-out attempt spends the request budget
(one attempt, no sleep, `read_timeout`); the batch budget still retries a
timed-out attempt.

Changed: four existing tests asserted exact sleep values and now assert the
jitter range via `_assert_jittered`.
`test_failed_mint_does_not_wedge_the_container` needed
`pc_signing_attempts` ConnectErrors instead of one — a single dropped
connection no longer fails a mint, which is the fix.

---

## 2. N2 — census retry

**Before.** `census.py` issued one `GET` and converted any `httpx.HTTPError`
straight into `CensusApiError`. No attempt loop, no backoff, no
retryable/permanent distinction. The only pacing on the path was
`asyncio.sleep(0.5)` between years, which is politeness. This is the mechanism
behind M4 occurrence 3: four `httpx.ReadTimeout`s cost a Maricopa parcel its
acs5 2021 and decennial 2020 rows, and not one was retried.

**After.** `CensusFetcher._get_with_retry` (`census.py:414`), called from
`_request`. 3 attempts (`census.py:35`) over `ReadTimeout`, `ConnectError`
(`census.py:33`) and `{500, 502, 503, 504}` (`census.py:28`), jittered
exponential backoff honouring `Retry-After`.

**4xx stays terminal.** `CensusHttpStatusError` from `e6afa9b` exists so a
dead `1990/dec/sf1` reaches the ledger as `failed`/`http_404` instead of
absence; retrying a settled answer would only spend the budget on it.

**The per-request deadline, and the task limit it is sized against.**
`_RETRY_BUDGET_S = 65.0` (`census.py:50`), same rule as `_sas_get`: an attempt
starts only while elapsed time leaves room for the wait.

- per attempt: `census_api_timeout = 30.0` (`config.py:56`)
- per logical request: 3 × 30 s + ~3 s backoff = **93 s**
- per census task: 9 logical requests (3 `DECENNIAL_YEARS` + 6 `ACS5_YEARS`)
  = **~841 s**, plus 8 × 0.5 s pacing
- the limit it must fit: `soft_time_limit=1800`, `time_limit=2100`
  (`tasks/timeline.py:1608-1609`)

Census runs concurrently with the imagery sources, not after them, so 1800 s
is the number it has to fit inside. `test_retry_budget_keeps_the_census_task_
inside_its_time_limit` pins the arithmetic to both constants, so moving either
breaks a test rather than a production run.

The ACS variable-drop loop (`_request_dropping_unknown`) can issue up to 12
requests for one year, but only a 400 with an unknown-variable body drives it,
and a 400 is not retried — so it cannot multiply against the retry budget.

**Ledger split.** An exhausted transport failure raises `CensusApiError` with
the `httpx` exception on `__cause__`, which `_census_failure_reason`
(`tasks/timeline.py:166-183`) reads as `read_timeout` — the Crawford shape. An
exhausted 5xx raises `CensusHttpStatusError` and becomes `http_503`. Both
tested.

---

## 3. ArcGIS 429

**Before.** `arcgis.py` had no 429 branch. A 429 fell through the generic
non-200 path and became an `ArcGISError` on the first try. Esri acknowledges
server-side rate limiting on hosted feature services with no published number
(SOURCE-LANDSCAPE §0.2, §5.6); Denver and Adams both run on hosted services,
and R4/R5 would add traffic to the same client.

**After.** `arcgis.py:110-143`. On 429: sleep `Retry-After` capped at 20 s
(`_RETRY_AFTER_CAP_S`, `arcgis.py:32`) or a jittered exponential backoff, up
to 3 attempts (`arcgis.py:27`), **inside the caller's existing `timeout`**
(30 s by default) rather than extending it — an attempt starts only while
`spent + wait <= timeout`. An unclearing 429 raises `ArcGISError` naming the
status (`arcgis.py:138-143`).

5xx and transport failures are unchanged: still terminal, still one failed
query. That is a scope choice, recorded rather than assumed — see *Deviations*.

### The rollup, checked rather than assumed

H4's rule at `tasks/timeline.py:1289-1302`: the property task is marked
`failed` only when `queries_failed == queries_attempted` and that count is
non-zero. There is **no `partial` status for a property task** — `partial`
exists only at the request level (`aggregate_request_status`, folding the
per-source task rows).

So, precisely:

- A 429-exhausted query on Adams (1 query) → `all_queries_failed` → task
  **`failed`**. Confirmed by test.
- A 429-exhausted query on Denver (2 permit queries) with the other
  succeeding → `queries_failed=1`, `queries_attempted=2` → task **`complete`**,
  with `items_found` reflecting only the surviving query. Confirmed by test.

**The second case is a real gap and is not fixed by this batch.** One
throttled Denver permit layer thins the result set and the task row says
`complete`. It is recorded in STATUS.md as a new finding rather than left in
this report. What the batch does change is that the query is now *counted* as
failed instead of returning rows-that-were-never-fetched, so a future
partial-status rule has something to read.

---

## 4. Socrata 404

**Before.** `socrata.py:73-78` answered a 404 with `[]`. `_collect` then
counted the query as a success with no rows and the property task completed
with zero. The 4x4 resource ids in `county_adapters.py` are string constants —
a retired or renamed dataset is exactly the failure mode this hid.

**After.** The special case is deleted; a 404 falls through to the generic
non-200 raise (`socrata.py:80`), with a comment at the site saying why.

### Grep for the shape

`grep -rn "return \[\]" backend/app/services/ backend/app/api/` — every hit,
with a verdict:

| site | verdict |
|---|---|
| `services/socrata.py:78` | **the finding. Fixed in `2c3f468`.** |
| `api/geocode.py:80`, `:83` | Same shape (Photon `RequestError` and `HTTPStatusError` → `[]`). This is **N4**, explicitly out of this batch — it ships with L8 in the frontend pass. Unchanged, and left recorded. |
| `services/demographics.py:246` | `compute_subtitles([])` returning `[]`. A pure function's early return on empty input, not a status. Not the shape. |

Also checked directly, not by grep: `arcgis.py` and `ckan.py` have no
status-to-empty-list branch — every non-200 raises. All five county adapters
were read; the `return SourceFetchResult()` sites (`county_adapters.py:230`
Denver sales, `:328` Adams sales, `:578` Santa Clara sales) are **zero
attempts**, documented as "no public API", which the dataclass docstring
already distinguishes from both success and failure. Correct as they stand.

### What "complete with zero" now means for property, per county

Property has no per-year ledger (m3-design §6), so the task status is the whole
record. After this batch:

| county | platform | `complete:0` means | can the adapter tell? |
|---|---|---|---|
| New York | Socrata | portal answered 200 with no matching rows | **yes** — 404 and every other non-200 now fail the query |
| Denver | ArcGIS | *at least one* query answered 200 with no matching rows | **partly** — a failed query is counted but does not change the task status unless *all* fail |
| District of Columbia | ArcGIS (7 layers) | same as Denver, over 7 layers | partly, same caveat, and the more layers the weaker the signal |
| Adams | ArcGIS | the one query answered 200 with no features, **or** returned rows the address matcher rejected | **no** — the raw/matched split is only in the log line `"Property events filtered"` |
| Santa Clara | CKAN | portal answered 200 with no matching rows | yes — CKAN never collapsed a status |

The one genuinely undistinguished case left is **rows returned but all
rejected by the address matcher**, which affects every county and is invisible
in the database. Filed in STATUS.md.

---

## 5. N5 — `prd-tnm` host allowlist

**The premise was already satisfied.** `prd-tnm.s3.amazonaws.com` is on the
allowlist at `stac.py:293`, added by `52b0223` (2026-08-22, security audit P5),
and the STATUS.md N5 row already records that resolution. `52b0223` also routed
all five stored-URL paths through one check — `_refuse_unlisted_host`
(`api/imagery.py:354`), called at `:486` for the COG tile path (NAIP,
Sentinel-2, **usgs_topo**) and `:689` for warmup. Per the investigate-first
norm: reported, not re-implemented.

**Production verification (read-only, 2026-08-27).** Distinct hosts over
`cog_url`, `thumbnail_url` and `additional_cog_urls` for every `usgs_topo` row
in `imagery_snapshots`:

    topo rows: 1183
    prd-tnm.s3.amazonaws.com  1183

One host, 1183 URLs, and it is the allowlisted one. No other host appeared, so
there was nothing to stop for.

**What was actually missing: the test.** `test_stac.py` covered
`is_allowed_upstream_url` as a function; nothing covered the topo tile route,
which is where the check matters most — usgs_topo calls `_proxy_cog_tile` with
`sign=False` (`api/imagery.py:634`), so the URL TNM handed us reaches Titiler's
`url=` with no other inspection at all. `6daf621` adds both halves: an unlisted
host 502s without calling Titiler, and the real TNM host is served with the URL
passed through.

---

## 6. Reversions observed (delete-the-fix)

Every item was verified by removing the fix and watching the new tests fail.

| item | what was reverted | result |
|---|---|---|
| N1 | `_RETRYABLE_SIGN_STATUSES` → `{429}`, `_RETRYABLE_SIGN_TRANSPORT` → `()` | **9 failed**, 93 passed |
| N2 | `_RETRY_ATTEMPTS` → 1 | 2 failed — *insufficient*, see below |
| N2 | `_get_with_retry` replaced by the pre-N2 single `GET` | **4 failed**, 47 passed |
| ArcGIS | `_RETRY_ATTEMPTS` → 1 | **3 failed**, 19 passed |
| Socrata | `if resp.status_code == 404: return []` restored | **2 failed**, 22 passed |
| N5 (check) | `_refuse_unlisted_host`'s allowlist call made unconditional | **1 failed** (the refusal test) |
| N5 (host) | `prd-tnm.s3.amazonaws.com` removed from the allowlist | **2 failed** (the positive control, and the existing production-rows test) |

The N2 row is recorded honestly rather than dropped. Setting `_RETRY_ATTEMPTS`
to 1 failed only 2 of the 4 new tests, because two of them assert
`await_count == _RETRY_ATTEMPTS` — they follow the constant. Deleting the retry
machinery outright failed all 4, which is the real standard. The two
constant-following assertions are still worth keeping (they check the loop runs
the configured number of times), but they are not what makes the fix
falsifiable, and the reason-mapping assertions beside them are.

---

## 7. Deviations from the batch prompt

1. **`wait_budget` now bounds elapsed time, not sleep time** (`stac.py:367`).
   The prompt says the budget split stays and N1 widens *which* statuses retry,
   not how long. The constants are untouched and the split is intact, but
   counting sleep alone stopped being equivalent the moment a `ReadTimeout`
   became retryable: a timed-out attempt costs 10 s of wall clock and no sleep,
   so four of them would have run 40 s on a route with ~30 s end to end. The
   new rule is strictly tighter than the old one (elapsed ≥ sleep), and it is
   what makes the "give up inside the budget" requirement true rather than
   nominal. Called out because it changes a documented meaning.

2. **ArcGIS retries 429 only, not 5xx.** The prompt scoped it to a 429 branch
   and that is what shipped. An ArcGIS 503 is still terminal on the first try.
   Recorded in STATUS.md as a known, accepted asymmetry with the signing path
   rather than left as an oversight.

3. **Item 5 was verification, not implementation.** See §5.

4. **Tests ran in the `api` container, not on the host.** `backend/.venv` on
   this machine is root-owned and built for the container's interpreter
   (`.venv/bin/python` is a dangling symlink), so `uv sync` cannot rebuild it,
   and the host has no `libpq`, so `psycopg2` will not build into a fresh venv
   either. `docker compose exec -T api uv run pytest` runs the same
   `uv.lock`-resolved environment CI builds. **No dependency changed in this
   batch, so `uv.lock` is untouched.** Cleaning up the root-owned `.venv`
   needs `sudo` and is the owner's call.

5. **No `partial` for a thinned property task.** §3 explains; filed rather
   than fixed, because inventing a fourth task status is a design decision, not
   a retry fix.

---

## 8. UNVERIFIED register

- **The SDK's default `retry_total` and `retry_backoff_factor`.** Read from
  the fetched `sas.py` as 10 and 0.8. The `status_forcelist` and the
  double-scheme mount were quoted verbatim; the defaults come from the same
  read but are not what this change adopts, so they are cited for context
  only. UNVERIFIED against a pinned release tag — the fetch was `main`.
- **That Planetary Computer's signing endpoint actually emits 5xx.** The
  ledger has recorded zero `sign_5xx` and zero `sign_429` rows, ever. The
  case for retrying 5xx rests on the vendor's own client, on Azure Blob's
  documented per-account 503/500 throttling (SOURCE-LANDSCAPE §5.7), and on
  the 2026-08-12 429 storm — not on an observed 503 from this endpoint.
- **That any current NYC Socrata 4x4 returns a 404.** Not probed; no network
  call was made to `data.cityofnewyork.us`. The fix is insurance. See
  PREDICTION P-6.
- **Why Adams returns empty.** §4 and PREDICTION P-7 narrow it to a 200 with
  no features *or* rows rejected by the address matcher, from the task rows
  alone. The ten-minute manual portal check the STATUS.md row asks for was
  **not** performed — it needs a live query against the Eye On Adams service
  with a real Adams address.
- **Whether Denver's one `failed` property task was a 429.** Cause not
  determined; the task row carries only the message.
- **Every timing figure is arithmetic, not measurement.** The 12 s request-path
  bound, the 93 s per-request census bound and the ~841 s task bound are
  derived from constants and verified by tests against those constants. No
  outage was reproduced.
- **The whole batch is undeployed.** Nothing here has been observed running.
