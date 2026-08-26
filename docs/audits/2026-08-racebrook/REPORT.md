# Racebrook Rd (`2f1b332e`) — Connecticut tract vintage resolution

**Date:** 2026-08-25 · **Base:** `df9f3ed` · **Mode:** investigate, then fix
· **Parcel:** `2f1b332e-2b96-401c-bba6-ce89e134dbf3`, Racebrook Road, Orange,
Connecticut 06477 · **Stored tract:** `09170157100` · **Point:**
41.2690529, -72.9999675

All Census API and Census geocoder results below were fetched live this
session (read-only `GET`, keyed) from this workstation. Production was read
via `fly ssh console -a log0s-plotline-api -C`, `SELECT` only.

---

## 0. Headline

The premise holds and the fix is smaller than the brief assumed.

The Census API knows Racebrook's tract under `09009157100` for every vintage
that predates Connecticut's 2022 county-equivalent change, and under
`09170157100` from ACS 2022 onward. **The Census geocoder already knows this**:
resolving the parcel's point at `Census2020_Current` or `ACS2021_Current`
returns `09009157100`, and at `ACS2022_Current`/`ACS2023_Current` returns
`09170157100`. No crosswalk file, no prefix rule and no Connecticut special
case is needed. The defect is that five of our ten `(dataset, year)` pairs have
**no vintage mapping at all** and therefore fall back to the parcel's stored
current-vintage tract — which, for a Connecticut parcel, is the planning-region
one. The fix is to give every year the vintage it is published on
(`census.py:86`).

Of Racebrook's five missing years, that recovers **three**, not five:

| year | recovered? | why |
|---|---|---|
| acs5 2009 | **yes** | `09009157100` returns 2757 |
| acs5 2021 | **yes** | `09009157100` returns 2453 |
| decennial 2020 | **yes** | `09009157100` returns 2604 |
| decennial 2000 | no | `2000/dec/sf1` addresses Connecticut tracts as `1571`, not `157100` — a different defect, found here, §4.2 |
| decennial 1990 | no | there is no 1990 decennial dataset on `api.census.gov` at all — §4.3 |

Neither of the two is a re-failure and neither is caused by the county code.
Both are recorded as new findings rather than silently folded into "absent".

---

## 1. How `tract_for` resolves today

### 1.1 The path

`_run_timeline` reads the tract off the parcel row and never re-derives it
(`backend/app/tasks/timeline.py:1369`):

```python
tract_fips = parcel.census_tract_id
```

That value was written at geocode time by `geocoder.py`, which asks the Census
geocoder at benchmark `Public_AR_Current` / vintage `Current_Current`
(`backend/app/services/geocoder.py:25,28`) — i.e. **today's** geography. For
Racebrook that is `09170157100`, verified live:

```
Current_Current      → 09170157100  (Census Tract 1571)
```

`tract_fips` and the parcel's lat/lon are handed to `_fetch_census`
(`timeline.py:1440-1447`), which builds a `_VintageTracts`
(`timeline.py:1018`) and calls `tracts.tract_for(dataset, year)` once per year
before each request (`timeline.py:1035`, `:1084`).

`_VintageTracts.tract_for` (`timeline.py:976-1003`) is three steps:

1. `vintage = geography_vintage(dataset, year)` (`census.py:94-96`), a lookup
   in `_GEOGRAPHY_VINTAGES` (`census.py:86-91`).
2. **If the lookup misses — `vintage is None` — return the stored tract
   unchanged** (`timeline.py:977-979`). This is the whole defect.
3. Otherwise resolve the point at that vintage through
   `geocoder_service.lookup_tract_at_vintage` (`geocoder.py:375`), cache it per
   vintage, and fall back to the stored tract on a geocoder outage or a vintage
   that yields no tract (`timeline.py:989-997`).

`_GEOGRAPHY_VINTAGES` as of `df9f3ed` has four entries — decennial 2010 and
acs5 2012/2015/2018, all mapped to `Census2010_Current`. The other six pairs
(acs5 2009, 2021, 2023; decennial 1990, 2000, 2020) miss, and take step 2.

### 1.2 What it has no notion of

