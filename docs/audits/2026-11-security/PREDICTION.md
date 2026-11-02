# Security audit 2026-11 — predictions

Written 2026-11-02, after the Phase 0 gate and inventory, **before any scanner
ran and before any advisory was read at its primary source**. Scored in
`ADVISORIES.md`. This file is not edited after its commit.

## What the predictions rest on (Phase 0 inventory)

| | API (`log0s-plotline-api`) | Worker (`plotline-worker`) | Titiler (`plotline-titiler`) | Frontend |
|---|---|---|---|---|
| Deployed | `GH_SHA=bac725c`, digest `sha256:2253d63e…`, built 2026-09-07 | `GH_SHA=bac725c`, digest `sha256:e0eee73e…` | stock `ghcr.io/developmentseed/titiler:1.2.1`, digest `sha256:9cc74708…`, no GH_SHA (not built by CI) | Cloudflare Pages, from `frontend/package-lock.json` |
| Base | `python:3.12-slim` (tag, not digest), Debian 13 | same image content as API | Debian 13 | — |
| Python | **3.12.14** | 3.12.14 | **3.14.3** | — |
| pip | 25.0.1 (base image; build-time only, `uv` installs the deps) | 25.0.1 | 26.0.1 | — |
| certifi | 2026.05.20 | 2026.05.20 | 2026.2.25 (also GDAL's curl CA bundle) | — |
| starlette | 1.6.0 | 1.6.0 | **0.52.1** | — |
| pillow | 12.3.0 | 12.3.0 | not installed | — |
| GDAL | not installed | not installed | **3.12.1**, bundled in the rasterio 1.5.0 wheel; netCDF 4.9.3 and HDF5 1.14.6 bundled; 147 drivers incl. `netCDF`, `HDF5`, `VRT`; no `HDF4` | — |
| vite | — | — | — | 5.4.21 (dev dependency) |

`HEAD` is `a45caf3`. `bac725c..a45caf3` is 14 commits that touch nothing outside
`docs/`, so the running API and worker code is HEAD's code. Installed packages
in the API image match `backend/uv.lock` exactly (except `colorama`, which is
Windows-only). API and worker `pip freeze` are identical. The MCP server is
**not in the repo**: no `mcp` dependency and no code. The pre-flight (2026-09-11)
designed against `mcp` 2.2.0, stateless Streamable HTTP, JSON responses.

## Step 5 — advisories

| # | Advisory | Prediction | One line of reasoning |
|---|---|---|---|
| 5a-1 | Starlette CVE-2026-48710 "BadHost" (fixed 1.0.1) | **API: not affected. Titiler: affected by version, not exploitable for an access decision.** | API is 1.6.0. Titiler's 0.52.1 is below the fix, but its access token is a query-parameter check, not a path check. The API's limiter keys on the route template and uses `request.url.path` only as a fallback that never fires inside a route (`rate_limit.py:51`). |
| 5a-2 | Starlette CVE-2026-48817 HTTPEndpoint dispatch (fixed 1.1.0) | **API: not affected. Titiler: affected by version, not reachable.** | FastAPI routes are not `HTTPEndpoint` subclasses, and neither codebase defines one. |
| 5a-3 | Starlette CVE-2026-48818 StaticFiles SSRF, Windows-only (fixed 1.1.0) | **Not applicable.** | Both run on Linux. The API mounts `StaticFiles` (`main.py:75`), and Titiler does not. |
| 5b-1 | MCP CVE-2026-52869 (fixed 1.27.2) | **Not applicable (not merged); 2.2.0 would be unaffected.** | No MCP code ships. The designed version is above the fix. |
| 5b-2 | MCP CVE-2026-52870 (fixed 1.27.2) | **Not applicable; 2.2.0 unaffected.** | Same. |
| 5b-3 | MCP CVE-2026-59950, WebSocket (fixed 1.28.1) | **Not applicable; 2.2.0 unaffected, and WebSocket is not the designed transport.** | The design is Streamable HTTP. |
| 5b-4 | MCP CVE-2026-59951, stateful Streamable HTTP (fixed 1.30.0 / 2.2.0) | **Not applicable; 2.2.0 unaffected.** | The modern protocol leg is unconditionally stateless. The legacy leg is stateful unless `stateless_http=True`, which matters only for an older pin. |
| 5c-1 | CPython CVE-2026-115557, ssl denylist for eMudhra/emSign (3.12 fixed in 3.12.16) | **API/worker: affected (3.12.14). Titiler: affected if the 3.14 fix is later than 3.14.3.** | Version arithmetic. Exploitation needs a MITM holding a certificate from the compromised CA. |
| 5c-2 | certifi ≥ 2026.10.19 for the same CA compromise | **Affected in all three images.** | 2026.05.20 and 2026.2.25 both predate the fix. httpx in the API/worker and GDAL's curl in Titiler both trust certifi's bundle. |
| 5c-3 | pip ≥ 26.2.2 for the same CA compromise | **Affected by version in all three images; build-time exposure only.** | pip 25.0.1 / 26.0.1. Nothing invokes pip at runtime. Dependencies install through `uv`, which has its own TLS stack. |
| 5d | Pillow CVE-2026-112900 / -112393 / -112403 (fixed 13.0.0) | **Affected by version in the API/worker image; not reachable from any network request. EPS RCE not exploitable.** | Pillow 12.3.0. Its one caller, `preview_renderer.py:130`, runs only from the operator script `scripts/seed_featured.py` on Titiler-rendered bytes. No Ghostscript in the image, which is the historical EPS precondition. Titiler has no Pillow. |
| 5e | GDAL USN-8812-1, netCDF and HDF-EOS drivers | **The USN doesn't apply as written (Ubuntu package; ours is a wheel-bundled GDAL on Debian). The upstream bugs probably do apply to 3.12.1, but only behind a compromised upstream or a leaked/unset Titiler token.** | The netCDF and HDF5 drivers are compiled in. `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` filters the URL's extension, not the content, so I expect GDAL to open a `.tif` URL whose bytes are another format if that driver can read through `/vsicurl/`. Least confident line in this file. |
| 5f | Vite CVE-2026-39363 / -39364 / -39365, CVE-2026-112945 | **Affected (dev-only), and the host precondition is met unconditionally.** | vite 5.4.21. `vite.config.ts` sets `server.host: "0.0.0.0"` for every `vite` invocation, and compose publishes `5173:5173` on all interfaces. Never in production: Pages serves the static build. |

## Step 6 — supply-chain IoCs

| # | Group | Prediction | One line of reasoning |
|---|---|---|---|
| 6a-1 | Mini Shai-Hulud TanStack wave (2026-05-11) | **Not affected, at HEAD and in history.** | Only `@tanstack/react-query` / `query-core` are in the lock. That is the query family, reported unaffected. |
| 6a-2 | axios compromise (2026-03-31) | **Not affected.** | axios is in neither the lock nor its history. The app uses `fetch`. |
| 6a-3 | OSV `MAL-` ids on the npm lock | **None.** | |
| 6b | PyPI: litellm 1.107.0, lightning 2.6.2/2.6.3, mistralai 2.4.6, telnyx 4.87.1/4.87.2, June 2026 science-package wave | **All absent from `uv.lock`, its history, and every image.** | No LLM, ML, or telephony dependency. The scientific packages we pull (shapely, pyproj, numpy in Titiler) I expect off the wave's list. |
| 6c | Cooldown / minimum-release-age / ignore-scripts | **None configured anywhere.** | No `.npmrc`; CI runs plain `npm ci`; `uv` has no `exclude-newer`. |
