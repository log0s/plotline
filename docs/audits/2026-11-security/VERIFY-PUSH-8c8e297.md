# Post-push verification — push of `8c8e297` + P3 on Titiler (2026-11-02)

**Mode:** report, don't fix. Read-only against production: no `fly ssh`,
no config or secret changes, no pushes. The Titiler token was used only
as `"$TITILER_ACCESS_TOKEN"` inside curl. It isn't in this report or in
any evidence file; every captured response was checked for it in raw and
percent-encoded form (0 occurrences).

**Push under test:** `main` at `8c8e297`. Deploy run `41506456853`,
2026-11-02 19:04–19:08Z. API release v88, worker v80, Titiler v11.

Evidence: `raw/verify-push/`.

## Bottom line

- **The API/worker deploy landed cleanly.** Tests passed (771) before
  either deploy. Both apps report `8c8e297`. The app smoke on plotline.land
  passes. All 4 proxy tiles are byte-for-byte the same size as before the
  push.
- **Python 3.12.14 → 3.12.16. CVE-2026-115557 is fixed in the running
  API/worker image.** Debian OpenSSL also moved, `deb13u2` → `deb13u3`.
  This came from the rebuild re-resolving `python:3.12-slim`, not from a
  fix. certifi is still 2026.05.20 and still trusts emSign ECC Root CA - G3,
  so **SEC-20 is only partly mitigated**.
- **P3 on Titiler: inconclusive.** The token in `$TITILER_ACCESS_TOKEN`
  was rejected: `401 {"detail":"Invalid \`access_token\`"}`. The request
  reached Titiler's token check over HTTP/1.1, but it never reached link
  generation. Details are under P3.
- **SEC-17 can close fully: no.**
- **Unpredicted: Titiler was redeployed too (v11, same digest).** The CI
  diff base is the API's deployed SHA, and Titiler's filter matched against
  it. That is the Titiler half of Z7 (see note C).

## Phase 1 — API/worker deploy

| # | Check | Command | Observed | Expected | Verdict |
|---|---|---|---|---|---|
| 1 | Push run result | `gh run list --limit 3`, `gh run view 41506456853 --json jobs` | `Deploy` run `41506456853` on `8c8e297`: **success**, 3m57s. `changes` ✓, `test` ✓ (**771 passed**, 19:05:36Z), `deploy-api` ✓ and `deploy-worker` ✓ (both started 19:05:53Z, after `test` finished at 19:05:51Z). **`deploy-titiler` ✓ also ran.** `test-frontend` skipped | test gates both deploys; both pass | **pass**. The Titiler run is a deviation, see note C (`raw/verify-push/ci-run-41506456853.txt`) |
| 1b | flyctl step, first run in api/worker jobs | `gh run view 41506456853 --log` | `/home/runner/work/_temp/flyctl.tgz: OK` in `deploy-api` (19:05:57Z), `deploy-worker` (19:05:59Z) and `deploy-titiler` (19:04:40Z) | checksum verified in all three jobs | **pass** |
| 2a | API version | `curl https://log0s-plotline-api.fly.dev/api/v1/health` | `200`, `status ok`, db/redis connected, `version.sha=8c8e297e…`, `built 2026-11-02T19:05:58Z` | `8c8e297` | **pass** |
| 2b | Image labels | `fly image show -a plotline-worker` / `-a log0s-plotline-api` | Worker, both machines: `GH_SHA=8c8e297e…`, digest `a1ec7e79…`. API, both machines: `GH_SHA=8c8e297e…`, digest `9297f6bc…` | `8c8e297` | **pass** |
| 2c | Machines healthy | `fly status -a <app>` × 3 | API v88: 2 × `started`. Worker v80: `e2862966b306d8` `started`, `e7845415f57728` `stopped` (the † standby). Titiler v11: 2 × `started`. **No Fly health checks are defined on any of the three apps** (`CHECKS` empty), so "healthy" here means `started` plus 2a / 4 / 5 | all started | **pass** (note A) |
| 3 | Base image moved | `docker pull registry.fly.io/log0s-plotline-api@sha256:9297f6bc…`, then `docker run --rm --network none --entrypoint python … -V` | **`Python 3.12.16`** (`PYTHON_VERSION=3.12.16`). OpenSSL `3.5.7-1~deb13u3`. Base `python:3.12-slim@sha256:b18b261e…` in both build logs. certifi **2026.05.20**, emSign G3 **still in the bundle**. pillow 12.3.0, anyio 4.13.0, pydantic-settings 2.14.1 unchanged | ADVISORIES.md for `bac725c`: **3.12.14**. Fix for CVE-2026-115557 needs ≥ 3.12.16 | **3.12.14 → 3.12.16: CVE-2026-115557 fixed in the image.** (`raw/verify-push/api-image-versions.txt`, note B) |
| 4a | App smoke, plotline.land | Playwright 1.64.1, `https://plotline.land/explore/bdf4bdcc-…` (RiNo), every non-GET aborted in the browser | `200` for parcel, imagery, demographics and events GETs. **28/28 tiles 200.** The map renders NAIP 2023-09-25 at 0.3 m. The census panel shows population, home value and owner-occupied insights. The timeline shows 82 items (69 imagery + Sales/Permits events). Aborted, never sent: `POST …/timeline`, `POST …/imagery/d1e5e2db…/warmup`, Cloudflare RUM beacon | imagery, census, property populate; no timeline POST | **pass** (note D, `raw/verify-push/app-smoke.txt`) |
| 4b | One tile per source through the API proxy | `GET https://log0s-plotline-api.fly.dev/api/v1/imagery/<snapshot>/tiles/<z/x/y>`, same snapshots and coords as `raw/verify/tiles-headers.txt` | see the table below: 4 × `200`, `immutable`, real image magic bytes | 200 | **pass** |
| 5 | Worker alive, no run triggered | `fly logs -a plotline-worker --no-tail` | `e2862966b306d8` pulled `a1ec7e79…`, booted 19:07:27Z. `Connected to rediss://…`, `Janitor found no stranded work`, **`celery@e2862966b306d8 ready.`** at 19:07:36Z. No tracebacks or errors | Celery ready on the new image | **pass** (note E, `raw/verify-push/worker-startup-logs.txt`) |

