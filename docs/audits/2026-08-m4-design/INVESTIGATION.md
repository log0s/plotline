# M4 design investigation — per-year outcome persistence

**Date:** 2026-08-24
**HEAD at investigation:** `07b55e0`
**Scope:** fact-gathering for the open M4 design question (STATUS.md, "Scheduled"):
where per-year outcomes live — a JSONB column on `timeline_request_tasks`, or a
per-year row in a new table. **This document decides nothing and implements
nothing.** Each section ends with an implication for the column-vs-row choice,
not a recommendation.

Line numbers are against the working tree as investigated. Every backend file
cited here is byte-identical to `07b55e0`. One cited frontend file is not:
`frontend/src/components/ParcelInfo.tsx` carried an uncommitted L8 change
(+1 net line at `:120-131`) while this ran, so its citations **below line 123**
— `:130-135`, `:249-254`, `:265-267`, `:268-274`, `:287-288` — are one greater
than the same lines at `07b55e0`. `:17-53` and `:57-70` sit above the change and
are unaffected. `STATUS.md`'s cited rows (`:66`, `:309`) are likewise unaffected
by its own uncommitted edits, which all land at or below `:30`, `:84`, `:542`.

Paths are repo-relative; `backend/` is elided for files under `backend/app` and
`backend/tests`, which are cited as `app/...` and `tests/...`.

---

## 1. Current schema, exactly

**Alembic head: `0010`** — `alembic/versions/0010_review_hardening.py:18`
declares `revision = "0010"`, and no migration in `alembic/versions/` declares
`down_revision = "0010"`. The chain is linear: 0001 → 0002 → … → 0010, with no
branch labels anywhere.

### 1.1 `timeline_requests`

ORM: `app/models/parcels.py:94-155`.
Created: `alembic/versions/0001_initial.py:76-116`.
Altered: `0009_schema_hardening.py:25-33` (adds `updated_at`);
`0010_review_hardening.py:44-74` (fails stranded rows, adds the in-flight
partial unique index, makes `parcel_id` NOT NULL).

| column | type | null | default | ORM | migration |
|---|---|---|---|---|---|
| `id` | UUID | no | `gen_random_uuid()` | `:101-106` | `0001:78-83` |
| `parcel_id` | UUID | **no** | — | `:107-112` | created nullable `0001:84-89`; NOT NULL `0010:74` |
| `status` | TEXT | no | `'queued'` | `:113-117` | `0001:90-95` |
| `created_at` | TIMESTAMPTZ | no | `NOW()` | `:118-122` | `0001:96-101` |
| `updated_at` | TIMESTAMPTZ | no | `now()`, ORM `onupdate=now()` | `:123-128` | `0009:25-33` |
| `completed_at` | TIMESTAMPTZ | yes | — | `:129-132` | `0001:102` |
| `error_message` | TEXT | yes | — | `:133` | `0001:103` |

Constraints and indexes:

- FK `parcel_id → parcels.id` **ON DELETE CASCADE** (ORM `:109`, mig `0001:87`).
- CHECK `ck_timeline_requests_status` — `status IN ('queued','processing','complete','failed')` (ORM `:148-151`, mig `0001:106-110`).
- INDEX `idx_timeline_requests_parcel_id` on `(parcel_id)` (mig `0001:112-116`). The ORM instead sets `index=True` on the column (`:111`), which autogenerates the name `ix_timeline_requests_parcel_id` — see §1.5.
- UNIQUE INDEX `uq_timeline_requests_parcel_inflight` on `(parcel_id) WHERE status IN ('queued','processing')` (mig `0010:66-70`). **Not declared in the ORM.**

### 1.2 `timeline_request_tasks`

ORM: `app/models/parcels.py:158-218`.
Created: `alembic/versions/0002_imagery_timeline.py:90-134`.
Altered: `0008_usgs_topo.py:32-39` (widens the source CHECK to include
`usgs_topo`); `0010_review_hardening.py:27-40` (dedupes, then adds
`uq_trt_request_source`).

| column | type | null | default | ORM | migration |
|---|---|---|---|---|---|
| `id` | UUID | no | `gen_random_uuid()` | `:166-171` | `0002:93-98` |
| `timeline_request_id` | UUID | no | — | `:172-177` | `0002:99-104` |
| `source` | TEXT | no | — | `:178` | `0002:105` |
| `status` | TEXT | no | `'queued'` | `:179-183` | `0002:106-111` |
| `items_found` | INTEGER | no | `0` | `:184` | `0002:112` |
| `started_at` | TIMESTAMPTZ | yes | — | `:185-188` | `0002:113` |
| `completed_at` | TIMESTAMPTZ | yes | — | `:189-192` | `0002:114` |
| `error_message` | TEXT | yes | — | `:193` | `0002:115` |

Constraints and indexes:

- FK `timeline_request_id → timeline_requests.id` **ON DELETE CASCADE** (ORM `:174`, mig `0002:102`).
- CHECK on `source` — `IN ('naip','landsat','sentinel2','census','property','usgs_topo')`. **Name differs:** DB `ck_timeline_request_tasks_source` (`0002:118-122`, replaced `0008:35-39`); ORM `ck_trt_source` (`:202-205`).
- CHECK on `status` — `IN ('queued','processing','complete','failed','skipped')`. **Name differs:** DB `ck_timeline_request_tasks_status` (`0002:124-128`); ORM `ck_trt_status` (`:206-209`).
- UNIQUE `uq_trt_request_source` on `(timeline_request_id, source)` (mig `0010:36-40`, ORM `:210-214`) — names agree.
- INDEX `idx_trt_request` on `(timeline_request_id)` (mig `0002:130-134`); ORM sets `index=True` on the column (`:176`) → `ix_timeline_request_tasks_timeline_request_id`.

**There is no index on `status`, on `source` alone, or on either timestamp.**

### 1.3 `imagery_snapshots`

ORM: `app/models/parcels.py:221-285`.
Created: `0002_imagery_timeline.py:25-88`.
Altered: `0007_imagery_additional_cog_urls.py:20-23` (adds
`additional_cog_urls TEXT[]`); `0008_usgs_topo.py:23-30` (widens the source
CHECK to include `usgs_topo`).

