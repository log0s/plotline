# M3 design investigation — per-source backfill reading the ledger

**Mode: report only.** No code, no migrations, nothing dispatched. Production
reads went through `fly ssh console -C`, `SELECT` only. Every line citation is
against the tree at `d294d2b`; every production number was read on 2026-08-26
between roughly 09:30Z and 10:10Z and is stamped where it appears.

The decision this exists to inform — `sources` column on `TimelineRequest`
versus derived per-run — is **not made here**. Section 2 lays the shapes side by
side and says what each costs; it stops there.

**Two premises in the prompt did not survive contact.** One is load-bearing for
item 5 (`e6afa9b` is *not* deployed) and one is a scope correction. Both are in
the register at the end. Read that first if you are about to plan the build
pass.

**One new production defect was found while gathering item 8** and is written up
in §8.3: the ledger recorded its first `failed` rows in production this morning
— 34 of them, on two parcels created today, one of which is serving a timeline
with **zero NAIP and zero Sentinel-2 rows** under a `complete` request. It is
the M4 shape, live, and today's backfill cannot see it. It is also the single
best acceptance case M3 has.

---

## 1. The current trigger, exactly

### 1.1 `maybe_refetch_for_backfill` — every condition it evaluates

`backend/app/services/imagery.py:347-471`. Called from exactly two sites, both
only on the `is_new == False` branch:

* `backend/app/api/v1/imagery.py:96` — `POST /parcels/{id}/timeline`
* `backend/app/api/v1/geocode.py:292` — inside `_ensure_timeline_request`

The frontend reaches the first on every deep-link load that has no nav-state
request id (`frontend/src/pages/ExplorePage.tsx:66-86`), so in practice this
runs on page views.

| # | reads | site | test | source it can speak for |
|---|---|---|---|---|
| 1 | `existing_req.status` | `:366` | must be `complete`, else `None` | — |
| 2 | `parcel.census_tract_id` | `:371` | truthy | census |
| 3 | the `census` task row of that one request | `:372-380` | `not census_task or status == 'failed'` (`:381`) | census |
| 4 | `parcel.county` + `get_adapter_for_county` | `:388-391` | adapter exists | property |
| 5 | the `property` task row of that request | `:392-400` | `not prop_task or status in ('skipped','failed')` (`:401`) | property |
| 6 | the `usgs_topo` task row of that request | `:407-415` | **`not topo_task`** only (`:417`) — status never examined | usgs_topo |
| 7 | `max(created_at)` over the parcel's requests | `:435-440` | age vs `backfill_cooldown_hours` = `6.0` (`app/config.py:72`) | — |
| 8 | `_create_queued_request` | `:455` | `AdmissionRefused` → `None` (`:456-463`); lost race → `None` (`:464-466`) | — |

**What it cannot see.** `naip`, `landsat`, `sentinel2` have **no trigger of any
kind**. Neither `items_found` nor its change between runs is read. No per-year
state is read — the ledger is not touched by this function or by anything it
calls. Trigger 6 is a one-shot latch: once any run creates a `usgs_topo` task
row, that condition is permanently false.

**The failure this produces, observed live today.** Parcel `6563dedf` (Crawford
County, MI; created 2026-08-26 09:14:34Z) holds `naip` **failed** and
`sentinel2` **failed** task rows under a request whose status is `complete`, and
serves **0 NAIP and 0 Sentinel-2** snapshots. Walk the table: census task exists
and is `complete` → no trigger. `get_adapter_for_county('Crawford')` is `None`,
so trigger 4 short-circuits and the `skipped` property task is never
consulted → no trigger. A `usgs_topo` task row exists → no trigger.
`needs_refetch` stays `False` and the function returns at `:425`. **A parcel
missing two entire imagery sources gets no backfill, on any number of page
views, forever.**

### 1.2 What it produces

`_create_queued_request(db, parcel.id)` (`:455`, defined `:100-134`) — a bare
`TimelineRequest(parcel_id=…, status='queued')`. There is no field on that row
naming a source, a year, or an origin. The returned request is dispatched by the
caller, and the worker rebuilds the source list from scratch.

### 1.3 The pipeline entry — how a request fans out

`_run_timeline_inner` (`backend/app/tasks/timeline.py:1344`):

```python
sources = [s["source"] for s in _SOURCES]     # naip, landsat, sentinel2   :1383
sources.append("usgs_topo")                                              # :1384
if tract_fips: sources.append("census")                                  # :1385-1386
if county:     sources.append("property")                                # :1387-1388
imagery_service.create_request_tasks(db, timeline_request_id=req_uuid,
                                     sources=sources)                    # :1389-1393
```

The list is derived from module-level configuration plus two parcel columns.
Nothing on the request row participates. The coroutine fan-out at `:1421-1470`
is built from the same two facts independently — so scoping `create_request_tasks`
alone would create fewer task rows while still running every fetch, and
`_set_task_status` would log *"No task row found for source"* (`:288-291`) for
each unscoped source rather than fail. **Both places have to learn the scope, or
neither.**

`create_request_tasks` (`imagery.py:252-305`) is `INSERT … ON CONFLICT
(timeline_request_id, source) DO UPDATE SET status='queued', items_found=0, …`,
and for each source it first calls `clear_task_year_outcomes(db,
timeline_request_id, source)` (`:288`), which deletes that task's ledger rows
(`year_ledger.py:207-227`). The delete is keyed on the **task**, not on the
ledger's `source` column, so passing `'census'` clears both `census_decennial`
and `census_acs5` rows. That is correct today and is a trap for §2.

### 1.4 Can anything today create a request with fewer than all sources?

**In application code, no.** `create_request_tasks` has exactly one non-test
caller (`timeline.py:1389`) and it always passes the full derived list. Tests
call it with subsets (`tests/test_imagery.py:154`, `tests/test_redact.py:125`,
`tests/test_year_ledger.py:226`).

**One script does produce a partial run, by a different mechanism.**
`scripts/heal_tract_vintage_gaps.py` resolves the parcel's *latest existing*
request id (`:85-102`) and calls `_fetch_census` directly against it
(`:169-178`). It never calls `create_request_tasks`. Consequences worth carrying
into §2 and §3:

* the census task row from the **old** run is mutated in place by
  `_set_task_status` — `started_at`/`completed_at` move, `status` resets;
