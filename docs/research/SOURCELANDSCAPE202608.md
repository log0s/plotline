# External Source Landscape — research pass

**Date:** 2026-08-15. **Brief:** external research on imagery & data sources for Plotline, against
`INVENTORY.md` (HEAD `103ddab`) as ground truth for how retrieval works today. Settled constraint
honored throughout: no bulk pixel ingest; every source judged as on-demand COG/tile/API access from
a small always-on backend.

**Method and trust notes.**

- All live probing was **read-only GETs against public endpoints**, per the brief. The research
  sandbox's egress proxy blocks raw `curl` to most hosts, so probes ran through a fetching tool
  that renders responses through an intermediate model. Load-bearing numbers (STAC counts, quotas,
  license quotes) came from targeted single-field extractions and the critical ones were re-fetched;
  residual extraction risk is noted where it matters.
- **UNVERIFIED** means exactly that: stated by a source I could not fetch, or inferred — not
  confirmed. Every UNVERIFIED item is also collected in §7. An absent rate-limit doc is recorded as
  a finding ("UNDOCUMENTED — checked \<urls\>"), per the brief.
- HTTP-header-level checks (HEAD, `Accept-Ranges`) were impossible from this sandbox — no probe
  below rests on one; where range-friendliness matters it is established by format documentation
  plus operational corroboration, and tagged.
- Where a promising source turned out to be the same thing underneath (mirror/rebrand/same bucket),
  it is called out inline — that failure mode has bitten this project before.

**If you do only three things:** (1) get a Planetary Computer subscription key and align signing
retries with Microsoft's own SDK (§5.1–5.2 — S, pure ops win); (2) add NYC's 1924/1951 historic
ortho tiles for the Manhattan adapter (§1 R1 — S, largest wow-per-line-of-code in this report);
(3) add Landsat MSS 1972–1984 from the PC collection you already speak (§1 R2).

---

## 0. Assigned verification gaps — closed

### 0.1 The USGS topo GeoTIFF host, named

`usgs_topo.py:4-5` asserts "public S3" but never names or checks the host. Verified live:

- A TNM products query for the 350 5th Ave bbox
  (`https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Historical Topographic Maps&bbox=-73.9867,40.7474,-73.9847,40.7494&max=3`)
  returned `total: 52`, and every item's `urls.GeoTIFF` points at
  **`https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/{state}/{name}.tif`**
  (e.g. `NY_Brooklyn_123124_1947_24000_geo.tif`). GeoPDF variants live under `.../PDF/`.
- **Access model:** genuinely public S3. An anonymous `ListObjectsV2` against
  `prd-tnm.s3.amazonaws.com` with the `HistoricalTopo/GeoTIFF/NY/` prefix succeeded (keys and sizes
  returned, ~7–9 MB per 1:62,500 sheet) — anonymous list *and* read, no auth, no requester-pays.
  USGS's own access-points page (usgs.gov/the-national-map-data-delivery/topographic-map-access-points)
  names the same bucket and describes access as free.