Columns: `id` UUID PK; `parcel_id` UUID NOT NULL; `source` TEXT NOT NULL;
`capture_date` DATE NOT NULL; `stac_item_id` TEXT NOT NULL; `stac_collection`
TEXT NOT NULL; `bbox` `geometry(POLYGON,4326)` NULL; `cog_url` TEXT NOT NULL;
`additional_cog_urls` TEXT[] NULL; `thumbnail_url` TEXT NULL; `resolution_m`
DOUBLE NULL; `cloud_cover_pct` DOUBLE NULL; `created_at` TIMESTAMPTZ NOT NULL
default `NOW()`. (ORM `:228-259`; mig `0002:28-62` plus `0007:20-23`.)

- FK `parcel_id → parcels.id` **ON DELETE CASCADE** (ORM `:236`, mig `0002:37`).
- CHECK `ck_imagery_snapshots_source` (ORM `:268-271`; mig `0002:65-69`, replaced `0008:26-30`).
- UNIQUE `uq_imagery_snapshots_parcel_stac_item` on `(parcel_id, stac_item_id)` (ORM `:272-276`, mig `0002:71-75`).
- INDEX `idx_imagery_parcel_date` on `(parcel_id, capture_date)` (ORM `:277`, mig `0002:77-81`).
- INDEX `idx_imagery_bbox` GIST on `(bbox)` (ORM `:278`, mig `0002:83-88`).

**There is no unique constraint on `(parcel_id, source, year)`** — the period
uniqueness the timeline depends on is enforced procedurally by
`reconcile_source_snapshots` (§6), not by the schema.

### 1.4 `census_snapshots`

ORM: `app/models/parcels.py:288-352`.
Created: `0003_census_snapshots.py:24-79`. **Never altered by any later
migration.**

Columns: `id` UUID PK; `parcel_id` UUID NOT NULL; `tract_fips` TEXT NOT NULL;
`dataset` TEXT NOT NULL; `year` INTEGER NOT NULL; eleven nullable demographic
columns (`total_population` … `median_gross_rent`, ORM `:311-321`, mig
`0003:42-52`); `raw_data` **`JSON`** (ORM `:323`, mig `0003:54`); `created_at`
TIMESTAMPTZ NOT NULL default `NOW()`.

- FK `parcel_id → parcels.id` **ON DELETE CASCADE** (ORM `:303`, mig `0003:35`).
- CHECK `ck_census_snapshots_dataset` — `dataset IN ('decennial','acs5')` (ORM `:338-341`, mig `0003:63-67`).
- UNIQUE `uq_census_snapshots_parcel_dataset_year` on `(parcel_id, dataset, year)` (ORM `:342-347`, mig `0003:69-73`).
- INDEX `idx_census_parcel_year` on `(parcel_id, year)` (ORM `:348`, mig `0003:75-79`).

Note the type: `census_snapshots.raw_data` is `JSON`, while
`property_events.raw_data` is `JSONB` (ORM `:398`, mig
`0004_property_events.py:51`). See §9.

### 1.5 Where the ORM and the migrations disagree

M7 ("ORM/schema drift", STATUS.md:66) is open and names three partial indexes.
The full list I found on and around these four tables:

1. **`uq_timeline_requests_parcel_inflight`** — partial unique index created at `0010:66-70`, absent from `TimelineRequest.__table_args__` (`app/models/parcels.py:147-152`). *(M7 as written.)*
2. **`uq_property_events_null_source_record`** — partial unique index created at `0009:48-52`, absent from `PropertyEvent.__table_args__` (`:412-427`). *(M7 as written.)*
3. **`idx_parcels_point_geog`** — expression index on `(point::geography)` created at `0010:82-84`, absent from `Parcel.__table_args__` (`:84-88`). *(M7 as written.)*
4. **`idx_parcels_address`** — GIN index on `to_tsvector('english', address)` created at `0001:67-73`, absent from the ORM. **Not named in M7.**
5. **CHECK-constraint name drift on `timeline_request_tasks`** — ORM says `ck_trt_source` / `ck_trt_status` (`:202-209`); the database has `ck_timeline_request_tasks_source` / `ck_timeline_request_tasks_status` (`0002:117-128`, `0008:35-39`). **Not named in M7.** This is the table M4 would modify. An `op.drop_constraint("ck_trt_source", ...)` written from the ORM would fail against production.
6. **Index-name drift** — ORM `index=True` on `TimelineRequest.parcel_id` (`:111`) and `TimelineRequestTask.timeline_request_id` (`:176`) implies `ix_*` names; the database carries `idx_timeline_requests_parcel_id` and `idx_trt_request`. Harmless today, a duplicate-index hazard for any future autogenerate.
7. **A third schema exists.** `tests/conftest.py:94-108` hand-writes `timeline_request_tasks` for SQLite with **no `ON DELETE CASCADE`** on the FK (`:96`, bare `REFERENCES timeline_requests(id)`) and no `idx_trt_request`. It does carry `UNIQUE (timeline_request_id, source)` (`:107`). *(M7 names `conftest.py` generally; the missing CASCADE is specific.)*

**What this implies for column vs row.** The drift is entirely additive
objects the ORM does not declare, plus names — no column type on these four
tables is in dispute, so neither shape lands on unstable ground. The asymmetry
is in what each shape *adds* to M7's surface: a per-year table is a fifth table
that must be declared in the ORM **and** hand-written a second time in
`tests/conftest.py`; a JSONB column is one `add_column` in each place. Item 5
above is a live trap for the migration itself regardless of shape.

---

## 2. Retention

**Task rows are kept per request, forever. Nothing prunes them.**

- **Within a request:** `create_request_tasks` (`app/services/imagery.py:207-254`) is `INSERT … ON CONFLICT (timeline_request_id, source) DO UPDATE SET status='queued', items_found=0, started_at=NULL, completed_at=NULL, error_message=NULL` (`:222-230`). A Celery redelivery of the same request therefore **resets** its task rows rather than duplicating them (the docstring says so at `:213-216`), and any prior outcome for that request is destroyed at that moment.
- **Across requests:** each run is a new `timeline_requests` row (`_create_queued_request`, `:98-128`), so a parcel accumulates one task row per (request, source). `uq_trt_request_source` (`0010:36-40`) makes that exactly one.
- **No upsert or replace across runs.** There is no code path that carries a prior request's task row forward.
- **No pruning.** `sweep_stranded_work` (`:449-553`) and `_fail_open_tasks` (`:431-446`) only *update* `status` / `completed_at` / `error_message`; neither deletes. There is no beat schedule — the janitor runs on `worker_ready` (`app/tasks/celery_app.py:116`).
- **The only deletion paths** are cascades from `parcels`: the FK chain `parcels → timeline_requests → timeline_request_tasks` is ON DELETE CASCADE at both hops (`app/models/parcels.py:109`, `:174`). Reachable via `scripts/remove_unverified_reverse_parcels.py:168` (`DELETE FROM parcels WHERE id = :id`) and, historically, the one-off `DELETE FROM timeline_requests WHERE parcel_id IS NULL` at `0010:73`. `scripts/seed_featured.py:219` deletes `featured_locations` rows only (`:212-216`), which do not cascade to requests.

