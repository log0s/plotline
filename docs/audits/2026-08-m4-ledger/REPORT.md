# M4 — per-year outcome ledger, as built

**Date:** 2026-08-25
**HEAD at writing:** `ef2d0a2` (the docs commit follows).
**Deploy state: committed, not deployed.** Nothing in this batch is running.
**Production writes: none.** No sweep, no heal, no migration run anywhere.

Three commits:

| Hash | Contents |
|---|---|
| `0814d7e` | Migration `0011`, `TimelineTaskYear` ORM model, `conftest.py` DDL |
| `ef2d0a2` | `group_key` encoding, `services/year_ledger.py`, all seven loop sites, `scripts/ledger_gaps.py`, tests |
| *(this commit)* | This report, `PREDICTION.md`, `STATUS.md` |

Line citations are against `ef2d0a2`. `backend/` is elided for files under
`backend/app` and `backend/tests`.

---

## 1. Schema as landed

**Alembic head before: `0010`. After: `0011`.** The chain stays linear —
verified with `ScriptDirectory.walk_revisions()`, one head, `0011 <- 0010 <-
… <- 0001`.

Rendered offline with `alembic upgrade 0010:0011 --sql`, which is the exact
DDL that will run:

```sql
CREATE TABLE timeline_task_years (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    task_id UUID NOT NULL,
    source TEXT NOT NULL,
    group_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_tty_task_id FOREIGN KEY(task_id)
        REFERENCES timeline_request_tasks (id) ON DELETE CASCADE,
    CONSTRAINT ck_tty_outcome CHECK (outcome IN
        ('ok', 'failed', 'absent', 'indeterminate', 'suppressed')),
    CONSTRAINT uq_tty_task_group UNIQUE (task_id, group_key)
);
CREATE INDEX idx_tty_source_group_outcome
    ON timeline_task_years (source, group_key, outcome);
CREATE INDEX idx_tty_task ON timeline_task_years (task_id);
```

Three declarations of the same table, as the repo requires:
`alembic/versions/0011_timeline_task_years.py`, `app/models/parcels.py:221-281`
(`TimelineTaskYear`), `tests/conftest.py:111-139` (SQLite).

**Nothing on `timeline_request_tasks` is touched.** The migration adds a
table and two indexes and issues no `ALTER`, so the ORM/database
CHECK-constraint name drift (M7 item 5 — ORM `ck_trt_source` /
`ck_trt_status`, database `ck_timeline_request_tasks_source` / `..._status`)
cannot bite it. Every constraint on the new table is named explicitly in the
migration and the ORM repeats those names verbatim, so this table starts
without drift of its own.

**No snapshot reference.** No `snapshot_id`, no FK to `imagery_snapshots`, by
rule 1 of `docs/adr/0001-imagery-normalization.md`. The served row for a group
is looked up by `(parcel_id, source, group_key)` at read time — see the P6
queries in `PREDICTION.md`.

**`source` is not always the task's source.** One `census` task row covers two
datasets, so its ledger rows carry `census_decennial` / `census_acs5`. That is
safe only while `DECENNIAL_YEARS` and `ACS5_YEARS` are disjoint — the unique
key is `(task_id, group_key)`, so a year in both lists would collide and the
second write would silently overwrite the first. The assumption is written at
the site (`app/tasks/timeline.py:1022-1029`), per the CLAUDE.md rule for
load-bearing assumptions.

### Observation, not a deviation

`idx_tty_task` on `(task_id)` is a prefix of the index `uq_tty_task_group`
already creates, so it serves no query the unique index could not. It is
built because the prompt's schema names it; on a table projected to grow ~23×
faster than its parent it is a small standing write cost. Dropping it would be
a one-line follow-up migration if the cost ever shows up.

---

## 2. `group_key` — one encoding, one place

Defined in `app/services/imagery.py` beside `SELECTION_SCOPES`
(`:642-652`): `_GROUP_KEY_ENCODERS` (`:668-672`), `encode_group_key`
(`:681`), `decode_group_key` (`:693`), `WHOLE_SOURCE_GROUP_KEY` (`:678`).