- **COG / range-friendliness:** the HTMC archive ("183,112 digitized maps created between 1884 and
  2006") is documented as stored **in Cloud-Optimized GeoTIFF format** on this bucket — but the
  explicit COG statement comes from a well-known third-party engineering write-up
  (github.com/kylebarron/usgs-topo-tiler), not a USGS page; USGS's page says "GeoTIFF" without the
  COG qualifier. Operationally corroborated: Plotline's own Titiler serves tiles from these URLs in
  production today (S6), which is only viable behavior for range-readable files. Byte-level
  verification (IFD layout, `Accept-Ranges`) — UNVERIFIED from this sandbox. S3 GETs support Range
  requests as a platform property.
- **Rate limits:** UNDOCUMENTED — checked usgs.gov TNM API FAQ, the GIS-data-download delivery page,
  and `tnmaccess.nationalmap.gov/api/v1/docs` (the last is a JS shell, unreadable to fetch tools).

**Consequence for the code:** the S6 assertion is true, and `sign=False` is correct. The
un-inspected host remains the N5 exposure (any URL TNM hands back is fetched by Titiler from inside
the network); now that the legitimate host is named, an allowlist for `prd-tnm.s3.amazonaws.com`
would close N5's widest case at the cost of one constant.

### 0.2 Upstream rate limits — every source, documented or established absent

The repo documents none, for any source. This table is the finding. "UNDOC." = no published numeric
limit; the absence was established against the listed pages.

| Source (INVENTORY §) | Documented limit | Evidence |
|---|---|---|
| PC STAC search (S0) | **None** — "We don't have rate limiting per-se on the STAC search endpoints, but it is a shared resource" (503/504 under load; retry-with-backoff advised) — maintainer M. McFarland, Aug 2023 | github.com/microsoft/PlanetaryComputer/discussions/246 |
| PC SAS signing (S4) | Rate limiting **exists and is official** ("This API *does* have rate limiting enabled") but the numbers live on a JS-walled docs page — UNVERIFIED numerically. Subscription key ⇒ "less restricted rate limiting" | discussion 246; planetary-computer SDK README; planetarycomputer.microsoft.com/docs/concepts/sas/ (JS shell — confirmed unreadable) |
| Azure Blob anonymous reads (S1–S3 bytes) | Account-level: 40,000 req/s per standard account primary-region default (20,000 elsewhere), ~3,000 req/s per single blob; throttle = 503/500. Anonymous readers share the *owner's* account ceiling | learn.microsoft.com/en-us/azure/storage/common/scalability-targets-standard-account |
| USGS TNM API (S6) | UNDOC. | usgs.gov API FAQ, GIS-data-download page; JS docs unreadable |
| prd-tnm S3 (S6 bytes) | UNDOC. (public S3; no policy page found) | probe + usgs.gov access-points page |
| Census Geocoder (S7) | Batch: 10,000 records/file. Single-address endpoints: **no published rate limit** | geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html (upd. 02/2026) |
| Census Data API (S8) | **The 500/day-keyless rule is gone.** Current: "An API key must be used with all data queries" + 50 variables/query; no numeric quota published | census.gov/data/developers/guidance/api-user-guide.Query_Limits.html (rev. 2026-05-14) |
| Photon (S9) | Policy, no number: "reasonable limit... Extensive usage will be throttled or completely banned"; heavy users told to self-host | github.com/komoot/photon README |
| ArcGIS Online hosted (S10, S11) | UNDOC. as a number; Esri officially acknowledges server-side 429 ("If you receive a 429 response, the request has been rate limited") | developers.arcgis.com query-features guide; doc.arcgis.com AGOL FAQ |
| DC DCGIS (S12) | UNDOC.; as-is/no-warranty terms only | dc.gov/node/939602 |
| San Jose CKAN (S13) | UNDOC. at both layers — CKAN core docs contain no rate limiting at all; result caps only (`limit` default 100, upper 32,000) | docs.ckan.org API + datastore docs; data.sanjoseca.gov |
| NYC Socrata (S14) | Token'd: "up to 1000 requests per rolling hour" still published on getting-started; app-tokens page now says token'd requests are *not* throttled "unless... abusive," keyless = shared IP pool, no number. **`config.py:63`'s "1K→10K/hr" matches no current page** | dev.socrata.com/consumers/getting-started.html; dev.socrata.com/docs/app-tokens.html |
| OpenFreeMap (S15) | Explicit no-limits: "There are no limits on the number of map views or requests." No SLA ("I don't offer SLA guarantees"), donation-funded | openfreemap.org |
| Earth Search (candidate) | UNDOC.; "This public API does not come with any guaranteed service." | github.com/Element84/earth-search README |
| CDSE (candidate) | **Fully documented, and disqualifying** — see §2 | documentation.dataspace.copernicus.eu/Quotas.html |
| OpenFEMA (candidate) | "Completely open," no key; 10,000 records/call max; no throttle number | fema.gov/about/openfema/api + FAQ |

Two record-drift items worth a STATUS.md line: the Census 500/day rule is superseded (harmless —
the client already hard-requires a key, `census.py:129-135`), and the Socrata `config.py:63` comment
cites a 10K/hr figure that no current Socrata page publishes.

---

## 1. Ranked recommendations

Ranked by portfolio value per unit of integration effort, not exhaustiveness. Sizes: S ≈ a day or
less, M ≈ a few days, L ≈ a week+. Licenses stated per source; everything here is free.

| # | Source | Adds | Size |
|---|---|---|---|
| R1 | NYC historic ortho tiles (1924, 1951, 1996, 2001–2018) | two pre-WWII years no one else has, on the flagship county | S–M |
| R2 | Landsat MSS via PC `landsat-c2-l1` (1972–1984) | +12 years of national satellite record | S–M |
| R3 | NYS statewide orthos (2000–2025 + 1994–98 CIR) | fills the Manhattan 2023-class holes; pre-2010 decade statewide | M |
| R4 | Hazard/context layers on the existing ArcGIS client (SVI, wildfire history, USA Structures) | tract time-series + dated fire events + building attributes | S each |
| R5 | FEMA NFHL flood zone + NRHP + OpenFEMA declarations | the most consequential parcel datum; historic-register flair; county disaster history | S each |
| R6 | Annual NLCD 1985–2025 land-cover timeline | "cropland until 1996" — a second, data-driven timeline | M |
| R7 | NOAA Emergency Response Imagery (2005–2026, coastal/event) | 15–50 cm post-storm + pre-event flights, sub-annual where it exists | M |
| R8 | NJ statewide ortho COGs (1930, 1970, 1977, 1995, 2002, 2007→2020) | 1930s aerials as plain public COGs — the cheapest deep-history pixels in this report | M |
| R9 | Colorado public-imagery bucket (NAIP 2005/2009 + Denver-metro DRAPP 2010–2020) | pre-2010 NAIP years and 3-inch metro orthos exactly over Denver/Adams | M (gated on one check) |

### R1. NYC historic orthophotos — maps.nyc.gov tile service

**What it adds.** Aerial layers for **1924 and 1951** — six decades earlier than any current imagery
source — plus 1996 (1 ft) and the 6-inch biennial series 2001-2→2018, over the county where
Plotline already has its richest adapter (S14).
**Access (verified).** Plain XYZ: `https://maps{1-4}.nyc.gov/xyz/1.0.0/photo/{year}/{z}/{x}/{y}.png8`,
layers `1924, 1951, 1996, 2001-2, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018`; WMTS
capabilities at `maps.nyc.gov/wmts/1.0.0/?REQUEST=getcapabilities` (EPSG:900913). A 1924 z15 tile
over the ESB point returned image bytes. Nothing newer than 2018 is on this service; NYC's 2020/2022/2024
orthos exist (city metadata repo) but their tile endpoints went unverified — for post-2022 NYC, R3
is the verified path.
**License.** "© City of New York, licensed for reuse under the Creative Commons Attribution (CC BY
4.0) license" (maps.nyc.gov/tiles/; corroborated by CityOfNewYork/nyc-geo-metadata). Attribution
line required in the UI.
**Rate limits.** UNDOC. — checked maps.nyc.gov/tiles/.
**Integration sketch.** This is the **S15 pattern, not the S1 pattern**: a browser-direct raster
source, no Titiler, no signing, no bytes through the backend. Two tiers: (S) register per-year XYZ
templates as timeline entries for NYC parcels — a new snapshot kind carrying a tile-URL template
instead of a `cog_url`, rendered by `applyImageryLayer.ts` as a raster source the way the basemap
style already is; the listing path treats it like `_NO_SIGN_SOURCES` (`api/imagery.py:205`), and no
`additional_cog_urls` mosaic logic applies (S1 quirks are moot — the service is pre-mosaicked).
(M) if you want parity with other sources' preview thumbnails and warmup, synthesize a static-tile
preview URL instead of S5's `rendered_preview`. Discovery is trivial: the year list is fixed;
coverage test = point-in-NYC, which the S14 adapter's borough logic already answers.

### R2. Landsat MSS — PC collection `landsat-c2-l1` (1972–1984)

