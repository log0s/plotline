# Security audit 2026-11 — findings

**Mode:** report, don't fix. **Date:** 2026-11-02.

**What was audited.** HEAD is `a45caf3` at the gate and `d226713` after
PREDICTION.md. The deployed code is `bac725c` (API and worker `GH_SHA`). The
commits between them touch only `docs/`.

**What touched production:** `GET /api/v1/health` (twice, step 1),
`fly image show` ×3, `fly config show -a plotline-titiler`, and
`fly auth docker` plus pulling the API and worker images from Fly's registry.

- The last three go beyond the prompt's step 1. They are metadata and registry
  reads, and they were needed for two things. Titiler carries no `GH_SHA`, so
  its config was the only way to confirm its "deployed state". And step 2's
  "Python actually inside each image" needs the deployed bytes, not a rebuild
  of a floating `python:3.12-slim` tag.
- `fly secrets list` was **denied** by the permission layer and not retried. It
  is in PROD-PROBES P6.

No `fly ssh` and no probes against production.

All probes ran against the deployed image digests, run locally:

- **API:** run on the compose network against local Postgres and Redis.
- **Titiler:** run on an `--internal` Docker network with no route out, with
  `fly.titiler.toml`'s exact env loaded from `raw/lab/fly-titiler.env`.

**Correction made during the session.** The first lab pass passed the Fly env
as an unquoted zsh variable. zsh does not word-split those, so Titiler started
**without** `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` and `TITILER_API_DISABLE_MOSAIC`.
I caught it when `/mosaicjson` appeared to be live. Every result below is from
the second pass, which used `--env-file`, with the env confirmed inside the
container (`disable_mosaic True`). No finding rests on the first pass.

**IDs start at SEC-17.** `STATUS.md` already uses SEC-1…SEC-13 (the 2026-08
audit). An uncommitted report from this morning,
`../2026-11-dependency-advisories/REPORT.md`, used SEC-14…16. Restarting at
SEC-1 would put two different SEC-1 rows in one ledger. The order is still
the severity ranking: SEC-17 is the most severe.

**Severity is impact in our topology** (the 2026-08 audit's scale: money,
upstream standing, uptime, truth, privacy, infrastructure reach) times
exploitability from the internet. It is not CVSS.

## The gating unknown

Two findings below change severity on one fact this session couldn't read:
**is `TITILER_API_GLOBAL_ACCESS_TOKEN` set on `plotline-titiler`?**

- STATUS.md last says SEC-1's operator steps are *pending* (2026-08-22), and
  nothing since records them done.
- The token can't be inferred from config: it is a secret, and secrets listing
  was denied.
- **PROD-PROBES P1** settles it with one anonymous `GET /healthz`. In the lab,
  the deployed digest returns 401 with the token set and 200 without it.

This is also the precondition the **M9 accept** names. The 2026-08-22 re-triage
says "the accept stands with the token as its precondition", so until P1
runs, that precondition is unverified, not satisfied.

---

## SEC-17 · HIGH if P1 returns 200 / MEDIUM if 401 · Titiler runs an 8-month-old stock image with stale parsers

**Evidence** (deployed digest `9cc74708…`, built 2026-03-09; `raw/titiler-inventory.txt`, `raw/pip-audit-titiler.json`, `raw/osv-image-titiler-summary.tsv`):

- **GDAL 3.12.1**, bundled in rasterio 1.5.0's wheel. It is affected by
  CVE-2026-49014 (netCDF `scanForGeometryContainers` stack overflow, 3.1.0–3.13.0,
  fixed 3.13.1). There is no 3.12.x backport.
- 147 drivers are compiled in, including `netCDF`, `HDF5`, `HDF5Image`, `VRT`,
  `GRIB`, `PDF`, `JP2OpenJPEG`, and `NITF`.
- The vendored native libraries are invisible to every scanner: libnetcdf 4.9.3,
  libhdf5 1.14.6, libcurl 8.17.0, OpenSSL 3.6.0. Their versions were read out with
  `strings`, and they ship inside `rasterio.libs/`.
- **starlette 0.52.1:** all five 2026 advisories apply, including
  **CVE-2026-48710 BadHost, on CISA KEV since 2026-09-02**. Lab:
  `raw/lab/badhost-starlette-unit.txt` and `raw/lab/badhost-titiler-reflect.txt`.
