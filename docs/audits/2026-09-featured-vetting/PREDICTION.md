# Featured-locations vetting — PREDICTION

Written **2026-09-11**, before any parcel was created or re-queued. Committed
first, scored in `VETTING.md`, and **never edited afterwards** — deviations are
recorded next to the prediction there, not folded into it.

Local stack only: `docker compose` at HEAD `332b5e6`, database at Alembic
`0019` (`imagery_snapshots` absent — `to_regclass` NULL), worker container
started `2026-09-11T21:47:46Z` and therefore loaded HEAD's code, not an older
process image (NORM-32). No production access of any kind was used to produce
this file.

Every number below comes from a read-only query run before the sweep. The
scripts are in `queries/` and their raw output in `queries/out/`; each row
names the file it came from.

---

## 0. What is being predicted, and for how many parcels

The brief names ten parcels: six incumbents and four candidates. This file
predicts **twelve**, because two of the four candidates resolve to more than
one row:

* **Marshall Fire** is one candidate with **two points** — the brief asks for
  the Sagamore (Superior) primary *and* a Louisville alternate, both with
  scene-edge distances, before a pick. Edge distance is measured from served
  scenes, so both points have to run.
* **Silver Creek Valley (San Jose)** is the **in-jurisdiction San Jose
  alternative** the brief asks me to propose if Cupertino turns out to be out
  of jurisdiction. It does (§2), so the alternative is here, run on the same
  code and catalogue so it can be ranked. It is a proposal, not a substitution:
  Apple Park is still run, at the point the brief's address resolves to.

| # | Label | Address as run | Point (lat, lon) | How the point was resolved | County | Stored tract |
|---|---|---|---|---|---|---|
| 1 | `rino-art-district` | 2901 Blake St, Denver, CO 80205 | 39.762786, -104.983456 | incumbent, already in the local DB | Denver | 08031001601 |
| 2 | `hudson-yards` | 500 W 33rd St, New York, NY 10001 | 40.753896, -73.999735 | incumbent | New York | 36061009903 |
| 3 | `green-valley-ranch` | 4800 Telluride St, Denver, CO 80249 | 39.783839, -104.781622 | incumbent | Denver | 08031008388 |
| 4 | `navy-yard-capitol-riverfront` | 1300 4th St SE, Washington, DC 20003 | 38.874833, -77.000503 | incumbent | District of Columbia | 11001007201 |
| 5 | `rodanthe-outer-banks` | 24241 Atlantic Dr, Rodanthe, NC 27968 | 35.584688, -75.464804 | incumbent | Dare | 37055970502 |
| 6 | `stapleton-central-park` | 8340 Northfield Blvd, Denver, CO 80238 | 39.785185, -104.891392 | incumbent | Denver | 08031004111 |
| 7 | `marshall-sagamore` | 333 Fox Ln, Superior, CO 80027 | 39.956238, -105.176513 | Census forward geocode (seed path) | Boulder | 08013060602 |
| 8 | `marshall-louisville` | 929 Eldorado Ln, Louisville, CO 80027 | 39.974884, -105.164606 | Census forward geocode (seed path) | Boulder | 08013013004 |
| 9 | `apple-park` | Apple Park Way, Cupertino, California 95014 | 37.334894, -122.013365 | **Photon** suggestion + reverse geocode — the Census forward geocode has no match for "1 Apple Park Way" or "One Apple Park Way" | Santa Clara | 06085508102 |
| 10 | `wharf-southwest-waterfront` | 760 Maine Ave SW, Washington, DC 20024 | 38.879238, -77.023572 | Census forward geocode (seed path) | District of Columbia | 11001010202 |
| 11 | `cornell-tech` | 2 West Loop Road, New York, New York 10044 | 40.755327, -73.956336 | **Photon** suggestion + reverse geocode — no Census match for "2 W Loop Rd" in either city form | New York | 36061023804 |
| 12 | `silver-creek-valley` | 5460 Country Club Pkwy, San Jose, CA 95138 | 37.274227, -121.772129 | Census forward geocode (seed path) | Santa Clara | 06085503338 |