Production shape (read-only, 2026-08-24, see §7): 338 requests over 184
parcels. 127 parcels have exactly one request; 57 have two or more; the
maximum is 13. Oldest request `2026-04-13`.

**What this implies for column vs row.** Cross-run failure history is already
free in *both* shapes, because the unit of history is the per-run
`timeline_requests` row, and it is never deleted. Whichever way outcomes are
stored, they inherit that. The difference is not whether the history exists but
whether "has (parcel, source, year) ever succeeded, on any run?" is a `GROUP
BY` over rows or an unnest-then-group over documents — see §4. One real
retention caveat applies to both: the ON CONFLICT reset at `:222-230` means a
redelivered request's earlier per-year outcomes are lost, so a design must
either accept that or write outcomes to a scope the reset does not clear.

---

## 3. Every per-year loop, and what each does on failure

Seven distinct sites. Four of them have no counter at all.

### (a) Landsat and Sentinel-2 — STAC search chunk loop

`_search_and_persist_source`, `app/tasks/timeline.py:246-269`. Grouping key:
**calendar year**, `range(start_year, end_year+1)` where `start_year` is 1984
for Landsat (`:68`) and 2015 for Sentinel-2 (`:80`), and `end_year` defaults to
`date.today().year` (`:236`). Both sources set `chunk_by_year: True`
(`:74`, `:86`).

Each year calls `_search_stac_with_retry` (`:97-135`), which retries
`{429, 500, 502, 503, 504}` and `httpx.RequestError` for 3 attempts with
exponential backoff, and re-raises the last exception.

- **(a) counter?** `failed_years += 1` (`:256`) — a **local integer** in the enclosing function, never persisted, discarded at return. Not `failed_requests`.
- **(b) logged?** Yes: WARNING `"STAC year chunk failed after retries; skipping"` with `source`, `year`, `error` (`:258-265`).
- **(c) distinguishable?** **Yes, here.** The exception object is in hand. A year that returns `[]` successfully takes the other branch (`:267`) and is indistinguishable from a year with data downstream — but at *this* site the two are separable.
- **(d) still `complete`?** Yes — `_set_task_status(…, "complete", …)` at `:435`. Only if **every** year failed does `:268-269` re-raise, which `_fetch_source` catches at `:168-171` and marks `failed`.

### (b) NAIP — no per-year fetch loop at all

`chunk_by_year: False` (`:62`). NAIP makes one search over
`2010-01-01/{current year}-12-31` (`:271-282`, start date `:56`) capped at 50
items (`:57`). Its only failure-shaped signal is the truncation warning at
`:293-302` — WARNING `"STAC search hit its item cap — results are truncated"`.
No counter, **no year attached** (it is a whole-source signal), task ends
`complete`. Not distinguishable: the comment at `:283-292` states the reason —
a response holding exactly its cap is indistinguishable from a complete answer,
and with no `sortby` the ordering that decides which items survive is
unspecified.

### (c) NAIP point-coverage gate — 14b59af

`stac_service.filter_groups_containing_point` (`app/services/stac.py:657-682`),
called at `app/tasks/timeline.py:322-336`. Grouping key: **year**, inherited
from `select_naip_items`' by-year grouping (`stac.py:785-789`). A year's mosaic
group survives only if at least one tile's footprint contains the point
(`stac.py:678`).

- **counter?** None.
- **logged?** Yes: WARNING `"Suppressing imagery year with no covering tile"` with `parcel_id`, `source`, `year`, `reason`, `tile_ids` (`timeline.py:327-336`). This is the richest per-year log in the codebase.
- **distinguishable?** **Yes, and it is a third category** — neither "upstream returned nothing" nor "request failed", but "upstream returned items and none of them covers this address". A boolean `failed` flag cannot represent it.
- **still `complete`?** Yes (`:435`).

### (d) Landsat / Sentinel-2 validation walk — e7d4c6d, and N1

`_validate_selection` (`app/services/stac.py:1098-1170`), reached from
`timeline.py:344-353`. Grouping key: **`period`** — `d.year` for Landsat
(`stac.py:1181`), `(d.year, (d.month-1)//3+1)` for Sentinel-2 (`stac.py:1202`).
On a selected item failing validation, every other same-period candidate is
walked, cloud-ranked (`:1121-1122`, `:1150-1165`); if none validates the period
is dropped.

- **counter?** None.
- **logged?** Yes, twice: WARNING `"%s item failed validation; trying fallbacks"` (`:1143-1147`) and WARNING `"No valid %s item for %s; skipping"` (`:1168`). The second is the message STATUS.md quotes.
- **distinguishable?** **No.** `_validate_asset` (`stac.py:1028-1080`) returns the same bare `False` for a missing asset key (`:1032-1039`), a non-allowlisted host (`:1042-1049`), a signing failure (`:1052-1059`), an HTTP ≥400 from the HEAD (`:1063-1070`), and a network error on the HEAD (`:1071-1078`). "This scene is broken" and "the signing endpoint is unhealthy" are the same value. `_sas_get` retries only 429 (`stac.py:342-347` — `if resp.status_code != 429: resp.raise_for_status()`), so a 503 on the signing endpoint is terminal on the first attempt, and the walk then re-signs every candidate against the same unhealthy endpoint. This is N1 (STATUS.md:309), confirmed at current line numbers.
- **still `complete`?** Yes (`timeline.py:435`).

### (e) USGS topo — no loop, four skip doors

There is **no per-decade loop over upstream requests**. `search_usgs_topo`
(`app/services/usgs_topo.py:62-103`) makes one TNM call;
`select_topo_items` (`:106-131`) groups the response by decade
(`decade = (year // 10) * 10`, `:117`) and picks one sheet per decade.
Failure-shaped outcomes, all in `_search_and_persist_topo`
(`timeline.py:465-553`) unless noted:

| door | site | counter | logged | distinguishable | task ends |
|---|---|---|---|---|---|
| whole-search failure | `usgs_topo.py:80` raises → `timeline.py:459-462` | n/a | ERROR `"USGS topo fetch failed"` | yes | **`failed`** |
| response hits its 100-row cap | `usgs_topo.py:89-97` | none | WARNING `"TNM query hit its row cap"` | **no** — a full page is indistinguishable from a complete answer | `complete` |
| product has no GeoTIFF url | `timeline.py:486-488` | none | **nothing — silent `continue`** | yes | `complete` |
| unparseable `publicationDate` | `timeline.py:496-505` | none | WARNING | yes | `complete` |
| missing `sourceId` | `timeline.py:513-518` | none | WARNING | yes | `complete` |

Two of those doors are **latent, not live**, and STATUS.md is right about one
of them: `select_topo_items` already drops items whose year will not parse
(`usgs_topo.py:114-116`), so the `publicationDate` guard at `timeline.py:496`
is unreachable. The same is true of the GeoTIFF-url skip:
`search_usgs_topo` already filters to items carrying `urls["GeoTIFF"]`
(`usgs_topo.py:99-103`), so `timeline.py:487` is unreachable too. **The live
topo doors are the cap and the missing `sourceId`.** This confirms STATUS.md's
2026-08-15 precision correction and extends it by one guard.

### (f) Decennial census

`_fetch_census_years`, `app/tasks/timeline.py:665-689`. Grouping key: **year**,
from `DECENNIAL_YEARS = [1990, 2000, 2010, 2020]` (`app/services/census.py:74`).

- **counter?** `failed_requests += 1` at `:684`, **only inside `except CensusApiError`**. A function-local integer, used once at `:723` and discarded.
- **logged?** On the exception path, WARNING `"Census decennial failed"` with `year` (`:685`). **On the `if data:` skip (`:670`), nothing at all** — no counter, no log at this level.
- **distinguishable?** **No.** `data == {}` arrives from three different upstream situations, all collapsed to the same empty dict before the loop sees it: a 204/404 (`census.py:264-269` → `None` → `{}` at `:189-190` / `:160-161`), a year with no decennial config (`census.py:177-180`), and every requested variable being dropped as unrecognised for the vintage (`census.py:210-229` returns `None` when `remaining` empties). The 404 is logged INFO `"Census API: no data for tract"` *inside the client* (`census.py:265-268`), but that log carries no parcel and does not reach the loop.
- **still `complete`?** Yes (`:735`), unless **all ten** requests raised (`:723-730`) — and a `{}` skip does not count toward that ten, so the all-failed check cannot see it.

### (g) ACS5

Same function, `timeline.py:692-715`. Grouping key: **year**, from
`ACS5_YEARS = [2009, 2012, 2015, 2018, 2021, 2023]` (`census.py:75`). Counter
`:711`, log `:712`, silent `if data:` skip `:697` — identical structure to (f).

One adjacent mechanism worth recording: `_VintageTracts.tract_for`
(`timeline.py:617-644`) resolves each year's tract against its own geography
vintage and, on a `GeocoderError`, **silently falls back to the stored tract**
(`:630-638`, WARNING logged). Which tract a year was actually fetched against
*is* persisted — on `census_snapshots.tract_fips` (`:675`, `:702`) — but only
for years that produced a row. For a year that produced nothing, the tract used
is unrecoverable.

### (h) Property — no year key

`_fetch_and_persist_property` (`timeline.py:800-892`). Counters
`queries_attempted` / `queries_failed` come off the adapter results
(`:829-830`) and feed only an all-or-nothing verdict (`:831-842`). Its natural
unit is the source record, not a period. Included here to be explicit: **the
property source has no per-year outcome to persist.**

### Summary

| # | source | site | key | counter | logged | can tell empty from failed | ends |
|---|---|---|---|---|---|---|---|
| a | landsat, sentinel2 | `timeline.py:246-269` | year | local `failed_years` | yes | **yes** | complete |
| b | naip | `timeline.py:271-302` | none (whole source) | none | yes (cap only) | no | complete |
| c | naip | `timeline.py:322-336` | year | none | yes, richly | **yes — third category** | complete |
| d | landsat, sentinel2 | `stac.py:1098-1170` | year / quarter | none | yes | **no** | complete |
| e | usgs_topo | `usgs_topo.py:89`, `timeline.py:513` | decade | none | yes | cap: no; skip: yes | complete |
| f | census decennial | `timeline.py:665-689` | year | local `failed_requests` | exception path only | **no** | complete |
| g | census acs5 | `timeline.py:692-715` | year | local `failed_requests` | exception path only | **no** | complete |
| h | property | `timeline.py:800-892` | — | local, all-or-nothing | yes | n/a | complete |

**What this implies for column vs row.** Two things, and the second matters
more than the first.

First, the write cost is not "persist a counter we already have". Two local
counters exist (`failed_years` at `:256`, `failed_requests` at `:661`) and both
are per-source scalars. At sites (c), (d), and (e) there is no counter at all.
Whichever shape is chosen, the work is introducing an outcome record at seven
sites across three files — and that cost is close to identical for a column and
for a table, since both are "call one recorder function here".

Second, and asymmetrically: at three of the seven sites — (d), (f)/(g), and the
cap half of (e) — **the code cannot tell absence from failure**, and at site (c)
there is a third state that is neither. So the value being stored is not a
boolean and not an error string; it is an enum wide enough for at least
`ok / failed / absent / indeterminate / suppressed`, plus a reason. That
constrains both shapes equally, but it rules out the cheapest version of the
JSONB option (a bare `{"1993": false}` map) — the document would have to carry
objects, not booleans, which is precisely the shape that is awkward to index
(§9).

---

## 4. What backfill reads today

`maybe_refetch_for_backfill`, `app/services/imagery.py:294-418`. Called from
exactly two places: `app/api/v1/imagery.py:96` and `app/api/v1/geocode.py:292`,
both only when an existing request was reused (`is_new == False`).

**Exactly what it inspects:**

| # | reads | site | test |
|---|---|---|---|
| 1 | `existing_req.status` | `:313` | must be `'complete'`, else return None |
| 2 | `parcel.census_tract_id` | `:318` | truthy |
| 3 | the `census` task row of **that one request** | `:319-327` | `not census_task or census_task.status == 'failed'` (`:328`) |
| 4 | `parcel.county` + `get_adapter_for_county` | `:335-338` | adapter exists |
| 5 | the `property` task row of that request | `:339-347` | `not prop_task or prop_task.status in ('skipped','failed')` (`:348`) |
| 6 | the `usgs_topo` task row of that request | `:355-363` | **`not topo_task`** only (`:364`) — its status is never examined |
| 7 | `max(created_at)` over the parcel's requests | `:382-387` | age vs `backfill_cooldown_hours`, default `6.0` (`app/config.py:72`) |