- **rio-tiler 8.0.5:** no band-math expression guard at all (GHSA-9cfx-96xx-wmh9,
  fixed 8.0.9). It is a repository advisory with no CVE, unreviewed, and absent
  from OSV, so **pip-audit and osv-scanner both pass it clean.** The only layer
  left is numexpr 2.14.1's denylist, which rejected both published payload
  building blocks in the lab (`raw/lab/probe3-out.txt`). Weaponized chains were
  not attempted.
- **certifi 2026.2.25** is also GDAL's curl CA bundle (`GDAL_CURL_CA_BUNDLE` →
  certifi's `cacert.pem`), so GDAL trusts emSign ECC Root CA - G3.
- **Python 3.14.3**, below 3.14.10 (CVE-2026-115557).
- Also stale: urllib3, requests, idna, anyio, opentelemetry-api. Debian 13 OS
  packages carry 1115 advisory ids.
- `fly.titiler.toml:10` pins by **tag**, not digest. Fly resolved the tag once, at
  deploy. A redeploy re-resolves it, and nothing records which bytes are expected.

**Exploitability path.** Everything here is reached by making Titiler open a
URL or evaluate an `expression=`.

- **P1 = 200 (token unset):** anyone on the internet can do it. Titiler routes
  take arbitrary `url=` and `expression=`, and production `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`
  only requires the URL to end in `.tif` (SEC-18).
- **P1 = 401 (token set):** only the API reaches Titiler. The API forwards only
  stored URLs whose host is on `stac.ALLOWED_UPSTREAM_HOSTS` (P5), and it never
  forwards `expression`. Exploitation then needs attacker-controlled bytes at an
  allowlisted host (Planetary Computer blob storage, the TNM S3 bucket) — the
  same second-order shape as N5.

**Impact.** A memory-safety bug in a parser, inside a container that:

- runs as **root** (`uid=0`, `raw/titiler-inventory.txt`);
- holds the Titiler token in its environment;
- sits on Plotline's Fly 6PN, with the API and worker reachable at `.internal`;
- shares two 1 GB machines with every legitimate tile.

**Confidence:** versions **high** (read from the deployed bytes). Exploitability **conditional on P1**.

**Fix sketch — M.**

- Move to a current Titiler release that bundles GDAL ≥ 3.13.1, rio-tiler
  ≥ 8.0.9 / 9.1.0, and starlette ≥ 1.3.1 (later than 1.0.1, so it covers all
  five).
- Reference it **by digest** in `fly.titiler.toml`, with the tag in a comment, the
  way the actions are pinned.
- M rather than S because titiler 1.2 → current may cross API changes that the
  tile proxy depends on. Check them with a browser pass.

**Regression test that fails if the fix is deleted:**

- `test_titiler_image_is_digest_pinned`: parse `fly.titiler.toml`; assert
  `build.image` contains `@sha256:` and that the digest equals a constant
  updated alongside it.
- A CI step running `pip-audit` inside that digest (as in `raw/EXIT-CODES.txt`
  row 2), failing on any advisory not on an explicit ignore list. Reverting the
  bump restores starlette 0.52.1 and fails it.
- The rio-tiler half needs its own assertion,
  `rio_tiler.__version__ >= 8.0.9`, because no scanner sees that advisory.


**Resolved:** `36531b1`, 2026-11-02 — committed, **not deployed**. Titiler
2.4.0 by index digest `sha256:5b739117…`: starlette 1.6.0, rio-tiler 9.4.4
(AST guard), Python 3.14.7, uid 65532. **Not everything above is fixed:**
GDAL is 3.12.4, still below 3.13.1 (the netCDF driver is now unregistered,
`36531b1`/SEC-18). Python is below 3.14.10. certifi 2026.7.22 is still
GDAL's CA bundle and still trusts emSign G3. No stock release ships
anything newer. Lab and residuals: `FIX-SEC-17-19.md`.

**Later (2026-11-02): deployed.** Titiler release v10 (push of `aef5fe6`)
runs the amd64 manifest of the pinned index. Anonymous `/healthz` → 401,
port 8000, non-root, all four sources render. BadHost: Fly forwards a
malformed Host over HTTP/1.1. The API doesn't reflect it; Titiler's
reflection needs the token to observe. `VERIFY-SEC-17-19.md`.

