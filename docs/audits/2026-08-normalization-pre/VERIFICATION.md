# Normalization pre-flight verification

Report-only. Verifies the state the imagery-normalization ADR
(`docs/adr/0001-imagery-normalization.md`, status Proposed) assumes, against
the repo at HEAD and against production, before any migration work is
drafted. No application code, schema, or script was changed to produce this
report.

**HEAD verified against:** `c808d5da26da9b81a8d1920f04289d4ee7cc60e9`
(2026-08-27 20:04:40 -0600).

## Summary

| # | Item | Verified state | Confidence | Blocks migration prompt? |
|---|---|---|---|---|
| 1 | M4/M3 deploy state | Both landed on main and deployed; API/worker both at `fbdc2f7`; prod ledger has 35,377 real rows across 5 outcomes and 6 sources | High — direct SHA ancestry checks + live prod queries | No |
| 2 | INVESTIGATION.md §6/§8 extraction | §6 matches ("Reconciliation's grouping key"). §8 does **not** match — it is "Consumers of task status", not an `imagery_snapshots` read-site enumeration. No section in the document is that enumeration; closest are §4 and §5 (partial, backfill/heal-script scoped) | High for §6; the §8 premise is confirmed wrong | Documentation gap, not a code blocker — see item 3 |
| 3 | Fresh read-site inventory | 20 distinct call sites at HEAD across `app/services/imagery.py`, `app/api/v1/imagery.py`, `app/api/v1/featured.py`, `app/services/preview_renderer.py`, tests, and the ORM model/migrations. INVESTIGATION.md has no comparable list to diff against (see item 2) | High for the inventory itself | No, but the ADR's "every read site" claim needs re-derivation from this table, not from §8 |
| 4 | group_key reality check | **The ADR's rule 2 has already shipped.** `encode_group_key`/`decode_group_key` (`imagery.py:1023-1048`) is now the single encoding, and all five sites INVESTIGATION.md §6 found hand-inlined are rewritten to call it (`stac.py:889,1018,1052,1147,1375,1401`; `usgs_topo.py:150`) | High — read every call site | No — this ADR premise is stronger than assumed, not weaker |
| 5 | STATUS.md state | M4 and M3 both **Resolved**, deployed, and swept in production (M3: `5f3aa7d`, deployed 2026-08-27T15:42Z; M4: ledger live since 2026-08-26T00:51:55Z, first sweep 2026-08-26). Normalization ADR is item 1 of the "Scheduled" sequence, not yet started | High — direct quotes | No |
| 6 | Local prediction inputs | 1,382 distinct `(stac_collection, stac_item_id)` pairs against 3,295 total local rows; **269 duplicate `(parcel_id, source, group_key)` groups** across 43 parcels, all but 3 groups on `sentinel2`; 141 rows carry non-empty `additional_cog_urls`, and of the 162 URLs inside them, only 50 match some row's `cog_url` elsewhere in the table | High — queries run and shown below | **Yes, for the local DB specifically** — see item 6 note. Not evidence about prod, which items 1c/5 show has already been swept under year-grouping |

**What blocks the migration prompt:** nothing found here blocks drafting it.
The one thing that changes the prompt's premises materially is item 4: the
ADR's rule 2 is not "make the five sites share an encoding," it already
happened — the migration only needs to make `group_key` a first-class column
carrying that same string, not invent the encoding. Item 6's duplicate-group
count is a local-dev-DB fact (never swept under year-grouping), not a
production fact, and should not be read as a duplication estimate for the
prod migration — item 1c and item 5 show prod's `imagery_snapshots` table has
already had its S2 quarter-duplication removed by the G8 sweep.

---

## 1. M4/M3 deploy state

### 1a. Landing commits on `main`

| Commit | Full SHA | What landed | Date | Ancestor of HEAD? |
|---|---|---|---|---|
| `0814d7e` | `0814d7eba060d67af3ae2c4ba5fcbaa5befec80e` | `timeline_task_years` migration (`backend/alembic/versions/0011_timeline_task_years.py`) | 2026-08-25 17:30:58 -0600 | Yes |
| `ae740cf` | `ae740cf525c4a5aa389e4497168bdad97389689f` | `TimelineRequest.sources[]` / `.origin` columns (`backend/alembic/versions/0012_request_scope_and_origin.py`) | 2026-08-26 15:34:34 -0600 | Yes |
| `a6c7800` | `a6c780015c96dcb2440245636a700b8adf7bffee` | `maybe_refetch_for_backfill` reading the ledger (`app/services/ledger.py`) | 2026-08-26 15:46:44 -0600 | Yes |

Verified with `git rev-parse` and `git merge-base --is-ancestor <sha> HEAD`
for each; all three returned success.

### 1b. Deploy state

`curl https://log0s-plotline-api.fly.dev/api/v1/health`:

```json
{"status":"ok","db":"connected","redis":"connected","version":{"sha":"fbdc2f7e0e8686dea4b4302bd0a3234b1d1eaed7","built":"2026-08-27T23:16:41Z"}}
```

`fly image show -a plotline-worker`: both machines' `GH_SHA` label is
`fbdc2f7e0e8686dea4b4302bd0a3234b1d1eaed7`.

