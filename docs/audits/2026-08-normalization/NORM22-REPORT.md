# NORM-22 — startup mint for SAS container tokens

Branch `norm22-startup-mint`, off `5aa24ff2706e791c41edd55e6b9e9a3ecaefd376`.
Not merged, not pushed, no production access of any kind — per the branch
prompt. This session ran in parallel with a separate production session on
`main`; nothing here touches that session's work.

## 0. Scope, stated honestly, up front

This closes the **deploy-triggered instance** of the NORM-22 class, not the
class. A sustained 429 storm arriving mid-traffic still hits the request
path's 2.0 s `SIGN_WAIT_REQUEST` wall — that is O1 act two / G4 territory,
untouched here. **No document from this session may be cited as evidence the
request path survives 429 storms.**

## 1. The premise, checked before building — and corrected

The prompt's mechanism, quoting STEP3-PROD-REPORT.md §5/F2 and
STATUS.md's NORM-22 row: *"a deploy empties the in-process SAS token cache."*
Reading `app/services/stac.py` before writing any code showed this claim
does not match the code that was live at incident time.

**The container-token cache is Redis-backed, not in-process.**
`_cached_container_token` reads and `_mint_container_token` writes
`get_async_redis()` under key `sas-token:{account}/{container}`
(`stac.py:499-543`, pre-existing). The only in-process state near this path
is `_token_flights` (`stac.py:514`), which coalesces *concurrent* mints —
it holds no token and is irrelevant to a cold cache across a deploy.

This Redis-backing predates the incident, not just this session:
`e8c857c` ("cache container tokens against their own expiry") and `2168124`
("single-flight the container-token mint per container") are both ancestors
of the deployed incident sha:

```
$ git merge-base --is-ancestor e8c857c c96dbf8 && echo yes
yes
```

Redis is provisioned as a separate Fly app (no `redis` service in
`fly.toml`/`fly.worker.toml`; `REDIS_URL` is an external secret), so an
API/worker deploy does not restart or flush it. **"A deploy empties the
cache" cannot be the literal mechanism** for a cache that lives outside the
process the deploy restarts.

**What the incident's own timeline is more consistent with:** PC container
tokens are cached ~45 minutes (margin-adjusted TTL, `_container_token_ttl`,
`stac.py:615-632`). This is a low-traffic app (189 parcels, no evidence of
steady tile traffic — STEP3-PROD-REPORT.md §1c notes "no user traffic in the
window"). A deploy's own post-deploy smoke/health traffic is a
disproportionately likely candidate to be *the first request* after a
container's token has sat idle past its TTL — not because the deploy did
anything to the cache, but because deploys are reliably followed by traffic
in an app that otherwise may go tens of minutes without any. That reframes
the class as **"first request after an idle period ≥ token TTL,"** of which
post-deploy is the highest-probability instance in this app's traffic
profile, not a mechanistically distinct one.

**This does not change the remedy.** A startup mint into the same
Redis-backed cache the request path reads guarantees a warm token exists
before post-deploy traffic arrives, regardless of *why* the previous token
was cold. It closes the observed window under either mechanism. What it
changes is the framing that should carry forward: the risk is
idle-period-shaped, and "the next deploy" is a proxy for "the next idle
window," not its exclusive trigger.

**Corrected and annotated, not silently fixed** (frozen docs are annotated,
never edited): STEP3-PROD-REPORT.md gets a dated "Later:" note after F2;
STATUS.md's NORM-22 row (the living ledger) is appended with the fix and
this correction.

## 2. Container-set derivation — three, not four

Design requirement 1 asked to derive the set from the code rather than trust
"four." It is **three**:

| Account | Container | Source |
|---|---|---|
| `naipeuwest` | `naip` | Only NAIP collection queried (`extract_cog_url`, `stac.py:1090`); confirmed in production mint logs (STEP3-PROD-REPORT.md §5, BOUNDARY-BASELINE.md §3, STATUS.md G7 row) |
| `sentinel2l2a01` | `sentinel2-l2` | Only Sentinel-2 collection queried is `sentinel-2-l2a` (`stac.py:1109`, `tasks/timeline.py`); container name from production evidence below |
| `landsateuwest` | `landsat-c2` | `LANDSAT_BLOB_CONTAINER` constant, `stac.py:321` |

`_container_token`'s own docstring (`stac.py:549-551`) establishes "one PC
collection maps to one container." Four collections are queried in total
(`extract_cog_url`'s three PC/STAC branches plus `usgs-historical-topo` in
`tasks/timeline.py:972`), but USGS topo is a TNM record served from
`prd-tnm.s3.amazonaws.com` (S3, not an Azure blob container — see
`ALLOWED_UPSTREAM_HOSTS`), so `_blob_container` returns `None` for it and it
never reaches `_container_token`. Exactly three collections resolve to a PC
blob container — landsat, naip, sentinel-2-l2a. NAIP and
Sentinel-2 have no named container constant (unlike Landsat); their
containers only ever appear inside live STAC item hrefs via
`_blob_container`. Absent a constant, the container names below were
cross-checked against production evidence rather than guessed.

**A real naming discrepancy, resolved with evidence, not judgment call.**
STEP3-PROD-REPORT.md §5's own mint-log excerpt reads
`sentinel2l2a01/sentinel2-l2a` (trailing "a"). Every other production
reading of this container disagrees: `BOUNDARY-BASELINE.md:154,409,451` and
STATUS.md's G7 row both say `sentinel2-l2` (no trailing "a"), across two
independently-captured measurement sessions on 2026-08-12, and
`test_stac.py`'s existing single-flight tests (`_SINGLE_FLIGHT_CONTAINERS`,
predating this batch) use `sentinel2-l2` as well. One report has a typo; the
container name used here is `sentinel2-l2`, on the weight of independent
corroboration. **If this is wrong, the consequence is silent and total**:
`STARTUP_MINT_CONTAINERS` would pre-warm a Redis key
(`sas-token:sentinel2l2a01/sentinel2-l2`) the request path never reads
(because `_blob_container` derives the real container from the live href,
`sentinel2l2a01/sentinel2-l2a`, and builds a different cache key) — the
startup mint would run, log success, and do nothing. This is exactly the
class of failure the delete-the-fix test standard is supposed to catch, and
it did not have to, because the real container name was confirmed against
production evidence rather than assumed. Anyone revisiting this: confirm
against a fresh production mint log line before trusting either spelling.

