# Featured-locations vetting — evidence and recommendation

Read-only investigation, **2026-09-11**, local stack only. No production access
of any kind: no `fly ssh`, no prod tunnel, no prod query. No application code,
no migration, no `scripts/seed_featured.py`, no `featured_locations` row was
changed. Twelve parcels were created or re-queued **in the local database
only**.

Environment: HEAD `332b5e6` (clean tree at session start), Alembic `0019`
(`to_regclass('public.imagery_snapshots')` → NULL), `docker compose` with the
worker container started `2026-09-11T21:47:46Z` — after HEAD, so the worker
process is running HEAD's code rather than an older image's (the NORM-32 trap).
Sweep window `2026-09-11T22:15:34Z` → `22:19:08Z`.

Prediction, written and committed before any parcel was created or re-queued:
`PREDICTION.md` (commit `ba8bb04`). It is scored in §6 and was not edited.

Every number below cites the file in `queries/out/` that produced it. The
scripts that produced those files are in `queries/`, and each is runnable again
against a future state of the database.

---

## 1. What was read, and where STATUS.md contradicts the brief's premises

Read at HEAD: `docs/audits/2026-08-second-audit/STATUS.md` (rows G1, G2, O6,
M4, the Adams/Santa Clara entry under *To investigate*, plus the NORM section
for the current schema), `docs/audits/2026-08-geometry-audit/HEAL-SCORECARD.md`
§2 and §7, `docs/audits/2026-08-geometry-audit/FINDINGS.md` §1 and §5,
`scripts/seed_featured.py`, `backend/app/services/county_adapters.py`, and the
`Scene` / `ParcelScene` models in `backend/app/models/parcels.py`.

**Seven notes. Six correct or sharpen a premise in the brief; the seventh
records that STATUS.md moved under this session.**

1. **`seed_featured.py` is `scripts/seed_featured.py`, not
   `backend/scripts/`.** `backend/scripts/` exists and is empty
   (root-owned). No other copy exists (`find -name seed_featured.py`).

2. **Sentinel-2 is not grouped by quarter, and O6 no longer rejects a flat
   expectation.** `6489018` (2026-08-25, row G8) moved the S2 selection scope
   to the calendar year (`timeline.py:88-95`), and O6's own row records the
   consequence: *"Year grouping makes the expectation flat and
   location-independent — `current_year − 2014` = 12"*. The brief asks for a
   range derived from the incumbents instead of a flat threshold; derived from
   the incumbents, the range **is** flat — all six held exactly 12 before the
   sweep and all twelve parcels hold exactly 12 after it
   (`queries/out/state_before.txt`, `queries/out/scorecard.txt` §3). The one
   documented way to get 11 is 2015 `absent`/`all_cloud_filtered` on
   northern-tier parcels; it did not occur here.

3. **"No data for tract" is a 204, not a 404, and it is not silent.** M4 is
   Resolved (2026-08-27) and the per-year ledger is live. A 204 is logged
   (`census.py:389-393`) and recorded as `absent`/`api_no_data` with the tract
   in `detail`; a 404 raises `CensusHttpStatusError` and lands as
   `failed`/`http_404` (`census.py:212-225`, `timeline.py:181`). This run
   produced **17 204s and zero 404s**, and every one of the 17 has a matching
   ledger row (§6.4).

4. **The "Photon path" is Census-first.** `POST /api/v1/geocode` always tries
   the Census forward geocoder on the submitted string; Photon coordinates are
   used only when that fails *and* the coordinates were served by this
   backend's own autocomplete, and then through `reverse_geocode`
   (`api/v1/geocode.py:200-241`). `scripts/seed_featured.py` sends **no**
   coordinates (`:134`), so the seed path is Census-only with no fallback —
   which is why two of the four candidate addresses cannot be seeded at all
   (§3).

5. **"NY was not flown in 2023, so no 2023 card is served" is false for both
   New York candidates.** Hudson Yards has served a 2023 NAIP card since the
   geometry heal, and Cornell Tech gets one too. Both come from NJ-program
   quads that reach across the state line and **contain the point**: Hudson
   Yards `nj_m_4007309_sw_18_030_20230820_20231019` at **124.2 m** inside the
   footprint edge, Cornell Tech the same item id at **661.9 m**
   (`queries/out/edge_distance.txt`). This is not the 350 5th Ave defect; it is
   the same tile, legitimately covering different points.

6. **"CO was flown 2021 and 2023" is right, and narrower than the whole
   truth**: the Colorado series in the PC `naip` collection is the full
   odd-year run 2011–2023. More usefully for a disaster page, the two Marshall
   flights bracket the fire — 2021-08-13 (pre) and 2023-09-25 (post)
   (`queries/out/scorecard.txt` §9).

7. **Two STATUS.md rows landed mid-session, from another session.** At session
   start `STATUS.md` was clean at `332b5e6`; at 21:50Z it carried uncommitted
   **AA5** and **AA6**, committed at 22:0xZ as `14dec9c`. They bear directly on
   this work — AA5 is "the pre-0014 `no_adapter` property row is still what the
   page serves", and Rodanthe is one of its named parcels. This session touched
   neither that file nor that folder; §6.5 records that the local re-run
   reproduces AA5's remedy exactly.

Everything else in the brief's premises checks out. In particular **4 of 6
incumbents were serving wrong-footprint cards before the geometry fix**
(FINDINGS §3: RiNo 6, Hudson Yards 5, Green Valley Ranch 2, Rodanthe 2 = 15
cards), and both of the featured-page rows that survived that heal — **G1**
(the wrong-place NAIP 2023 card) and **G2** (Rodanthe's 25.04 % Sentinel-2
granule) — are now **Resolved** in STATUS.md. This run finds no wrong-footprint
card on any of the six (§6.6).

---

## 2. Hard gate — jurisdiction, before any pipeline run

The gate was run as a read-only replay of `_fetch_property` with the app's own
adapters, coverage gate, search-term extraction and H5 matcher
(`queries/property_probe.py` → `queries/out/property_probe.txt`), plus direct
queries against each portal.

| Candidate | County → adapter | Coverage verdict | Evidence |
|---|---|---|---|
| Apple Park, Cupertino | Santa Clara → `SantaClaraAdapter` | **Out of jurisdiction** | `COVERED_CITIES = {"SAN JOSE"}` (`county_adapters.py:632`); `covers("CUPERTINO")` → False |
| Cornell Tech, Roosevelt Island | New York → `NewYorkCountyAdapter` | **Covered, and it returns real rows** | 29 DOB permit rows, 29 matched |
| The Wharf, 760 Maine Ave SW | District of Columbia → `DCAdapter` | **Covered** | 8 queries, 6 rows, 6 matched |
| Marshall Fire (both points) | Boulder → *none* | **No adapter** | `COUNTY_ADAPTERS` has no `boulder` key (`county_adapters.py:972-978`) |

