# Security audit 2026-11 — advisories

Date 2026-11-02. HEAD `d226713` (PREDICTION.md). Deployed code is `bac725c`; the gap is docs-only.
Versions are read from the **deployed images**, pulled by digest and run
locally with `--network none`:

- API/worker: `registry.fly.io/log0s-plotline-api@sha256:2253d63e…` and `plotline-worker@sha256:e0eee73e…`. Their `pip freeze` output is identical, and it matches `backend/uv.lock` exactly.
- Titiler: `ghcr.io/developmentseed/titiler@sha256:9cc74708…`.

Primary sources were checked for every row, mostly through OSV and GitHub's advisory API. The checks ran
in a delegated pass; its working notes are not in the repo, and every URL below is the primary one.
Where a primary source disagrees with the prompt's summary, the **Disagreement** column says so,
and the primary source wins.

## 1. Requested advisories

| Advisory | Package | API/worker | Titiler | Frontend | Affected in our deployment? | Evidence | Disagreement with the prompt | Primary source |
|---|---|---|---|---|---|---|---|---|
| CVE-2026-48710 "BadHost" (GHSA-86qp-5c8j-p5mr), fixed 1.0.1 | starlette | 1.6.0 | **0.52.1** | — | **API no. Titiler yes by version.** It reproduces at the Starlette level, but it doesn't affect any access decision: the Titiler token is a per-route query-parameter dependency. | `raw/lab/badhost-starlette-unit.txt` (0.52.1: `url.path='/api/v1/health'` for routed `/cog/tiles/1/2/3`; 1.6.0 falls back to the server address); `raw/lab/badhost-api.txt` (limiter keyed on route template: 4 Hosts, 1 bucket); `raw/lab/badhost-titiler-reflect.txt` (injected path reflected into links) | None on scope. **Not in the prompt: it is on CISA KEV, added 2026-09-02.** | https://github.com/advisories/GHSA-86qp-5c8j-p5mr |
| CVE-2026-48817 (GHSA-x746-7m8f-x49c), fixed 1.1.0 | starlette | 1.6.0 | 0.52.1 | — | **No.** It needs an `HTTPEndpoint` routed without `methods=`, and no `HTTPEndpoint` exists in `backend/app`, titiler or rio_tiler (grep in the image). | `grep -rn HTTPEndpoint` → empty in all three | None | https://github.com/advisories/GHSA-x746-7m8f-x49c |
| CVE-2026-48818 (GHSA-wqp7-x3pw-xc5r), fixed 1.1.0 | starlette | 1.6.0 | 0.52.1 | — | **Not applicable.** It is Windows-only, and both images are Debian 13. | `raw/titiler-inventory.txt`; API `/etc/os-release` | None | https://github.com/advisories/GHSA-wqp7-x3pw-xc5r |
| CVE-2026-54282 (GHSA-jp82-jpqv-5vv3), fixed 1.3.0 | starlette | 1.6.0 | 0.52.1 | — | API no. Titiler yes by version: path-into-authority, reachable only from pre-routing code and 404 handlers. | pip-audit `raw/pip-audit-titiler.json` | Not in the prompt | https://github.com/advisories/GHSA-jp82-jpqv-5vv3 |
| CVE-2026-54283 (GHSA-82w8-qh3p-5jfq), fixed 1.3.1 | starlette | 1.6.0 | 0.52.1 | — | API no. **Titiler: not reachable.** It is a form-parsing DoS, and Titiler routes are GET-only and never call `request.form()`. | pip-audit | Not in the prompt | https://github.com/advisories/GHSA-82w8-qh3p-5jfq |
| CVE-2026-52869 (GHSA-jpw9-pfvf-9f58), fixed 1.27.2 | mcp | not installed | — | — | **Not applicable.** No MCP code or dependency at HEAD. The design (`mcp` 2.2.0, stateless, no auth) would also be unaffected. | `grep -rni mcp backend/app backend/pyproject.toml` → empty; `docs/audits/2026-09-mcp-preflight/PREFLIGHT.md` §(a) | Scope: SSE or **stateful** Streamable HTTP, **and only with authentication enabled** | https://github.com/advisories/GHSA-jpw9-pfvf-9f58 |
| CVE-2026-52870 (GHSA-hvrp-rf83-w775), fixed 1.27.2 | mcp | — | — | — | Not applicable | as above | **Not a transport bug.** It affects only servers that call `server.experimental.enable_tasks()`, and the range starts at 1.23.0. | https://github.com/advisories/GHSA-hvrp-rf83-w775 |
| CVE-2026-59950 (GHSA-vj7q-gjh5-988w), fixed 1.28.1 | mcp | — | — | — | Not applicable. The deprecated WebSocket transport was removed in v2. | as above | The fix is opt-in: upgrading alone changes nothing on 1.x. | https://github.com/advisories/GHSA-vj7q-gjh5-988w |
| CVE-2026-59951 (GHSA-84m7-p3x7-pcfv), fixed 1.30.0 / 2.2.0 | mcp | — | — | — | Not applicable. The design is stateless on both legs, and 2.2.0 is outside the range. | as above | None. OSV lists **no advisory affecting 2.2.0**. The latest is 2.3.0 (2026-10-02). | https://github.com/advisories/GHSA-84m7-p3x7-pcfv |
| CVE-2026-115557 (PSF-2026-46), CPython ssl denylist for compromised eMudhra intermediates | CPython | **3.12.14** | **3.14.3** | — | **Yes, both.** Fixed in 3.12.16 and 3.14.10, both released 2026-10-25. Exploitation needs a network-position attacker holding a certificate from the compromised intermediates. | API/worker image env `PYTHON_VERSION=3.12.14`; Titiler `PYTHON_VERSION=3.14.3` | None | https://www.cve.org/CVERecord?id=CVE-2026-115557 · https://www.python.org/downloads/release/python-31216/ |
| GHSA-6q48-6c7w-9gw2 (no CVE), certifi trusts `emSign ECC Root CA - G3` | certifi | **2026.05.20** | **2026.2.25** (also GDAL's curl CA bundle: `GDAL_CURL_CA_BUNDLE` resolves to certifi's `cacert.pem`) | — | **Yes, both.** httpx (API/worker) and GDAL/libcurl (Titiler) trust the G3 root. | pip-audit both images; `raw/titiler-inventory.txt` | **The first fixed release is 2026.10.18, not .19.** The advisory recommends 2026.10.19, which restored the unaffected roots. 2026.10.23 later removed C1 and C3 too, without a stated reason. | https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2 |
| pip ≥ 26.2.2 (same CA compromise) | pip | 25.0.1 | 26.0.1 | — | **No pip advisory exists.** pip 26.2.2 only re-vendors certifi 2026.10.19. Our exposure is pip's vendored bundle, and only when pip itself runs. Nothing invokes pip at runtime, and `uv` installs all dependencies at build. osv-scanner lists other, older pip advisories (`raw/osv-image-*-summary.tsv`), all build-time. | image `pip --version`; `Dockerfile.fly:21-23` | **The premise is partly wrong:** there's no pip advisory for this, only a vendored-bundle refresh. | https://raw.githubusercontent.com/pypa/pip/26.2.2/NEWS.rst |
| CVE-2026-112900 (GHSA-w889-685w-c8fh), EPS, fixed 13.0.0 | pillow | 12.3.0 | not installed | — | **No.** It needs Ghostscript (absent from the image: `which gs` is empty) **and** an attacker-influenced filename passed to `Image.open`. Our only caller passes `BytesIO` (`preview_renderer.py:130`), which takes Pillow's safe `mkstemp` branch. | image check; source read | **The mechanism differs:** the injection is through the filename, not the EPS content. The "public exploit" is the PoC inside the GHSA itself. | https://github.com/advisories/GHSA-w889-685w-c8fh |
| CVE-2026-112393 (GHSA-332p-7hrc-92wf), fixed 13.0.0 | pillow | 12.3.0 | — | — | **No.** It needs a TIFF **save** to a target with no `fileno()`. We save JPEG to a file path (`preview_renderer.py:151`). | source read | None | https://github.com/advisories/GHSA-332p-7hrc-92wf |
| CVE-2026-112403 (GHSA-8g5g-8vmr-9782), fixed 13.0.0 | pillow | 12.3.0 | — | — | **No in practice.** It needs `draft()`/`thumbnail()` on a lossless JPEG. We call `open().convert()` on Titiler's PNG output, and `load()` at scale 1 is unaffected. | source read | None | https://github.com/advisories/GHSA-8g5g-8vmr-9782 |
| USN-8812-1 (GDAL; CVE-2026-49014 netCDF, CVE-2026-8084/8086/8087/8088/8212/8213 HDF-EOS) | GDAL | not installed | **3.12.1** (bundled in the rasterio 1.5.0 wheel, on Debian, not Ubuntu) | — | **The USN itself doesn't apply** (it covers Ubuntu packages). **CVE-2026-49014 (netCDF, 3.1.0–3.13.0, fixed 3.13.1): yes by version.** The driver is compiled in, and it is selected by content from a `.tif` URL whenever userfaultfd is available (`raw/lab/ufd-direct.txt`). Whether userfaultfd is available on Fly is UNVERIFIED (PROD-PROBES P5). **The six HDF-EOS CVEs: not applicable.** They live in the HDF4 driver, and the image's 147 drivers do not include `HDF4`/`HDF4Image`. | `raw/titiler-inventory.txt` (driver list); `raw/lab/probe-out.txt`; FINDINGS SEC-17/18 | **Two corrections:** the USN rates 8084 and 8088 as DoS, not RCE, and VulDB scores the HDF-EOS records as local attacks. The USN says nothing about driver selection. GDAL's own security doc does: "you cannot know which driver will handle a file by just looking at its extension." | https://ubuntu.com/security/notices/USN-8812-1 · https://gdal.org/en/stable/user/security.html |
| CVE-2026-39363 (GHSA-p9ff-h696-f583) | vite | — | — | 5.4.21 (dev) | **No.** The range starts at 6.0.0. | npm registry ranges; osv-scanner did not flag it | The prompt implies all three hit our line | https://github.com/advisories/GHSA-p9ff-h696-f583 |
| CVE-2026-39364 (GHSA-v2wj-q39q-566r) | vite | — | — | 5.4.21 | **No.** The range starts at 7.1.0. | as above | as above. For 6.x the floor is 6.4.5 (CVE-2026-118662 regression). | https://github.com/advisories/GHSA-v2wj-q39q-566r |
| CVE-2026-39365 (GHSA-4w7w-66w2-5vf9) | vite | — | — | 5.4.21 | **Disputed. Treat it as yes.** The GHSA range includes 5.x with no 5.x fix; the CVE text says "from 6.0.0". osv-scanner flags 5.4.21. The precondition (`--host`) is met unconditionally: `vite.config.ts:15`. | `raw/osv-lockfiles.json` | The primary sources disagree with each other | https://github.com/advisories/GHSA-4w7w-66w2-5vf9 |
| CVE-2026-112945 (GHSA-9jrq-w75r-8gcw) | vite | — | — | 5.4.21 | **Affected by version, precondition not met.** It needs custom middleware passing the raw URL to `transformIndexHtml` (`middlewareMode` / `appType: 'custom'`). `vite.config.ts` uses the default `spa`. No 5.x fix exists. | `frontend/vite.config.ts` | **Not gated on `--host`.** It is a browser-mediated attack on a localhost dev server. | https://github.com/advisories/GHSA-9jrq-w75r-8gcw |