| scope | key | decode range |
|---|---|---|
| `year` | `"1993"` | 1993-01-01 … 1993-12-31 |
| `quarter` | `"1993Q3"` | 1993-07-01 … 1993-09-30 |
| `decade` | `"1960s"` | 1960-01-01 … 1969-12-31 |

`encode_group_key` accepts a `date` or a bare `int` year, because the topo
path derives its key from an `int` before anything becomes a date
(`usgs_topo._publication_year`) and the census year lists are ints — the
asymmetry INVESTIGATION §6 flagged as making `SELECTION_SCOPES["decade"]` not
directly reusable there.

### All five inlined derivations replaced

INVESTIGATION §6 listed five. All five now call `encode_group_key`; none was
left.

| rule | site before | site now |
|---|---|---|
| year | `reconcile_source_snapshots`, `bucket(capture_date)` | `imagery.py:774`, `:792` |
| year | `select_naip_items`, `by_year[…year]` | `stac.py:796` |
| year | `select_landsat_items`, `by_year[…year]` | `stac.py:925` |
| year | `select_sentinel_items`, `by_year[…year]` | `stac.py:959` |
| decade | `select_topo_items`, `(year // 10) * 10` | `usgs_topo.py:150` |
| year | `_validate_selection` callers, `period=lambda d: d.year` | `stac.py:1279`, `:1305` |

Four of those changed a dict key from `int` (or a tuple) to `str`, and three
of them sort those keys — `sorted(by_year.keys())` in `select_naip_items`,
`sorted(by_decade.keys())` in `select_topo_items`. **Behaviour is preserved
because every encoding is prefixed by a four-digit year, so lexicographic
order equals chronological order.** That is the load-bearing assumption; it is
stated as a comment on `_GROUP_KEY_ENCODERS` and at both sorting sites, and it
breaks for a source predating year 1000. Nothing in the repo has one.

`stac.item_group_key(item, scope)` (`stac.py:1045`) is the one bridge from a
STAC item to a key; it returns `None` for an item with `"datetime": null`,
which is the same item the selectors already drop.

### `SELECTION_SCOPES` round-trip

`tests/test_year_ledger.py::test_every_selection_scope_round_trips` asserts,
for every scope in `SELECTION_SCOPES` including the unused `quarter`, that
`decode(encode(d))` covers `d` and that re-encoding either endpoint returns
the same key. A scope the ledger cannot encode is a scope whose rows nothing
could target.

---

## 3. Vocabulary

`app/services/year_ledger.py:31-99`. Outcomes as specified. Reasons as
specified for `failed` and `absent`; `suppressed` gained four beyond
`naip_no_point_coverage`, each named for a live site:

| reason | site | live or latent |
|---|---|---|
| `naip_no_point_coverage` | `timeline.py:523` | live (14b59af) |
| `no_cog_url` | `timeline.py:603` | live — was a silent `continue` |
| `topo_no_source_id` | `timeline.py:858` | **live** — the door topo loses sheets through |
| `topo_no_geotiff_url` | `timeline.py:802` | latent — `search_usgs_topo_products` already filters these out |
| `topo_unparseable_date` | `timeline.py:827` | latent — `select_topo_items` already drops these |

The two latent ones are recorded because a row carrying either means an
upstream shape defeated a filter, which is itself the finding (INVESTIGATION
§3e, UNVERIFIED item 7).

`indeterminate` takes free text and `_validate` (`year_ledger.py:113`)
*requires* it — a confession with no site named is worse than none.
`LedgerVocabularyError` is raised at record time, in the accumulator too, so a
typo fails a test rather than becoming a `WHERE` clause that matches nothing.

---

## 4. Per-loop mapping, as implemented

Where the prompt's expected mapping and the code disagreed, the code wins and
the difference is stated.

### 4a. Landsat / Sentinel-2 — the STAC year-chunk loop (`timeline.py:388-418`)