### 2.1 Santa Clara is the City of San Jose's portal — confirmed, and the portal itself is empty for Cupertino

The adapter reads `data.sanjoseca.gov`, San Jose's own CKAN, across three
permit resources (`county_adapters.py:617-623`). Sales are not fetched at all
(`fetch_sales` returns an empty `SourceFetchResult`, `:647-655`).

The brief asked for one read-only query against that endpoint for the Apple
Park address. All twelve combinations were run
(`queries/out/ckan_apple_park_probe.txt`):

```
active/under_inspection/expired  q='1 APPLE PARK'   rows=0
active/under_inspection/expired  q='APPLE PARK'     rows=0
active/under_inspection/expired  q='10600 TANTAU'   rows=0
```

So the refusal is not merely a gate decision: **the portal holds nothing for
the address, because Cupertino issues its own permits.** The gate is the
correct answer and the honest one — `skipped` / `coverage='not_covered'` /
`queries_run=0`, which is "we did not ask", not "we asked and there is
nothing". Observed live in the run (§6.5).

### 2.2 New York County does cover Roosevelt Island — permits yes, sales structurally no

DOB Permit Issuance (`ipu4-2q9a`) answers `house__='2' AND upper(street_name)
LIKE '%LOOP%'` with **29 rows, all `2 WEST LOOP ROAD`**, all 29 accepted by the
H5 matcher. They persist as **7** events, not 29: `uq_property_events_parcel_
source_record` is `(parcel_id, source, source_record_id)` and
`source_record_id` is the DOB **job number**, of which there are seven
(`queries/out/scorecard.txt` §5; job ids 121187571 … 140326966). NYC publishes
one row per filing, so a 4:1 collapse is normal.

Sales return zero, and there are **two separate reasons**, only one of which is
a defect:

* Roosevelt Island has no sales rows to find: `borough='1' AND upper(address)
  LIKE '%WEST LOOP%'` on `w2pb-icbu` returns **0** (the campus sits on RIOC
  ground lease).
* **The sales query cannot match a directional address at all.** The pattern is
  `'%{house} {street}%'` (`county_adapters.py:781`), and `extract_search_terms`
  drops the directional and the ordinal suffix, so "450 W 33rd St" goes out as
  `'%450 33%'`. Live: `'%450 WEST 33%'` → **1 row**, `'%450 33%'` → **0 rows**.
  This is latent for both NY parcels here (neither address has a sale record)
  and live for any Manhattan address that does. Proposed as **FV-1** in §9.

### 2.3 DC covers the Southwest Waterfront, with a date floor

`760 MAINE AVE SW` matches the DC permit layers on 6 rows, all at that exact
address, all matched. But `DCAdapter.PERMIT_LAYERS` is seven **year-specific**
layers, 2020 through 2026 (`county_adapters.py:466-474`), so the Wharf's
construction era (2014–2017) is structurally unreachable: the earliest event
the page can show is **2020-11-17** (`queries/out/scorecard.txt` §5). Sales
returned zero rows for this address.

### 2.4 Boulder has no adapter — and the UI says so explicitly

This is the state the brief asked me to characterise. It is an explicit skip,
not a broken-looking page. Observed after the run, on the real API and against
the components that read it:

* **Task row:** `skipped`, `coverage='no_adapter'`, `items_found` NULL,
  `queries_run=0`, `error_message='Property data not yet available for Boulder
  County'` (`queries/out/scorecard.txt` §2).
* **`GET /api/v1/parcels/{id}/events`:** `{"county": "Boulder", "supported":
  false, "supported_counties": ["Denver County, CO", "Adams County, CO",
  "Washington, DC", "Santa Clara County, CA", "New York County, NY"]}`
  (`queries/out/events_api_states.txt`).
* **Sidebar source list:** `ParcelInfo.tsx:35-50` renders `items_found == null
  && skipped && coverage !== 'covered'` as the literal string **"not covered"**
  (not "0 items"), and `SourceIssueRow` (`:63-77`) prints the task's own
  `error_message` under the timeline.
* **Demographics panel:** `supported: false` sets `showUnsupported`
  (`DemographicsPanel.tsx:70`), which renders `UnsupportedCountyBanner` —
  *"Property records not yet available for Boulder County. Currently supported:
  …"* (`:206-210`).

One wording note, not a defect: the task row says "not covered" for
`no_adapter` as well as for `not_covered`, so the two skip reasons read
identically in the sidebar; only the banner distinguishes them.

For contrast, Apple Park's not-covered case renders differently:
`/events` reports `supported: **true**` (the flag is computed from the adapter
registry alone, `events.py:63`), so the unsupported-county banner does *not*
fire; the `NotCoveredBanner` fires instead, off the served task's
`coverage='not_covered'` and its message *"Santa Clara County's records don't
cover Cupertino — the city keeps its own"* (`ParcelInfo.tsx:299-300` →
`DemographicsPanel.tsx:171`). That is correct **only while the served request
is a full-scope one carrying 0014's columns** — which is exactly AA6's warning.

### 2.5 The in-jurisdiction San Jose alternative (proposed, not substituted)

Apple Park is out of jurisdiction, so per the brief I propose one San Jose
address and do not substitute it for Apple Park — Apple Park was run at the
point its own address resolves to (§3).

**Proposal: `5460 Country Club Pkwy, San Jose, CA 95138` — Silver Creek Valley
Country Club.** Reasoning:

* **In jurisdiction.** The Census forward geocode returns `5460 COUNTRY CLUB
  PKWY, SAN JOSE, CA, 95138`, so `city_from_address` → `SAN JOSE` →
  `covers()` → True (`queries/out/property_probe.txt`).
* **Landsat-legible, and measured rather than asserted.** LCMAP CONUS v1.3
  (`usgs-lcmap-conus-v13`, the Landsat-derived annual land-cover product)
  within ±500 m of the point: **1985 Grass/Shrub 66 %, Developed 28 % → 2001
  Developed 81 % → 2021 Developed 79 %** — a **+51-point** shift into
  Developed, achieved almost entirely between 1985 and 2001
  (`queries/out/lcmap_change_2.txt`). For calibration on the same instrument,
  the two incumbent greenfield stories score **+46** (Green Valley Ranch, 1985
  Grass/Shrub 90 % → 2021 Developed 46 %) and **+62** (Stapleton, Developed
  35 % → 97 %). The candidate's change is the same size as the stories the
  product already tells.
* **Archetype:** hillside build-out — grazing land to golf course and gated
  subdivision, 1990s–2000s. New state, new decade, new form.
* **What it is not:** iconic. It is a country-club subdivision, not a landmark.

