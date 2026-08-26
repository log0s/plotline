# Census decennial: the 1990 endpoint, the 2000 tract width, and the reason split

**Date:** 2026-08-26
**Mode:** investigate, then fix — items 1 and 2 are measurement, items 3-5 act on it.
**Production:** read-only, `fly ssh console -a log0s-plotline-api -C`, `SELECT` only.
Live Census API calls are unauthenticated-read `GET`s against `api.census.gov`,
keyed, paced at 0.5-0.6 s.

---

## 0. Headline

1. **Decennial 2000's tract-width mismatch is fleet-wide and mechanical, not a
   Connecticut quirk.** `2000/dec/sf1` addresses a census tract by its *basic
   code plus a real suffix* — four characters when the tract has no suffix, six
   when it does. Our six-character form 204s on every no-suffix tract. In the
   ledger the split is perfect: all 47 parcels whose decennial 2000 reads `ok`
   have a tract that does **not** end in `00`; all 80 parcels whose tract **does**
   end in `00` read `absent`. Under the four-character form, **64 of those 80
   answer 200 today**. Fixed (§5.3).
2. **Decennial 1990 does not exist on `api.census.gov` — confirmed from the
   discovery endpoint, not just from a 404.** `api.census.gov/data.json` lists
   1,798 datasets; `dec/*` appears at vintages **2000, 2010 and 2020 only**, and
   the 36 datasets at vintage 1990 are CPS, CBP, PEP and SIPP. Removed from the
   attempted set (§5.2). The user-facing "1990" claims are inventoried in §3 and
   **not edited here** — that is the separate copy batch.
3. **An HTTP error can no longer read as data absence.** `_request` mapped 404
   to `None` to `{}` to `absent`/`api_no_data`, which is how a dead endpoint
   spent months in the ledger as "the tract has no data". 4xx/5xx now raise a
   status-carrying error and land as `failed`/`http_<status>` (§5.1).

---

## 1. Decennial 2000 blast radius

### 1.1 The ledger, all 186 parcels

Latest per-`(parcel, source, group_key)` outcome, ranked by the timeline
request's `created_at` — the `ledger_gaps.py` query, restricted to
`source LIKE 'census%'`. The fleet is **186** parcels, not the 184 of the M4
sweep; two were added since.

| source | year | `ok` | `absent` / `api_no_data` | `failed` |
|---|---|---:|---:|---:|
| `census_decennial` | 1990 | 0 | **186** | 0 |
| `census_decennial` | 2000 | 47 | **139** | 0 |
| `census_decennial` | 2010 | 186 | 0 | 0 |
| `census_decennial` | 2020 | 186 | 0 | 0 |
| `census_acs5` | 2009 | 112 | 74 | 0 |
| `census_acs5` | 2012/2015/2018/2021/2023 | 186 each | 0 | 0 |

`census_snapshots` agrees row for row: `decennial 2000` holds 47 rows,
`decennial 1990` holds **none, ever**.

So decennial 2000 is **not** CT-only — 139 of 186 parcels, across 34 states.
The decennial floor in production is 2010 for 139 parcels and 2000 for 47.

### 1.2 The split is exactly "does the stored tract end in `00`"

Cross-tabulating that outcome against the parcel's stored `census_tract_id`:

| | tract ends `00` | tract does not |
|---|---:|---:|
| `ok` | **0** | 47 |
| `absent` | **80** | 59 |

No exceptions in either direction. The 80 span **27 states** (06 ×7, 08 ×6,
09 ×1, 11 ×3, 12 ×2, 13 ×3, 17 ×5, 19, 24, 25 ×2, 26 ×6, 27 ×2, 29, 31 ×2,
33 ×2, 34 ×6, 36 ×11, 39, 41 ×5, 42, 47, 48 ×2, 49, 50, 51 ×2, 53 ×4, 55).

The 59 `absent` tracts that do not end in `00` are a different thing — a tract
with a real suffix that did not exist in 2000. `36061009903` is one:
`tract:009903` 204s, and `tract:0099` returns 200 with a *different, larger*
geography (the 2000 parent). The fix below deliberately cannot reach those, and
must not: trimming a real suffix would silently substitute a parent tract.

### 1.3 Live API, both tract forms

`GET https://api.census.gov/data/2000/dec/sf1?get=P001001,H001001&for=tract:<t>&in=state:<s> county:<c>`

