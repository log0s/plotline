# NORM-10 fix — split retry policy by endpoint, pace the run

Session of 2026-08-28. Scope: `scripts/enrich_synthesized_scenes.py` and
`backend/tests/test_enrich_synthesized_scenes.py` only, as the prompt
constrained. No production access; no migration, read-path, or other script
touched. Fix and tests: `f2d6cc3`.

## 1. What NORM-10 was

`ENRICH-PROD-REPORT.md` §5 (F6): the production dry run issued ~814 requests
in 28 s (~29 req/s, concurrency 6, no pacing) and 6 of 309 `/search` calls
came back 403. `_RETRYABLE_STATUSES` (`{429, 500, 502, 503, 504}`) excluded
403, so `search`'s `raise_for_status()` turned each into an `HTTPStatusError`
that `resolve_row` recorded as `error` — a throttle response read as a
permanent per-item refusal. All six replayed at a 2 s gap and returned 200
with the item the row needs: the rows were fine, the rate was not.

## 2. The fix — retry policy split by endpoint

One shared constant became two, at `scripts/enrich_synthesized_scenes.py:119`:

| Endpoint | Retryable statuses | Why |
|---|---|---|
| Item GET (`get_item`) | `{429, 500, 502, 503, 504}` — unchanged | A 403 here is the geometry audit's per-item refusal: permanent for that item, so it falls straight through to search (as before) rather than burning the retry budget on something that will never succeed. |
| Search (`search`) | `{403, 429, 500, 502, 503, 504}` | PC's `/search` answers a throttle with 403, not 429 (NORM-10). Treated as a rate-limit signal: retried with the same `Retry-After`-aware backoff as a 429. A 403 that survives `FETCH_ATTEMPTS` (4) still raises `HTTPStatusError`, which `resolve_row` records as `error` — a genuine permanent search 403, should one exist, still surfaces rather than being retried forever or swallowed as `unmatched`. |

`_request` now takes `retryable_statuses` as a required keyword argument
instead of reading one module-level constant, so each call site states its
own policy rather than inheriting one written for the other endpoint. The
comment at the constants' definition (`enrich_synthesized_scenes.py:119-129`)
cites NORM-10 and spells out why the sets differ, per the adjacent-warning
rule.

## 3. Pacing

`_request` already bounded concurrency (`FETCH_CONCURRENCY = 6`, a
`Semaphore`), but concurrency alone doesn't bound *rate* — six workers
issuing fast requests back-to-back is exactly what produced ~29 req/s.

Added: a global minimum interval between request **dispatches**
(`StacLookup._pace`), independent of the concurrency semaphore. It sits
inside the semaphore-held section of `_request`, immediately before the
`GET`/`POST`, so every attempt — including retries — is paced, not just the
first try of each row.

**Defaults:** `FETCH_CONCURRENCY` stays 6 (unchanged, geometry-audit
precedent). New `DEFAULT_MIN_INTERVAL_S = 0.2` (5 req/s), giving ~5.8x margin
under the ~29 req/s that provoked the throttle, and well above the 0.5 req/s
(2 s gap) that the replay confirmed safe — that number is known-safe but
was never a measured ceiling, so pacing at 5 req/s trades a little of that
margin for finishing in minutes rather than half an hour. Both are CLI flags
(`--concurrency`, `--min-interval-s`) so a future run can retune without a
code change; `--min-interval-s 0` disables pacing.

**Expected wall time for the production run (505 rows, ~814 requests
observed):** pacing alone puts a floor of `814 × 0.2s ≈ 163s` (~2.7 minutes)
on dispatch, since dispatches are globally serialized to 5/s regardless of
concurrency. Actual network latency is mostly absorbed under that floor —
concurrency 6 means up to 6 requests are in flight awaiting a response while
the pacer is only gating when the *next* one is sent. Call it **3-5 minutes**
end to end, comfortably inside the "minutes" the detached-run pattern already
assumes (NORM-8) and far below the client's timeout window that pattern
exists to survive.

## 4. Tests — delete-the-fix, `backend/tests/test_enrich_synthesized_scenes.py`

Four new tests exercise `StacLookup` directly (`_client.get`/`.post` are
swapped for fakes) rather than through `FakeStac`, which replaces the whole
lookup and has no retry logic of its own to get wrong:

| Test | Asserts | Verified failing with the fix reverted |
|---|---|---|
| `test_search_403_retries_and_succeeds` | A `/search` 403 followed by a 200 yields the item, and both calls happened. | Yes — reverting `_SEARCH_RETRYABLE_STATUSES` to the item set drops it to 1 call and the item is never found. |
| `test_item_403_does_not_retry_falls_through_to_search` | An item-GET 403 returns `(403, None)` after exactly one call. | Yes — adding 403 to `_ITEM_RETRYABLE_STATUSES` makes it retry 4 times and raise instead. |
| `test_search_403_exhausts_retry_budget_is_an_error` | A `/search` that 403s every time raises `HTTPStatusError` after exactly `FETCH_ATTEMPTS` calls (not swallowed, not retried forever). | Yes — same revert as the first test drops it to 1 call before raising. |
| `test_pacing_does_not_exceed_configured_concurrency` | With `concurrency=2`, 6 concurrent `get_item` calls never have more than 2 in flight at once. | Not re-verified by reverting a line (there is no single line whose removal is "no more concurrency limit" without deleting the semaphore itself, which the original tests already implicitly rely on) — this test guards the pacer addition sitting *inside* the semaphore block, not the semaphore's existence. |

Each 403-response fake sets `Retry-After: 0` so a retried request's backoff
sleep is instant rather than the 1 s default — the tests assert *that* a
retry happened, not how long it waited, keeping the suite fast (0.3-0.4s for
all 14 tests) and non-flaky. The pacing test uses `min_interval_s=0` (pacing
disabled) and an `asyncio.sleep(0)` yield inside the fake to force overlap
under `asyncio.gather`; it asserts an upper bound on concurrent calls, never
a timing value, per the prompt's no-wall-clock-assertions constraint.

The paired item/search 403 assertions sit adjacent in the test file, as
NORM-10 names them. Both were confirmed failing with the corresponding half
of the fix reverted (`_SEARCH_RETRYABLE_STATUSES` back to the item set;
separately, 403 added into `_ITEM_RETRYABLE_STATUSES`) and passing again
with the fix restored. Full suite: 14 passed, 0 failed, `ruff check` and
`mypy` clean on both files (mypy's one pre-existing `no-any-return` on
`_mosaic_ids:250` predates this change and is untouched).

## 5. Local re-run

Local `scenes` provenance: `snapshot` 1174, `enriched` 88, `mosaic_url` **0**
— the queue NORM-7's local enrichment pass already emptied. **Expected
outcome: queue 0, zero STAC requests, clean exit.** Ran:

```
docker compose exec api python scripts/enrich_synthesized_scenes.py \
    --report docs/audits/2026-08-normalization/norm10-local-dryrun.md
```

**Observed: exactly that.** `queue (provenance = 'mosaic_url'): 0 row(s)` /
`Nothing to enrich.`; SQL log shows only the three read queries
(`parcel_scenes`, `parcels`, `scenes WHERE provenance = 'mosaic_url'`), no
`get_item`/`search` calls, and the transaction ends in `ROLLBACK` — no write.
Report at `norm10-local-dryrun.md`, retrieved via `docker cp` since
`docs/` is not one of the container's bind mounts (only `./backend` and
`./scripts` are — `docker-compose.yml:56-58`).

This is the only local run that makes sense here: the local queue this
session's fix could exercise doesn't exist, so the retry-policy and pacing
changes are validated by the unit tests in §4, not by a local STAC call.
Manufacturing a synthetic queue row locally to re-trigger a 403 would not
test anything the mocked `StacLookup` tests above don't already cover more
precisely, and would touch the local DB outside what NORM-10 asked for.

## 6. What's still open

- **Production re-run is not done here.** This session had no production
  access. NORM-10 stays open in STATUS.md until a session with production
  access re-runs the dry run and it comes back clean (505 → 499 enriched + 6
  now resolving, per `ENRICH-PROD-REPORT.md` §9's next-session note), writes
  a prediction to `PREDICTION-ENRICH.md` before the execute, and runs
  `--execute` once detached (NORM-8).
- The fix is **committed, not deployed.** Fly's `plotline-api`/`worker`
  images are still on `GH_SHA=99e33f2853ca…`, the sha `ENRICH-PROD-REPORT.md`
  read at deploy-gate time; this fix's commits are ahead of that. Whoever
  runs the production re-run must first verify the deployed sha carries this
  fix (`fly image show`), the same way `ENRICH-PROD-REPORT.md` §1 did for
  migration 0016.
- NORM-9 (NAIP `resolution_m` wrong for most vintages) is unaffected by this
  batch and stays open at production scale, since it only resolves through a
  write this session did not make.
