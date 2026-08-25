# REMEDIATION-1 — security audit batch 1

**Date:** 2026-08-22. **Base:** `8c8907f` (audit docs, unpushed). **Commits:**
`52b0223` (Group A), `b606d18` (Group B), `6c34335` (Group C), Group D is the
commit carrying this file and the STATUS.md section. **Nothing pushed, nothing
deployed, no secret set, no production write.** Line numbers are at `6c34335`
unless stated. Every production touch is in §4 and §8.

Deviations from the brief, up front:
- `claude/SOURCE-LANDSCAPE-2026-08.md` (named for the topo host) does not exist
  in this checkout; the allowlist is derived from the live query alone (§4),
  which the brief asked for anyway.

  > **Later (2026-08-24, `a7a09f0`):** the report was committed to
  > [`docs/research/SOURCELANDSCAPE202608.md`](../../research/SOURCELANDSCAPE202608.md)
  > and the citation now resolves. §0.1 names the topo host this deviation was
  > about. The deviation stands as written — the file genuinely was absent on
  > 2026-08-22, and §4's allowlist still rests on the live query, not on this
  > document.
- B3 produced a script but **no dry-run match count beyond the candidate set**:
  the evidence predicate needs Photon, and the brief forbids running it. What
  a dry run prints is the 71 candidates (§2 SEC-5).
- Group A also adds `fail_closed` to the limiter (the G2 decision) because it
  is one constructor flag in the same file as the SEC-3 change; the
  route-level tests for it are in Group B.
- SEC-7's log half is closed as a side effect of SEC-4 (the scrubber runs at
  the task-row sinks); not widened beyond that.

## 1. Gates

### G1 — does anything outside the backend fetch a Titiler URL directly?

**No. Proceed.** Every browser-reachable URL is an API URL or a non-Titiler host:

| Path | What the browser gets | Evidence |
|---|---|---|
| Tile layers | `${apiBase}/api/v1/imagery/{id}/tiles/{z}/{x}/{y}[?cog=n]` | `frontend/src/utils/applyImageryLayer.ts:80, 92` |
| Warmup | `POST ${apiBase}/api/v1/imagery/{id}/warmup` | `frontend/src/api/imagery.ts:27` |
| `thumbnail_url` | a signed `planetarycomputer.microsoft.com` preview, not Titiler | §4 `hosts_thumb`; `Timeline.tsx:634` |
| `preview_image_url` | `/static/featured/<slug>.jpg` served by the API | `FeaturedCards.tsx:119-144`; rendered offline by `preview_renderer.py` |
| `cog_url`/`additional_cog_urls` in the listing | signed blob URLs the browser never fetches (tiles go via the proxy) | `api/imagery.py:242-272` |
| Any `titiler` string in the bundle | only the TechFooter link to developmentseed.org | `grep -rn titiler frontend/src` → `TechFooter.tsx:11` |

Titiler callers are exactly: the API tile proxy (COG and STAC), warmup (COG and
STAC), and the preview renderer — all server-side. The worker never calls
Titiler (`grep -rn titiler backend/app/tasks` → 0). So a global query-string
token never reaches a browser, and SEC-1's fix as written is right.

### G2 — which rate-limited paths can fail closed?

Read `rate_limit.py` and all five callers. Classification, now pinned by
`test_dispatching_routes_fail_closed_and_read_routes_fail_open`
(`tests/test_rate_limit.py:160`), which walks the live route table:

| Route | Limit | Creates/dispatches? | Redis-down policy | Why |
|---|---|---|---|---|
| `POST /geocode` | 10/min | parcel row + Celery run | **closed — 503, Retry-After 30** | the cost it bounds is the cost running away |
| `POST /parcels/{id}/timeline` | 20/min | Celery run (failed/never-run parcels) | **closed — 503** | same |
| `GET /geocode/autocomplete` | 60/min | no (Photon call, cache) | open | availability; SEC-8's budget is the real bound, deferred |
| `POST /imagery/{id}/warmup` | 120/min | no (Titiler header read) | open | costs Titiler CPU, not Upstash/Neon/worker; a refused warmup only slows a real first tile |
| `GET /imagery/{id}/stac` | 600/min | no (PC item fetch + 3 signs, cached) | open | called by Titiler from inside a tile render; closing it breaks Landsat tiles on every Redis blip |