* the ledger rows are upserted on `(task_id, group_key)`
  (`year_ledger.py:141-156`), so the old attempt's rows are **overwritten**, not
  added to. The re-run leaves no trace that there were two attempts;
* the request's `created_at` does not move, so `ledger_gaps.py`'s
  latest-by-run ordering still reads the row correctly — but its `attempts`
  window count does not increment.

That is the only in-tree precedent for "run one source against a request", and
it is precedent for the shape M3 should *not* copy.

**What this implies:** backfill's decision surface is three task-row probes with
no imagery source among them and no per-year input, and its output is
structurally incapable of naming a source — so M3 is two independent changes
(a selector that reads the ledger, and a request shape that can carry scope),
and the only existing partial-run path buys its scope by destroying attempt
history.

---

## 2. Scope: column, derived, or task-only

Three shapes. `A` = `sources` column on `TimelineRequest`. `B` = derived per run
from the previous request's task rows. `C` = scope carried only by which
`timeline_request_tasks` rows exist, `TimelineRequest` unchanged.

### 2.1 Side by side

| | **A — `TimelineRequest.sources`** | **B — derived from the previous request** | **C — task rows only** |
|---|---|---|---|
| **Schema** | new migration: `sources TEXT[]` (or `jsonb`) nullable, `NULL` = all. One column, one `CHECK` at most. | none | none |
| **How `create_request_tasks` learns scope** | read `request.sources` in `_run_timeline_inner`, intersect with the derived list, pass the result to both `create_request_tasks` **and** the coroutine fan-out (`timeline.py:1383-1470`). | worker re-derives: query the parcel's previous request's task rows + ledger, decide what to run. Re-runs the selection logic **inside** the worker, so the API and the worker can disagree about what this request is for. | the *creator* writes the task rows before dispatch; the worker reads `SELECT source FROM timeline_request_tasks WHERE timeline_request_id = …` and fans out over exactly those. `create_request_tasks` becomes creator-side, not worker-side. |
| **`clear_task_year_outcomes` interaction** | safe by construction: the loop at `imagery.py:287-296` only iterates the scoped list, so an unrun source's ledger rows are untouched — **provided the request is new**. On a *reused* request it would delete the previous attempt's rows for the scoped source, which is the history M3's retry policy needs (§3.4). | same hazard, and worse: the derivation happens in the worker, after the request exists, so a mis-derivation clears rows for a source it then does not run. | same as A. The invariant to state in code: **`create_request_tasks` may only ever be called on a request created for this run.** |
| **Cooldown** | naturally becomes per-request-per-scope: `last_attempt` (`imagery.py:435-440`) would need `WHERE sources @> ARRAY[<source>] OR sources IS NULL` to mean "when did we last try *this* source". Without that change a census-only backfill blocks a landsat backfill for six hours. | no place to put the predicate — the previous request's *task rows* are the only record of what it ran, so the cooldown query grows a join to `timeline_request_tasks`. Expressible, one join. | identical to B: join `timeline_request_tasks`. Cheaper than it sounds — the join is on an indexed FK (`idx` on `timeline_request_id`, `parcels.py:172-177`). |
| **What the UI sees** | `TimelineRequestResponse.tasks` (`schemas/imagery.py:30-41`) is built from the task rows either way, so a scoped request renders **only the scoped sources**. `ParcelInfo.tsx:131-136` computes `unavailableSources` from that list, so a census-only request makes a previously-`failed` landsat row *disappear from the panel*; `Timeline.tsx:56-66`'s `progressLabel` shows one source; `DemographicsPanel`'s `censusStatus` (`:20`, `:31`) is resolved by `tasks.find(t => t.source === 'census')` and is `undefined` for an imagery-only scope, which the component already treats as "no status reported" (`:18-19`). **The regression is the same in all three shapes** and is a real UI decision, not an implementation detail. | ditto | ditto |
| **`requeue_parcels.py --sources`** | `--sources census` → `_create_queued_request(…, sources=['census'])`, one extra kwarg through `create_queued_request_waiting` (`imagery.py:137-172`). The flag is a request attribute; nothing else changes. | not expressible — the script cannot state intent, only hope the worker re-derives the same thing. Would need its own out-of-band channel. | `--sources census` → create the request, then `create_request_tasks(db, req.id, ['census'])` before `dispatch_timeline_task`. Two calls instead of one, no new kwarg, no migration. |
| **Auditability** | the request row says what it was *for*, forever, even if the task rows are later reset. | nothing records intent. | task rows record what was *created*; a reset (`ON CONFLICT DO UPDATE`) preserves the set, since a reset never removes a row. |
| **Failure mode if it goes wrong** | request says `['census']`, worker runs everything → extra work, no data loss. | worker derives a different set than the operator expected → silent wrong scope, and no artifact to diff against. | worker fans out over the task rows; a missing task row means a source silently not run, and `_set_task_status`'s "No task row found" warning (`timeline.py:288`) becomes the only signal. |

### 2.2 The three facts that actually separate them

**(a) `_find_reusable_request` makes a scoped request the parcel's "current"
request.** `imagery.py:74-86` orders by `created_at DESC LIMIT 1` over
`queued|processing|complete`. A census-only backfill request therefore becomes
what `get_or_create_timeline_request` hands the next visitor, and what
`maybe_refetch_for_backfill` inspects. Walk the table in §1.1 against a
census-only request: it has no `usgs_topo` task row, so **trigger 6 fires and
the next page view dispatches a full-pipeline backfill**. Every shape has this
problem, because it is a property of the reusable-request query, not of where
scope is stored. Shapes A and C can fix it (`WHERE sources IS NULL`, or a
`HAVING count(*) = <full set>` on task rows); shape B has nothing to filter on.

**(b) `requeue_empty_property.py` reads the latest request and requires a
`property` task on it** (`:48-91`: `latest` subquery on `max(created_at)`, then
`WHERE t.source='property' AND t.status='complete' AND t.items_found=0`). A
census-only backfill on a parcel makes that parcel **invisible to the property
heal** until the next full run. Same class of breakage as (a), same three
shapes, and it is a second reason the "latest request" concept needs to become
"latest request that ran source X".