`tract_for` has no concept of a county-equivalent change, and it does not need
one: the geocoder's per-vintage lookup already returns the correct
county-equivalent FIPS for the vintage asked (§2.3). What `tract_for` lacks is
a mapping for the years where it matters. Its fallback is documented as
"the same request the code made before per-vintage resolution existed, so the
worst case is today's behaviour rather than a lost year"
(`timeline.py:959-962`) — true for tract redistricting, false here, because for
a Connecticut parcel *today's behaviour is itself the lost year*.

### 1.3 Why the 2020-redistricting heal did not catch this shape

`b5a306a` ("resolve each census year against its own tract vintage",
2026-08-04) and `scripts/heal_tract_vintage_gaps.py` address the same function
and a different mechanism:

| | b5a306a's mechanism | this one |
|---|---|---|
| what changes | the **tract**: boundaries redrawn in the 2020 redistricting, a new 6-digit code | the **county-equivalent**: tract unchanged, its containing entity re-coded 09009 → 09170 |
| symptom | 2012/2015/2018 empty, 2021/2023 present | 2009/2021 and decennial 2020 empty, 2012/2015/2018 present |
| affected years | those mapped to `Census2010_Current` | those *not* mapped at all |
| fix | add the pre-2020 vintages to the map | add the remaining vintages to the map |

The heal script's selection is the proof it cannot see this parcel. It looks
only at `HEALABLE_YEARS = (2012, 2015, 2018)` and requires at least one of
`CURRENT_VINTAGE_YEARS = (2021, 2023)` present
(`scripts/heal_tract_vintage_gaps.py:37-43,72-79`). Racebrook **has** 2012,
2015 and 2018 — they are the years that already work — so it has no missing
healable year and drops out of the selection. The script would report nothing
to do, correctly, and the parcel would stay broken.

The deeper reason is the comment at `census.py:79-85`, which reasons entirely
in tract-boundary terms: "2021/2023 and decennial 2020 already are 2020
geography". That sentence is true about *tracts* and false about *county
equivalents*, and the four-entry map is what it produced.

---

## 2. What the API actually knows

### 2.1 The five missing pairs, asked under `09009`

`GET api.census.gov/data/{...}?get=…&for=tract:157100&in=state:09 county:009`,
keyed. Both keys were asked for all ten of Racebrook's `(dataset, year)` pairs;
the full matrix is §2.2.

| dataset/year | endpoint | `09009157100` | `09170157100` (what we asked) |
|---|---|---|---|
| acs5 2009 | `2009/acs/acs5` | **200** — `B01003_001E` = 2757 | 204 |
| acs5 2021 | `2021/acs/acs5` | **200** — 2453 | 204 |
| decennial 1990 | `1990/dec/sf1` | 404 (endpoint does not exist) | 404 |
| decennial 2000 | `2000/dec/sf1` | 204 | 204 |
| decennial 2020 | `2020/dec/dhc` | **200** — `P1_001N` = 2604 | 204 |

The reverse direction, on succeeding years:

| dataset/year | `09009157100` (what we asked) | `09170157100` |
|---|---|---|
| acs5 2012 | 200 — 2783 | **204** |
| acs5 2015 | 200 — 2634 | **204** |
| acs5 2018 | 200 — 2564 | **204** |
| decennial 2010 | 200 — 2603 | **204** |
| acs5 2023 | **204** | 200 — 2711 |

Every cell is exclusive: exactly one of the two keys answers, never both. The
boundary sits between ACS 2021 and ACS 2022 (`2022/acs/acs5`: 204 under
`09009`, **200 — 2554** under `09170`), and decennial 2020 is on the *county*
side of it.

### 2.2 The boundary, from primary sources

- **Census Bureau, "Final Changes to County Equivalents in Connecticut"**
  (`https://www2.census.gov/geo/pdfs/reference/ct_county_equiv_change.pdf`,
  retrieved 2026-08-25), first paragraph: *"The Census Bureau adopted [the nine
  COGs/Planning Regions] … as the county-equivalent geographic unit for
  purposes of collecting, tabulating, and disseminating statistical data in
  2022."*
- **Census Bureau ACS user note 2023-01, "Change to County-Equivalents in the
  State of Connecticut for 2022 ACS"**
  (`https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2023-01.html`,
  September 2023, retrieved 2026-08-25): the 2022 ACS data products are the
  first to reflect the nine planning regions as county-equivalent units.
