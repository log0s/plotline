# External Source Inventory

**Purpose.** A ground-truth picture of every external source Plotline talks
to, written to brief an external research pass on alternative and additional
sources. It describes what the code does, not what the docs say it does.

**Method and scope.** Read-only. Every claim carries a `file:line` against
**HEAD `103ddab`** (2026-08-15), re-verified in this session by reading the
cited site — nothing is carried over from the audit documents without
re-checking. No production system was contacted; no local database read was
possible either (`docker compose ps` returns no running containers), so this
document contains **no row counts and no observational claims** — only code.
Where a number is quoted from an earlier audit it is labelled as such and
attributed.

Known pain points already on the record appear as one-line pointers per
section (§8 of each). They are **not** re-investigated here.

**Settled, not revisited:** pixel ingest is ruled out. The Sentinel-2 and NAIP
hosting paths are currently Planetary Computer and are under re-evaluation;
this document inventories the current paths as-is. Their signing, caching and
failure-handling sections are written to be self-contained, because that is
the evidence base the re-evaluation will read.

---

**Path conventions.** Line references are shortened. Several modules share a
basename across directories, so those are always qualified:

| Shorthand | Real path |
|---|---|
| `api/<file>` | `backend/app/api/v1/<file>` |
| `services/<file>`, or a bare `stac.py` / `census.py` / `geocoder.py` / `usgs_topo.py` / `county_adapters.py` / `arcgis.py` / `socrata.py` / `ckan.py` / `preview_renderer.py` | `backend/app/services/<file>` |
| `timeline.py` | `backend/app/tasks/timeline.py` |
| `config.py`, `db.py`, `main.py` | `backend/app/<file>` |
| `rate_limit.py` | `backend/app/api/rate_limit.py` |
| `celery_app.py` | `backend/app/tasks/celery_app.py` |
| `*.tsx`, `*.ts` | under `frontend/src/` |

`api/imagery.py` and `services/imagery.py` are different files, as are
`api/demographics.py` / `services/demographics.py` and
`api/parcels.py` / `services/parcels.py`.

---

## Contents

