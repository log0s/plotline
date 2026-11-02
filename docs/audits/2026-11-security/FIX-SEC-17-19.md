# Fix batch — SEC-17, SEC-18, SEC-19 (2026-11-02)

**Mode:** execute, lab only. No production requests, no `fly ssh`, no secrets. The
lab Titiler token is the literal `labtoken-not-a-real-secret`. Real-source SAS
tokens were minted from Planetary Computer's public endpoint into a scratch dir
and are redacted from every committed file. **Nothing is pushed or deployed.**

## Outcome

| Finding | State | Commit |
|---|---|---|
| SEC-17 stale Titiler image | **Fixed, pending deploy.** It has residuals (GDAL/Python/certifi lag), see §Residuals | `36531b1` |
| SEC-18 driver selection by content | **Partially fixed, pending deploy.** HDF5, netCDF and 137 other drivers are gone. **The VRT half stays open** | `36531b1` |
| SEC-19 unpinned flyctl | **Binary half fixed, pending deploy** | `aef5fe6` |
| Regression tests | 7 tests, 9 delete-the-fix mutations, all red when mutated | `1c3fe32` |

## Where this differs from the prompt or the fix sketch

1. **`GDAL_SKIP=VRT` "at minimum" isn't possible.** Lab, before any config
   was written: rasterio 1.5.1 builds an in-memory `<VRTDataset>` string and
   opens it in `_calculate_default_transform`. Skipping VRT therefore fails
   every tile that needs reprojection, which is all four sources:
   - NAIP z16 tile with no skip: 200, 156 KB.
   - With `GDAL_SKIP=VRT`: `CPLE_OpenFailedError`.

   Titiler's own security page recommends exactly this, and it is wrong for
   the current rasterio. The allowlist keeps VRT. The fixture still opens and
   still fetches its nested `.tif`.

   **What would close it:** a reader that calls `rasterio.open(url,
   driver=["GTiff"])`. Only the user URL gets restricted; rasterio's internal
   VRT string still works. That means a custom Titiler image (a `Dockerfile`
   plus a small `main.py`), which changes how Titiler is deployed. The prompt
   ruled that out, so it's **your decision**. Until then, the VRT risk rests
   on the token, which P1 says is set.
2. **Allowlist mechanism.** GDAL 3.12 has no positive driver list; `strings`
   on `libgdal` shows only `GDAL_SKIP` and `GDAL_DRIVER_PATH`. So the
   allowlist is written as its complement: every driver registered in the
   pinned image except `GTiff, MEM, PNG, JPEG, VRT`. That's 142 names.
   - The sketch's alternative was a custom reader with `allowed_drivers`.
     It is the same thing as item 1, so it's deferred with it.
   - The test pins the image's driver inventory. A digest bump can't bring
     in an unlisted driver silently: the test fails until the list is
     regenerated.
3. **Two settings the prompt didn't ask for, both required by 2.x:**
   - `TITILER_API_DISABLE_ZARR=TRUE`: 2.0 added a default-on `/zarr` router,
     with xarray readers outside GDAL.
   - `PORT=8000` with `internal_port = 8000`: 2.x runs as uid 65532. Upstream's
     Dockerfile says low ports need an unprivileged-port sysctl, or a `PORT`
     of 1024 or above. The API reaches Titiler at
     `https://plotline-titiler.fly.dev` (`fly.toml:13`), so the container
     port is invisible to it.

   Deployment is otherwise unchanged: still the stock image, directly from
   `fly.titiler.toml`.
4. **flyctl:** the prompt said "pin a release version". I replaced
   `setup-flyctl` instead of adding `with: version:`, because the action
   verifies no checksum even with a version set. That's the whole of SEC-19's
   binary half. Version 0.4.123 (2026-10-26) rather than 0.5.1, which was 4
   days old and starts a new minor line. Nothing else in the workflow changed.
