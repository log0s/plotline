# Security audit — findings

**Frozen record.** Date 2026-08-22. HEAD `dacbcbf`; deployed API and worker
`dacbcbf` (`/api/v1/health` sha, probe #1; `fly image show` labels); Titiler
`titiler:1.2.1` digest `9cc74708…`. Companion: `SURFACE.md` (inventory),
`URGENT.md` (stop-gate finding). Mode: report, don't fix. No production
write, no `/warmup`, no tile request, no load was generated; every
production touch is in §8.

## 1. Threat model

What changed: the site is shared and indexed; the API log already shows
scanner traffic hitting `/login` and `/robots.txt` from non-US Fly edges
(probe #15). There are no accounts, so nothing to steal *from* a user —
what an attacker takes is Plotline's **money** (Neon, Upstash, Fly egress
bill per use), its **upstream standing** (PC signing quota, Census key,
Photon's ban policy, county ArcGIS endpoints), its **uptime** during a
share, the **integrity** of records shown against an address, the
**privacy** of people who searched their own homes, and — via the tile
stack — **infrastructure** reach. Severity below is impact in those terms ×
exploitability from the public internet with zero inside knowledge; no CVSS.
HIGH = a stranger can do it today with curl and it costs money, standing,
uptime or truth; MEDIUM = needs timing, volume or a second condition;
LOW = real but bounded or second-order.

## 2. Premises

| | Result |
|---|---|
| P1 | **Holds.** Titiler is `https://plotline-titiler.fly.dev` (`fly.toml:13`, `fly.worker.toml:15`), dedicated public v6 + shared v4 (`fly ips list`), reachable (probe #7, #12). |
| P2 | **Holds, from code.** Stock image, no `TITILER_API_*` env (`fly.titiler.toml`), `global_access_token`/`disable_*` at defaults (read from the image's `titiler.application.settings`). Arbitrary `url=` on every `/cog`, `/stac`, `/mosaicjson` route (probe #12). The optional prod probe against `/cog/info` was **not** made — the code read was unambiguous. |
| P3 | **Holds with two corrections.** Precedence is `Fly-Client-IP` → XFF → socket (`rate_limit.py:33-38`). Fly's docs say the proxy sets it and that it is preferable to XFF; they do not literally say "overwritten on every request" (UNVERIFIED, §7). `api.plotline.land` resolves to the Fly ingress IPs, not Cloudflare (DNS + `server: Fly`, probe #2), so the key is the real client. **Redis down or throttled → fail OPEN** (`rate_limit.py:72-74`, by design per the module docstring). **Key includes the resolved path** (`rate_limit.py:59`), so per-id routes get a bucket per id (SEC-3). |
| P4 | **Holds.** No global cap, no queue-depth check, no kill switch: `dispatch_timeline_task` calls `.delay()` unconditionally (`services/imagery.py:173`); `rate_limit_enabled` is the only flag (`config.py:78`). One-in-flight-per-parcel is enforced by a partial unique index (`alembic/versions/0010:66-70`). |
| P5 | **Does not hold.** `_ALLOWED_STAC_HOSTS` covers only the API's Landsat item fetch (`api/imagery.py:336,750`). NAIP/S2/topo `cog_url`, thumbnails and the topo GeoTIFF host reach Titiler's `url=` unchecked (N5, SURFACE F6/F9); the worker's validation `HEAD` follows redirects to whatever the STAC href names (F4). |
| P6 | **Holds.** `task_serializer`/`result_serializer`/`accept_content` all `json` (`celery_app.py:831-833`). |
| P7 | **Public.** `api.github.com/repos/log0s/plotline` → `"visibility": "public"` (`gh` not installed; public API used). Everything under `docs/audits/` and all history is published. |
| P8 | **In sync.** HEAD = deployed = `dacbcbf` on API (built 2026-08-19T23:29Z) and worker (release 52, 2026-08-20). No gap commits. |

## 3. Findings

### SEC-1 · HIGH · Titiler is a public, unauthenticated open fetcher
- **Surface:** `plotline-titiler.fly.dev` `/cog/*`, `/stac/*`, `/mosaicjson/*`. `fly.titiler.toml:10-23`.
- **Confirmed:** code/config read + image introspection; route list probe #12.
- **Exploit:** `GET /cog/info?url=https://<any host>/x.tif` — GDAL fetches it from Plotline's egress; `url=/vsicurl/http://[<api 6PN v6>]:8000/...` probes the private network; `url=/any/local/path` opens container files; `/mosaicjson/tiles/…?url=<attacker mosaic.json>` fans out to N assets per tile.
- **Impact:** cost (Fly egress + Titiler CPU, 2 × 1 GB shared machines), upstream standing (third-party hosts see Plotline's IP), GDAL driver attack surface (RCE-class, in a container holding no secrets), and a reliability lever — a flood here starves the legitimate tile path that shares the same two machines.
- **Fix:** `TITILER_API_GLOBAL_ACCESS_TOKEN` + pass `access_token` at 5 call sites — **S** (one constant + ~10 lines). `TITILER_API_DISABLE_MOSAIC=TRUE` — **one env var, zero code**. Flycast private addressing — **S/M**, also closes M9's routing exposure. See `URGENT.md`.
- **Raises/lowers:** a GDAL CVE in 3.12.1 reachable via a remote driver raises it to critical; Flycast alone lowers the *internet* half but leaves the `/stac` callback public.
- **Re-triages:** M9 (deferred), N5.

### SEC-2 · HIGH · Unbounded full-pipeline creation via user-supplied coordinates
- **Surface:** `POST /api/v1/geocode` with `lat`/`lon` (`api/geocode.py:187-206`, `schemas/geocode.py:19-32`).
- **Confirmed:** read. When the forward geocode fails (any unmatchable 5+ char string), `reverse_geocode` stores the **caller's coordinates and raw address string** as the parcel (`geocoder.py:322-331`, `parcels.py:135-149`) and dispatches the full pipeline.
- **Exploit:** loop over points ≥50 m apart anywhere on Earth (dedup is 50 m, `config.py:66`); each request = 1 Census geocoder call + 1 reverse call + 1 parcel row + 1 worker run of 56 STAC searches (43 Landsat years + 12 Sentinel-2 + 1 NAIP, `timeline.py:243-254,276`; each up to 3 attempts), ~40–90 validation `HEAD`s (`stac.py:1024`), 1 TNM call, 10 Census data calls + up to 4 vintage lookups (`census.py:73-74`, `timeline.py:617-644`), and 1–8 county queries (`county_adapters.py:257, 403, 556, 681`). 10/min/IP → 600 runs/hour/IP; the worker drains ~120–240/hour (one machine, concurrency 2, ~30 s per run on the last three prod runs, probe #19), so a single IP backlogs the queue indefinitely and every legitimate search waits behind it. 100 IPs: 60,000 queued runs/hour against a 240/hour drain.
- **Impact:** availability (the realistic outage-during-a-share), Neon row growth (~90 rows/run: 80 snapshots + 8 census + tasks on the last prod run), Upstash commands (broker ops per task + rate-limit INCRs), Census key standing (6,000+ data calls/hour/IP on one key), PC search load. Global coordinates also mean Landsat searches over oceans succeed (Landsat is global) — wasted but real work. This is also the 2.1b answer: address variants do **not** amplify (dedup is geographic, 50 m), but coordinates do, without limit.
- **Fix:** (a) reject `lat/lon` outside CONUS (`_US_BBOX` already exists, `api/geocode.py:32`) — **S**; (b) a global in-flight/queue-depth cap (count `timeline_requests` in flight via the partial index, or `celery.control.inspect`) before `.delay()` — **S/M**; (c) an env kill switch `ACCEPT_NEW_PARCELS` — **S**. (b) and (c) **change behaviour under a legitimate spike** (new searches get a 503 with a message instead of a queued run) — that is the intended trade.
- **Raises/lowers:** a measured Upstash/Neon bill per run would make the dollar figure concrete; a worker autoscale policy would lower the availability half and raise the cost half.
- **Re-triages:** none directly; M3's cooldown applies only to the complete-then-backfill path, never to new parcels.

### SEC-3 · HIGH · Per-id rate-limit keys multiply every limit by the id space
- **Surface:** `rate_limit.py:59` (`request.url.path` in the key) with `/parcels/{id}/timeline` 20/min, `/imagery/{sid}/warmup` 60/min, `/imagery/{sid}/stac` 600/min.
- **Confirmed:** read.
- **Exploit:** one IP, N snapshot ids (≈80 per parcel; ids come from the public listing) → 60·N warmups/min, each a Titiler COG header read or a STAC fetch + 3 signings; 600·N `/stac` calls/min, each spending PC signing budget. The M9 rationale ("one shared bucket for all users") is wrong in the other direction too: it is one bucket *per snapshot per IP*, which bounds nothing an attacker cares about. `/parcels/{id}/timeline` on a parcel whose last request is `failed` creates a **new request on every call** — `_find_reusable_request` reuses only in-flight/complete rows (`services/imagery.py:68-79`) and the backfill cooldown only runs on the complete path — so 20 runs/min per failed parcel per IP; 3 such parcels exist today (probe #19). 2.1c bound: on *complete* parcels the cooldown holds (one refetch per parcel per 6 h, `config.py:72`), so a visitor can trigger at most one run per parcel-with-a-gap per 6 h — bounded by parcel count (180 today), not by anything per visitor.
- **Impact:** cost + PC standing + Titiler saturation; the tile proxy itself has **no** limit at all.
- **Fix:** key on the route template (`request.scope["route"].path`) — **S, one line**. Changes nothing for legitimate users unless one visitor warms >60 snapshots/min (a session warms ~80 once — borderline; raise `times` to 120 in the same change).
- **Re-triages:** M2, M9.

### SEC-4 · MEDIUM · `CENSUS_API_KEY` reaches the logs through `str(HTTPStatusError)`
- **Surface:** `geocoder.py:282` (`f"Census reverse geocoder error: {exc}"`), `:382` (vintage lookup); consumed at `api/geocode.py:213` (`extra={"error": str(exc)}`) and `timeline.py:631-635` (`exc_info=exc`).
- **Confirmed:** local — httpx 0.28.1 renders `Server error '500 …' for url 'https://…?address=…&key=…'`. The forward path (`geocoder.py:155-157`) correctly keeps only the status code; the other two do not. `logging_config.py:62-66` silences httpx's own logger *for exactly this reason*, so the intent exists and the shape was missed — the same "grep for the shape" lesson.
- **Exploit:** not attacker-triggered directly, but any Census geocoder 5xx (they happen; 22 TNM 504s sit in task rows today) writes the key to Fly logs, and log shipping is an open decision.
- **Impact:** credential disclosure to whoever reads logs; the key is free to replace but is the one upstream credential Plotline has.
- **Fix:** use `exc.response.status_code` in both messages; add a structlog processor that scrubs `key=`, `sig=` query params — **S**. Rotate the key after the fix ships if any log has been exported.
- **Re-triages:** L10 (log half), G5.

### SEC-5 · MEDIUM · Parcel poisoning: attacker-chosen address and coordinates, inherited by the next real visitor
- **Surface:** same path as SEC-2; `parcels.py:119-130` (dedup hit returns the existing row unchanged).
- **Confirmed:** read.
- **Exploit:** submit `{address: "<anything>", lat, lon}` for a target home with an unmatchable address string. The parcel is created with `address`/`normalized_address` = attacker text. When the resident later searches the real address, the 50 m dedup returns the attacker's row: their text is what the page shows (`GeocodeResponse.address`), and the property search ran on the attacker's street-name token, so county records are for whatever street the attacker named (bounded by `is_address_match`, §5 L3 row). Nothing updates `address` on a dedup hit, so the row is permanent.
- **Impact:** integrity of served data; defacement with a permanent row.
- **Fix:** never store the raw string as `normalized_address` on the reverse path, and/or only accept coords when the text round-trips through Photon — **S**. Independent of SEC-2's bbox check.
- **Re-triages:** L3 (this is the only path where *user* text reaches the WHERE clause; otherwise it is Census `matchedAddress`).

### SEC-6 · MEDIUM · Rate limiter fails open, and nothing else limits
- **Surface:** `rate_limit.py:72-74`; tile proxy, listing, `/parcels/{id}` have no limit (SURFACE 1.1).
- **Confirmed:** read; M6's 2 s timeouts make Upstash throttling a real trigger.
- **Exploit:** exhaust Upstash's per-second command limit (it is the broker, the cache and the limiter) and every limit on every route disappears simultaneously, including `/geocode`'s 10/min.
- **Impact:** availability/cost cascade: the thing that protects upstreams depends on the upstream most likely to be saturated by the attack. IPv6 /128 keying (`rate_limit.py:33`) is a second, smaller bypass: one /64 rotates freely.
- **Fix:** fail **closed** for the three dispatching routes only (`/geocode`, `/timeline`, `/warmup`), open elsewhere; key IPv6 on /64 — **S**. **Behaviour change:** a Redis blip makes new searches 429 for its duration; that is the right failure for a portfolio site.
- **Re-triages:** M2, M6.

### SEC-7 · MEDIUM · Task rows expose upstream URLs to clients; Titiler error bodies (with SAS `sig=`) are logged
- **Surface:** `timeline.py:209,461,593,796,1168` (`error_message=str(exc)`) → `GET /timeline-requests/{id}`; `api/imagery.py:395-400,419-424` (`titiler_body[:500]`).
- **Confirmed:** prod rows carry `Server error '504 Gateway Timeout' for url 'https://tnmaccess…'` (probe #19, 22 rows); GDAL error text embeds the full signed URL (G5's quoted `se=` came from exactly this line).
- **Impact:** signed-URL disclosure into logs (45-min read token to public-data blobs — low value, but the first thing a log-shipping vendor will index); upstream-host disclosure to clients (hygiene, no credential).
- **Fix:** scrub `sig=` in the two `titiler_body` log lines; store `type(exc).__name__` + status instead of `str(exc)` — **S**.
- **Re-triages:** L10 (client accept stands; log half is new), G5.

### SEC-8 · MEDIUM · Geocoder endpoints as free upstream proxies, on Plotline's reputation
- **Surface:** `/geocode/autocomplete` (Photon, 60/min/IP, `api/geocode.py:45-75`); `/geocode` (Census geocoder, 10/min/IP, up to 3 attempts × 20 s each).
- **Confirmed:** read. Photon is called with a fixed UA, no key, no 429 handling (N4); a ban lands on Fly's shared egress for *every* Plotline user.
- **Exploit:** 100 IPs × 60/min = 6,000 Photon queries/min through Plotline; the 300 s cache helps only for repeated `q`.
- **Impact:** upstream standing; autocomplete dies for everyone with no failure signal (N4).
- **Fix:** global Photon budget (Redis token bucket) in front of the call, returning cached-or-empty when exhausted — **S**; same shape for the Census geocoder.
- **Re-triages:** L8 (the benign version of this), N4.

### SEC-9 · MEDIUM · CI/CD: floating third-party actions and an ungated deploy
- **Surface:** `.github/workflows/deploy.yml:26,31,55,58,72,84,93` (`actions/checkout@v6`, `dorny/paths-filter@v4`, `astral-sh/setup-uv@v9.0.0`, `superfly/flyctl-actions/setup-flyctl@master`); trigger `push: main`, no environment/approval.
- **Confirmed:** read. No `pull_request_target`; secrets not exposed to forks. `@master` on the flyctl action is a mutable ref with `FLY_API_TOKEN` in scope.
- **Impact:** supply chain: a compromise of that ref deploys arbitrary images to all three apps with whatever the token can do (scope UNVERIFIED).
- **Fix:** pin all four to commit SHAs; scope the token (`fly tokens create deploy -a …`) — **S**. Branch protection UNVERIFIED (§7).

### SEC-10 · MEDIUM · Dependency advisories with a reachable path
- **Surface:** `backend/uv.lock`: `pillow 12.2.0` (12 advisories per pip-audit, fixed 12.3.0; reachable at `preview_renderer.py:126` on upstream-fetched bytes — offline script only), `starlette 1.0.1` (4 advisories; the one affecting plain apps, CVE-2026-54282, is rated Low by GHSA), `pydantic-settings 2.14.1`. `frontend/package-lock.json`: `react-router 7.14.0` (high-rated; the SSR/loader paths Plotline does not use), `lodash` via recharts, `protocol-buffers-schema` via maplibre; build-time only: vite 5, esbuild, postcss, js-yaml, nanoid, brace-expansion. Titiler image: `starlette 0.52.1`. Totals: pip-audit 26 advisories / 3 packages; npm 8 high, 2 moderate, 1 low, 0 critical.
- **Fix:** `uv lock --upgrade-package pillow starlette pydantic-settings`; `npm audit fix` (non-major clears all but vite/esbuild) — **S**; test suites exist.

### SEC-11 · LOW · API serves no security headers; `/docs`, `/redoc`, `/openapi.json` are public
- **Confirmed:** probes #3-#5 (no HSTS, no `X-Content-Type-Options`, no frame/CSP); Cloudflare Pages sends only `referrer-policy` (probes #6, #10).
- **Impact:** low for a cookie-less JSON API; `/docs` reads as a portfolio choice (`main.py:44-45`) — reported, not decided. Titiler's `/api.html` is the image default, not a choice (probe #11).
- **Fix:** a small middleware (HSTS, nosniff, `frame-ancestors 'none'`) and `frontend/public/_headers` — **S**. A CSP for MapLibre is feasible (`worker-src blob:`; `img-src`/`connect-src` limited to PC, openfreemap, the API host) — **M**.

### SEC-12 · LOW · Neon role is the database owner; container runs as root with gcc
- **Confirmed:** `current_user = neondb_owner`, `createdb`, full DML incl. `TRUNCATE` (probe #19); `uid 0`, `/usr/bin/gcc` present (probe #20) — L12 confirmed in production. `sslmode=require` via the pooler (probe #20): encrypted, CA unverified; `pg_stat_ssl.ssl=false` there is the pooler→Postgres hop, not the client hop.
- **Impact:** an RCE in the API or worker (GDAL is not in these images; Pillow is) gets full DB control. Second-order.
- **Fix:** app role with DML only, owner reserved for `alembic/env.py` — **M**; multi-stage Dockerfile without gcc + `USER` — **S**; `sslmode=verify-full` with Neon's CA — **S**.

### SEC-13 · LOW · The repo publishes residential addresses from production
- **Confirmed:** regex count over the docs: street-address shapes in geometry FINDINGS (6), HEAL-SCORECARD (4), STATUS.md (3), ops FINDINGS, CENSUS_TRIAGE, INVENTORY (1 each); repo public (P7). Parcel ids are `gen_random_uuid()` (not guessable); the only listing is the six curated featured parcels (probe #14); no retention statement exists on the site or in the README; no code path deletes a parcel (1.4).
- **Impact:** privacy of people who searched their homes, against the project itself. This audit adds none.
- **Fix:** frozen docs cannot be edited by policy; the options are a history-preserving redaction commit (first-8 ids) or an explicit accept in STATUS.md. Owner's call — **S** either way.

## 4. Re-triaged prior rows

| Row | Before → after | Reason |
|---|---|---|
| L3 | Low → **Low (hold), new fact** | Local mock (Denver adapter, six adversarial inputs incl. `%`, `_`, `%AIN%`): wildcards widen the upstream LIKE to the cap — both permit layers return every row — but `is_address_match` attached **zero** stranger records; cost-only, and user text reaches it only via SEC-5's path. Records with no `situs_address` bypass the filter (`timeline.py:850`) — add to the row. Sites at HEAD: `county_adapters.py:243, 339, 432, 487` (ArcGIS), `:704, :766` (Socrata); CKAN uses full-text `q` (`:594`). |
| L8 | Low → Low | Benign instance of SEC-8; fix together. |
| L10 | Accept **holds for clients**; **log half reopened** (SEC-4, SEC-7) | Re-traced at `dacbcbf`: 502 details curated; `error_message` rows carry URLs without credentials; but two geocoder messages carry the key and `titiler_body` carries `sig=`. |
| L12 Dockerfile | Low → **Low, confirmed live** (uid 0, gcc) | Blast-radius multiplier for SEC-10/12. |
| M2 | Accept holds on topology; **severity up** via SEC-3 and SEC-6 | New facts (per-id keys, fail-open, IPv6 /128), not a re-litigation of XFF. |
| M9 | Deferred → **should be scheduled**, rationale corrected | "One shared bucket for all users" is wrong: it is one bucket per snapshot per IP. The Titiler token (SEC-1) is the mechanism the row defers and closes both directions at once. |
| G4 | unchanged | The hostile version is SEC-3 (`/stac` × N). A per-client dimension cannot work while every legitimate `/stac` call comes from Titiler's IP; a **global signing circuit breaker** (open on K 429s per window, fast 502, no sleeps on the request path) is the right shape — sketch only. |
| G5 | resolved; log-surface part → SEC-7 | The `se=` quote came from `titiler_body`. |
| O4 | holds | HEAD = deployed today. |
| N5 | Low → **Medium, absorbed by SEC-1** | Once Titiler refuses everyone else, the unchecked `url=` is only the worker-written supply-chain path; without SEC-1 it is moot because anyone can pass any URL anyway. |

## 5. Coverage table

| Surface entry | Checked by | Result |
|---|---|---|
| `/health` | probe #1, read | clean (sha/build by design) |
| `/geocode/autocomplete` | read | SEC-8 |
| `POST /geocode` | read, schema | SEC-2, SEC-5 |
| `/parcels/{id}` | read | clean (UUID, no enumeration) |
| `POST /parcels/{id}/timeline` | read | SEC-3 |
| `/timeline-requests/{id}` | read, prod rows | SEC-7 |
| `/parcels/{id}/imagery` | read | unlimited signing fan-out, cache-backed; noted under SEC-6 |
| tile proxy | read | no limit (SEC-6); z/x/y bounded (L9) |
| `/warmup` | read | SEC-3 |
| `/{id}/stac` | read | SEC-3; host allowlist clean |
| demographics / events / featured | read | clean; `type` split is parameterised |
| `/static` | read | clean (Starlette path guard) |
| `/docs` family | probes #3-5 | SEC-11 |
| Titiler routes | image + probe #12 | SEC-1 |
| F1 STAC search | read | next-link host unchecked — second-order |
| F2/F3 signing | read | clean |
| F4 validation HEAD | read | follow_redirects to an upstream-named host — second-order |
| F5 | read | clean (allowlisted) |
| F6/F7/F9 | read | SEC-1, N5 |
| F8 TNM | read | clean |
| F10/F11 Census | read + local httpx test | SEC-4 |
| F12 Photon | read | SEC-8 |
| F13–F15 county | read + local mock | L3 hold; `follow_redirects=True` + status check is the login-redirect shape, but a portal login page decodes as non-JSON → one failed query, not a silent success — handled |
| Redis/Neon TLS | probe #20 | clean / SEC-12 (unverified CA) |
| Secrets in history | gitleaks 8.30.1, 185 commits, all refs + regex pass | **0 hits**; `.env.example` placeholders only; local `.env` gitignored, never committed |
| Frontend bundle | probe #10 | clean (API host only; no key-shaped strings) |
| Frontend markup | grep | clean (two static `innerHTML` marker templates; no user text) |
| Regex backtracking | local timed run, 6 adversarial inputs ≤10 kB, all <1 ms | clean |
| Celery serializer | read | clean (P6) |
| CI/CD | read | SEC-9 |
| Dependencies | pip-audit, npm audit, image introspection | SEC-10 |
| Security headers | probes #3-6, #10, #13 | SEC-11 |
| Privacy/enumeration/retention | probe #14, read | SEC-13 |
| Sessions/logins/roles/CSRF/stored XSS | n/a | no such surface; `allow_credentials=False` |

## 6. Remediation order (exploitability × impact ÷ size)

**One-constant fixes, ship first:**
1. `TITILER_API_DISABLE_MOSAIC=TRUE` (env only), then the access token + 5 call sites (SEC-1).
2. Rate-limit key on the route template (SEC-3) — one line. *Behaviour change:* none for normal sessions if `/warmup` goes to 120/min in the same commit.
3. CONUS bbox check on `lat/lon` (SEC-2a) — the constant exists.
4. `status_code` instead of `{exc}` at `geocoder.py:282,382` + `sig=` scrub (SEC-4, SEC-7).
5. Pin the four GitHub actions (SEC-9).

**Then:**
6. Fail-closed limiter on the three dispatching routes (SEC-6). *Behaviour change under a legitimate spike:* Redis trouble → 429s on new searches. Intended.
7. Global queue-depth cap + `ACCEPT_NEW_PARCELS` kill switch (SEC-2b/c). *Behaviour change:* a real burst beyond N concurrent new searches gets a polite 503 instead of a 30-minute queue — the G4 lesson in reverse: the protective change *is* the user-visible behaviour, so the message matters.
8. Global Photon / Census-geocoder budget (SEC-8). *Behaviour change:* autocomplete degrades to cache-only under a flood.
9. Reverse-path address handling (SEC-5).
10. Dependency bumps (SEC-10), headers (SEC-11), Neon role + Dockerfile (SEC-12), repo address decision (SEC-13).

**Levers that exist today without a deploy (2.1h):** `fly secrets set` on Titiler (SEC-1 step 1); `fly scale count 0 -a plotline-worker` (stops worker spend; the queue persists in Upstash); provider spend caps (UNVERIFIED whether set). Cloudflare rules do **not** apply — the API is not proxied. **Does not exist:** a parcel-creation flag, a queue-depth cap, a Photon budget, any circuit breaker, any Fly-level IP block on this config.

## 7. UNVERIFIED register

| Claim | Status | Check |
|---|---|---|
| Fly proxy overwrites a client-sent `Fly-Client-IP` | UNVERIFIED (docs: "set by Fly Proxy") | a temporary debug line echoing the header, then `curl -H 'Fly-Client-IP: 1.2.3.4'` |
| `FLY_API_TOKEN` scope | UNVERIFIED | `fly tokens list`; compare to the GH secret's creation date |
| Branch protection on `main` | UNVERIFIED (`gh` absent) | `gh api repos/log0s/plotline/branches/main/protection` |
| Upstash token scope / command cap; Neon spend cap | UNVERIFIED | Upstash console → database → credentials/usage; Neon console → billing |
| Census API quota with a key | UNVERIFIED | api.census.gov key terms |
| Titiler image CVEs (GDAL 3.12.1, rasterio 1.5.0, starlette 0.52.1) | versions verified, advisories not | `pip-audit` inside the image |
| $ per Upstash command / Neon compute-hour per run | UNVERIFIED | provider pricing vs SEC-2's per-run call counts |
| Worker throughput 120–240 runs/hour | derived from 3 runs of ~30 s (probe #19) | `SELECT avg(completed_at-created_at) FROM timeline_requests WHERE status='complete' AND created_at > now()-interval '30 days'` |

## 8. Probe log

Every production touch, UTC 2026-08-22. No writes, no `/warmup`, no tiles, no loops.

| # | Time | Action | Result | Purpose |
|---|---|---|---|---|
| 1 | 22:05:08 | GET `log0s-plotline-api.fly.dev/api/v1/health` | 200 | P8 |
| 2 | 22:05:09 | GET `api.plotline.land/api/v1/health` | 200, `server: Fly` | P3 |
| 3 | 22:05:10 | HEAD `…/docs` | 200 | 2.4d, 2.5f |
| 4 | 22:05:10 | HEAD `…/openapi.json` | 200 | 2.4d |
| 5 | 22:05:10 | HEAD `…/redoc` | 200 | 2.4d |
| 6 | 22:05:10 | GET `plotline.land/` | 200, `server: cloudflare` | P3, 2.5f |
| 7 | 22:05:10 | HEAD `plotline-titiler.fly.dev/healthz` | 405 (GET-only) | P1 |
| 8 | 22:05:11 | HEAD `…/docs` | 404 | P2 |
| 9 | 22:05:11 | GET `…/openapi.json` | 404 | P2 |
| 10 | 22:05:29 | GET `plotline.land/assets/index-CSzBQCSk.js` | 200 (1.7 MB) | 2.4e |
| 11 | 22:05:30 | HEAD `plotline-titiler.fly.dev/api.html` | 200 | P2 |
| 12 | 22:05:30 | GET `plotline-titiler.fly.dev/api` | 200, route list | P2 |
| 13 | 22:05:31 | HEAD `plotline-titiler.fly.dev/` | 405 | 2.5f |
| 14 | 22:05:31 | GET `…/api/v1/featured` | 200, 6 locations | 2.6a |
| 15 | 22:06:09 | `fly logs --no-tail -a log0s-plotline-api` | 7 lines | 2.4b |
| 16 | 22:06:10 | `fly logs --no-tail -a plotline-worker` | 0 lines | 2.4b |
| 17 | 22:08:32 | `fly logs --no-tail -a plotline-titiler` | 0 lines (hung; 45 s timeout) | 2.4b |
| 18 | 22:09:19 | `fly logs --no-tail -a plotline-worker -i e2862966b306d8` | 0 lines | 2.4b |
| 19 | 22:12:39 | `fly ssh console -a log0s-plotline-api` — read-only SQL (`SET SESSION … READ ONLY`, `statement_timeout 30s`): counts, requests/day, last 3 runs, status mix, `error_message` histogram, role privileges, `pg_stat_ssl` | 180 parcels / 334 requests / 1,897 tasks / 14,215 snapshots / 1,408 census / 383 events; 127 requests on 08-12 (sweep), 1–9/day since; last run 6 tasks, 80 snapshots, 8 census rows, 30 s; 3 `failed` requests; `neondb_owner` | 2.1a, 2.5c |
| 20 | 22:13:06 | `fly ssh console` — settings shape only (pooler y/n, `sslmode`, redis scheme, uid, gcc) | pooler, `require`, `rediss`, uid 0, gcc | 2.5a, 2.5c |
| — | ~22:04 | `fly status`, `fly image show`, `fly secrets list` (names only), `fly ips list`, three apps | metadata | P1, P8, 1.3 |

**Not run:** the optional `/cog/info` probe (2.3a) — the code made it unnecessary. `fly ssh console` was permitted, so no queries are outstanding beyond §7's throughput query.

## 9. For Ryan to check (the session cannot)

- **Upstash console → database → Usage/Limits:** monthly command cap or spend alert; whether the token in `REDIS_URL` is the read-write one.
- **Neon console → Billing → limits;** **Roles:** create an app role with DML only.
- **Fly dashboard → Tokens:** what `FLY_API_TOKEN` in GitHub is (org vs deploy-scoped); **Billing → spend alerts**.
- **GitHub → Settings → Branches:** protection on `main`.
- **Cloudflare → DNS:** `api.plotline.land` is DNS-only. Leave it — proxying would break `Fly-Client-IP` keying (P3) unless the limiter changes first.
- **Cloudflare Pages → Settings:** add `_headers` (SEC-11).
- **Census API key:** rotate if any Fly log has ever been exported (SEC-4).