| § | Source | Provider | Kind |
|---|---|---|---|
| [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5) | PC platform (clients, signing, throttle, caches) | Microsoft | shared mechanism |
| [S1](#s1-naip) | NAIP aerial imagery | Microsoft Planetary Computer STAC + Azure Blob | imagery |
| [S2](#s2-landsat-collection-2-level-2) | Landsat C2 L2 | Microsoft Planetary Computer STAC + Azure Blob | imagery |
| [S3](#s3-sentinel-2-l2a) | Sentinel-2 L2A | Microsoft Planetary Computer STAC + Azure Blob | imagery |
| [S4](#s4-pc-sas-signing-service) | SAS signing service | Microsoft Planetary Computer | auth plane |
| [S5](#s5-pc-data-api-rendered_preview-thumbnails) | `rendered_preview` thumbnails | Microsoft Planetary Computer Data API | imagery (browser-direct) |
| [S6](#s6-usgs-historical-topographic-maps) | Historical topo maps | USGS The National Map + public GeoTIFF host | imagery |
| [S7](#s7-us-census-geocoder) | Address → coords, tract, county | US Census Bureau Geocoder | geocoding |
| [S8](#s8-us-census-data-api-acs5--decennial) | ACS5 + Decennial | US Census Bureau Data API | demographics |
| [S9](#s9-photon-komoot--address-autocomplete) | Address autocomplete | Photon (komoot), OSM-derived | geocoding |
| [S10](#s10-denver-county--arcgis-hub) | Denver permits | ArcGIS Hub (`services1.arcgis.com`) | property |
| [S11](#s11-adams-county--arcgis-hub) | Adams permits | ArcGIS Hub (`services3.arcgis.com`) | property |
| [S12](#s12-district-of-columbia--dcgis) | DC sales + permits | DCGIS (`maps2.dcgis.dc.gov`) | property |
| [S13](#s13-santa-clara--city-of-san-jose--ckan) | San Jose permits | CKAN (`data.sanjoseca.gov`) | property |
| [S14](#s14-new-york-county-manhattan--nyc-open-data-socrata) | NYC sales + permits | Socrata (`data.cityofnewyork.us`) | property |
| [S15](#s15-openfreemap--basemap-tiles) | Basemap tiles | OpenFreeMap | basemap (browser-direct) |
| [T](#t-titiler--self-hosted-not-an-external-source) | Titiler | self-hosted | tile renderer / egress path |

Then: [dependency table](#dependency-table--what-breaks-if-a-source-goes-away),
[replacement quirks](#quirks-a-replacement-source-would-need-to-match),
[caching ledger](#caching-ledger--the-complete-picture),
[new findings](#new-findings).

---

## S0. Planetary Computer platform (shared by S1–S3, S5)

Three imagery collections and the thumbnail path all ride one platform. The
mechanics live here once; each collection section states the concrete path it
takes and what differs.

**Endpoint constants** — `stac.py:24-26`:

| Constant | Value |
|---|---|
| `STAC_API` | `https://planetarycomputer.microsoft.com/api/stac/v1` |
| `PC_SIGN_URL` | `https://planetarycomputer.microsoft.com/api/sas/v1/sign` |
| `PC_TOKEN_URL` | `https://planetarycomputer.microsoft.com/api/sas/v1/token` |

A fourth PC host path, the Data API preview, is referenced only as a string
match: `_PC_PREVIEW_PATH = "/api/data/v1/item/preview.png"`
(`api/imagery.py:129`). See [S5](#s5-pc-data-api-rendered_preview-thumbnails).

**Search call sites.**

| Call | Site |
|---|---|
| `POST {STAC_API}/search` | `stac.py:140` |
| Pagination re-POST (follows `links[rel=next]`, method POST) | `stac.py:161` |
| Pagination GET (non-POST next link) | `stac.py:163` |
| Single-item fetch `GET {STAC_API}/collections/{c}/items/{id}` | `scripts/remove_uncovered_snapshots.py:193` (offline condemnation tool only) |
| Landsat item self-link fetch (see [S2](#s2-landsat-collection-2-level-2)) | `api/imagery.py:759` |

Pagination is real but effectively unreachable for our parameters: the request
`limit` is `min(max_items, 100)` (`stac.py:132`) and the walk continues only
`while len(items) < max_items` (`stac.py:145`), so any `max_items ≤ 100`
completes in one page. `max_items` is hard-capped at 500 (`stac.py:126`).

**No `sortby` is ever sent.** The payload carries `collections`, `bbox`,
`datetime`, `limit` and an optional `query` only (`stac.py:128-135`). STAC
leaves the ordering of an unsorted search unspecified, so *which* items
survive a cap is not a property the code controls. This is stated at the call
site (`timeline.py:228-233`).

**HTTP clients** (per event loop, because the Celery worker runs each task in
its own `asyncio.run()` loop and httpx clients are loop-affine —
`stac.py:80-86`):

| Client | Timeout | Limits | Site |
|---|---|---|---|
| search (also used for asset `HEAD`) | 30 s | 20 conns / 10 keepalive | `stac.py:99-102` |
| signing | 10 s | 50 conns / 20 keepalive | `stac.py:229-232` |

Both are closed per task run via `close_clients()` (`stac.py:237-247`), called
from the task's `finally` (`timeline.py:900`) and the API lifespan
(`main.py:37`).

**Auth — the SAS signing plane.** Two mechanisms, chosen by URL shape in
`sign_pc_url` (`stac.py:524-564`):

1. **Container-scoped token** for anything on `*.blob.core.windows.net`
   (`_BLOB_HOST_SUFFIX`, `stac.py:216`; host/container split in
   `_blob_container`, `stac.py:345-360`). One `GET {PC_TOKEN_URL}/{account}/{container}`
   (`stac.py:399`) yields a `sr=c` token appended to the href as a query string
   (`stac.py:545-546`). One PC collection maps to one container, so a single
   token signs every asset of a collection.
2. **Per-URL signature** for everything else — `GET {PC_SIGN_URL}?href=...`
   (`stac.py:520`), returning a fully signed href.

**Signing throttle and the wait-budget split** (the `a536d07` / `3b7b10e`
split named in the brief; both verified as ancestors of HEAD):

- **Concurrency cap.** An `asyncio.Semaphore` per event loop, sized from
  `pc_signing_concurrency` (default **4**) — `stac.py:257-266`,
  `config.py:85`.
- **Attempts.** `pc_signing_attempts`, default **4** — `config.py:86`, read at
  `stac.py:303`.
- **Retry trigger — 429 only.** `_sas_get` (`stac.py:282-342`) retries only
  when `resp.status_code == 429` (`stac.py:311`). Any other non-2xx raises
  immediately via `raise_for_status()` (`stac.py:312`), and network errors are
  not caught at all. See [N1](#n1-sas-signing-retries-only-429--a-transient-pc-5xx-or-connection-error-is-terminal).
- **Backoff.** `Retry-After` (delta-seconds form only) if parseable
  (`_retry_after_seconds`, `stac.py:269-279`), else exponential from 1 s
  doubling (`stac.py:304, 323, 339`). Sleeps happen **outside** the semaphore
  (`stac.py:331-337`).
- **Give-up rule — the budget split.** `SIGN_WAIT_BATCH = 60.0` and
  `SIGN_WAIT_REQUEST = 2.0` (`stac.py:213-214`) cap the *total* time spent
  sleeping. A backoff that would overshoot the budget is not taken; the last
  429 is raised instead (`stac.py:324-329`). Rationale is written at the
  constants (`stac.py:200-212`).

  | Caller profile | Budget | Sites |
  |---|---|---|
  | Request path | `SIGN_WAIT_REQUEST` (2 s) | `api/imagery.py:221` (listing), `api/imagery.py:462` (COG tile), `api/imagery.py:523` (Landsat cache-key), `api/imagery.py:654` (warmup), `api/imagery.py:785` (band signing) |
  | Batch path | `SIGN_WAIT_BATCH` (60 s) | `stac.py:1009` (asset validation), `preview_renderer.py:104-106` (offline preview render); also the default of `sign_pc_url` (`stac.py:524`) |

  The budget is inherited by followers of a coalesced mint, which is safe only
  because processes are budget-homogeneous — stated as a load-bearing
  assumption at `stac.py:440-444`.
- **Single-flight on cold mints.** One in-flight `asyncio.Task` per
  (event loop, container), followers `asyncio.shield`ed so a caller that gives
  up cannot cancel the mint the others need — `stac.py:363-368, 451-463`.
  Accepted bound (one mint per process per container per boundary, not one
  globally) is recorded as a code comment at `stac.py:433-438`.
- **Instrumentation.** Every mint logs `SAS container token minted container=… se=… ms=…`
  at INFO — `stac.py:401-406`.

**Caching (Redis).** Two keys live here; the full ledger for the whole system
is [below](#caching-ledger--the-complete-picture).

| Key | Holds | TTL | Sites |
|---|---|---|---|
| `sas:{url}` | a per-URL signed href | **1200 s** fixed (`_SAS_CACHE_TTL`, `stac.py:179`) | read `stac.py:548-553`, write `stac.py:560` |
| `sas-token:{account}/{container}` | a container token | **derived**: the token's own `se` less a 300 s margin; falls back to 1200 s if `se` won't parse; not cached at all if less than the margin remains | `_container_token_ttl` `stac.py:487-504`; `_SAS_TOKEN_MARGIN_S` `stac.py:198`; key `stac.py:446`; read `stac.py:371-384`; write `stac.py:408-413` |

Note the blob path **never touches `sas:{url}`** — it appends the container
token and returns (`stac.py:543-546`), so the per-URL cache is now only for
non-blob hrefs.

Redis failure is fail-soft everywhere: `(RedisError, OSError)` is caught and
the code proceeds to sign upstream (`stac.py:379-381, 412-413, 554-555,
561-562`). Redis clients carry 2 s socket and connect timeouts
(`db.py:79, 99-101, 116-118`).

**Failure modes at the platform level.**

- Signing failure in the **listing** path: the URL is left out of the signed
  map and the snapshot is dropped from the response, with a count logged —
  `api/imagery.py:229-237, 245-246`. Deliberately never falls back to the unsigned
  href (`api/imagery.py:226-228`).
- Signing failure in the **tile** path: HTTP 502 with a curated message —
  `api/imagery.py:464-479`. The unsigned-href fallback is explicitly refused, with
  the reasoning at `api/imagery.py:465-471`.
- Signing failure in **warmup**: warmup is skipped, 204 returned —
  `api/imagery.py:656-664`.
- Signing failure in **band signing** for a Landsat item: 502, whole item
  fails — `api/imagery.py:790-804`.
- Signing failure in **validation** (worker): `_validate_asset` returns False,
  which the caller reads as "this item is broken" and walks to a fallback —
  `stac.py:1010-1017`. This is where a transient signing outage becomes a
  dropped year; see [N1](#n1-sas-signing-retries-only-429--a-transient-pc-5xx-or-connection-error-is-terminal).

---

## S1. NAIP

**1. Source + provider.** NAIP (USDA aerial imagery) via the Microsoft
Planetary Computer STAC collection `naip`; COG bytes from Azure Blob Storage
(`naipeuwest.blob.core.windows.net` in practice — the host is not hardcoded,
it arrives in the asset href).

**2. Endpoints.**

| Path | Endpoint | Site |
|---|---|---|
| Search | `POST https://planetarycomputer.microsoft.com/api/stac/v1/search`, `collections=["naip"]` | `stac.py:140`, collection from `timeline.py:47` |
| Signing | `GET .../api/sas/v1/token/{account}/{container}` (blob href → container token) | `stac.py:399` via `stac.py:543-546` |
| Tile serving | `GET {titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}` with `url=<signed>` | `api/imagery.py:485-486` |
| Warmup | `GET {titiler_url}/cog/info` with `url=<signed>` | `api/imagery.py:665-668` |
| Preview render (offline) | `GET {titiler_url}/cog/bbox/{minx},{miny},{maxx},{maxy}/{w}x{h}.png` | `preview_renderer.py:96-98, 113-116` |
| Byte reads | Azure Blob, performed by Titiler's GDAL, not by us | see [T](#t-titiler--self-hosted-not-an-external-source) |

**3. Auth.** Container-scoped SAS token appended to the blob href
(`stac.py:543-546`). Request-path sites pass `SIGN_WAIT_REQUEST`
(`api/imagery.py:221, 462, 654`); the offline preview renderer passes
`SIGN_WAIT_BATCH` (`preview_renderer.py:104-106`). NAIP has **no** validation
pass, so it never signs from the worker. Full mechanism: [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5).

**4. Rate limits and retry.**

- *Search*: `_search_stac_with_retry` — 3 attempts, 1 s doubling, retries
  `{429, 500, 502, 503, 504}` and any `httpx.RequestError`; other 4xx raise
  immediately (`timeline.py:94, 97-135`). NAIP takes the **un-chunked** branch
  (`timeline.py:270-282`), so one search failure after retries fails the whole
  source.
- *Signing*: [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5) — 429-only
  retry, concurrency 4, 2 s request budget.
- *Tile*: no retry in our proxy. Titiler's own GDAL retries are
  `GDAL_HTTP_MAX_RETRY=3`, `GDAL_HTTP_RETRY_DELAY=1` (`fly.titiler.toml:22-23`).

**5. Caching.**

- Search results: **nothing is cached.** Every timeline run re-searches PC.
- Selected items: persisted to `imagery_snapshots` (`services/imagery.py:672-762`) —
  this DB row is the only durable memory of the search.
- Signed URL: container token in Redis (`sas-token:…`), derived TTL.
- Tile bytes: **not cached by us.** Browser caching only, via
  `Cache-Control: public, max-age=86400, immutable` (`api/imagery.py:431`).
- Snapshot row: in-process LRU, 300 s TTL, 500 entries
  (`api/imagery.py:289-306`).
- Listing response: `Cache-Control: no-cache` (`api/imagery.py:282`).

**6. Subset consumed.**

| Dimension | Value | Site |
|---|---|---|
| Collection | `naip` | `timeline.py:47` |
| Date range | `2010-01-01` → `{current year}-12-31` | `timeline.py:56`, `timeline.py:271-274` |
| Item cap | `max_items = 50`, single page | `timeline.py:58`; `stac.py:126, 132, 145` |
| Property filter | none | `timeline.py:59` |
| Asset | `assets["image"]` only, and only if its `type` contains "geotiff" | `stac.py:946-949`, `_is_cog_asset` `stac.py:918-928` |
| Bands rendered | `bidx=[1,2,3]`, `rescale=0,255` (4-band uint8 RGBI, IR dropped) | `api/imagery.py:311` |
| Search bbox | 1500 m buffer around the parcel point | `timeline.py:964` |
| Viewport bbox | 1250 m buffer, used for mosaic coverage | `timeline.py:965` |
| Tiles per year | ≤ 3, greedy to 95 % viewport coverage | `select_naip_items` `stac.py:730-863` |
| Resolution recorded | 1.0 m | `timeline.py:61`, `stac.py:30` |

The `2010-01-01` floor is the PC collection's own declared temporal extent,
not a truncation artefact; the reasoning and the corroborating measurement are
cited at the site (`timeline.py:48-57`).

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| Search 429/5xx/network | 3 attempts, then the exception propagates → `_fetch_source` catches, marks the `naip` task **failed** | `timeline.py:97-135, 207-210` |
| Search 4xx (non-429) | raises immediately → task **failed** | `timeline.py:126-127` |
| Search returns exactly 50 items | `WARNING "STAC search hit its item cap — results are truncated"`, results used anyway | `timeline.py:293-302` |
| No item covers the point | the year is **suppressed** with a WARNING; a gap is preferred to the wrong state | `filter_groups_containing_point` `stac.py:623-648`; caller `timeline.py:322-336` |
| Item has no parseable `datetime` | dropped from selection | `_has_capture_date` `stac.py:701-717`, applied `stac.py:753-755` |
| `extract_cog_url` returns None | the group is skipped silently (`continue`), no counter | `timeline.py:377-378` |
| Empty result set | task marked **complete** with `items_found` = the DB count | `timeline.py:433-435` |
| Signing fails at listing / tile / warmup | drop / 502 / skip — see [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5) | `api/imagery.py:229-246, 464-479, 656-664` |

**Is failure distinguishable from empty?** *At the source level, yes* — a
whole-search failure marks the task `failed`. *Within a source, no* — a
truncated pool, a suppressed year, and a group skipped for a missing asset all
end at `complete`, and nothing persists which years were considered. This is
the M4 shape.

**8. Known pain points on the record** (pointers only):

- Un-chunked search + unspecified ordering → truncation risk, instrumented but
  unpaginated — STATUS.md **T4**, **T5**.
- 2010 floor is the collection edge; user-facing "2003" copy corrected —
  STATUS.md **T5**, **T6** (T6 notes production `featured_locations` rows are
  not yet updated).
- Viewport selection ignored point containment; fixed prospectively —
  STATUS.md **geometry family**, **G1** (deletion tool committed, production
  execution pending).
- No `sortby` sent; the old "newest first" comment was false — STATUS.md
  **T4**, **T5(d)**.

---

## S2. Landsat Collection 2 Level-2

**1. Source + provider.** Landsat C2 L2 surface reflectance via the PC STAC
collection `landsat-c2-l2`; single-band COGs in the Azure container
`landsateuwest/landsat-c2` (hardcoded, `stac.py:221`, with the reason at
`stac.py:218-220`).

**2. Endpoints.** Landsat is the only source with a three-hop tile path,
because its bands are separate COGs.

| Path | Endpoint | Site |
|---|---|---|
| Search | `POST .../api/stac/v1/search`, `collections=["landsat-c2-l2"]`, one call **per year** | `stac.py:140`; loop `timeline.py:246-267` |
| Validation | `HEAD <signed red-band blob href>`, `follow_redirects=True` | `stac.py:1020` |
| Signing | container token for `landsateuwest/landsat-c2` | `stac.py:399` |
| Item fetch (API → PC) | `GET <stored cog_url>` = the STAC item self-link, host-allowlisted | `api/imagery.py:759`; allowlist `api/imagery.py:336-340, 750-755` |
| Callback (Titiler → API) | `GET {api_internal_url}/api/v1/imagery/{id}/stac?v={token se}` | built `api/imagery.py:534-535`; served `api/imagery.py:723-813` |
| Tile serving | `GET {titiler_url}/stac/tiles/WebMercatorQuad/{z}/{x}/{y}.png` with `assets=[red,green,blue]`, `asset_as_band=True`, `nodata=0`, `rescale=7000,14000` ×3 | `api/imagery.py:556-564` |
| Warmup | `GET {titiler_url}/stac/info` with the same callback URL | `api/imagery.py:644-648` |

`cog_url` for Landsat stores the **item self-link**, not a band href
(`extract_cog_url` `stac.py:951-963`), with a constructed canonical URL as
fallback (`stac.py:959-962`).

**3. Auth.** Container token, as [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5).
Landsat signs at three distinct points:

- worker validation, `SIGN_WAIT_BATCH` — `stac.py:1009`;
- the callback's band signing, `SIGN_WAIT_REQUEST`, three bands concurrently
  via `asyncio.gather` — `api/imagery.py:783-789`;
- the cache-key derivation `container_token_expiry`, `SIGN_WAIT_REQUEST` —
  `api/imagery.py:521-524`, `stac.py:507-515`.

The listing endpoint **does not** sign Landsat: `_NO_SIGN_SOURCES =
{"landsat", "usgs_topo"}` (`api/imagery.py:205`), because the stored URL is a
public item link.

**4. Rate limits and retry.**

- *Search*: same 3-attempt retry as NAIP, but **chunked by year** from 1984 to
  the current year (`timeline.py:234-269`). A year that still fails is logged
  and skipped; the source fails only if **every** year fails
  (`timeline.py:255-269`).
- *Signing*: [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5).
- *Validation `HEAD`*: no retry; any `RequestError` or status ≥ 400 marks the
  item unusable (`stac.py:1019-1036`).
- *Item fetch*: no retry; `RequestError`/`HTTPStatusError` → 502
  (`api/imagery.py:758-764`).

**5. Caching.**

- Raw STAC item JSON: Redis `stac:{snapshot_id}`, **3600 s**, stored
  *unsigned* — `api/imagery.py:739, 743-745, 768`.
- Container token: Redis `sas-token:landsateuwest/landsat-c2`, derived TTL.
- Callback URL versioning: `?v={token se}` so Titiler's item cache key rotates
  with the token; falls back to a `t{epoch//120}` wall-clock bucket if the
  expiry is unavailable — `api/imagery.py:494, 519-535`. `_landsat_stac_url` never
  raises, by design (`api/imagery.py:516-518`).
- Callback response freshness: `private, max-age=min(se - now - 300, 900)`, or
  `no-store` — `_stac_cache_control` `api/imagery.py:677-698`, applied
  `api/imagery.py:812`.
- Titiler's own rio-tiler item LRU (`maxsize=512`, **no TTL**) is external to
  us and documented at `fly.titiler.toml:24-31`.
- Tile bytes: browser only, `max-age=86400, immutable` (`api/imagery.py:431`).
- Search results: **nothing cached** — 43 year-chunk searches per parcel per
  run, every run.

**6. Subset consumed.**

| Dimension | Value | Site |
|---|---|---|
| Collection | `landsat-c2-l2` | `timeline.py:67` |
| Years | 1984 → current year, one search each | `timeline.py:68`, `timeline.py:235-243` |
| Per-year cap | 20 items | `timeline.py:69` |
| Property filter | `{"eo:cloud_cover": {"lt": 40}}` | `timeline.py:70` |
| Assets read | `red`, `green`, `blue`; `red` alone is the validation canary | `api/imagery.py:782`; `stac.py:1041-1048` |
| Render params | `nodata=0`, `rescale=7000,14000` per band | `api/imagery.py:558-562` |
| Selection | one item per year, lowest `eo:cloud_cover`, LE07 (SLC-off) only as fallback | `select_landsat_items` `stac.py:866-893` |
| Missing cloud cover | treated as 100 % (fully cloudy) | `_cloud_cover` `stac.py:720-723` |
| Resolution recorded | 30 m | `timeline.py:73` |

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| One year's search fails after retries | `WARNING`, year skipped, **task still completes** | `timeline.py:255-266` |
| Every year fails | last exception re-raised → task **failed** | `timeline.py:268-269` |
| Selected item's `red` band unsignable or `HEAD` ≥ 400 | item rejected; walk same-year candidates by ascending cloud cover; if none work the year is dropped with `WARNING "No valid Landsat item for %s; skipping"` | `stac.py:1056-1128`, esp. `:1107-1126` |
| Scene footprint excludes the parcel | filtered out before selection (geometry test, bbox fallback) | `filter_items_containing_point` `stac.py:570-620`; applied `timeline.py:309-310` |
| Item fetch 4xx/5xx/timeout | 502 "Failed to fetch STAC item" | `api/imagery.py:762-764` |
| Non-allowlisted host in `cog_url` | 502, refuses the fetch | `api/imagery.py:750-755` |
| Any band unsignable | 502 for the whole item — deliberately, since an unsigned private blob href guarantees a Titiler 409 | `api/imagery.py:772-804` |
| Titiler ≥ 500 | 502 "Titiler upstream error" | `api/imagery.py:394-401` |
| Titiler 404 | transparent 1×1 PNG, `max-age=3600` | `api/imagery.py:408-414`, PNG at `:374-379` |
| Titiler other 4xx | 502, never passed through with cache headers | `api/imagery.py:418-425` |

**Is failure distinguishable from empty?** No, within the source. A year lost
to a search failure and a year lost to a failed validation walk both leave a
`complete` task with a smaller row count, and nothing records which years were
attempted.

**8. Known pain points on the record:**

- Per-year failures are counted but never persisted; three production
  instances from three upstreams — STATUS.md **M4** (Scheduled).
- Signing 429 storms dropping years; the two-act fix (`a536d07`, `3b7b10e`) —
  STATUS.md **O1**.
- Titiler item LRU pinning expired tokens — STATUS.md **O8** / **G5**
  (resolved `cf0df2b`).
- Cold-token mint fan-out; single-flight fix and its accepted bound — STATUS.md
  **G7** (resolved `2168124`, `e8c857c`).
- Batch/request signing contention during sweeps, attribution still unmeasured
  — STATUS.md **G4**.
- Non-covering granules served (29 Landsat rows) — STATUS.md **geometry
  family** (fixed `2039e64`).
- STAC pagination loop has no page counter — STATUS.md **L1** (open).
- Titiler callback is unauthenticated; rate limit is an interim mitigation —
  STATUS.md **M9** (deferred).

---

## S3. Sentinel-2 L2A

**1. Source + provider.** Sentinel-2 Level-2A via the PC STAC collection
`sentinel-2-l2a`; the `visual` (TCI) COG from Azure Blob.

**2. Endpoints.**

| Path | Endpoint | Site |
|---|---|---|
| Search | `POST .../api/stac/v1/search`, `collections=["sentinel-2-l2a"]`, one call per year | `stac.py:140`; loop `timeline.py:246-267`; collection `timeline.py:79` |
| Validation | `HEAD <signed visual href>` | `stac.py:1020` via `validate_sentinel_item` `stac.py:1051-1053` |
| Signing | container token (blob href) | `stac.py:399` via `stac.py:543-546` |
| Tile serving | `GET {titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}` with `url=<signed>` | `api/imagery.py:485-486` |
| Warmup | `GET {titiler_url}/cog/info` | `api/imagery.py:665-668` |

**3. Auth.** Container token, exactly as NAIP. Worker validation signs with
`SIGN_WAIT_BATCH` (`stac.py:1009`); listing, tile and warmup sign with
`SIGN_WAIT_REQUEST` (`api/imagery.py:221, 462, 654`). Mechanism: [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5).

**4. Rate limits and retry.** Identical to Landsat: year-chunked search with
3-attempt retry on `{429,500,502,503,504}` + network errors, one bad year
skipped, all-years-bad fails the source (`timeline.py:234-269`). Signing per
[S0](#s0-planetary-computer-platform-shared-by-s1s3-s5). `HEAD` validation has
no retry (`stac.py:1019-1036`).

**5. Caching.** Same profile as NAIP: **no search cache**, no tile cache on
our side, container token in Redis, selected items in `imagery_snapshots`,
snapshot row in the 300 s in-process LRU (`api/imagery.py:289-306`), listing
`no-cache` (`api/imagery.py:282`), tiles `max-age=86400, immutable`
(`api/imagery.py:431`). Sentinel-2 has **no** equivalent of Landsat's
`stac:{snapshot_id}` item cache — it does not need one, since the tile path
uses the direct COG href.

**6. Subset consumed.**

| Dimension | Value | Site |
|---|---|---|
| Collection | `sentinel-2-l2a` | `timeline.py:79` |
| Years | 2015 → current year | `timeline.py:80` |
| Per-year cap | 20 items | `timeline.py:81` |
| Property filter | `{"eo:cloud_cover": {"lt": 40}}` | `timeline.py:82` |
| Asset | `assets["visual"]` only (uint8 3-band TCI). **B04 deliberately not used** — its 0–10000 uint16 range is incompatible with the configured rescale | `stac.py:965-971` |
| Render params | `bidx=[1,2,3]`, `rescale=0,255` | `api/imagery.py:312` |
| Selection | one item per **calendar quarter**, lowest cloud cover | `select_sentinel_items` `stac.py:896-912` |
| Resolution recorded | 10 m | `timeline.py:85` |

**7. Failure modes as implemented.** Same table as Landsat for search
(`timeline.py:255-269`), signing ([S0](#s0-planetary-computer-platform-shared-by-s1s3-s5))
and Titiler (`api/imagery.py:394-432`), with these differences:

| Event | Behaviour | Site |
|---|---|---|
| Selected granule's `visual` fails `HEAD` | walk same-**quarter** candidates by cloud cover; drop the quarter if none work | `validate_sentinel_selection` `stac.py:1145-1163` → `_validate_selection` `stac.py:1056-1128` |
| Granule footprint excludes the parcel | filtered before selection | `stac.py:570-620`; applied `timeline.py:309-310` |
| Signing fails at listing | snapshot dropped from the response | `api/imagery.py:245-246` |
| Signing fails at tile | 502 | `api/imagery.py:477-479` |

**Is failure distinguishable from empty?** No — a lost quarter looks exactly
like a quarter with no acceptable granule. Cloud-cover filtering makes the
expected count location-dependent, which is precisely why S2 damage has never
been assessed (STATUS.md **O6**).

**8. Known pain points on the record:**

- Sentinel-2 health is **unassessed**, not cleared; needs a per-parcel
  expectation (available vs selected) — STATUS.md **O6** (open).
- S2 had no validation pass at all until `e7d4c6d`; 4 non-covering rows found
  — STATUS.md **geometry family**.
- One quarter (Rodanthe 2015 Q3) still serves a 25 % non-covering granule
  because its covering sibling is in a different quarter group — STATUS.md
  **G2** (open).
- One duplicate 2026-Q1 group that re-running cannot clear — STATUS.md **G3**
  (open).
- Same M4 per-year/per-quarter invisibility as Landsat — STATUS.md **M4**.

---

## S4. PC SAS signing service

Broken out because it is a distinct upstream with its own availability and its
own rate limit, and because a replacement for S1 or S3 would have to replace
this too.

**1. Provider.** Microsoft Planetary Computer, `/api/sas/v1`.

**2. Endpoints.** `GET {PC_TOKEN_URL}/{account}/{container}` (`stac.py:399`)
and `GET {PC_SIGN_URL}?href=…` (`stac.py:520`), both issued through
`_sas_get` (`stac.py:282-342`) on the 10 s pooled signing client
(`stac.py:229-232`).

**3. Auth.** **None outbound** — the signing endpoints are called anonymously.
Their *output* is the credential.

**4. Rate limit and retry.** Concurrency 4 (`config.py:85`), 4 attempts
(`config.py:86`), 429-only retry with `Retry-After` or 1 s-doubling backoff,
bounded by `SIGN_WAIT_BATCH`/`SIGN_WAIT_REQUEST` (`stac.py:213-214, 304-342`).
On budget exhaustion: `INFO "SAS rate-limited; backoff exceeds wait budget,
giving up"` then the 429 is raised (`stac.py:324-329, 341-342`).

**5. Caching.** `sas:{url}` (1200 s) and `sas-token:{account}/{container}`
(derived) — see [S0](#s0-planetary-computer-platform-shared-by-s1s3-s5) and the
[ledger](#caching-ledger--the-complete-picture). Single-flight coalescing on
cold mints (`stac.py:451-463`).

**6. Subset consumed.** Two of the API's endpoints; three containers in
practice (`landsateuwest/landsat-c2` hardcoded at `stac.py:221`, plus the NAIP
and Sentinel-2 containers derived from asset hrefs at `stac.py:345-360`).

**7. Failure modes.** 429 → retry within budget, then raise. **Any other
status, and any network error, is terminal on the first attempt**
(`stac.py:311-312`) — see [N1](#n1-sas-signing-retries-only-429--a-transient-pc-5xx-or-connection-error-is-terminal).
Callers translate that into: drop the snapshot (listing), 502 (tile / band /
warmup-skip), or "item is broken" (validation).

**8. Known pain points on the record:** STATUS.md **O1** (both acts),
**G4**, **G7**.

---

## S5. PC Data API `rendered_preview` thumbnails

**1. Source + provider.** Planetary Computer Data API, server-rendered PNG
previews, surfaced as STAC assets.

**2. Endpoints.** Not called by the backend at all. The href is extracted from
the STAC item (`extract_thumbnail_url`, checking `rendered_preview`,
`thumbnail`, `overview` in that order — `stac.py:976-986`), stored on the
snapshot row (`timeline.py:386`), and returned to the browser, which fetches
`https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?…`
directly (`Timeline.tsx:632-634`).

**3. Auth.** **None.** These URLs self-sign server-side, so the SAS endpoint
would hand them back unchanged; signing one is a wasted round-trip and is
skipped by path match (`_is_pc_preview` `api/imagery.py:134-135`, applied
`api/imagery.py:215-216, 259-260`).

**4. Rate limit and retry.** None — the request is the browser's.

**5. Caching.** Not cached anywhere on our side. The URL is rewritten to add
`max_size=128` unless it already carries a size parameter
(`_bounded_preview_url` `api/imagery.py:138-150`, constant `api/imagery.py:131`),
which the docstring records as ~1 MB / 2.4 s → ~19 KB (`api/imagery.py:140-144`).

**6. Subset consumed.** One asset key per item, first match of three.

**7. Failure modes.** A non-preview thumbnail (a blob href) that fails signing
is set to `None` rather than failing the snapshot — the UI has a placeholder
(`api/imagery.py:262-264`, reasoning at `:261-263`). A preview URL that 4xx/5xxs
in the browser is a broken `<img>`, handled by `imgError` state
(`Timeline.tsx:632`). Nothing on the server observes either.

**8. Known pain points on the record:** none specific to thumbnails.

---

## S6. USGS Historical Topographic Maps

**1. Source + provider.** USGS Historical Topographic Map Collection,
discovered through **The National Map (TNM) API** — not STAC. GeoTIFFs are
served from a public host named in the TNM response.

**2. Endpoints.**

| Path | Endpoint | Site |
|---|---|---|
| Search | `GET https://tnmaccess.nationalmap.gov/api/v1/products` with `datasets=Historical Topographic Maps`, `bbox`, `max`, `outputFormat=JSON` | `usgs_topo.py:19, 71-79` |
| GeoTIFF hosting | whatever `item["urls"]["GeoTIFF"]` carries — **the host is never inspected or allowlisted** | `extract_geotiff_url` `usgs_topo.py:134-140`; stored `timeline.py:486, 520-532` |
| Tile serving | `GET {titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}` with `url=<stored URL, unsigned>` | `api/imagery.py:601` → `api/imagery.py:485-486` with `sign=False` |
| Warmup | `GET {titiler_url}/cog/info`, unsigned | `api/imagery.py:650-651, 665-668` |

**3. Auth.** **None.** The code asserts these are public S3
(`usgs_topo.py:4-5`, `timeline.py:452`) and routes topo past all signing:
`_NO_SIGN_SOURCES` in the listing (`api/imagery.py:205`) and `sign=False` on the
tile path (`api/imagery.py:601`), with the same skip in warmup
(`api/imagery.py:650-651`).

**4. Rate limits and retry.** **None on either count.** One un-paginated `GET`
with `resp.raise_for_status()` (`usgs_topo.py:79-80`) — no retry wrapper, no
backoff, no error-type wrapping. Client: 30 s timeout, 10 conns / 5 keepalive,
per event loop (`usgs_topo.py:42-52`), closed at `usgs_topo.py:55-59` (called
from `timeline.py:901`).

**5. Caching.** **Nothing is cached.** Every timeline run issues a fresh TNM
query. Selected sheets land in `imagery_snapshots`; tiles get the browser's
`max-age=86400, immutable` (`api/imagery.py:431`); the snapshot row gets the 300 s
in-process LRU (`api/imagery.py:289-306`).

**6. Subset consumed.**

| Dimension | Value | Site |
|---|---|---|
| Dataset | `Historical Topographic Maps` | `usgs_topo.py:72` |
| bbox | the 1500 m search bbox | `usgs_topo.py:73`; `timeline.py:474, 964` |
| Cap | `max=100`, un-paginated | `usgs_topo.py:64, 74` |
| Filter | products with a `urls.GeoTIFF` entry only | `usgs_topo.py:99-103` |
| Selection | one sheet per **decade**: finest extent first (`_EXTENT_PRIORITY`, 11 ranks), then earliest `publicationDate` | `usgs_topo.py:23-35, 106-131` |
| Date used | `publicationDate` → Jan 1 of that year | `extract_publication_date` `usgs_topo.py:143-153` |
| Identity | `sourceId` | `usgs_topo.py:156-158` |
| Footprint | `boundingBox` → WKT polygon | `usgs_topo.py:161-171` |
| Render params | `bidx=[1,2,3]`, `rescale=0,255` | `api/imagery.py:313` |
| Resolution recorded | `None` | `timeline.py:529` |

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| TNM 4xx/5xx/timeout/non-JSON | exception propagates → caught by the broad handler → topo task marked **failed** with the message | `usgs_topo.py:79-81`; `timeline.py:457-462` |
| Response holds exactly 100 products | `WARNING "TNM query hit its row cap — results are truncated"`; counted **before** the GeoTIFF filter, deliberately | `usgs_topo.py:89-97` |
| Product with unparseable `publicationDate` | skipped with a WARNING; task still **complete** | `timeline.py:490-505`; `usgs_topo.py:174-181` |
| Product with no `sourceId` | skipped with a WARNING; task still **complete** | `timeline.py:507-518` |
| Product with no GeoTIFF URL | dropped in the search filter, silently | `usgs_topo.py:99-103` |
| Empty result | task **complete** with the DB count | `timeline.py:548-550` |

**Is failure distinguishable from empty?** **Partly, and better than the other
sources.** A whole-search failure *is* distinguishable — the task ends
`failed`, not `complete`-with-zero (`timeline.py:457-462`). What stays
invisible is per-product loss: truncation at the cap, and products skipped for
a bad date or a missing id, all end at `complete`. (STATUS.md's M4 row
summarises the topo path as dropping decades "under a `complete` task"; on the
whole-search branch that is more pessimistic than the code — the per-product
branches are the ones that match the description.)

**8. Known pain points on the record:**

- Cap is unverified and pagination deliberately unbuilt; cap-hit warning is
  the accepted instrument — STATUS.md **T3**, **L6**.
- Survey/photorevision dates are unobtainable from any structured source; only
  publication dates exist. Negative result, remedy was presentational —
  STATUS.md **T1** (note its own provenance caveat).
- The 1900 fallback date, removed — STATUS.md **T2** (resolved `c82ed51`).
- A zero-topo parcel observed in production — STATUS.md **O5** appendix,
  ops-audit §8.

---

## S7. US Census Geocoder

**1. Source + provider.** US Census Bureau Geocoding Services API. Three
distinct uses.

**2. Endpoints.**

| Use | Endpoint | Site |
|---|---|---|
| Forward geocode | `GET https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress` | URL `config.py:57-59`; call `geocoder.py:137` |
| Reverse (coords → geographies) | `GET .../geocoder/geographies/coordinates` | `geocoder.py:248, 269` |
| Vintage tract lookup | `GET .../geocoder/geographies/coordinates` with a historical `vintage` | `geocoder.py:348, 369` |

Parameters: `benchmark=Public_AR_Current`, `vintage=Current_Current`,
`layers=Census Tracts,Counties`, `format=json`
(`geocoder.py:24, 27, 118-124, 249-256`); the vintage lookup overrides
`vintage` and requests `layers=Census Tracts` only (`geocoder.py:349-356`).

**3. Auth.** Optional API key, sent as `key` when `census_api_key` is set —
`geocoder.py:125-126, 257-258, 357-358`; setting at `config.py:55`. Absence is
not an error on this API.

**4. Rate limits and retry.** `_MAX_ATTEMPTS = 3` (`geocoder.py:30`) with a
flat 1 s sleep — but **only timeouts are retried**. `HTTPStatusError` and
`RequestError` raise immediately (`geocoder.py:139-155`, `:271-281`,
`:371-381`). Timeout is `census_geocoder_timeout`, default 20 s
(`config.py:60`). A **fresh `httpx.AsyncClient` per call** — no pooling
(`geocoder.py:130, 262, 362`).

**5. Caching.** **Nothing is cached.** Every geocode is a live call. The
*result* is deduplicated at the parcel level: an existing parcel within
`parcel_dedup_radius_meters` (default 50 m, `config.py:66`) is reused
(`services/parcels.py:100-121`), which is what keeps repeat
addresses from re-geocoding. Within one census fetch, resolved vintage tracts
are memoised per vintage in `_VintageTracts._cache`
(`timeline.py:615, 621-622, 639`) — one geocoder call per distinct vintage per
parcel.

**6. Subset consumed.** Two geography layers (Census Tracts, Counties); from
tracts, `STATE`+`COUNTY`+`TRACT` concatenated into an 11-char FIPS
(`geocoder.py:179-186, 292-299, 395-405`); from counties, `BASENAME` only
(`geocoder.py:193-195, 303-305`). One vintage is used beyond the current one:
`Census2010_Current` (`census.py:86-91`).

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| Non-JSON body (the maintenance page served with 200) | `GeocoderUnavailableError` — treated as an outage, not a bad request | `_parse_json` `geocoder.py:45-73` |
| Non-object JSON | `GeocoderUnavailableError` | `geocoder.py:65-72` |
| Unexpected payload shape | `GeocoderUnavailableError` via `_shape_error` | `geocoder.py:76-87, 198-199, 306-307, 399-400` |
| No `addressMatches` | `AddressNotFoundError` → HTTP **422** with a user-facing message | `geocoder.py:165-166`; `api/geocode.py:218-223` |
| Unavailable | HTTP **502** with a curated message | `api/geocode.py:212-217` |
| Forward geocode fails but the client supplied coords | falls back to reverse geocode | `api/geocode.py:186-206` |
| Vintage lookup fails or yields no tract | falls back to the **stored** tract, with a WARNING — worst case is the pre-existing behaviour | `timeline.py:626-644`; `geocoder.py:388-393, 402-403` |
| County layer absent | `county` stays `None`. **No fallback to the tract's `NAME`** — deliberate, because "Census Tract 62.02" is truthy and would never be healed | `geocoder.py:188-195, 301-305` |

**Is failure distinguishable from empty?** Yes, on the geocode path — 502 vs
422 are different states, surfaced to the user. On the **vintage** path, no: a
geocoder outage and a vintage that genuinely has no tract both silently fall
back to the stored tract.

**8. Known pain points on the record:**

- Retry asymmetry (only timeouts retried; a transient 503 fails at once) —
  STATUS.md **M1**, explicitly flagged as defensible-but-undocumented, now
  documented at both ends.
- The `NAME`-fallback bug and its heal script — STATUS.md **L5** (resolved
  `3269bbf`).

---

## S8. US Census Data API (ACS5 + Decennial)

**1. Source + provider.** US Census Bureau data API, `api.census.gov/data`.

**2. Endpoints.**

| Dataset | Endpoint | Site |
|---|---|---|
| ACS 5-year | `GET https://api.census.gov/data/{year}/acs/acs5` | base `census.py:127`; path `census.py:153-158`; call `census.py:250` |
| Decennial 2020 | `GET .../data/2020/dec/dhc` | `census.py:29`, `census.py:182-188` |
| Decennial 2010 / 2000 | `GET .../data/{year}/dec/sf1` | `census.py:35, 42` |
| Decennial 1990 | `GET .../data/1990/dec/sf1` | `census.py:49` |

Query shape: `get=<vars>`, `for=tract:{code}`, `in=state:{s} county:{c}`
(`census.py:241-245`).

**3. Auth.** API key **required by our client** — `CensusFetcher.__init__`
raises `CensusMissingKeyError` if `api_key` is falsy (`census.py:129-135`);
sent as the `key` parameter (`census.py:246-247`). Setting: `census_api_key`
(`config.py:55`), passed at `timeline.py:1013`.

**4. Rate limits and retry.** **No retry of any kind.** A single `GET`; any
`httpx.HTTPError` becomes `CensusApiError` immediately (`census.py:249-253`).
The only backoff is a politeness `await asyncio.sleep(0.5)` between years
(`timeline.py:689, 715`). Timeout: `census_api_timeout`, default 30 s
(`config.py:56`, passed `timeline.py:1014`, applied `census.py:137`). One
client per fetch, closed in a `finally` (`census.py:139-140`;
`timeline.py:717-718`). See [N2](#n2-the-census-data-api-client-has-no-retry-at-all).

**5. Caching.** **Nothing is cached.** Rows land in `census_snapshots`
(`services/demographics.py:45-131`) and that table is the only memory. The
`/demographics` response is served `Cache-Control: no-cache`
(`api/demographics.py:37`) so late-arriving backfill is not
masked.

**6. Subset consumed.**

| Dimension | Value | Site |
|---|---|---|
| ACS5 years | 2009, 2012, 2015, 2018, 2021, 2023 | `census.py:75` |
| ACS5 variables | 11: `B01003_001E`, `B19013_001E`, `B25077_001E`, `B25035_001E`, `B25001_001E`, `B25002_003E`, `B25003_001E/002E/003E`, `B01002_001E`, `B25064_001E` | `census.py:59-71` |
| Decennial years | 1990, 2000, 2010, 2020 | `census.py:74` |
| Decennial variables | 2 per year (population + total housing units); names differ by decade | `census.py:27-56` |
| Geography | one tract, resolved per vintage | `census.py:242-244`; `timeline.py:597-644` |
| Vintage map | decennial 2010 and acs5 2012/2015/2018 → `Census2010_Current`; everything else → current | `census.py:86-96` |

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| HTTP error / timeout | `CensusApiError`, `failed_requests += 1`, **that year is lost**, loop continues | `census.py:249-253`; `timeline.py:683-687, 710-714` |
| 302 to `missing_key` (or `x-datawebapi-keyerror`) | `CensusMissingKeyError` → re-raised out of the loop → task **failed** | `census.py:255-262`; `timeline.py:686-687, 713-714` |
| 204 / 404 | returns `None` → `{}` → **silently skipped by `if data:` without incrementing `failed_requests`** | `census.py:264-269, 160-161, 190-191`; `timeline.py:670, 697` |
| 400 "unknown variable 'X'" | variable dropped, request retried without it; if it can't be attributed, raises | `_request_dropping_unknown` `census.py:195-229`; regex `census.py:121` |
| Other non-200 | `CensusApiError` | `census.py:276-281` |
| HTML error page with 200 | `CensusApiError` on JSON decode | `census.py:283-291` |
| Annotation values ≤ −111111111 | mapped to `None` | `census.py:22, 328-344` |
| **All 10** requests fail | task marked **failed** — an outage is not "no data" | `timeline.py:720-730` |
| Some fail | task **complete**; the gaps are permanent, because backfill only refetches missing/failed tasks | `timeline.py:732-735`; backfill `services/imagery.py:309-324` |

**Is failure distinguishable from empty?** **No, and this is the sharpest
instance in the system.** The `if data:` skips at `timeline.py:670` and
`:697` are the M4 silent-skip sites named in the brief: a 204/404 year returns
`{}`, is skipped, and does **not** increment `failed_requests`
(`timeline.py:684, 711`), so the all-failed check at `timeline.py:723` cannot
see it either. A year absent because Census has no data and a year absent
because the request 404'd are the same row-that-isn't-there.

**8. Known pain points on the record:**

- Per-year failure persistence — STATUS.md **M4** (Scheduled; three production
  instances, one of them four `httpx.ReadTimeout`s against `api.census.gov`).
- One parcel (Racebrook Road, Orange CT) where nothing in the system can say
  whether years re-failed or were never published — STATUS.md **M4 (4)**.
- The 2020 tract-split vintage gaps and their heal — STATUS.md **M4**,
  `scripts/heal_tract_vintage_gaps.py`.
- Decennial rows are structurally excluded from the Housing chart — STATUS.md
  **H1 decennial half** (deferred).
- The census upsert not refreshing `tract_fips` — STATUS.md notes-for-future-readers
  (fixed `386f3e3`).

---

## S9. Photon (komoot) — address autocomplete

**1. Source + provider.** Photon, komoot's public OSM-derived geocoder.

**2. Endpoint.** `GET https://photon.komoot.io/api` with
`q`, `bbox=-125.0,24.0,-66.0,50.0`, `limit=6`, `lang=en` —
`api/geocode.py:68-75`, bbox constant `api/geocode.py:32`.

**3. Auth.** **None.** A `User-Agent: Plotline/1.0 (address-history-app)`
header is sent (`api/geocode.py:65`); no key, no token.

**4. Rate limits and retry.** **No retry.** Timeout **3 s**
(`api/geocode.py:64`), a fresh client per request (`api/geocode.py:63-66`). Our own
inbound limit is 60 req/min/IP (`api/geocode.py:45`). Photon's own limits are
undocumented here and unhandled — there is no 429 branch.

**5. Caching.** Redis `autocomplete:{q.lower().strip()}`, **300 s**
(`_AUTOCOMPLETE_CACHE_TTL` `api/geocode.py:34`; read `api/geocode.py:52-60`; write
`api/geocode.py:146-151`). This uses the **synchronous** Redis client inside an
`async` handler (`api/geocode.py:56, 147`) — STATUS.md **M5**.

**6. Subset consumed.** `features[]` filtered to `countrycode == "US"`
(`api/geocode.py:90`), requiring 2-element coordinates (`api/geocode.py:93-95`);
display name assembled from `housenumber`/`street`/`name`, `city`/`town`/`village`,
`state`, `postcode` (`api/geocode.py:98-121`); deduplicated by display name
(`api/geocode.py:127-129`); capped at 5 results (`api/geocode.py:142-143`).

**7. Failure modes as implemented.** `RequestError` → `return []`
(`api/geocode.py:77-79`). `HTTPStatusError` → `return []` (`api/geocode.py:80-82`).
Both log a WARNING and both are **indistinguishable from "no suggestions"** to
the caller and the user. See [N4](#n4-photon-failure-returns-an-empty-suggestion-list).

**8. Known pain points on the record:**

- Sync Redis I/O on the event loop, autocomplete half **not** accepted —
  STATUS.md **M5** (open).
- Frontend debounce and input-clearing self-DoS — STATUS.md **L8** (open).

---

## S10. Denver County — ArcGIS Hub

**1. Source + provider.** Denver open data on ArcGIS Hub (migrated off Socrata
c. 2025 — `county_adapters.py:196-200`).

**2. Endpoints.** `GET {layer}/query` (`arcgis.py:58, 67`) against:

- `https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_DEV_RESIDENTIALCONSTPERMIT_P/FeatureServer/316` — `county_adapters.py:202-203`
- `.../ODC_DEV_COMMERCIALCONSTPERMIT_P/FeatureServer/317` — `county_adapters.py:204`

Both queried concurrently (`county_adapters.py:250-253`).

**3. Auth.** **None.**

**4. Rate limits and retry.** No retry. Timeout 30 s default
(`arcgis.py:29`), a fresh `AsyncClient` with `follow_redirects=True` per query
(`arcgis.py:65`). Failures are caught per query and converted to `None`
(`county_adapters.py:246-248`).

**5. Caching.** **Nothing is cached.** Events persist to `property_events`
(`property_events.py`), and `/events` is served `no-cache`
(`api/events.py:46`).

**6. Subset consumed.** `where = upper(ADDRESS) LIKE '{num} %{name}%'`
(`county_adapters.py:236`), `outFields=*`, `orderByFields=DATE_ISSUED DESC`,
`resultRecordCount=100`, `f=json`, `returnGeometry=false`
(`county_adapters.py:240-245`; `arcgis.py:48-56`). Fields read:
`DATE_ISSUED`, `CLASS`, `VALUATION`, `PERMIT_NUM`, `CONTRACTOR_NAME`,
`ADDRESS` (`county_adapters.py:256-282`). **Sales are not available** — the
adapter returns an empty `SourceFetchResult` with zero attempts
(`county_adapters.py:214-223`).

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| Timeout / request error | `ArcGISError` | `arcgis.py:68-71` |
| Non-200 | `ArcGISError` with body excerpt logged | `arcgis.py:73-78` |
| 200 with non-JSON (HTML error page) | `ArcGISError` — deliberately, so one query fails rather than the task | `arcgis.py:83-92` |
| `{"error": …}` in a 200 body | `ArcGISError` | `arcgis.py:97-99` |
| Any of the above | that query counts as failed via a `None` chunk | `_collect` `county_adapters.py:124-143` |
| Rows == cap | `WARNING "ArcGIS query hit its row cap — results are truncated"` | `arcgis.py:108-112` |
| **All** queries across sales+permits fail | property task marked **failed** | `timeline.py:829-842` |
| Some fail | task **complete** | `timeline.py:886` |
| Record's address fails the fuzzy match | dropped silently | `timeline.py:848-852` |
| Record has no `source_record_id` | skipped silently | `timeline.py:866-867` |

**Is failure distinguishable from empty?** At the adapter level yes — the
`queries_attempted` / `queries_failed` counters exist precisely for this
(`SourceFetchResult` docstring, `county_adapters.py:105-121`). Below that,
no: a partial failure, a too-narrow `LIKE`, and a genuinely permit-free
address all yield `complete` with a smaller count.

**8. Known pain points on the record:**

- Row caps: pagination accepted-not-built; cap-hit warning is the instrument,
  and it has already fired once (DC) — STATUS.md **counties item 13**, **G6**.
- `WHERE`-clause escaping is quote-doubling only, and anchoring differs
  between adapters — STATUS.md **L3** (open).
- `ON CONFLICT DO NOTHING` freezes property records — STATUS.md **M8** (open).
- The 2026-08-11 incident parcel recorded `property complete:0` while its five
  Denver peers hold 10–33 events — STATUS.md **to investigate**.

---

## S11. Adams County — ArcGIS Hub

**1. Source + provider.** Adams County "Eye On Adams" Feature Service on
ArcGIS Hub.

**2. Endpoint.** `GET https://services3.arcgis.com/4PNQOtAivErR7nbT/arcgis/rest/services/Building_Permits_Eye_On_Adams/FeatureServer/0/query`
— `county_adapters.py:300-303`, call `county_adapters.py:335-340`, `/query`
suffix `arcgis.py:58`.

**3. Auth.** **None.**

**4. Rate limits and retry.** Same shared client as S10 — no retry, 30 s
timeout (`arcgis.py:29, 65`), single query, failure → `None`
(`county_adapters.py:341-343`).

**5. Caching.** **Nothing is cached.**

**6. Subset consumed.** `where = upper(CombinedAddress) LIKE '{num} %{name}%'`
(`county_adapters.py:332`), `orderByFields=CaseOpened DESC`, cap 100
(`county_adapters.py:338-339`). Fields: `CaseOpened`, `TypeOfWork`,
`ClassOfWork`, `Description`, `RecordID_`, `CombinedAddress`
(`county_adapters.py:346-363`). Sales unavailable
(`county_adapters.py:313-321`). Coverage caveat written into the docstring:
unincorporated areas only; Thornton, Westminster etc. issue their own permits
(`county_adapters.py:295-297`).

**7. Failure modes as implemented.** Identical to S10 (`arcgis.py:68-112`;
`county_adapters.py:341-344`; `timeline.py:829-842`).

**8. Known pain points on the record:**

- **Adams returns empty, every time** — five property tasks across two months,
  all `complete` with `items_found: 0`, zero `property_events` rows ever.
  Needs a manual portal check before any code — STATUS.md **to investigate**;
  ops audit MEDIUM-3.
- Row caps / escaping / DO NOTHING as S10.

---

## S12. District of Columbia — DCGIS

**1. Source + provider.** DC Open Data via DCGIS ArcGIS REST services. The
only adapter with both sales and permits.

**2. Endpoints.**

| Use | Endpoint | Site |
|---|---|---|
| Sales | `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Property_and_Land_WebMercator/MapServer/56/query` (ITSPE FACTS) | `county_adapters.py:388-392`; call `:428-437` |
| Permits | `https://maps2.dcgis.dc.gov/dcgis/rest/services/FEEDS/DCRA/MapServer/{layer}/query`, **7 year-specific layers**: 18=2026, 17=2025, 16=2024, 15=2023, 14=2022, 3=2021, 2=2020 | `county_adapters.py:394-404`; call `:482-497` |

All 7 permit layers are queried concurrently (`county_adapters.py:497`).

**3. Auth.** **None.**

**4. Rate limits and retry.** No retry; 30 s per query; per-query failure →
`None` (`county_adapters.py:438-440, 491-495`).

**5. Caching.** **Nothing is cached.**

**6. Subset consumed.**

- Sales: `where = upper(PROPERTY_ADDRESS) LIKE '{num} %{name}%'` — anchored at
  the start deliberately, so "100 X" cannot match "1100 X"
  (`county_adapters.py:423-425`); explicit `out_fields` list of 7 columns
  (`county_adapters.py:431-435`); cap **20** (`county_adapters.py:436`). Rows
  with no `LAST_SALE_PRICE` are dropped (`county_adapters.py:443-445`).
- Permits: `where = upper(FULL_ADDRESS) LIKE '{num} %{name}%'`
  (`county_adapters.py:480`), `orderByFields=ISSUE_DATE DESC`, cap **50** per
  layer (`county_adapters.py:488-489`). Fields: `ISSUE_DATE`,
  `PERMIT_TYPE_NAME`, `PERMIT_SUBTYPE_NAME`, `DESC_OF_WORK`, `FEES_PAID`,
  `PERMIT_ID`, `FULL_ADDRESS` (`county_adapters.py:500-530`).

**7. Failure modes as implemented.** As S10 (`arcgis.py:68-112`). Note the
sales cap of 20 is the lowest in the system, and the ArcGIS cap-hit warning
**has fired on this layer in production** (STATUS.md **G6**).

**8. Known pain points on the record:**

- G6: a DC ArcGIS query hit its row cap at 03:48:33Z — the evidence counties
  item 13 was waiting for — STATUS.md **G6**.
- Hardcoded year-by-year permit layers are an annual manual chore, accepted —
  STATUS.md **L12, DC permit layers**.
- `APPRAISED_VALUE_CURRENT_TOTAL` is fetched but unused — STATUS.md **counties
  code oddities** (open).

---

## S13. Santa Clara / City of San Jose — CKAN

**1. Source + provider.** City of San Jose open data on CKAN
(`data.sanjoseca.gov`). Covers San Jose addresses only; other Santa Clara
cities have their own portals or none (`county_adapters.py:542-544`).

**2. Endpoint.** `GET https://data.sanjoseca.gov/api/3/action/datastore_search`
— `ckan.py:49, 67`; domain `county_adapters.py:547`. **Three resources**,
queried concurrently (`county_adapters.py:549-553, 597`):
`761b7ae8-…` (active), `89ccdad9-…` (under_inspection), `df4b8461-…` (expired).

**3. Auth.** **None.**

**4. Rate limits and retry.** No retry; 30 s timeout; fresh client with
`follow_redirects=True` per query (`ckan.py:30, 65`); per-query failure →
`None` (`county_adapters.py:591-595`).

**5. Caching.** **Nothing is cached.**

**6. Subset consumed.** CKAN full-text `q = "{street_number} {street_name}"`
(`county_adapters.py:581`), `limit=100`, `offset=0` (`ckan.py:50-54`;
`county_adapters.py:589`). Results are then re-filtered in Python: the first
whitespace token of `gx_location` must equal the street number exactly and the
street name must appear in the location — a substring check would let "12"
match "512 S 1ST ST" (`county_adapters.py:599-606`). Fields read:
`ISSUEDATE`, `WORKDESCRIPTION`, `FOLDERDESC`, `FOLDERNAME`,
`PERMITVALUATION`, `CONTRACTOR`, `FOLDERNUMBER`, `gx_location`
(`county_adapters.py:610-638`). Sales unavailable
(`county_adapters.py:563-571`).

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| Timeout / request error | `CKANError` | `ckan.py:68-71` |
| Non-200 | `CKANError` | `ckan.py:73-83` |
| 200 non-JSON | `CKANError` | `ckan.py:88-97` |
| `success: false` | `CKANError` with the portal's message | `ckan.py:102-104` |
| Records == cap | `WARNING "CKAN query hit its row cap — results are truncated"` | `ckan.py:112-116` |
| Rows failing the Python address re-filter | dropped silently | `county_adapters.py:601-606` |

Rollup to the task is the same as S10 (`timeline.py:829-842`).

**8. Known pain points on the record:**

- Santa Clara coverage is thin — two parcels, one event between them —
  STATUS.md **to investigate** (weaker than the Adams case but the same
  shape).
- Row caps, escaping, DO NOTHING as S10.

---

## S14. New York County (Manhattan) — NYC Open Data (Socrata)

**1. Source + provider.** NYC Open Data on Socrata
(`data.cityofnewyork.us`). The richest adapter: two sales datasets plus
permits.

**2. Endpoints.** `GET https://data.cityofnewyork.us/resource/{id}.json`
(`socrata.py:49, 67`), with:

| Resource | Id | Site |
|---|---|---|
| Annualized Calendar Sales (2016+) | `w2pb-icbu` | `county_adapters.py:675` |
| Rolling Calendar Sales (trailing ~12 months — the only source for the current year) | `usep-8jbt` | `county_adapters.py:676` |
| DOB Permit Issuance | `ipu4-2q9a` | `county_adapters.py:678` |

The two sales resources are queried concurrently
(`county_adapters.py:713`); overlapping rows dedupe on a synthesised
`block-lot-date` record id at upsert time (`county_adapters.py:730-734`, and
the note at `:666-670`).

**3. Auth.** Optional Socrata app token, sent as the `X-App-Token` header
when present (`socrata.py:56-58`); setting `socrata_app_token`
(`config.py:63`, "increases rate limit 1K→10K/hr"), passed from
`timeline.py:1029` → `timeline.py:822-823` → `county_adapters.py:707, 767`.

**4. Rate limits and retry.** No retry; 30 s timeout; fresh client with
`follow_redirects=True` per query (`socrata.py:30, 65`). The app token is the
only rate-limit lever; there is no 429 handling
(`socrata.py:80-90` treats it as a generic non-200).

**5. Caching.** **Nothing is cached.**

**6. Subset consumed.**

- Sales: `$where = borough='1' AND upper(address) LIKE '%{num} {name}%' AND sale_price > 0`
  (`county_adapters.py:697`), `$order = sale_date DESC`, `$limit = 200`
  (`county_adapters.py:704-706`; params built `socrata.py:50-54`). Fields:
  `sale_date`, `sale_price`, `neighborhood`, `building_class_category`,
  `block`, `lot`, `address` (`county_adapters.py:716-748`).
- Permits: `$where = borough='MANHATTAN' AND house__='{num}' AND upper(street_name) LIKE '%{name}%'`
  (`county_adapters.py:759`), `$order = issuance_date DESC`, `$limit = 100`
  (`county_adapters.py:766-768`). Fields: `issuance_date`, `job_type`,
  `permit_type`, `owner_s_business_name`, `filing_status`, `house__`,
  `street_name`, `job__` (`county_adapters.py:775-814`). DOB job types are
  mapped to readable labels via a 5-entry table
  (`county_adapters.py:781-788`).

**7. Failure modes as implemented.**

| Event | Behaviour | Site |
|---|---|---|
| Timeout / request error | `SocrataError` | `socrata.py:68-71` |
| **404** | logs a WARNING and returns `[]` — **a retired dataset is indistinguishable from an address with no records** | `socrata.py:73-78` |
| Other non-200 | `SocrataError` | `socrata.py:80-90` |
| 200 non-JSON | `SocrataError` | `socrata.py:95-104` |
| Non-list body | `SocrataError` | `socrata.py:106-107` |
| Rows == limit | `WARNING "Socrata query hit its row cap — results are truncated"` | `socrata.py:113-117` |

Rollup as S10 (`timeline.py:829-842`).

**8. Known pain points on the record:**

- Row caps — STATUS.md **counties item 13**, **G6**.
- Address-matching threshold discards records whose street naming differs
  (NYC DOB spells out directionals) — second-audit **H5** (resolved
  `add8102`), matcher at `address_normalizer.py`.
- `WHERE` anchoring differs between the NYC adapter (`%`-prefixed) and the
  ArcGIS ones (anchored) — STATUS.md **L3** (open).

---

## S15. OpenFreeMap — basemap tiles

**1. Source + provider.** OpenFreeMap "liberty" style, fetched **directly by
the browser**, never by our backend.

**2. Endpoint.** `https://tiles.openfreemap.org/styles/liberty` —
`MapView.tsx:29` (used at `:74`) and
`CompareView.tsx:22` (used at `:79, :89`). The style
document then drives all tile and glyph fetches from the client.

**3. Auth.** **None.** No key, no referrer restriction in our code.

**4. Rate limits and retry.** None on our side; entirely MapLibre's and the
browser's.

**5. Caching.** **Nothing on our side** — browser HTTP cache only.

**6. Subset consumed.** One style URL. Our imagery raster layers are inserted
below `boundary_3`, falling back to `building`
(`applyImageryLayer.ts:97-101`) — a dependency on that
style's layer names.

**7. Failure modes.** If the style fails to load, MapLibre renders no basemap;
nothing in our code observes or reports it. Imagery layers are added relative
to layer ids that would then be absent — `beforeLayer` becomes `undefined`
and layers stack on top (`applyImageryLayer.ts:97-101, 103-118`), so imagery
still renders.

**8. Known pain points on the record:** none.

---

## T. Titiler — self-hosted, *not* an external source

Included because it is the component that actually reads source bytes, and
because a hosting change for S1 or S3 lands here.

- **Image**: `ghcr.io/developmentseed/titiler:1.2.1` (`fly.titiler.toml:10`).
- **Our endpoints into it**: `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
  (`api/imagery.py:485`), `/stac/tiles/WebMercatorQuad/{z}/{x}/{y}.png`
  (`api/imagery.py:563`), `/cog/info` (`api/imagery.py:666`), `/stac/info`
  (`api/imagery.py:646`), `/cog/bbox/{bbox}/{w}x{h}.png`
  (`preview_renderer.py:96-98`).
- **Its egress**: signed Azure Blob URLs (S1–S3) and unsigned public GeoTIFF
  URLs (S6), passed as the `url` query parameter. **No host allowlist is
  applied to that parameter** for any source — the allowlist at
  `api/imagery.py:336-340` guards only the API's own Landsat item fetch. See
  [N5](#n5-no-host-allowlist-on-the-url-parameter-handed-to-titiler).
- **Its own item cache**: rio-tiler's module-level `LRUCache(maxsize=512)`
  with no TTL, keyed on the item URL. No environment variable bounds it; the
  reasoning and the failed `RIO_TILER_CACHE_TTL` attempt are recorded at
  `fly.titiler.toml:24-31`.
- **GDAL tuning**: `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, `VSI_CACHE=TRUE`,
  `VSI_CACHE_SIZE=268435456`, `GDAL_CACHEMAX=200`,
  `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff`,
  `GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES`, `GDAL_HTTP_MULTIPLEX=YES`,
  `GDAL_HTTP_MAX_RETRY=3`, `GDAL_HTTP_RETRY_DELAY=1`
  (`fly.titiler.toml:14-23`).
- **Routing**: Titiler reaches the API back over the **public** URL
  (`api_internal_url`, `config.py:92`), because Fly private DNS is IPv6-only
  and the internal addressing attempt was reverted — accepted, STATUS.md
  **M9**.

---

## Dependency table — what breaks if a source goes away

| Source | Product surface that breaks | Degradation shape | Anchor |
|---|---|---|---|
| PC STAC API (S0) | **All three imagery sources at once**: no NAIP, Landsat or Sentinel-2 rows can be created | New parcels get imagery tasks marked `failed`; existing parcels keep serving stored rows until their tokens can't be signed | `timeline.py:207-210` |
| PC SAS signing (S4) | NAIP + Sentinel-2 tiles and thumbnails; Landsat tiles (band signing); Landsat validation | Listing silently drops snapshots; tiles 502 | `api/imagery.py:229-246, 464-479, 790-804` |
| Azure Blob (S1–S3 hosting) | All raster tiles for the three PC sources | Titiler 500 → our 502 | `api/imagery.py:394-401` |
| PC Data API (S5) | Timeline thumbnails only | Broken `<img>` → placeholder | `Timeline.tsx:632` |
| NAIP collection alone | The 1 m aerial layer, featured-card previews (`preview_renderer` reads NAIP only) | Timeline loses its highest-resolution decade cards; featured previews cannot be rendered | `preview_renderer.py:69-73` |
| Landsat collection alone | The entire pre-2010 timeline; the "how it changed" narrative | Timeline starts at 2010–2011 | `timeline.py:68` |
| Sentinel-2 collection alone | Quarterly recent-change cards, 2015→ | Timeline loses intra-year granularity | `timeline.py:80` |
| USGS TNM (S6) | Historical topo cards (pre-aerial era, back to the 1890s) | `usgs_topo` task `failed`; no topo cards | `timeline.py:457-462` |
| Topo GeoTIFF host (S6) | Topo tile rendering (search still succeeds) | Rows exist, tiles 502 | `api/imagery.py:394-401` |
| Census Geocoder (S7) | **The entire product.** No address can be resolved → no parcel → no timeline, no demographics, no property | `POST /geocode` returns 502 | `api/geocode.py:212-217` |
| Census Geocoder — vintage endpoint only | Pre-2020-geography ACS/decennial accuracy | Falls back to the stored tract; wrong-tract numbers rather than no numbers | `timeline.py:626-644` |
| Census Data API (S8) | The whole demographics panel | Census task `failed` if all 10 requests fail; partial loss otherwise | `timeline.py:720-730` |
| Photon (S9) | Address autocomplete only | Empty dropdown; typed addresses still geocode | `api/geocode.py:77-82` |
| Denver ArcGIS (S10) | Denver permits | Property task `failed` (all queries) or `complete` with fewer rows | `timeline.py:829-842` |
| Adams ArcGIS (S11) | Adams permits | as above | `timeline.py:829-842` |
| DC DCGIS (S12) | DC sales **and** permits | as above | `timeline.py:829-842` |
| San Jose CKAN (S13) | San Jose permits | as above | `timeline.py:829-842` |
| NYC Socrata (S14) | Manhattan sales **and** permits | as above; a 404 degrades to "no records" | `socrata.py:73-78` |
| OpenFreeMap (S15) | Basemap under the imagery | No basemap; imagery still renders | `MapView.tsx:29` |
| Titiler (T) | **Every raster tile** from every imagery source | 502 on all tiles; timeline metadata and demographics unaffected | `api/imagery.py:390-392` |
| Redis | Signing caches, autocomplete cache, rate limits, **and the Celery broker** | Caches and limits fail open (`stac.py:379-381`, `rate_limit.py:71-73`); the broker does not — dispatch marks the request `failed` | `services/imagery.py:161-185` |

---

## Quirks a replacement source would need to match

**NAIP (S1)**
- Multi-tile **mosaic per year**: up to 3 tiles chosen greedily by viewport
  overlap, tie-broken by proximity to day-of-year 196 (~15 July), stopping at
  95 % coverage; the "remaining uncovered" rectangle is a documented
  rectangular approximation of a non-rectangular union
  (`stac.py:730-863`, esp. `:774-859`).
- Components ride on the snapshot as `additional_cog_urls` and are rendered as
  **stacked raster layers** addressed by `?cog=N`
  (`applyImageryLayer.ts:85-94`; `api/imagery.py:451-457`).
- A year with no tile containing the point must be **suppressed**, not
  best-effort mosaicked (`stac.py:623-648`).
- 4-band uint8 RGBI where band 4 is dropped by `bidx=[1,2,3]`
  (`api/imagery.py:311`).
- Asset key `image`, with a GeoTIFF media-type check that treats a missing
  `type` as safe (`stac.py:946-949, 918-928`).
- A collection start that is the *source's* edge, not a truncation
  (`timeline.py:48-57`).

**Landsat (S2)**
- **Validation fallback walk**: HEAD the `red` band; on failure iterate the
  same year's candidates in ascending cloud cover; drop the year if none pass
  (`stac.py:1056-1128, 1131-1142`).
- **Separate single-band COGs** requiring server-side RGB composition — which
  is why the pipeline stores an *item link*, not an asset href, and needs the
  `/stac` indirection at all (`stac.py:951-963`; `api/imagery.py:538-564`).
- LE07 (SLC-off, striped since 2003) deprioritised to fallback-only
  (`stac.py:877-889`).
- Missing `eo:cloud_cover` must read as 100, not 0 (`stac.py:720-723`).
- Surface-reflectance DN handling: `nodata=0`, `rescale 7000,14000`
  (`api/imagery.py:553-562`).
- Year-chunked search because ordering is unspecified (`timeline.py:228-233`).
- A **cache key that rotates with the credential** — anything caching the item
  document must not outlive the token inside it (`api/imagery.py:497-535`).

**Sentinel-2 (S3)**
- **Quarter** grouping, not year — one granule per calendar quarter
  (`stac.py:896-912`), and reconciliation must bucket the same way
  (`services/imagery.py:573-577`; `timeline.py:429`).
- A single pre-composited uint8 RGB asset (`visual`/TCI); the raw B04 route is
  explicitly rejected on data-range grounds (`stac.py:965-971`).
- Its own quarter-scoped validation walk (`stac.py:1145-1163`).
- Cloud-cover filtering makes the expected per-parcel count location-dependent
  — any health metric has to be per-parcel, not a flat threshold (STATUS.md
  **O6**).

**USGS topo (S6)**
- **One sheet per decade**, ranked by extent fineness across an 11-entry
  priority table, then earliest publication year (`usgs_topo.py:23-35,
  106-131`).
- Reconciliation scoped to the **decade** (`services/imagery.py:573-577`;
  `timeline.py:545`).
- Dates are **publication** dates only; survey and photorevision dates exist
  only in the scanned map collar (STATUS.md **T1**), so a replacement claiming
  survey dates would be a genuine capability gain, not a like-for-like swap.
- Products carry `sourceId` as the identity key and a `boundingBox` object
  (not a STAC bbox array) (`usgs_topo.py:156-171`).
- Public, unsigned COG URLs — the whole `_NO_SIGN_SOURCES` branch exists for
  this (`api/imagery.py:205, 601, 650-651`).

**Census (S7/S8)**
- **Vintage/ancestor-tract logic**: a tract resolved at current (2020)
  geography does not exist in a year published on 2010 geography, and FIPS
  arithmetic cannot bridge it — the point must be re-resolved at the older
  vintage (`geocoder.py:328-347`; map at `census.py:77-96`).
- Per-vintage memoisation, one geocoder call per distinct vintage per parcel
  (`timeline.py:597-644`).
- The upsert must **relabel `tract_fips`** when a re-run resolves a different
  ancestor, or a row carries one tract's label over another's numbers
  (`services/demographics.py:56-62, 91`).
- Tract-split seams must break trend computation: subtitles are computed over
  the longest single-geography run, with wording that scopes them
  (`services/demographics.py:196-238`).
- Variable names **drift by decade** and an unknown variable rejects the whole
  request — hence the drop-and-retry loop (`census.py:107-121, 195-229`).
- Large negative annotation values mean "not available"
  (`census.py:18-22, 328-344`).
- 11-char FIPS decomposition into state/county/tract (`census.py:294-302`).

**County property (S10–S14)**
- A common `SourceFetchResult` contract carrying `queries_attempted` /
  `queries_failed`, because empty and broken are otherwise identical
  (`county_adapters.py:105-143`).
- Deliberately broad `LIKE` queries plus a **fuzzy address re-match** in the
  caller (`timeline.py:846-852`), because portal address spellings differ.
- Per-county date formats: ArcGIS epoch-milliseconds
  (`county_adapters.py:839-848`), San Jose `M/D/YYYY h:mm:ss AM`
  (`county_adapters.py:640-655`), NYC `MM/DD/YYYY` or ISO
  (`county_adapters.py:816-833`).
- A stable per-record id; where none exists one is synthesised
  (`county_adapters.py:730-734`), and records without one are dropped
  (`timeline.py:866-867`).
- Permit-type normalisation into our enum, with "RENEWAL" checked *before*
  "NEW" (`classify_permit` `county_adapters.py:854-883`).
- A `display_name` is abstract on the base class so an adapter cannot be
  registered without one (`county_adapters.py:157-166`).

**Any PC replacement (S0/S4)**
- Two-tier signing (container-scoped and per-URL) with different cache
  semantics (`stac.py:524-564`).
- A credential whose expiry is **parseable from the URL**, because the TTL, the
  cache key, and the HTTP `Cache-Control` are all derived from it
  (`stac.py:466-515`; `api/imagery.py:497-535, 677-698`).
- Rate limiting on *request rate*, answered with a semaphore plus 429 backoff
  rather than volume budgeting (`config.py:79-86`; `stac.py:282-342`).
- Two caller profiles with different deadlines — the 60 s/2 s split is not
  incidental (`stac.py:200-214`).

---

## Caching ledger — the complete picture

The brief asks whether FINDINGS.md's claim still holds — that Redis holds only
SAS signatures under `sas:{url}` at 600 s. **It does not, on either half.**
The first audit's line is `docs/audits/2026-05-first-audit/FINDINGS.md:132`
("SAS tokens are cached for 10 minutes (tokens last ~30 minutes) … if signing
fails, falls back to unsigned URL"). Against HEAD:

- `sas:{url}` TTL is **1200 s**, not 600 (`stac.py:179`), and the blob path no
  longer uses that key at all (`stac.py:543-546`).
- **Four** other Redis keys exist (below).
- The unsigned-URL fallback is **gone** from every site — STATUS.md **O1**.

That findings document is frozen and may only be annotated, so this section is
the correction of record.

**Redis (all keys, verified by enumerating every `get`/`set`/`setex` call in
`backend/app`):**

| Key | Contents | TTL | Sites |
|---|---|---|---|
| `sas:{url}` | signed href (non-blob URLs only) | 1200 s | `stac.py:548, 553, 560`; TTL `stac.py:179` |
| `sas-token:{account}/{container}` | container SAS token | token `se` − 300 s; 1200 s if unparseable; not cached if under the margin | `stac.py:446`, `:371-384`, `:408-413`, `:487-504` |
| `stac:{snapshot_id}` | raw **unsigned** Landsat STAC item JSON | 3600 s | `api/imagery.py:739, 743, 768` |
| `autocomplete:{q}` | Photon suggestions | 300 s | `api/geocode.py:52, 56, 147-151` |
| `ratelimit:{path}:{ip}` | fixed-window counter | the window (`EXPIRE … NX`) | `rate_limit.py:59, 67-70` |

Redis is also the **Celery broker and result backend**
(`celery_app.py:37-42`), with results disabled (`task_ignore_result=True`,
`celery_app.py:53`).

**In-process caches:**

| Cache | Contents | Bound | Site |
|---|---|---|---|
| `_snapshot_cache` | `ImagerySnapshotRow` by id | 300 s TTL, 500 entries, LRU | `api/imagery.py:289-306` |
| `_VintageTracts._cache` | tract FIPS per vintage | per census fetch | `timeline.py:615, 621-622, 639` |
| `_search_clients` / `_sign_clients` / `_tnm_clients` | httpx connection pools | per event loop | `stac.py:85-86`; `usgs_topo.py:39` |
| `_sign_semaphores` / `_token_flights` | concurrency + single-flight state | per event loop | `stac.py:254, 368` |
| `get_settings` | `Settings` | `lru_cache(maxsize=1)` | `config.py:116-119` |

**Not cached at all — every request goes upstream:**

- **Every STAC search.** ~43 Landsat year-chunks + ~12 Sentinel-2 year-chunks
  + 1 NAIP search per timeline run, every run (`timeline.py:246-267,
  270-282`).
- **Every TNM query** (`usgs_topo.py:79`).
- **Every Census Data API request** — 10 per parcel per run
  (`census.py:250`).
- **Every Census Geocoder call** — forward, reverse, and per-vintage
  (`geocoder.py:137, 269, 369`); deduplication happens at the parcel row, not
  the HTTP layer (`services/parcels.py:100-121`).
- **Every county portal query** — 2 (Denver), 1 (Adams), 8 (DC), 3 (San Jose),
  3 (NYC) per run (`arcgis.py:67`; `ckan.py:67`; `socrata.py:67`).
- **Every tile render.** No tile bytes are stored anywhere on our side; the
  only tile caching is the browser's `max-age=86400, immutable`
  (`api/imagery.py:431`) and Titiler's in-process GDAL/VSI caches
  (`fly.titiler.toml:15-17`).

**Persistent store as de facto cache.** `imagery_snapshots`
(`services/imagery.py:672-762`), `census_snapshots` (`services/demographics.py:45-131`) and
`property_events` are the only durable memory of any upstream response.
Re-running is governed by `maybe_refetch_for_backfill`
(`services/imagery.py:285-400`) with a 6-hour cooldown (`config.py:72`;
`services/imagery.py:372-390`), and backfill only ever triggers on **missing, skipped,
or failed** tasks — never on a `complete` task with gaps
(`services/imagery.py:309-360`). That rule is what turns every "complete with zero"
above into a permanent gap.

---

## New findings

Not on STATUS.md as of HEAD `103ddab`. Recorded, not touched.

### N1. SAS signing retries only 429 — a transient PC 5xx or connection error is terminal

**Severity: MEDIUM.** `_sas_get` (`stac.py:282-342`) branches on
`resp.status_code != 429` and calls `raise_for_status()` immediately
(`stac.py:311-312`); `httpx.RequestError` is never caught inside the loop at
all. So a 503 from `/api/sas/v1/token/...`, or a reset connection, fails on
the first attempt, with none of the 4 attempts, the semaphore backoff, or the
wait budget applying.

The docstring's own argument extends to this case: it says a 429 means "slow
down", not "this asset is broken" (`stac.py:293-295`) — the same is true of a
503. The consequence differs by caller, and the worker one is the expensive
one: `_validate_asset` catches the raised error and returns `False`
(`stac.py:1010-1017`), which `_validate_selection` reads as "item is broken"
and answers by walking every same-period candidate (`stac.py:1107-1123`) —
each of which signs against the same unhealthy endpoint. A brief signing
outage therefore burns the fallbacks and drops the year with
`WARNING "No valid %s item for %s; skipping"` (`stac.py:1126`), under a task
that still ends `complete` (`timeline.py:435`). That is an M4-shaped permanent
gap from a cause M4 does not name (M4's three instances are 429s, a pre-deploy
release, and Census timeouts).

Note the asymmetry with the search path, which *does* retry
`{429, 500, 502, 503, 504}` and `RequestError` (`timeline.py:94, 125-130`).

### N2. The Census Data API client has no retry at all

**Severity: MEDIUM.** `CensusFetcher._request` issues one `GET` and converts
any `httpx.HTTPError` — timeout, connect error, read error — directly into
`CensusApiError` (`census.py:249-253`). There is no attempt loop, no backoff,
and no distinction between a retryable and a permanent failure. The only
pacing is `await asyncio.sleep(0.5)` between years (`timeline.py:689, 715`),
which is politeness, not retry.

This is the direct mechanism of M4's third production instance — four
`httpx.ReadTimeout`s against `api.census.gov` costing one parcel its acs5 2021
and decennial 2020 rows. M4 records that outcome and prescribes per-year
failure *persistence*; nothing on the ledger records that the client would not
have retried a single one of those four timeouts. Both the geocoder
(`geocoder.py:30, 139-147`) and the STAC search (`timeline.py:97-135`) retry;
this client is the outlier.

### N3. STATUS.md's M9 row states the warmup rate limit as 30/min; it is 60/min

**Severity: LOW (record drift).** STATUS.md M9 reads "`/warmup` (30/min) and
`/{id}/stac` (600/min)". The code is
`RateLimit(times=60, seconds=60)` (`api/imagery.py:624`), raised from 30 by
`69b94e1` ("perf: warm a snapshot once per session, not once per scrub hop"),
verified as an ancestor of HEAD. The `/stac` half (600/min) is still accurate
(`api/imagery.py:721`). Per CLAUDE.md's "the record moves with the code", the M9
row is stale.

### N4. Photon failure returns an empty suggestion list

**Severity: LOW.** Both `httpx.RequestError` and `httpx.HTTPStatusError` are
answered with `return []` (`api/geocode.py:77-82`). To the caller — and to the
user — a Photon outage, a 429, and "no US addresses match this prefix" are the
same empty dropdown. It is the "complete with zero" pattern on the one path
where nothing persists, so no backfill or heal could ever notice. Contained
(typed addresses still geocode via S7, and the 300 s cache does not store
empty-on-failure separately from empty-on-success), which is why it is LOW
rather than MEDIUM — but it is a fresh instance of the shape the second audit
called out as the system's characteristic reflex.

### N5. No host allowlist on the `url` parameter handed to Titiler

**Severity: LOW (second-order).** `api/imagery.py:336-340` allowlists
`planetarycomputer.microsoft.com` for the API's own Landsat item fetch, and
the comment at `api/imagery.py:330-335` gives the reason: without it, "a `cog_url`
written by a compromised upstream would make the API fetch an attacker-chosen
URL from inside the network."

The same stored values are also passed to Titiler as the `url` query parameter
on four paths — `_proxy_cog_tile` (`api/imagery.py:484-486`), warmup
(`api/imagery.py:646-648, 665-668`), the Landsat STAC callback URL
(`api/imagery.py:556-557`) and the preview renderer
(`preview_renderer.py:113-116`) — with **no host check on any of them**, for
NAIP, Sentinel-2 and USGS topo alike. Topo is the widest case: the URL comes
straight out of TNM's `urls.GeoTIFF` and is never inspected
(`usgs_topo.py:134-140`). Titiler then fetches it from inside the private
network.

The exposure is the same second-order shape the existing comment already
reasons about — it requires a compromised or malicious upstream, and the value
is written by our own worker — but the mitigation was applied to one of the
five paths and not the other four. `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff`
(`fly.titiler.toml:19`) narrows what GDAL will open but does not constrain the
host.

---

## Verification limits

- **No live upstream was contacted** and **no database was read** — the local
  stack is not running (`docker compose ps` returns no containers). Every
  claim here is from code at HEAD `103ddab`. Where a number comes from an
  earlier audit's measurement it is labelled and attributed rather than
  restated as fact.
- **The USGS topo GeoTIFF host is not verifiable from the repo.** The code
  asserts public S3 (`usgs_topo.py:4-5`; `timeline.py:452`) but never names,
  inspects or validates the host — it is whatever `urls.GeoTIFF` carries
  (`usgs_topo.py:134-140`). A researcher evaluating topo hosting should
  confirm it against a live TNM response.
- **Azure Blob account/container names for NAIP and Sentinel-2 are derived at
  runtime** from asset hrefs (`stac.py:345-360`); only Landsat's
  (`landsateuwest/landsat-c2`) is hardcoded (`stac.py:221`). The others cannot
  be quoted from the repo.
- **Upstream-side rate limits are not documented anywhere in the repo** for
  any source. What is recorded here is our own throttling and retry behaviour.
  The one exception is the Socrata app-token note ("1K→10K/hr",
  `config.py:63`), which is a comment, not a measurement.
- **STATUS.md's M4 topo characterisation is more pessimistic than the code**
  on one branch: a whole TNM search failure marks the task `failed`
  (`timeline.py:457-462`), not `complete`. The per-product skips
  (`timeline.py:497-505, 513-518`) and the cap (`usgs_topo.py:89-97`) do match
  the description. Noted rather than edited — M4 is an open row and rewriting
  it is out of scope for this pass.