Unlimited and unchanged: tile proxy, listing, `/parcels/{id}`, demographics,
events, featured — read-only and cache-backed. The admission gate (B2) does
not use Redis at all, so the *global* cap survives a Redis outage; only the
per-IP limiter is affected, and on the two dispatching routes it refuses.

## 2. Per SEC id

Delete-the-fix standard: the named test was run with the fix reverted
(exact edit noted), observed failing, then the fix restored and the full
suite re-run green. Final suite: **465 passed**, mypy clean, ruff clean.

| Id | What changed | Where (HEAD) | Regression test | Delete-the-fix observed |
|---|---|---|---|---|
| SEC-1 | `titiler_access_token` setting; `titiler_params()` appends `access_token` only when set; used at all five call sites; `TITILER_API_DISABLE_MOSAIC=TRUE` in toml; `DEPLOY-SEC-1.md` | `config.py:110`; `services/titiler.py:10-18`; `api/imagery.py:512` (COG tiles), `:584` (STAC tiles), `:681` (warmup STAC), `:704` (warmup COG); `preview_renderer.py:119`; `fly.titiler.toml:16` | `test_titiler_params_unset_is_byte_identical`, `test_titiler_params_appends_token_when_set`, `test_every_titiler_call_site_sends_the_token` (`tests/test_imagery.py:1216-1276`) | `return params` unconditionally → 2 failed, 1 passed (the unset test still passes by construction — it is the property, not the fix) |
| P5 | `ALLOWED_UPSTREAM_HOSTS` + `is_allowed_upstream_url`; gates at tile proxy, warmup, preview renderer, validation HEAD, pagination next-link | `stac.py:236-248` (constant), `:156` (next-link), `:1042` (HEAD); `api/imagery.py:354-366, 486, 687, 708`; `preview_renderer.py:102` | `test_allowed_upstream_hosts_match_production_rows`, `test_validate_asset_refuses_non_allowlisted_href`, `test_search_stac_stops_at_non_allowlisted_next_link` (`tests/test_stac.py:1753-1825`), `test_tile_proxy_refuses_non_allowlisted_cog_host` (`tests/test_imagery.py:1279`) | each gate replaced by `if False:`/`return` → the tile-proxy, validate and pagination tests each fail individually (1 failed ×3) |
| SEC-3 | key on `request.scope["route"].path`; `/warmup` 60 → 120 | `rate_limit.py:44-51, 68`; `api/imagery.py:658` | `test_rate_limit_key_uses_route_template` (`tests/test_rate_limit.py:126`) | key reverted to `request.url.path` → 2 failed, 8 passed (this test + the fail-closed test, which was reverted in the same edit) |
| G2 / SEC-6 | `RateLimit(fail_closed=True)` → 503 + `Retry-After: 30` on Redis error | `rate_limit.py:62-65, 88-97`; `api/geocode.py:190`; `api/imagery.py:65` | `test_fail_closed_limiter_returns_503_when_redis_down` (`:146`), `test_dispatching_routes_fail_closed_and_read_routes_fail_open` (`:160`), route-level `test_geocode_fails_closed_when_redis_is_down` / `test_autocomplete_fails_open_when_redis_is_down` (`tests/test_admission.py`) | flag dropped from `/geocode` → 1 failed, 1 passed (geocode test fails, autocomplete test still passes, as it should) |
| SEC-4 | `app/redact.py` (param family + URL passwords); structlog processor after `format_exc_info`; task-row sinks; geocoder messages carry status not `{exc}` | `redact.py:43-78`; `logging_config.py:35-36`; `services/imagery.py:275, 290`; `geocoder.py:127-132, 199, 327, 429` | `tests/test_redact.py` — `test_redact_removes_the_secret_value` (6 parametrised shapes), `test_logged_httpx_exception_does_not_carry_the_census_key` (real structlog pipeline, real `HTTPStatusError`, asserts the key string is **absent** from the rendered line), `test_reverse_geocode_error_message_carries_status_not_url` (real httpx MockTransport), `test_task_row_error_message_is_scrubbed` | processor line, geocoder `_describe`, and both sinks removed → 3 failed, 7 passed |
| SEC-9 | four actions pinned to SHAs | `.github/workflows/deploy.yml:25, 29, 58, 60, 75, 76, 91, 92, 105, 106` | `test_every_action_is_pinned_to_a_commit_sha` (`tests/test_workflow_pins.py`) | one `uses:` set back to `@master` → 1 failed |
| SEC-2 (B1) | served-coordinate marker on autocomplete; reverse fallback only for served pairs; Redis failure = not served | `geocoder.py:41-66`; `api/geocode.py:147-170, 218-234` | `test_geocode_refuses_coordinates_the_backend_did_not_serve`, `test_geocode_refuses_coordinates_when_redis_is_down`, `test_served_coordinates_round_trip`, updated `test_geocode_with_coords_falls_back_to_reverse` (`tests/test_geocode.py:211-322`) | check replaced with `if False:` and `address=body.address` → 3 failed of 3 selected |
| SEC-2 (B2) | `services/admission.py`: kill switch + in-flight cap, logged refusals; gates in `parcels.get_or_create_parcel` and `_create_queued_request`; quiet backfill suppression; 503 mapping in both routes | `admission.py:33-79`; `parcels.py:139`; `services/imagery.py:108, 403-409`; `api/geocode.py:267-269, 305-313`; `api/imagery.py:85-91`; `config.py:79-92`; `.env.example` | `tests/test_admission.py` (13 tests: cap boundary at 2/3 vs 3/3, terminal statuses not counted, kill switch on/off/env, dedup hit served under kill switch, new parcel refused, timeline route 202 for complete vs 503 for never-run, backfill suppressed quietly, refusal logged with reason, Redis-down per class) + `test_geocode_503s_when_admission_is_refused` | `ensure_admission` made a no-op → 6 failed, 40 passed across admission+geocode |
| SEC-5 | served display name becomes `normalized_address`; B3 script | `api/geocode.py:234`; `scripts/remove_unverified_reverse_parcels.py`; `tests/test_remove_unverified_reverse_parcels.py` (6) | `test_geocode_with_coords_falls_back_to_reverse` asserts the served name; script: `test_inconclusive_candidate_refuses_the_whole_run`, `test_execute_deletes_only_condemned_rows` | script's inconclusive guard removed → 1 failed, 5 passed |
| SEC-10 | pillow 12.2.0→12.3.0, starlette 1.0.1→1.6.0, react-router(-dom) 7.14.x→7.18.2 | `backend/uv.lock`, `frontend/package-lock.json` | full suites (465 backend; tsc + eslint + vite build frontend — there is no frontend test suite to run) | n/a |