- **The FIPS code**, from the API itself (`2022/acs/acs5`, `get=NAME&for=county:*&in=state:09`):
  `09170` = **South Central Connecticut Planning Region**. `09009` = New Haven
  County, from `www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt`.

  *Correction to a frozen document:* `../2026-08-m4-ledger/HEAL-SCORECARD.md`
  §11.1 and the STATUS.md "To investigate" entry both call `09170` the "Greater
  New Haven Planning Region". Its Census name is South Central Connecticut
  Planning Region. Recorded here rather than edited there.

**The brief's expectation is half-falsified.** It predicted "ACS 2022+ and
decennial 2020 re-releases". ACS 2022+ is confirmed. Decennial 2020 is **not**:
both `2020/dec/dhc` and `2020/dec/pl` answer under `09009` and return 204 under
`09170`. Whatever re-tabulated 2020 products exist on data.census.gov, the two
decennial 2020 endpoints this codebase queries are county-based. So the
operative rule is:

> **ACS 5-year 2022 and later use Connecticut planning-region county codes.
> Every other dataset/year this codebase queries — all decennial vintages
> including 2020, and ACS 5-year 2021 and earlier — use the pre-2022 county
> codes.**

### 2.3 The geocoder already implements that rule

Resolving Racebrook's point (41.2690529, -72.9999675) at benchmark
`Public_AR_Current`, layer `Census Tracts`, across every vintage the geocoder
offers:

| vintage | returned GEOID |
|---|---|
| `Current_Current` | `09170157100` |
| `Census2010_Current` | `09009157100` |
| `Census2020_Current` | `09009157100` |
| `ACS2019_Current` | `09009157100` |
| `ACS2021_Current` | `09009157100` |
| `ACS2022_Current` | `09170157100` |
| `ACS2023_Current` | `09170157100` |

The geocoder's vintage boundary and the data API's vintage boundary are the
same boundary. Every vintage returns `NAME = "Census Tract 1571"` — the tract
is one tract throughout; only its county-equivalent parent is re-coded.

**This is why no crosswalk table is needed.** The brief's item 4 asked whether
the six-digit tract number is preserved across the change and whether that is
the rule or a coincidence. It is the rule for Connecticut — see §2.4 — but the
fix does not rest on it, because the fix never performs the substitution
itself. It asks the geocoder, which performs it spatially.

### 2.4 Is the six-digit number preserved? (answered, then unused)

Asked anyway, because the eventual TIGER ingest will need it. Full tract
inventories from the API for the whole state, either side of the boundary
(`for=tract:*&in=state:09 county:*`):

| | counties (`2021/acs/acs5`) | planning regions (`2022/acs/acs5`) |
|---|---|---|
| rows | 883 | 884 |
| distinct 6-digit codes | 881 | 881 |
| codes present only on that side | **0** | **0** |

The set of six-digit tract codes is **identical** across the change: not one
tract was renumbered to avoid a collision. So code preservation is the rule for
Connecticut, not a coincidence of `157100`.

One caveat that matters for anyone tempted to build the crosswalk as
`code → county`: it is not injective. `990000` appears in two counties in 2021
and three planning regions in 2022, and `990100` twice on each side — the water
tracts. A pure code lookup would be ambiguous for them; a spatial resolution
is not. Another argument for §2.3's approach.

---

## 3. Blast radius

Production, `SELECT` only, at `825d69b7e46618`.

**Every `absent`/`api_no_data` ledger row whose detail names an `09…` tract:**

| parcel | source | year | outcome | tract in detail |
|---|---|---|---|---|
| `2f1b332e` | `census_acs5` | 2009 | absent / api_no_data | `09170157100` |
| `2f1b332e` | `census_acs5` | 2021 | absent / api_no_data | `09170157100` |
| `2f1b332e` | `census_decennial` | 1990 | absent / api_no_data | `09170157100` |
| `2f1b332e` | `census_decennial` | 2000 | absent / api_no_data | `09170157100` |
| `2f1b332e` | `census_decennial` | 2020 | absent / api_no_data | `09170157100` |

Grouped by tract prefix: `09170` — 5 rows, 1 parcel. No other prefix appears.