`fly image show -a log0s-plotline-api`: both machines' `GH_SHA` label is the
same `fbdc2f7e...`.

`git merge-base --is-ancestor <sha> fbdc2f7e...` confirmed true for all three
of `0814d7e`, `ae740cf`, and `a6c7800`. **All three M4/M3 landing commits are
deployed on both the API and the worker**, as of the same build
(2026-08-27T23:16:41Z).

### 1c. Ledger contents in production

Method: `fly ssh console -a plotline-worker -C "python -"`, piping a script
that reads `DATABASE_URL` from the worker's own environment (asyncpg driver
name swapped for `psycopg2`, `?ssl=require` rewritten to `?sslmode=require`
since `psycopg2` doesn't accept the asyncpg-style query param), `SELECT`-only.

Schema, from `information_schema.columns` (differs from the prompt's
assumption only in that it doesn't assume — this is what's actually there):

```
id           uuid
task_id      uuid
source       text
group_key    text
outcome      text
reason       text
detail       text
created_at   timestamp with time zone
```

```sql
SELECT count(*), min(created_at), max(created_at) FROM timeline_task_years;
```
→ **35,377 rows**, `min = 2026-08-26 02:16:44.621472+00`, `max = 2026-08-27 22:00:44.961932+00`.

```sql
SELECT outcome, count(*) FROM timeline_task_years GROUP BY outcome ORDER BY count(*) DESC;
```

| outcome | count |
|---|---|
| ok | 30,686 |
| absent | 4,621 |
| failed | 34 |
| suppressed | 19 |
| indeterminate | 17 |

```sql
SELECT source, count(*) FROM timeline_task_years GROUP BY source ORDER BY count(*) DESC;
```

| source | count |
|---|---|
| landsat | 16,383 |
| naip | 6,494 |
| sentinel2 | 4,548 |
| census_acs5 | 3,582 |
| usgs_topo | 2,391 |
| census_decennial | 1,979 |

This matches STATUS.md's M4 row narrative (first sweep 2026-08-26
02:16:35Z–03:04:07Z, baseline 16,244 rows at 03:07Z) plus roughly a day and a
half of subsequent traffic and heals — the row count growing from 16,244 to
35,377 is consistent with the M3 acceptance heals (P1–P3) and the ops-batch
sweep STATUS.md also records running in that window, not a new anomaly.

---

## 2. INVESTIGATION.md extraction

`docs/audits/2026-08-m4-design/INVESTIGATION.md` exists. Its section headers:

```
1. Current schema, exactly
2. Retention
3. Every per-year loop, and what each does on failure
4. What backfill reads today
5. What the heal scripts read
6. Reconciliation's grouping key
7. Prod scale (read-only)
8. Consumers of task status
9. Existing JSONB usage
Consolidated UNVERIFIED register
Premises in the prompt that I found to be wrong
```

**§6 matches** the prompt's "five inlined grouping derivations / group_key
material" request. Reproduced verbatim:

> ## 6. Reconciliation's grouping key
>
> `reconcile_source_snapshots` (`app/services/imagery.py:598-687`) buckets both
> this run's selection (`:644-646`) and the parcel's existing rows (`:660-665`)
> through a single lambda taken from:
>
> ```python
> SELECTION_SCOPES: dict[str, Callable[[date], tuple[int, ...]]] = {
>     "year":    lambda d: (d.year,),
>     "quarter": lambda d: (d.year, (d.month - 1) // 3 + 1),
>     "decade":  lambda d: ((d.year // 10) * 10,),
> }
> ```
>
> — `app/services/imagery.py:591-595`. The scope name arrives as a parameter:
> from the source config's `selection_scope` for STAC sources
> (`timeline.py:429`; values `"year"` `:60`, `"year"` `:72`, `"quarter"` `:84`)
> and hardcoded `"decade"` for topo (`timeline.py:545`).
>
> **But it is not the only derivation.** The same three rules are re-derived,
> independently, in five other places:
>
> | rule | site |
> |---|---|
> | year | `select_naip_items` — `by_year[_capture_date(item).year]`, `stac.py:785-789` |
> | year | `select_landsat_items` — `by_year[_capture_date(item).year]`, `stac.py:914-918` |
> | quarter | `select_sentinel_items` — `(d.year, (d.month - 1) // 3 + 1)`, `stac.py:936-942` |
> | decade | `select_topo_items` — `(year // 10) * 10`, `usgs_topo.py:112-118` |
> | year / quarter | `_validate_selection` callers — `period=lambda d: d.year` (`stac.py:1181`), `period=lambda d: (d.year, (d.month-1)//3+1)` (`stac.py:1202`) |
>
> The quarter rule in particular is duplicated **verbatim** in three files
> (`imagery.py:593`, `stac.py:941`, `stac.py:1202`). And the topo path derives its
> key from an `int` year (`_publication_year`, `usgs_topo.py:174-181`) *before*
> anything becomes a `date`, so `SELECTION_SCOPES["decade"]` — which takes a
> `date` — is not directly reusable there.
>
> The output types also differ: `SELECTION_SCOPES` returns a tuple (`(2021, 3)`),
> the selectors return a bare `int` or a tuple. **No text encoding of a group key
> exists anywhere in the codebase** — there is no `"2021Q3"` or `"1960s"` string
> to adopt.
>
> **What this implies for column vs row.** There is exactly one named, reusable
> definition and five hand-inlined copies of the same three rules, so a
> `group_key` column has a canonical function to call but adopting it means
> touching five call sites either way. Two facts bear on the shape: a per-year
> table's `group_key` needs a single **text** encoding that does not exist yet
> and must be invented (and then must round-trip back to a `date` range for any
> targeted refetch); a JSONB document's keys need the same encoding, since JSON
> object keys are strings. So this cost is shared. What is *not* shared is the
> schema's ability to enforce it — a table can carry a CHECK on `group_key`
> format and a UNIQUE on `(task_id, group_key)`; a document cannot.