**What it cannot see.** Which years any source got. Whether `items_found`
changed between runs. Whether a year failed, was empty, or was suppressed.
Anything at all about `landsat`, `sentinel2`, or `naip` — those three sources
have **no trigger whatsoever**. Trigger 6 is a one-shot: once any run creates a
`usgs_topo` task row, the imagery half of backfill is permanently inert, no
matter how many years those sources are missing.

And what it produces is a **whole-pipeline re-run**: `_create_queued_request`
(`:402`) yields a bare request, and the worker rebuilds the full source list
from `_SOURCES` plus topo/census/property (`timeline.py:946-951`, `:984-1032`).
It cannot target a source, let alone a year. The comment at `:374-380` says so
and defers per-source scope to M3.

Nothing else decides to re-run a source. `sweep_stranded_work` (`:449-553`)
only marks rows failed; the heal scripts (§5) each build their own selection.

### The query backfill would need, in both shapes

Target question: *"parcels where Landsat 1993 has no snapshot and the last
attempt at it did not succeed."*

**Shape A — JSONB column** (`timeline_request_tasks.year_outcomes jsonb`,
document keyed by group, e.g. `{"1993": {"outcome": "failed", "reason": "…"}}`):

```sql
SELECT DISTINCT r.parcel_id
FROM timeline_request_tasks t
JOIN timeline_requests r ON r.id = t.timeline_request_id
WHERE t.source = 'landsat'
  AND (t.year_outcomes -> '1993' ->> 'outcome') IS DISTINCT FROM 'ok'
  AND r.created_at = (
        SELECT max(r2.created_at)
        FROM timeline_requests r2
        WHERE r2.parcel_id = r.parcel_id
      );
```

The latest-run subquery is forced: with one document per (request, source)
there is no per-year row to order or aggregate over. The broader question —
*"which (parcel, source, year) triples have never succeeded on any run"* —
requires unnesting first:

```sql
SELECT r.parcel_id, y.key AS group_key
FROM timeline_request_tasks t
JOIN timeline_requests r ON r.id = t.timeline_request_id
CROSS JOIN LATERAL jsonb_each(t.year_outcomes) AS y(key, value)
WHERE t.source = 'landsat'
GROUP BY 1, 2
HAVING count(*) FILTER (WHERE y.value ->> 'outcome' = 'ok') = 0;
```

Indexability: `->>` with `IS DISTINCT FROM` is not GIN-servable. Serving the
first query from an index means a GIN index (`jsonb_path_ops`) plus rewriting
the predicate as containment (`year_outcomes @> '{"1993":{"outcome":"failed"}}'`),
which cannot express "not ok" — so "never succeeded" stays a sequential scan
plus unnest either way. An expression B-tree on
`((year_outcomes -> '1993' ->> 'outcome'))` would serve one hardcoded year.

**Shape B — per-year table**
(`timeline_task_years(task_id, source, group_key, outcome, reason, …)`):

```sql
SELECT DISTINCT r.parcel_id
FROM timeline_task_years y
JOIN timeline_request_tasks t ON t.id = y.task_id
JOIN timeline_requests r ON r.id = t.timeline_request_id
WHERE y.source = 'landsat'
  AND y.group_key = '1993'
  AND y.outcome <> 'ok';
```

served by a plain B-tree on `(source, group_key, outcome)`. And the broader
question is an ordinary aggregate:

```sql
SELECT r.parcel_id, y.group_key
FROM timeline_task_years y
JOIN timeline_request_tasks t ON t.id = y.task_id
JOIN timeline_requests r ON r.id = t.timeline_request_id
WHERE y.source = 'landsat'
GROUP BY 1, 2
HAVING count(*) FILTER (WHERE y.outcome = 'ok') = 0;
```

**What this implies for column vs row.** Both shapes can express every question
backfill would want to ask; they differ in whether the cross-run question needs
an unnest before it can aggregate, and in whether a targeted single-year lookup
can be indexed generically or only per-year. Separately and relevant to either:
backfill's trigger set is today three all-or-nothing task-status probes, and its
output is an untargeted full-pipeline re-run — so a per-year signal is
*necessary but not sufficient* for the heal loop M4 is meant to close. The
targeting half is M3.

---

## 5. What the heal scripts read

### `scripts/revalidate_landsat.py`

Selection (`:41-49`):

```sql
SELECT parcel_id FROM imagery_snapshots WHERE source = 'landsat' GROUP BY parcel_id;
```

Every parcel with any Landsat row at all — **184 of 184 in production**. It
targets nothing; it re-runs the whole pipeline for every parcel and relies on
re-validation plus reconciliation to fix whatever was broken (`:2-9`,
`:64-86`). **Collapses into a per-year ledger query**: the script exists because
the ledger does not, and its natural predicate is "parcels holding a Landsat
group whose last recorded outcome was a validation drop."

### `scripts/requeue_empty_property.py`

Selection (`find_candidates`, `:33-75`) — the latest request per parcel joined
to its `property` task:

```sql
SELECT p.id, p.county
FROM parcels p
JOIN (SELECT parcel_id, max(created_at) AS created_at
      FROM timeline_requests GROUP BY parcel_id) latest ON latest.parcel_id = p.id
JOIN timeline_requests r ON r.parcel_id = latest.parcel_id
                        AND r.created_at = latest.created_at
JOIN timeline_request_tasks t ON t.timeline_request_id = r.id
WHERE r.status = 'complete'
  AND t.source = 'property'
  AND t.status = 'complete'
  AND t.items_found = 0
  AND p.county IS NOT NULL;
```

then filtered in Python to counties that still have an adapter (`:71-74`).
**Does not collapse.** Its subject is "complete-with-zero", an aggregate over
the whole source, and property has no period key (§3h). Note this predicate is
already expressible today against the existing schema — which is why the script
is one query and not a Python reconstruction.

### `scripts/heal_tract_vintage_gaps.py`

Selection (`_parcels_with_vintage_gaps`, `:49-81`) — one broad SQL pull:

```sql
SELECT p.id, p.census_tract_id, p.latitude, p.longitude, c.year
FROM parcels p
JOIN census_snapshots c ON c.parcel_id = p.id AND c.dataset = 'acs5'
WHERE p.census_tract_id IS NOT NULL
  AND p.latitude IS NOT NULL
  AND p.longitude IS NOT NULL
ORDER BY p.id;
```

