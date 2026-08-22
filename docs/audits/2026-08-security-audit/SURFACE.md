# Security audit — surface inventory

Pre-registered before assessment, from code at HEAD `dacbcbf` (2026-08-22).
Coverage in `FINDINGS.md` §5 is measured against this file. Line numbers are
HEAD's. No production request was made to build this file.

## 1.1 Route inventory

Built from `main.py:61-67` router registrations plus FastAPI defaults
(`main.py:41-46`: `docs_url="/docs"`, `redoc_url="/redoc"`, default
`/openapi.json`) and the `/static` mount (`main.py:71`). Rate limits are
`RateLimit(times, seconds)` dependencies (`api/rate_limit.py`), keyed
`ratelimit:{request.url.path}:{ip}` (`rate_limit.py:59`) — note the key is the
*resolved path*, so routes with a path parameter get one bucket per id.

| Method | Path | Side effects | Rate limit | Cost class | Input validation |
|---|---|---|---|---|---|
| GET | `/api/v1/health` | DB `SELECT 1` + Redis PING | NONE | DB+Redis probe, 2 s timeouts | — |
| GET | `/api/v1/geocode/autocomplete` | Redis get/set; **calls Photon** (`api/geocode.py:67-75`) | 60/min/IP | geocoder call (3 s timeout) | `q` 3–200 chars |
| POST | `/api/v1/geocode` | **Calls Census geocoder** (1–3 attempts × 20 s); **creates parcel row**; **creates TimelineRequest + dispatches Celery** (`api/geocode.py:229-277`) | 10/min/IP | full timeline run | `address` 5–500 chars, stripped; `lat` −90..90; `lon` −180..180 (`schemas/geocode.py`) |
| GET | `/api/v1/parcels/{id}` | none | NONE | DB read | UUID path |
| POST | `/api/v1/parcels/{id}/timeline` | **Creates TimelineRequest + dispatches Celery** when none in flight/complete, or backfill refetch (`api/imagery.py:79-94`) | 20/min/IP **per parcel** | full timeline run | UUID path |
| GET | `/api/v1/timeline-requests/{id}` | none | NONE | DB read; returns `error_message` strings (`api/imagery.py:117-125`) | UUID |
| GET | `/api/v1/parcels/{id}/imagery` | **Signing calls** for every non-Landsat/topo URL (`api/imagery.py:205-225`); container-token path is Redis-cached | NONE | signing fan-out (up to 80+ URLs, cache-backed) | UUID; `source` free string; dates |
| GET | `/api/v1/imagery/{sid}/tiles/{z}/{x}/{y}` | **Signing call** (cached) + **Titiler request** per tile (`api/imagery.py:435-486, 538-564`) | NONE | Titiler fan-out + GDAL range reads on PC/S3 | UUID; z 0–24; x,y 0–2^24−1; `cog` ≥0 |
| POST | `/api/v1/imagery/{sid}/warmup` | **Titiler `/cog/info` or `/stac/info`** (+ sign) (`api/imagery.py:642-668`) | 60/min/IP **per snapshot** | Titiler fan-out (COG header read; Landsat: STAC fetch + 3 band signs) | UUID |
| GET | `/api/v1/imagery/{sid}/stac` | **Fetches PC STAC item** (allowlisted host, `api/imagery.py:750-764`), **signs 3 bands**, Redis get/setex | 600/min/IP **per snapshot** | signing (3 container-token signs) + PC GET | UUID |
| GET | `/api/v1/parcels/{id}/demographics` | none | NONE | DB read | UUID |
| GET | `/api/v1/parcels/{id}/events` | none | NONE | DB read (2 queries when `type` set) | UUID; `type` free string split on commas; dates |
| GET | `/api/v1/featured` | none | NONE | DB read | — |
| GET | `/api/v1/featured/{slug}` | none | NONE | DB read | `slug` free string (parameterised) |
| GET | `/static/{path}` | none | NONE | file read (Starlette StaticFiles) | Starlette path guard |
| GET | `/docs`, `/redoc`, `/openapi.json` | none | NONE | static | — |

Titiler routes reachable publicly (`plotline-titiler.fly.dev`, stock
`ghcr.io/developmentseed/titiler:1.2.1`, `fly.titiler.toml:10`; route list
taken from its `/api` OpenAPI document, probe-log #12): `/cog/*` (info,
statistics, tiles, preview, bbox, feature, point, validate, viewer, map,
tilejson, WMTS), `/stac/*` (same set plus assets/asset_statistics/renders),
`/mosaicjson/*`, `/algorithms`, `/colorMaps`, `/tileMatrixSets`, `/healthz`,
`/api`, `/api.html`. Every `/cog`, `/stac` and `/mosaicjson` route takes an
arbitrary `url=` query parameter. No rate limit, no auth (`fly.titiler.toml`
sets no `TITILER_API_*` variable). CORS `*`, GET only (image default).