**§8 does not match.** Its actual title is "Consumers of task status," and its
content is a Pydantic/API/frontend consumer inventory for task-status fields
(`items_found`, `status`, etc.) — not an `imagery_snapshots` read-site
enumeration. Reproduced verbatim, for the record:

> ## 8. Consumers of task status
>
> ### Backend
>
> | consumer | site | reads |
> |---|---|---|
> | `TimelineRequestTaskResponse` | `app/schemas/imagery.py:17-27` | `source`, `status`, `items_found`, `started_at`, `completed_at`, `error_message` (`from_attributes`) |
> | `TimelineRequestResponse` | `app/schemas/imagery.py:30-41` | embeds `tasks: list[…]` |
> | `GET /timeline-requests/{id}` | `app/api/v1/imagery.py:111-138`, validation at `:129` | the whole task list |
> | `maybe_refetch_for_backfill` | `app/services/imagery.py:294-418` | §4 |
> | `sweep_stranded_work` / `_fail_open_tasks` | `app/services/imagery.py:431-553` | writes `status` only |
> | `scripts/requeue_empty_property.py` | `:53-61` | `source`, `status`, `items_found` — the only script that reads task rows |
>
> `items_found` is the only quantitative field, and it is set from a **whole-table
> count**, not from this run's work: `count_imagery_snapshots`
> (`app/services/imagery.py:559-572`) and `count_census_snapshots`
> (`app/services/demographics.py:134-143`) both count every row for the parcel,
> including prior runs' (`timeline.py:433`, `:548`, `:733`).
>
> ### Frontend
>
> All of it comes from the one endpoint, via `fetchTimelineRequest`
> (`frontend/src/api/imagery.ts:22`), typed at
> `frontend/src/types/index.ts:64-81`.
>
> | consumer | site | behaviour |
> |---|---|---|
> | `TaskRow` | `ParcelInfo.tsx:17-53`, rendered `:249-254` | per-source dot; `complete` → `"{items_found} items"`, else `loading… / failed / skipped / queued` |
> | `SourceIssueRow` | `ParcelInfo.tsx:57-70`, rendered `:268-274` | after the run, for `failed`/`skipped` only (`:131-133`); `failed` → "we'll retry on your next visit", `skipped` → `error_message` |
> | `taskStatus(source)` | `ParcelInfo.tsx:134-135`, passed `:287-288` | hands `census` / `property` status to the panel |
> | `DemographicsPanel` | `DemographicsPanel.tsx:20-26`, `:78-106` | `queued`/`processing` → "data will appear once the timeline finishes"; `failed` → "couldn't load census/property records"; **otherwise → "No census or property records found for this address"** (`:104-106`) |
> | `progressLabel` | `Timeline.tsx:57-67`, called `:378-379` | `"{label} ({items_found})"` for complete, `"Loading {label}..."` for processing |
>
> **The surface a "years failed" signal must reach is small: one Pydantic model,
> one endpoint, one TypeScript interface, three components.** Two of those
> components already render the M4 lie in user-visible text —
> `DemographicsPanel.tsx:104-106` says "No census or property records found for
> this address" for a task that ended `complete` with missing years, and
> `ParcelInfo.tsx:265-267` reports a bare `snapshots.length` with no notion of
> which periods are absent.
>
> **What this implies for column vs row.** Nothing, and that is the finding. Every
> consumer above reads a **derived summary** through a Pydantic model, never the
> storage. Whichever shape wins, the API would expose something like
> `groups_missing: string[]` or a per-source count, computed server-side — the
> serialization boundary at `app/schemas/imagery.py:17-27` insulates all six
> consumers from the choice. The consumer surface is not a tiebreaker.

**Finding:** the document has no section titled or shaped as an
`imagery_snapshots` read-site enumeration. The two sections that come closest
in subject matter are §4 ("What backfill reads today," `maybe_refetch_for_backfill`'s
own reads plus the two query shapes backfill would need) and §5 ("What the
heal scripts read," a per-script table for `revalidate_landsat.py`,
`requeue_empty_property.py`, `heal_tract_vintage_gaps.py`, `requeue_parcels.py`)
— both scoped to specific consumers, neither a general enumeration of every
site touching `imagery_snapshots`. This gap is why item 3 below does the
enumeration fresh rather than diffing against an existing one.

---

## 3. Read-site inventory, verified fresh at HEAD