## 2. Supply-chain IoCs (step 6)

| Group | Primary list | Checked against | Result | Source |
|---|---|---|---|---|
| Mini Shai-Hulud, TanStack, 2026-05-11 (CVE-2026-45321, KEV) | 42 `@tanstack/*` Router/Start packages × 2 versions = 84 | all 5 revisions of `frontend/package-lock.json` (511 name@version), installed `frontend/node_modules` | **Absent.** Only `@tanstack/query-core` and `react-query`, at **5.95.2** in every revision ever. No `router_init.js` or `"@tanstack/setup"` marker in `node_modules`. | https://github.com/advisories/GHSA-g7cv-rxg3-hmpx · TanStack postmortem (query* listed clean; its timeline's mention of `query-core` as a removed tarball conflicts with that, and no primary source resolves it, so it is recorded here rather than assumed to be a typo) |
| axios, 2026-03-31 | `axios` 1.14.1, 0.30.4; injected `plain-crypto-js` 4.2.0/4.2.1 | same | **Absent.** Neither name appears in any revision. `package-lock.json` has existed since 2026-03-25, so the window is covered. | https://github.com/advisories/GHSA-fw8c-xr5c-95f9 · https://github.com/axios/axios/issues/10636 |
| OSV `MAL-` ids, npm and PyPI lockfiles at HEAD | — | osv-scanner 2.7.0 | **Zero MAL- ids** | `raw/osv-lockfiles.json` |
| PyPI: litellm 1.107.0 (and 1.82.7/1.82.8), lightning and pytorch-lightning 2.6.2/2.6.3, mistralai 2.4.6, telnyx 4.87.1/4.87.2, the June wave (`2026-06-compr-woodpecker`, 38 entries), plus adjacent durabletask 1.4.1–1.4.3 and guardrails-ai 0.10.1 | 82 name==version | all 3 revisions of `backend/uv.lock`, the API/worker image freeze, the Titiler image freeze | **Absent. No IoC package name appears at any version.** | `raw/IOC-CHECK.txt`; MAL ids and maintainer GHSAs are in the table above's sources; woodpecker: https://bad-packages.kam193.eu/pypi/campaign/2026-06-compr-woodpecker |
| Cooldown / ignore-scripts | — | `frontend/.npmrc` (absent), repo-root `.npmrc` (absent), `deploy.yml:208` (`npm ci`), `backend/pyproject.toml` (no `[tool.uv] exclude-newer`) | **None configured.** Lifecycle scripts run on every dev and CI install. Mitigating: uv verifies lockfile hashes by default (`uv export` emits `--hash`, `Dockerfile.fly:21-23`). | FINDINGS SEC-23 |