| situation | outcome | reason | site |
|---|---|---|---|
| chunk raised, status 403 | `failed` | `stac_403` | `:396` via `_stac_failure_reason` `:146` |
| chunk raised, status 5xx | `failed` | `stac_5xx` | `:396` |
| chunk raised, `httpx.TimeoutException` | `failed` | `read_timeout` | `:396` |
| chunk raised, other transport error | `failed` | `connect_error` | `:396` |
| chunk returned `[]`, unfiltered probe finds scenes | `absent` | `all_cloud_filtered` | `:409-415` |
| chunk returned `[]`, probe finds nothing | `absent` | `no_scenes` | `:409-415` |
| chunk returned `[]`, probe itself failed | `indeterminate` | free text | `_classify_empty_chunk:232` |

**Correction to the prompt's mapping — `all_cloud_filtered` is not observable
without an extra request.** The prompt expected "items but all ≥ cloud
threshold → `absent/all_cloud_filtered`". There is no such state at this site:
`eo:cloud_cover < 40` is pushed into the STAC query itself
(`_SOURCES`, `query`), so a year whose every scene is cloudy and a year the
satellite never imaged both arrive as the same empty list. The prompt's own
P3 — nine `all_cloud_filtered` rows for S2 2015 — could not be satisfied by
reading the response.

So `_classify_empty_chunk` (`timeline.py:200-235`) re-runs the year's search
**once, with the cloud query dropped and `max_items=1`**, only for years that
came back empty and only for sources that carry a cloud query. Cost: one extra
STAC request per empty year. Fleet Landsat sits at 43 of 43 years for most
parcels (INVESTIGATION §7), so this is a handful of requests per run against
the 55 the run already makes. This is a **deviation: it changes what the
fetch does upstream**, not only what it records. It is the smallest change
that makes the reason field mean what the O6 check needed it to mean.

**A STAC 429 lands in `other`,** with the status in `detail`. The prompt's
`failed` vocabulary has `sign_429` (the signing endpoint) and no STAC
equivalent; inventing `stac_429` would put a reason in the table that no
reader knows to look for. `_search_stac_with_retry` retries 429 three times
first, so reaching this branch means a sustained refusal.

### 4b. Spatial filter and the attempted set (`timeline.py:485-503`)

After the point/viewport filter, every attempted key with no verdict yet:

| situation | outcome | reason |
|---|---|---|
| the search covered the period and returned nothing, pool not capped | `absent` | `no_scenes` |
| …pool capped | `indeterminate` | `… hit its item cap …` |
| items came back, none survived the spatial filter | `absent` | `no_covering_item` |

**NAIP's attempted set is the query's own `datetime_range`**
(`_range_years`, `timeline.py:182`), 2010–2026 today. INVESTIGATION UNVERIFIED
item 2 said NAIP's attempted year set "is not knowable from code at all"
because it runs no per-year loop. That is true of the *response*; the query's
date range still says which years were asked about, and that is what
"attempted" means. It makes NAIP fully enumerable, which the whole-source
fallback would not have.

### 4c. NAIP point-coverage gate (`timeline.py:519-531`)

Served → `ok` (4e). Selection dropped for no covering tile →
`suppressed` / `naip_no_point_coverage`, with the tile ids in `detail`. No
items for a year → `absent` / `no_scenes` via 4b.

### 4d. The validation walk (`stac.py:1165-1268`, recorded at `timeline.py:565-569`)

`_validate_asset` (`stac.py:1078`) now returns `str | None` — the reason, or
`None` for servable — instead of a bare `False`. That bare `False` was N1:
a missing asset key, a non-allowlisted host, a signing failure, an HTTP ≥ 400
from the HEAD and a network error were one value, so "this scene is broken"
and "the signing endpoint is unhealthy" were indistinguishable.

| failure | reason |
|---|---|
| missing asset key / non-allowlisted host / HEAD ≥ 400 | `validation_failed` |
| signing raised 429 | `sign_429` (`signing_failure_reason`, `stac.py:1057`) |
| signing raised 5xx | `sign_5xx` |
| signing raised other status | `other` |
| signing or HEAD raised a timeout | `read_timeout` |
| signing or HEAD raised another transport error | `connect_error` |