`grep -rn "imagery_snapshots\|ImagerySnapshot" backend --include="*.py"`,
excluding the ORM class body and Alembic column-add/constraint boilerplate
that doesn't read the table.

| file:line | What it reads | In INVESTIGATION §4/§5? |
|---|---|---|
| `app/models/parcels.py:358` | ORM table definition (`class ImagerySnapshot`) | Implicit (§1.3), not a read site |
| `app/services/imagery.py:908-920` (`count_imagery_snapshots`) | `SELECT COUNT(*) ... WHERE parcel_id, source` | No — mentioned only as a *consumer* in §8, not listed as a read site itself |
| `app/services/imagery.py:1153-1157` | `SELECT id, stac_item_id, capture_date ... WHERE parcel_id, source` (reconciliation's existing-rows pull) | No |
| `app/services/imagery.py:1188` | `DELETE FROM imagery_snapshots WHERE id = :id` (a write, listed for completeness) | No |
| `app/services/imagery.py:1237,1268` | `INSERT INTO imagery_snapshots ...` (writes) | No |
| `app/services/imagery.py:1330-1355` (`get_snapshot_by_id`) | Full-row `SELECT ... WHERE id = :id` | No |
| `app/services/imagery.py:1357-1400` (`get_imagery_snapshots`) | Full-row `SELECT` filtered by parcel/source/date range, raw SQL to dodge GeoAlchemy2's `AsEWKB` on `bbox` | No |
| `app/api/v1/imagery.py:199` | Calls `get_imagery_snapshots` for the timeline response | No |
| `app/services/preview_renderer.py:70` | Calls `get_imagery_snapshots` to pick a preview scene | No |
| `app/api/v1/featured.py:30-43` | Raw `SELECT parcel_id, id, capture_date FROM imagery_snapshots WHERE parcel_id IN (...)` for the featured-parcels thumbnail picker | No |
| `app/services/imagery.py:1145,1167` (`encode_group_key` call sites inside reconciliation) | Not a table read, but consumes rows already selected above | N/A |
| `scripts/revalidate_landsat.py:41-49` | `SELECT parcel_id FROM imagery_snapshots WHERE source = 'landsat' GROUP BY parcel_id` | **Yes — §5** |
| `tests/conftest.py:164,266` | Test-DB `CREATE TABLE` / fixture cleanup list | No (test infra) |
| `tests/test_featured.py:78` | Test fixture `INSERT` | No |
| `tests/test_remove_uncovered_snapshots.py:103,181` | Test fixture `INSERT` / `SELECT id FROM imagery_snapshots` | No |
| `tests/test_year_ledger.py:328,352,380` | Test fixture `SELECT COUNT`, `INSERT`, `SELECT stac_item_id ... WHERE capture_date` | No |
| `tests/test_imagery.py:194-274,517,808-838` | Exercises `get_imagery_snapshots`/`upsert_imagery_snapshot` and one raw `SELECT stac_item_id ... WHERE parcel_id, source` | No |
| `tests/test_timeline.py:366` | Patches `count_imagery_snapshots`, doesn't read the table directly | No |
| `alembic/versions/0002_imagery_timeline.py`, `0007_imagery_additional_cog_urls.py`, `0008_usgs_topo.py` | Schema DDL only (create/alter/drop table, columns, constraints) | No |

**No orphan sites in either direction that matter for the migration:** every
production-code (non-test, non-migration) read site is one of `count_imagery_snapshots`,
the reconciliation existing-rows pull, `get_snapshot_by_id`, `get_imagery_snapshots`,
the featured-parcels raw query, and `revalidate_landsat.py`'s selection query.
§5 names only the last of these — the other five aren't drift so much as scope:
§4/§5 were written to answer "what does backfill/heal read," not "what reads
this table," so they correctly omit the read-path (`get_imagery_snapshots`,
`get_snapshot_by_id`, the featured query) entirely. **That read-path is the
part the ADR's `scenes`/`parcel_scenes` split has to preserve call-compatible,
and it has no home in INVESTIGATION.md at all** — this is the actual gap item
2 surfaces, not a numbering mismatch.

---

## 4. group_key reality check

**The ADR's rule 2 ("group_key is one shared encoding") is no longer a
proposal — it shipped.** At HEAD:

```python
# app/services/imagery.py:964-968
_GROUP_KEY_ENCODERS: dict[str, Callable[[tuple[int, ...]], str]] = {
    "year": lambda parts: f"{parts[0]:04d}",
    "quarter": lambda parts: f"{parts[0]:04d}Q{parts[1]}",
    "decade": lambda parts: f"{parts[0]:04d}s",
}

# app/services/imagery.py:1023-1032
def encode_group_key(scope: str, value: date | int) -> str:
    """Encode a capture date (or bare year) as this scope's group key.

    ``year`` -> ``"1993"``; ``quarter`` -> ``"1993Q3"``; ``decade`` ->
    ``"1960s"``. An ``int`` is read as a calendar year, which is what the
    topo path and the census year lists have in hand — they never build a
    date just to bucket it.
    """
    as_date = date(value, 1, 1) if isinstance(value, int) else value
    return _GROUP_KEY_ENCODERS[scope](SELECTION_SCOPES[scope](as_date))
```