followed by **the ledger, reconstructed in Python** (`:69-81`): group years per
parcel; keep a parcel only if it holds at least one of
`CURRENT_VINTAGE_YEARS = (2021, 2023)` (`:42`, tested `:76-77`); report the
missing members of `HEALABLE_YEARS = (2012, 2015, 2018)` (`:38`, tested
`:78-80`). **Collapses**, and the interesting part is what disappears with it:
the `2021 or 2023 present` test at `:76-77` is a *proxy* for "this parcel was
ever fetched", stated as such in the comment at `:40-42`. A per-year ledger
replaces an inference with a fact.

### `scripts/requeue_parcels.py`

**Runs no selection query.** Parcel ids come from `argv`; `_known_parcels`
(`:184-188`) only validates that they exist
(`SELECT id FROM parcels WHERE id IN (…)`). Its substance is the deployed-SHA
gate (`:98-181`). **Does not collapse** — it is a delivery mechanism, not a
finder.

**What this implies for column vs row.** Two of the four collapse, and they are
exactly the two whose subject has a period key. Both collapsed forms are the
"has this (parcel, source, group) ever succeeded" query from §4, so the shape
that answers that question cheaply is the shape that retires these scripts.
Neither collapses more readily into a column than into a table — but
`heal_tract_vintage_gaps.py`'s Python reconstruction (`:69-81`) is a preview of
what a JSONB document forces the *reader* to do in code, at every call site,
which the table shape does in SQL once.

---

## 6. Reconciliation's grouping key

`reconcile_source_snapshots` (`app/services/imagery.py:598-687`) buckets both
this run's selection (`:644-646`) and the parcel's existing rows (`:660-665`)
through a single lambda taken from:

```python
SELECTION_SCOPES: dict[str, Callable[[date], tuple[int, ...]]] = {
    "year":    lambda d: (d.year,),
    "quarter": lambda d: (d.year, (d.month - 1) // 3 + 1),
    "decade":  lambda d: ((d.year // 10) * 10,),
}
```

— `app/services/imagery.py:591-595`. The scope name arrives as a parameter:
from the source config's `selection_scope` for STAC sources
(`timeline.py:429`; values `"year"` `:60`, `"year"` `:72`, `"quarter"` `:84`)
and hardcoded `"decade"` for topo (`timeline.py:545`).

**But it is not the only derivation.** The same three rules are re-derived,
independently, in five other places:

| rule | site |
|---|---|
| year | `select_naip_items` — `by_year[_capture_date(item).year]`, `stac.py:785-789` |
| year | `select_landsat_items` — `by_year[_capture_date(item).year]`, `stac.py:914-918` |
| quarter | `select_sentinel_items` — `(d.year, (d.month - 1) // 3 + 1)`, `stac.py:936-942` |
| decade | `select_topo_items` — `(year // 10) * 10`, `usgs_topo.py:112-118` |
| year / quarter | `_validate_selection` callers — `period=lambda d: d.year` (`stac.py:1181`), `period=lambda d: (d.year, (d.month-1)//3+1)` (`stac.py:1202`) |

The quarter rule in particular is duplicated **verbatim** in three files
(`imagery.py:593`, `stac.py:941`, `stac.py:1202`). And the topo path derives its
key from an `int` year (`_publication_year`, `usgs_topo.py:174-181`) *before*
anything becomes a `date`, so `SELECTION_SCOPES["decade"]` — which takes a
`date` — is not directly reusable there.

The output types also differ: `SELECTION_SCOPES` returns a tuple (`(2021, 3)`),
the selectors return a bare `int` or a tuple. **No text encoding of a group key
exists anywhere in the codebase** — there is no `"2021Q3"` or `"1960s"` string
to adopt.

**What this implies for column vs row.** There is exactly one named, reusable
definition and five hand-inlined copies of the same three rules, so a
`group_key` column has a canonical function to call but adopting it means
touching five call sites either way. Two facts bear on the shape: a per-year
table's `group_key` needs a single **text** encoding that does not exist yet
and must be invented (and then must round-trip back to a `date` range for any
targeted refetch); a JSONB document's keys need the same encoding, since JSON
object keys are strings. So this cost is shared. What is *not* shared is the
schema's ability to enforce it — a table can carry a CHECK on `group_key`
format and a UNIQUE on `(task_id, group_key)`; a document cannot.

---

## 7. Prod scale (read-only)

Access **was** available. Method: `fly ssh console -a log0s-plotline-api -C
"python -c …"` against machine `825d69b7e46618` (lax), using `app.db.SessionLocal`
with `SELECT`-only statements. No writes, no schema queries beyond counts.
Snapshot taken 2026-08-24.

### Row counts

| table | rows |
|---|---|
| `parcels` | 184 |
| `timeline_requests` | 338 |
| `timeline_request_tasks` | 1,921 |
| `imagery_snapshots` | 14,534 |
| `census_snapshots` | 1,442 |
| `property_events` | 383 |

Mean tasks per request: **5.68**.

### `timeline_request_tasks` in the last 30 days

Requests created in the window: **253**; task rows attached to them: **1,518**
(79% of all task rows ever — the oldest request is 2026-04-13).

| source | complete | failed | skipped |
|---|---|---|---|
| census | 253 | — | — |
| landsat | 252 | 1 | — |
| naip | 250 | 3 | — |
| sentinel2 | 253 | — | — |
| property | 58 | 1 | 194 |
| usgs_topo | 229 | 24 | — |

Note the shape of the M4 problem in this table: `landsat` shows **one** failed
task in 30 days, against a known production incident that cost one parcel 20 of
its 43 Landsat years. Per-source status is close to a constant `complete`; it
is not a signal.

### Rows a per-year ledger would carry

Attempted groups per task per source, from the code:

| source | natural key | attempted per run | basis |
|---|---|---|---|
| landsat | year | **43** (1984–2026) | `timeline.py:235-243`, config `:68` |
| sentinel2 | year (search) / quarter (selection) | **12** / **48** | config `:80-88`; `select_sentinel_items` `stac.py:941` |
| naip | year | **≤17** (2010–2026) | config `:56`; not chunked, so the attempted set is only knowable post-hoc |
| usgs_topo | decade | variable | `select_topo_items` `usgs_topo.py:117` |
| census | year | **10** (4 decennial + 6 acs5) | `census.py:74-75` |
| property | — | 0 | no period key |

Observed rows *landed* per parcel per source (all time):