**SEC-5, fully or prospectively?** Prospectively. B1 stops new rows with
attacker text/coordinates. It cannot clear the 71 existing reverse-path rows
(§4 `reverse_signature`), and nothing in the database distinguishes a poisoned
row from a legitimate autocomplete fallback — both have `normalized_address =
address`, both sit in a real tract. The NAIP-gate lesson applies; the script
is the instrument, with Photon as the evidence. Residual even after the
script: `parcels.address` remains the first submitter's text on every path,
which was always true of the forward path too.

## 3. Grep for the shape

**A1 — Titiler call sites** (`grep -rn "titiler_url\|/cog/\|/stac/" backend/app scripts`):
`api/imagery.py:512, 584, 681, 704` and `preview_renderer.py:119` — all five now
go through `titiler_params`. `scripts/` has no Titiler caller. Nothing left alone.

**A2 — fetches whose URL comes from a DB row or an upstream response:**

| Site | Source of the URL | Now |
|---|---|---|
| `api/imagery.py:759` Landsat STAC item GET | DB `cog_url` | already allowlisted (PC only); kept narrower than the shared set, deliberately |
| `api/imagery.py:486` tile proxy → Titiler `url=` | DB `cog_url` / `additional_cog_urls` | **gated** (502) |
| `api/imagery.py:687` warmup → Titiler `url=` | DB `cog_url` | **gated** (204, logged) |
| `preview_renderer.py:102` → Titiler `url=` | DB `cog_url` + extras | **gated** (tile skipped) |
| `stac.py:1042` validation HEAD | STAC asset href (upstream response), signed | **gated** (item not servable) |
| `stac.py:156` search pagination next link | upstream response | **gated** (pagination stops) |
| `timeline.py:486-527` topo `cog_url` persisted from TNM | upstream response | left alone at persist time: it is only ever *fetched* via the gated tile/warmup paths; gating at write would double the check |
| `api/imagery.py:221-276` listing signs `cog_url`/`thumbnail_url` | DB | left alone: signing posts the URL to PC's signer (fixed host); the browser, not us, fetches the result |
| Landsat `/stac` callback URL handed to Titiler | `api_internal_url` (ours) | left alone: not from a row or an upstream |
| Census, TNM, Photon, county portals, PC search/sign | constant hosts in code | left alone |