Point evidence: `queries/out/geocode_probe_candidates.txt`,
`queries/out/census_match_batch*.txt`, `queries/out/predict_sources.txt`.

---

## 1. Landsat

**43 rows on every one of the twelve** — 1984–2026 inclusive, the CONUS span
`IMAGERY_SOURCE_START_YEAR['landsat'] = 1984` (`imagery.py:1007-1011`) through
the current year. All six incumbents hold exactly 43 today
(`queries/out/state_before.txt`).

Falsified by: any parcel below 43, any duplicate calendar year, or any parcel
above 43.

## 2. Sentinel-2

**12 rows on every one of the twelve** — one per calendar year 2015–2026.

*Premise correction, stated before the run:* the brief asks for "Sentinel-2
quarters" and for a range derived from the incumbents rather than a flat
threshold, citing O6. Sentinel-2 has not been quarter-grouped since `6489018`
(2026-08-25, G8): `selection_scope` is `"year"` (`timeline.py:95`) and the
expectation is flat by construction, `current_year − 2014 = 12`. O6's own row
records this — "Year grouping makes the expectation flat and
location-independent". The incumbent-derived range is therefore degenerate:
**all six incumbents hold exactly 12 today**, so the range is 12–12.

The one documented way to land at 11 is 2015 `absent`/`all_cloud_filtered` on
northern-tier parcels (O6: nine parcels, 38.7–47.5° N, all PNW/NorCal/Lake
Michigan). None of the twelve is in that cluster, so **11 on any parcel is a
deviation to investigate, not an accepted outcome** — and the ledger will say
which of `all_cloud_filtered` / `no_scenes` / `failed` it was.

## 3. NAIP

Predicted from a read-only Planetary Computer search per point, run with the
pipeline's own parameters — 1500 m bbox, `2010-01-01/2026-12-31`,
`max_items=50` — and a shapely point-in-geometry test on every returned tile
(`queries/predict_sources.py`, output `queries/out/predict_sources.txt`). A
year with at least one containing tile is a card; a year with tiles but none
containing the point is what `filter_groups_containing_point` suppresses.

| Label | Predicted NAIP years | n | Raw pool / cap |
|---|---|---|---|
| `rino-art-district` | 2011, 2013, 2015, 2017, 2019, 2021, 2023 | 7 | 28 / 50 |
| `hudson-yards` | 2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022, 2023 | 9 | 49 / 50 |
| `green-valley-ranch` | 2011, 2013, 2015, 2017, 2019, 2021, 2023 | 7 | 7 / 50 |
| `navy-yard-capitol-riverfront` | 2011–2018, 2021, 2023 | 10 | 42 / 50 |
| `rodanthe-outer-banks` | 2012, 2014, 2016, 2018, 2020, 2022 | 6 | 6 / 50 |
| `stapleton-central-park` | 2011, 2013, 2015, 2017, 2019, 2021, 2023 | 7 | 14 / 50 |
| `marshall-sagamore` | 2011, 2013, 2015, 2017, 2019, 2021, 2023 | 7 | 14 / 50 |
| `marshall-louisville` | 2011, 2013, 2015, 2017, 2019, 2021, 2023 | 7 | 7 / 50 |
| `apple-park` | 2012, 2014, 2016, 2018, 2020, 2022 | 6 | 12 / 50 |
| `wharf-southwest-waterfront` | 2011–2018, 2021, 2023 | 10 | 28 / 50 |
| `cornell-tech` | 2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022, 2023 | 9 | 35 / 50 |
| `silver-creek-valley` | 2012, 2014, 2016, 2018, 2020, 2022 | 6 | 6 / 50 |

Zero pools hit the 50-item cap; Hudson Yards is the closest at 49, so **a
"STAC search hit its item cap" warning on any of the twelve would be a
deviation**.