---

## SEC-18 · MEDIUM · GDAL picks drivers by content; the extension filter is not a format filter, and a `.tif` VRT steps around the host allowlist

**Evidence** (deployed Titiler digest with `fly.titiler.toml`'s env, `raw/lab/probe-out.txt`, `raw/lab/probe2-out.txt`, `raw/lab/ufd-direct.txt`):

| Served at `http://…/<name>.tif` | Result |
|---|---|
| a real GeoTIFF | 200, driver `GTiff` |
| `notallowed.png` | refused before fetch: the extension filter works for what it is |
| **HDF5 bytes** (netCDF-4) | **opened by `HDF5Image`** (rio-tiler then failed for lack of a CRS, *after* libhdf5 parsed the file) |
| **netCDF classic bytes** | Docker: refused, "requires Linux userfaultfd". With userfaultfd available: **opened by `netCDF`, pixels read** |
| **VRT XML** | **opened by `VRT`; it fetched the nested `/vsicurl/http://audit-canary:8080/canary.tif`** (canary access log) and returned its statistics |
| VRT whose nested source has no `.tif` suffix | nested fetch refused ("Read failed"; no canary hit). The extension filter applies to nested sources too |
| VRT with `VRTRawRasterBand` → `/etc/hostname`, `/proc/self/environ` | refused by GDAL 3.12's default `GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE=SIBLING_OR_CHILD_OF_VRT_PATH` |
| `url=/proc/self/environ`, `file:///etc/passwd` | "not recognized as being in a supported file format" |

GDAL's own security document says this outright: "a VRT file might be
disguised as a .tif … you cannot know which driver will handle a file by just
looking at its extension". Titiler's security page recommends `GDAL_SKIP=VRT`.
Production sets no `GDAL_SKIP` (`fly config show` output, matching
`fly.titiler.toml`).

**Exploitability path.** The same gate as SEC-17. Add one thing that matters
**even with the token set**: P5's allowlist (`stac.ALLOWED_UPSTREAM_HOSTS`)
checks only the **top-level** `url=` the API forwards. If an allowlisted
upstream ever serves VRT XML at a `.tif` path, Titiler fetches whatever `.tif`
URLs that VRT names. That includes `http://[<6PN v6>]:…/x.tif` on Plotline's
private network and any internet host. The allowlist is then bypassed one hop
down.

This is N5's second-order shape, in a mechanism neither N5 nor P5 covered. It
is recorded here and cross-referenced, not re-argued
(`../2026-08-source-inventory/INVENTORY.md` §N5; STATUS.md N5 and P5 rows).

**Impact.**

- It widens SEC-17's reachable parsers from GTiff to every content-identified
  driver.
- It turns one poisoned upstream file into an internal-network fetcher. The
  fetcher is read-only and needs a `.tif` suffix, which is trivially satisfied.
- netCDF reachability depends on whether userfaultfd is usable on the Fly
  microVM. That is unverified (PROD-PROBES P5).

**Confidence:** **high** for HDF5 and VRT (reproduced), **medium** for netCDF in production (P5).

**Fix sketch — S.**

- Set `GDAL_SKIP=VRT,netCDF,HDF5,HDF5Image` in `fly.titiler.toml` `[env]`. That
  is everything the lab showed reachable that Plotline doesn't read; Plotline
  reads only GeoTIFF/COG.
- Better, and **M**: a positive allowlist, meaning a custom Titiler reader
  passing `allowed_drivers=["GTiff","COG"]` through rasterio.
- Mirror the env in `docker-compose.yml`'s titiler service so local equals
  production.

**Regression test:**

- The lab harness as a test: start the pinned Titiler digest with
  `fly.titiler.toml`'s env and request `vrt_ssrf.tif` and `nc4.tif` (both in
  `raw/lab/www/`). Assert both are refused **and** the canary saw no request.
  Deleting `GDAL_SKIP` brings back the 200 and the canary hit.
- Cheap companion: a unit test asserting `GDAL_SKIP` in `fly.titiler.toml`
  contains `VRT`.