**A3 — Redis keys / metrics built from a concrete request path:** `ratelimit:`
(fixed); `autocomplete:{q}` (keyed on the query by design); `stac:{snapshot_id}`
and `sas-token:` (per-id caches by design); no metrics exist. Nothing else.

**A4 — places an httpx exception/request/response URL is stringified** (`grep -n "str(exc)\|{exc}\|exc_info\|titiler_body\|\.url" backend/app`):
all log paths pass through the processor at `logging_config.py:36`, so the
per-site list is about *what survives the scrub*: `api/geocode.py:169, 229, 243, 317`
(`str(exc)` in extra — scrubbed); `api/imagery.py:426, 450` (`titiler_body` —
scrubbed, SEC-7 log half); `:502, :556, :840` (`str(exc)` — scrubbed);
`timeline.py:209, 461, 593, 796, 1151, 1168` (`str(exc)` into logs and into
`error_message` — both scrubbed, the latter at the sink); `census.py:252-253`
(`exc_info` + `f"HTTP error: {exc}"` — scrubbed in the log; the exception
message itself still carries the URL until it hits a sink, acceptable);
`stac.py:639, 1057, 1076` (`str(exc)` — scrubbed); `geocoder.py:155-160`
forward path (was already status-only; `:199` RequestError branch now
`_describe`). The scrub is regex-based: it masks the *values* of the listed
parameter names and URL passwords; a secret that appears in some other shape
(a bare token in a body) is not caught — hence "at minimum" met, not "all
secrets everywhere".

**A5 — third-party actions in every workflow:** only `deploy.yml` exists.
`actions/checkout@v6` → `d23441a48e516b6c34aea4fa41551a30e30af803` (v6.1.0, 5
sites); `dorny/paths-filter@v4` → `ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d`
(v4.0.3); `astral-sh/setup-uv@v9.0.0` → `c771a70e6277c0a99b617c7a806ffedaca235ff9`;
`superfly/flyctl-actions/setup-flyctl@master` →
`ed8efb33836e8b2096c7fd3ba1c8afe303ebbff1` (= tag 1.6, `master` on 2026-08-22;
3 sites). Resolved with `git ls-remote`, not from memory.

## 4. Production queries (read-only)

Run 2026-08-22 over `fly ssh console -a log0s-plotline-api` executing a
base64 Python payload through the app's SQLAlchemy engine (the ops audit's
Appendix B method; `psql` is not in the image). Session opened with
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY; SET statement_timeout = '60s'`.

```sql
-- hosts_cog
SELECT regexp_replace(cog_url, '^https?://([^/]+)/.*$', '\1') AS host, source, count(*)
  FROM imagery_snapshots GROUP BY 1,2 ORDER BY 1,2;
-- naipeuwest.blob.core.windows.net      naip       1240
-- planetarycomputer.microsoft.com       landsat    7731
-- prd-tnm.s3.amazonaws.com              usgs_topo   959
-- sentinel2l2a01.blob.core.windows.net  sentinel2  4285