**What it adds.** Extends the satellite timeline from 1984 back to July 1972, nationwide. 60 m
(resampled) MSS, 4 bands, no blue — renders as false color or simulated natural color, which is an
honest presentation choice for the era.
**Access (verified).** Same platform Plotline already runs: PC STAC collection `landsat-c2-l1`
(fetched: Landsat 1–5 MSS, 1972-07-25 → 2013-01-07, COG assets, public-domain license), same SAS
signing plane (S0/S4), same Azure hosting. No new hosts, no new auth, no Titiler config change.
**License.** Public domain (USGS).
**Rate limits.** The PC regime you already run (§0.2).
**Integration sketch.** A fourth entry in `timeline.py`'s source configs next to `landsat-c2-l2`
(`timeline.py:67-73`), searched year-chunked 1972–1984 exactly like S2 §4. The S2 quirks list
carries over almost intact — separate band COGs through the `/stac` callback
(`api/imagery.py:538-564`), validation walk (`stac.py:1056-1128`), missing-cloud-cover=100
(`stac.py:720-723`) — but **the render params do not**: L1 DNs are not surface reflectance, so
`nodata=0, rescale=7000,14000` (`api/imagery.py:558-562`) is wrong here; band keys differ
(green/red/NIR — verify exact asset keys against a live item at build time) and rescale must be
re-derived. That, plus a UI note for the false-color era, is the whole job. UNVERIFIED here: exact
MSS asset key names and DN range — one item fetch settles both.
**Same-thing-underneath note:** this is the same USGS Collection 2 archive as S2, one level up —
which is exactly why it's cheap.

### R3. New York State statewide orthos — orthos.its.ny.gov

**What it adds.** Statewide leaf-off orthos ~2000–2025 on a 4–5-year county rotation (NYC boroughs
in even years), **plus a `napp` service: 1994–1998 statewide 1 m color-IR** — pre-NAIP years for
every NY address. Also the verified answer to "Manhattan after 2022": the NYS `2024` service
carries Spring 2024 12-inch imagery with a fused Web Mercator tile cache.
**Access (verified).** ArcGIS Server REST at `https://orthos.its.ny.gov/arcgis/rest/services/wms/`
— 52 MapServers (`2000`…`2025`, `_cir` variants, `Latest`, `NAIP_2019`, `napp`). The `2024` and
`napp` services expose a **fused 256 px tile cache to ~z19** → XYZ-style
`…/wms/2024/MapServer/tile/{z}/{y}/{x}`, plus WMS on every service, plus exportImage (max
4096×4096). Anonymous.
**License.** No named license; "as is," attribution line "NYS ITS Geospatial Services" (service
iteminfo). **Rate limits.** UNDOC. — checked gis.ny.gov/orthoimagery + service JSON.
**Integration sketch.** Same S15-shaped browser-direct raster integration as R1 (tile cache), with
one addition: per-year coverage varies by county (rotation), so the adapter needs a
"was this county flown in year Y" gate — resolvable from the program page's schedule or by probing
the year service with an exportImage/identify at the parcel point at fetch time (one GET; treat
empty as not-covered, which matches the S1 point-coverage philosophy at `stac.py:623-648`). Watch
the same-thing-underneath trap: `NAIP_2019`/`napp` re-serve USDA/USGS federal imagery — dedupe
against PC NAIP by year+provenance so 2019 doesn't appear twice.

### R4. Hazard/context layers that reuse `arcgis.py` as-is

All three verified end-to-end with anonymous point queries; all are `GET {layer}/query&f=json` —
the existing client (`arcgis.py:48-56`) plus three geometry params
(`geometry={lon},{lat}&geometryType=esriGeometryPoint&inSR=4326`).

- **CDC/ATSDR SVI, tract-level 2000–2022** (probed: one query returned all 7 release years for a
  Denver tract; `onemap.cdc.gov/onemapservices/rest/services/SVI/SVI_consolidated_data/FeatureServer/0/query`).
  Matches the vintage-aware tract model (S7/S8 quirks); can even query by the tract FIPS the
  pipeline already resolves. Handle the documented −999 sentinels like S8's annotation values
  (`census.py:328-344` analog). **S.**
- **NIFC interagency fire-perimeter history** (probed: Camp Fire returned at Paradise, 34 fires
  named CAMP, `FIRE_YEAR` 1971–2018; `services3.arcgis.com/T4QMspbfLg3qTGWY/.../InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query`).
  Dated events for the timeline; dedupe on `IRWINID`/year (probe saw "Camp"+"CAMP" duplicates).
  Emits through the same `SourceFetchResult` rollup as S10–S14 (`timeline.py:829-842`). **S.**
- **FEMA/ORNL USA Structures** (probed: occupancy class, sq ft, height, `PROP_ADDR` at a Denver
  point; `services2.arcgis.com/FiaPA4ga0iQKduv3/.../USA_Structures_View/FeatureServer/0/query`).
  Parcel-card enrichment, and `PROP_ADDR` is a free cross-check for the address matcher
  (`address_normalizer.py`, second-audit H5). `OCC_CLS` is often "Unclassified" — display honestly.
  **S.**

Licenses: federal public data; verbatim license text pages were unfetchable — UNVERIFIED as quotes,
standard federal-work status. Rate limits: all UNDOC.; note the Esri 429 acknowledgment in §0.2 —
give the shared client a 429 branch before adding traffic (§5.6).

### R5. FEMA NFHL flood zones + NPS NRHP + OpenFEMA declarations

- **NFHL** — flood zone at the parcel coordinate (`FLD_ZONE`, `SFHA_TF`, BFE):
  `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query`. The endpoint and
  FEMA_MAC ownership were confirmed via the ArcGIS item registry, but hazards.fema.gov blocks this
  sandbox's fetcher — **anonymous point query UNVERIFIED; one curl from your machine settles it**:
  `curl 'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query?geometry=-95.3698,29.7604&geometryType=esriGeometryPoint&inSR=4326&outFields=FLD_ZONE,SFHA_TF&returnGeometry=false&f=json'`.
  Two design cautions: unmapped counties must render as "no digital FIRM," not "Zone X" (the
  complete-with-zero rule), and layer ids have historically shifted — resolve id by layer name at
  startup rather than hardcoding 28 (the DC year-layer chore shape, L12). **S** once verified.