`validate_landsat_item` / `validate_sentinel_item` keep their boolean shape
for existing callers; `check_landsat_item` / `check_sentinel_item` are the
reason-returning pair the walk uses.

`_validate_selection` fills an optional `notes: dict[str, GroupNote]`
out-parameter (`stac.py:1249`, `:1261`) rather than returning a second value,
so the two public wrappers' signatures stay compatible. A dropped period gets
`GroupNote("failed", <last candidate's reason>, …)`; a period rescued by a
fallback gets `GroupNote("ok", None, "served by validation fallback: X -> Y")`.

**The reason recorded is the *last* candidate's, not the first's** — the walk
re-signs every candidate against the same endpoint, so when signing is what is
broken, the last answer describes the walk. This matches the prompt.

**Correction to the prompt's premise — there is no relaxed threshold.** The
prompt asked for "a group served by the fallback is `ok` with `detail` noting
the relaxed threshold". `e7d4c6d` gave Sentinel-2 the validation fallback
Landsat already had; nothing about the walk relaxes a criterion (INVESTIGATION
"Premises … I found to be wrong", item 1). The `detail` names the swap
instead, which is the fact that exists.

### 4e. Persist (`timeline.py:596-660`)

| situation | outcome | reason |
|---|---|---|
| snapshot written | `ok` | — (detail carries the fallback swap when there was one) |
| selected group's primary item has no COG asset | `suppressed` | `no_cog_url` |
| attempted, reached the end with no verdict | `indeterminate` | `… no outcome` |

The `ok` write is `commit=False` **immediately before**
`upsert_imagery_snapshot`, whose own `db.commit()` carries both. Neither
upsert was modified. An `ok` committed first would be a claim about a row that
might never arrive; this ordering makes that shape unreachable.

### 4f. USGS topo (`timeline.py:745-890`)

| situation | key | outcome | reason |
|---|---|---|---|
| TNM transport failure | `*` | `failed` | mapped as 4a |
| TNM non-JSON body (`ValueError`) | `*` | `failed` | `other` |
| response capped at 100 | `*` | `indeterminate` | `… row cap …` |
| response empty, not capped | `*` | `absent` | `no_scenes` |
| sheet served for a decade | `"1960s"` | `ok` | — |
| product with no `sourceId` | its decade | `suppressed` | `topo_no_source_id` |
| product with no GeoTIFF url | its decade | `suppressed` | `topo_no_geotiff_url` |
| product with unparseable date | `*` | `suppressed` | `topo_unparseable_date` |

**Correction to the prompt's mapping — "no products for the decade →
`absent/no_scenes`" is not expressible.** Topo runs one untimed TNM query and
has no configured decade range, so there is no set of attempted decades to
mark absent against. Inventing one (say 1880s–2010s) would be a claim about
the collection that nothing in the repo supports. The whole-search verdict
goes under `WHOLE_SOURCE_GROUP_KEY` (`"*"`) instead, and per-decade rows cover
only what the response held. **This is the source's asymmetry, and it is the
one place where "never tried" and "tried and absent" still cannot be told
apart at decade granularity.** Listed as a follow-up in §6.

The prompt's "fifth door" — the silent GeoTIFF-url skip INVESTIGATION found —
is now `topo_no_geotiff_url` and no longer silent.

`search_usgs_topo_products` (`usgs_topo.py:92`) is new: it returns
`TopoSearchResult(items, truncated)` so the caller can see the cap, which the
log-only warning never let it. `search_usgs_topo` is kept as a thin wrapper
over it for existing callers.

### 4g. Census (`timeline.py:1035-1140`)

| situation | ledger source | outcome | reason |
|---|---|---|---|
| row upserted | `census_decennial` / `census_acs5` | `ok` | — (detail: the tract used) |
| API returned `{}` (the `if data:` skip) | as above | `absent` | `api_no_data` |
| `CensusApiError` caused by a timeout | as above | `failed` | `read_timeout` |
| `CensusApiError` caused by another transport error | as above | `failed` | `connect_error` |
| `CensusApiError` from a non-200 status | as above | `failed` | `other` (status in `detail`) |