### Tiles (step 4b) — `raw/verify-push/tiles-headers.txt`

| Source | Snapshot | Tile | Before push (`raw/verify/`) | After push | Δ |
|---|---|---|---|---|---|
| USGS topo | `186f4004` | 13/1708/3109 | 200 `image/jpeg` 23,699 B | 200 `image/jpeg` 23,699 B | 0 |
| NAIP | `d1e5e2db` | 16/13656/24866 | 200 `image/jpeg` 28,680 B | 200 `image/jpeg` 28,680 B | 0 |
| Sentinel-2 | `67dba3d8` | 13/1706/3109 | 200 `image/png` 67,014 B | 200 `image/png` 67,014 B | 0 |
| Landsat (`/stac` callback) | `e30da741` | 12/853/1554 | 200 `image/png` 182,291 B | 200 `image/png` 182,291 B | 0 |

All four carry `cache-control: public, max-age=86400, immutable`. That
rules out the proxy's 68-byte 404 placeholder and its 401 → 502 path.

### Notes

- **A. No Fly health checks.** `fly status` shows an empty `CHECKS` column
  for the API, worker and Titiler. The deploy's "good state" is the
  machine state, not an HTTP check. Health was shown directly instead:
  `/health` 200 with db and redis connected, tiles rendering, and the
  Celery `ready` line.
- **B. What step 3 proves and doesn't.**
  - The pulled digest `9297f6bc…` is the one both API machines run, and
    its `GH_SHA` label is `8c8e297`.
  - The worker image wasn't pulled. Its build log shows the same base
    digest (`b18b261e…`) and the same `uv:0.11` digest (`77280f2f…`), from
    the same `Dockerfile.fly`.
  - The pull used a temporary docker config in the session scratchpad,
    logged in with the local `fly auth token`, then logged out and
    deleted. `~/.docker` wasn't touched.
  - **Not a fix, just a rebuild.** `Dockerfile.fly` still pins
    `python:3.12-slim` by tag. A rollback to release ≤ v87 (API) or ≤ v79
    (worker) brings back 3.12.14.