5. **docker-compose.yml** now mirrors the digest, `GDAL_SKIP` and
   `DISABLE_ZARR` (sketch item). It stays on :80 because Docker lets non-root
   bind low ports. Checked locally: healthy, uid 65532, 5 drivers.

## Versions (read inside each image, `raw/lab-fix/versions.txt`)

| Component | Before (`titiler:1.2.1`, deployed) | After (`titiler@sha256:5b739117…`, tag 2.4.0) | Target from FINDINGS |
|---|---|---|---|
| titiler | 1.2.1 | **2.4.0** (latest release, 2026-09-21) | current |
| starlette | 0.52.1 | **1.6.0** | ≥ 1.3.1 ✔ |
| rio-tiler | 8.0.5 | **9.4.4**, with the AST expression allowlist (`rio_tiler/expression.py:14-49`) | ≥ 9.1.0 ✔ |
| GDAL (rasterio wheel) | 3.12.1 (rasterio 1.5.0) | **3.12.4** (rasterio 1.5.1) | ≥ 3.13.1 ✘ (no stock image has it) |
| Python | 3.14.3 | 3.14.7 | ≥ 3.14.10 ✘ |
| numexpr | 2.14.1 | 2.14.2 | — |
| fastapi | 0.135.1 | 0.141.1 | — |
| certifi (GDAL CA bundle) | 2026.2.25 | 2026.7.22, still has emSign ECC Root CA - G3 | ≥ 2026.10.18 ✘ |
| uid | 0 | **65532** | — |
| GDAL drivers registered | 147 | **5** (`GTiff, JPEG, MEM, PNG, VRT`) | — |
| pip-audit (2.10.1, `--no-deps`) | 27 advisories, 8 packages | 22 advisories, 7 packages (aiohttp, certifi, multidict, oauthlib, opentelemetry-api, pyasn1, urllib3; `raw/lab-fix/pip-audit-titiler-2.4.0.txt`) | — |
| flyctl in CI | `latest` at run time, unverified | **0.4.123**, tarball sha256 `08d8b45e…94bc` | pinned + verified ✔ |

The flyctl hash is checked three ways and all agree: local `sha256sum`, the
release's `checksums.txt`, and GitHub's asset `digest` field.

Note on the "before" image: the local 1.2.1 has RepoDigest `8c1b3428…` (the
index). The audit's `9cc74708…` is the amd64 manifest. They have the same
build date (2026-03-09) and identical versions.

## Lab proof

Harness: `raw/lab-fix/run_lab.sh` and `probe_fix.py`.

- **Fixture instances** run on an `--internal` network and use the audit's
  `raw/lab/www/` fixtures.
- **Real-source instances** run on a plain bridge.
- **After env:** generated from the committed `fly.titiler.toml`, so the lab
  tests what deploys. **Before env:** the audit's `raw/lab/fly-titiler.env`.
- **"No-fix"** is the same 2.4.0 image with `GDAL_SKIP` removed.

All requests carry the lab token unless marked anonymous.

### (a)/(b) driver surface — SEC-18