`_census_failure_reason` (`timeline.py:165`) reads `exc.__cause__`, because
`CensusFetcher._request` flattens every `httpx.HTTPError` into one
`CensusApiError(f"HTTP error: {exc}")` and the `raise … from exc` is the only
place the transport type survives.

**`failed_requests` is unchanged.** The `{}` skip still increments nothing and
the all-failed check at `timeline.py:1154` still cannot see it — the ledger is
the record, and task status semantics are out of scope for this pass, as
specified.

### 4h. Task status

Unchanged everywhere. A task with failed years still ends `complete`. No
`_set_task_status` call was added, removed, or reordered.

### 4i. The redelivery reset

`create_request_tasks` (`imagery.py:288`) calls
`clear_task_year_outcomes(db, request_id, source)` before each source's
`INSERT … ON CONFLICT`, in the same transaction. Scoped by source rather than
by request, so a reset of one source leaves another's rows alone —
`tests/test_year_ledger.py::test_redelivered_request_reset_clears_prior_year_rows`
asserts both halves.

---

## 5. Every `indeterminate` site — the follow-up list

Four sites can emit it. Each is a place the code admits it cannot decide.

1. **`timeline.py:494` — an absent year under a saturated pool.** NAIP sends
   no `sortby`, so which items survive the 50-item cap is unspecified and a
   year missing from a capped response may have been truncated away. *Fix
   shape:* pagination, or a `sortby`. Both are T4/G8 work, deliberately not
   built.
2. **`timeline.py:771` — a topo decade under a capped 100-row TNM response.**
   Same shape, same fix shape (counties item 13, the L6 accept).
3. **`_classify_empty_chunk:232` — the cloud probe itself failing.** The one
   site this batch created. A failed probe leaves the year unclassified rather
   than guessing. *Fix shape:* retry the probe, or accept it — the year is
   already recorded as needing attention.
4. **`timeline.py:691` — an attempted group reaching the end of
   `_search_and_persist_source` with no verdict.** The residual pass, and the
   only one expected to be **zero**. If it ever fires, some path between
   search and persist is dropping groups in a way this batch did not find.
   That is a new defect, and this row is how it becomes visible.

Two further places where the ledger is *silent* rather than indeterminate,
because there is no key to hang a row on:

- **Topo decades the TNM response never mentioned** (§4f). No attempted set
  exists.
- **The `property` source.** No period key at all (INVESTIGATION §3h); it
  writes no ledger rows, by design.

---

## 6. Tests

`backend/tests/test_year_ledger.py`, 34 tests. Full suite: **522 passed, 0
failed** (`.venv/bin/python -m pytest tests/ -q`), up from 488 at `fa3ea89`.

**The two known environmental failures did not occur.** `HEAL-SCORECARD-2.md`
§3 and `LOGGING-FIX.md` §3 record `test_health::test_health_survives_missing_build_identity`
and `test_workflow_pins::test_every_action_is_pinned_to_a_commit_sha` failing
inside the dev container (`GIT_SHA=dev`, `.github/` not mounted). This run was
against the host venv, where both pass. **They are expected to fail again
under `make test`**, which runs in the container; that is environmental and
unchanged by this batch.

`ruff check` and `ruff format --check` over `app/` and `tests/` pass; `mypy
app/` reports no issues over 47 source files. `scripts/` is outside `make
lint`'s target; `ledger_gaps.py` passes ruff check and format anyway, and
`seed_featured.py`'s five pre-existing errors are unchanged.

### Delete-the-fix — 11 reversions, all verified

Each recorder call was deleted, the named test run, and the call restored.
Every one failed with the call removed.