`decode_group_key` (`imagery.py:1035-1048`+) is the stated inverse, returning
an inclusive `(start, end)` date range per scope — this is what would let a
migration or heal turn a stored `group_key` back into a fetch range.

All five sites INVESTIGATION.md §6 found hand-inlining the three rules now
call `encode_group_key` instead of re-deriving:

| former inline site (§6) | now |
|---|---|
| `select_naip_items` — `stac.py:785-789` | `stac.py:1052`: `by_year[encode_group_key("year", _capture_date(item))]` |
| `select_landsat_items` — `stac.py:914-918` | `stac.py:1018`: `by_year[encode_group_key("year", _capture_date(item))]` |
| `select_sentinel_items` — `stac.py:936-942` | `stac.py:889`: `by_year[encode_group_key("year", _capture_date(item))]` (also renamed to year bucketing per the G8 change below) |
| `select_topo_items` — `usgs_topo.py:112-118` | `usgs_topo.py:150`: `by_decade[encode_group_key("decade", year)]` |
| `_validate_selection` callers — `stac.py:1181,1202` | `stac.py:1375,1401`: `period=lambda d: encode_group_key("year", d)` |

`timeline.py:412,416,473,852,1091,1169` and `imagery.py:1010,1014,1017` (census
year sets, ledger writes, topo decade lookups) all call the same function.
`SELECTION_SCOPES["quarter"]` still exists but is unused in current selection
paths — STATUS.md's G8 entry confirms it's "kept and marked unused" after
Sentinel-2 moved from quarter to year grouping on 2026-08-25.

**Implication for the ADR:** rule 2 as written in the ADR describes work that
is already done. The normalization migration doesn't need to invent or
consolidate the encoding — `parcel_scenes.group_key` just needs to store the
string `encode_group_key` already produces, and the migration's job is
schema (table split, backfill, cutover), not the encoding logic STATUS.md's
`../2026-08-second-audit/STATUS.md` line ~1507 already documents this
decoupling decision for.

---

## 5. STATUS.md state

Quoted verbatim from `docs/audits/2026-08-second-audit/STATUS.md` at HEAD.

**M3 row (Medium table):**

> | M3 Backfill scope | **Resolved, observed — all three acceptance heals run
> and scored (`ae740cf`, `c98de1b`, `a6c7800`, `b7c9cbb`, `bd03432`,
> `5f3aa7d`; deployed 2026-08-27T15:42Z, both machines confirmed on
> `5f3aa7d`, `alembic_version=0012`).** [...]

(Full row is long — see file for the complete acceptance-heal narrative; the
deploy-state clause quoted above is the load-bearing sentence for this
report.)

**M4 row (Medium table):**

> | M4 Partial census/Landsat failures | **Resolved, 2026-08-27 — see the M3
> row above.** *This row's stated blocker was "M4's remedy is a heal, and no
> heal has run." That is now false: [...] all ran and scored 2026-08-27.*
> [...] **Deployed 2026-08-26T00:51:55Z. The first full sweep was authorised
> the same day and did not run — `../2026-08-m4-ledger/GATE-STOP.md`.**
> [...] **First full production sweep, 2026-08-26 02:16:35Z-03:04:07Z — the
> ledger is populated and PREDICTION.md is scored:
> `../2026-08-m4-ledger/HEAL-SCORECARD.md`, baseline
> `../2026-08-m4-ledger/BASELINE.txt` (16,244 rows, captured 03:07Z [...]).**
> [...]

**Fix-commits table entry:**

> | 0814d7e, ef2d0a2 | M4 (per-year ledger — instrumentation half; the heal
> path is M3) |

**Scheduled section — normalization ADR's own status:**

> ## Scheduled
>
> *2026-08-27: the remediation arc (M4 → M3 → ops batch → Z6 → Y7/Y8 →
> property outcomes) is closed and scored [...]*
>
> 1. **Imagery normalization** (`docs/adr/0001-imagery-normalization.md`) —
>    `scenes` + `parcel_scenes`, four additive steps, each with a prediction
>    before it runs. This is the first structural change to the imagery
>    model; the NAIP-selector coverage item below and any new imagery source
>    wait on it so their waves write against the new shape once instead of
>    twice.

**G3 note (relevant context, not directly asked for but adjacent to item 6's
duplicate-group findings):** STATUS.md's G-family rows document that
production's Sentinel-2 quarter-duplication was itself found, diagnosed
(20-item search cap + PC's newest-first ordering making Q1/Q2 structurally
unreachable), fixed (G8: quarter→year grouping), deployed, and swept twice —
first 30/184 parcels, then the remaining 154/184 — with the completion sweep
scorecard reporting **zero parcels holding two Sentinel-2 rows in one
calendar year, fleet-wide** as of 2026-08-25. This is why item 6's local
269-duplicate-group count below should not be read as a production estimate.

**No STATUS.md row exists yet for the normalization migration's own progress**
— it is listed only as scheduled work, not yet started, which matches "status:
Proposed" on the ADR.

---

## 6. Prediction inputs, local database only