**(c) `ledger_gaps.py` is already immune.** Its window partitions on
`(parcel_id, source, group_key)` and orders by `r.created_at DESC, y.created_at
DESC` (`scripts/ledger_gaps.py:41-64`). A scoped run writes rows only for the
sources it ran, so a source it did not run simply has no newer row and the
previous run's row stays latest — which is the correct answer. **The ledger read
path needs no change for any of the three shapes.** That is worth stating
plainly because it is the one place where scoping was designed for in advance
(ADR rule 1, `docs/adr/0001-imagery-normalization.md`).

**What this implies:** the column-vs-derived question is smaller than the
question underneath it — all three shapes leave `_find_reusable_request` and
`requeue_empty_property.py` reading a scoped request as if it were a full one,
and shape B is the only one that cannot express the fix because it stores no
intent anywhere.

---

## 3. Selection

### 3.1 "Latest outcome per (parcel, source, group_key)", precisely

Ordered by the **timeline request's** `created_at` descending, tie-broken by the
ledger row's own `created_at` descending, taking `rn = 1`:

```sql
ROW_NUMBER() OVER (PARTITION BY r.parcel_id, y.source, y.group_key
                   ORDER BY r.created_at DESC, y.created_at DESC)
```

`scripts/ledger_gaps.py:48-58`. **`ledger_gaps.py` already computes exactly
this** — confirmed by reading the file and by re-running its shape against
production. It also computes `attempts` as `COUNT(*) OVER (PARTITION BY
parcel_id, source, group_key)` (`:59-61`) and, separately, the set of every
distinct reason ever recorded for a triple (`_REASONS_SQL`, `:68-81`).

Two properties of that definition worth writing down:

* **It is request-anchored, not task-anchored.** An in-place re-run against an
  existing request (the `heal_tract_vintage_gaps.py` pattern, §1.4) overwrites
  the ledger row without moving `r.created_at`. The *outcome* stays correct;
  the *attempt count* does not increment and the *ordering* silently treats a
  new attempt as if it were the old one.
* **A request with no ledger rows for a source contributes nothing**, which is
  what makes it scope-safe (§2.2c).

### 3.2 Retry policy per outcome/reason

Vocabulary and its meanings: `backend/app/services/year_ledger.py:33-100`.

| outcome / reason | retryable? | why, and what must be true |
|---|---|---|
| `failed/read_timeout`, `connect_error`, `sign_429`, `sign_5xx`, `stac_403`, `stac_5xx`, `http_5xx` | **yes, immediately** | the fetch was attempted and did not complete. Nothing about the world has to change for a retry to be worth making. This is the whole reason the outcome exists. |
| `failed/http_4xx` (other than 429) | **no, not without a code change** | a 4xx is us asking wrong. `http_404` on `1990/dec/sf1` is the canonical instance and the answer was to stop asking (`e6afa9b`), not to retry. |
| `failed/validation_failed`, `failed/other` | **yes, bounded** | the walk drops a period when every candidate's asset check fails (`stac.py`, recorded at `timeline.py:571-578`). Asset availability on Planetary Computer does come back — that is what `revalidate_landsat.py` exists for — but an unbounded retry here is a loop against a dead scene. |
| `absent/api_no_data` | **only after a named fix** | the API answered and had nothing *for the geography we asked about*. Retrying the identical request is guaranteed-identical work. Retryable exactly when the request changed — which is the decennial-2000 trim (§5). |
| `absent/all_cloud_filtered` | **only if the threshold changed** | the 40% `eo:cloud_cover` filter is in `_SOURCES` (`timeline.py:69`, `:81`). Same request, same answer, until that number moves. |
| `absent/no_scenes` | **never** | the search covered the period and the catalogue is empty. New scenes for 1987 do not arrive. The only thing that makes this stale is a **collection extent change** or a new source, which is a code event, not a time event. |
| `absent/no_covering_item` | **no** | items existed, none contained the point. Geometry does not change. |
| `suppressed/*` | **never a retry** — it is *reconciliation* input | a candidate existed and was deliberately not served. Retrying re-suppresses. §4 is what this outcome is actually for. |
| `indeterminate/*` | **not a retry; a code fix** | today's two instances are both response caps (`naip` item cap ×7 on one parcel, TNM row cap ×1). Re-running with the same cap re-produces the same uncertainty. Raise the cap or paginate, then re-run. |

### 3.3 What the policy needs that the ledger does not record

1. **Attempt count that survives an in-place re-run.** `attempts` is a window
   count over ledger rows, which the `(task_id, group_key)` upsert collapses
   (§3.1). A backoff policy — "stop retrying `failed/read_timeout` after N
   consecutive attempts" — has no trustworthy N today. Production confirms it:
   of 2,283 non-`ok` latest rows, **2,270 read `attempts = 1`** and 13 read 2
   (§8.2). The ledger has effectively one attempt of history.
2. **A fixed-by marker.** "`absent/api_no_data` is retryable *only after a fix
   like the trim*" is not expressible against the ledger. Nothing on
   `timeline_requests` records which code a run executed —
   `revalidate_landsat.py:40-53` says so explicitly and works around it by
   reading the deployed image's build time from `/api/v1/health`. To make
   "retry every `absent/api_no_data` recorded before SHA X" a query, either
   `timeline_requests` gains a `ran_under_sha` column, or the policy stays a
   per-invocation argument naming the reason and the cutoff timestamp.
   (`parcel_scenes.selected_by` in the ADR is the same idea for the selection
   side — worth landing the two together rather than inventing two spellings.)
3. **Nothing else.** `source`, `group_key`, `outcome`, `reason`, `detail` and
   the request join cover the rest. `decode_group_key` (`imagery.py:686-711`)
   already turns a key back into the date range the refetch needs, which is what
   makes a ledger row a targeting instruction rather than a label.

### 3.4 Code or argument?

Split, and the split falls out of the table above rather than from taste:

* **In code:** the outcome/reason → *class* mapping (`retry now` / `retry after
  a change` / `never` / `not a retry at all`). It is a property of the
  vocabulary, it belongs next to `REASONS` in `year_ledger.py` where a new
  reason cannot be added without classifying it, and it is testable without a
  database. Today it exists as `ACTIONABLE = ("failed", "indeterminate")`
  (`ledger_gaps.py:83-85`) — which is a *reporting* filter and already wrong as
  a *retry* filter, since `indeterminate` is a code fix, not a retry.
* **Per invocation:** the *change* that makes a "retry after a change" class
  eligible — `--reason api_no_data --recorded-before <ts>`, or `--source
  census_decennial --group 2000`. That is the operator asserting "I deployed
  the thing that makes this different", which is exactly the assertion
  `requeue_parcels.py --require-sha` already forces them to make and verify
  (`:98-181`).