-- hosts_extra
SELECT regexp_replace(u, '^https?://([^/]+)/.*$', '\1') AS host, source, count(*)
  FROM imagery_snapshots, unnest(additional_cog_urls) u GROUP BY 1,2 ORDER BY 1,2;
-- naipeuwest.blob.core.windows.net      naip        578

-- hosts_thumb
SELECT regexp_replace(thumbnail_url, '^https?://([^/]+)/.*$', '\1') AS host, source, count(*)
  FROM imagery_snapshots WHERE thumbnail_url IS NOT NULL GROUP BY 1,2 ORDER BY 1,2;
-- planetarycomputer.microsoft.com       landsat 7731 / naip 1240 / sentinel2 4285

-- counts
SELECT (SELECT count(*) FROM parcels), (SELECT count(*) FROM timeline_requests);
-- 180, 334

-- outside_conus
SELECT count(*) FROM parcels
 WHERE NOT (longitude BETWEEN -125 AND -66 AND latitude BETWEEN 24 AND 50);
-- 0

-- reverse_signature
SELECT count(*) FROM parcels WHERE normalized_address = address;
-- 71
-- ... AND census_tract_id IS NULL  -> 0
-- count(*) FILTER (WHERE normalized_address = upper(normalized_address)) -> 111 of 180

-- throughput (FINDINGS §7's outstanding check)
SELECT count(*), avg(completed_at-created_at),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY completed_at-created_at)
  FROM timeline_requests WHERE status='complete' AND created_at > now()-interval '30 days';