State flight patterns, read off the same search: **CO odd years 2011–2023**,
**CA even years 2012–2022**, **NC even years 2012–2022**, **NY 2010–2023**
including 2022 *and* 2023, **MD/VA 2011–2018, 2021, 2023**. No state in this
set has a 2024 or 2025 item in the collection.

Two brief premises are corrected here, before the run:

* **"CO was flown 2021 and 2023"** — confirmed, and the CO series is the full
  odd-year run 2011–2023. For the Marshall points the two flights bracket the
  fire (2021-12-30): the 2021 tile is `co_m_3910507_ne_13_060_20210813`
  (2021-08-13, pre-fire) and the 2023 tile is
  `co_m_3910507_ne_13_030_20230925_20240104` (2023-09-25, post-fire).
  **Predicted: both parcels serve a 2021 and a 2023 NAIP card, and the 2023
  capture_date is after 2021-12-30.**
* **"NY was not flown in 2023, so no 2023 card is served"** — false for both
  New York candidates. Hudson Yards has served a 2023 card since the geometry
  audit (`nj_m_4007416_se` contains the point — STATUS.md's geometry section
  says so explicitly), and Cornell Tech's 2023 pool holds
  `nj_m_4007309_sw_18_030_20230820_20231019`, whose footprint **contains** the
  Roosevelt Island point with **662 m to the footprint edge**
  (`queries/edge_distance.py item naip …`). Both are NJ-program quads that
  reach across the state line, and both are legitimate point-covering tiles,
  not the 350 5th Ave defect. **Predicted: `cornell-tech` serves a 2023 NAIP
  card, from that NJ item id, and it passes the point-coverage gate.**

## 4. Topo

Predicted by running the pipeline's own TNM query (same 1500 m bbox,
`max=100`) and reducing it the way `select_topo_items` does — one sheet per
decade, GeoTIFF url present, parseable `publicationDate`, non-empty
`sourceId`.

| Label | Predicted decades | n | TNM products (cap 100) |
|---|---|---|---|
| `rino-art-district` | 1890s, 1930s, 1940s, 1950s, 1960s, 1980s, 1990s | 7 | 36 |
| `hudson-yards` | 1880s, 1890s, 1900s, 1930s, 1940s, 1950s, 1960s, 1980s, 1990s | 9 | 72 |
| `green-valley-ranch` | 1890s, 1930s, 1940s, 1950s, 1960s, 1970s, 1980s | 7 | 30 |
| `navy-yard-capitol-riverfront` | 1890s, 1900s, 1930s, 1940s, 1950s, 1960s, 1980s | 7 | 45 |
| `rodanthe-outer-banks` | 1950s, 1960s, 1980s | 3 | 15 |
| `stapleton-central-park` | 1890s, 1930s, 1940s, 1950s, 1960s, 1970s, 1980s | 7 | 33 |
| `marshall-sagamore` | 1890s, 1940s, 1950s, 1960s, 1980s | 5 | 25 |
| `marshall-louisville` | 1890s, 1940s, 1950s, 1960s, 1980s | 5 | 25 |
| `apple-park` | 1880s, 1890s, 1900s, 1940s, 1950s, 1960s, 1970s, 1980s, 1990s | 9 | 80 |
| `wharf-southwest-waterfront` | 1890s, 1900s, 1940s, 1950s, 1960s, 1980s | 6 | 41 |
| `cornell-tech` | 1880s, 1890s, 1900s, 1940s, 1950s, 1960s, 1980s, 1990s | 8 | 67 |
| `silver-creek-valley` | 1880s, 1890s, 1940s, 1950s, 1960s, 1970s | 6 | 27 |

(Product counts are GeoTIFF-carrying products after the client's filter; none
was truncated, so **any `TNM query hit its row cap` warning during the sweep is
a deviation**, and Apple Park at 80 is the closest to the cap.)