**Later (2026-11-02): partially resolved** in `36531b1`, committed, **not
deployed**. `GDAL_SKIP` removes every driver except GTiff, MEM, PNG, JPEG
and VRT, and the HDF5 and netCDF rows above now refuse. **The VRT rows
still reproduce**, canary hit included. `GDAL_SKIP=VRT` breaks every
reprojected tile, because rasterio 1.5.1 opens an in-memory VRT to warp.
Closing it needs a custom reader (`FIX-SEC-17-19.md` §Residuals).

**Later (2026-11-02): deployed** (Titiler v10). Deployed `[env]` equals
`fly.titiler.toml`, `GDAL_SKIP` included. The registered-driver count on
the machine itself is unobserved; it needs `fly ssh`.
`VERIFY-SEC-17-19.md`.

---

## SEC-19 · MEDIUM · Deploy jobs run an unpinned flyctl binary holding a token that spans all three apps

**Evidence.**

- **Unpinned binary.** `deploy.yml:223, 240, 255` pin `superfly/flyctl-actions/setup-flyctl`
  to `ed8efb3` (SEC-9) but pass no `version:`. At that SHA the action resolves
  `latest` from `api.fly.io/app/flyctl_releases/…`. It downloads the tarball with
  `toolCache.downloadTool(url)` and **verifies no checksum** (`dist/index.js`
  lines 33852–33861, fetched from the pinned SHA). The binary then runs with
  `FLY_API_TOKEN` in its env (`deploy.yml:231, 246, 258`). Pinning the action pinned
  the installer, not the thing installed.
- **Token scope.** One `secrets.FLY_API_TOKEN` deploys `log0s-plotline-api`,
  `plotline-worker` and `plotline-titiler`. `fly tokens create deploy` is
  app-scoped, so this cannot be a single-app deploy token. It is an org-scoped
  token or a personal one, which also grants `fly ssh` and secret writes on
  every app in the org. The value was never read.
- **No workflow `permissions:` block.** The `GITHUB_TOKEN` gets the repository
  default, which this session couldn't read (UNVERIFIED).
- **Branch protection is off.** `GET api.github.com/repos/log0s/plotline/branches/main`
  returns `"protected": false`.
- **Build inputs resolved by mutable tag:**
  - `FROM python:3.12-slim` (`Dockerfile.fly:5`)
  - `COPY --from=ghcr.io/astral-sh/uv:0.11` (`Dockerfile.fly:15`) — the
    binary that installs every Python dependency. It does verify the lockfile
    hashes (`uv export` emits `--hash`; uv verifies by default).
  - `titiler:1.2.1` (SEC-17)

**Exploitability path.**

- A compromised flyctl release, or a compromise of the resolution endpoint, runs
  inside our deploy job with an org-wide token. That is the TanStack/LiteLLM
  shape: a release pipeline that trusts whatever is newest.
- The LiteLLM Oct-2026 root cause (a long-lived, broadly scoped token,
  [vendor postmortem](https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain))
  is the same class of credential as this one.
- Without branch protection, anyone who obtains push access to `main` ships to
  production unreviewed. Today that is only the owner's account.

**Confidence:** **high** for the binary and branch protection. **Medium** for
token scope (inferred from usage, not read).

**Fix sketch — S each.**