| # | call site | test |
|---|---|---|
| 1 | `timeline.py:396` chunk failure | `test_landsat_chunk_403_is_recorded_and_costs_no_rows` |
| 2 | `timeline.py:415` empty-chunk probe | `test_sentinel_2015_with_only_cloudy_scenes_is_cloud_filtered` |
| 3 | `timeline.py:569` walk notes | `test_signing_429_exhausting_the_walk_records_sign_429` |
| 3b | `stac.py:1261` `GroupNote("failed", …)` | same |
| 3c | `stac.py:1249` `GroupNote("ok", …)` | `test_a_year_rescued_by_the_fallback_ends_ok_with_the_swap_in_detail` |
| 4 | `timeline.py:636` imagery `ok` | `test_a_served_year_writes_an_ok_row_with_its_snapshot` |
| 5 | `timeline.py:523` NAIP suppression | `test_naip_year_with_no_covering_tile_is_suppressed` |
| 6 | `timeline.py:875` topo `ok` | `test_topo_records_ok_per_decade` |
| 7 | `timeline.py:858` topo no-`sourceId` | `test_topo_product_with_no_source_id_is_suppressed` |
| 8 | `timeline.py:1071` census `absent` | `test_census_empty_response_is_absent_api_no_data` |
| 9 | `timeline.py:1133` census `failed` | `test_census_read_timeout_is_failed_read_timeout` |

Six loops were required; these are nine recorder sites plus the two
`GroupNote` fills that feed one of them.

### Acceptance cases from the record

| case | test |
|---|---|
| 2015 S2 search returning only ≥ 40 % scenes → `absent/all_cloud_filtered` | `test_sentinel_2015_with_only_cloudy_scenes_is_cloud_filtered` |
| Landsat chunk 403 → `failed/stac_403`, existing snapshot rows untouched | `test_landsat_chunk_403_is_recorded_and_costs_no_rows` |
| census `{}` → `absent/api_no_data`, `failed_requests` unchanged | `test_census_empty_response_is_absent_api_no_data` |
| census `ReadTimeout` → `failed/read_timeout` | `test_census_read_timeout_is_failed_read_timeout` |
| NAIP year with no covering tile → `suppressed` | `test_naip_year_with_no_covering_tile_is_suppressed` |
| Landsat signing 429 exhausting the walk → `failed/sign_429` | `test_signing_429_exhausting_the_walk_records_sign_429` |
| failed-then-ok fallback ends `ok` | `test_a_failed_then_ok_walk_ends_ok`, and end-to-end in `test_a_year_rescued_by_the_fallback_…` |
| a redelivered request's reset clears prior year rows | `test_redelivered_request_reset_clears_prior_year_rows` |
| `group_key` round-trip for every scope | `test_every_selection_scope_round_trips` |

The loop tests drive the real `_fetch_source` / `_fetch_usgs_topo` /
`_fetch_census` against the real SQLite test schema, through the real upserts,
via a new `committing_db` fixture (`conftest.py`). The existing `db` fixture
rolls its transaction back, which cannot test a ledger row and a snapshot
committing together.

### A live-network call found and closed

Three topo tests patched `topo_service.search_usgs_topo`. The topo path now
calls `search_usgs_topo_products`, so those patches stopped intercepting and
the tests began making **real requests to `tnmaccess.nationalmap.gov`** —
observed at DEBUG, HTTP 200, 152 KB, with the row-cap warning firing. They now
patch what the code calls. Worth recording as a class: a rename can turn a
mocked test into a live one silently, and the suite has no network guard.

---

## 7. Which heal scripts `ledger_gaps.py` subsumes

`scripts/ledger_gaps.py` is read-only: latest outcome per
`(parcel, source, group_key)` across runs, attempt counts and every reason
seen for the actionable ones, with `--source` / `--parcel` / `--outcome`
filters.

| script | subsumed? | why |
|---|---|---|
| `revalidate_landsat.py` | **yes** | Its selection is `SELECT parcel_id FROM imagery_snapshots WHERE source='landsat' GROUP BY parcel_id` — all 184 parcels, targeting nothing. Its real predicate is "parcels holding a Landsat group whose last outcome was a validation drop", which is `--source landsat --outcome failed`. |
| `heal_tract_vintage_gaps.py` | **yes** | Its "2021 or 2023 present" test is an explicit proxy for "this parcel was ever fetched" (its own comment says so). The ledger replaces that inference with `census_acs5` rows carrying `ok` or `absent`. |
| `requeue_empty_property.py` | **no** | Its subject is `property`, which has no period key. "Complete with zero events" is an aggregate over the whole source and stays expressible against the existing task columns. |
| `requeue_parcels.py` | **no** | It runs no selection query at all — ids come from `argv`, and its substance is the deployed-SHA gate. It is a delivery mechanism, and the natural consumer of whatever `ledger_gaps.py` selects. |