Every incumbent's predicted decade count equals the count it holds today
(7/9/7/7/3/7 — `queries/out/state_before.txt`), so **zero topo churn is
predicted on the incumbents**.

## 5. Census — the expected set per dataset, not a count

Predicted by resolving the tract at each vintage the pipeline uses
(`_GEOGRAPHY_VINTAGES`, `census.py:186-199`) and then asking the Census API for
every (dataset, year) through the app's own `CensusFetcher`
(`queries/predict_sources.py`). So these are upstream facts: a deviation at run
time means the *pipeline*, not the API.

`DECENNIAL_YEARS = [2000, 2010, 2020]`, `ACS5_YEARS = [2009, 2012, 2015, 2018,
2021, 2023]` (`census.py:152-153`), nine attempted per parcel.

| Label | decennial present | decennial absent | acs5 present | acs5 absent | rows |
|---|---|---|---|---|---|
| `rino-art-district` | 2010, 2020 | 2000 | 2009, 2012, 2015, 2018, 2021, 2023 | — | 8 |
| `hudson-yards` | 2010, 2020 | 2000 | 2009, 2012, 2015, 2018, 2021, 2023 | — | 8 |
| `green-valley-ranch` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `navy-yard-capitol-riverfront` | 2010, 2020 | 2000 | 2009, 2012, 2015, 2018, 2021, 2023 | — | 8 |
| `rodanthe-outer-banks` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `stapleton-central-park` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `marshall-sagamore` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `marshall-louisville` | **2000**, 2010, 2020 | — | 2009, 2012, 2015, 2018, 2021, 2023 | — | **9** |
| `apple-park` | **2000**, 2010, 2020 | — | 2009, 2012, 2015, 2018, 2021, 2023 | — | **9** |
| `wharf-southwest-waterfront` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `cornell-tech` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |
| `silver-creek-valley` | 2010, 2020 | 2000 | 2012, 2015, 2018, 2021, 2023 | 2009 | 7 |

Every absence above is a **204 with an empty body** from the Census API for the
tract asked, which the ledger records as `absent`/`api_no_data` with the tract
in `detail`. It is not a 404 and not a silent skip.

*Premise correction:* the brief expects "no data for tract" **404s** as the
silent M4 skips. Since `e6afa9b` a 404 raises `CensusHttpStatusError` and lands
in the ledger as `failed`/`http_404` (`census.py:212-225`, `timeline.py:181`);
the no-data case is a **204**, logged as `Census API: no data for tract`
(`census.py:389-393`) and recorded as `absent`/`api_no_data`
(`timeline.py:1165-1171`). **Predicted: zero `http_404` ledger rows, and every
absence above present as `absent`/`api_no_data`.** A 404 on any of the twelve
would be a finding.

**Three incumbents gain a row.** `rino-art-district`, `hudson-yards` and
`navy-yard-capitol-riverfront` hold five acs5 rows today (2012–2023) and the
API has acs5 2009 for their 2010-vintage tracts, so the re-run should write it
— the `4ce1822` ride-along (acs5 2009 resolved at `Census2010_Current`) reaching
these parcels for the first time locally. **Predicted: `census_snapshots`
+1 row on each of those three, +0 on the other three incumbents.**

## 6. Tract lineage (2010 vs 2020)

From `geocoder.lookup_tract_at_vintage` at each vintage
(`queries/out/predict_sources.txt`). "Differ" is where a growth story splits a
tract and where M4-shaped gaps concentrate.