- `with: version: <x.y.z>` on all three setup steps.
- Three app-scoped deploy tokens, one per job (`fly tokens create deploy -a <app>`).
- Top-level `permissions: contents: read`.
- Base images by digest.
- Branch protection on `main` (Ryan's, in GitHub settings).

**Regression test.** Extend `test_every_action_is_pinned_to_a_commit_sha`:

- every `setup-flyctl` step must carry `with.version` matching `^\d+\.\d+\.\d+$`;
- every `FROM` / `COPY --from` in `Dockerfile.fly` must contain `@sha256:`;
- the workflow must have a top-level `permissions` key.

Each assertion fails when its fix is reverted.


**Later (2026-11-02): binary half resolved** in `aef5fe6`, committed, **not
deployed**. flyctl 0.4.123 is pinned and `sha256sum -c` runs before
extraction in all three jobs. Branch protection is done (Ryan, before
this batch). Token re-scoping is Ryan's. `permissions:` and the
`Dockerfile.fly` base-image digests are still open: they were out of
scope for this batch.

**Later (2026-11-02): exercised in CI.** `deploy-titiler`, run
`41503221445`: `flyctl.tgz: OK` before extraction. The `deploy-api` and
`deploy-worker` copies run first on the next `backend/**` push.
`VERIFY-SEC-17-19.md`.

**Later (2026-11-02): all three copies exercised.** Run `41506456853`
(push of `8c8e297`): `flyctl.tgz: OK` in `deploy-api` and `deploy-worker`
too. `VERIFY-PUSH-8c8e297.md`.

---

## SEC-20 · LOW-MEDIUM · The API/worker image trusts the compromised emSign chain and has not been rebuilt since 2026-09-07

**Evidence.** Deployed image `2253d63e…`, created 2026-09-07T03:23Z:

- **Python 3.12.14.** The CPython denylist for the compromised eMudhra
  intermediates is in 3.12.16, released 2026-10-25.
- **certifi 2026.05.20.** It still trusts emSign ECC Root CA - G3;
  GHSA-6q48-6c7w-9gw2 fixes it in 2026.10.18, with .19 recommended.
- **Debian `openssl 3.5.7-1~deb13u2`.** Python's `ssl` links it. 13 Debian
  advisories are fixed in `deb13u3` (2026-09-29, `raw/osv-image-api-debian-summary.tsv`).
  Most are QUIC/DTLS/server-side; CVE-2026-35189 (CRL distribution point parsing)
  is client-reachable.
- **pillow 12.3.0** (ADVISORIES §3, operator-only path), **anyio 4.13.0**,
  **pydantic-settings 2.14.1**.

No mechanism rebuilds the image unless `backend/**` changes (`deploy.yml:101-114`),
so base-image security updates land only by accident.

**Exploitability path.** It needs a network-position attacker on the
Fly → upstream path who holds a certificate issued under one of the compromised
intermediates. Under that attacker:

- httpx's TLS to Census (whose `key=` rides in the query string), Planetary
  Computer and the county portals is interceptable.
- redis-py's `rediss://` uses the system store. Neon's `sslmode=require`
  doesn't verify at all (SEC-12, already open).

**Confidence:** **high** on versions, **low** on likelihood.

**Fix sketch — S.**

- `uv lock --upgrade-package certifi anyio pydantic-settings` (pillow 13 is a
  major; separate, also S).
- Rebuild on `python:3.12.16-slim` by digest.
- Add a scheduled `workflow_dispatch`, or a monthly cron, that rebuilds with
  `force_deploy`.

**Regression test:** `test_ca_bundle_excludes_compromised_emsign`. Assert that
`"emSign ECC Root CA - G3"` is not in `open(certifi.where()).read()`. It runs in
the CI test job against the locked certifi and fails if the bump is reverted. Add
`sys.version_info >= (3, 12, 16)` once CI's setup-uv `python-version` is pinned
to the patch.

**Later (2026-11-02): partly mitigated by a rebuild, not by a fix.** The
push of `8c8e297` rebuilt the API/worker image (`9297f6bc…`, API v88,
worker v80) on `python:3.12-slim@sha256:b18b261e…`. It runs **Python
3.12.16** and **OpenSSL `3.5.7-1~deb13u3`**, so the CPython denylist and
the 13 Debian fixes are live. **Still open:** certifi 2026.05.20 (locked
in `uv.lock`) still trusts emSign ECC Root CA - G3; pillow, anyio and
pydantic-settings are unchanged; the base is still tag-pinned, and rolling
back to API ≤ v87 / worker ≤ v79 brings 3.12.14 back. The fix sketch
stands minus the Python step. `VERIFY-PUSH-8c8e297.md` step 3.

---

## SEC-21 · LOW-MEDIUM · Third-party basemap attribution is written with `innerHTML`, and plotline.land sends no CSP

**Evidence.**

- maplibre-gl **4.7.1** writes the attribution string with
  `this._innerContainer.innerHTML = attribHTML`
  (`node_modules/maplibre-gl/src/ui/control/attribution_control.ts:176`), with no
  sanitizer.
- The string comes from the style JSON fetched at runtime from
  `https://tiles.openfreemap.org/styles/liberty` (`MapView.tsx:29, 81`;
  `CompareView.tsx:22, 82`).
- `frontend/public/` has no `_headers`, so Cloudflare Pages serves no CSP
  (SEC-11, still open).
- npm audit labels this GHSA-jrc7-96c5-q579, a "DOM.sanitize bypass". That label
  doesn't fit 4.7.1, which has no sanitizer to bypass. The exposure underneath
  the label is real.

This was first written up in this morning's uncommitted
`../2026-11-dependency-advisories/REPORT.md` (its SEC-14). It is re-verified
here and given an ID, because that report's STATUS rows were reverted from the
working tree at 10:32. That is why it appears here and not there.

**Exploitability path.** A compromise of openfreemap's style endpoint (or its
CDN) yields script execution on plotline.land. There are no sessions or cookies
to steal. What's at stake is integrity of what visitors see, and the visitor's
IP plus searched addresses sent to an attacker's host.