**Every Connecticut parcel, gaps or not** (`parcels` where `state_fips = '09'`
or `census_tract_id LIKE '09%'`): exactly one row, `2f1b332e`, `county =
"South Central Connecticut"`, `census_tract_id = 09170157100`. The fleet's
state distribution puts CT at 1 of 184 parcels (CO 27, CA 25, NY 16, OR 14 at
the top).

Its five surviving census snapshots:

| dataset | year | `tract_fips` |
|---|---|---|
| acs5 | 2012 / 2015 / 2018 | `09009157100` |
| acs5 | 2023 | `09170157100` |
| decennial | 2010 | `09009157100` |

**Racebrook is the only known beneficiary.** The fix has one parcel to help
today; the test is the guard, and the next Connecticut address a user enters is
the reason it matters. Note that the geocoder writes `county = "South Central
Connecticut"` for such parcels, which is also what `get_adapter_for_county`
will see — out of scope here, recorded in STATUS.md.

---

## 4. Three findings this investigation produced that the fix does not fix

### 4.1 Not a finding — the confirmed part

acs5 2009, acs5 2021 and decennial 2020 are recoverable and are what the fix
recovers. §5.

### 4.2 `2000/dec/sf1` addresses Connecticut tracts with four digits

`for=tract:*&in=state:09 county:009` on `2000/dec/sf1` returns tract codes
`0000`, `1201`, `1202`, `1251`, … — four characters, no two-digit suffix. Our
code always sends the six-character form (`parse_tract_fips` → `157100`), which
204s. Sending `1571` instead returns **200: `P001001` = 2207, `H001001` = 891**.

The same query against Denver (`state:08 county:031`) returns `000101`,
`000102`, … — six characters. So the code width is not uniform across states in
that dataset, and the fleet-wide "decennial 2000 absent on 137 of 184 parcels"
pattern in the M4 scorecard is at least partly this, not genuine absence.

Not fixed here: it is a different mechanism, it is fleet-wide rather than
Connecticut, and guessing a width per state from a wildcard probe is a design
decision, not a patch. Recorded in STATUS.md.

### 4.3 There is no 1990 decennial dataset on `api.census.gov`

`https://api.census.gov/data/1990/dec/sf1` returns a Tomcat **404** page, under
both county keys and for any tract. `api.census.gov/data/1990.json` lists 37
datasets for the 1990 vintage — CPS, CBP, PEP, SIPP — and **no `dec/*` dataset
at all**. `_DECENNIAL_CONFIGS[1990]` (`census.py:47-54`) names an endpoint that
does not exist.

This is the complete explanation of the M4 sweep's "decennial 1990 is `absent`
on all 184 parcels". It is not absence of data for those tracts; it is a
request to a URL that has never resolved. `_request` maps 404 → `None` →
`{}` → `absent`/`api_no_data`, so the ledger has been recording an endpoint
error as a data absence.

Not fixed here (out of scope, and the remedy — drop 1990, or move to a source
that serves it — is a product decision). Recorded in STATUS.md.

### 4.4 ACS 2009 is 2000 tract geography, and the existing comment is right about it

Tract inventories per county, one vintage against another:

| county | `2009/acs/acs5` | `2010/dec/sf1` | `2000/dec/sf1` |
|---|---|---|---|
| New Haven CT (09009) | 186 | 190 | 186 |
| Denver CO (08031) | 136 | 144 | 136 |

2009 matches 2000, not 2010. Denver's `004107` — the 2010 ancestor tract the
existing test uses — is **absent** from `2009/acs/acs5`. So mapping acs5 2009
to `Census2010_Current` does not make 2009 work for a parcel whose tract was
redistricted in 2010; it returns 204 exactly as the stored tract does. It works
for Racebrook because tract 1571 is unchanged across 2000/2010/2020 and only
its county code moved. §6 covers what this costs.

---

## 5. What changed

One table and its comment, `backend/app/services/census.py:77-96`:

```python
_GEOGRAPHY_VINTAGES: dict[tuple[str, int], str] = {
    ("acs5", 2009): "Census2010_Current",
    ("acs5", 2012): "Census2010_Current",
    ("acs5", 2015): "Census2010_Current",
    ("acs5", 2018): "Census2010_Current",
    ("acs5", 2021): "ACS2021_Current",
    ("acs5", 2023): "ACS2023_Current",
    ("decennial", 2010): "Census2010_Current",
    ("decennial", 2020): "Census2020_Current",
}
```

Every year the geocoder can serve now names the vintage it is published on,
instead of only the years that were failing in 2026-08. Decennial 1990 and 2000
stay unmapped — the geocoder's oldest vintage is `Census2010_Current` and
neither year's geography is available at any vintage — and §4.2/§4.3 give the
reasons those two would not come back regardless.

The substitution log the brief asked for already exists and now fires for these
years: `tract_for` logs `"Resolved tract for vintage"` with `vintage`, `tract`
and `stored_tract` (`timeline.py:999-1002`), which for Racebrook reads
`vintage=Census2020_Current tract=09009157100 stored_tract=09170157100`.

**No new Connecticut-specific code, no crosswalk data file.** §2.3 is the
argument: the geocoder resolves the point at the requested vintage and returns
the county-equivalent FIPS that vintage uses, so a planning-region substitution
written by hand would duplicate — and could disagree with — a lookup we already
make.

### 5.1 What this changes for the other 183 parcels

- **acs5 2021, acs5 2023, decennial 2020** — outside Connecticut the resolved
  tract equals the stored tract (tract boundaries and county codes are
  unchanged since 2020 everywhere else), so the request is identical. The cost
  is geocoder calls: distinct vintages per parcel go from 1 to 4, each cached
  for the whole fetch, each falling back to the stored tract on failure
  (`timeline.py:989-997`).