`STARTUP_MINT_CONTAINERS` (`stac.py`, new) holds these three, with the
derivation and the correction written as a comment at the constant.

## 3. Design

**Where it runs.** `app/main.py`'s `lifespan`, immediately after the
existing `"Plotline API starting"` log line, calls
`stac_service.schedule_startup_mint()` — synchronous, returns immediately.
Only the API process gets this. The worker was deliberately not wired: every
worker call site already passes `SIGN_WAIT_BATCH` (60 s), which already
absorbs a throttled re-mint the way this fix gives the API's boot path room
to as well — there is no fragile-budget window on the worker to close.

**Boot safety.** `schedule_startup_mint()` fires one `asyncio.create_task`
per container and returns without awaiting any of them — `lifespan`'s
`yield` (and the app taking traffic) is never blocked on PC being reachable.
Each task (`_mint_at_startup`) calls the existing `_mint_container_token`
with `wait_budget=SIGN_WAIT_BATCH`, so a throttled mint gets the batch
profile's retry room instead of the request path's 2.0 s. A task that still
fails (`httpx.HTTPStatusError` or `httpx.RequestError` — the two exception
types `_sas_get` can raise, per its docstring) is caught, logged as
`"SAS startup mint failed; falling back to on-demand re-mint"` with the
container label, and does nothing further: the next real request re-mints
under `SIGN_WAIT_REQUEST` exactly as it does today. No bare `except
Exception` (project standard); no custom retry loop layered on top of
`_sas_get`'s own — that already retries within its wait budget, and adding a
second retry mechanism around it would be the over-engineering the project
norms warn against.

A success logs `"SAS startup mint succeeded"` with the container label,
distinct from `_mint_container_token`'s own `"SAS container token minted"`
line (unchanged), so a deploy-window log read can grep startup-specific
events without conflating them with ordinary on-demand mints during traffic.

**Task lifetime.** `asyncio.create_task` results are held in a module-level
`_startup_mint_tasks: set[...]` with a `done_callback` that discards them —
a bare `create_task` with no reference is eligible for garbage collection
before it runs, a documented asyncio pitfall unrelated to this fix but real
enough to guard against.

**Same cache, no parallel store.** Both the startup mint and
`_container_token` build the Redis key through one new helper,
`_container_cache_key(account, container)`, extracted from the inline
f-string `_container_token` used before (`stac.py`, now shared) — no drift
risk between what the mint writes and what the request path reads. This
directly answers design requirement 3: the cache is not restructured, only
given a second writer that shares its key-construction with the existing
one.

## 4. Tests — delete-the-fix standard

All five in `backend/tests/test_stac.py`, under a new
`# ── SAS signing: startup mint (NORM-22) ──` section. All mock PC via
`_get_sign_client`/`_token_response` (existing test helpers) and Redis via a
new `_FakeRedis` (a real per-key dict, not a blanket mock — needed because
these tests specifically check that what the startup mint writes is what the
request path reads back, which a `_cache_miss_redis()` that ignores the key
argument cannot exercise). No network in any test.

1. `test_startup_mint_populates_cache_for_every_derived_container` — all
   three `STARTUP_MINT_CONTAINERS` end up minted and cached.
2. `test_startup_mint_failure_does_not_raise_and_leaves_cache_empty` — a
   429 whose advised wait (120 s) exceeds even `SIGN_WAIT_BATCH` fails all
   three mints; `asyncio.gather` on the tasks does not raise; the cache
   stays empty; three distinct `"SAS startup mint failed"` log lines appear.
   **Delete the `try/except` around `_mint_container_token` in
   `_mint_at_startup` and this fails** — the gather raises.