| parcel state / county | stored tract | six-digit form | four-digit form |
|---|---|---|---|
| CA, Sacramento 06067 | `000400` | **204** | **200** — P 3909, H 2355 |
| CO, Mesa 08077 | `000200` | **204** | **200** — P 2221, H 1238 |
| GA, Fulton 13121 | `002500` | **204** | **200** — P 1981, H 988 |
| NY, Kings 36047 | `019500` | **204** | **200** — P 3821, H 1927 |
| WA, Chelan 53007 | `960700` | **204** | **200** — P 2734, H 1045 |
| CT, New Haven 09009 | `157100` | **204** | **200** — P 2207, H 891 |

Five states plus the Connecticut case the Racebrook investigation found. The
six-digit form 204s everywhere; the four-digit form answers everywhere.

### 1.4 What format the dataset expects, from the API itself

`api.census.gov/data/2000/dec/sf1/geography.json` describes `tract` only as
`geoLevelDisplay: "140"`, `requires: [state, county]` — it states no width, and
`examples.json` carries no tract example. The API's operative answer is its own
tract inventory, `for=tract:*&in=state:<s> county:<c>`:

| county | tracts | 4-char | 6-char | 6-char ending `00` | 4-char+`00` colliding with a 6-char |
|---|---:|---:|---:|---:|---:|
| CA 06067 | 279 | 55 | 224 | 0 | 0 |
| CO 08031 | 136 | 18 | 118 | 0 | 0 |
| CT 09009 | 186 | 158 | 28 | 0 | 0 |
| GA 13121 | 167 | 83 | 84 | 0 | 0 |
| NY 36047 | 783 | 728 | 55 | 0 | 0 |
| WA 53007 | 12 | 12 | 0 | 0 | 0 |
| TX 48453 | 181 | 5 | 176 | 0 | 0 |
| IL 17031 | 1,344 | 1,082 | 262 | 0 | 0 |

3,088 tracts, 8 counties, 8 states. **No six-character code in `2000/dec/sf1`
ends in `00`**, and no four-character code padded with `00` collides with a
six-character one. The two widths partition the space. Control: the same
counties on `2010/dec/sf1` return **only** six-character codes, 45/22/155/74 of
them ending in `00`.

That is the whole rule, and it is universal rather than CT-specific: **the 2000
dataset carries the tract's basic code and omits an empty two-digit suffix; 2010
and 2020 pad it to six.** Dropping a trailing `00` for `2000/dec/sf1` is a
re-encoding of the same tract, not a fallback to a coarser one.

### 1.5 What the fix recovers

All 80 ends-in-`00` parcels, asked live under the four-digit form:
**64 return 200, 16 return 204.** The 16 are genuinely not in the 2000 vintage
under that code:

`08031015300`, `09170157100`, `11001980000` (×3 parcels), `17031839100`,
`17031980000`, `26019000500`, `26061000800`, `29147470400`, `34023009300` (×2),
`36121970700`, `48453032600`, `53035940000`, `55079187300`.

`09170157100` — Racebrook — is 204 for a *second* reason, not the width: its
stored county is the **planning region** `170`, which no decennial vintage
knows. Its four-digit tract `1571` answers under county `009` (§1.3) and would
need a `("decennial", 2000)` entry in `_GEOGRAPHY_VINTAGES` to be asked that
way. Not done here; see §6 deviation 2.

---

## 2. Decennial 1990 does not exist

`api.census.gov/data.json`, the full discovery endpoint, 1,798 datasets:

* datasets at `c_vintage: 1990` — **36**, and every one is `cbp`, `cps/basic/*`,
  `pep/int_*` or `sipp/*`. **No `dec/*`.**
* vintages carrying any `dec/*` dataset — **`[2000, 2010, 2020]`**.
* vintages carrying `dec/sf1` specifically — **`[2000, 2010]`**.

`api.census.gov/data/1990.json` returns the same 36 datasets. Direct requests:
`https://api.census.gov/data/1990/dec/sf1` → **404**;
`.../1990/dec/sf1.json` → **404**.

`_DECENNIAL_CONFIGS[1990]` named an endpoint that has never resolved. Every one
of the 186 `absent`/`api_no_data` rows for it is a 404 wearing an absence
label — the exact collapse §5.1 closes.