- **acs5 2009** is a real behaviour change fleet-wide: a parcel whose tract was
  created in the 2010 redistricting will now be asked under its 2010 tract
  instead of its 2020 tract. Per §4.4 that is usually still a 204, never worse
  than today (the 2010 tract is strictly closer to 2000 geography than the 2020
  tract is), and it can only add rows, never remove them. It reverses a
  deliberate choice recorded in `test_timeline.py:585-587` ("stays on the
  stored tract rather than silently borrowing the 2010 ancestor"); that test is
  updated with the reason. Flagged in STATUS.md because a future full-fleet
  re-run may gain acs5 2009 rows on parcels unrelated to this pass.

---

## 6. Tests

`backend/tests/test_timeline.py`.

**Added — `test_fetch_census_uses_county_tract_before_planning_regions`.**
Racebrook's shape exactly: stored tract `09170157100`, lat/lon 41.2690529 /
-72.9999675, and a fake `lookup_tract_at_vintage` keyed on vintage the way the
live geocoder is (§2.3) — `Census2010_Current`, `Census2020_Current`,
`ACS2021_Current` → `09009157100`; `ACS2023_Current` → `09170157100`. It
asserts the *county* code each year was requested with:

- acs5 2009, 2012, 2015, 2018, 2021 and decennial 2010, 2020 → `009`
- acs5 2023 → `170`
- decennial 1990, 2000 → `170`, the stored tract, with the §4.2/§4.3 reasons in
  the docstring so the assertion is not mistaken for an endorsement.

**Delete-the-fix:** reverting `census.py` to the four-entry map (`git stash
push backend/app/services/census.py`, tests untouched) fails it —

```
>           assert asked[("acs5", year)] == "009", f"acs5 {year}"
E           AssertionError: acs5 2009
E           assert '170' == '009'
1 failed, 35 deselected
```

— on the first of the three pre-boundary requests the fix exists for; acs5
2021 and decennial 2020 are the same assertion two and five lines down. Run and
observed, not asserted from reading.

**Updated — `test_fetch_census_uses_ancestor_tract_for_older_vintages`** (the
Denver 41.11 → 41.07 case). Its `lookup_tract_at_vintage` mock returned one
value for every vintage, which no longer expresses anything now that four
vintages are in play; it is keyed by vintage, `await_count` moves 1 → 4, and
the acs5 2009 expectation moves from "stored tract" to "2010 ancestor" with
§4.4's measurement as the reason. The redistricting behaviour it was written to
protect — 2018 and decennial 2010 resolve to `004107`, 2021/2023/decennial 2020
stay on `004111` — is unchanged and still asserted.

**`test_upsert_relabels_when_tract_changes`** (`test_census.py:577`) is
untouched and, as the brief anticipated, **is not exercised by this fix**.
Racebrook's three recovered years have no `census_snapshots` row at all — they
were `absent`, never written — so the re-run `INSERT`s rather than conflicting,
and the relabel branch never runs. The years that *do* conflict on re-run
(acs5 2012/2015/2018, decennial 2010, acs5 2023) resolve to the same tract they
already carry, so nothing relabels there either. The test still guards the
b5a306a path it was written for.

**Suite:** results recorded in §8.

---

## 7. Deviations from the brief

1. **No substitution logic in `tract_for`, and no crosswalk data table**
   (brief item 4). §2.3: the geocoder already returns the correct
   county-equivalent per vintage, so the fix is the vintage map, not a
   Connecticut rule. The brief's stop condition was "if the fix needs data we
   don't hold" — the opposite happened. The prefix question the brief asked to
   verify is answered in §2.4 anyway, because the TIGER ingest will need it.
2. **Three years recovered, not five** (brief item 6 expected five). §4.2 and
   §4.3 are the two that do not come back, each for a reason unrelated to the
   county-equivalent change and each newly discovered here. `PREDICTION.md`
   predicts three and says why the other two stay `absent` — the prediction is
   written to the evidence, not to the brief.
3. **Decennial 2020 is not a planning-region vintage** (brief item 2 expected
   "decennial 2020 re-releases"). §2.2 — `dec/dhc` and `dec/pl` both answer
   under `09009` only.
4. **No "census ingest item" exists in STATUS.md to annotate** (brief item 7).
   Grepping the whole record for `ingest` / `TIGER` / `spatial join` finds
   nothing; the census tabular ingest pass is queued outside the written record.
   A Scheduled entry is added for it, carrying the stopgap note the brief asked
   to put under it.
5. **`fly ssh console -C` ran a stdin-piped script, not a one-liner.** The
   blast-radius queries are multi-statement; they were base64'd and piped to
   `python -` inside the machine so that nothing was written to the machine's
   filesystem and no local process touched production. `SELECT` only.

---

## 8. Test and lint results

Docker is not running on this workstation, so the suite ran under
`backend/.venv` rather than `make test`'s `docker compose exec api pytest`.
Same interpreter version (3.12) and same `tests/conftest.py` SQLite harness.

```
$ .venv/bin/python -m pytest tests/ -q
524 passed, 2 skipped, 2 warnings in 6.88s

$ .venv/bin/python -m ruff check app/ tests/
All checks passed!

$ .venv/bin/python -m ruff format --check app/ tests/
72 files already formatted

$ .venv/bin/python -m mypy app/
Success: no issues found in 47 source files
```

523 before this batch, 524 after: one test added, one rewritten in place
(measured — the pre-batch count is from the same suite with both changed files
stashed).
The delete-the-fix run is quoted in §6.

---

## 9. UNVERIFIED

- **That `ACS2021_Current` and `Census2020_Current` return the same tract for
  every point outside Connecticut.** Both were checked at Racebrook only.
  They are used for different years (acs5 2021, decennial 2020), so a
  divergence would show as a per-year difference, and both fall back to the
  stored tract — the pre-fix behaviour — if a vintage yields nothing.
- **That code preservation across the county-equivalent change holds for
  vintages other than 2020 tracts.** §2.4 compares the 2021 and 2022 ACS
  inventories, which are both 2020 tract geography. Nothing here says what a
  2030 re-tabulation will do.
- **The §4.2 four-digit reading, beyond Connecticut and Denver.** Two counties
  were probed. Whether the width varies by state, by county, or by something
  else in `2000/dec/sf1` is unmeasured, and so is how much of the fleet-wide
  2000 absence it explains.
- **Whether any re-tabulated 2020 decennial product is published under
  planning-region codes anywhere.** `dec/dhc` and `dec/pl` are not
  (§2.2); data.census.gov surfaces a South Central Connecticut Planning Region
  profile, but which dataset backs it was not established, and it is not one
  this codebase queries.
- **The requeue outcome.** `PREDICTION.md` is written before the run, per the
  norms; nothing in this report claims a production result for the fix.