3. `test_startup_mint_retries_a_recoverable_429_and_still_populates_cache` —
   a 429 with a 1 s advised wait, well inside the batch budget, followed by
   a 200: the cache ends up populated. Exercises the "retries in the
   background under the batch budget" requirement using `_sas_get`'s
   existing retry logic rather than a new one.
4. `test_request_path_finds_a_pre_minted_token_without_re_minting` — **the
   load-bearing test.** Runs the startup mint to completion, records the PC
   call count, then calls `_container_token` exactly as a request handler
   would (`wait_budget=SIGN_WAIT_REQUEST`) and asserts the PC call count is
   unchanged. **Delete `schedule_startup_mint()` from `lifespan`** (or point
   the constant at the wrong container name, per §2's failure mode) **and
   this is the test that catches it** — with a cold cache the call count
   would increase by one.

`docker compose exec -T api python -m pytest tests/test_stac.py -q`: **106
passed** (101 pre-existing + 5 new). Full suite:
`docker compose exec -T api python -m pytest -q`: **736 passed, 7 skipped**
(pre-existing skips, unrelated). `make lint`: ruff check clean, ruff format
clean (one file reformatted by `ruff format` itself, `test_stac.py`), mypy
clean on 48 source files.

## 5. Local verification

`docker compose restart api` (twice-observed boot, since `--reload` fired an
extra restart on a detected file change):

```
07:50:35.416Z  Plotline API starting
07:50:35.665Z  SAS container token minted container=naipeuwest/naip ms=248
07:50:35.666Z  SAS startup mint succeeded    container=naipeuwest/naip
07:50:35.668Z  SAS container token minted container=sentinel2l2a01/sentinel2-l2 ms=235
07:50:35.668Z  SAS startup mint succeeded    container=sentinel2l2a01/sentinel2-l2
07:50:36.030Z  SAS container token minted container=landsateuwest/landsat-c2 ms=596
07:50:36.031Z  SAS startup mint succeeded    container=landsateuwest/landsat-c2
```

Real network, real Planetary Computer, real dev Redis — not mocked. All
three containers mint and log at boot, in both restarts.

Then a real Landsat tile request against a locally-seeded `parcel_scenes`
row (`34a1995e-a8c2-440e-ae0b-5b9e85e55306`, source `landsat`):

```
$ curl -s -o /dev/null -w '%{http_code}\n' \
    http://localhost:8000/api/v1/imagery/34a1995e-a8c2-440e-ae0b-5b9e85e55306/tiles/8/60/95
200
$ docker compose logs api --since 60s | grep -c "SAS container token minted"
0
```

**Zero re-mint events** on the first real request after boot — grepped, not
assumed, per the branch prompt's item 3.

## 6. Deviations from the prompt

1. **The premise correction in §1** — not itemized as a separate deviation
   in the prompt's sense of "the plan changed," since the prompt itself
   anticipated mechanism/count uncertainty ("if it isn't four, that's a
   finding... not a blocker"; "if the cache is keyed... that is a design
   finding to report"). Recorded here because it is larger than either of
   those anticipated cases: it corrects the *causal* claim in F2 and in
   NORM-16's and NORM-22's STATUS.md rows, not just a number or a key shape.
2. **No custom background-retry loop beyond `_sas_get`'s own.** The prompt's
   wording ("retries in the background under the BATCH budget") is
   satisfied by running the existing retry-bearing mint call
   (`wait_budget=SIGN_WAIT_BATCH`) inside a background task, rather than
   building a second retry mechanism around it. Simpler, and avoids two
   independent backoff policies disagreeing with each other.
3. **Container name for Sentinel-2 resolved by cross-referencing three
   independent production documents against one internally-inconsistent
   one** (§2) — flagged rather than silently picking either spelling.

## 7. What is still open

- **NORM-22's non-deploy-triggered instance** (429 storm mid-traffic) is
  unaddressed, by design — O1 act two / G4 territory.
- **Proactive token refresh ahead of expiry** (mid-traffic, not at boot) was
  explicitly out of scope per the branch prompt. A cheap shape, described
  and not built: `_mint_container_token`'s existing single-flight is already
  per-container: a periodic task (interval somewhat under the ~45 min TTL
  margin, e.g. every 30 min) that calls `_container_token` for each of
  `STARTUP_MINT_CONTAINERS` would keep entries perpetually warm the same way
  the startup mint does once, at the cost of one more long-lived background
  task per API process and PC call volume roughly 3×/hour/machine — worth
  it only if idle-period cold-starts (§1) turn out to recur outside the
  deploy window this fix already covers, which `PREDICTION-NORM22.md`'s
  next-deploy read will help judge.
- **This branch is unmerged and undeployed.** Nothing in this report is
  "resolved" in STATUS.md's deploy-honesty sense — it is a fix in the code,
  on a branch, verified locally only. The next deploy that carries these
  commits is what `PREDICTION-NORM22.md` scores.