| Case | Command | Before (1.2.1) | After (2.4.0 + fix) | No-fix (2.4.0) | Expected |
|---|---|---|---|---|---|
| HDF5 bytes at `.tif` | `GET /cog/info?url=…/nc4.tif` | 500 `'NoneType'…to_authority` (HDF5Image parsed it, then failed on CRS) | **500 "not recognized as being in a supported file format"** | 500 `to_authority` | refused before parse ✔ |
| same, driver identity | `rasterio.open('/www/nc4.tif')` (`driver-identity.txt`) | — | **refused** | `driver=HDF5Image` | refused ✔ |
| netCDF classic, userfaultfd available | `GET /cog/info?url=…/nc_classic.tif`, `--security-opt seccomp=unconfined` | **200, driver=netCDF** | **500 not recognized** | 200, driver=netCDF | refused ✔ |
| VRT at `.tif` → nested `/vsicurl/http://audit-canary…/canary.tif` | `GET /cog/info?url=…/vrt_ssrf.tif` + canary `/_hits` | 200, driver=VRT, canary +2 | **200, driver=VRT, canary +2** | 200, VRT, +2 | **fails to open ✘, as predicted** (§Differs 1) |
| VRT pixels | `GET /cog/statistics?url=…/vrt_ssrf.tif` | 200, values = canary's (7) | **200, values = canary's** | 200 | ✘ (served from VSI cache, so +0 hits) |
| VRT, nested source without `.tif` | `/cog/info?url=…/vrt_ssrf_noext.tif` | 200 info, canary +0 | 200, +0 | 200, +0 | nested fetch refused by the extension filter ✔ |
| `VRTRawRasterBand` → `/proc/self/environ` | `/cog/statistics?url=…/vrt_raw_environ.tif` | 500 (SIBLING_OR_CHILD default) | 500 | 500 | refused ✔ |
| Extension filter | `/cog/info?url=…/notallowed.png` | 500 refused pre-fetch | 500 | 500 | refused ✔ |

The first scored pass had a **harness bug**. The fixture's nested source
is `audit-canary`, and the canary container wasn't aliased to that name.
So every VRT row read "Read failed / 0 hits" on every instance, which
would have looked like a fix. The bad pass is kept as
`run1-fixtures-out-canary-dns-miss.tsv`; the alias was added and the
pass re-run. Every table here comes from the re-run (`fixtures-out.tsv`).

### (c) one real asset per production source — `real-out.tsv`

Each request uses the exact endpoint shape and params the API sends
(`api/v1/imagery.py:323-325, 513-515, 586-596, 682-706`;
`preview_renderer.py:97-119`).

| Source / shape | Asset | Before | After | Expected |
|---|---|---|---|---|
| NAIP `/cog/tiles/WebMercatorQuad/16/…` bidx 1,2,3 rescale 0,255 | `co_m_3910417_nw_13_030_20230925` (UTM 13N) | 200 jpeg 24,832 B | **200 jpeg 24,832 B** | 200 image ✔ |
| Sentinel-2 `/cog/tiles/…/13/…` | `S2C_MSIL2A_20261029…T13TEE` TCI | 200 png 68,069 B | **200 png 68,069 B** | ✔ |
| USGS topo `/cog/tiles/…/13/…` | Denver East 1:100k 1981 (NAD27) | 200 jpeg 23,699 B | **200 jpeg 23,699 B** | ✔ |
| Landsat `/stac/tiles/…/12/….png` assets red,green,blue, nodata 0, rescale 7000,14000 ×3 | `LC08_L2SP_034032_20261023` (signed item JSON served locally, standing in for the `/stac` callback) | 200 png 189,854 B | **200 png 189,854 B** | ✔ |
| Preview `/cog/bbox/…/512x512.png` | NAIP | 200 png 621,686 B | **200 png 621,686 B** | ✔ |
| Warmup `/cog/info` | USGS topo | 200, GTiff | 200, GTiff | ✔ |
| Warmup `/stac/info` | Landsat | 200 | 200 | ✔ |

Byte counts are identical for every image, before and after. That is strong
evidence the render path didn't change, not just that it still returns 200.

### SEC-17 — access, BadHost, expressions (`fixtures-out.tsv`)