The same instrument is why Apple Park's "visible at every resolution" needs
qualifying: at the Apple Park point, LCMAP reads **99 % Developed in 1985 and
92 % Developed + 8 % Cropland in 2021** — the ring replaced an office park, so
the *land-cover class* barely moves. The change is unmistakable at NAIP's
0.6 m and legible as shape at 30 m; it is not a land-cover change.

Two San Jose options were measured and rejected: North San Jose (Cisco Way) was
already 68–72 % Developed in 1985 (+27 points by 2021), and Communications Hill
70–86 % Developed in 1985 (+6) — neither is a farmland-to-campus story on the
evidence (`queries/out/lcmap_change_1.txt`, `_2.txt`).

---

## 3. Point selection

### 3.1 What the geocoders actually returned

`queries/out/geocode_probe_candidates.txt`, `queries/out/census_match_batch*.txt`.

| Candidate | Census forward geocode (the seed path) | Photon autocomplete (the UI path) | Point used |
|---|---|---|---|
| 760 Maine Ave SW, Washington DC | **match** `760 MAINE AVE SW, WASHINGTON, DC, 20024` 38.879238, -77.023572 | street-level `Maine Avenue Southwest` (bus_stop) | Census |
| 5460 Country Club Pkwy, San Jose | **match** 37.274227, -121.772129 | — | Census |
| 333 Fox Ln, Superior CO | **match** `333 FOX LN, SUPERIOR, CO, 80027` 39.956238, -105.176513 | street-level `Cherokee Avenue` | Census |
| 929 Eldorado Ln, Louisville CO | **match** 39.974884, -105.164606 | `Via Appia Way` (bus_stop) — wrong place | Census |
| **1 Apple Park Way / One Apple Park Way, Cupertino** | **NO MATCH** (both forms) | `Apple Park Way, Cupertino, California 95014`, `osm_value=unclassified` (a road), 37.334894, -122.013365 | **Photon + reverse geocode** |
| **2 W Loop Rd, New York / Roosevelt Island NY** | **NO MATCH** (both city forms) | `2 West Loop Road, New York, New York 10044`, `osm_value=outdoor_seating`, 40.755327, -73.956336 | **Photon + reverse geocode** |

**Finding: two of the four candidate addresses cannot be seeded by the seed
script at all.** `seed_featured.py` posts the address with no coordinates, so a
Census miss is a 422 and the loop prints `FAILED (422)` and `continue`s
(`:134-137`) — no parcel, no featured row, no Photon fallback. Apple Park and
Cornell Tech are both in that state. Proposed as **FV-5**.

Census-matchable addresses do exist on both campuses and are recorded here as
information for the owner, **not** substituted into this run: `10600 N Tantau
Ave, Cupertino, CA 95014` → 37.331413, -122.005728 (Apple Park Visitor Centre,
779 m east of the point actually used) and `1 Main St, New York, NY 10044` →
40.752906, -73.957347 (282 m south of the Cornell Tech point). Roosevelt
Island's Main Street addresses geocode; its Loop Road addresses do not.

Neither Photon hit is AA4's city-level shape — both are sub-city features (a
road and a POI), so `city_from_address` reads a real city in both cases
(`CUPERTINO`, `NEW YORK`) and the coverage gate makes a real decision rather
than failing open. The Apple Park point is nonetheless **a road, not a
property**, which is the same class of thing AA4 is about one level down.

Viewport framing at the default zoom 15 (`MapView.tsx:76`), 1280×800 px:
±2.43 km E-W and ±1.52 km N-S at 37.3° N. The Apple Park campus (779 m across
the point-to-Visitor-Centre span) and the Cornell Tech campus (282 m) are both
inside it; Landsat and Sentinel-2 cards ease out to zoom 13
(`MapView.tsx:176`), ±9.7 km E-W.

### 3.2 The Marshall Fire point — chosen, with both options measured