**Confidence:** high (code read).

**Fix sketch.**

- **S:** `attributionControl: false`, plus a static `customAttribution` string
  we own.
- **M:** a CSP with `script-src 'self'`, `worker-src blob:`,
  `connect-src`/`img-src` limited to the API, openfreemap and
  planetarycomputer — that is the SEC-11 work.
- **M:** maplibre-gl 6.16 (two majors).

**Regression test:** a Vitest test that mocks the style fetch to return
`attribution: '<img src=x onerror="window.__xss=1">'`, mounts `MapView`, and
asserts the attribution node contains no `<img>` element. It fails if the
control goes back to rendering upstream HTML.

---

## SEC-22 · LOW · The dev stack listens on every interface with default credentials

**Evidence.**

- `frontend/vite.config.ts:15` sets `server.host: "0.0.0.0"` for every `vite`
  run, not only inside Docker.
- `docker-compose.yml` publishes these ports on all interfaces:
  - `5432` (Postgres, `plotline`/`plotline`)
  - `6379` (Redis, no auth)
  - `8000` (API)
  - `8001` — a stock Titiler with no token: a full open fetcher
  - `5173` (Vite)
- Vite 5.4.21 carries CVE-2026-39365 for 5.x per the GHSA (disputed by the CVE
  text) with `--host` met, plus CVE-2026-112945 (precondition not met). Neither
  has a 5.x fix.

**Exploitability path.**

- Anyone who can reach this machine's interfaces gets the dev database, the
  queue, and a fetcher that runs inside the dev network.
- On WSL2 with the default NAT networking that means the Windows host; with
  mirrored networking, the LAN. This session didn't check which mode is in use.

**Confidence:** high on config, low on reachability.

**Fix sketch — S.** Prefix every published port with `127.0.0.1:`. Make
`server.host` conditional on an env var that only the compose service sets.
The Vite major bump goes in the toolchain batch.

**Regression test:** a pytest that loads `docker-compose.yml` and asserts every
`ports` entry starts with `127.0.0.1:`. Deleting a prefix fails it.

---

## SEC-23 · LOW · No install-time controls: no cooldown, lifecycle scripts run everywhere

**Evidence.** There is no `.npmrc` (no `ignore-scripts`, no release-age
cooldown). CI runs plain `npm ci` (`deploy.yml:208`). `backend/pyproject.toml`
sets no `[tool.uv] exclude-newer`. How Cloudflare Pages installs is UNVERIFIED.
The IoC sweep is clean (ADVISORIES §2), so this is about the next wave, not a
past one.

**Exploitability path.** The TanStack, axios and June PyPI payloads all ran at
install or import time. Any lock refresh that resolved a malicious version
during its first hours would have executed it on the dev machine and in CI.

**Mitigations already in place:**

- lockfiles everywhere, refreshed rarely (5 and 3 revisions in history);
- hash-verified uv installs;
- the CI test jobs hold no secrets (`FLY_API_TOKEN` is scoped to deploy steps).

**Confidence:** high.

**Fix sketch — S.**

- Add `frontend/.npmrc` with `ignore-scripts=true`. Check first that esbuild's
  platform binary still installs: it ships via `optionalDependencies`, but
  confirm with a clean `npm ci && npm run build`.
- Add a release-age cooldown for lock refreshes. The npm and uv support for
  relative-duration options is UNVERIFIED for the versions in use; an absolute
  `exclude-newer` timestamp, bumped on purpose, works on any uv.