## 1.2 Outbound fetch inventory

| # | Site | Host | URL origin | Allowlist | TLS verify | Timeout | Retry | Redirects | Max size |
|---|---|---|---|---|---|---|---|---|---|
| F1 | STAC search `stac.py:144,165,167` | planetarycomputer.microsoft.com | constant; pagination follows `links[rel=next]` **from the response** (`stac.py:150-167`) | none (next-link host unchecked) | httpx default (verify on) | 30 s | 3× on 429/5xx/RequestError (`timeline.py:94-135`) | httpx default (off) | none |
| F2 | SAS token mint `stac.py:399` | PC | constant base; account/container parsed from an **asset href** (`stac.py:349-367`) | suffix `.blob.core.windows.net` selects path only | default | 10 s | 429 only, ≤4 attempts (N1) | off | none |
| F3 | Per-URL sign `stac.py:524` | PC | constant; `href` = DB/upstream URL | none | default | 10 s | as F2 | off | none |
| F4 | Validation HEAD `stac.py:1024` | whatever the STAC asset href names | upstream response | none | default | 30 s | none | **`follow_redirects=True`** | none |
| F5 | Landsat item fetch `api/imagery.py:759` | PC | **DB row** `cog_url` | **yes** `_ALLOWED_STAC_HOSTS` (`:336`) | default | 15 s | none | off | none |
| F6 | Titiler calls `api/imagery.py:389` (tiles), `:645`, `:665` (warmup); `preview_renderer.py:113-116` | self-hosted Titiler (public host) | `url=` is a **DB row** (NAIP/S2/topo `cog_url`, signed) or the API's own `/stac` URL | none on `url` (N5) | default | 30 s (preview 60 s) | none | off | full body buffered |
| F7 | GDAL vsicurl inside Titiler | whatever `url=` names | **anyone on the internet** (public route) | `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff` (extensions only, `fly.titiler.toml:19`) | GDAL curl default (verify on, `GDAL_CURL_CA_BUNDLE` set in image) | GDAL defaults | `GDAL_HTTP_MAX_RETRY=3` | curl follows | `VSI_CACHE_SIZE` 256 MB |
| F8 | TNM products `usgs_topo.py:76` | tnmaccess.nationalmap.gov | constant; bbox from parcel coords | n/a | default | 30 s | none | off | none |
| F9 | Topo GeoTIFF (read by Titiler) | whatever TNM `urls.GeoTIFF` says | upstream response → DB row (`usgs_topo.py:134-140`) | **none** | — | — | — | — | — |
| F10 | Census geocoder forward `geocoder.py:137`; reverse `:269`; vintage `:369` | geocoding.geo.census.gov | constant; `address` / coords from **user input**; `key=` query param | n/a | default | 20 s | 3× timeouts only | off | none |
| F11 | Census data API `census.py:250` | api.census.gov | constant; `key=` query param | n/a | default | 30 s | none (N2) | off | none |
| F12 | Photon `api/geocode.py:67` | photon.komoot.io | constant; `q` from **user input** | n/a | default | 3 s | none | off | none |
| F13 | ArcGIS `arcgis.py:67` (Denver ×2, Adams ×1, DC ×8 layers) | services{1,3}.arcgis.com, maps2.dcgis.dc.gov | constant layer URLs; `where` from **parcel address** | n/a | default | 30 s | none | **`follow_redirects=True`** | none |
| F14 | CKAN `ckan.py:67` (San Jose ×3) | data.sanjoseca.gov | constant; `q` from parcel address | n/a | default | 30 s | none | **`follow_redirects=True`** | none |
| F15 | Socrata `socrata.py:67` (NYC ×3) | data.cityofnewyork.us | constant; `$where` from parcel address; `X-App-Token` header | n/a | default | 30 s | none | **`follow_redirects=True`** | none |
| F16 | Browser-direct (not server): PC `preview.png` thumbnails (`Timeline.tsx:634`), OpenFreeMap basemap | — | DB row / constant | — | — | — | — | — | — |

Redis (Upstash, `rediss://`, `db.py:743-766`, `celery_app.py:815-821`): redis-py
`rediss://` defaults to `ssl_cert_reqs=required`; Celery URL gets
`ssl_cert_reqs=CERT_REQUIRED` appended. Postgres (Neon pooler host,
`sslmode=require` — encrypted, CA not verified; `config.py:83-89`).

## 1.3 Secrets inventory (names only)