- **NRHP** (probed: White House point+150 m buffer returned L'Enfant Plan;
  `mapservices.nps.gov/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer/{0,1}/query`).
  Listing dates make real timeline events. Sensitive properties are excluded by design. **S.**
- **OpenFEMA disaster declarations, county-level 1953+** (probed: Marshall Fire declaration
  returned; `GET fema.gov/api/open/v2/DisasterDeclarationsSummaries?$filter=...`). The one API in
  this report with documented openness: "does not require a key. It is completely open," 10,000
  records/call max. New ~socrata-shaped client (`$filter/$top/$skip`), county FIPS already in hand
  from S7. Label events county-scoped in the UI. **S.**

### R6. Annual NLCD 1985–2025 — the land-cover timeline

**What it adds.** Per-year 30 m land-cover class at the parcel for 41 years — a second timeline
that narrates change ("cropland → low-intensity developed, 1997") even where imagery is sparse.
Collection 1.2 (June 2026) spans **1985–2025** (mrlc.gov/data/project/annual-nlcd, fetched).
**Access — two candidate hosted mechanisms, final pick needs ~10 min on your machine (sandbox-blocked):**
(a) **WMS GetFeatureInfo** at `dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms`
(official services page; capabilities confirmed GetFeatureInfo with `application/json`) — layer
names / time-dimension semantics UNVERIFIED (capabilities fetch came back garbled here);
(b) **public COG + your own Titiler `/cog/point`** — FGDC metadata confirms distribution as Cloud
Optimized GeoTIFF with use constraints "None," but the *cloud* copy USGS documents is
requester-pays (`s3://usgs-landcover` — rejected), and whether MRLC's own download links resolve to
a public bucket suitable for direct range reads is UNVERIFIED (their download UI is JS-rendered).
**License.** Public domain / "None" constraints (FGDC metadata, fetched).
**Rate limits.** UNDOC. — checked mrlc.gov services + project pages.
**Integration sketch.** Not an imagery snapshot — a demographics-shaped panel (S8 analog): one
fetch per parcel writing per-year class rows, rendered like the census series. Mechanism (a) is a
~50-line WMS client (GET, JSON) with the S8 politeness pause; mechanism (b) reuses T's
`/cog/point` with `sign=False` (S6 shape) if a public `.tif` URL exists. The change-count/first-change
products can compress 41 calls to 2–3. **M**, gated on the mechanism check.

### R7. NOAA Emergency Response Imagery — public S3 COGs

**What it adds.** 15–50 cm aircraft orthos flown within days of hurricanes/tornadoes/floods,
2005 (Katrina) → 2026, **plus Pre_Event baseline collections (2022–2026)** — sub-annual,
dated, dramatic layers for coastal/storm-path parcels. Coverage is event-footprint-only by nature:
a "when present, show it" source.
**Access (verified).** Public bucket `noaa-eri-pds` (registry.opendata.aws/noaa-eri: "no AWS
credentials required"; COG for recent events). Anonymous prefix list works; sample Milton keys are
20–400 MB `.tif` COGs whose filenames encode the DMS lon/lat of each quarter-minute tile
(`20241011aC0822530w271245n.tif`). Older events (e.g. Harvey 2017) are JPEG+worldfile — the
COG-era cutoff (~2020) must be handled per event; exact cutoff UNVERIFIED.
**License.** NOAA NODD open data, "can be used as desired," attribution requested (registry page).
**Rate limits.** UNDOC. beyond being public S3.
**Integration sketch.** **S6 minus TNM**: unsigned public `.tif` through the existing `/cog` tile
path (`_NO_SIGN_SOURCES` + `sign=False`, `api/imagery.py:205,601`);
`CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff` already admits the bytes. The new code is discovery:
event → prefix → tile-key parse (or the per-event tileindex/VRT manifests), then point-in-tile from
the filename grid. Grouping is neither year (S1) nor quarter (S3) — event-dated snapshots need
their own reconciliation bucket, the same way topo uses decades (`services/imagery.py:573-577`).
**M.**

### R8. New Jersey statewide ortho COGs — `njogis-imagery` bucket

**What it adds.** For NJ addresses: **1930s statewide aerials**, 1970, 1977, 1995, 2002, then
1-ft leaf-off 2007→2020 — the deepest cheap history in this report. (No NJ county adapter exists
yet, but imagery is address-agnostic — any NJ address benefits.)
**Access (verified).** Anonymous S3, us-west-2 (registry.opendata.aws/nj-imagery): year prefixes
`1930/…2020/`; verified keys like
`https://njogis-imagery.s3.us-west-2.amazonaws.com/2020/cog/A15B12.tif` (~250 MB COGs). Live WMS
also verified (`img.nj.gov/imagerywms/Natural2020`, AccessConstraints "none").
**License.** Open data "as is"; **1930s caveat:** NJDEP metadata requests acknowledgement and says
redistribution requires written permission — serving tiles from their bucket is not
redistribution, but put the attribution line in. UNVERIFIED beyond the metadata page.
**Rate limits.** UNDOC. — checked registry + WMS caps.
**Integration sketch.** The S6 shape again — unsigned public COGs through Titiler — with the
discovery difference: no search API. Point→key needs the tile-grid index (the `A##B##` naming
scheme; a one-time index shapefile/lookup per year — **metadata, not pixel ingest**, so it honors
the settled constraint, but note it plainly: this is the one recommendation that needs a static
lookup table shipped with the code). WMS is the zero-index fallback (browser-direct, S15 shape).
**M.**

### R9. Colorado — `colorado-public-imagery` bucket (Denver/Adams synergy)

**What it adds.** Registry-verified holdings: **NAIP GeoTIFFs 2005 and 2009** — pre-2010 years PC
does not have — plus 2009–2021, and **DRAPP Denver-metro 3/6/12-inch orthos 2010–2020**, directly
over the two Colorado counties Plotline already serves. CC0, anonymous, us-west-2
(registry.opendata.aws/colorado-imagery, fetched).
**The gate:** bucket layout and COG-organization are UNVERIFIED (not listed in this pass). One
anonymous `ListObjectsV2` from your machine tells you whether it's the NJ pattern (drop into
Titiler) or plain untiled GeoTIFFs (viable via vsicurl but slower).
**Integration sketch.** If COG: identical to R8 including the point→key index caveat. **M.**