| source | rows | parcels | rows/parcel |
|---|---|---|---|
| landsat | 7,903 | 184 | 43.0 |
| sentinel2 | 4,382 | 184 | 23.8 |
| naip | 1,267 | 183 | 6.9 |
| usgs_topo | 982 | 157 | 6.3 |
| census acs5 | 1,028 | 184 | 5.6 |
| census decennial | 414 | 184 | 2.3 |

Landsat distinct years per parcel: **min 34, median 43, max 43** — every parcel
is at or near the theoretical ceiling, which is why a 20-year loss on one
parcel is invisible against the aggregate.

**Estimate.** A ledger recording one row per *attempted* group, per task:
43 (landsat) + 48 (S2 quarters) + ~17 (NAIP) + ~10 (topo decades) + 10 (census)
≈ **128 rows per request**; ~92 if S2 is recorded by year rather than quarter.
Against 338 existing requests that is **31k–43k rows today** — roughly 2–3× the
current `imagery_snapshots` table — accruing at ~253 requests / 30 days, i.e.
**~23k–32k rows per 30 days** at current traffic. Trivial for Postgres.

The JSONB alternative adds **zero rows**: one column on 1,921 existing rows,
each document carrying ~128 keys.

**What this implies for column vs row.** Absolute size decides nothing at this
scale — 43k rows is noise, and the row count is not an argument against the
table. The number that *does* bear on the choice is the 79% concentration in the
last 30 days against a 4-month history: this table grows with traffic, and a
per-year table grows ~23× faster than the task table it hangs off, so whichever
shape is chosen should be picked on query ergonomics rather than on a size
projection that both shapes survive comfortably.

---

## 8. Consumers of task status

### Backend

| consumer | site | reads |
|---|---|---|
| `TimelineRequestTaskResponse` | `app/schemas/imagery.py:17-27` | `source`, `status`, `items_found`, `started_at`, `completed_at`, `error_message` (`from_attributes`) |
| `TimelineRequestResponse` | `app/schemas/imagery.py:30-41` | embeds `tasks: list[…]` |
| `GET /timeline-requests/{id}` | `app/api/v1/imagery.py:111-138`, validation at `:129` | the whole task list |
| `maybe_refetch_for_backfill` | `app/services/imagery.py:294-418` | §4 |
| `sweep_stranded_work` / `_fail_open_tasks` | `app/services/imagery.py:431-553` | writes `status` only |
| `scripts/requeue_empty_property.py` | `:53-61` | `source`, `status`, `items_found` — the only script that reads task rows |

`items_found` is the only quantitative field, and it is set from a **whole-table
count**, not from this run's work: `count_imagery_snapshots`
(`app/services/imagery.py:559-572`) and `count_census_snapshots`
(`app/services/demographics.py:134-143`) both count every row for the parcel,
including prior runs' (`timeline.py:433`, `:548`, `:733`).

### Frontend

All of it comes from the one endpoint, via `fetchTimelineRequest`
(`frontend/src/api/imagery.ts:22`), typed at
`frontend/src/types/index.ts:64-81`.

| consumer | site | behaviour |
|---|---|---|
| `TaskRow` | `ParcelInfo.tsx:17-53`, rendered `:249-254` | per-source dot; `complete` → `"{items_found} items"`, else `loading… / failed / skipped / queued` |
| `SourceIssueRow` | `ParcelInfo.tsx:57-70`, rendered `:268-274` | after the run, for `failed`/`skipped` only (`:131-133`); `failed` → "we'll retry on your next visit", `skipped` → `error_message` |
| `taskStatus(source)` | `ParcelInfo.tsx:134-135`, passed `:287-288` | hands `census` / `property` status to the panel |
| `DemographicsPanel` | `DemographicsPanel.tsx:20-26`, `:78-106` | `queued`/`processing` → "data will appear once the timeline finishes"; `failed` → "couldn't load census/property records"; **otherwise → "No census or property records found for this address"** (`:104-106`) |
| `progressLabel` | `Timeline.tsx:57-67`, called `:378-379` | `"{label} ({items_found})"` for complete, `"Loading {label}..."` for processing |

**The surface a "years failed" signal must reach is small: one Pydantic model,
one endpoint, one TypeScript interface, three components.** Two of those
components already render the M4 lie in user-visible text —
`DemographicsPanel.tsx:104-106` says "No census or property records found for
this address" for a task that ended `complete` with missing years, and
`ParcelInfo.tsx:265-267` reports a bare `snapshots.length` with no notion of
which periods are absent.

**What this implies for column vs row.** Nothing, and that is the finding. Every
consumer above reads a **derived summary** through a Pydantic model, never the
storage. Whichever shape wins, the API would expose something like
`groups_missing: string[]` or a per-source count, computed server-side — the
serialization boundary at `app/schemas/imagery.py:17-27` insulates all six
consumers from the choice. The consumer surface is not a tiebreaker.

---

## 9. Existing JSONB usage

Two JSON-typed columns exist in the schema:

- **`property_events.raw_data` — `JSONB`** (`app/models/parcels.py:398`; `0004_property_events.py:51`)
- **`census_snapshots.raw_data` — `JSON`, not `JSONB`** (`app/models/parcels.py:323`; `0003_census_snapshots.py:54`)

Both are written as pre-serialized text bound into raw SQL —
`json.dumps(raw_data) if raw_data else None` at
`app/services/property_events.py:90` and `app/services/demographics.py:126` —
and read back **whole**: `SELECT … raw_data FROM property_events`
(`property_events.py:143`) and `SELECT … raw_data FROM census_snapshots`
(`demographics.py:157`), each followed by an
`if isinstance(raw, str): raw = json.loads(raw)` shim in Python
(`property_events.py:153`, `demographics.py:167-171`) because SQLite hands the
column back as text.

A repo-wide grep across `backend/app`, `backend/alembic`, and `scripts` for
`->>`, `->`, `jsonb_*`, `json_*`, `.astext`, and jsonb containment returns
**no query that reads inside a JSON document**. No migration creates a GIN index
on either column; the only GIN index in the schema is
`idx_parcels_address` on `to_tsvector('english', address)`
(`0001_initial.py:66-72`).

**Finding: the codebase has never queried JSON by content, in SQL, anywhere.**
It has one column typed `json` rather than `jsonb`, so even "we already use
JSONB" is only half true as precedent.