- **C. Titiler redeployed (v11) on a push that didn't touch it.**
  - The `changes` job takes its diff base from the API's
    `/api/v1/health` SHA, here `bac725c`. It applies that base to every
    filter, including `titiler`.
  - `bac725c..8c8e297` contains `36531b1`'s `fly.titiler.toml` edit, so
    `Filter titiler = true`.
  - Result: Titiler redeployed the same pinned index, and still runs
    platform manifest `29286aa3…`.
  - The restart was harmless, and every tile above was rendered by v11.
  - **The hazard is the reverse case.** Suppose `deploy-titiler` fails
    and `deploy-api` succeeds in one run. The next push diffs from the new
    API SHA, the Titiler change drops out of the filter, and CI is green
    while Titiler lags. That is Z7's mechanism for the worker.
  - Z7's proposed fix (the older of the API and worker `GH_SHA`) doesn't
    cover Titiler, which has no `GH_SHA` label (VERIFY-SEC-17-19 note A).
  - Recorded on Z7.
- **D. How the smoke stayed read-only.**
  - On a deep link with no nav-state request id,
    `ExplorePage.tsx:73-90` calls `POST /parcels/{id}/timeline` once
    imagery loads. That can queue worker runs.
  - The selected NAIP snapshot also fires a `/warmup` POST.
  - Playwright aborted every non-GET/HEAD/OPTIONS request inside the
    browser (`route.abort`), so none reached the network.
  - The UI then shows `Could not start timeline: Failed to fetch`. That
    is the block, not a fault.
  - Census and property panels still load: `ParcelInfo.tsx:293-296`
    enables them when there is no request id and snapshots exist.
  - The browser talks to `api.plotline.land`; step 4b used
    `log0s-plotline-api.fly.dev`, as the earlier verify did. Both are the
    same API app.
- **E. Old worker's exit code.** The replaced process logged `Warm
  shutdown`, then `Main child exited normally with code: 1`. That is
  consistent with Celery's SIGINT handler, which exits with `EX_FAILURE`
  on warm shutdown; Fly's default kill signal is SIGINT. Warm shutdown
  lets in-flight tasks finish, and the new worker's janitor found no
  stranded work on boot. Not treated as a fault.
- **Root user.** The worker logs Celery's `SecurityWarning` about running
  as uid 0. That is SEC-12's "root + gcc" (`Dockerfile.fly` has no
  `USER`), already open. Nothing new.

## Phase 2 — P3 on Titiler

**Command** (VERIFY-SEC-17-19.md §P3 "For Ryan", with `-D-` so headers
are captured):

```sh
curl -sS --http1.1 -D- -G -H 'Host: plotline-titiler.fly.dev/badhost-probe?x=' \
  --data-urlencode "access_token=$TITILER_ACCESS_TOKEN" \
  'https://plotline-titiler.fly.dev/tileMatrixSets'
```

**Deviation: `-G --data-urlencode` instead of `?access_token=<token>` in
the URL.**
- The first attempt, run exactly as written, put the value raw in the URL.
  curl refused it locally (`curl: (3) URL rejected: Malformed input to a
  URL function`, `http_code=000`), so **no request was sent**.
- Checked without printing it: the env value is 60 characters and
  contains 5 whitespace characters and `&`.
- Percent-encoding is the only way to send that value as one query
  parameter.

**Captured response** (`raw/verify-push/p3-titiler.txt`, token redacted;
there were 0 occurrences to redact):

```
HTTP/1.1 401 Unauthorized
server: Fly/366e4bf88 (2026-10-27)
content-length: 35
content-type: application/json
cache-control: public, max-age=3600
via: 1.1 fly.io, 1.1 fly.io

