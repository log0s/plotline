# Property outcomes — Z3, Z4, the municipality coverage gate

STATUS.md Z3, Z4, the Adams jurisdiction row, and the Y7 UNVERIFIED register's
entry 1. Decided and built 2026-08-27. Migration 0014, four commits, none
pushed. Predictions written before any run: `PREDICTION.md`.

Three defects, one shape: a state the system could not tell from success.

---

## 1. The path as it was (item 1)

### Per county

`fetch_sales` and `fetch_permits` are gathered together
(`tasks/timeline.py:1379-1382`), so "queries" below is the sum across both.

| county | sales queries | permit queries | total | one query fails → task was | raw vs matched at the rollup |
|---|---|---|---|---|---|
| Denver | 0 — the Socrata sales dataset was retired at the ArcGIS Hub migration, `fetch_sales` returns an empty `SourceFetchResult` with `queries_attempted = 0` | 2 (residential 316, commercial 317) | **2** | `complete`, thinner | available in memory, written nowhere |
| Adams | 0 | 1 (Eye On Adams layer 0) | **1** | `failed` — correctly, and only because 1 of 1 is "all" | same |
| District of Columbia | 1 (ITSPE FACTS, layer 56) | 7 (year layers 18, 17, 16, 15, 14, 3, 2) | **8** | `complete`, thinner | same |
| Santa Clara / San Jose | 0 | 3 CKAN resources (active, under_inspection, expired) | **3** | `complete`, thinner | same |
| New York | 2 Socrata (annualized `w2pb-icbu`, rolling `usep-8jbt`) | 1 Socrata (`ipu4-2q9a`) | **3** | `complete`, thinner | same |

**Zero-attempt sources are not failures.** `SourceFetchResult()` with
`queries_attempted = 0` is "there is no public API to ask", which is why
Denver, Adams and Santa Clara having no sales feed never counted against
`all_queries_failed` (`county_adapters.py:126-128`).

**The H4 rule.** `queries_attempted > 0 and queries_failed == queries_attempted`
was the only failure test in the property path. Everything short of total
failure fell through to a single unconditional
`_set_task_status(..., "complete", items_found=total_items)`. Adams passed
this test only by arithmetic: with one query, "one failed" and "all failed"
are the same sentence.

**Raw vs matched.** Both counts existed at the rollup —
`len(all_events)` before the `is_address_match` loop and `len(matched_events)`
after — and both went into a `logger.info("Property events filtered", …)` line
and nowhere else. `items_found` is `count_property_events(db, parcel_id)`, the
persisted total for the parcel, so it is not even the run's own matched count.

**The existing skip.** `get_adapter_for_county` returning None wrote
`status = 'skipped'` with an `error_message`, `items_found` left at its
default 0. That is the state the coverage gate now joins, one level down.

**Where the city was.** Nowhere convenient: `parcels` has `address`,
`normalized_address`, `county`, `state_fips` and no city column;
`GeocodeResult` (`services/geocoder.py:176-185`) carries the same fields and
no city. The Census geocoder's `matchedAddress` — which is exactly what
`normalized_address` stores (`geocoder.py:281`) — is comma-delimited
street, city, state, ZIP. That line is the only place a city exists.

---

## 2. Schema as landed (item 2)

`backend/alembic/versions/0014_property_task_outcomes.py`, head `0013 → 0014`.
Applied to local dev Postgres, `alembic upgrade head` exit 0, head check
`database=['0014'] scripts=['0014']`.

On `timeline_request_tasks`, all nullable, no backfill:

| column | type | meaning |
|---|---|---|
| `queries_run` | `INTEGER` | queries attempted across sales + permits |
| `queries_failed` | `INTEGER` | of those, how many errored out |
| `rows_returned` | `INTEGER` | events the adapters handed the address matcher |
| `rows_matched` | `INTEGER` | events it kept |
| `coverage` | `TEXT` | `covered` / `not_covered` / `no_adapter`, CHECK `ck_timeline_request_tasks_coverage` |

Plus two widenings, both discussed under Deviations:

- `ck_timeline_request_tasks_status` now admits `partial`.
- `items_found` drops `NOT NULL`.