-- 248, 0:06:13 mean (skewed by the 08-12 sweep's queueing), 0:00:42 median
```

Allowlist = the four `cog` hosts + `landsateuwest.blob.core.windows.net`
(Landsat band hrefs arrive inside STAC items, not rows; `stac.LANDSAT_BLOB_CONTAINER`).
`planetarycomputer.microsoft.com` covers the STAC API, item self-links, the
signer and the thumbnails.

## 5. B2 design decisions

**Where the counter lives, and what it counts.** Queue depth —
`count(timeline_requests where status in (queued, processing))` — in Postgres,
checked before a parcel row or a request row is written. Rejected: a
fixed-window creation counter in Redis.

Against what a flood looks like to the single worker: it is a backlog the
worker cannot drain (median run 42 s at concurrency 2 ≈ 170/hour). Depth is
that backlog, measured directly. It self-corrects as the worker drains; when
the worker is down it stays high and new work is refused, which is the right
answer because that work would never run; and it lives in the store the
request row goes to, so it keeps working when Redis — broker, cache and
limiter at once — is the component under strain (SEC-6's cascade). A Redis
window of N/hour either starves a legitimate burst (N small) or admits a
backlog the worker cannot clear (N large), and it fails with the component
it protects. Cost of the choice: one `COUNT(*)` over an indexed status column
per new-parcel request, and parcel-row growth during a sustained flood is
bounded by the drain rate (~170/hour), not zero — the kill switch is the zero.

**Cap value:** 30 ≈ 10 minutes of wait for the last in line at today's drain.
A knob (`MAX_INFLIGHT_TIMELINE_REQUESTS`), not a constant.

**Kill switch scope:** refuses new parcels and new request rows; dedup hits,
complete requests, and every read path are untouched; a suppressed backfill
is silent. Only a parcel with no reusable request at all sees a 503 on its
explore page, and that is a parcel with nothing to show anyway.

**B1 design:** served-coordinate markers in Redis rather than a signed token
(needs a secret shared across uvicorn workers) or a server-side Photon
round-trip at search time (adds a SEC-8 upstream call to every fallback).
The marker is written by the only code that produces coordinates, read by the
only code that consumes them, and a Redis outage degrades to "no fallback",
never to "trust the client".

## 6. UNVERIFIED

| Claim | Check |
|---|---|
| Titiler 1.2.1 returns **401** (not 403) without the token once `TITILER_API_GLOBAL_ACCESS_TOKEN` is set; FINDINGS read this from the image but no probe has been made | DEPLOY-SEC-1.md step 4's `curl` — accept either 401 or 403, reject 500 |
| `fly secrets set` on `plotline-titiler` completes its restart without the machine failing its health check (the image takes the env at boot) | `fly status -a plotline-titiler` after step 3 |
| Landsat band hrefs in PC STAC items are all on `landsateuwest.blob.core.windows.net` (the constant `LANDSAT_BLOB_CONTAINER` says so; not re-sampled this session) | after deploy, grep worker logs for `asset on a non-allowlisted host; refusing` — any hit means a host is missing from the allowlist |
| starlette 1.0.1 → 1.6.0 changes no runtime behaviour under uvicorn on Fly (tests pass locally; the local venv had been running 1.3.1 ahead of the lock) | first deploy's health check + one tile + one geocode |
| A MapLibre session warms ≤120 snapshots/min through one IP (the new per-route `/warmup` bucket) | after deploy, count `429` on `/warmup` in API logs over a day; expect 0 |
| Photon's 250 m radius separates poisoned rows from legitimate fallbacks on the 71 candidates | the script's `--verify` dry run, which Ryan runs |

## 7. What Ryan has to do, in order

1. **Push** `52b0223..` with `8c8907f` (they go together by design). CI runs
   tests and deploys API + worker (backend paths changed) and Titiler
   (`fly.titiler.toml` changed → `DISABLE_MOSAIC` lands).
2. **Verify deploy 1:** `/api/v1/health` sha = `6c34335` or later; one tile
   200 through the API; one address search 200; a `curl` to
   `https://plotline-titiler.fly.dev/mosaicjson/info?url=x` → 404.
3. **DEPLOY-SEC-1.md** steps 0–5: generate the token; `fly secrets set
   TITILER_ACCESS_TOKEN=… -a log0s-plotline-api` (restarts the API); verify a
   tile; `fly secrets set TITILER_API_GLOBAL_ACCESS_TOKEN=… -a
   plotline-titiler` (one action, restarts Titiler); verify a tile and that
   `/cog/info?url=` direct is refused. Rollback is `fly secrets unset`.
4. **Kill switch:** name `ACCEPT_NEW_PARCELS`, default `true` (absent = on).
   To pull it mid-flood: `fly secrets set ACCEPT_NEW_PARCELS=false -a
   log0s-plotline-api` (restarts the API in ~30 s; existing parcels keep
   loading). To restore: `fly secrets unset ACCEPT_NEW_PARCELS -a
   log0s-plotline-api`. Cap: `MAX_INFLIGHT_TIMELINE_REQUESTS`, default 30, same
   mechanism.
5. **Score the B4 predictions** in STATUS.md after a day of traffic: grep API
   logs for `Admission refused`, `Refusing coordinates this backend did not
   serve`, `Rate limit check failed closed`, `Backfill suppressed — admission
   refused`; expect zero of each on a normal day.
6. **Rotate `CENSUS_API_KEY`** if any Fly log was ever exported (SEC-4); the
   scrub only protects logs written after deploy.
7. **Decide on the 71 rows:** `fly ssh console -a log0s-plotline-api -C
   "python /app/scripts/remove_unverified_reverse_parcels.py --verify"` is a
   read-only dry run (71 Photon queries, 1 s apart). Write the prediction
   into STATUS.md SEC-5 before adding `--execute`.
8. Still yours from FINDINGS §9: token scope, branch protection, provider
   spend caps, Cloudflare `_headers` (SEC-11), the address-publication
   decision (SEC-13).

## 8. Production touches this session

| Action | Result |
|---|---|
| `fly apps list` | 3 apps, metadata only |
| `fly ssh console -a log0s-plotline-api` — one read-only Python payload, nine SELECTs (§4) | as listed; no write, no tile, no `/warmup`, no load |
| `git ls-remote` against four GitHub repos | action SHAs (§3 A5) |

No request was made to `plotline-titiler.fly.dev` or `api.plotline.land`.