---

## 2. Re-opened decision: Sentinel-2 hosting

Candidates evaluated from scratch: stay on **Planetary Computer** (incumbent, S3+S0/S4), migrate to
**Earth Search / Element 84** (prior decision), or **Copernicus Data Space Ecosystem**.

### The probe matrix (350 5th Ave bbox, `numberMatched` unless noted)

| Year | PC `sentinel-2-l2a` | ES `sentinel-2-l2a` (legacy) | ES `sentinel-2-c1-l2a` |
|---|---|---|---|
| 2015 Jun–Dec | 20 (feature count) | — (2016 is 0) | 0 |
| 2016 | 67 (feature count) | **0** | **0** |
| 2017 | not probed | 75 | — |
| 2018 | not probed | 152 | 52 (starts 2018-11-29) |
| 2019 | not probed | 258 | 42 in H1 (thin) |
| 2020 | not probed | 290 | 145 |
| 2022 | not probed | 146 | **13** |
| 2023 | ≥187 (87 Jan–Apr + 100 Jul–Dec, page-capped) | 130 | 146 |
| 2026-08-01→15 | 7 (newest 08-14 present ≤1 day later) | — | 7 (newest 08-14, `created` +5.9 h) |

ES `sentinel-2-pre-c1-l2a`: 0 for both 2016 and 2020 — empty over this bbox; ignore it.
(Legacy-collection counts are inflated ~2× in 2019–2020 by duplicate processing versions — the
qualitative reading below is what matters. PC's GET pagination silently capped a `limit=400`
request at 100 with no `next` link under the `fields` extension — worth knowing if you ever count
PC results this way.)

### What the matrix and the documents say

- **ES cannot serve 2015–2016 at all.** Zero items in every ES collection over the probe bbox for
  2016 (and c1 for 2015). PC has 2015-08 onward (20 + 67 items, Microsoft-processed backfill —
  processing timestamps in the ids are 2021). Losing 2015–2016 contradicts the product surface
  (`timeline.py:80`: 2015→current) and S3's quarter-grouped timeline.
