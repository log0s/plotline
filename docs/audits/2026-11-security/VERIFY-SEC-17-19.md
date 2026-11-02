# Post-deploy verification — SEC-17/18/19 Titiler 2.4.0 (2026-11-02)

**Mode:** report, don't fix. Read-only against production: no `fly ssh`, no
secrets read, no config changes, no pushes. The Titiler token was never
seen or used. P2–P4 were authorized against production in the batch prompt.

**Deploy under test:** push of `aef5fe6` to `main` (it carries `36531b1`).
Deploy run `41503221445`, Titiler release v10, 2026-11-02 18:43–18:44Z.

**Rollback not needed.** Steps 3 and 4 both passed. For reference, rollback
is `git revert 36531b1`, then Ryan pushes. Not run.

## Bottom line

- **Titiler 2.4.0 is live and serving.** One tile per source rendered
  through the API proxy. The USGS topo tile, the one exact lab scene, is
  byte-identical to the lab output (23,699 B).
- **M2 holds.** P4 gave 120 × 204 and 1 × 429. Fly overwrites a
  client-sent `Fly-Client-IP`.
- **New: Fly forwards a malformed `Host` over HTTP/1.1.** Over HTTP/2 it
  resets the stream. PROD-PROBES P2/P3 as written use curl's default
  HTTP/2, so they never reach the app. The API doesn't reflect the bad
  Host. Titiler's reflection can't be observed without the token, so that
  check is **open for Ryan** (command below).
- **Safe to push the rest: yes** (see the last section).

## Phase 1 — deploy landed

| # | Check | Command | Observed | Expected | Verdict |
|---|---|---|---|---|---|
| 1a | Push run result | `gh run list --limit 3` | `Deploy` run `41503221445` on `aef5fe6`: **success**, 1m39s. Jobs: `changes` ✓, `deploy-titiler` ✓ (1m14s); `test`, `deploy-api`, `deploy-worker`, `test-frontend` skipped | only `deploy-titiler` runs | **pass** |
| 1b | flyctl install step | `gh run view 41503221445 --log-failed` (empty, because the run passed), then `--log` | Step `Install flyctl (pinned, sha256-verified)`, env `FLYCTL_VERSION: 0.4.123`, `FLYCTL_SHA256: 08d8b45e…94bc`. Log line: **`2026-11-02T18:43:42.6682978Z /home/runner/work/_temp/flyctl.tgz: OK`**. `flyctl deploy` then ran: `Searching for image 'ghcr.io/developmentseed/titiler@sha256:5b739117…' remotely... image found`, and both machines reached a good state | checksum verified before extraction | **pass** (`raw/verify/deploy-titiler-flyctl-step.txt`) |
| 2a | Titiler image | `fly image show -a plotline-titiler` | Both machines (`080e603a732098`, `825d6ea73e9278`) run `ghcr.io/developmentseed/titiler@sha256:29286aa3…e812`. OCI labels: `version=2.4.0`, `revision=dac9fa0b…`, `created=2026-09-21`. **No `GH_SHA` label**, see note A | `GH_SHA` = pushed commit | **pass, by digest** (note A) |
| 2b | API / worker image | `fly image show -a log0s-plotline-api` / `-a plotline-worker` | Both machines of each: `GH_SHA=bac725c5…`. Latest releases v87 / v79, Sep 7 2026 03:23 | unchanged from before the push | **pass** |
| 3 | Anonymous health | `curl -sS -w '\n%{http_code}\n' https://plotline-titiler.fly.dev/healthz` | `{"detail":"Missing \`access_token\`"}` / `401` | 401 | **pass** |
| 4a | Startup | `fly logs -a plotline-titiler --no-tail` | Both machines: `Preparing to run: gunicorn -k uvicorn.workers.UvicornWorker … --bind ${HOST}:${PORT} --workers ${WEB_CONCURRENCY}` **`as nonroot`**; `Starting gunicorn 26.2.0`; **`Listening at: http://0.0.0.0:8000`**; one worker booted; `Application startup complete`. No errors or tracebacks | uvicorn on 8000, non-root, no driver errors | **pass** (`raw/verify/titiler-startup-logs.txt`) |
| 4b | Env present | `fly config show -a plotline-titiler`, compared in Python against `fly.titiler.toml` | Deployed `[env]` **equals** the repo's `[env]`, key for key. `GDAL_SKIP` has 142 comma-separated names; none of `GTiff, MEM, PNG, JPEG, VRT` is in it; `HDF5`, `HDF5Image`, `netCDF` are. `PORT=8000` = `internal_port 8000`. `TITILER_API_DISABLE_ZARR=TRUE`, `…_MOSAIC=TRUE`. `build.image` = the pinned index digest | allowlist env present | **pass** (note B) |
| 5 | One tile per source via the frontend path | `GET https://log0s-plotline-api.fly.dev/api/v1/imagery/<snapshot>/tiles/<z>/<x>/<y>` (`frontend/src/utils/applyImageryLayer.ts:80`) | see the tile table below: 4 × 200, `image/*`, `immutable`, real pixels | 200, `image/*`, bytes within 10% of lab | **pass**. The byte criterion applies to 1 of 4; 3 are N/A (note C) |
| 6a | API version | `curl https://log0s-plotline-api.fly.dev/api/v1/health` | `200`, `status ok`, db/redis connected, `version.sha=bac725c5…`, `built 2026-09-07T03:23:17Z` | sha unchanged | **pass** |
| 6b | Timeline for a featured parcel | **not run as specified**; substitute: `GET /api/v1/parcels/bdf4bdcc-…/imagery` (RiNo) | `200`, 53,986 B, 0.97 s, 69 snapshots: landsat 43, sentinel2 12, naip 7, usgs_topo 7 | timeline completes with imagery present | **partial**: deviation, note D |