Two of four, and they are exactly the two whose subject has a period key —
which is what INVESTIGATION §5 predicted. Neither is deleted in this batch:
the ledger has no history, so until every parcel has been swept once, a
ledger-driven selection would miss every parcel that has not.

---

## 8. Deviations

1. **The empty-year cloud probe** (§4a). One extra STAC request per empty year
   on cloud-filtered sources. It changes fetch behaviour, not only recording.
   Rationale: without it `all_cloud_filtered` is unreachable, and that reason
   is the O6 distinction the prompt cites as the ledger's purpose.
2. **NAIP's attempted set comes from the query's date range** (§4b) rather
   than the whole-source fallback, contradicting INVESTIGATION UNVERIFIED item
   2's "not knowable from code at all".
3. **Topo uses a whole-source key** (§4f) instead of per-decade `absent` rows,
   because no attempted decade set exists to mark absent against.
4. **Four `suppressed` reasons added** beyond `naip_no_point_coverage` (§3),
   each naming a live or latent skip that had no vocabulary.
5. **A STAC 429 records as `other`** (§4a) rather than a new `stac_429`.
6. **`_validate_asset` changed shape** from `bool` to `str | None`, with
   `check_*_item` added and `validate_*_item` kept as the boolean face. Eight
   existing tests moved their patch target accordingly.
7. **`_validate_selection` takes an out-parameter** (`notes`) rather than
   returning a tuple, to keep both public wrappers' return types compatible
   with their ten existing callers and tests.
8. **`search_usgs_topo_products` added** alongside `search_usgs_topo`, so the
   caller can see the response cap.
9. **`get_task_id` is tolerant.** A `task_id` that will not parse as a UUID
   logs a warning and skips the ledger rather than raising. A fetch should not
   die over bookkeeping; the cost is that a broken task row makes the ledger
   silent rather than loud. Recorded as an accepted risk in STATUS.md.

---

## 9. UNVERIFIED register

1. **The migration has not run anywhere.** The DDL in §1 is `alembic upgrade
   --sql` output, not an observation. No PostgreSQL instance — local or
   production — has executed it.
2. **`gen_random_uuid()`** is assumed available, as every prior migration
   assumes (`0001` onward). Not re-checked against production's `pg_extension`.
3. **The M7 item 5 constraint-name drift** is still inferred from migration
   source, not from `pg_constraint`. This batch avoids it by issuing no
   `ALTER`, so the inference is not load-bearing here — but it remains
   unverified.
4. **Row-volume projections** in `PREDICTION.md` §2 assume every source
   attempts its full configured range on every parcel. A parcel whose
   `_fetch_source` raises before the chunk loop writes fewer.
5. **Topo decade counts.** The ledger counts decades in the TNM *response*;
   the 6.3/parcel figure is a historical `imagery_snapshots` average. They
   should agree; nothing measured says they must.
6. **The cloud probe's cost** is estimated from "fleet Landsat sits at 43 of
   43 years for most parcels". The number of empty parcel-years fleet-wide has
   not been counted, so the extra-request count is an inference.
7. **SQLite does not enforce the new FK's `ON DELETE CASCADE`.**
   `conftest.py` declares it, matching production, but never sets
   `PRAGMA foreign_keys=ON` — consistent with the rest of that file, and the
   reason M7 notes the existing `timeline_request_tasks` FK has no CASCADE at
   all there.
8. **Consumers outside this repository.** No API schema, endpoint, or frontend
   type exposes the ledger in this pass; a dashboard or notebook reading
   `timeline_request_tasks` directly would not see it either.