**Regression test:** assert `frontend/.npmrc` contains `ignore-scripts=true`.

---

## Accepted items: does anything new change their premise?

| Item | Premise it rests on | Verdict |
|---|---|---|
| **M2** (XFF branch unreachable) | Fly's proxy overwrites `Fly-Client-IP` on every request | **Not changed by any advisory.** BadHost concerns `Host`, not `Fly-Client-IP`. The API's Starlette is patched, and the limiter keys on the route template, which a malformed Host can't move (`raw/lab/badhost-api.txt`). The premise itself has been **UNVERIFIED since 2026-08-22** (2026-08 FINDINGS §7), and nothing since verified it. PROD-PROBES **P4** tests it in 121 requests. If P4 shows `121 204`, M2 reopens. |
| **M9** (public Titiler routing) | "the accept stands with the token as its precondition" | **The precondition is now load-bearing for SEC-17 and SEC-18, and it is unverified in production.** No advisory changes the routing question. P1 decides whether the accept is currently valid. |
| **L10** (upstream URLs in client errors) | no credential leak to clients | **Holds.** The lab shows Titiler error bodies can embed full `/vsicurl/<url>` strings, but the API answers every Titiler failure with a curated `502 "Titiler upstream error"` (`api/v1/imagery.py:421-452`). Bodies go only to logs, through the SEC-4 scrubber. |
| **N5 / P5** (host allowlist) | the allowlist constrains what Titiler fetches | **Narrowed, not reversed.** It constrains the first hop only. SEC-18's VRT case is a second hop it can't see. The prompt placed N5 in SOURCE-LANDSCAPE, but no such file exists in the repo (REMEDIATION-1.md:10 already says so). N5 lives in `../2026-08-source-inventory/INVENTORY.md` §N5 and STATUS.md. |

---

## Checked and found clean