**History caveat.** The lockfiles bound what history can show:
`package-lock.json` has 5 revisions since 2026-03-25 and `uv.lock` has 3 since
2026-05-22. Before 2026-05-22 the backend installed from unpinned ranges, and
`fly.titiler.toml` pointed at Titiler `latest`. What resolved in that window
was never recorded. None of the PyPI IoC packages is in our dependency tree
at any version, so the gap cannot have hidden one of *these*. It is still a gap.

## 3. Everything else the scanners found (not in the prompt's list)

| Package | Image | Version → fix | Reachable? |
|---|---|---|---|
| pillow, 39 other advisories (FPX/JPEG heap overflows, TIFF UAF, bundled libopenjp2 GHSA-78g4-xqwv-q3g8, …) | API/worker | 12.3.0 → 13.0.0 | The only decode site is `preview_renderer.py:130`, called only from `scripts/seed_featured.py` (operator, via `fly ssh`), on PNG bytes **our Titiler encoded**. No request path decodes. Bump at leisure; the earlier dependency-advisories pass reads it as "reachable", but reachable means operator-only. |
| anyio (CVE-2026-63374 IDN TLS hostname, CVE-2026-64847 process pool) | both | 4.13.0 / 4.12.1 → 4.14.2 | No. Upstream hosts are ASCII, and nothing uses anyio process pools. |
| pydantic-settings (CVE-2026-58203, nested `secrets_dir`) | both | 2.14.1 / 2.13.1 → 2.14.2 | No. No `secrets_dir` is configured. |
| rio-tiler band-math guard (GHSA-9cfx-96xx-wmh9, repository advisory, **unreviewed, no CVE, invisible to OSV and Dependabot**) | Titiler | 8.0.5 → 8.0.9 | **8.0.5 has no expression guard at all.** The only layer left is numexpr 2.14.1's own denylist, which rejects both published building blocks (`b1.__class__`, generator expressions) — `raw/lab/probe3-out.txt`. Weaponized chains were not attempted. SEC-17. |
| urllib3 (7), requests (1), idna (1), opentelemetry-api (1) | Titiler | → 2.8.0, 2.33.0, 3.15, 1.45.1 | Low. GDAL fetches with libcurl, not urllib3, and these are titiler's own client paths. Part of SEC-17's image bump. |
| cryptography 48.0.0 (4), mako 1.3.12 (Windows-only) | lock only (dev / transitive) | → 50.0.0, 1.4.2 | cryptography is dev-only (not in the API image freeze). mako is not applicable. |
| Debian 13 OS packages | API: 1270 ids / 87 source pkgs; Titiler: 1115 ids | — | Mostly not network-reachable (`linux` headers alone are 1001 of the API's). **The material line:** API `openssl 3.5.7-1~deb13u2` has 13 fixes in `deb13u3` (2026-09-29), published after the image was built (2026-09-07). Python's `ssl` links this OpenSSL. SEC-20. |
| maplibre-gl GHSA-jrc7-96c5-q579 "DOM.sanitize bypass" | frontend (prod bundle) | 4.7.1 → 6.4.1+ | The advisory text doesn't fit 4.7.1, which has no sanitizer to bypass. The exposure underneath it does: SEC-21. |
| lodash, protocol-buffers-schema | frontend (prod bundle) | — | Recorded unreachable in SEC-10 (2026-08-22). Re-checked: no `_.template` or `_.unset` call in `frontend/src`. Unchanged. |
| esbuild GHSA-67mh-4wv8-2f99, vitest/tinypool/@vitest/mocker, postcss, eslint chain, … | frontend dev | — | Dev/CI only. esbuild's advisory concerns its `serve` API, which Vite 5 does not use. Part of SEC-22's toolchain batch. |

## 4. Predictions scored

PREDICTION.md (`d226713`) was written before any scanner ran. Verdicts:
**confirmed** (observed as predicted), **deviation** (right direction, wrong in a
stated detail), **falsified**, **not-exercised**.

| # | Prediction (abridged) | Observed | Verdict |
|---|---|---|---|
| 5a-1 | BadHost: API not affected; Titiler affected by version, not exploitable for an access decision | Exactly that. The Starlette-level divergence reproduces on 0.52.1, and the token dependency is per-route. Missed: KEV listing. | **confirmed** |
| 5a-2 | HTTPEndpoint: not reachable | No `HTTPEndpoint` anywhere | **confirmed** |
| 5a-3 | StaticFiles Windows: N/A | Windows-only per GHSA | **confirmed** |
| 5b-1..4 | MCP: N/A, 2.2.0 unaffected | Not merged. No advisory affects 2.2.0. 52870 is feature-gated, not a version-floor issue. | **confirmed** (all four) |
| 5c-1 | CPython: API affected; Titiler affected if the 3.14 fix > 3.14.3 | The fixes are 3.12.16 and 3.14.10, so both are affected | **confirmed** |
| 5c-2 | certifi affected in all images | Yes. The fix floor is 2026.10.18 (advisory), with .19 recommended. | **confirmed** |
| 5c-3 | pip affected by version, build-time only | No pip advisory exists. The exposure is pip's vendored certifi, build-time only. | **deviation**: the predicted object (a pip advisory) doesn't exist |
| 5d | Pillow affected by version, not network-reachable, EPS not exploitable | Yes on all three counts. EPS also needs an attacker-influenced filename (we pass BytesIO). | **confirmed** |
| 5e | USN N/A as written; upstream bugs probably apply but only behind a compromised upstream or unset token; a `.tif` URL with other-format bytes opens if the driver reads `/vsicurl/` | USN N/A ✓. netCDF CVE applies by version ✓. **HDF-EOS CVEs N/A because the image has no HDF4 driver ✗.** Format confusion confirmed for HDF5 (always) and netCDF (when userfaultfd is available) ✓. Not anticipated: the VRT-as-`.tif` pivot. | **deviation**: the HDF-EOS half was wrong |
| 5f | Vite: affected (dev-only), host precondition met unconditionally | 39363 and 39364 don't cover 5.x. 39365 is disputed between GHSA and CVE. 112945 is affected by version, but its precondition (custom `transformIndexHtml`) is not met and is not `--host`-gated. The host precondition *is* met unconditionally. | **falsified** for 39363/39364; the rest **deviation** |
| 6a-1 | TanStack: not affected, HEAD and history | Only query-core/react-query 5.95.2 in every revision | **confirmed** |
| 6a-2 | axios: not affected | Absent in every revision; `plain-crypto-js` absent too | **confirmed** |
| 6a-3 | No MAL- ids | Zero | **confirmed** |
| 6b | PyPI IoCs absent everywhere | Absent at any version in the lock history and both images | **confirmed** |
| 6c | No cooldown or ignore-scripts anywhere | None | **confirmed** |

15 confirmed, 2 deviation, 1 falsified (5f), out of 18 predictions. 5f's error was trusting the prompt's
grouping of the three April Vite CVEs as one line-wide range. 5e's was assuming
"GDAL has the HDF-EOS driver" without checking the driver list, which this
session had already printed by then.