Local stack: `docker compose ps` shows `postgres`, `api`, `redis`, `titiler`
all up. Local DB: user `plotline`, database `plotline` (per `.env` /
`docker-compose.yml`), queried via `docker compose exec -T postgres psql -U
plotline -d plotline`. `alembic_version = 0014`. 43 parcels, 3,295
`imagery_snapshots` rows locally — this is a small dev dataset, not a
production mirror, and (per item 5's G3 note) has never been swept under the
year-grouping code the way production has.

### 6a. Distinct `(stac_collection, stac_item_id)`

```sql
SELECT count(DISTINCT (stac_collection, stac_item_id)) FROM imagery_snapshots;
```
→ **1,382**, against **3,295** total rows.

### 6b. Duplicate `(parcel_id, source, group_key)` groups

Group encoding used: the same one verified in item 4 —
`year` for `naip`/`landsat`/`sentinel2` (all three are `selection_scope:
"year"` per `app/tasks/timeline.py:66,78,94`), `decade` for `usgs_topo`
(hardcoded, per `timeline.py:961` and `usgs_topo.py`'s decade bucketing).
Reproduced in SQL as:

```sql
CASE WHEN source = 'usgs_topo'
     THEN ((EXTRACT(YEAR FROM capture_date)::int / 10) * 10)::text || 's'
     ELSE EXTRACT(YEAR FROM capture_date)::int::text
END AS group_key
```

```sql
SELECT parcel_id, source, group_key, count(*) n
FROM (…group_key expression…) grouped
GROUP BY parcel_id, source, group_key
HAVING count(*) > 1;
```

**269 duplicate groups**, all `sentinel2` (266 groups) or `naip` (3 groups) —
zero `landsat` or `usgs_topo` duplicates. **43 distinct parcels** affected —
essentially all of them, since the local DB only has 43 parcels total. This
is consistent with the local DB predating (and never having been swept under)
the G8 Sentinel-2 quarter→year regrouping STATUS.md documents as production-
only work: the local rows still carry the old per-quarter picks that
reconciliation would collapse once run under current code with the ledger
active, or once `revalidate_landsat.py`/an equivalent sweep runs locally.

Full list, address + source + group_key + row count per duplicate group:

| address | source | group_key | n |
|---|---|---|---|
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2015 | 2 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2016 | 4 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2017 | 3 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2018 | 3 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2019 | 3 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2020 | 2 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2021 | 3 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2022 | 2 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2023 | 2 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2024 | 3 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2025 | 2 |
| 1 Infinite Loop, Cupertino, California 95014 | sentinel2 | 2026 | 3 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2015 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2016 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2017 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2018 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2019 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2020 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2021 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2022 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2024 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2025 | 2 |
| 1010 W Jefferson St, Boise, ID 83702 | sentinel2 | 2026 | 2 |
| 1123 county road | sentinel2 | 2015 | 2 |
| 1123 county road | sentinel2 | 2016 | 4 |
| 1123 county road | sentinel2 | 2017 | 4 |
| 1123 county road | sentinel2 | 2018 | 3 |
| 1123 county road | sentinel2 | 2019 | 2 |
| 1123 county road | sentinel2 | 2020 | 2 |
| 1123 county road | sentinel2 | 2021 | 3 |
| 1123 county road | sentinel2 | 2022 | 2 |
| 1123 county road | sentinel2 | 2023 | 2 |
| 1123 county road | sentinel2 | 2024 | 2 |
| 1123 county road | sentinel2 | 2025 | 2 |
| 1123 county road | sentinel2 | 2026 | 3 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2015 | 2 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2016 | 4 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2017 | 2 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2018 | 2 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2021 | 2 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2024 | 2 |
| 11770 South, South Jordan, Utah 84095 | sentinel2 | 2026 | 2 |
| 11775 Wadsworth Blvd, Broomfield, CO 80020 | sentinel2 | 2015 | 2 |
| 11775 Wadsworth Blvd, Broomfield, CO 80020 | sentinel2 | 2016 | 2 |
| 11775 Wadsworth Blvd, Broomfield, CO 80020 | sentinel2 | 2026 | 2 |
| 11775 Wadsworth Boulevard, Broomfield, Colorado 80020 | sentinel2 | 2015 | 2 |
| 11775 Wadsworth Boulevard, Broomfield, Colorado 80020 | sentinel2 | 2016 | 2 |
| 11775 Wadsworth Boulevard, Broomfield, Colorado 80020 | sentinel2 | 2026 | 2 |
| 1201 16th St, Denver, CO 80202 | sentinel2 | 2015 | 2 |
| 12345, Berlin, New York | sentinel2 | 2016 | 4 |
| 12345, Berlin, New York | sentinel2 | 2017 | 4 |
| 12345, Berlin, New York | sentinel2 | 2018 | 2 |
| 12345, Berlin, New York | sentinel2 | 2019 | 2 |
| 12345, Berlin, New York | sentinel2 | 2020 | 2 |
| 12345, Berlin, New York | sentinel2 | 2021 | 2 |
| 12345, Berlin, New York | sentinel2 | 2022 | 2 |
| 12345, Berlin, New York | sentinel2 | 2023 | 2 |
| 12345, Berlin, New York | sentinel2 | 2024 | 2 |
| 12345, Berlin, New York | sentinel2 | 2025 | 2 |
| 12345, Berlin, New York | sentinel2 | 2026 | 2 |
| 12804 Emerson St Thornton CO 80241 | sentinel2 | 2015 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2015 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2016 | 3 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2017 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2018 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2019 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2020 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2021 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2025 | 2 |
| 1300 4th St SE, Washington, DC 20003 | sentinel2 | 2026 | 2 |
| 1361 Leyner Drive, Erie, Colorado 80516 | sentinel2 | 2015 | 2 |
| 1361 Leyner Drive, Erie, Colorado 80516 | sentinel2 | 2016 | 2 |
| 1361 Leyner Drive, Erie, Colorado 80516 | sentinel2 | 2017 | 2 |
| 1361 Leyner Drive, Erie, Colorado 80516 | sentinel2 | 2026 | 2 |
| 1437 Bannock St, Denver, CO 80202 | sentinel2 | 2015 | 2 |
| 1437 Bannock St, Denver, CO 80202 | sentinel2 | 2015 | 2 |
| 1437 Bannock St, Denver, CO 80202 | sentinel2 | 2025 | 3 |
| 1500 Pearl St, Denver CO | sentinel2 | 2015 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2015 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2016 | 4 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2017 | 3 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2018 | 3 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2019 | 3 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2020 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2021 | 3 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2022 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2023 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2024 | 3 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2025 | 2 |
| 1600 Amphitheatre Pkwy, Mountain View, CA 94043 | sentinel2 | 2026 | 3 |
| 1600 Broadway, Denver, CO 80202 | sentinel2 | 2015 | 2 |
| 1600 Glenarm Pl, Denver, CO 80202 | sentinel2 | 2015 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2015 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2016 | 3 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2017 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2018 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2019 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2020 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2021 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2025 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC | sentinel2 | 2026 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2015 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2016 | 3 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2017 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2018 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2019 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2020 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2021 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2025 | 2 |
| 1600 Pennsylvania Ave NW, Washington, DC 20500 | sentinel2 | 2026 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2015 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2016 | 3 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2017 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2018 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2019 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2020 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2021 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2025 | 2 |
| 1600 Pennsylvania Ave, Washington DC | sentinel2 | 2026 | 2 |
| 16th Street Mall, Denver, Colorado | sentinel2 | 2015 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2015 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2016 | 3 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2017 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2018 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2019 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2020 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2021 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2025 | 2 |
| 1922 9th St NW, Washington, DC | sentinel2 | 2026 | 2 |
| 200 E Santa Clara St, San Jose, CA 95113 | sentinel2 | 2015 | 2 |
| 200 E Santa Clara St, San Jose, CA 95113 | sentinel2 | 2016 | 2 |
| 200 E Santa Clara St, San Jose, CA 95113 | sentinel2 | 2021 | 2 |
| 200 E Santa Clara St, San Jose, CA 95113 | sentinel2 | 2026 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2015 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2016 | 4 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2017 | 3 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2018 | 3 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2019 | 3 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2020 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2021 | 3 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2022 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2023 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2024 | 3 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2025 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | sentinel2 | 2026 | 3 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2015 | 2 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2016 | 4 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2017 | 4 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2018 | 3 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2019 | 3 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2020 | 3 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2021 | 3 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2022 | 2 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2023 | 2 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2024 | 4 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2025 | 2 |
| 233 S Wacker Dr, Chicago, IL 60606 | sentinel2 | 2026 | 3 |
| 2345 East, Cottonwood Heights, Utah 84121 | sentinel2 | 2015 | 2 |
| 2345 East, Cottonwood Heights, Utah 84121 | sentinel2 | 2016 | 2 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2015 | 2 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2016 | 4 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2017 | 4 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2018 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2019 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2020 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2021 | 2 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2022 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2023 | 2 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2024 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2025 | 2 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | sentinel2 | 2026 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2015 | 2 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2016 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2017 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2018 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2019 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2020 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2021 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2022 | 2 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2023 | 2 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2024 | 3 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2025 | 2 |
| 2600 Benjamin Franklin Parkway, Philadelphia, Pennsylvania 19130 | sentinel2 | 2026 | 3 |
| 2901 Blake St, Denver, CO 80205 | sentinel2 | 2015 | 2 |
| 350 5th Ave, New York, NY 10118 | naip | 2013 | 2 |
| 350 5th Ave, New York, NY 10118 | naip | 2015 | 2 |
| 350 5th Ave, New York, NY 10118 | naip | 2017 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2015 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2015 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2016 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2016 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2017 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2017 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2018 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2018 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2019 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2019 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2020 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2020 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2021 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2021 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2022 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2022 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2025 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2025 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2026 | 2 |
| 350 5th Ave, New York, NY 10118 | sentinel2 | 2026 | 2 |
| 4800 Telluride St, Denver, CO 80249 | sentinel2 | 2015 | 2 |
| 4800 Telluride St, Denver, CO 80249 | sentinel2 | 2016 | 2 |
| 4800 Telluride St, Denver, CO 80249 | sentinel2 | 2019 | 2 |
| 4800 Telluride St, Denver, CO 80249 | sentinel2 | 2021 | 2 |
| 4800 Telluride St, Denver, CO 80249 | sentinel2 | 2026 | 2 |
| 4800 Telluride Street, Denver, Colorado 80249 | sentinel2 | 2015 | 2 |
| 4800 Telluride Street, Denver, Colorado 80249 | sentinel2 | 2016 | 2 |
| 4800 Telluride Street, Denver, Colorado 80249 | sentinel2 | 2019 | 2 |
| 4800 Telluride Street, Denver, Colorado 80249 | sentinel2 | 2021 | 2 |
| 4800 Telluride Street, Denver, Colorado 80249 | sentinel2 | 2026 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2015 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2016 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2017 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2018 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2019 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2020 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2021 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2022 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2025 | 2 |
| 500 W 33rd St, New York, NY 10001 | sentinel2 | 2026 | 2 |
| 7809 South Lemay Ave Fort Collins, CO 80525 | sentinel2 | 2015 | 2 |
| 7809 South Lemay Ave Fort Collins, CO 80525 | sentinel2 | 2016 | 3 |
| 7809 South Lemay Ave Fort Collins, CO 80525 | sentinel2 | 2017 | 2 |
| 7809 South Lemay Ave Fort Collins, CO 80525 | sentinel2 | 2026 | 2 |
| 8340 Northfield Blvd, Denver, CO 80238 | sentinel2 | 2015 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2015 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2016 | 3 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2017 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2018 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2019 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2020 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2021 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2022 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2023 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2024 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2025 | 2 |
| 9311 S Cimarron Rd, Las Vegas, NV 89178 | sentinel2 | 2026 | 2 |
| Bannock Street, Denver, Colorado 80273 | sentinel2 | 2015 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2016 | 3 |
| Bannock, Ohio 43972 | sentinel2 | 2017 | 4 |
| Bannock, Ohio 43972 | sentinel2 | 2018 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2019 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2020 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2021 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2022 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2024 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2025 | 2 |
| Bannock, Ohio 43972 | sentinel2 | 2026 | 3 |
| Death Valley, California 92328 | sentinel2 | 2016 | 2 |
| Death Valley, California 92328 | sentinel2 | 2017 | 2 |
| Death Valley, California 92328 | sentinel2 | 2021 | 2 |
| Death Valley, California 92328 | sentinel2 | 2026 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80522 | sentinel2 | 2015 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80522 | sentinel2 | 2016 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2015 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2015 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2016 | 3 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2016 | 3 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2017 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2017 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2026 | 2 |
| South Lemay Avenue, Fort Collins, Colorado 80525 | sentinel2 | 2026 | 2 |

Note two of the addresses above ("South Lemay Avenue, Fort Collins, Colorado
80525" and "South Lemay Avenue, Fort Collins, Colorado 80522") and
("11775 Wadsworth Blvd" / "11775 Wadsworth Boulevard", "4800 Telluride St" /
"4800 Telluride Street") look like the same real-world location geocoded to
two different `parcels` rows under slightly different address strings — a
parcel-identity question, not a `group_key` question, and out of this
report's scope, but worth flagging since a `scenes`/`parcel_scenes` migration
that keys off `parcel_id` will carry the split forward unless parcel
de-duplication happens separately.

### 6c. `additional_cog_urls` cross-reference

```sql
SELECT count(*) FROM imagery_snapshots
WHERE additional_cog_urls IS NOT NULL AND array_length(additional_cog_urls,1) > 0;
```
→ **141 rows** (column is `text[]`, not `jsonb` — confirmed via
`information_schema.columns` after an initial `jsonb`-typed query errored
with "operator does not exist: text[] <> jsonb").

```sql
WITH exploded AS (
  SELECT id, unnest(additional_cog_urls) AS url
  FROM imagery_snapshots
  WHERE additional_cog_urls IS NOT NULL AND array_length(additional_cog_urls,1) > 0
)
SELECT count(*) AS total_urls,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM imagery_snapshots s2 WHERE s2.cog_url = exploded.url
       )) AS matched_urls
FROM exploded;
```
→ **162 total URLs across those 141 rows; 50 matched some row's `cog_url`
elsewhere in the table; 112 did not.** All five sampled unmatched URLs are
NAIP tile URLs (`naipeuwest.blob.core.windows.net/naip/...`) — additional
tiles mosaicked into a multi-tile NAIP scene that were never themselves
persisted as their own `imagery_snapshots` row, which is the expected shape
for NAIP's viewport-mosaic path (`use_viewport_filter: True`,
`app/tasks/timeline.py:69`) rather than a defect. The migration should treat
`additional_cog_urls` entries as "URLs that may or may not correspond to
another row" rather than assuming full referential coverage.

**Note per the prompt's instruction:** these are local-only figures. The
production equivalents (prod's `(stac_collection, stac_item_id)` distinct
count, prod's duplicate-group count under the current encoding, and prod's
`additional_cog_urls` cross-reference) are not derived in this report and
should be derived separately, read-only via `fly ssh console`, before the
migration runs — the local numbers above should not stand in for them, both
because the local dataset is two orders of magnitude smaller and because
(per item 5's G3 note) production has already been swept under the current
group encoding while local has not.