**What this implies:** the retryable set is decided almost entirely by `outcome`
and `reason`, which the ledger already carries — the two things it does not
carry, attempt history and a fixed-by marker, are both consequences of the same
gap, that nothing records which code a run executed.

---

## 4. Reconciliation and `suppressed`

### 4.1 How deletion is decided today

`reconcile_source_snapshots` (`imagery.py:713-815`), called once per imagery
source at `timeline.py:679-685` with `scope=source_cfg["selection_scope"]` and
`timeline.py:545` (hardcoded `"decade"`) for topo.

```python
keep, groups = set(), set()
for stac_item_id, capture_date in selected:          # :770-773
    keep.add(stac_item_id); groups.add(encode_group_key(scope, capture_date))
if not keep: return 0                                # :775-776
# for each existing row of (parcel, source):         # :778-785
#   skip if its item id is in keep                   # :788-789
#   delete iff its group is in groups                # :790-792
```

Three rules, stated in the docstring (`:756-765`) and enforced by that loop:

1. an item still selected is kept;
2. a row whose group **is** in this run's selection and whose item id is not, is
   superseded → delete;
3. **a group absent from the selection is never touched.** The docstring's
   reason: an absent group usually means that chunk's search failed, and
   deleting on that basis converts a transient upstream error into permanent
   data loss.

Rule 3 is why `suppressed` survives. A NAIP year the point-coverage gate rejects
never enters `selected_groups` (`timeline.py:528-546` drops it *before* the
persist loop), so it never enters `selected_refs` (`:664`), so its group is not
in `groups`, so an already-written row for that year is invisible to the loop.
The gate refuses to **write**; it has no power to **remove**.

### 4.2 What it would take to let a `suppressed` outcome authorise a delete

The ledger is precisely the evidence rule 3 was written in the absence of.
Minimum shape:

* the run's `YearOutcomeLog` for this source is in hand at the reconcile call
  site (`timeline.py:679`) — `ledger` is in scope and has already been flushed
  at `:604-606`, so no new plumbing;
* pass the set of group keys this run recorded as `outcome == 'suppressed'`;
* a row whose group is in that set and whose **item id is named in the
  suppression's `detail`** is deleted;
* everything else is unchanged.

The item-id condition is the safety property, not decoration. The suppression
detail already carries the tile ids —
`"selected tiles do not contain the parcel: {', '.join(tile_ids)}"`
(`timeline.py:534-540`) — and the served row for `e513188c` names one of them.
Deleting only rows the gate positively identified means a *different* item that
happens to fall in the same year is left alone, and it makes the rule a
statement about an item rather than about a period.

### 4.3 What it must not do

* **An `absent/*` outcome is not authority to delete.** All four absent reasons
  mean "the fetch completed and found nothing usable *this time*". Rule 3's
  original reasoning applies unchanged, and the fleet numbers make the stakes
  concrete: `naip absent/no_scenes` is 1,848 latest rows (§8.1). A rule that
  deleted on absence would delete on the largest population in the ledger.
* **A `failed/*` outcome is not authority.** Strictly stronger: a failed search
  knows less than an absent one.
* **`indeterminate` is not authority**, by definition — it names a site that
  could not tell absence from truncation.
* **A `suppressed` row from an *older* run is not authority.** The delete must
  be driven by *this* run's outcomes, not by a ledger query, or a
  since-corrected suppression licenses a delete years later.
* **`suppressed/no_cog_url` should not be swept in with
  `naip_no_point_coverage` without deciding separately.** It means the selected
  item carried no COG asset (`timeline.py:600-614`); the previously-served row
  for that group may be a perfectly good *different* item. The item-id
  condition in §4.2 happens to make this safe, which is another argument for it.

### 4.4 `e513188c`'s 2023 row, traced

Read live 2026-08-26 ~09:50Z.

Served: `imagery_snapshots` row for `parcel e513188c`, `source naip`,
`capture_date 2023-08-20`, `stac_item_id
nj_m_4007309_sw_18_030_20230820_20231019`, `created_at 2026-05-23 08:02:12Z`.

Ledger, latest for `(e513188c, naip, 2023)`, run `2026-08-26 02:22:28Z`:
`suppressed` / `naip_no_point_coverage` /
`"selected tiles do not contain the parcel: nj_m_4007309_sw_18_030_20230820_20231019, nj_m_4007424_ne_18_030_20230820_20231019"`.

Today: the 2023 group is not in `selected_refs`; `groups` for that run contains
`{2010, 2011, 2013, 2015, 2017, 2019, 2021, 2022}` (the eight `ok` years); the
2023 row's group is not in it; the loop at `:787-792` skips it. **Kept.**

Under the §4.2 rule: `2023 ∈ suppressed_groups`, and the served row's item id
appears verbatim in the suppression detail → **deleted**, and the parcel's
timeline gains an honest gap at 2023 instead of a mosaic of the wrong place.

**Fleet-wide blast radius, measured today: one row.** Nine `suppressed` rows are
latest fleet-wide — `1754635c` ×5 (2010, 2013, 2015, 2017, 2019), `8d9ee137` ×3
(2012, 2014, 2016), `e513188c` ×1 (2023) — and a served-snapshot existence check
against each is `False` for the first eight and `True` only for `e513188c`. This
reproduces STATUS.md's G1 exactly and independently.

### 4.5 Does the rule survive the ADR?

Under `docs/adr/0001-imagery-normalization.md` the deletion becomes a
`parcel_scenes` delete, and the rule gets **simpler**, not harder:

* `parcel_scenes` is keyed `UNIQUE (parcel_id, source, group_key)` (ADR
  §`parcel_scenes`), and `group_key` is "the same encoding as the M4 ledger"
  (rule 2). The suppression's group key is therefore already the target row's
  key — the `_capture_date` parse and re-encode at `imagery.py:789-791` goes
  away entirely.
