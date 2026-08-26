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

Commit `e6afa9b`, three files of code and three of tests. Committed, **not
deployed**; nothing below is running in production yet.

### 5.1 An HTTP error stops reading as an absence

`backend/app/services/census.py`:

* New `CensusHttpStatusError(CensusApiError)` (`census.py:150-166`) carrying
  `status_code` and the dataset `path`.
* `_request` (`census.py:330-347`): `if resp.status_code in (204, 404)` becomes
  `== 204`. Every other non-200 — 404 included — raises
  `CensusHttpStatusError(status, _dataset_path(url))`. `_dataset_path`
  (`census.py:375-380`) strips `BASE_URL` and never touches the query string,
  which is where the key is.

`backend/app/tasks/timeline.py`: `_census_failure_reason` (`:176-177`) returns
`f"http_{exc.status_code}"` for that class, ahead of the `__cause__` walk that
separates timeouts from transport errors.

`backend/app/services/year_ledger.py`: `failed` now also accepts
`http_<status>` (`_HTTP_REASON_RE`, `year_ledger.py:100-106`, checked in
`_validate` at `:143`). A family rather than an enumeration, and the comment
says why: the statuses an upstream can return are not ours to enumerate, and
what matters is that the status is *in* the reason.

The ledger `detail` is `str(exc)` as before, which now reads
`Census API returned 404 for /1990/dec/sf1`.

### 5.2 Decennial 1990 is not attempted

`DECENNIAL_YEARS` is `[2000, 2010, 2020]` (`census.py:91`), and
`_DECENNIAL_CONFIGS[1990]` is gone, replaced by a comment at the same site
naming what §2 established and where 1990 actually lives — NHGIS or
`www2.census.gov/census_1990/`, a download, so it returns with the census
tabular ingest pass, not by re-adding a config. The module docstring's
"Decennial Census (1990–2020)" is corrected to 2000. The `_GEOGRAPHY_VINTAGES`
comment, which explained why 1990 and 2000 are unmapped, now explains only
2000 and names the one parcel it costs.

### 5.3 Decennial 2000 asks for the tract the dataset addresses

A `"trim_empty_tract_suffix": True` flag on the 2000 config entry
(`census.py:42-59`, the flag itself at `:54`), applied by `_tract_for_dataset` (`census.py:360-372`),
called once in `fetch_decennial` (`census.py:248`). Six characters ending in
`00` become four; everything else is passed through untouched, including a
real suffix — trimming one would ask for a coarser geography and label the
answer with the parcel's tract.

Per-dataset by construction: 2010 and 2020 carry no flag, so their requests
are byte-identical to before.

---

## 6. Tests

529 passing, 2 skipped. **5 added, 2 rewritten in place** (523 → 524 in the
Racebrook batch, 524 → 529 here).

| test | file | what only it can catch |
|---|---|---|
| `test_fetch_raises_on_404` *(rewritten from `test_fetch_returns_empty_on_404`)* | `test_census.py` | 404 raising with status and path, and the key not riding along |
| `test_request_raises_on_unexpected_status` *(extended)* | `test_census.py` | a 500 carrying the dataset path, not the key |
| `test_decennial_2000_asks_for_the_four_character_tract` | `test_census.py` | the trim fires — asserts the literal `for=tract:0025` |
| `test_decennial_2000_keeps_a_real_tract_suffix` | `test_census.py` | the trim does **not** fire on `009903` |
| `test_decennial_2010_pads_every_tract_to_six` | `test_census.py` | the trim is per-dataset |
| `test_1990_is_not_attempted` | `test_census.py` | 1990 out of both the year list and the config map |
| `test_census_http_404_is_failed_http_404` | `test_year_ledger.py` | end-to-end: a real `CensusFetcher` over a mocked transport, all nine groups reading `failed`/`http_404` with the dataset path in `detail` |