One further constraint that bears directly on this: **the test suite runs on
SQLite.** `tests/conftest.py:94-108` hand-writes the DDL with `TEXT PRIMARY
KEY`, and the production code already carries dialect branches for exactly this
reason — `_is_postgres` (`app/services/imagery.py:783-788`), the
PostGIS/NULL split in `_bbox_select_sql` vs `_bbox_select_sql_sqlite`
(`:791-806`), and the `isinstance(raw, str)` JSON shims above. SQLite has
neither `jsonb_each` nor GIN.

**What this implies for column vs row.** A JSONB `year_outcomes` column would be
the first content-queried JSON in the repo, and every query in §4's Shape A
(`->`, `->>`, `jsonb_each`) is unavailable in the test database — so each such
query would need either a dialect branch alongside the three that already exist,
or a Postgres-only test path that the current harness does not have. A per-year
table is ordinary rows and ordinary B-trees, and runs identically on both
dialects. This is the sharpest asymmetry the investigation found, and it is a
fact about the harness, not about Postgres.

---

## Consolidated UNVERIFIED register

1. **Production catalog names.** §1 describes constraints and indexes as the *migrations* create them. I did not query `pg_indexes` / `pg_constraint` on production — prod access was scoped to the row counts in item 7. If a constraint was ever renamed or dropped by hand, this document would not know. **This matters for §1.5 item 5**, which predicts that an `op.drop_constraint("ck_trt_source", …)` would fail; that prediction is inferred from migration source, not observed.
2. **NAIP's attempted-year set.** NAIP is not chunked (`timeline.py:271-282`), so the set of years it *tried* is not knowable from code at all. The "≤17" in §7 is an upper bound from the 2010 start date (`:56`) and the current year — not a measurement.
3. **The 128-rows-per-request estimate** (§7) assumes a ledger records one row per *attempted* group, including groups that yielded nothing. A design that records only failures would be an order of magnitude smaller. I have no basis in the code or the record to prefer either, so the estimate should be read as an upper bound on the row shape.
4. **Whether `census_snapshots.raw_data` being `json` rather than `jsonb`** (§9) was deliberate. Nothing in the repo, the migrations, or STATUS.md says. `property_events.raw_data`, added one migration later, is `jsonb`.
5. **Consumers outside this repository.** §8 enumerates readers found in this repo. A dashboard, notebook, or ad-hoc script living elsewhere would not appear.
6. **The prod snapshot is a single point in time** (2026-08-24). The "last 30 days" window is relative to that moment, and the 24 `usgs_topo` failures in it are a count, not a diagnosis — I did not determine whether they share a cause.
7. **Reachability of the two latent topo doors** (§3e — the GeoTIFF-url skip at `timeline.py:487` and the `publicationDate` skip at `:496`) is argued from the upstream filters at `usgs_topo.py:99-103` and `:114-116`. It is a source-reading argument, not an observation; a TNM response shape that defeats those filters would make them live.
8. **Whether the ON CONFLICT reset in `create_request_tasks`** (`imagery.py:222-230`) has ever actually discarded per-source outcomes in production. It is reachable by construction (Celery `acks_late` redelivery, per the docstring at `:213-216`); I found no evidence either way that it has fired.

---

## Premises in the prompt that I found to be wrong

1. **"the S2 relaxed-fallback walk (e7d4c6d)".** `e7d4c6d` is *"feat: give Sentinel-2 the validation fallback Landsat already had"* — it is the S2 **validation** fallback walk, not a relaxed one. Nothing about the walk relaxes a criterion; it swaps in the next-best same-quarter candidate against the same validation test (`stac.py:1187-1205` → `:1098-1170`). The mechanism is otherwise exactly as the prompt describes.

2. **"the selection query each one runs" — for all four heal scripts.** `scripts/requeue_parcels.py` runs **no selection query**. Its parcel ids come from `argv`; the only DB read is an existence check (`:184-188`). §5 reports it as such.

3. **"the Landsat 'No valid Landsat item for year N; skipping' path"** as a single known door alongside the census `if data:` skips. That message lives at `stac.py:1168`, inside `_validate_selection` — the *validation* path. The Landsat **search** loop has a different skip with a different message (`"STAC year chunk failed after retries; skipping"`, `timeline.py:258-265`). These are two distinct doors on the same source, and only one of them can distinguish failure from absence (§3a vs §3d).

4. **"Every per-year loop … For … USGS topo".** USGS topo has **no per-decade loop over upstream requests**. It makes one TNM search (`usgs_topo.py:62-103`) and groups the response by decade afterwards (`:106-131`). Its failure-shaped outcomes are the response cap, two item-level skips, and a whole-search failure that marks the task **`failed`** rather than `complete` (`timeline.py:457-462`) — §3e reports all of them, and adds a fifth (silent) skip the record had not named.

5. **"the NAIP point-coverage gate (14b59af)"** listed among per-year loops. It is a per-year *outcome*, correctly, but it is a filter over already-selected groups (`stac.py:657-682`), not a fetch loop. NAIP has no per-year fetch at all (§3b). This does not change what the gate contributes to M4 — it produces exactly the third-category outcome §3 flags as the hardest to model.

### Record-keeping note

Per CLAUDE.md, discoveries belong in STATUS.md in the same batch. This session
was scoped to "report only … commit the report only", so **I have not updated
`docs/audits/2026-08-second-audit/STATUS.md`**. Four findings here would change
rows there if carried across, and are recorded so they are not lost:

- **M7 is understated by three items** — §1.5 items 4, 5, 6. Item 5 (the `ck_trt_*` name drift on `timeline_request_tasks`) is the one that would bite M4's own migration.
- **A fifth silent topo door exists** — the GeoTIFF-url skip at `timeline.py:486-488` has no log at all, unlike its four siblings. It is latent (§3e), like the `publicationDate` guard the record already classifies that way.
- **Backfill has no imagery trigger** — `maybe_refetch_for_backfill` never examines `landsat`, `sentinel2`, or `naip`, and its `usgs_topo` probe tests row *absence* only (`imagery.py:355-364`). Once any run creates a topo row, the imagery half of backfill is permanently inert. The M4 row says "backfill only triggers on failed/missing tasks"; for three of six sources it does not trigger at all.
- **The codebase has never queried JSON by content** (§9), and the test harness is SQLite — which constrains the JSONB option in a way no row in STATUS.md currently records.

Separately: `CLAUDE.md`'s `scripts/` listing omits four scripts that exist —
`backfill_census_housing.py`, `requeue_empty_property.py`,
`remove_uncovered_snapshots.py`, `remove_unverified_reverse_parcels.py`. The
prompt's item 5 named one of them, so the omission is load-bearing for anyone
navigating from that listing.