1990 tract-level decennial data is published, but as downloads, not on this API:
NHGIS (`nhgis.org`) redistributes STF1/STF3 at tract level, and the Census's own
`www2.census.gov/census_1990/` FTP tree carries the raw STF files. Both are an
ingest, not a call.

---

## 3. Inventory of user-facing "1990" claims — reported, not edited

Per the brief, the copy batch is separate (as the NAIP 2003→2010 correction
was). Nothing in this list is touched by this pass.

| file:line | text | status |
|---|---|---|
| `README.md:81` | data-source table: US Census Bureau, "Nationwide, **1990–2023**" | **false** — decennial floor is 2000, and 2000 only reaches 64 more parcels after this fix |
| `README.md:205` | "the **1990 data** may represent a much larger geographic area than the 2020 data" | **false premise** — no 1990 data exists or ever did |
| `README.md:207` | "A median income of $40,000 **in 1990** is not directly comparable to $75,000 in 2023" | **false premise** — median income is an ACS variable; the decennial config never requested it, and the ACS floor is 2009 |
| `README.md:17` | "Census demographic data across **four decades**" | **false** — three (2000, 2010, 2020) plus ACS 2009-2023 |
| `README.md:28` | Green Valley Ranch blurb: "**four decades** of Census data" | **false**, same count |
| `scripts/seed_featured.py:59` | Green Valley Ranch `description`: "alongside **four decades** of Census data on the population growth" | **false**, same count |
| `backend/app/services/census.py:3` | module docstring, "Decennial Census (**1990**–2020)" | internal, **corrected in this batch** (§5.2) — it is the code's own claim, not product copy |

Checked and **clean**:

* **Frontend copy** — no year-range or decade-count claim anywhere in
  `frontend/src`. `grep -n "1990"` over `frontend/src` outside tests and
  fixtures: zero hits. The only census-adjacent copy is
  `DemographicsPanel.tsx:151` ("Census data unavailable — we'll retry on your
  next visit") and `chart-utils.tsx:7` (tract-break note), neither of which
  names a year.
* **`DEVELOPMENT.md`** — `grep -n "1990"`: zero hits.
* **MCP tool-description draft** — not committed. `grep -rl` for `MCP` across
  the repo finds only `docs/adr/0001-imagery-normalization.md`, which is about
  imagery normalization, not census years. Nothing to inventory.
* **`prompts/PHASE_3_PROMPT.md`** — names 1990 in nine places, but it is a
  frozen build-era spec, not user-facing, and the audit trail does not edit it.

**Production `featured_locations`, read-only (6 rows).** Only one row names a
year in the 1990s: Hudson Yards, *"Landsat imagery from the 1990s shows bare
tracks"* — a **Landsat** claim, true (Landsat reaches 1984), not a census claim.
**Deviation worth recording:** the deployed Green Valley Ranch `description`
does *not* contain the seed script's "four decades of Census data" sentence —
the prod row still carries the older NAIP-only text. The false claim is in
`scripts/seed_featured.py`, and would reach production the next time that
script is run.

---

## 4. Grep for the shape: does anything else read an HTTP error as absence?

`_request`'s `if resp.status_code in (204, 404): return None` is the shape.
Every other outbound client was checked:

| site | 4xx/5xx handling | verdict |
|---|---|---|
| `usgs_topo.py:106` (TNM search) | `resp.raise_for_status()` — propagates to `_fetch_usgs_topo`, which marks the task **`failed`** | **clean** — the collapse does not exist here |
| `arcgis.py:73-78` | non-200 → `ArcGISError` | clean |
| `ckan.py:73-83` | non-200 → `CKANError` | clean |
| `stac.py:1120-1127` | `>= 400` → asset treated as broken, walk continues, ledger records the period | clean — a status, not an absence |
| `geocoder.py:131,195` | status carried into the error message | clean |
| **`socrata.py:73-78`** | **404 → `return []`** | **same shape.** A 404 means the dataset id is wrong or the resource was removed — a failure — and it becomes "this county has no property records" |

The Socrata one is a real instance of the pattern, in the **property** path.
It does not reach the ledger (property has no ledger source; the M4 sweep's
sources are `census_*`, `landsat`, `sentinel2`, `naip`, `topo`), so it is not
fixed here — out of this brief's scope. Recorded in STATUS.md as newly
discovered, per engineering norm 3.

---

## 5. What changed

*(Written with the fix; the code commit follows this one. §5-§8 are appended in
the docs commit so that the report file matches the code that landed.)*
