# Z6 — `lookup_tract_at_vintage` transient failure degrades to the stored tract

Fix for `docs/audits/2026-08-second-audit/STATUS.md` row Z6, found by the
ops-batch sweep (`../2026-08-ops-batch/SWEEP-SCORECARD.md` §9.1). Fix + tests
in `4275908`, docs in this commit. Not pushed. No prod writes; item 5 below
is read-only.

## 1. The path, and the sweep's instance

`geocoder.lookup_tract_at_vintage` (`backend/app/services/geocoder.py:414`,
pre-fix) issued one `client.get`, retried only `httpx.TimeoutException` (flat
1 s sleep), and raised `GeocoderUnavailableError` on the first attempt for
everything else — `httpx.ConnectError` and any 5xx included
(`geocoder.py:427-430`, pre-fix). Its caller, `_VintageTracts.tract_for`
(`backend/app/tasks/timeline.py:1013`, pre-fix), caught every `GeocoderError`
unconditionally:

```python
try:
    resolved = await geocoder_service.lookup_tract_at_vintage(
        self._lat, self._lon, vintage, get_settings()
    )
except GeocoderError as exc:
    logger.warning(
        "Vintage tract lookup failed, using stored tract",
        extra={"vintage": vintage, "tract": self._stored},
        exc_info=exc,
    )
    resolved = None

tract = resolved or self._stored
```

`tract` is then cached per vintage and handed to the fetch loop, which writes
the census row and the ledger `ok` outcome under it — the row and the ledger
carry no trace that the tract came from a fallback rather than a resolved
lookup.

**The sweep's instance.** One `httpx.ConnectError` reached this call at
18:55:14Z on 2026-08-27, during the census task for parcel
`64a47cd8-0ff6-4250-b02a-70cb1fbe2ec1` ("2 Broadway, New York, NY 10004"),
stored tract `36061000900`. The exact `(dataset, year)` that triggered it
did not survive in the captured log line (`fly logs` dropped ~3% of the
worker stream that sweep, SWEEP-SCORECARD.md §9.1.2), but the tract identity
is enough to evaluate correctness on its own: querying production read-only
(2026-08-27), every census row this parcel has — all 9 `(dataset, year)`
rows, `acs5` 2009/2012/2015/2018/2021/2023 and `decennial` 2000/2010/2020 —
carries `tract_fips = 36061000900`, identical to the stored tract. A fresh
lookup at every geocoder-mapped vintage for this point (item 5 below,
2026-08-27) also resolves to `36061000900`. **The fallback this instance hit
was, this time, correct** — Lower Manhattan tract 900 has not moved under any
vintage the geocoder serves — which is why SWEEP-SCORECARD.md could
truthfully call it "degraded, not lost." That is luck, not a property of the
mechanism: nothing about the code path knew the fallback would be right, and
Denver 41.11 (`4ce1822`) is the standing counterexample of a point where it
would not have been.

## 2–3. Retry, and no degrade on exhaustion

`_vintage_get_with_retry` (`geocoder.py`, new) replaces the ad hoc loop
inside `lookup_tract_at_vintage`. Same shape as N2's `_get_with_retry`
(`census.py:418`, `8a86fad`): `httpx.ReadTimeout`, `httpx.ConnectError`, and
`{500, 502, 503, 504}` retry up to 3 attempts with jittered exponential
backoff honouring `Retry-After`; any other status (4xx, or a status outside
that set) raises on the first attempt via `response.raise_for_status()`. A
5xx that survives all 3 attempts, and any exhausted transport failure, raises
`GeocoderUnavailableError` with the underlying `httpx.HTTPStatusError` /
`httpx.RequestError` on `__cause__` — mirroring how `CensusApiError` carries
its cause for `_census_failure_reason`.

Retry budget (`_VINTAGE_RETRY_BUDGET_S = 45.0`, `geocoder.py`): two full
`census_geocoder_timeout` (20 s, `config.py:60`) attempts plus jittered
backoff must fit before a third attempt starts — `2*20 + jittered(1.0) +
jittered(2.0) <= 43.75s` worst case, scaling N2's own arithmetic (`2*30 +
backoff <= ~64s < 65s` budget there) down to this client's shorter timeout.

`_VintageTracts.tract_for` (`timeline.py:1003`) no longer catches
`GeocoderError` at all — it propagates. The per-year loops in
`_fetch_census_years` (`timeline.py:1078`, `timeline.py:1156`) now wrap the
`tract_for` call in its own `try/except GeocoderError`, separate from the
existing `except CensusApiError` around the fetch call:

```python
try:
    year_tract = await tracts.tract_for("decennial", year)
except GeocoderError as exc:
    failed_requests += 1
    ledger.record(
        key, "failed", _geocoder_failure_reason(exc),
        f"vintage tract lookup ({geography_vintage('decennial', year)}) via "
        f"geocoder.lookup_tract_at_vintage failed: {exc}",
        source="census_decennial",
    )
    await asyncio.sleep(0.5)
    continue