Verified on dev immediately after the upgrade:
`SELECT count(*), count(queries_run), count(coverage), count(*) FILTER (WHERE
items_found IS NULL)` → `718|0|0|0`. Nothing was inferred, nothing was
rewritten.

ORM mirrored in `app/models/parcels.py` (`TimelineRequestTask`, with
`VALID_STATUSES` gaining `partial` and a new `VALID_COVERAGE`); test DDL
mirrored in `backend/tests/conftest.py:108-131`.

**Downgrade** is lossy by construction and says so: restoring `NOT NULL`
forces the not-covered rows back to `items_found = 0`, which is the exact
conflation this migration removes. `partial` rows are not rewritten — the
narrowed CHECK fails loudly on them instead of demoting a partial outcome to a
word the old readers would trust. Read, not executed.

**Constraint-name drift, found by running it.** The first `alembic upgrade
head` failed: `constraint "ck_trt_status" of relation
"timeline_request_tasks" does not exist`. The database's constraints on that
table are `ck_timeline_request_tasks_source` / `_status` (set by 0002); the
ORM spelled two of them `ck_trt_*`, a label no server ever carried. Every
other table in the model uses the long form (`ck_timeline_requests_status`,
`ck_parcels_latitude`), so this table was the outlier. The migration targets
the real names and the ORM was corrected to match — a metadata label, no DDL.
Filed as **AA1**.

---

## 3. Z4 — the counts (item 3)

`_fetch_and_persist_property` writes all four on every terminal property task
(`tasks/timeline.py:1456-1476`), via a new frozen `TaskCounts` dataclass
(`services/imagery.py:46-68`) threaded through `_set_task_status` →
`update_request_task`.

`rows_returned` is `len(all_events)` and `rows_matched` is
`len(matched_events)` — deliberately the two numbers already in the
`"Property events filtered"` log line, so that `rows_returned - rows_matched`
is *exactly* the address matcher's rejection count and nothing else. A count
of raw portal rows before parsing would have been a different, also-useful
number, but it would have broken that subtraction (DC's `_parse_sale` drops
rows with no sale price; Santa Clara's `parse_row` applies its own
street-number check), so it was not used. The log line stays.

The all-queries-failed path also writes counts, with `rows_returned = 0` —
nothing came back to match against.

## 4. Z3 — `partial` at the task level (item 4)

`status = "partial" if queries_failed else "complete"`
(`tasks/timeline.py:1456`). Full rule:

- `complete` — every query answered, **including a run that returned zero rows**
- `partial` — at least one failed, at least one did not
- `failed` — all failed (H4's rule, unchanged)

`partial` did **not** already exist on the task-level CHECK — 0012 added it to
`timeline_requests` only — so 0014 adds it there. `partial` also joins
`_TERMINAL_TASK_STATUSES` (`imagery.py:43`) so a partial task gets a
`completed_at` and does not read as stranded to a sweep.

**Request aggregation needed a change; it did not already follow.**
`aggregate_request_status` counted only `status == "failed"`, so a `partial`
task would have landed silently in the `complete` bucket — the same defect one
level up. It now computes a `degraded` list of `failed | partial`
(`imagery.py:501-533`):

- `failed` — still requires *every* task to be genuinely `failed`. A partial
  task served data; calling the whole request failed for it would be this
  batch's own defect in the other direction.
- `partial` — any degraded task.

The prompt's instruction ("treats a partial task as a failed task for the
request's `partial` computation") is scoped to the partial computation, which
is how it is implemented.

**One more consequence, not in the prompt.**
`maybe_refetch_for_backfill` retried a property task that was
`skipped | failed`. `partial` was added — it is precisely the state that
trigger exists for. See §6 for the `not_covered` exclusion that had to come
with it.

## 5. The coverage gate (item 5)

`CountyAdapter.covers(city: str | None) -> bool`, default `True`
(`county_adapters.py:175-188`). Denver, DC and New York do not override it:
two are city-counties and the third is a borough, so there is no boundary
below the county to gate on.

`city_from_address` (`services/address_normalizer.py:109-137`) reads the
second comma component of `normalized_address`, uppercased.

The pipeline calls it before `processing`, so a not-covered address never
reaches a query (`tasks/timeline.py:1301-1329`): `status = 'skipped'`,
`coverage = 'not_covered'`, `items_found` NULL, `queries_run = 0`. The
existing no-adapter skip gets `coverage = 'no_adapter'` and NULL `items_found`
too (`timeline.py:1279-1292`) — same argument, and leaving one at 0 while the
other is NULL would have put the conflation back in a new place.

### Adams — the rule and its evidence

Deny-list of mailing cities (`county_adapters.py:312-373`): **THORNTON,
NORTHGLENN, WESTMINSTER, COMMERCE CITY, FEDERAL HEIGHTS, AURORA, ARVADA**. A
deny-list rather than an allow-list because the county serves the residual —
everything that is *not* one of these.

Three sources, in order of what they actually settle:

1. **The layer's own definition query, read 2026-08-27** —
   `…/Building_Permits_Eye_On_Adams/FeatureServer/0?f=json`. Its
   `definitionQuery` filters on `ApplicationStatus` only (a long OR-list of
   ~20 statuses) and its `definitionExpression` is null. **It encodes no
   jurisdiction at all.** The prompt expected this to carry the rule; it does
   not, so the rule had to be derived from what the layer holds.
2. **The portal check of 2026-08-27** (STATUS.md, the Adams row): the exact
   pattern the adapter sends returns `count=3` for Emerson St, coverage
   5600–8371, no `exceededTransferLimit`; 12804 Emerson returns 0.
3. **A house-number sample taken for this batch, 2026-08-27.** Queried
   `upper(StreetName) = <street>` for HURON, YORK, WASHINGTON and EMERSON:
   4,013 house numbers spanning 741–16610, and **zero** anywhere in the band
   9000–13600 — which is Thornton, Northglenn and Federal Heights. What
   records do exist in 8400–8700 (YORK 25, EMERSON 17) sit in the
   unincorporated pocket just north of 84th. The gap is the jurisdiction.

**DENVER and BRIGHTON are deliberately not on the list.** Both are mailing
cities for large unincorporated pockets the layer *does* cover, confirmed by
geocoding two addresses the layer holds (2026-08-27): `8601 EMERSON CT,
DENVER, CO, 80229` → county **Adams**, and `16610 YORK ST, BRIGHTON, CO,
80602` → county **Adams** (16610 is the exact maximum York St house number in
the layer). Denying on mailing city alone would have lost both.

### Santa Clara — the rule and its source

Allow-list of one: **SAN JOSE** (`county_adapters.py:606-643`). The inverse
shape because the source is the inverse: `data.sanjoseca.gov` is the City of
San Jose's own CKAN portal, not the county's, and Sunnyvale, Mountain View,
Cupertino and Palo Alto run their own permit systems with no countywide feed
to fall back on. This is what the adapter's docstring has said since it was
written; the gate makes the pipeline act on it.

### A `None` city never denies

Both rules return `True` for a missing city. The gate is only allowed to turn
a real answer into "we did not ask" when it knows something.

This mattered immediately. Reading production (2026-08-27) showed
`normalized_address` carries **three** shapes, not one:

- the strict Census form — `12804 EMERSON ST, THORNTON, CO, 80241`
- a spelled-out variant — `12804 Emerson Street, Thornton, Colorado 80241`
  (this is the actual Adams parcel; both parse to `THORNTON`)
- **city-level geocodes with no street line** — `Cupertino, California 95014`,
  where the second component is the *state*

The third would have handed `covers()` the string `CALIFORNIA 95014` as a
city. Santa Clara's allow-list would then have denied Cupertino — the right
verdict reached by a reading that was never made. `city_from_address` now
rejects any component containing a digit: a US city name has none. Cupertino
falls back to `covered` and a real `complete:0`, which is where it was before
this batch.

### `items_found = 0` readers (item 5's grep)

Three, all checked:

| site | handles NULL? |
|---|---|
| `scripts/requeue_empty_property.py:92` — `.where(items_found == 0)` | Yes. `NULL == 0` is NULL, so not-covered rows are excluded; they are also `skipped` rather than `complete`, so the status filter excludes them independently. Comment added at the site. |
| `frontend/src/components/ParcelInfo.tsx` `TaskRow` | Now renders "not covered" for a skipped task with a NULL count, instead of "0 items". |
| `frontend/src/components/Timeline.tsx` `progressLabel` | A NULL count contributes nothing to the progress string rather than "(0)". |

### UI

`coverage` is on `TimelineRequestTaskResponse` (`app/schemas/imagery.py`) and
on the frontend `TimelineRequestTask` type — **optional**, not merely nullable,
because `src/test/types.contract.test.ts` pins real captured payloads that
predate the field.

`not_covered` renders as `NotCoveredBanner`
(`frontend/src/components/demographics/NotCoveredBanner.tsx`), deliberately
the same quiet informational treatment as the existing no-adapter case
(`demographics/UnsupportedCountyBanner.tsx`) — same container, same muted
type, no red, no retry promise. It carries the task's own `error_message`,
which names the county and the city. In the empty-panel branch the copy also
drops from "No census **or property** records found" to "No census records
found", because the property half would be a claim that we looked.

`ParcelInfo`'s `SourceIssueRow` already rendered a skipped task's
`error_message` with an amber dot and slate text
(`ParcelInfo.tsx:63-78`) — informational, not an error — so the not-covered
message lands there correctly with no change. `TaskRow` now also treats
`partial` as done (green dot, item count) rather than falling through to
"queued".

---

## 6. `not_covered` must not re-dispatch — a defect this batch would have introduced

Adding `not_covered` as a **skipped** task collides with
`maybe_refetch_for_backfill`, which retries a property task that is
`skipped`. Before the gate, an Adams address was `complete` and did not
re-dispatch; after it, it would have dispatched a full-scope request on
**every page view, forever**, and got the same answer every time.

`imagery.py:630` excludes it: a jurisdiction gap is not a transient one. Only
a deploy — a new adapter, or a changed coverage rule — can move it. Covered by
`test_backfill_never_retries_a_not_covered_property_task`, reversion observed.

---

## 7. `street_name` — read-only finding (item 6)

**The premise in the prompt does not hold, and the real exposure is
different.** No adapter ever receives a street suffix, abbreviated or
expanded. `extract_search_terms` (`address_normalizer.py:90-106`) returns the
house number and **one** token — the first street-name word after an optional
directional. `"12804 EMERSON ST"` → `("12804", "EMERSON")`. So "does `LIKE`
survive `ST` vs `STREET`" is moot: neither form is ever sent.

Per adapter, with what is actually sent:

| adapter | pattern | robust to the real inputs? |
|---|---|---|
| Denver | `upper(ADDRESS) LIKE '<n> %<name>%'` | Yes. Anchored on the house number, suffix-agnostic, tolerant of a directional between number and name. Deliberately broad; the address matcher cleans up. |
| Adams | `upper(CombinedAddress) LIKE '<n> %<name>%'` | Yes, same shape. Confirmed live: the exact pattern returns `count=3` for a covered Emerson address. |
| DC sales | `upper(PROPERTY_ADDRESS) LIKE '<n> %<name>%'` | Yes, same shape. |
| DC permits | `upper(FULL_ADDRESS) LIKE '<n> %<name>%'` | Yes, same shape. |
| Santa Clara | CKAN full-text `q = "<n> <name>"`, then a Python filter requiring `tokens[0] == street_number` and `name in location` | Yes for suffixes; the Python filter is the strict part, and it compares against `gx_location` which has no suffix problem either. |
| NYC sales | `upper(address) LIKE '%<n> <name>%'` | Yes, though the leading `%` means "100 MAIN" also matches "1100 MAIN"; the address matcher rejects those. |
| NYC permits | `house__ = '<n>' AND upper(street_name) LIKE '%<name>%'` | Yes — `street_name` is a suffix-free column. |

**The genuine exposures, neither of which is suffix form:**

1. **Ordinal stripping makes numbered streets very broad.**
   `normalize_address` turns `17TH` into `17`, so `"245 E 17TH ST"` queries as
   `LIKE '245 %17%'`. That is correct for NYC DOB (which stores `17`) and is
   why the rule exists, but on Denver and DC it also matches `1170`, `X17Y`
   and anything else containing the digits. The rows come back and the address
   matcher rejects them — which, after Z4, is now *visible* as
   `rows_returned >> rows_matched` instead of invisible.
2. **Multi-word street names query on their first word only.**
   `"500 MARTIN LUTHER KING BLVD"` goes out as `LIKE '500 %MARTIN%'`. Broad,
   not wrong, and again absorbed by the matcher.

**What a fix would be:** pass the full normalized street line to the adapter
alongside the two extracted terms, and let each adapter tighten its own
pattern where its column can support it (Denver/Adams/DC's single address
column can take a second `LIKE` on the remaining tokens; NYC's split columns
already do). Not attempted here — the prompt scoped item 6 as read-only, and
the change would alter what every adapter *fetches*, which this batch was
explicitly told not to do. Filed as **AA3**.

---

## 8. Fixture fix (item 7)

The Y7 UNVERIFIED register's entry 1 recorded
`scripts/backfill_census_housing.py`'s `deployed_sha` write as code-read only,
on the grounds that "the SQLite in-memory fixture the rest of the suite uses
is not reachable from a script-level `SessionLocal`".

**That diagnosis was wrong.** `from app.db import SessionLocal` binds a name
*on the script module*, and rebinding that attribute is what
`backend/tests/test_revalidate_landsat.py:178` has been doing all along. The
seam existed.

What actually blocked the test was one line: the script passed `parcel_id` as
a `str` into a `UUID(as_uuid=True)` column. psycopg2 coerces that; SQLAlchemy's
SQLite variant raises `'str' object has no attribute 'hex'`. Fixed at the
source — `uuid.UUID(parcel_id)` — with a comment saying why, and
`backend/tests/test_backfill_census_housing.py` now covers both the create and
the reuse path. The Y7 entry is closed.

---

## 9. Tests (item 8)

Every reversion below was executed and the failure observed.

| test | file | reversion |
|---|---|---|
| `test_fetch_property_partial_failure_keeps_records_and_marks_partial` | `test_timeline.py` | `status = "partial" if queries_failed else "complete"` → `"complete"`. **Failed.** Uses the real `DenverAdapter` with `query_feature_service` raising `ArcGISError` on the commercial layer only, so it exercises the actual two-layer fan-out: task `partial`, `queries_run=2`, `queries_failed=1`, `items_found=1` from the surviving layer. **This test previously asserted `complete`** — Z3 was written down as an expectation, so it was rewritten rather than added to. |
| `test_fetch_property_records_the_address_matcher_split` | `test_timeline.py` | drop the `counts=` argument from the terminal `_set_task_status`. **Failed.** DC shape, one row in and zero kept: `rows_returned=1`, `rows_matched=0`, `queries_run=8`, status still `complete`. |
| `test_fetch_property_outside_coverage_skips_without_asking` (Adams/Thornton, Santa Clara/Sunnyvale) | `test_timeline.py` | `if not adapter.covers(city):` → `if False:`. **Both parametrizations failed.** Also asserts `query_feature_service` and `query_ckan_datastore` were never called. |
| `test_fetch_property_inside_coverage_still_queries` (Brighton, Denver-mailing, San Jose) | `test_timeline.py` | covered by the same reversion in reverse — these are the rows that fail if `covers()` over-denies. |
| `test_adams_covers_unincorporated_only`, `test_santa_clara_covers_san_jose_only` | `test_county_adapters.py` | `covers()` → `return True` on both adapters. **7 of 16 parametrizations failed.** |
| `test_covers_defaults_to_true_for_city_county_adapters` | `test_county_adapters.py` | pins that Denver/DC/NYC never deny. |
| `test_aggregate_request_status_treats_a_partial_task_as_degraded` | `test_imagery.py` | drop `"partial"` from the `degraded` comprehension. **Failed.** |
| `test_backfill_retries_a_partial_property_task` | `test_imagery.py` | drop `"partial"` from the refetch status tuple. **Failed.** |
| `test_backfill_never_retries_a_not_covered_property_task` | `test_imagery.py` | `covered = …` → `covered = True`. **Failed.** |
| `test_city_from_address` | `test_address_normalizer.py` | covers all three production address shapes including the digit guard. |
| `test_new_request_records_the_deployed_sha` | `test_backfill_census_housing.py` | drop `deployed_sha=get_settings().git_sha`. **Failed.** Closes Y7 UNVERIFIED entry 1. |
| `test_existing_request_is_reused_and_not_restamped` | `test_backfill_census_housing.py` | pins that reuse does not re-stamp an older run's SHA. |
| "says the records are the city's when the county doesn't cover the address" | `DemographicsPanel.test.tsx` | remove the `propertyCoverage === "not_covered"` branch. **Failed.** Asserts the banner renders *and* that no error copy, no retry promise and no "no records found" appears. |

**Suite state.** Backend `667 passed, 7 skipped`. `make lint` — ruff check,
ruff format, mypy — all clean. Frontend `tsc --noEmit` clean, `vitest run`
20 passed, eslint clean. `prettier --check` reports two files this batch never
touched (`src/api/client.ts`, `src/components/SearchBar.tsx`) as already
unformatted on `main`; only the files this batch edited were formatted.

---

## 10. Deviations from the prompt

1. **"No changes to existing `timeline_request_tasks` constraints" could not
   be honoured, and both breaches are load-bearing.** Item 4 requires
   `partial` on the task status CHECK and item 5 requires `items_found` NULL;
   a CHECK cannot be widened additively (multiple CHECKs AND together) and
   NOT NULL cannot be relaxed by adding anything. Both are widenings — every
   value that was legal before is still legal — but they are edits to existing
   constraints and are named here rather than glossed. `ck_trt_source` /
   `ck_timeline_request_tasks_source` was left alone.
2. **No adapter's reporting changed, because none needed to.**
   `SourceFetchResult` already carried `queries_attempted` / `queries_failed`
   (Z1's work), so commit 2 touched the task path only. Commit 3 is the one
   that changes adapters, and only by adding `covers()`. Nothing about what
   any adapter *fetches* changed, per the prompt's constraint.
3. **The county layer's definition query does not contain the coverage rule.**
   Item 5 named it as a source; it turned out to encode only an
   `ApplicationStatus` filter. The rule is derived from the portal check and a
   fresh house-number sample instead, both documented in §5 and both dated.
4. **`items_found` is NULL for `no_adapter` too, not only `not_covered`.**
   Item 5 scoped the NULL to `not_covered`. Extending it is the same argument
   — a task that ran no queries has no count — and leaving no-adapter at 0
   would have preserved the conflation in the larger of the two populations
   (hundreds of skipped tasks across ~90 counties, versus one Adams parcel).
5. **A defect the batch had to fix in its own work.** `not_covered` as a
   `skipped` status would have made `maybe_refetch_for_backfill` re-dispatch a
   full-scope request on every page view for those parcels. See §6. Not in
   the prompt; found by following the status through its readers.
6. **`city_from_address` rejects components containing digits.** Not in the
   prompt. Forced by production carrying city-level geocodes
   (`Cupertino, California 95014`) where the second component is the state.
   See §5.

---

## 11. UNVERIFIED register

1. **Nothing in `PREDICTION.md` has been observed.** Migration 0014 is not
   deployed (production is at `0013`, both apps at `07db132`), no property
   task has run under the new code, and deploys are Ryan's. Every claim P-1
   through P-8 is pending the next fleet sweep.
2. **Migration downgrade path** — read, not executed against any database.
   Its lossiness is reasoned, not measured.
3. **The Adams deny-list beyond Thornton.** WESTMINSTER, COMMERCE CITY,
   FEDERAL HEIGHTS, AURORA and ARVADA are on the list by the same argument
   that puts NORTHGLENN there — the layer holds nothing in their house-number
   bands on the four streets sampled — but only Thornton has a
   confirmed-from-two-directions instance. Four streets is a sample, not a
   census of the layer.
4. **The mailing-city false negative has never been observed**, because the
   fleet holds exactly one Adams parcel and it is genuinely in Thornton. The
   risk is reasoned from how the Census geocoder works, not measured. STATUS.md
   AA2.
5. **Eye On Adams is 2011-onward and status-filtered** (carried forward from
   the Adams row; the `definitionQuery` read in §5 confirms the status
   filtering directly). A *covered* Adams address therefore gets a partial
   permit history, and nothing in this batch records that — `coverage =
   'covered'` says the county is the authority, not that its feed is complete.

---

## 12. Commits

1. `1f7e398` — `feat(schema): migration 0014 — property task counts, partial, coverage`
2. `48b7fd8` — `feat(property): Z3 task partial, Z4 matcher split on the task row`
3. `eee8a9e` — `feat(property): municipality coverage gate — covers(city) on the adapter`
4. This commit — docs, prediction, STATUS.md.

None pushed.