| Name | Injected | Travels | Privilege | Rotation |
|---|---|---|---|---|
| `DATABASE_URL` | Fly secrets (api, worker); local `.env` (gitignored, never committed) | `config.py:83-89` / `alembic/env.py:36-42` normalise it; SQLAlchemy `echo` is off in prod (`db.py:671`); not logged by the app | **Neon `neondb_owner`**: owner role, `createdb`, full DML incl. `TRUNCATE`/`DELETE` (probe-log #19) | none recorded |
| `REDIS_URL` | Fly secrets (api, worker) | Celery broker/backend + app clients; Celery's own startup banner prints the broker URL **with password masked** | Upstash default user (read-write; token scope UNVERIFIED) | none recorded |
| `CENSUS_API_KEY` | Fly secrets (api, worker); local `.env` | **query param** on every geocoder/data call (`geocoder.py:135,259,359`; `census.py:247`); httpx logger pinned to WARNING to keep it out of access logs (`logging_config.py:62-66`); **but `str(HTTPStatusError)` embeds the full URL** — see FINDINGS SEC-4 | read-only public API key | none recorded |
| `CORS_ORIGINS` | Fly secret (api) | not sensitive | — | — |
| `SOCRATA_APP_TOKEN` | not set in prod (`fly secrets list`) | header only | — | — |
| `FLY_API_TOKEN` | GitHub Actions secret | `flyctl deploy` only | scope UNVERIFIED (org vs app deploy token) | none recorded |
| Cloudflare Pages | dashboard GitHub integration; no token in repo | — | — | — |
| PC SAS tokens | minted at runtime (`stac.py:391-420`) | Redis (`sas-token:*`, `sas:*`), signed URLs to the browser (`/parcels/{id}/imagery`), Titiler `url=` params, Titiler error bodies logged at `api/imagery.py:395-400,419-424` (`titiler_body[:500]`), `se=` logged at mint | read-only, ~45 min | self-expiring |
| `GIT_SHA`/`BUILT_AT` | build args | `/api/v1/health` | public by design | — |

## 1.4 Data inventory

Stored (`models/parcels.py`): `parcels.address` (raw user string, `parcels.py:140`),
`normalized_address` (Census `matchedAddress`, **or the raw user string on the
reverse-geocode path** `geocoder.py:323`), `latitude`/`longitude`/`point`,
`census_tract_id`, `county`, `state_fips`, `created_at`; `timeline_requests`
`created_at`/`updated_at`; imagery/census/property rows keyed to the parcel.
**No IP, user agent or referrer column exists anywhere.** Parcels are never
deleted (no delete path in code; `scripts/remove_uncovered_snapshots.py`
deletes snapshots only).

Surfaces: `GET /parcels/{id}` (address + coords — UUID needed, not listed);
`GET /geocode` response; `/featured` (6 curated parcels); logs:
`api/geocode.py:180,199,219` log the submitted address at INFO;
`parcels.py:130,161` log `normalized_address`; `geocoder.py:129,179` log
address and coordinates; `timeline.py:966-973` logs the bbox. Repo: street
addresses appear in `docs/audits/` (geometry FINDINGS ×5+, HEAL-SCORECARD,
ops FINDINGS, CENSUS_TRIAGE, STATUS.md ×3, INVENTORY ×1; counted by regex,
not listed).

## 1.5 Trust boundaries

- Browser → `plotline.land` (Cloudflare Pages, Cloudflare-proxied,
  probe-log #6): anonymous, static bundle.
- Browser → `api.plotline.land` = `log0s-plotline-api.fly.dev` (DNS resolves to
  Fly ingress IPs directly; `server: Fly`; **not** Cloudflare-proxied,
  probe-log #2, DNS): anonymous; Fly proxy sets `Fly-Client-IP`.
- API → Titiler (`https://plotline-titiler.fly.dev`, public, `fly.toml:13`):
  anonymous; carries SAS-signed URLs in `url=`.
- Titiler → API `/api/v1/imagery/{id}/stac` (`https://log0s-plotline-api.fly.dev`,
  `fly.toml:19`, public): anonymous, indistinguishable from any other caller.
- Public internet → Titiler: anonymous, arbitrary `url=`.
- Worker → PC STAC/SAS (anonymous), Census (key in query), Photon (n/a —
  API only), TNM (anonymous), county portals (anonymous; Socrata token unset).
- API & worker → Neon (owner role, TLS required/unverified), Upstash
  (password, TLS verified).
- GitHub Actions → Fly (`FLY_API_TOKEN`), push-to-main, no environment gate.
- Titiler inside Fly 6PN: can reach `*.internal` IPv6 of the API and worker
  apps; worker exposes no service; Titiler holds no secrets.