```

— no fetch, no upsert, no `ok` row for that year. `_geocoder_failure_reason`
(`timeline.py`, new, next to `_census_failure_reason`) maps the exhausted
`__cause__` to `read_timeout` / `connect_error` / `http_<status>` / `other`.

The one case that still falls back to the stored tract is unchanged and
untouched: `geography_vintage(dataset, year)` returning `None` (decennial
2000's pre-geocoder geography, Racebrook `4ce1822`) short-circuits before
`tract_for` ever calls the geocoder, so no exception is in play there at all.

## 4. Tests

`backend/tests/test_geocode.py` (unit, on `lookup_tract_at_vintage` directly,
respx-mocked):

- `test_lookup_tract_at_vintage_retries_timeout_then_succeeds` — one
  `ReadTimeout` then a 200 resolves the tract; 2 calls.
- `test_lookup_tract_at_vintage_exhausts_retries_on_repeated_timeout` — 3
  `ReadTimeout`s raise `GeocoderUnavailableError` with `httpx.ReadTimeout` on
  `__cause__`; 3 calls.
- `test_lookup_tract_at_vintage_404_is_terminal_no_retry` — a 404 raises
  immediately with `HTTPStatusError(404)` on `__cause__`; 1 call, no retry.
- Existing `test_lookup_tract_at_vintage_returns_ancestor_tract` and
  `test_lookup_tract_at_vintage_returns_none_without_tract` (pre-existing,
  unaffected) still pass.

`backend/tests/test_timeline.py`:

- `test_fetch_census_skips_year_when_vintage_lookup_fails` (rewritten from
  `test_fetch_census_falls_back_when_vintage_lookup_fails`, which pinned the
  defect as intended behaviour — see below) — an exhausted `ReadTimeout`
  (cause set on the mocked `GeocoderUnavailableError`) on every geocoder-
  mapped vintage: only decennial 2000 (no vintage) still resolves and is
  saved (`count == 1`, one `fetch_decennial` call, zero `fetch_acs5` calls,
  `upsert_census_snapshot` called once under the stored tract); the other 8
  years each write a `failed` outcome via `YearOutcomeLog.record` (patched
  with `autospec=True, side_effect=<original>` to keep behaviour while
  capturing calls) with `reason == "read_timeout"` and `detail` naming both
  the vintage (`"Census2010_Current"`) and `"lookup_tract_at_vintage"`.
- `test_fetch_census_uses_ancestor_tract_for_older_vintages`,
  `test_fetch_census_uses_county_tract_before_planning_regions` (pre-existing,
  unaffected) still pass — including the latter's decennial-2000 no-vintage
  assertion, pinning that case unchanged.

**Delete-the-fix.** Reverted item 3 (`timeline.py`'s `tract_for` back to
catching `GeocoderError` and falling back) with `git stash`, then ran
`test_fetch_census_skips_year_when_vintage_lookup_fails`: it failed, with the
old `"Vintage tract lookup failed, using stored tract"` warning firing on
every attempt — the defect, reproduced. Restored the fix (`git stash pop`);
the test passes again.

Full suite: `docker compose exec -T api uv sync --locked && python -m
pytest tests/` — **622 passed, 7 skipped** (pre-existing skips, unrelated).
`make lint` (ruff check, ruff format, mypy) — clean after `ruff format`
reformatted the two touched files.

## 5. Blast radius (read-only, production, 2026-08-27)

Method: for every `(parcel, dataset, year)` row in `census_snapshots`
(joined to `parcels` for `latitude`/`longitude`), skip rows whose
`geography_vintage(dataset, year)` is `None` (the no-vintage design gap —
not this defect). For the rest, cache one `lookup_tract_at_vintage` call per
`(parcel, vintage)` — the same caching `_VintageTracts` uses — and compare
today's resolved tract against the row's stored `tract_fips`. Paced 0.6 s
between geocoder calls. Run inside `log0s-plotline-api` via `fly ssh console
-C`, app code only, no writes.

| metric | count |
|---|---:|
| census rows examined | 1,574 |
| rows skipped (no geocoder vintage — decennial 2000) | 111 |
| distinct `(parcel, vintage)` geocoder calls made | 756 |
| geocoder errors during the scan | 0 |
| vintage yields no tract today (`no_tract_today`) | 0 |
| **mismatches** (today's tract ≠ stored tract) | **0** |

**Zero mismatches, fleet-wide, including parcel
`64a47cd8-0ff6-4250-b02a-70cb1fbe2ec1`** (the sweep's own instance, §1). No
wrong-tract row from this defect is currently sitting in production. No heal
is warranted — item 6 of the assigning prompt only calls for a
`PREDICTION.md` addendum if this count were non-zero.

This does not mean the defect was harmless in general, only that it has not
yet produced a detectable wrong row: 189 parcels is the entire fleet
(`SELECT COUNT(DISTINCT parcel_id) FROM census_snapshots` = 189), the sweep
met this failure exactly once in 69 minutes (SWEEP-SCORECARD.md §9.1), and
that once happened to land on a tract whose boundary is stable across every
vintage the geocoder serves. A future instance landing on a Denver-41.11-
shaped parcel — one where the vintage tract genuinely differs from the
current one — would not be this lucky, which is the whole reason items 2–3
exist.

## Deviations from the prompt

None. All six items completed as specified.

## UNVERIFIED register

- The exact `(dataset, year)` that the sweep's `ConnectError` hit is
  UNVERIFIED — not recoverable from the captured log line
  (SWEEP-SCORECARD.md §9.1.2 notes ~3% log loss that sweep). Worked around by
  checking every vintage for the parcel instead of the one that failed.
- Whether any parcel *outside* the 189 with `census_snapshots` rows today
  ever had a Z6-caused wrong-tract row written and later overwritten (e.g. by
  a subsequent successful fetch, or a prior heal) is UNVERIFIED — `census_
  snapshots` has no history/audit table, only current state, so an
  overwritten wrong row leaves no trace to check.

## STATUS.md

Z6 marked resolved, citing `4275908` and this report's item 5 count (zero).
See `docs/audits/2026-08-second-audit/STATUS.md`.