The perimeter is **not** in NIFC's `InterAgencyFirePerimeterHistory_All_Years_
View` (an 11-row `INCIDENT LIKE '%arshall%'` query returns no 2021 Colorado
fire, and a point query over Sagamore returns zero features). It **is** in
`WFIGS_Interagency_Perimeters` layer 0: `poly_IncidentName='Marshall'`,
`attr_UniqueFireIdentifier='2021-COBLX-000995'`, 6,079.9 GIS acres
(`queries/out/marshall_points_chosen.txt`).

Damage evidence is Boulder County's own residential damage assessment
(`RDA_Public_View` layer 0, 1,473 rows; fields `addr`, `damage`,
`jurisdiction`). Superior holds 386 Destroyed; Louisville 555
(`queries/out/marshall_rank.txt`).

|  | **Sagamore, Superior** (`333 Fox Ln`) | **Harper Lake, Louisville** (`929 Eldorado Ln`) |
|---|---|---|
| Point | 39.956238, -105.176513 | 39.974884, -105.164606 |
| Inside the WFIGS Marshall perimeter | **yes**, 658 m from the boundary | **yes**, 177 m from the boundary |
| Structures within 250 m | **153, all Destroyed** | 164 Destroyed, 1 Minor |
| Within 500 m | **187, all Destroyed** | 303 Destroyed, 11 Minor, 4 Affected, 2 Major |
| Within 1 km | 309 Destroyed, 6 Minor, 4 Affected, 2 Major | 392 Destroyed, 19 Minor, 16 Affected, 9 Major |
| Inside the z15 viewport | 469 Destroyed, 18 Minor, 10 Affected, 4 Major | 486 Destroyed, 26 Minor, 39 Affected, 14 Major |
| Neighbourhood total | **171 structures, 171 Destroyed, 0 anything else** | 265 structures, 259 Destroyed, 5 Minor, 1 Major |
| Census rows served | 7 (decennial 2000 and acs5 2009 absent) | **9 — the full set** |
| Min Landsat edge distance | 18,491 m | 19,009 m |
| Min Sentinel-2 edge distance | 7,207 m | 7,282 m |
| Min NAIP edge distance | 1,143 m | 2,164 m |

Both are geometrically safe by a wide margin. **The pick is Sagamore**, on
three grounds:

1. **"A block that was fully destroyed" is literally true only here.** Every
   one of the 187 structures within 500 m is `Destroyed`, and the
   neighbourhood's own tally in the county layer is **171 of 171** — the same
   count contemporaneous reporting used ("all 171 homes in the neighborhood
   burned down", [9news](https://www.9news.com/article/news/local/wildfire/marshall-fire-sagamore-subdivision-superior/73-aac0cd4c-7a68-42e3-b1aa-c94242e19257)).
   Harper Lake mixes Minor/Affected/Major from 250 m out.
2. **The burn edge is not in the immediate frame.** Sagamore sits 658 m inside
   the fire perimeter against Louisville's 177 m, so at Louisville the
   burned/unburned boundary crosses the near field of the default view. (At
   z15 both frames are ~4.7 × 2.9 km, so both eventually reach unburned ground;
   the difference is how close it starts.)
3. Its NAIP pair brackets the fire the same way (2021-08-13 / 2023-09-25), and
   both points share the identical NAIP quad and topo set.

The cost of the pick is real and is the reason both rows stay in this report:
**Sagamore serves 7 census years and Louisville 9** (Louisville's tract
`08013013004` answers at every vintage from 2000 on; Sagamore's is
`08013060600` at the 2010 vintage and `08013060602` at 2020, and neither
`2000/dec/sf1` nor acs5 2009 has data for the tract asked). If the
demographic series matters more than the frame, the Louisville point is the
better parcel and is fully vetted here.

*(Item 4 of the brief — the prediction — is `PREDICTION.md`, committed at
`ba8bb04` before this section's run and scored in §6. That is why this report
has no §4.)*

---

## 5. The run

Twelve parcels, one sweep, one code state, one catalogue state.

* Six candidates created through `POST /api/v1/geocode` between 22:15:34Z and
  22:16:36Z (four via the plain address, two via the Photon path with
  autocomplete-served coordinates).
* Six incumbents re-queued **full scope** at 22:17:04Z with
  `scripts/requeue_parcels.py --skip-deploy-check` (local `/api/v1/health`
  reports `sha: dev`). Output captured, **exit code 0**, `Done — queued 6
  timeline request(s), skipped 0.`, no `unreached:` line
  (`queries/out/requeue_incumbents.txt`). Full scope, not `--sources`, because
  a scoped request is never served to a page (`imagery.py:183-205`, AA6).
* Log capture started **33 s before** the first parcel (22:15:01Z) and ran to
  the end of the sweep — `docker compose logs -f worker api`, 57,153 lines, no
  gap. What is committed is the reduced form: every structured log **event**
  (2,314 lines, 11 of them `warning`), with SQLAlchemy's statement echo
  stripped, at `queries/out/run_capture_events.txt`. Each count in §7 was taken
  from the full capture and re-verified against the reduced one.

**Outcome: 12 requests, 12 `complete`, 0 `failed`, 0 `partial`, 0 retries.**
Not one parcel was re-run: `queries/out/scorecard.txt` §10 lists exactly one
request per parcel in the window. Task rows: 12 × `census`, `landsat`, `naip`,
`sentinel2`, `usgs_topo` all `complete`; `property` 8 `complete` + 4 `skipped`.
Request wall time 24.8 s (Stapleton) to 123.8 s (Hudson Yards).

Fleet totals, before → after (`queries/out/state_before.txt`,
`queries/out/scorecard.txt` §11): parcels 45 → 51, `parcel_scenes` 3,082 →
3,496 (+414, exactly the six new parcels' rows), `scenes` 1,342 → 1,386,
`census_snapshots` 330 → 379 (+49), `property_events` 660 → 673 (+13),
`timeline_task_years` 17,892 → 18,944.

**Incumbent churn: one row.** Across all six incumbents, exactly one
`parcel_scenes` row was written by the sweep — RiNo's Sentinel-2 **2026**, the
open year. Everything else is untouched: no card gained, no card lost, no
duplicate group, no topo or NAIP movement.

---

## 6. Scorecard against `PREDICTION.md`

### 6.1 Per-source counts

| Parcel | Landsat | Sentinel-2 | NAIP | Topo | Census | Property | Verdict |
|---|---|---|---|---|---|---|---|
| 1 rino-art-district | 43 / 43 | 12 / 12 | 7 / 7 | 7 / 7 | 8 / 8 | 14 events / 14 | **confirmed** |
| 2 hudson-yards | 43 / 43 | 12 / 12 | 9 / 9 | 9 / 9 | 8 / 8 | 40 / ≥40 | **confirmed** |
| 3 green-valley-ranch | 43 / 43 | 12 / 12 | 7 / 7 | 7 / 7 | 7 / 7 | 10 / 10 | **confirmed** |
| 4 navy-yard | 43 / 43 | 12 / 12 | 10 / 10 | 7 / 7 | 8 / 8 | 128 / 128 | **confirmed** |
| 5 rodanthe | 43 / 43 | 12 / 12 | 6 / 6 | 3 / 3 | 7 / 7 | skipped/`no_adapter` | **confirmed** |
| 6 stapleton | 43 / 43 | 12 / 12 | 7 / 7 | 7 / 7 | 7 / 7 | 12 / 12 | **confirmed** |
| 7 marshall-sagamore | 43 / 43 | 12 / 12 | 7 / 7 | 5 / 5 | 7 / 7 | skipped/`no_adapter` | **confirmed** |
| 8 marshall-louisville | 43 / 43 | 12 / 12 | 7 / 7 | 5 / 5 | 9 / 9 | skipped/`no_adapter` | **confirmed** |
| 9 apple-park | 43 / 43 | 12 / 12 | 6 / 6 | 9 / 9 | 9 / 9 | skipped/`not_covered` | **confirmed** |
| 10 wharf | 43 / 43 | 12 / 12 | 10 / 10 | 6 / 6 | 7 / 7 | 6 / 6 | **confirmed** |
| 11 cornell-tech | 43 / 43 | 12 / 12 | 9 / 9 | 8 / 8 | 7 / 7 | **7 / 29** | **falsified** (see 6.3) |
| 12 silver-creek | 43 / 43 | 12 / 12 | 6 / 6 | 6 / 6 | 7 / 7 | **0 / 0** | **confirmed** |

Observed / predicted. Landsat 43 on all twelve, no duplicate year, none above
43. Sentinel-2 exactly 12 on all twelve (2015–2026), no duplicate calendar
year, none at 11. Every predicted NAIP **year set** matched exactly, not just
the count (`queries/out/scorecard.txt` §3 against `PREDICTION.md` §3), and
every topo **decade set** matched.

### 6.2 Census — years present and missing, per dataset

Every parcel's set matched the prediction exactly, including the three
incumbents predicted to *gain* acs5 2009 (`rino`, `hudson-yards`, `navy-yard`
— the `4ce1822` vintage ride-along reaching them locally for the first time).
`census_snapshots` +49 rows, the predicted number to the row.

| Parcel | decennial present | acs5 present | absent, all `api_no_data` | tracts served |
|---|---|---|---|---|
| rino | 2010, 2020 | 2009, 2012, 2015, 2018, 2021, 2023 | dec 2000 | 08031001600 → 08031001601 |
| hudson-yards | 2010, 2020 | 2009 … 2023 | dec 2000 | 36061009900 → 36061009903 |
| green-valley-ranch | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 08031008388 only |
| navy-yard | 2010, 2020 | 2009 … 2023 | dec 2000 | 11001007200 → 11001007201 |
| rodanthe | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 37055970502 only |
| stapleton | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 08031004107 → 08031004111 |
| marshall-sagamore | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 08013060600 → 08013060602 |
| marshall-louisville | **2000**, 2010, 2020 | 2009 … 2023 | — | 08013013004 only |
| apple-park | **2000**, 2010, 2020 | 2009 … 2023 | — | 06085508102 only |
| wharf | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 11001010200 → 11001010202 |
| cornell-tech | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 36061023801 → 36061023804 |
| silver-creek | 2010, 2020 | 2012 … 2023 | dec 2000, acs5 2009 | 06085503334 → 06085503338 |

**Is each absence plausible, or a failure?** Plausible, and independently
confirmed: the same 17 absences were produced by asking the Census API directly
*before* the run, at the same vintage-resolved tracts
(`queries/out/predict_sources.txt`). Both patterns are structural rather than
per-parcel:

* **decennial 2000 is absent wherever the 2020-vintage tract is not a 2000
  tract code** — 10 of 12. `_GEOGRAPHY_VINTAGES` has no entry for decennial
  2000 (the geocoder's oldest vintage is `Census2010_Current`), so the stored
  tract is asked of `2000/dec/sf1`. This is the open item STATUS.md records
  under *To investigate* ("Decennial 2000 has no geocoder vintage"). The two
  parcels that do get 2000 are the two whose tract has not changed since.
* **acs5 2009 is absent wherever the 2010 tract did not exist in 2009** — 8 of
  12, all of them tracts created or renumbered in the 2010 redistricting.

**Tract lineage** (`PREDICTION.md` §6) was confirmed on all twelve: eight
parcels differ between 2010 and 2020 and serve two `tract_fips`; four
(green-valley-ranch, rodanthe, marshall-louisville, apple-park) do not and
serve one. Stapleton's is the 41.07 → 41.11 split `4ce1822` already names.

### 6.3 The one falsified line, and its mechanism

**Cornell Tech property `items_found`: predicted 29, observed 7.** The
prediction read the matcher's output (29 rows matched) as the served count. It
is not: `upsert_property_event` conflicts on `(parcel_id, source,
source_record_id)` (`models/parcels.py:652-656`) and NYC DOB's
`source_record_id` is the job number, so 29 filings on 7 jobs persist as 7
events. Hudson Yards shows the same collapse at a larger scale (100 rows
matched, 40 events) and was predicted only as "≥ 40", which is why it did not
trip. Nothing is lost: the timeline shows 7 permit events spanning 2015-05-05
to 2019-05-08 — the construction record of the campus.

Also **falsified in the direction of more information, not less**: hudson-yards
`usgs_topo` recorded one `indeterminate` row on the whole-source key `*`
(reason: TNM cap), where the prediction said zero `indeterminate` fleet-wide.
Its nine topo decades are unaffected and match the prediction. See §7.

### 6.4 The M4 surface — every non-`ok` ledger row

Fleet-wide over the twelve served requests, **1,052 ledger rows: zero
`failed`, zero `suppressed`, one `indeterminate`, 130 `absent`, 921 `ok`**
(`queries/out/scorecard.txt` §6, §7).

| Outcome | Count | Composition |
|---|---|---|
| `ok` | 921 | landsat 516 (43 × 12), sentinel2 144 (12 × 12), naip 91, usgs_topo 79, census_acs5 65, census_decennial 26 |
| `absent` / `no_scenes` | 113 | NAIP years in 2010–2026 with no tile in the pool (204 naip groups attempted, 91 served) |
| `absent` / `api_no_data` | 17 | decennial 2000 ×10, acs5 2009 ×7 |
| `indeterminate` | 1 | hudson-yards `usgs_topo` `*`, TNM row cap |
| `failed` | **0** | — |

Zero `http_404` rows, so the census absences are all 204s, exactly as
§1 item 3 predicted. Zero `suppressed`/`naip_no_point_coverage` — no parcel had
a NAIP year whose selected tiles miss the point, which is the G1 defect and it
did not recur anywhere.

### 6.5 Property, per parcel, with the skip states

| Parcel | Task | coverage | queries_run/failed | rows_returned → matched | events served |
|---|---|---|---|---|---|
| rino | complete | covered | 2 / 0 | 14 → 13 | 14 |
| hudson-yards | complete | covered | 3 / 0 | **100 → 100 (Socrata cap)** | 40 |
| green-valley-ranch | complete | covered | 2 / 0 | 10 → 10 | 10 |
| navy-yard | complete | covered | 8 / 0 | **181 → 53 (ArcGIS cap on sales)** | 128 |
| rodanthe | **skipped** | **no_adapter** | 0 / 0 | — | 0 |
| stapleton | complete | covered | 2 / 0 | 12 → 12 | 12 |
| marshall-sagamore | **skipped** | **no_adapter** | 0 / 0 | — | 0 |
| marshall-louisville | **skipped** | **no_adapter** | 0 / 0 | — | 0 |
| apple-park | **skipped** | **not_covered** | 0 / 0 | — | 0 |
| wharf | complete | covered | 8 / 0 | 6 → 6 | 6 |
| cornell-tech | complete | covered | 3 / 0 | 29 → 29 | 7 |
| silver-creek | complete | covered | 3 / 0 | **4 → 0** | **0** |

**Silver Creek is a live Z4 instance, predicted before the run and observed
exactly.** San Jose's CKAN returns four permits at the address; the H5 matcher
rejects all four. The street line in the record is `'5460  COUNTRY CLUB PY  '`,
`PY` is not in `SUFFIX_MAP` (`address_normalizer.py:13-32`), and the overlap
coefficient on the remaining tokens is 2/3 = **0.667** against a 0.7 threshold
(`address_normalizer.py:153-181`) — one token short. The page shows no property
history; only `rows_returned=4, rows_matched=0` says otherwise. Proposed as
**FV-2**.

**AA5 reproduced and cleared locally.** Rodanthe's served property row before
the sweep was the pre-0014 shape — `skipped`, `coverage` NULL, `items_found`
**0** (`queries/out/state_before.txt`) — which renders as "0 items". After one
full-scope re-run it is `skipped` / `no_adapter` / NULL, which renders as "not
covered". That is AA5's stated remedy ("any full-scope run rewrites a parcel")
observed end to end, locally.

### 6.6 Geometry — the audit method, ported to `scenes` + `parcel_scenes`

`queries/edge_distance.py` reimplements FINDINGS §1's method against the
post-0019 schema: read every served `parcel_scenes` row **plus every tile in
`mosaic_scene_ids`**, refetch the STAC item from Planetary Computer, test
`item["geometry"]` with shapely against the `item["bbox"]` test the pipeline
used to run, and measure the distance to the footprint edge in the point's own
UTM zone. `usgs_topo` is excluded — TNM products, no STAC item — exactly as the
2026-08 audit excluded them.

**794 scene references measured across the twelve parcels: 751 primaries and 43
mosaic tiles. Zero unfetchable** (NORM-23's HTTP-403 class is still gone), and
**zero disagreements** between the footprint stored at selection time and the
one PC serves now.

* **`bbox=Y, geom=N` among primaries: 0.** No residue of the pre-`2039e64`
  defect on any of the twelve, incumbents included.
* **One `bbox=Y, geom=N` overall**, and it is a **mosaic tile**: navy-yard NAIP
  2023 `md_m_3807601_sw_18_030_20230901_20231018`, 16.5 m *outside* the
  footprint. This is not the defect: 19 of the 43 mosaic tiles do not contain
  the point **by design** — the NAIP mosaic adds neighbours for viewport
  coverage and only the group needs a containing tile
  (`stac.py:930-1046`, gate at `timeline.py:567-570`). Recorded so that a
  future re-run of the geometry audit filters to primaries; a naive port
  reports a false residue. Proposed as **FV-10**.

Minimum edge distance per parcel and source, primaries only
(`queries/out/edge_summary.txt`):

| Parcel | Landsat min | <1 km | Sentinel-2 min | <1 km | NAIP min | <200 m |
|---|---|---|---|---|---|---|
| rino | 528.8 m | 2 | 1,436.9 m | 0 | 1,617 m | 0 |
| hudson-yards | 16,183 m | 0 | 20,371 m | 0 | **124.2 m** | 1 |
| green-valley-ranch | 4,067 m | 0 | 13,589 m | 0 | 2,849 m | 0 |
| navy-yard | 32,867 m | 0 | 5,417 m | 0 | 245.4 m | 0 |
| rodanthe | 644.5 m | 2 | 47,765 m | 0 | 2,675 m | 0 |
| stapleton | 251.6 m | 2 | 460.2 m | 2 | 1,612 m | 0 |
| marshall-sagamore | 18,491 m | 0 | 7,207 m | 0 | 1,143 m | 0 |
| marshall-louisville | 19,009 m | 0 | 7,282 m | 0 | 2,164 m | 0 |
| apple-park | 69,694 m | 0 | 22,378 m | 0 | 1,361 m | 0 |
| wharf | 30,806 m | 0 | 7,477 m | 0 | 717.7 m | 0 |
| **cornell-tech** | **11.5 m** | **2** | 16,877 m | 0 | 661.9 m | 0 |
| silver-creek | 925.8 m | 1 | 8,858 m | 0 | 2,150 m | 0 |

**The prediction that no Landsat row would fall under 1 km is falsified on five
parcels**, and one of them is severe: Cornell Tech's Landsat **2017**
(`LC08_L2SP_014031_20171018_02_T1`) sits **11.5 m** inside the footprint edge,
and its **2013** (`LC08_L2SP_014031_20130820_02_T1`) 155.3 m — both WRS-2 path
014 / row 031 scenes whose edge runs across Roosevelt Island. They pass today
and are one granule-geometry revision or reprojection wobble from flipping to
non-covering, which is precisely FINDINGS §5's tail with a named instance.
Stapleton (Landsat 251.6 m, Sentinel-2 460.2 m ×2) and RiNo (Landsat 528.8 m
×2) are the incumbent members of the same tail. Proposed as **FV-7**.

NAIP sub-1-km rows are routine — a quarter-quad is ~6 km, so the meaningful
figure is <200 m, and there is exactly one: hudson-yards 2023 at 124.2 m.

### 6.7 The two source-specific checks the brief asked for

* **CO candidates, NAIP 2023 present and post-fire: confirmed.** Both Marshall
  parcels serve `co_m_3910507_ne_13_030_20230925_20240104`, `capture_date`
  **2023-09-25**, 0.3 m — 21 months after the fire — alongside
  `co_m_3910507_ne_13_060_20210813` (**2021-08-13**, 0.6 m), 4½ months before
  it (`queries/out/scorecard.txt` §9).
* **NY candidates, series ends 2022 and no 2023 card: falsified, twice.** Both
  serve a 2023 card built from `nj_m_4007309_sw_18_030_20230820_20231019`,
  which contains both points (124.2 m and 661.9 m inside the edge). PC holds no
  2024 or 2025 NAIP item for any state in this set, so the newest aerial on any
  of these twelve pages is **2023** (CO, MD/VA, NY) or **2022** (CA, NC).

---

## 7. Noise profile of the run

Counted from the full 57,153-line capture and re-verified against the committed
reduction (`queries/out/run_capture_events.txt`), attributed to a parcel and a
source. **Eleven warning lines in the whole sweep**, and they are all in the
table below.

| Signal | Count | Attribution |
|---|---|---|
| Planetary Computer 429 / signing backoff / `Band signing failed` | **0** | — |
| SAS container-token mints during the sweep | **0** | all signing ran on the three tokens NORM-22's startup mint wrote at **21:48:00Z** (609/632/656 ms), still warm at sweep time |
| STAC year-chunk failures (`failed`/`stac_*`) | **0** | — |
| `STAC search hit its item cap` (NAIP) | **0** | largest pool 49 of 50 (hudson-yards) |
| `TNM query hit its row cap` | **1** | hudson-yards `usgs_topo`, bbox `-74.0175,40.7404,-73.9820,40.7674`, cap 100 → ledger `*` `indeterminate` |
| `Socrata query hit its row cap` | **1** | hudson-yards `property`, `ipu4-2q9a`, cap 100, `where borough='MANHATTAN' AND house__='500' AND upper(street_name) LIKE '%33%'` |
| `ArcGIS query hit its row cap` | **1** | navy-yard `property`, DC sales layer 56, cap **20**, `where upper(PROPERTY_ADDRESS) LIKE '1300 %4%'` |
| `Census API request failed; retrying` | **8** | see below — all recovered on attempt 2 |
| `Census API retry exceeds the request budget` | **0** | — |
| `Census API: no data for tract` (204) | **17** | matches the 17 `absent`/`api_no_data` ledger rows exactly |
| `Admission refused` / admission waits | **0** | 12 requests against a cap of 30 |
| Tracebacks, task failures, `All … queries failed` | **0** | — |

**The eight census retries** are transport failures against `api.census.gov`
(`status=None`, empty error string, i.e. a `_RETRYABLE_TRANSPORT` exception),
each retried once and answered on the second attempt. Census tasks ran two at a
time, so five are attributable exactly by the outcome line that follows and
three by elimination of the concurrent task:

| Time (Z) | Endpoint | Parcel | Outcome after retry |
|---|---|---|---|
| 22:16:09.6 | `/2009/acs/acs5` | marshall-sagamore | 204 → `absent` |
| 22:16:15.3 | `/2000/dec/sf1` | marshall-louisville | data → `ok` |
| 22:16:51.2 | `/2010/dec/sf1` | wharf | data → `ok` (tract 11001010200) |
| 22:16:52.7 | `/2015/acs/acs5` | marshall-louisville | data → `ok` |
| 22:18:00.8 | `/2009/acs/acs5` | rino | data → `ok` (tract 08031001600) |
| 22:18:01.3 | `/2010/dec/sf1` | green-valley-ranch | data → `ok` |
| 22:18:40.1 | `/2000/dec/sf1` | navy-yard | 204 → `absent` |
| 22:19:02.0 | `/2015/acs/acs5` | hudson-yards | data → `ok` (tract 36061009900) |

**Not one of the eight cost a year** — the ledger holds zero `failed` rows
fleet-wide. This is the N2 retry policy (`8a86fad`) doing exactly what M4
occurrence (3) needed and did not have.

**The three cap hits are the interesting noise**, because two of them land on
an incumbent's public page:

* Navy Yard's **sales** query is capped at 20 rows and hit it, with the AA3
  over-broad pattern `'1300 %4%'` (the ordinal strip turns `4TH` into `4`). The
  page's 16 sale events are drawn from a truncated, unordered answer — a sale
  at this address could be absent because it fell outside the 20.
* Hudson Yards' **permits** query returned exactly its 100-row Socrata cap, so
  its 40 permit events are drawn from a truncated pool too.
* Hudson Yards' **topo** search hit TNM's 100-product cap, which is the third
  production-shaped instance of T3's instrument firing (after G6 and the
  2026-08-27 sweep). Its nine decades are intact; the ledger says only that a
  tenth cannot be ruled out.

---

## 8. Recommendation

### 8.1 Per candidate

**Marshall Fire — Sagamore, Superior (`333 Fox Ln`): featured-ready, one
caveat.**
Deciding evidence: all six data sources complete on the first run; 43 Landsat /
12 Sentinel-2 / 7 NAIP / 5 topo / 7 census; NAIP 2021-08-13 and 2023-09-25
bracket the fire; 153 destroyed structures within 250 m and **not one
surviving** within 500 m; 658 m inside the WFIGS perimeter so the whole default
frame is inside the burn; minimum edge distances 18.5 km (Landsat), 7.2 km
(S2), 1.1 km (NAIP) — the safest geometry of any candidate. Caveat: Boulder has
no adapter, so the property panel shows the explicit "not covered" state, and
the census series starts at 2010 (decennial 2000 and acs5 2009 absent because
the tract was split in 2020).

**Silver Creek Valley, San Jose (`5460 Country Club Pkwy`) — proposed
alternative: featured-ready with a caveat.**
Deciding evidence: in San Jose's jurisdiction (the gate says `covered`);
LCMAP +51 points into Developed within ±500 m, the same magnitude as Green
Valley Ranch (+46) and Stapleton (+62); 43/12/6/6/7 with clean geometry
(minimum Landsat edge 925.8 m, NAIP 2.2 km). Caveat: the property panel will be
empty even though four permits exist, because the matcher rejects `COUNTRY CLUB
PY` at 0.667 (FV-2, a one-token fix). Second caveat: it is not a famous place.

**Cornell Tech, Roosevelt Island (`2 W Loop Rd`): ready with two caveats.**
Deciding evidence: 43/12/9/8/7 all complete; the richest property record of any
candidate and the right one — 7 DOB permit events spanning 2015-05-05 to
2019-05-08, the campus's construction; a 2023 NAIP card (a legitimate,
point-covering NJ-program quad). Caveats: (a) **the Landsat edge tail** — 2017
at 11.5 m and 2013 at 155.3 m inside a WRS-2 footprint edge, the thinnest
margin measured anywhere in this batch; (b) the seed script cannot geocode
`2 W Loop Rd` at all (Census has no match; Main Street addresses on the island
do match). Archetype overlap: NYC and the 2010s, both already carried by Hudson
Yards.

**The Wharf / Southwest Waterfront (`760 Maine Ave SW`): featured-ready, and
the cleanest data of the four — but it duplicates an incumbent.**
Deciding evidence: 43/12/10/6/7, six matched permits, zero cap hits, zero
warnings of any kind, minimum NAIP edge 717 m, Landsat 30.8 km. Its NAIP series
(2011–2018, 2021, 2023) covers the build directly. Two limits: DC's permit
layers start at 2020, so the construction-era record (2014–2017) is
unreachable, and the archetype — DC waterfront industrial-to-mixed-use
redevelopment — is Navy Yard's, two miles away.

**Apple Park (`1 Apple Park Way`): not ready.**
Deciding evidence: (a) the seed path cannot create it — the Census forward
geocoder has no match for either address form, and `seed_featured.py` has no
fallback, so seeding it today is a 422; (b) it is out of jurisdiction — Santa
Clara's adapter is San Jose's portal, which holds zero rows for any Apple Park
query, so the property panel is permanently the "not covered" state; (c) the
point the UI path resolves to is a **road**, not a property; (d) the change is
not a land-cover change — LCMAP reads 99 % Developed in 1985 and 92 % in 2021,
so "visible at every resolution" holds at NAIP's 0.6 m and as a shape at
Landsat's 30 m, but not as the kind of change the other pages tell. Imagery
itself is clean (43/12/6/9/9, all sources complete, no geometry flags).

### 8.2 Ranked pick of two

1. **Marshall Fire — Sagamore.** It adds the archetype the set is missing
   entirely: sudden loss, then rebuild, in a place where the before/after is
   two NAIP flights 25 months apart. Nothing in the current six is a disaster
   story, and no other candidate adds an archetype the set lacks outright.
2. **Silver Creek Valley, San Jose.** It fills the slot Apple Park was chosen
   for — a new state and a West Coast story — while being in jurisdiction, and
   it is the only candidate whose change is *measured* as Landsat-legible at
   the same magnitude as the incumbents' greenfield pages. Take it in
   preference to Apple Park, not alongside it.

Ranked below those: **Cornell Tech** third (a genuinely distinct archetype —
an institution built on a cleared hospital site on an island — held back by an
11.5 m Landsat margin and an address the seed script cannot geocode), **The
Wharf** fourth (best data, weakest spread), **Apple Park** fifth (not ready).

If only one slot is filled this round, fill it with Marshall.

### 8.3 Is any incumbent in worse shape than a candidate? Yes — three

* **Rodanthe is the thinnest page in the set**, and thinner than both bench
  candidates: no property adapter (Dare County), **3** topo decades against a
  set median of 7, 6 NAIP years, 7 census years. Its imagery is otherwise
  clean and G2's wrong Sentinel-2 card is gone.
* **Hudson Yards carries two truncations that the candidates do not**: its
  permit pool hit the Socrata 100-row cap, and its topo search hit TNM's cap
  and left an `indeterminate` whole-source ledger row — the only
  `indeterminate` in the batch.
* **Navy Yard's sales query hit the ArcGIS 20-row cap** with an over-broad
  pattern, so its 16 sale events come from a truncated answer.

And one copy defect on the demo surface: `scripts/seed_featured.py:56-61` tells
Green Valley Ranch visitors there is "Census data back to 2000 on the
population growth". Decennial 2000 is `absent`/`api_no_data` for that tract;
the page's earliest census year is **2010**. Same shape as T6's NAIP-2003
correction, on the row below it.

---

## 9. STATUS.md rows proposed

Not written by me — listed here for the owner to fold in with the decision.
Each is new unless it says otherwise.

| Proposed | Where it belongs | Row |
|---|---|---|
| **FV-1** | property / adapters | **The NYC sales query cannot match any address carrying a directional.** `NewYorkCountyAdapter.fetch_sales` builds `upper(address) LIKE '%{house} {street}%'` (`county_adapters.py:781`) while `extract_search_terms` strips the directional and the ordinal suffix, so "450 W 33rd St" is asked as `'%450 33%'`. Live on `w2pb-icbu`, borough 1: `'%450 WEST 33%'` → 1 row, `'%450 33%'` → 0. Latent for Hudson Yards and Cornell Tech (neither address has a sale record) and live for any Manhattan address that does. AA3 named the *breadth* of the ordinal strip; this is the *miss* on the other side. Unfixed. |
| **FV-2** | property / matcher | **`PY` is missing from `SUFFIX_MAP`, and a three-token street name lands 0.033 short of the threshold.** San Jose CKAN returns 4 permits for `5460 COUNTRY CLUB PKWY` as `'5460  COUNTRY CLUB PY  '`; the H5 overlap is 2/3 = 0.667 against 0.7, so all four are rejected and the task reads `complete` with `rows_returned=4, rows_matched=0`. A live Z4 instance, on a candidate parcel. One-token fix; the arithmetic is the finding. |
| **FV-3** | property / caps | **DC's sales layer hit its 20-row cap on a featured page.** Navy Yard, `where upper(PROPERTY_ADDRESS) LIKE '1300 %4%'`, cap 20, warning at 22:18:09Z. Third cap-hit instance after G6 and the 2026-08-27 sweep; unlike those, this one is on a public demo page and the truncated source is *sales*, whose ordering is unspecified. |
| **FV-4** | topo / T3 | **Hudson Yards' TNM search hit the 100-product cap and its ledger now carries `usgs_topo` `*` `indeterminate`.** The nine served decades are unchanged; the row says a tenth cannot be ruled out. T3's bet keeps paying: this is a cap hit on the flagship surface. |
| **FV-5** | featured / seeding | **The seed path is Census-only, so a featured address the Census geocoder cannot match cannot be seeded at all.** `seed_featured.py:134` posts no coordinates; `POST /geocode` 422s; the loop prints `FAILED (422)` and continues. Both `1 Apple Park Way, Cupertino` and `2 W Loop Rd, New York` are in that state today. Product decision: change the seed path, or pick addresses TIGER carries. |
| **FV-6** | copy / T6 | **The seeded Green Valley Ranch blurb claims census data back to 2000; the page's earliest census year is 2010.** `seed_featured.py:56-61`. Decennial 2000 is `absent`/`api_no_data` for tract 08031008388 — and for 10 of the 12 parcels measured. Same shape as T6, one dataset over. |
| **FV-7** | geometry / FINDINGS §5 | **Named instance of the edge tail: Cornell Tech Landsat 2017 sits 11.5 m inside its footprint edge** (`LC08_L2SP_014031_20171018_02_T1`), 2013 at 155.3 m. Stapleton (Landsat 251.6 m, S2 460.2 m) and RiNo (528.8 m) are the incumbent members. Nothing to fix; it is a selection criterion for new featured pages. |
| **FV-8** | census | **decennial 2000 is absent on 10 of 12 vetted parcels, from one cause.** `_GEOGRAPHY_VINTAGES` has no decennial-2000 entry, so the 2020-vintage tract is asked of `2000/dec/sf1`. Confirms, on a fresh population, the item already under *To investigate* ("Decennial 2000 has no geocoder vintage"); the two parcels that do serve 2000 are the two whose tract has not changed since 2000. |
| **FV-9** | property / AA5 | **AA5's remedy is confirmed end to end, locally.** Rodanthe's served property row went from the pre-0014 shape (`skipped`, coverage NULL, `items_found` 0 → renders "0 items") to `skipped`/`no_adapter`/NULL (renders "not covered") after one full-scope re-run — "any full-scope run rewrites a parcel", observed. |
| **FV-10** | geometry / method | **A post-0019 geometry audit must filter to primary scenes.** 19 of 43 NAIP mosaic tiles do not contain the parcel point *by design*, and one of them is `bbox=Y, geom=N` (navy-yard 2023 `md_m_3807601_sw…`, 16.5 m outside). A naive port of FINDINGS §1's method to `parcel_scenes` + `mosaic_scene_ids` reports that as defect residue. Primaries: 751 measured, **zero** `bbox=Y, geom=N`, zero non-containing. |

Nothing in this batch makes an existing STATUS.md row false. G1, G2, O6 and M4
are all confirmed in the state their rows describe; AA2/AA4's Cupertino
observations are extended, not contradicted (the point here parses to a real
city, so the gate denies rather than failing open).

---

## 10. Files

| File | What it is |
|---|---|
| `PREDICTION.md` | the pre-run prediction, committed at `ba8bb04`, unedited |
| `queries/marshall_points.py` | Boulder County damage layer + WFIGS perimeter; neighbourhood ranking and per-point destruction density |
| `queries/geocode_probe.py` | Census forward geocode, Photon autocomplete, vintage tracts, property-gate preview, per address |
| `queries/census_match_batch.py` | which address strings the Census forward geocoder (the seed path) matches |
| `queries/predict_sources.py` | per-point NAIP / topo / census expectations read from upstream |
| `queries/property_probe.py` | read-only replay of `_fetch_property` through the real adapters |
| `queries/lcmap_change.py` | LCMAP land-cover shares 1985 / 2001 / 2021 around a point, via local Titiler |
| `queries/edge_distance.py` | the geometry audit's method, ported to `scenes` + `parcel_scenes` |
| `queries/state_snapshot.sql` | before/after database state |
| `queries/scorecard.sql` | the scoring queries behind §6 |
| `queries/out/*` | the raw output of every one of the above, including `run_capture_events.txt` (the sweep's structured log events) and `scorecard.txt` |

Re-running the check after a future heal: `state_snapshot.sql`, then the sweep,
then `scorecard.sql` and `edge_distance.py db <parcel ids>`. The parcel ids are
in `scorecard.sql`'s `v_labels` view.