| Case | Command | Before | After | Expected |
|---|---|---|---|---|
| Anonymous health | `GET /healthz` (no token) | 401 | **401** | 401 ✔ |
| BadHost | `GET /tileMatrixSets`, `Host: lab/badhost-probe?x=` | 200, links **reflect** `/badhost-probe/` | **200, no reflection** | no reflection ✔ |
| Mosaic / zarr | `/mosaicjson/info`, `/zarr/info` | 404 / 404 | 404 / 404 | 404 ✔ |
| Benign expression | `expression=b1*2`, `where(b1>0,1,0)` | 200 | 200 | 200 ✔ |
| Predicted "accepted before" | `expression=b1*0+int(True)` | **500** (numexpr: `'VariableNode' object is not callable`) | 400 `disallowed function: 'int'` | 200 → reject: **falsified on the before side** |
| Accepted before, rejected after (post-hoc, not predicted) | `expression=b1<<1` | **200** | **400** `disallowed expression: LShift` | ✔ |
| same | `expression=b1 is b1` | **200** (Python `is` evaluated inside numexpr's `eval`) | **400** `disallowed expression: Is` | ✔ |
| Dunder | `expression=b1.__class__` | 500 numexpr denylist | 400 `disallowed expression: Attribute` | rejected ✔ |

The `b1 is b1` row is the useful one. It shows 1.2.1 handed arbitrary Python
AST to `eval` behind numexpr's string denylist, which is the GHSA's premise.
2.4.0 rejects it at the AST, before numexpr sees it.

### SEC-19 — install step, run locally (`flyctl-install-step.{sh,txt}`)

The script is the `run:` block extracted verbatim from `deploy-titiler`,
plus `set -e`, which is GitHub's default `bash -e`.

| Case | Command | Result | Expected |
|---|---|---|---|
| Pinned hash | `FLYCTL_VERSION=0.4.123 FLYCTL_SHA256=08d8b45e… bash flyctl-install-step.sh` | `OK`, exit 0, extracted, PATH written, `flyctl v0.4.123` | ✔ |
| One digit changed | `FLYCTL_SHA256=18d8b45e…` | `FAILED`, exit 1, **nothing extracted, PATH untouched** | ✔ |

## Regression tests

These are config tests; they run in CI's `test` job. The compose container
doesn't mount the repo root, so there they skip, like the existing
`test_workflow_pins` test. Here they were run in the api container with
`.github/`, `fly.titiler.toml` and `docker-compose.yml` mounted at `/`:
7 passed. Full suite: 749 passed, 22 skipped. `ruff check` and `format` are
clean, and `mypy app/` is clean.

Delete-the-fix (`raw/lab-fix/delete-the-fix.txt`). Each mutation was
applied alone, then the file restored:

| Mutation | Fails |
|---|---|
| M1 `GDAL_SKIP` deleted from `fly.titiler.toml` | 3 tests |
| M2 `HDF5Image` dropped from the list (allowlist widened by one) | 3 |
| M3 image back to `titiler:1.2.1` | 2 |
| M4 `TITILER_API_DISABLE_ZARR` deleted | 1 |
| M5 `GDAL_SKIP` deleted from `docker-compose.yml` only | 1 |
| M6 `sha256sum -c` line deleted from one job | 1 |
| M7 `deploy.yml` reverted to `setup-flyctl` | 1 |
| M8 checksum moved after `tar -x` | 1 |
| M9 `FLYCTL_VERSION: "latest"` | 1 |
| M0 unmodified | 0 (7 passed) |

The lab harness itself isn't a CI test, because it needs Docker and
egress. Re-run it with `raw/lab-fix/run_lab.sh <dir with urls.json and
items/>` when the digest is bumped.

## Files changed

| File | Change |
|---|---|
| `fly.titiler.toml` | image by digest; `TITILER_API_DISABLE_ZARR`, `PORT=8000`, `GDAL_SKIP` (142); `internal_port = 8000`; rio-tiler cache comment re-verified for 9.4.4 |
| `docker-compose.yml` | titiler: same digest, `GDAL_SKIP`, `DISABLE_ZARR` |
| `.github/workflows/deploy.yml` | top-level `FLYCTL_VERSION`/`FLYCTL_SHA256`; three `setup-flyctl` steps → download, `sha256sum -c`, extract |
| `backend/tests/test_titiler_config.py` | new, 5 tests |
| `backend/tests/test_workflow_pins.py` | `+test_flyctl_is_pinned_and_checksum_verified_before_it_runs` |
| `docs/audits/2026-08-second-audit/STATUS.md` | predictions (`bb28a5b`); rows, scoring, P1 note, discoveries, M9 note |
| `docs/audits/2026-11-security/FINDINGS.md` | dated Resolved/Later annotations on SEC-17/18/19 |
| `docs/audits/2026-11-security/raw/lab-fix/` | harness, env files, outputs |

The API and worker code are untouched. See deploy step 3 for the image
side effect.

## Residuals (all in STATUS.md)

- **SEC-18 VRT half.** See §Differs 1. It now rests on the token, and the
  M9 note says so.
- **GDAL 3.12.4 < 3.13.1** (CVE-2026-49014, netCDF). The code is still
  linked, but the driver is unregistered and the zarr/xarray router is off.
  No stock Titiler has a newer GDAL; `titiler:latest`, built from main
  today, isn't a release.
- **Python 3.14.7 < 3.14.10** (CVE-2026-115557).
- **certifi 2026.7.22 is GDAL's CA bundle and still trusts emSign G3.** The
  image's system bundle (`/etc/ssl/certs/ca-certificates.crt`) doesn't have
  that root.
  - Candidate fix: `GDAL_CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`
    in `[env]`. **Untested** against PC/TNM.
- **`MAX_WORKERS` / `WORKERS_PER_CORE` are inert.** Both images' CMD uses
  `WEB_CONCURRENCY`, which defaults to 1, so production has run one worker
  per machine all along. Left as-is to preserve behaviour.
- **SEC-19:** token re-scope (yours), top-level `permissions:`, and
  `Dockerfile.fly` base digests are still open.

## What you need to do after push

Pushes and deploys are yours. The order matters because of the path filters:

1. **Push through `aef5fe6` first:** `git push origin aef5fe6:main`.
   - That push contains `bb28a5b`, `36531b1` and `aef5fe6`. The only filter
     it matches is `titiler` (`fly.titiler.toml`), so **only
     `deploy-titiler` runs.**
   - That run is also the first real execution of the new flyctl install
     step. If the download or checksum fails, the job stops before any
     release.
2. **Confirm Titiler:**
   - Anonymous `curl -s -o /dev/null -w '%{http_code}' https://plotline-titiler.fly.dev/healthz` → **401**.
   - One tile per source loads in the app: NAIP, Sentinel-2, Landsat, USGS
     topo, e.g. one parcel timeline.
   - `fly releases -a plotline-titiler` shows the new image.
   - **Watch for:** the port move (the machine must listen on 8000, so check
     the logs for `Listening at: http://0.0.0.0:8000`), and Fly accepting a
     digest-form `image`. Neither can be verified outside Fly.
   - **Rollback:** `git revert 36531b1` and push. Never a local
     `fly deploy`.
3. **Then push the rest** (`1c3fe32` and the docs commit).
   - `backend/tests/**` matches the `backend/**` filter, so **this push
     rebuilds and redeploys API and worker.** The app code is identical, but
     the rebuild re-resolves `python:3.12-slim` and `uv:0.11` (SEC-19's
     open half).
   - Nothing else depends on the Titiler deploy.
   - If you'd rather not rebuild API/worker now, hold this push. The tests
     only guard config that is already live after step 1.

After step 2, the STATUS rows can move from "pending deploy" to deployed
with the date.

## Commits

| Hash | What |
|---|---|
| `bb28a5b` | docs(status): predictions, before the lab run |
| `36531b1` | fix(titiler): 2.4.0 by digest, driver allowlist, /zarr off |
| `aef5fe6` | fix(ci): flyctl 0.4.123, sha256 verified before it runs |
| `1c3fe32` | test: Titiler pin, allowlist, flyctl checksum |
| *(the commit adding this file)* | docs: report, lab outputs, STATUS rows, FINDINGS annotations |