- **ES's go-forward collection is still a construction site.** Element 84's own README: c1 is
  "intended to eventually replace the other Sentinel-2 L2A collection"; as of its Apr-2024 note the
  ESA baseline-5.0 reprocessing gaps were "Nov 2016 to Nov 2019 and 2022," completion timing
  "unknown." My probes confirm partial progress (2018 now starts Nov-29, 2019 H1 thin at 42) and
  confirm **2022 is still a 13-item hole vs 146 in the legacy collection**. Meanwhile the legacy
  collection is tapering (130 vs c1's 146 in 2023) and its eventual deletion has been publicly
  floated (Element84/earth-search issue #45 — closed with no visible maintainer answer in the
  fetched thread). Serving 2015→present from ES today means stitching
  two collections with different id schemes and duplicate semantics, plus an era ES simply lacks.
- **Where ES is genuinely better:** the c1 `visual` asset is a plain public COG
  (`https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/.../TCI.tif`, verified href;
  registry: free, anonymous, no requester-pays) — **the SAS plane (S0/S4) and its 429 regime
  dissolve entirely** for anything served from it; the whole `_NO_SIGN_SOURCES`/`sign=False` path
  (S6's shape) applies. stac-server gives `numberMatched` + `sortby` (verified root conformance) —
  better truncation instrumentation than PC's POST responses. Observed ingest latency ~6 h
  (`created` field). No SLA and no documented limits ("does not come with any guaranteed service").
- **CDSE is disqualified on three independent counts** (each alone sufficient): (1) bytes require
  account + generated S3 keys (secret shown once) or a **10-minute** access token — a worse
  credential dance than SAS against every S0 replacement quirk (the credential-expiry-derived cache
  keys at `stac.py:466-515` would rebuild around a 10-min token); (2) **documented quotas that a
  tile server cannot live inside**: 50,000 requests/month "direct HTTP/COG access," S3 at 2,000
  req/min with **4 concurrent connections** and 20 MB/s (documentation.dataspace.copernicus.eu/Quotas.html)
  — Titiler's per-tile range reads through a 4-connection ceiling is a non-starter; (3) Sentinel-2
  bytes are SAFE/JP2 (their COG program covers other product lines "in the upcoming months"), and
  Titiler's `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff` (fly.titiler.toml:19) doesn't even open
  `.jp2` before you get to JP2 decode cost. Its anonymous STAC search (new v1 endpoint, verified)
  is fine — and irrelevant without readable bytes.

### Recommendation

**Stay on Planetary Computer as the serving path.** The prior Earth Search decision does not
survive re-evaluation *as a wholesale migration*: the zero-signing benefit is real but currently
only covers ~2019+ (with a 2022 hole in c1 and a deprecating legacy collection covering it), and
2015–2016 exist on ES nowhere. Re-opened did not mean the prior answer was wrong — it was right
about the signing win and understated the catalog cost.

What to do with Earth Search instead: treat it as the **S2 failover/second-host option** (M). The
dependency table's sharpest row is that a PC STAC outage takes all three imagery sources at once;
ES c1 is a genuine degraded-mode S2 catalog+bytes for recent years with zero new auth code — the
integration is the already-existing unsigned path plus a collection/id mapping. Optional, not
urgent.

**What would reverse this** (each checkable in minutes):
1. ES c1 backfill completes: `numberMatched > 0` for 2016 and ~146 for 2022 on the probe bbox —
   at that point c1 alone spans 2015→present with no signing, and migration becomes a
   straightforward win worth re-scoping.
2. A PC access regression: SAS instability recurring at O1 scale, an announced policy change to
   anonymous access, or the naip/landsat-style collection-boundary problems appearing in
   `sentinel-2-l2a`.
3. Evidence that PC's ingest latency materially lags ES's ~6 h for fresh scenes (not observed:
   both had the 08-14 scene by 08-15).

---

## 3. Re-opened decision: NAIP hosting

Candidates: stay on **PC `naip`** (incumbent, S1), **USDA's own distribution**, **AWS NAIP
holdings**, plus the discovered **Earth Search `naip`** catalog.

### What actually exists, verified

- **PC `naip`:** temporal extent 2010-01-01 → **2023-12-31** (collection JSON). The 2010 floor is
  PC's collection boundary, restated. The 6-item 403 episode from the last audit is a recorded
  incident, not reproducible read-only from here — treated as an availability data point, not a
  disqualifier.
- **AWS NAIP buckets (`naip-analytic`, `naip-visualization`, `naip-source`):**
  **requester-pays, 2010–2023** (registry.opendata.aws/naip, fetched). Requester-pays means AWS
  credentials + SigV4 + per-GB egress billed to you on the hottest path (tiles). Fails "free"
  outright. Adds no years over PC.
- **Earth Search `naip`:** exists (v1 collections list), extent **2010→2022-12-31** — one season
  *behind* PC — and its item assets point at `s3://naip-analytic/...` with
  `storage:requester_pays: true` (verified item). Same thing underneath: a free catalog over
  metered bytes. Rejected.
- **USDA's own channels:** no on-demand per-quad path anywhere — Geospatial Data Gateway serves
  county-mosaic ZIPs (bulk-shaped), the NRCS Box front is a JS app (contents unverifiable here),
  and EarthExplorer's per-quad GeoTIFF/JP2 downloads (2003→present) sit behind ERS login with an
  HTML download flow. The USGS `USGSNAIPPlus` ImageServer *is* anonymous and its `exportImage`
  works (probed) — but its default mosaic over the ESB point serves **2019** quads (probed via
  `identify`), i.e. staler than PC's 2022, and per-year addressability went unverified.
- **The 2023 gap at 350 5th Ave is real data absence, and now explained:** NY was not flown in the
  NAIP 2023 season. PC's collection is complete through 2023 (extent end 2023-12-31; a 2023 search
  over an upstate-NY bbox returns only MA/CT/VT edge quads — states that flew); NAIP 2023–24 is a
  two-year cycle mirroring 2021–22, and NY flew in 2021+2022 (PC items; NOAA InPort flight records)
  → NY's next season is 2024. Newest NAIP that verifiably exists anywhere over Manhattan:
  **2022-07-19**. No primary record of published NY-2024 quads found yet in PC, AWS, USGS, or NOAA
  channels (UNVERIFIED whether it's on Box/EarthExplorer). The fill for Manhattan-after-2022 is
  therefore not NAIP at all — it's R1/R3.

### Pre-2010 sub-question

No alternative host extends NAIP's years on-demand. Pre-2010 NAIP (2003–2009) exists at
EarthExplorer (ERS login, per-quad `.tgz`/JP2, no COG, no anonymous path) and in Google Earth
Engine (2002+, API-only, mechanism incompatible with Titiler) — both fail the constraint. What
*does* exist on-demand is regional: state buckets carry pre-2010 federal imagery re-hosted (CO
NAIP 2005/2009 — R9; NYS `napp` 1994–98 — R3; NJ 1995/2002 — R8). The 1990s–2009 1 m national
story (DOQ + HRO + early NAIP) all funnels through the same EROS/EarthExplorer/M2M door: free,
scanned, per-item — but login + manual M2M access approval + `.tgz` + not-COG means each viewed
parcel implies fetch→convert→cache. That is bounded per-parcel work, not bulk ingest, but it is
the most integration-heavy idea in this report (**L**) and its API docs are themselves
login-walled (rate limits publicly UNKNOWN). Park it until a dedicated feature justifies it;
don't let it block the state-bucket wins.

### Recommendation

**Stay on PC for NAIP.** It remains the only free, anonymous, per-quad COG catalog of NAIP in
existence — every alternative is the same USDA pixels behind a meter (AWS, ES), a login
(EarthExplorer), or a bulk shape (GDG); and the S1 quirks bar (3-tile greedy mosaic scoring,
point-coverage suppression, `additional_cog_urls` stacking — `stac.py:730-863, 623-648`) would
have to be rebuilt against a *worse* access model in every case. Fill coverage holes with R1/R3
(and R8/R9 for their states) rather than switching hosts.

**What would reverse this:**
1. A free, anonymous, per-quad NAIP COG bucket appearing (watch the AWS registry entry flipping
   off requester-pays, or USDA publishing a public bucket — either is a one-probe check).
2. PC's collection stalling: no 2024 season by the time USDA/state channels clearly have it
   (checkable with the same edge-quad search used above).
3. Recurrence of the 403 episode at scale — availability, not catalog, is PC-NAIP's only observed
   weakness.

---

## 4. Landsat: alternatives evaluated (Q4)

Verdict up front: **no alternative Landsat host survives contact; stay on PC.** The actionable
Landsat move is R2 (MSS, same host). Findings, each primary-sourced:

- **USGS LandsatLook STAC** (`landsatlook.usgs.gov/stac-server`): anonymous search, same asset key
  names Plotline uses, `numberMatched` support, catalog from 1982. **Catalog parity with PC
  verified 1:1** on the probe bbox (1985: 35/35, 2000: 82/82, 2020: 95/95; scene ids correspond).
  But the bytes are unreachable: every https `/data/` asset href — COG, MTL, even thumbnails —
  **302-redirects to `ers.cr.usgs.gov/login`** (probed), and the s3 alternates are requester-pays.
  There is no machine-auth contract GDAL/vsicurl could satisfy. Reject as byte host; no reason to
  adopt as search-only given verified parity.
  **Integration trap worth recording:** Plotline's validation HEAD treats status ≥400 as broken
  (`stac.py:1019-1036`) with `follow_redirects=True` — a login-redirecting host like this would
  *pass* validation (302→200 HTML) and then fail at Titiler. If a host swap ever happens, add a
  content-type check to `_validate_asset`.
- **USGS M2M / EarthExplorer:** whole-file order/download model, ERS login + manual access
  approval ("24–48 business hours"), API docs themselves behind the login. Fails the settled
  constraint by design.
- **AWS `usgs-landsat`:** requester-pays confirmed (registry + anonymous GET → 403). Same archive,
  metered.
- **NASA HLS (HLSL30/HLSS30 v2.0):** starts 2013/2015 — cannot replace 1984–2012, which is the
  reason Landsat is in the product. For 2015+ it is redundant against 10 m Sentinel-2, and its
  bytes require Earthdata bearer tokens (60-day lifetime, max 2 concurrent) that would have to be
  injected into shared-Titiler GDAL headers — leaking to other hosts absent per-source header
  plumbing. PC's own `hls2-*` mirrors start 2020. Reject on all framings.
- **Earth Search `landsat-c2-l2`:** item assets are `s3://usgs-landsat/...` with
  `storage:requester_pays: true` (verified item) — a free catalog over the same metered bucket.
  Reject.
- **Same-thing-underneath, stated once:** PC's `landsat-c2-l2` is a Microsoft-hosted Azure copy of
  USGS Collection 2 Level-2 (collection providers: NASA/USGS producer+licensor, Microsoft host).
  LandsatLook https, `usgs-landsat` S3, M2M, and ES-landsat are four doors onto one archive; PC's
  Azure mirror is the only free anonymous door with range-readable bytes.

---

## 5. Retrieval-pattern findings (Q7 + the rate-limit gap)

Each item names the code it touches; none is speculative.

1. **The PC subscription key is a documented, free, unused lever.** Microsoft's SDK README states
   a key is not required for the service but having one "allows for less restricted rate
   limiting"; the maintainer guidance on the rate-limit thread is to register for an API key. The
   SDK sends it as an **`Ocp-Apim-Subscription-Key` header on the same token endpoint Plotline
   already calls** (`planetary_computer/sas.py`, read from source: header on
   `GET {sas_url}/{account}/{container}`). Integration: one optional setting + one header in
   `_sas_get` (`stac.py:282-342`). Directly de-rates the O1/G4/N1 429 regime. **S.** UNVERIFIED:
   the numeric before/after limits (JS-walled docs page) and the 2026 key-signup flow (the APIM
   portal `planetarycomputer.developer.azure-api.net` exists; walk it interactively when you sign
   up — no signups were made in this pass).
2. **Microsoft's own SDK retries signing on `[429, 500, 502, 503, 504]` — ten attempts,
   exponential backoff** (`urllib3 Retry` in `sas.py`, read from source). Plotline's `_sas_get`
   retries **only 429** and treats any 5xx/network error as terminal (INVENTORY N1). The vendor's
   reference client is documentary evidence for N1's fix: align the retry set (keep the existing
   budget split; this is a condition change, not a rearchitecture).
3. **PC STAC search has no rate limit but is explicitly a "shared resource" with 503/504 under
   load and retry-with-backoff advised** (discussion 246). The search path already retries
   {429,5xx} (`timeline.py:97-135`) — compliant. What the guidance implies and the code lacks is
   **any search-result caching**: ~43 Landsat + ~12 S2 year-chunks + 1 NAIP search per parcel per
   run, every run, cache-nothing (INVENTORY caching ledger). A Redis cache of search responses
   keyed on (collection, bbox-hash, year) with even a 24 h TTL would cut re-run traffic to near
   zero. **S/M.**
4. **`sortby` exists on PC** — the root document advertises `item-search#sort` (verified), so the
   unspecified-ordering problem behind the no-`sortby` note (`timeline.py:228-233`) and the T4/T5
   truncation anxiety is self-imposed. The year-chunk design is still reasonable (bounded
   result sets), but the L1 pagination blindness could alternatively be retired with one sorted,
   paginated search per collection. Note before relying on it: PC's GET+`fields` path silently
   page-capped at 100 with no `next` link in my probes — use POST for sorted pagination.
5. **Photon's published posture makes the current usage a policy risk, not just a robustness one:**
   "Extensive usage will be throttled or completely banned," heavy users told to self-host (komoot
   README). Plotline fronts Photon with its own 60/min/IP inbound limit but has no 429 branch and
   no outbound pacing (`api/geocode.py:63-82`), and L8's debounce self-DoS multiplies exactly the
   traffic komoot says gets you banned. Cheap insurance: honor 429/`Retry-After` distinctly from
   "no suggestions" (N4), fix L8.
6. **Esri acknowledges 429 rate limiting on hosted feature services with no published number**
   (§0.2). `arcgis.py` has no 429 branch — a 429 today reads as a generic `ArcGISError` and, under
   the S10–S14 rollup, can mark a property task failed or silently thin results. One added branch
   (retry-after-sleep within the existing 30 s budget) covers Denver/Adams — and R4/R5 add more
   traffic to the same client. **S.**
7. **Azure Blob throttling is per-account, shared with every other anonymous PC reader**
   (40k req/s account default; 503/500 on overload — Microsoft docs). Ambient 503s from
   `*.blob.core.windows.net` are therefore expected background behavior, which is another argument
   for §5.2's retry alignment on the signing/validation path and for GDAL's existing
   `GDAL_HTTP_MAX_RETRY=3` staying put on the byte path.
8. **Census keying rule changed upstream** (§0.2): key now required for *all* Data API queries —
   the client's hard requirement (`census.py:129-135`) went from stricter-than-upstream to
   exactly-right. No code change; a STATUS.md line and N2's no-retry fix remain the actionable
   parts.
9. **TNM asks nothing of us that we violate** — no documented limits, no pagination guidance
   beyond `max`/`offset` params. The accepted cap-warning instrument (T3/L6) stands; nothing in
   TNM's docs contradicts the un-paginated single GET. The only TNM-side news is §0.1's named host.

---

## 6. Investigated and rejected

One line each; rejections are findings.

- **CDSE for Sentinel-2** — 4 concurrent S3 connections / 50k direct-access requests/month
  (documented), 10-min tokens, JP2 bytes: three independent disqualifiers (§2).
- **Earth Search as wholesale S2 migration** — no 2015–2016 anywhere, c1's 2022 hole, two-collection
  stitch with a deprecating half (§2); keep as failover candidate.
- **Earth Search `naip` / `landsat-c2-l2`** — free catalogs over `storage:requester_pays: true`
  buckets (verified items); same pixels, now metered.
- **AWS `naip-*`, `usgs-landsat`, `usgs-landcover` buckets** — requester-pays (registry-verified);
  "free" fails at the first tile.
- **USGS LandsatLook as byte host** — every https asset href 302s to ERS login (probed); no
  machine-auth contract.
- **USGS M2M/EarthExplorer as a runtime dependency** — login + human-approved access + whole-file
  downloads + login-walled docs; the DOQ/HRO/pre-2010-NAIP archive behind it is real and is the
  only 1990s–2009 1 m door — parked as an L-sized future feature, not a source swap (§3).
- **NASA HLS** — starts 2013; token-injection into shared Titiler leaks credentials across hosts;
  redundant vs S2 for the years it covers (§4).
- **Esri World Imagery Wayback** — access trivial (public WMTS since 2014), license fatal:
  imagery is "licensed under the Esri Master License Agreement," export "intended for use only
  within ArcGIS" (item licenseInfo + Esri blog, fetched). Serving it in MapLibre is outside the
  grant. Full MLA text UNVERIFIED; nothing fetched contradicts the restrictive reading.
- **Corona/declass** — free scans exist but frames are unrectified film needing per-frame warping;
  unscanned frames are $30 orders. Fails as a map layer twice.
- **EROS Aerial Single Frames / NAPP / NHAP as map layers** — free downloads for scanned frames,
  but USGS states plainly they "have not been geocorrected" — a photos-beside-the-map product
  surface someday, not a Titiler layer.
- **USGS DOQ (1987–2006) / HRO (2000–2016)** — the archive that would fill the 1990s hole;
  EarthExplorer-only (TNM products queries for NAIP and HRO return `total: 0` — probed), so it
  inherits the M2M rejection above.
- **US Topo (2009+) via TNM** — Geospatial PDF only on the same prd-tnm bucket (probed sample);
  not a Titiler-readable format.
- **TNM as a source of more imagery generally** — the datasets enumeration (probed) shows nothing
  else with per-item GeoTIFF URLs; TNM is exhausted beyond the topos.
- **Google Earth Engine NAIP (2002+)** — Earth Engine API only, registration + non-commercial
  framing; mechanism incompatible with COG/Titiler.
- **USDA GDG county mosaics / NRCS Box** — bulk-shaped ZIPs; Box is a JS app (UNVERIFIED contents).
- **Esri-run `naip.imagery1.arcgis.com` ImageServer** — anonymous root metadata but export/identify
  behavior unverified after repeated fetch failures; re-probe before ever depending on it.
- **OpenAerialMap** — perfect mechanism (public COGs + per-item TMS, CC-BY), near-zero US
  coverage: the Manhattan probe returned one resampled Sentinel-2 scene. Not worth a card slot.
- **Maxar Open Data** — event-activated only, and the observed attribution string is CC-BY-**NC**.
- **Microsoft Global ML footprints / Overture buildings** — file dumps, or PMTiles that Overture
  itself labels not production-ready, ODbL share-alike, plus a new client; USA Structures (R4)
  delivers the value on the existing client.
- **EPA efservice as a geo query** — keyless and live, but coordinate-range chaining times out
  server-side (probed); the documented point-radius service (`get_facilities`) is the right door
  if ever wanted (host robots-blocked here — UNVERIFIED live).
- **historicaerials.com** — commercial/watermarked; no API license.
- **NYS/NC/etc. county-mosaic ZIP downloads** — right pixels, bulk shape; their tile/WMS services
  (R3 pattern) are the compliant door.

---

## 7. Consolidated UNVERIFIED register

Anything below was *not* confirmed by a fetch in this pass. Do not treat as fact without the
listed check.

| Claim | Status / one-line check |
|---|---|
| HTMC GeoTIFFs are COG at byte level | secondary source + production corroboration; `curl -r 0-1023` one file and read the IFD |
| PC SAS numeric rate limits (keyless vs keyed) | docs page is a JS shell; read in a browser |
| PC key signup flow in 2026 | APIM portal exists; walk it when signing up |
| NAIP 2024 New York existence in any channel | cycle-inferred; re-probe PC/AWS/registry quarterly |
| NFHL anonymous point query | endpoint + owner verified via registry; one curl (§1 R5) |
| Annual NLCD WMS layer semantics; public COG URL | 10-min local check (§1 R6) |
| CO `colorado-public-imagery` layout/COG-ness | one anonymous ListObjectsV2 |
| NOAA ERI COG-era cutoff year | registry says "recent events"; list one 2019–2021 event |
| NYC 2020/2022/2024 ortho tile endpoints | named in city metadata; fetch the WMTS caps they link |
| NYS `wms/2024` cache rendering NYC pixels | holdings confirmed via download listing; load one tile |
| MSS asset keys and DN rescale for `landsat-c2-l1` | one item fetch |
| NJ 1930s redistribution-permission scope | NJDEP metadata language; read the full metadata record |
| WFIGS / USA Structures / NFHL license verbatim | federal-work status assumed; terms pages unfetchable |
| M2M quotas, token mechanics | docs behind ERS login |
| HLS unauthenticated byte behavior; int16 scale/fill | robots-blocked; moot given rejection |
| Esri full Master License Agreement text | rejection rests on item licenseInfo + Esri blog |
| ES `sentinel-2-l2a` 2015 count (assumed ~0 from 2016=0) | one numberMatched probe |
| Legacy-vs-c1 duplicate semantics (2× counts) | inferred from id suffixes; compare one day's items |

**Probe environment disclosure:** raw `curl`/HEAD/Range was blocked by the sandbox egress proxy
for nearly all hosts; every live probe above went through a rendering fetch tool (GET only). All
STAC counts came from `numberMatched` where the server provides it (Earth Search, LandsatLook) or
exact feature-array counts under the `fields` extension (PC), with the PC page-cap caveat noted in
§2. Landsat parity numbers (35/82/95) and several §1 endpoint verifications were produced by
delegated research agents in this session; their probe logs (URL + status per claim) are retained
in the session transcript.