`test_fetch_census_uses_county_tract_before_planning_regions`
(`test_timeline.py`) is the second rewrite: its 1990-and-2000 assertion
becomes a 2000 assertion plus `("decennial", 1990) not in asked`.

### 6.1 Delete-the-fix, five reversions, each run and observed

| reverted | result |
|---|---|
| `== 204` back to `in (204, 404)` | 2 failed — `test_fetch_raises_on_404`, `test_census_http_404_is_failed_http_404` |
| `_tract_for_dataset(...)` back to `tract_code` | 1 failed — `test_decennial_2000_asks_for_the_four_character_tract` |
| `_DECENNIAL_CONFIGS[1990]` and `DECENNIAL_YEARS` restored | 2 failed — `test_1990_is_not_attempted`, `test_fetch_census_uses_county_tract_before_planning_regions` |
| the `isinstance(exc, CensusHttpStatusError)` branch removed | 1 failed — the ledger test, on `other` instead of `http_404` |
| the ledger's `http_` allowance removed | 1 failed — the ledger test, on the vocabulary error |

Restored after each; the suite is green at 529.

---

## 7. Test and lint results

Docker is not running on this workstation, so the suite ran under
`backend/.venv` rather than `make test`'s `docker compose exec api pytest` —
same interpreter (3.12), same `tests/conftest.py` SQLite harness.

```
$ .venv/bin/python -m pytest tests/ -q
529 passed, 2 skipped, 2 warnings in 6.84s

$ .venv/bin/python -m ruff check app/ tests/
All checks passed!

$ .venv/bin/python -m ruff format --check app/ tests/
72 files already formatted

$ .venv/bin/python -m mypy app/
Success: no issues found in 47 source files
```

---

## 8. Deviations from the brief

1. **The fleet is 186 parcels, not 184.** Every count in this report is over
   186; the brief's 184 is the M4 sweep's number. Two parcels were added
   since, and no claim here depends on which.
2. **Item 1 asked what the API's *docs* say the tract format is; the docs do
   not say.** `geography.json` gives `tract` a level and its required
   parents and no width, and `examples.json` carries no tract example (§1.4).
   The evidence used instead is the dataset's own tract inventory over 3,088
   tracts — the API answering the question directly rather than describing
   it. The underlying Census 2000 "basic code + suffix" convention is named
   in §9 as UNVERIFIED, because the primary technical documentation was not
   fetched and the fix does not rest on it.
3. **Item 5's stop condition was "CT-specific or inconclusive → do not fix".**
   Neither held — the rule is mechanical and universal — so the fix landed.
4. **Racebrook still does not get decennial 2000, and the reason is not the
   width.** Its stored county is a planning region. Recovering it needs a
   `("decennial", 2000)` vintage entry, which is a fleet-wide behaviour
   change to recover one parcel; not done, recorded in STATUS.md under To
   investigate with the argument for and against.
5. **One finding outside the census path.** §4's grep found `socrata.py`'s
   404 → `[]`. Out of scope, unfixed, in STATUS.md.
6. **`census.py`'s module docstring was edited despite item 2's "do not edit
   copy".** It is the code's own claim, not product copy, and leaving a
   docstring saying 1990–2020 next to a config that no longer has 1990 would
   be a new false statement. Every user-facing string in §3 is untouched.

---

## 9. UNVERIFIED

- **That the Census 2000 "basic code + optional two-digit suffix" convention
  is documented as such by the Bureau.** The behaviour is measured over 3,088
  tracts in 8 states and the two widths partition cleanly, but the primary
  technical documentation (Census 2000 SF1, Appendix A geographic terms) was
  not fetched. If it turns out the rule has an exception somewhere, the
  falsifier is a `2000/dec/sf1` tract code that is six characters and ends in
  `00`; none exists in the sample.
- **That the 64 recoverable parcels are still 64 when the sweep runs.** They
  were probed live on 2026-08-26 against tracts stored in production that
  day. A parcel re-geocoded between now and the sweep could change its stored
  tract.