| Label | 2010 tract | 2020 tract | Differ? |
|---|---|---|---|
| `rino-art-district` | 08031001600 | 08031001601 | **yes** |
| `hudson-yards` | 36061009900 | 36061009903 | **yes** |
| `green-valley-ranch` | 08031008388 | 08031008388 | no |
| `navy-yard-capitol-riverfront` | 11001007200 | 11001007201 | **yes** |
| `rodanthe-outer-banks` | 37055970502 | 37055970502 | no |
| `stapleton-central-park` | 08031004107 | 08031004111 | **yes** (the 41.07 → 41.11 split `4ce1822` names) |
| `marshall-sagamore` | 08013060600 | 08013060602 | **yes** |
| `marshall-louisville` | 08013013004 | 08013013004 | no |
| `apple-park` | 06085508102 | 06085508102 | no |
| `wharf-southwest-waterfront` | 11001010200 | 11001010202 | **yes** |
| `cornell-tech` | 36061023801 | 36061023804 | **yes** |
| `silver-creek-valley` | 06085503334 | 06085503338 | **yes** |

Predicted consequence: on every "yes" parcel the served census rows carry **two
distinct `tract_fips`** — the 2010-vintage tract on acs5 2009–2018 and
decennial 2010, the 2020 tract on acs5 2021/2023 and decennial 2020. On the
three "no" parcels, one.

## 7. Property

From a read-only replay of `_fetch_property` against the live portals with the
app's own adapters, coverage gate, search-term extraction and H5 matcher
(`queries/property_probe.py`, output `queries/out/property_probe.txt`).

| Label | Predicted task state | queries_run | rows_returned → matched | items_found |
|---|---|---|---|---|
| `rino-art-district` | `complete` / `covered` | 2 | 14 → 13 | 14 (unchanged) |
| `hudson-yards` | `complete` / `covered` | 3 | 100 → 100 (Socrata cap 100 **hit**) | ≥ 40 |
| `green-valley-ranch` | `complete` / `covered` | 2 | 10 → 10 | 10 |
| `navy-yard-capitol-riverfront` | `complete` / `covered` | 8 | 181 → 53 | 128 |
| `rodanthe-outer-banks` | `skipped` / **`no_adapter`** | 0 | — | NULL |
| `stapleton-central-park` | `complete` / `covered` | 2 | 12 → 12 | 12 |
| `marshall-sagamore` | `skipped` / **`no_adapter`** | 0 | — | NULL |
| `marshall-louisville` | `skipped` / **`no_adapter`** | 0 | — | NULL |
| `apple-park` | `skipped` / **`not_covered`** | 0 | — | NULL |
| `wharf-southwest-waterfront` | `complete` / `covered` | 8 | 6 → 6 | 6 |
| `cornell-tech` | `complete` / `covered` | 3 | 29 → 29 | 29 |
| `silver-creek-valley` | `complete` / `covered` | 3 | **4 → 0** | **0** |

Two of these are the interesting ones and both are predicted before the run:

* **`silver-creek-valley` will show zero property events with four rows
  returned.** San Jose's CKAN holds four permits at the address and the H5
  matcher rejects all four: the record street line is
  `'5460  COUNTRY CLUB PY  '`, `PY` is not in `SUFFIX_MAP`
  (`address_normalizer.py:13-32`), so the token overlap is 2/3 = 0.667 against
  a 0.7 threshold (`address_normalizer.py:153-181`). This is Z4's shape,
  visible only as `rows_returned=4, rows_matched=0`.
* **`rodanthe-outer-banks`'s served property row changes shape.** Its current
  served row is pre-0014 — `skipped`, `coverage` NULL, `items_found` 0
  (`queries/out/state_before.txt`) — which is AA5's local instance. A
  full-scope re-run writes `coverage='no_adapter'` with `items_found` NULL, so
  the task row should read "not covered" instead of "0 items"
  (`ParcelInfo.tsx:35-50`).

## 8. Ledger (`timeline_task_years`) shape per parcel

Per parcel, one row per attempted group (`imagery.attempted_group_keys`):
**43 landsat + 12 sentinel2 + 17 naip (2010–2026) + 9 census + topo**. Topo has
no attempted set, so it records only the decades the response held, plus a `*`
row if the search failed or was capped.

Predicted outcome mix:

* landsat: 43 `ok` on every parcel, 0 `failed`, 0 `absent`.
* sentinel2: 12 `ok`, 0 `absent`, 0 `failed`.
* naip: `ok` on the years in §3, `absent`/`no_scenes` on the remaining years of
  2010–2026, and **zero `suppressed`/`naip_no_point_coverage`** — the probe
  found no year with tiles but no containing tile, on any of the twelve.
* census: `ok`/`absent` exactly as §5, all absences `api_no_data`.
* topo: one `ok` per decade in §4, no `*` row.
* **Fleet-wide: zero `failed` rows and zero `indeterminate` rows.** Any of
  either is a deviation and gets attributed to a parcel and a source in §7 of
  the report.

## 9. Geometry (item 6 of the brief)

* **Zero `bbox=Y, geom=N` rows across all twelve parcels and every served
  scene, primary and mosaic tile.** The point filter has read
  `item["geometry"]` since `2039e64`; a residue row would mean either a scene
  written before that fix survived reconciliation, or the fix has a hole.
* Minimum edge distances: Landsat scenes are 185 km wide and every incumbent is
  interior, so **no Landsat row under 1 km** is expected on any parcel;
  Sentinel-2 has a real tail (FINDINGS §5: 45 of 836 rows under 1 km) and
  Rodanthe is the coastal one, so **an S2 row under 1 km at Rodanthe or the
  Wharf is plausible and not a defect by itself**; NAIP quads are ~6 km, so
  sub-1-km rows are routine and the meaningful figure is <200 m. The one
  already-measured value: `cornell-tech` NAIP 2023 sits **662 m** inside its
  footprint edge.
* **Prediction: at least one NAIP row under 1 km on `cornell-tech` (the 2023
  NJ quad), and zero rows of any source *outside* their footprint.**

## 10. Run mechanics and noise

* Six parcels are created through `POST /api/v1/geocode` (the four candidates,
  the Marshall alternate, the San Jose alternative); six incumbents are
  re-queued full-scope with `scripts/requeue_parcels.py --skip-deploy-check`
  (local health reports `sha: dev`). Full scope, not `--sources`: a scoped
  request is never served to a page (`imagery.py:183-205`), which is AA6's
  mechanism.
* **Predicted: 12 requests, all reaching `complete`, zero `failed`, zero
  `partial`.**
* **Predicted noise: some Planetary Computer 429s.** The signing endpoint
  already returned `429 Rate limit is exceeded. Try again in 53 seconds` three
  times during this file's own LCMAP probe (`queries/out/lcmap_change_2.txt`),
  and twelve parcels × (43 + 12) year-chunk searches plus band signing is a
  heavier burst than that. The `_sas_get` retry (429 only) and
  `SIGN_WAIT_BATCH` should absorb them; **what would be a finding is a 429 that
  costs a year** — i.e. a `failed`/`sign_429` or `failed`/`stac_403` ledger row.
* Retries: any re-run of a parcel will be counted and its reason stated in
  VETTING.md §7. A green result reached by retrying is reported as a retry, not
  as a first-pass green.

## 11. What this prediction deliberately does not settle

* **Landsat and Sentinel-2 per-year availability was not probed upstream.**
  43 + 12 searches × 12 parcels is 660 PC searches before the run, which would
  distort the very noise profile §10 is about. Their expectations come from the
  config floors and the incumbents' current counts.
* **Nothing here predicts image content.** "The burn scar is visible", "the ring
  is visible" are claims about pixels; the only pixel-level evidence in this
  batch is the LCMAP land-cover shares in `queries/out/lcmap_change_*.txt`,
  which are a Landsat-derived *class* product and cannot see change inside the
  Developed class.
* **The seed path is not exercised by the run.** `scripts/seed_featured.py`
  geocodes with no coordinates, so for `apple-park` and `cornell-tech` — where
  the Census forward geocode has no match — it would 422 and seed nothing. That
  is reported as a finding, not fixed, and the run uses the Photon path those
  two would need.