| Step | What | How | Result |
|---|---|---|---|
| 1 | Deployed equals HEAD | `/health` sha, `fly image show` GH_SHA ×2, Titiler digest + `fly config show` vs `fly.titiler.toml` | `bac725c..a45caf3` is docs-only; Titiler config identical |
| 2 | Installed equals locked | `pip freeze` in the deployed image vs `uv export --frozen` | identical (colorama is Windows-only) |
| 6 | IoCs in lockfiles, lock history, both images, installed `node_modules` | `raw/IOC-CHECK.txt`; `find`/`grep` for `router_init.js`, `"@tanstack/setup"` | none |
| 7 | `pull_request_target` / `workflow_run` triggers | read `deploy.yml` | none (push to main + `workflow_dispatch`) |
| 7 | Cache poisoning | read | `setup-node` npm cache and setup-uv cache feed only the test jobs; deploys build remotely on Fly from source and consume no Actions cache. Only `main` pushes write caches |
| 7 | Secrets per job | read | `FLY_API_TOKEN` only in the three deploy steps' `env`; test jobs hold none |
| 7 | Script injection | read, plus a local test of 12 revision strings | The one externally sourced value interpolated into `run:` is the health endpoint's sha (`deploy.yml:43-83`). It must pass `git cat-file -e "$x^{commit}"` and `merge-base --is-ancestor` first. Every string carrying `$(…)`, backticks or `:/` regex alternations was rejected; it also presupposes a compromised production API. Clean, noted |
| 8 | Secrets in history | gitleaks 8.30.1 over 387 commits / all refs + working tree; custom grep for Neon/Upstash/Fly/GitHub/AWS token shapes over `git log -p --all` | 1 history hit: `backend/tests/test_redact.py:16`, `c3n5…` (len 25), a synthetic fixture **not equal** to the real key (compared in-process, never printed). Working tree adds `.env` `CENSUS_API_KEY` `e2b6…` (len 40), gitignored and **never committed** (`git log --all -- .env` is empty). Custom grep: 16 lines, all local defaults or placeholders |
| 9 | Secrets each app's code reads | grep over `settings.*` | Matrix in PROD-PROBES P6. The worker never calls Titiler and doesn't read `CORS_ORIGINS`. Titiler needs only its token. The presence check is P6 (Ryan) |
| 10 | BadHost on the API | local deployed digest; malformed Host ×3 on a rate-limited route; Redis keys inspected | patched (1.6.0); limiter key unaffected. No `TrustedHostMiddleware` anywhere, and none needed for this |
| 10 | Other `request.url` consumers | `grep -rn 'request\.url\|base_url\|url_for' backend/app` | only `rate_limit.py:51`, a fallback that never runs inside a route. The Landsat callback URL is built from `settings.api_internal_url`, not the request |
| 11 | Titiler token semantics | lab: with token set, every route incl. `/healthz` → 401 | app-wide dependency (`titiler/application/main.py:81-100`); BadHost can't bypass it. The comparison is `!=`, not constant-time, which is immaterial over the network |
| 11 | `/mosaicjson` disabled | lab with production env | 404, no fetch |
| 11 | Token reaches the browser? | grep `titiler_url`, `titiler_params` | no; every Titiler call is server-side (`api/v1/imagery.py:514-706`, `preview_renderer.py:98-119`) |
| 12 | Query-language injection | read `county_adapters.py:48-58, 256-850` | ArcGIS `where` and SoQL `$where` interpolate through `_escape_sql_literal` (quote doubling, non-printables stripped, 100-char cap); values go as httpx `params=`. LIKE wildcards unescaped is **L3, already recorded** (cost-only, zero stranger records attached). CKAN `q` is full-text. Photon and Census take user text as URL params, no query language |
| 12 | Raw SQL | `grep -E 'text\(|execute\(f'` | the two f-strings in `app/` (`featured.py:57`, `services/imagery.py:1752`) interpolate generated `:p{i}` placeholder names only; values are bound. Scripts are operator-only and identifier-validated (`scripts/shared/probe.py:78`) |
| 13 | Celery | read `celery_app.py:24-49` | `task_serializer`/`result_serializer`/`accept_content` all `json`. One task, `fetch_imagery_timeline.delay(str(request.id))` (`services/imagery.py:392`); no request-controlled task name or args. `rediss://` gets `ssl_cert_reqs=CERT_REQUIRED`. *Note:* no validator **requires** `rediss://` in production, so a secret edit to `redis://` would silently run plaintext. Prod used `rediss` at the 2026-08-22 probe; not re-checked (no ssh) |
| 14 | DB roles | read; 2026-08 probe #19 | API and worker both connect with `DATABASE_URL` = `neondb_owner`: **SEC-12, open, unchanged.** The MCP path doesn't exist, and the read-only role PREFLIGHT §7 specifies hasn't been created in code (no `GRANT` in migrations). Nothing to verify by grants until it exists |
| 15 | CORS | `main.py:53-62`; Titiler image | API: origins from settings, `allow_credentials=False`. Titiler: `*` with `allow_credentials=True` (stock), no cookies anywhere, token in the query: no impact |
| 15 | Exception leakage | read `_fetch_titiler`, route handlers | no custom exception handler; FastAPI's default 500 has no traceback; Titiler and geocoder failures curated to 502 text (L10 scope) |
| 15 | Work-triggering endpoints | route inventory | `POST /geocode` (10/min, fail-closed, admission cap), `POST /parcels/{id}/timeline` (20/min, fail-closed, admission), `POST …/warmup` (120/min, creates nothing). **No ingest, heal, or admin endpoint exists**; heals are `fly ssh` scripts. `/docs`, `/redoc`, `/openapi.json` public: SEC-11, open |
| 15 | Frontend markup | grep `innerHTML` in `src/` | two static marker templates (`MapView.tsx:121`, `CompareView.tsx:114`), no data interpolated; the third-party path is SEC-21 |

## Not done, and why

- `fly secrets list`: denied; P6.
- Prod probes: by instruction; PROD-PROBES.md.
- Debian OS packages in the API image were checked through OSV's batch API, not
  osv-scanner (whose dpkg extractor didn't fire on the exported rootfs;
  `raw/EXIT-CODES.txt`).
- The `rasterio.libs` native libraries were inventoried by `strings` and
  matched to advisories by hand for GDAL only; libcurl 8.17.0, OpenSSL 3.6.0,
  libhdf5 1.14.6, and libnetcdf 4.9.3 were not matched against their own
  advisory feeds. The SEC-17 image bump replaces them all; until then this is a
  gap.
- Weaponized expression-injection payloads against numexpr 2.14.1: not attempted.