{"detail":"Invalid `access_token`"}
```

**Interpretation: inconclusive.** Titiler on Starlette 1.6.0 should not
reflect the malformed Host in any URL field or `Location` header. This
response can't show either way.
- **Evidence line:** `{"detail":"Invalid \`access_token\`"}`. The token
  check ran and rejected the value, so `/tileMatrixSets` never built a
  link.
- Reaching the check confirms again that Fly forwards the malformed Host
  over HTTP/1.1. Without a token the error is `Missing`; with one it is
  `Invalid`.
- `badhost-probe` appears 0 times in the response. With no `Location`
  header and no link body, that is no evidence at all.
- **Why the token was rejected is not established.**
  - A token from `secrets.token_urlsafe()` would have no whitespace or
    `&`. So the session's env var probably doesn't hold just the deployed
    secret: an export that captured extra text, or quoting, are the
    likely candidates.
  - Not investigated further. Trying variants means guessing at the
    secret.
- **For Ryan:** check the variable in your shell (`echo
  ${#TITILER_ACCESS_TOKEN}`; a urlsafe token is usually 43 characters),
  then re-run the command above. A conclusive "not reflected" needs a 200
  whose `links[].href` values start `https://plotline-titiler.fly.dev/` or
  `http://plotline-titiler.fly.dev/`, with no `/badhost-probe` in them.

Side observation: the 401 carries `cache-control: public, max-age=3600`.
That is Titiler's cache-control middleware applying to error responses.
No shared cache sits in front of Titiler (it is served straight from
`fly.dev`), so nothing caches it today. Not a finding at this topology.

### Step 7 — GDAL driver count

**Skipped.** It needs `fly ssh`
(`python -c "import rasterio; print(sorted(rasterio.Env().drivers()))"`
on a Titiler machine), so it stays Ryan's, as in VERIFY-SEC-17-19 note B.
The Titiler machines did restart on v11 with the same digest and the same
`[env]` (no `fly.titiler.toml` change since v10).

## SEC-17 — can the row close fully?

**No.** Two reasons, either one enough:
1. **The production BadHost check is still unobserved on Titiler** (P3
   above). The lab result (not reflected on 2.4.0) stands, but it is a
   lab result.
2. **The row's residuals are untouched by this push:**
   - GDAL 3.12.4 (< 3.13.1)
   - Python 3.14.7 (< 3.14.10)
   - certifi 2026.7.22 as GDAL's CA bundle, still trusting emSign G3
   - 22 pip-audit advisories

   No stock Titiler release newer than 2.4.0 exists. Closing these needs
   a newer upstream image or a custom one (Ryan's decision, see SEC-18).

The SEC-17 row is still updated: it said `1c3fe32` was "not yet pushed",
which is now false.

## Predictions from the previous batch, scored

From `VERIFY-SEC-17-19.md` §"Check after that push" and STATUS.md's
"discovered" note on the `1c3fe32` push:

| Prediction | Observed | Verdict |
|---|---|---|
| `/api/v1/health` `version.sha` moves to the pushed HEAD | `8c8e297` | confirmed |
| `fly image show` `GH_SHA` matches on both apps | `8c8e297` on all 4 API/worker machines | confirmed |
| One tile still renders through the proxy | 4 of 4, identical sizes | confirmed |
| The push rebuilds API and worker and re-resolves `python:3.12-slim` / `uv:0.11` | Both rebuilt on `python:3.12-slim@b18b261e…` / `uv:0.11@77280f2f…` | confirmed |
| "It may also move SEC-20's base image; untested" | Moved: Python 3.12.16, OpenSSL `deb13u3` | confirmed |
| First run of the pinned flyctl step in `deploy-api` / `deploy-worker` passes | `flyctl.tgz: OK` in both | confirmed |
| (implicit) only API and worker redeploy; "nothing in the remaining commits touches Titiler" | Titiler also redeployed (v11) | **deviation**: the commits didn't touch Titiler, but the diff base reached back to `bac725c` (note C) |

## Production traffic from this session

- **API, `log0s-plotline-api.fly.dev`:** 1 × `/api/v1/health`, 4 tiles.
- **plotline.land, one page load:**
  - `api.plotline.land`: 4 GETs and 28 tile GETs.
  - Basemap tiles from OpenFreeMap.
  - 3 POSTs aborted in the browser, never sent.
- **Titiler:** 1 request (P3). The first P3 attempt never left curl.
- **Registry:** 1 image pull from `registry.fly.io`.
- **Read-only CLI:**
  - `fly`: `image show` × 3, `status` × 3, `logs` × 1.
  - `gh`: `run list`, `run view`.

## Record

This commit makes these updates:
- **STATUS.md:**
  - SEC-17: no longer says "not yet pushed"; P3 still open.
  - SEC-19: the api/worker flyctl copies have run.
  - SEC-20: partly mitigated by the rebuild, certifi half open.
  - Z7: a dated `Later:` note on the Titiler half.
  - A post-push block under the SEC-17/18/19 fix batch: predictions
    scored, P3 inconclusive, and the discovered absence of Fly health
    checks (note A).
- **FINDINGS.md:** dated `Later:` notes on SEC-19 (all three flyctl
  copies exercised) and SEC-20.
- **VERIFY-SEC-17-19.md:** a dated `Later:` note under "Check after that
  push".