- **The acs5 2009 ride-along's fleet-wide size.** 74 parcels have no 2009 row;
  how many the `Census2010_Current` mapping recovers was never measured, here
  or in the Racebrook pass. P9 predicts a range and a floor, not a number.
- **That no non-census upstream is currently returning a 4xx/5xx that reads as
  absence in the ledger.** §4 establishes that no other *client* has the
  collapse in its code. It does not establish that production is quiet — the
  first sweep under `e6afa9b` is what would show a `failed`/`http_*` row.
- **That 1990 tract-level data on NHGIS matches what this product would want.**
  Named as where 1990 lives; not evaluated for coverage, variables, or
  licensing. That is the ingest pass's problem.

---

## 10. Addendum, 2026-08-26 — the copy batch itself

§3's inventory closed. Re-grepped `1990` across `README.md`, `scripts/`,
`frontend/src`, `docs/posts/`, `DEVELOPMENT.md` (leaving `docs/audits/`
untouched, per the audit norm). No new hits beyond §3's list — the only
remaining `1990` occurrences are Landsat claims (`README.md:34`,
`scripts/revalidate_landsat.py:4`, `scripts/seed_featured.py:101`, and
`frontend/src/test/fixtures/*`), all true (Landsat reaches 1984) and out of
scope.

Six lines corrected, one commit:

| file:line | before | after |
|---|---|---|
| `README.md:17` | "Census demographic data across **four decades**" | "Census demographic data **back to 2000**" |
| `README.md:28` | Green Valley Ranch: "**four decades** of Census data" | "Census data **back to 2000**" |
| `README.md:81` | data-source table: "Nationwide, **1990–2023**" | "Nationwide, **2000–2023**" |
| `README.md:205` | "the **1990 data** may represent a much larger geographic area" | "the **2000 data** may represent a much larger geographic area" |
| `README.md:207` | "A median income of $40,000 **in 1990**" | "A median income of $40,000 **in 2009**" (median income is ACS-only; the decennial config never requested it, and the ACS floor is 2009 — §3's "doubly false" note) |
| `scripts/seed_featured.py:59` | Green Valley Ranch `description`: "alongside **four decades** of Census data" | "alongside Census data **back to 2000**" |

`census.py`'s docstring already read "Decennial Census (2000–2020)" — corrected
in `e6afa9b`, per §3's note that it is code's own claim, not product copy.

**Prod comparison, read-only (`fly ssh console -a log0s-plotline-api -C`,
2026-08-26).** `featured_locations` row for `green-valley-ranch`:

    ('green-valley-ranch', 'The area east of Denver near E-470 was open
    prairie and farmland in the early 2000s. NAIP imagery shows the rapid
    development of subdivisions, schools, and commercial centers that now
    house tens of thousands.')

This is the T6 NAIP-only text, not `seed_featured.py`'s current description
(which now reads "...alongside Census data back to 2000..."). §3's deviation
note holds: the two differ, and per the brief this is not reconciled here —
prod carries no false "four decades" claim today, and would only pick one up
if `seed_featured.py` were run against it.

**Item 4's guard.** No existing test asserted README/blurb copy against
config — the NAIP correction (T6) did not add one. Added
`test_readme_decennial_floor_matches_config` in `backend/tests/test_census.py`,
asserting `f"Nationwide, {min(DECENNIAL_YEARS)}–2023"` appears in `README.md`
and that no line combining "1990" with "census" (case-insensitive) survives.
Delete-the-fix: run against README.md before this batch's edits (`git stash`),
the table-line assertion fails and both `1990`+`census` lines are caught. The
test `pytest.skip`s if `README.md` isn't present — true inside the `api`
container, which mounts only `backend/` — but runs for real in CI, which
checks out the full repo before `cd backend && uv run pytest`.

STATUS.md: the "user-facing 1990 claim" row → resolved, this commit.