### Tiles (step 5) — `raw/verify/tiles-headers.txt`

`immutable` matters here. When Titiler 404s, the proxy returns a 68-byte
transparent PNG with `max-age=3600` instead (`api/v1/imagery.py:435-441`).
A 401 from Titiler, e.g. a token mismatch, becomes a 502. So
`200 + immutable + >68 B` proves Titiler rendered the tile with the API's
token. Each tile was also viewed and shows real imagery.

| Source | Snapshot (RiNo parcel) | Tile | Observed | Lab post-fix | Δ | Same scene as lab? |
|---|---|---|---|---|---|---|
| USGS topo | `186f4004` Denver East 1:100k 1981 | 13/1708/3109 (lab coords) | 200 `image/jpeg` **23,699 B** | 23,699 B | **0.0%** | **yes** |
| Sentinel-2 | `67dba3d8` S2C T13TEE 2026-08-20 | 13/1706/3109 (lab coords) | 200 `image/png` 67,014 B | 68,069 B | −1.5% | no: lab used 2026-10-29 |
| Landsat (`/stac/tiles` via the API's `/stac` callback) | `e30da741` LC09 033033 2026-08-05 | 12/853/1554 (lab coords) | 200 `image/png` 182,291 B | 189,854 B | −4.0% | no: lab used LC08 034032 2026-10-23 |
| NAIP | `d1e5e2db` m_3910409_sw 2023-09-25, 30 cm | 16/13656/24866 (parcel) | 200 `image/jpeg` 28,680 B | 24,832 B | (+15.5%) | no: different quarter-quad and tile, not comparable |

The S2 tile is about ⅔ transparent on its west side. That is the T13TEE
scene edge at those coordinates, not a render fault. The lab tile at the
same coordinates came out within 1.5% of this size.

### Notes

- **A. No `GH_SHA` on Titiler.** It deploys the stock upstream image, so
  `fly deploy` never adds the GitHub labels, before this push or after.
  Identity is the digest instead:
  - `fly.titiler.toml` pins the **index** `sha256:5b739117…`.
  - `fly image show` reports the **platform manifest** `29286aa3…`.
  - `docker buildx imagetools inspect …@sha256:5b739117…` lists
    `29286aa3…` as its `linux/amd64` manifest. So the machines run the
    pinned bytes.
  - Future checks: compare against the amd64 child of the index, not the
    index digest.
- **B. What 4b does and doesn't prove.** GDAL doesn't log driver
  registration, so "no driver-registration errors" is an absence in the
  logs, which is weak evidence. The strong evidence is env equality plus
  four tiles rendering. **Not verified in production:** that exactly 5
  drivers are registered on the machine. That needs `fly ssh` (Ryan's):
  `python -c "import rasterio; print(sorted(rasterio.Env().drivers()))"`.
- **C. Lab scenes aren't reachable from production read-only.**
  - S2 (2026-10-29) and Landsat (2026-10-23) postdate every snapshot RiNo
    holds; its latest are 2026-08-20 and 2026-08-05.
  - The lab NAIP quarter-quad `m_3910417_nw` covers 39.6875–39.75 N, which
    is south of all three Denver featured parcels: RiNo 39.763, Stapleton
    39.785, GVR 39.784.
  - Finding another parcel that holds them needs the DB (`fly ssh`) or a
    geocode, which writes. So same-source snapshots stand in.
  - The topo tile, the one exact match, is byte-identical. S2 and Landsat
    use the lab's tile coordinates and land within 4%.
- **D. Why the timeline `POST` wasn't sent.**
  `POST /parcels/{id}/timeline` calls `get_or_create_timeline_request`.
  For a reused request it can call `maybe_refetch_for_backfill` and
  `dispatch_timeline_task`, which queue worker runs
  (`api/v1/imagery.py:83-106`). That is a production write and conflicts
  with "read-only throughout".
  - The substitute read covers what the port change could break on the
    API side: the imagery list, and four API→Titiler tile renders,
    including the Landsat `/stac` callback.
  - **What it doesn't cover:** the worker's run of a timeline. The worker
    never calls Titiler (PROD-PROBES P6) and its image is unchanged.
  - If Ryan wants the literal check: open
    `https://plotline.land/explore/bdf4bdcc-3e7f-4cb6-b918-2337c3a0a808`
    in a browser.

## Phase 2 — audit probes (authorized)

All anonymous. Every command was run once as written (curl's default,
which negotiated **HTTP/2**). Because of the h2 result, each was also run
once with `--http1.1`. That is the protocol the BadHost attack uses, and
without it P2's own table couldn't be scored. P2+P3 sent 9 requests: the
8 in the tables, plus one `-v` repeat of the API h2 request to see where
the reset happens.

**All production traffic from this session:**
- Phase 1: 1 `/healthz`, 1 `/featured` (to find parcel ids), 1 parcel
  imagery list, 4 tiles, 1 `/health`.
- Phase 2: 9 for P2+P3, 121 for P4.
- Read-only `fly`/`gh` CLI: `image show`, `releases`, `logs`,
  `config show`, `run view`.

### P2 — malformed `Host` (BadHost)

| Target | Command | Raw result | Interpretation |
|---|---|---|---|
| API, as written (h2) | `curl -sS -D- -o /dev/null -H 'Host: log0s-plotline-api.fly.dev/api/v1/health?x=' https://log0s-plotline-api.fly.dev/api/v1/featured` | no status, no body. `curl: (92) HTTP/2 stream 1 was not closed cleanly: PROTOCOL_ERROR (err 1)`. `-v` shows the request headers were sent, then the stream was reset | Rejected at the protocol layer before any app: a `:authority` containing `/` and `?` is invalid on h2. `-v` doesn't name the sender of the reset; Fly's h2 proxy is the only candidate between curl and the app. **This is not a mitigation:** the same request over HTTP/1.1 gets through (next row) |
| API, `--http1.1` | same, plus `--http1.1` | `HTTP/1.1 200 OK`, `server: Fly/366e4bf88 (2026-10-27)`, `via: 1.1 fly.io, 1.1 fly.io`, `content-type: application/json`, 4,954 B, the normal featured list | **Fly forwards the malformed Host to the app.** That's PROD-PROBES row 2: the API is fine (patched starlette, limiter keys on the route template). Run P3 |
| Titiler, as written (h2) | `curl -sS -D- -o /dev/null -H 'Host: plotline-titiler.fly.dev/healthz?x=' https://plotline-titiler.fly.dev/healthz` | `curl: (92) … PROTOCOL_ERROR` | same as the API |
| Titiler, `--http1.1` | same, plus `--http1.1` | `HTTP/1.1 401 Unauthorized`, `server: Fly/…`, `{"detail":"Missing \`access_token\`"}` | Forwarded. The JSON 401 is the app's token dependency, not the proxy |

### P3 — does the bad Host get reflected?

| Target | Command | Raw result | Interpretation |
|---|---|---|---|
| Titiler, as written (h2, no token) | `curl -sS -H 'Host: plotline-titiler.fly.dev/badhost-probe?x=' 'https://plotline-titiler.fly.dev/tileMatrixSets' \| head -c 400` | `curl: (92) … PROTOCOL_ERROR` | same h2 reset |
| Titiler, `--http1.1` (no token) | same, plus `--http1.1` | `{"detail":"Missing \`access_token\`"}` / `401` | The token dependency runs before the route, so link generation never happens. **Reflection can't be observed without the token: inconclusive.** The lab predicts no reflection on 2.4.0 (starlette 1.6.0, `FIX-SEC-17-19.md` §SEC-17) |
| API, same shape (h2) | `curl -sS -H 'Host: log0s-plotline-api.fly.dev/badhost-probe?x=' https://log0s-plotline-api.fly.dev/api/v1/featured` | `curl: (92) … PROTOCOL_ERROR` | h2 reset |
| API, `--http1.1` | same, plus `--http1.1` | `200`, 4,954 B. `badhost-probe` occurs 0 times. JSON-equal to the normal `/featured` response | **App-level: no reflection.** As PROD-PROBES says, no API endpoint reflects `request.url` |

**For Ryan, to close P3 on Titiler.** You hold the token. Note
`--http1.1`: without it the request never reaches Titiler.

```sh
curl -sS --http1.1 -H 'Host: plotline-titiler.fly.dev/badhost-probe?x=' \
  'https://plotline-titiler.fly.dev/tileMatrixSets?access_token=<token>' | head -c 400
```

Expected (lab): links like `http://plotline-titiler.fly.dev/tileMatrixSets/…`,
with no `/badhost-probe/` in them.

### P4 — `Fly-Client-IP` spoof against the limiter — `raw/verify/p4-results.txt`

The command is PROD-PROBES P4 exactly: 121 × `POST
/api/v1/imagery/00000000-0000-0000-0000-000000000001/warmup`, each with a
fresh random `Fly-Client-IP: 10.x.x.x`. The one change: requests ran 4 at
a time (`xargs -P 4`) instead of one after another.

| Measure | Value |
|---|---|
| Responses | **120 × 204, 1 × 429** |
| Wall time, first request start to last request end | 13.36 s, inside one 60 s window |
| Distinct spoofed IPs | 121 of 121 (0 duplicates) |
| 429 body | `{"detail":"Too many requests — please slow down and try again shortly."}`: the app's `RateLimit`, not Fly |

**Interpretation:** PROD-PROBES row 1. Fly overwrites the header.

**Which bucket tripped:** `ratelimit:/api/v1/imagery/{snapshot_id}/warmup:<real client IP>`.
- Each spoofed value was unique, so a spoofed-IP bucket could never pass 1.
- The only key that can reach 121 is the one every request shared: the
  connecting IP that Fly wrote into `Fly-Client-IP`.
- The 429 went to the request launched last (#121). Under `-P 4` that is
  not guaranteed to be the last to arrive, but exactly one request over
  the limit is what matters.
- Side effect, as PROD-PROBES predicted: the operator's IP was locked out
  of `/warmup` for under 60 s. Nothing else was touched.

**Deviation from the prompt's pacing instruction.** The prompt asked to
stay under 60/min on the real IP until the step meant to trip it. With a
120-per-60 s **fixed window** (`rate_limit.py:83-86`, `EXPIRE … NX`), that
can't produce a trip:
- If Fly overwrites the header, the real-IP bucket has to reach 121
  inside one window.
- A paced run lets the key expire and never trips. That reads as
  "121 × 204", PROD-PROBES' **reopen** row: a false reopen of M2.
- So the run followed "P4 as written": one burst, timed to prove it fit
  one window.
- Request count stayed at 121, P4's own number.

### M2

**M2 holds.** It is verified in production for the first time since
2026-08-22. `Fly-Client-IP` can't be set by the client on
`log0s-plotline-api.fly.dev`. The spoofable `X-Forwarded-For` branch in
`rate_limit.py:38-40` stays unreachable behind Fly's proxy, as the comment
at `rate_limit.py:28-34` says. The topology caveat still applies: it holds
only behind Fly's proxy.

## Safe to push the remaining commits?

**Yes.**

**What's unpushed:** `1c3fe32` and `bb89b97`, which the prompt names, plus
`6cfdf38` (docs, sleep recon) and this report's commit. All four are on
local `main` ahead of `origin/main` = `aef5fe6`.

**Why it's safe:**
- **The Titiler half is verified.** 401 anonymous, port 8000, non-root,
  env equals the repo, four sources render. Nothing in the remaining
  commits touches Titiler.
- **The new tests assert what is live.** `test_titiler_config.py` checks
  `fly.titiler.toml`, and step 4b shows the deployed config equals that
  file. They can't fail on a drift that exists.
- **CI gates the deploy.** `1c3fe32` matches `backend/**`, so the push
  runs `test`. `deploy-api` and `deploy-worker` both `needs: test`
  (`deploy.yml:220, 249`), so a red test job stops the rebuild.

**What that push changes (known, in STATUS):**
- It rebuilds and redeploys API and worker. The app code is identical,
  but the rebuild re-resolves `python:3.12-slim` and `uv:0.11` by tag
  (SEC-19's open half). It may also move SEC-20's base image; untested.
- It is the first run of the pinned flyctl step in `deploy-api` and
  `deploy-worker`. It's the same version and hash env that passed here.

**Check after that push:**
- `/api/v1/health` `version.sha` moves to the pushed HEAD.
- `fly image show` `GH_SHA` matches on both apps.
- One tile still renders through the proxy.

*Later (2026-11-02): all three confirmed after the push of `8c8e297`
(`VERIFY-PUSH-8c8e297.md`). P3 on Titiler is still open: the token
supplied for it was rejected as invalid.*

**Not blocking:** P3 on Titiler with the token (above) and the in-machine
driver count (note B).

## Record

This commit makes these updates:
- **STATUS.md:**
  - SEC-17/18/19 rows: "pending deploy" becomes deployed 2026-11-02.
  - SEC-19: CI-exercised in `deploy-titiler`.
  - A post-deploy block under the fix batch: P2–P4 results and the
    discoveries above.
  - M2 accept: a `Later:` note.
- **FINDINGS.md:** dated `Later:` annotations on SEC-17/18/19.
- **PROD-PROBES.md:** a dated `Later:` note on P2/P3. They need
  `--http1.1`.