* Rule 1 ("the M4 ledger does not reference either table; the served row for a
  group is looked up by `(parcel_id, source, group_key)` at read time") is
  precisely the lookup §4.2 needs. The suppressed-delete rule is an instance of
  the read the ADR was designed to support.
* The item-id safety condition survives as a `scene_id` comparison —
  `parcel_scenes.scene_id` → `scenes.item_id` — which is a join rather than a
  string match, so it gets stricter.
* One thing to carry over deliberately: today the served-row check is against
  `stac_item_id` in the same table. Under normalization a mosaic's tiles live in
  `mosaic_scene_ids`, so "is the suppressed tile the one we served" must check
  the primary **and** the mosaic array, or a NAIP mosaic whose *primary* was not
  the named tile escapes.

**What this implies:** the deletion rule's whole content is "who is allowed to
say a served row is wrong", the ledger's `suppressed` outcome plus its item id
is the first thing in the system that can say it, and normalization makes the
same rule cheaper to express rather than obsolete.

---

## 5. The decennial-2000 heal, dry-run

**Premise correction first, because it changes what this section is.** The
prompt states the trim fix `e6afa9b` is deployed. **It is not.** Verified
2026-08-26 ~09:35Z:

```
$ fly image show -a plotline-worker
  … LABELS  … GH_SHA=43308335e366fed355eaa5b2d7c6a264303c475c
$ git merge-base --is-ancestor e6afa9b 4330833 ; echo $?
1
```

`e6afa9b` is four commits *after* `4330833` on `main` and is not in its
ancestry. Production is running the pre-trim code on both API and worker. **A
census-only re-run today would change nothing** — it would ask `157100`-shaped
tracts exactly as the sweep already did and re-record the same 80 `absent` rows.
The numbers below are the dry-run for the run that happens **after** `e6afa9b`
deploys; they are not a green light to run anything now.

### 5.1 The parcel list

Query: latest ledger outcome for `(source='census_decennial', group_key='2000')`
joined to `parcels.census_tract_id`, all 186 parcels, read 2026-08-26 ~09:45Z.

| | tract ends `00` | tract does not | total |
|---|---:|---:|---:|
| `ok` | **0** | 47 | 47 |
| `absent` / `api_no_data` | **80** | 59 | 139 |

**80 parcels, no exceptions in either direction** — reproducing
`../2026-08-census-decennial/REPORT.md` §1.2 exactly, on a fleet that has since
grown from 184 to 186. The 80, by stored tract:

```
06001401700 06001422100 06057000900 06067000400 06073001400 06081604900
06085511200 08031002000 08031002000 08031015300 08069002700 08077000200
08077000700 09170157100 11001980000 11001980000 11001980000 12087970900
12099002600 13121002500 13121003900 13313000700 17031320400 17031839100
17031980000 17161021100 17201000600 19113001500 24510010500 25005632100
25017356300 26019000500 26021001300 26039960500 26061000800 26089970100
26125131500 27053110900 27123032000 29147470400 31055002500 31105954500
33015051000 33015058000 34023001100 34023006500 34023009300 34023009300
34029713100 34029713600 36047019500 36059409000 36061000900 36061001300
36061003100 36061007600 36063021100 36081071100 36081073900 36111952300
36121970700 39103405000 41039004600 41039005000 41041951100 41041951200
41065970200 42101007900 47065001800 48453000700 48453032600 49035101800
50007000100 51013101300 51760020900 53007960700 53035940000 53073001000
53075000700 55079187300
```

(80 rows; duplicates are distinct parcels sharing a tract.) The full
parcel-uuid ↔ tract mapping was read in the same query and is reproducible from
it; it is not pasted here because the tract list is the operative key and the
uuids churn as the fleet grows.

**Expected recovery: 64 of 80.** The 16 that answer 204 even under the
four-character form are listed by tract in
`../2026-08-census-decennial/REPORT.md` §1.5 — `08031015300`, `09170157100`,
`11001980000` (×3), `17031839100`, `17031980000`, `26019000500`, `26061000800`,
`29147470400`, `34023009300` (×2), `36121970700`, `48453032600`, `53035940000`,
`55079187300`. All sixteen appear in the 80 above; the arithmetic closes.
`09170157100` (Racebrook) is 204 for a second, unrelated reason — its stored
county is a planning region no decennial vintage knows.

This is `PREDICTION.md` P8 restated against a 186-parcel fleet with the same
numbers, because the two parcels added since the sweep both landed in the
ends-in-`00` set and both are already `absent`.

### 5.2 What a census-only scoped re-run touches

Per parcel, one `census` task; `_fetch_census` → `_fetch_census_years`
(`timeline.py:1010-1172`):

* **3 decennial years** (`DECENNIAL_YEARS = [2000, 2010, 2020]`,
  `census.py:91` — 1990 is gone as of `e6afa9b`) and **6 ACS5 years**
  (`ACS5_YEARS = [2009, 2012, 2015, 2018, 2021, 2023]`, `:92`);
* up to 9 Census API calls plus one geocoder call per distinct geography
  vintage (`_VintageTracts`, `timeline.py:959-1008`), with a 0.5s sleep between
  years (`:1094`, `:1141`);
* 9 ledger rows upserted on the census task;
* **no imagery task rows created, no STAC search, no signing calls, and — the
  point — `reconcile_source_snapshots` is not reached at all.** It is called
  only from `_search_and_persist_source` (`timeline.py:679`) and
  `_search_and_persist_topo` (`:545`), both of which live behind imagery task
  coroutines that a census-only scope does not create.

Cost estimate for 80 parcels: ~720 Census API calls, ~4.5 s of deliberate sleep
per parcel, so wall time is dominated by how many run concurrently (§7), not by
the API.

### 5.3 Is the re-run add-only?

**Yes, and it is proven twice over.**

*Structurally* (`../2026-08-geometry-audit/CENSUS_TRIAGE.md` §2, §3c): exactly
one `DELETE` exists in the backend and it is hard-scoped to `imagery_snapshots`
(`imagery.py`, inside `reconcile_source_snapshots`); `census_snapshots` has no
triggers and its only delete-capable constraint is the parcel FK cascade. The
unique key is `(parcel_id, dataset, year)` — `tract_fips` is not in it — so a
re-fetch **overwrites in place**; it can never insert alongside and never
removes. And a year that fails or comes back empty runs **no statement at all**:
the upsert is inside `if data:` (`timeline.py:1046`, `:1108`), so a failure is
net zero, not −1.

*Confirmed against the current code:* `upsert_census_snapshot`
(`demographics.py:76-105`) is `ON CONFLICT (parcel_id, dataset, year) DO UPDATE`
over the demographic columns, `raw_data`, **and `tract_fips`** — the last of
which is a change since CENSUS_TRIAGE §4 flagged its omission as a provenance
defect. `created_at` remains outside the update list, so it is still a true
birth timestamp and the window arithmetic CENSUS_TRIAGE relies on still holds.

For these 80 parcels specifically the 47 `ok` parcels are untouched (their
tracts do not end in `00`, so `_tract_for_dataset` (`census.py:360-370`) does
not fire), and each of the 80 can only gain a `(decennial, 2000)` row or stay as
it is.

**What this implies:** the acceptance case is an 80-parcel, census-only,
add-only run whose expected delta is exactly 64 new `census_snapshots` rows and
64 ledger rows moving `absent` → `ok` — and it cannot be run until `e6afa9b`
reaches the worker, which it has not.

---

## 6. What the existing heal scripts become

| script | after M3 | why |
|---|---|---|
| `revalidate_landsat.py` | **subsumed as a finder; survives as a sweeper** | Its selection is `SELECT parcel_id FROM imagery_snapshots WHERE source='landsat' GROUP BY parcel_id` — every parcel, targeting nothing. That half dies: the ledger expresses its real predicate (`--source landsat --outcome failed`) directly. What does *not* die is its second job, which its own docstring names (`:11-14`): it is the fleet-wide sweep used to realise a selection-changing deploy, and "re-run everything under the new code" is not a ledger query. Expect it to lose `_landsat_parcels` and keep `--skip-swept-since`, `--max-wait-minutes`, and the admission wait. |
| `requeue_parcels.py` | **remains, and becomes the delivery mechanism M3 selects into** | It runs no selection query at all (`:184-188` only validates ids exist); its substance is the deployed-SHA gate (`:98-181`). That gate is exactly what §3.3's "fixed-by marker" needs an operator to assert, and §5's premise correction is a live demonstration of why it exists. `--sources` lands here (§2.1). |
| `heal_tract_vintage_gaps.py` | **subsumed, and should be deleted rather than ported** | Its selection reconstructs the ledger in Python (`:69-81`) and its "2021 or 2023 present" test is an explicit proxy for "was this parcel ever fetched" — its own comment says so. The ledger answers that with a fact. Its *dispatch* mechanism (call `_fetch_census` in-place against a reused request, `:169-178`) is the anti-pattern §1.4 and §3.1 describe and must not become M3's model. |
| `requeue_empty_property.py` | **remains, and needs a fix M3 causes** | Its subject is complete-with-zero over a whole source, which has no period key. §2.2b: once scoped requests exist, its `latest request` join silently loses every parcel whose most recent request did not run `property`. Whatever M3 does about "latest request that ran source X" has to reach this script in the same batch. |

### 6.1 Property has no ledger source — what that means

`property` writes no `timeline_task_years` rows at all. It is the one source in
`VALID_SOURCES` (`models/parcels.py:163`) with no per-period structure: events
are addressed by `(parcel_id, source, source_record_id)` and an event's
`event_date` is an attribute of the record, not a thing we searched for.

**Does property need an outcome ledger of its own?** The honest answer from the
code is: it has one axis, and it is not time. `_fetch_and_persist_property`
(`timeline.py:1259-1279`) fans out over exactly **two feeds** —
`adapter.fetch_sales(...)` and `adapter.fetch_permits(...)` — each returning its
own `queries_attempted` / `queries_failed`, and then **collapses them**: the
task is marked `failed` only when `queries_failed == queries_attempted` across
both (`:1266-1278`), and `complete` otherwise. So **sales succeeding while
permits fails entirely is recorded as `complete`** — the same complete-with-zero
shape M4 exists to make visible, one level up from years.

If property gets a ledger, its `group_key` is the **feed**, not a period:
`"sales"` and `"permits"`, with the whole-source sentinel
`WHOLE_SOURCE_GROUP_KEY = "*"` (`imagery.py:672-681`) available for an
adapter-level failure that precedes both. That is the same move topo already
made — topo records one `*` row because its attempted decade set is not
enumerable from configuration (REPORT §4f). Two rows per property task, `ok` /
`failed` / `absent(no records)`, would make `requeue_empty_property.py`'s
predicate a ledger query like the other two — and would distinguish "this
address genuinely has no permits" from "the permits endpoint was down", which
is exactly the distinction that script was written because we could not make.

**Not recommended here, only scoped.** It is a separate change with its own
vocabulary decision (`absent` needs a reason that is not `no_scenes`), and
nothing in M3 depends on it.

**What this implies:** M3 retires two selection queries and no scripts — the two
"subsumed" scripts each carry a second job (a fleet sweep, an in-place census
call) that the ledger does not replace, and the one script M3 actively breaks is
the one whose source has no ledger at all.

---

## 7. Cooldown and the admission cap

### 7.1 The cap, and who competes for it

`ensure_admission` (`admission.py:54-76`) counts `TimelineRequest` rows in
`(queued, processing)` and refuses at `max_inflight_timeline_requests = 30`
(`config.py:92`). Two call sites: `parcels.py:139` (`what="parcel"`) and
`imagery.py:114` (`what="timeline_request"`) — the latter is inside
`_create_queued_request`, which **every** new pipeline run passes through:
user-initiated, backfill, and every heal script alike.

`what` is a log field only (`:59`, `:68`). It is not read by any policy.

### 7.2 Are backfill requests distinguishable from user ones?

**No.** `TimelineRequest` carries `id, parcel_id, status, created_at,
updated_at, completed_at, error_message` (`models/parcels.py:94-152`) and
nothing else. There is no origin, no priority, no requester. The row a backfill
creates at `imagery.py:455` and the row a first-time geocode creates at
`geocode.py:284` are byte-identical in shape. Neither `ensure_admission` nor
`inflight_depth` (`admission.py:44-51`) can tell them apart, and neither can any
heal script's wait loop.

The one asymmetry that exists today is in how a refusal is *handled*, not in
whether it happens: backfill catches `AdmissionRefused` and returns `None`
silently (`imagery.py:456-463`, "a backfill is optional work on a parcel that
already renders"), while a user-facing refusal becomes a 503 with `Retry-After`
(`imagery.py:83-88` in the API layer, `geocode.py:267-270`). So under
saturation **backfill already yields** — but only after it has already taken a
slot on every prior request that got in.

### 7.3 What actually stops a burst today

Three things, in order of effectiveness:

1. **The one-in-flight-per-parcel unique index.**
   `uq_timeline_requests_parcel_inflight ON timeline_requests (parcel_id) WHERE
   status IN ('queued','processing')` (`alembic/versions/0010_review_hardening.py:65-69`).
   A parcel can occupy at most one of the 30 slots. With 186 parcels the
   theoretical worst case is 186 queued requests fighting for 30 slots, not
   thousands.
2. **The cooldown**, `backfill_cooldown_hours = 6.0` (`config.py:72`), read at
   `imagery.py:434-452` as `now() - max(TimelineRequest.created_at)` for the
   parcel. It is **dispatch-anchored**: it measures time since the newest
   request was *created*, not since a source was last *attempted*. Per parcel,
   not per source. So a census-only backfill fired at T blocks a landsat
   backfill until T+6h, and a full sweep by `revalidate_landsat.py` resets the
   clock on all 186 parcels at once.
3. **Page-view arrival rate.** Backfill only fires from a page view of that
   parcel, so the burst is bounded by traffic, not by the size of the backlog.

### 7.4 What changes when backfill can find work on most parcels

Today `needs_refetch` is false for essentially every parcel (§1.1 walks the
three triggers). Under a ledger-reading selector, §8's numbers say **80 of 186
parcels** have at least one retryable group once `e6afa9b` deploys. Every page
view of any of those 80 becomes a dispatch candidate.

That is still bounded by (1) and (2) — at most 80 slots' worth of demand,
against a cap of 30, refreshing every 6 hours. It does not saturate on its own.
What it does do is make the *mix* matter for the first time: with the queue at
depth 30, a first-time visitor's geocode and a backfill for a six-year-old
Landsat gap are indistinguishable to the gate, and the geocode is the one whose
refusal a human sees as a 503.

The mechanism that would fix that is the same one §3.3 wants for a different
reason: **something on the request row that says what it is.** An `origin`
column (`'user' | 'backfill' | 'heal'`) makes three things possible that are
impossible today — a lower cap for non-user work (`ensure_admission` gains a
per-origin ceiling), a drain order, and the ability to *measure* the mix, which
right now cannot be measured at all. It is the M9-shaped question in the sense
the prompt means: the instrument is missing, not the policy.

**What this implies:** nothing today distinguishes a backfill request from a
user request at the gate, so the only reason a ledger-driven backfill does not
starve user traffic is that the per-parcel index and the six-hour cooldown cap
demand at ~80 parcels — a bound that comes from the size of the fleet, not from
any decision about priority.

---

## 8. Prod numbers

All read 2026-08-26 between ~09:35Z and ~10:05Z via `fly ssh console -a
log0s-plotline-api -C "python -c …"`, `SELECT` only. Fleet: **186 parcels**,
709 `timeline_requests`. **Zero parcels have no ledger rows** — the M4 ledger's
"absence is not evidence of health until every parcel has been swept once"
caveat (`ledger_gaps.py:19-24`) is now closed: every parcel in the fleet has
been swept.

### 8.1 Latest outcome per (parcel, source, group), by source

| source | outcome | reason | groups |
|---|---|---|---:|
| `census_acs5` | `ok` | | 1,042 |
| `census_acs5` | `absent` | `api_no_data` | 74 |
| `census_decennial` | `ok` | | 419 |
| `census_decennial` | `absent` | `api_no_data` | 325 |
| `landsat` | `ok` | | 7,981 |
| `landsat` | **`failed`** | **`read_timeout`** | **17** |
| `naip` | `ok` | | 1,281 |
| `naip` | `absent` | `no_scenes` | 1,848 |
| `naip` | **`failed`** | **`read_timeout`** | **17** |
| `naip` | `indeterminate` | item cap | 7 |
| `naip` | `suppressed` | `naip_no_point_coverage` | 9 |
| `sentinel2` | `ok` | | 2,211 |
| `sentinel2` | `absent` | `all_cloud_filtered` | 9 |
| `usgs_topo` | `ok` | | 1,165 |
| `usgs_topo` | `absent` | `no_scenes` | 1 |
| `usgs_topo` | `indeterminate` | TNM row cap | 1 |

Total 16,406 triples with a latest outcome. Never-`ok` triples (no run has ever
recorded `ok`): `census_decennial` 325, `naip` 1,881, `census_acs5` 74,
`landsat` 17, `sentinel2` 9, `usgs_topo` 2.

### 8.2 The backlog M3's first run would face, under §3.2's policy

| class | source | groups | parcels |
|---|---|---:|---:|
| **A — retry now** (`failed/read_timeout`) | `landsat` | 17 | 2 |
| **A — retry now** | `naip` | 17 | 1 |
| **B — retry after `e6afa9b` deploys** (`absent/api_no_data`, decennial 2000, tract ends `00`) | `census_decennial` | 80 | 80 |
| C — disappears at deploy (decennial 1990, never attempted after `e6afa9b`) | `census_decennial` | 186 | 186 |
| D — code fix, not a retry (`indeterminate`) | `naip` 7, `usgs_topo` 1 | 8 | 2 |
| E — only if the cloud threshold changes (`absent/all_cloud_filtered`) | `sentinel2` | 9 | 9 |
| F — reconciliation input, never a retry (`suppressed`) | `naip` | 9 | 3 |
| G — never retryable (`ok`, `absent/no_scenes`, remaining `absent/api_no_data`) | all | 16,081 | 186 |

**A + B is the whole first-run backlog: 114 groups across 80 distinct parcels**
(both A-parcels are inside the B-80). At the current cap that is fewer than
three full queue-depths, and §5.2 establishes the B half needs no imagery work
at all.

Attempt counts on the 2,283 non-`ok` latest rows: **2,270 read `attempts = 1`**,
13 read 2 (11 `naip absent`, 2 `census_decennial absent`). §3.3's point,
measured.

### 8.3 New — the first `failed` rows the ledger has ever recorded in production

`BASELINE-failed.txt` (03:07Z, SHA `3a86dd69`) reads *"No ledger rows match. 0
(parcel, source, group) triples"*, and `PREDICTION.md` P4 was confirmed at zero
`failed` fleet-wide. **Six hours later there are 34**, on two parcels that did
not exist at baseline:

* **`09f35468`** (New York County, NY; parcel and its only request both created
  2026-08-26 08:04:56Z). `landsat/1994` = `failed`/`read_timeout`. Task
  `landsat` = `complete`, `items_found` 42. Request `complete`. One silently
  lost year.
* **`6563dedf`** (Crawford County, MI; created 2026-08-26 09:14:34Z). **16
  Landsat years failed** (1984–1999, contiguous) and **17 NAIP years failed**
  (2010–2026, every year the source has), all `read_timeout`. Task rows:
  `naip` **failed**, `sentinel2` **failed**, `landsat` `complete` with
  `items_found` 27, `usgs_topo` `complete`, `census` `complete`, `property`
  `skipped` (no adapter). **Request status: `complete`.** Served snapshots: 27
  Landsat, **0 NAIP, 0 Sentinel-2**.

Three things follow, and all three belong in the build pass's framing:

1. **The instrument works.** This is the M4 shape — an upstream burst costing
   contiguous years under a `complete` request — caught in the act, with a
   machine-readable reason, on the day the ledger was populated. Before the
   ledger, `09f35468` would have been undetectable and `6563dedf` would have
   been "a parcel with no NAIP, cause unknown".
2. **Today's backfill cannot touch either.** §1.1 walks `6563dedf` through all
   three triggers and it fails every one, because Crawford County has no
   property adapter and the census and topo tasks completed. A parcel whose page
   shows no aerial imagery at all will never be retried by any code path that
   runs on its own.
3. **`revalidate_landsat.py` would not find `6563dedf` either** — its selection
   is parcels *holding* Landsat rows, and this one does hold 27, so it would be
   swept incidentally by a fleet-wide run and never by a targeted one.

**What this implies:** the retryable backlog M3's first run faces is 114 groups
on 80 parcels, four fifths of it census work that needs no imagery pipeline at
all, and the sharpest case in it appeared six hours after the baseline was taken
on a parcel today's backfill is structurally unable to see.

---

## Consolidated UNVERIFIED register

1. **The 16 tracts that 204 under the four-character form were not re-probed
   here.** §5.1 carries them forward from
   `../2026-08-census-decennial/REPORT.md` §1.5 (probed 2026-08-26, earlier the
   same day). The 80/64 split is only as current as that probe. Re-probing is a
   live-API call this session did not make.
2. **No estimate of how often backfill currently fires in production.** §7.4's
   claim that demand is bounded at ~80 parcels is arithmetic over the ledger,
   not a measurement of dispatch rate. `fly logs` was not read for
   `"Created new timeline request for backfill"` lines.
3. **The UI regression in §2.1 is read from the code, not observed.** No scoped
   request exists to render, so "a previously-`failed` landsat row disappears
   from `ParcelInfo`'s unavailable list" is a reading of
   `ParcelInfo.tsx:131-136` against `TimelineRequestResponse.tasks`, not a
   screenshot.
4. **Whether `suppressed/no_cog_url` has ever fired in production is unknown.**
   Zero rows carry that reason today; whether that means it is unreachable or
   merely rare is not established. §4.3's caution about it is precautionary.
5. **The cost estimate in §5.2 (~720 Census API calls) assumes no vintage
   geocoder call is cached across parcels.** `_VintageTracts` caches per
   parcel-instance only (`timeline.py:966`), so this is an upper bound on
   geocoder calls and an exact count on Census calls only if every year is
   attempted — which a `CensusMissingKeyError` would cut short.
6. **`property`'s two-feed collapse (§6.1) is read from
   `_fetch_and_persist_property` only.** Whether any adapter reports
   `queries_attempted` in a way that makes a per-feed ledger row meaningful for
   *all* counties was not checked adapter by adapter (`county_adapters.py` is
   917 lines and was not read in full).
7. **§8's numbers are a single point-in-time read.** The fleet gained two
   parcels and 34 `failed` rows in the six hours before it; nothing here is a
   trend.

---

## Premises in the prompt that I found to be wrong

1. **"the trim fix (`e6afa9b`) is deployed" — false, and load-bearing.**
   `fly image show -a plotline-worker` reports `GH_SHA=43308335e366…`, and
   `git merge-base --is-ancestor e6afa9b 4330833` exits 1: `e6afa9b` is four
   commits later on `main` and is not in the deployed image's ancestry. Both
   API and worker are on `4330833`. §5 is therefore a dry-run for a run that
   **cannot be executed yet**, and any build-pass prediction that assumes
   otherwise would be scored against the wrong code. Item 5 was completed under
   the corrected premise rather than stopped, because the numbers it asks for
   are unaffected by *when* the run happens.
2. **"both visible in `BASELINE.txt` today" — half right.** `e513188c`'s NAIP
   2023 suppression is in `BASELINE.txt` and was re-confirmed live. The
   decennial-2000 case is in `BASELINE.txt` only as undifferentiated `absent`
   rows over 184 parcels; the 80/64 split does not appear there and comes from
   `../2026-08-census-decennial/REPORT.md` §1.2/§1.5 plus the live query in
   §5.1 over 186 parcels. Not a defect in the prompt, but the baseline is not
   the source for item 5's numbers and should not be cited as one.
3. **"which are subsumed … and which are deleted" presumes deletion follows
   subsumption.** §6 finds it does not: both subsumed scripts carry a second
   job the ledger does not replace, so M3 retires two *selection queries* and
   zero scripts. Stated here because the item's framing invites an answer the
   code does not support.

Everything else in the prompt held: `maybe_refetch_for_backfill` does inspect no
imagery source and its topo check does test row absence only (§1.1); the M4
ledger is deployed and populated fleet-wide, now measurably so at 0 unswept
parcels (§8); `reconcile_source_snapshots` never deletes an absent group and the
`e513188c` card is still served (§4.4); `ledger_gaps.py` does already compute
latest-outcome-per-triple (§3.1).

---

### Record-keeping note

§8.3 is a new production defect discovered by this investigation. Per the
project's third record rule — a discovery enters STATUS.md even if unfixed — it
is filed there in this batch under **To investigate**, with the parcel ids, the
task/ledger split, and the reason today's backfill cannot reach it. Nothing else
in this report changes a STATUS.md claim: M3 remains deferred and no finding was
resolved here. One STATUS.md statement is now stale in the other direction and
is *not* edited — the M4 row's "zero `failed` rows fleet-wide" was true as
measured at 03:07Z and stays as written; §8.3 and the new row are where the
later measurement lives.
