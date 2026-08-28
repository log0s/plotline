# Normalization step 1 — build and local run

Step 1 of `docs/adr/0001-imagery-normalization.md`: create `scenes` and
`parcel_scenes`, backfill them from `imagery_snapshots`, score a written
prediction. Steps 2 (dual-write), 3 (read cutover) and 4 (retirement) were
not in scope and were not started.

**Production was not touched.** No `fly ssh`, no prod credentials, no query
against Neon. The production figures quoted here were derived read-only on
2026-08-28 and given to this session; the production backfill has not run.

Built on `6d8a6b9`; this batch's commits:

| Commit | Unit |
|---|---|
| `822faca` | migration `0015_scenes_and_parcel_scenes.py` |
| `0fc0f64` | `Scene` / `ParcelScene` ORM models + `tests/conftest.py` DDL |
| `b3f8e94` | `scripts/backfill_scenes.py` |
| `ea98325` | `PREDICTION-STEP1.md`, before the run |
| `d13026e` | the same file's Observed half, after it |
| `382329e` | `backend/tests/test_backfill_scenes.py` |

---

## 1. What was built

### Migration 0015 (`822faca`)

Head at the start of the batch was `0014` (`SELECT version_num FROM
alembic_version` → `0014`), so `0015` is the right number. Pure DDL: two
`CREATE TABLE`s and three indexes, no data movement, nothing touching
`imagery_snapshots`. Verified by `alembic upgrade head`, `alembic downgrade
-1`, `alembic upgrade head` again, all clean, and by `\d scenes` / `\d
parcel_scenes` against the local database:

```
Indexes:
    "idx_scenes_footprint" gist (footprint)
    "idx_scenes_source_capture" btree (source, capture_date)
    "uq_scenes_collection_item" UNIQUE CONSTRAINT, btree (collection, item_id)
Check constraints:
    "ck_scenes_provenance" CHECK (provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text]))
    "ck_scenes_source" CHECK (source = ANY (ARRAY['naip'::text, 'landsat'::text, 'sentinel2'::text, 'usgs_topo'::text]))
```

```
Indexes:
    "idx_parcel_scenes_scene" btree (scene_id)
    "uq_parcel_scenes_parcel_source_group" UNIQUE CONSTRAINT, btree (parcel_id, source, group_key)
Check constraints:
    "ck_parcel_scenes_group_key" CHECK (group_key ~ '^[0-9]{4}(Q[1-4]|s)?$'::text)
    "ck_parcel_scenes_source" CHECK (source = ANY (ARRAY['naip'::text, 'landsat'::text, 'sentinel2'::text, 'usgs_topo'::text]))
Foreign-key constraints:
    "fk_parcel_scenes_parcel_id" FOREIGN KEY (parcel_id) REFERENCES parcels(id) ON DELETE CASCADE
    "fk_parcel_scenes_scene_id" FOREIGN KEY (scene_id) REFERENCES scenes(id)
```

`group_key`'s CHECK matches the three shapes `encode_group_key`
(`backend/app/services/imagery.py:1023-1032`) emits and nothing else.
`footprint` is nullable. `mosaic_scene_ids` is `uuid[]` as the ADR specifies.

### ORM models and test DDL (`0fc0f64`)

`Scene` and `ParcelScene` in `backend/app/models/parcels.py`, constraint names
repeating 0015's exactly so neither table starts with the ORM/database name
drift M7 records. The hand-written SQLite block in
`backend/tests/conftest.py` mirrors both, including the group_key CHECK — the
POSIX regex has no SQLite operator, so it is expressed as three `GLOB`
alternatives that admit exactly the same strings. `mosaic_scene_ids` uses the
`ARRAY(...).with_variant(JSON, "sqlite")` pattern `TimelineRequest.sources`
already uses (`parcels.py:143-144`).

### Backfill script (`b3f8e94`)

`scripts/backfill_scenes.py`, three phases, dry run by default. Idempotent by
construction: it reads the existing keys of both tables and inserts only what
is missing, never updating. A `parcel_scenes` row that disagrees with what the
snapshots now imply is reported as drift and left alone — reconciling it is a
dual-write question, which is step 2's.

Three refusals, all evaluated before any write: a duplicate `(parcel_id,
source, group_key)` group, a mosaic URL that is not a parseable NAIP tile URL,
and a snapshot row whose source has no configured selection scope. The scope
map is read from `app/tasks/timeline.py`'s `_SOURCES` rather than restated, so
a grouping change there cannot leave the script bucketing by the old rule;
`usgs_topo`'s `"decade"` is added the same way it is passed at
`app/tasks/timeline.py:961`.

### Tests (`382329e`)

Ten tests in `backend/tests/test_backfill_scenes.py`. Full suite after the
batch: **677 passed, 7 skipped**. `ruff check app/ tests/`, `ruff format
--check app/ tests/` and `mypy app/` all clean (`Success: no issues found in
48 source files`).

**Delete-the-fix, verified by running it.** Each of eight mutations was
applied, the covering test run, and the mutation reverted:

| Removed | Test | Result |
|---|---|---|
| `uq_parcel_scenes_parcel_source_group` | `test_second_row_for_one_period_is_rejected` | FAILS |
| `ck_parcel_scenes_group_key` | `test_group_key_must_be_one_of_the_three_encodings` | FAILS |
| the `if url in url_to_key` branch | `test_matched_mosaic_url_resolves_to_the_existing_scene` | FAILS |
| the synthesis branch | `test_unmatched_naip_url_synthesizes_a_scene` | FAILS |
| `parse_naip_tile_url`'s refusal | `test_unparseable_mosaic_url_refuses_the_run` | FAILS |
| the duplicate-group guard | `test_duplicate_group_refuses_the_run` | FAILS |
| the scene-exists skip | `test_second_run_writes_nothing` | FAILS |

**One test did not meet the standard on the first draft and was rewritten.**
`test_matched_mosaic_url_resolves_to_the_existing_scene` originally gave the
neighbouring tile a URL whose filename equalled its item id. With that
fixture, matching the URL and parsing the URL produce the same scene, so
deleting the matching branch changed nothing and the test passed against the
mutation. The fixture now uses the realistic shape — a filename that omits the
publication date its item id carries — where the two paths diverge, and the
mutation fails as it should. Recorded because the first version would have
shipped as coverage that covered nothing.

---

## 2. Local sweep

The local database had never been swept under the year-grouping code
production got on 2026-08-25 (G8), so its duplicate state did not match
production's. It does now.

### Before

```sql
WITH g AS (
  SELECT parcel_id, source,
    CASE WHEN source = 'usgs_topo'
         THEN ((EXTRACT(YEAR FROM capture_date)::int / 10) * 10)::text || 's'
         ELSE EXTRACT(YEAR FROM capture_date)::int::text END AS group_key
  FROM imagery_snapshots)
SELECT count(*) AS dup_groups, sum(n) AS rows_in_dup_groups FROM (
  SELECT count(*) n FROM g GROUP BY parcel_id, source, group_key HAVING count(*) > 1) d;
```

| dup_groups | rows_in_dup_groups |
|---|---|
| 269 | 618 |

266 `sentinel2`, 3 `naip`, 0 `landsat`, 0 `usgs_topo` — matching
VERIFICATION item 6b exactly. `imagery_snapshots` held 3,295 rows across 43
parcels.

### The sweep

```
docker compose exec api python scripts/requeue_parcels.py \
    --skip-deploy-check --sources naip,landsat,sentinel2,usgs_topo <43 parcel ids>
→ Done — queued 43 timeline request(s), skipped 0.
```

`--skip-deploy-check` because a local image reports `GIT_SHA=dev`, so
`--require-sha` cannot be satisfied; the script requires exactly one of the
two. The worker was started for this (`docker compose up -d worker`); it is
not part of the default local stack.

### After the first pass — 4 survivors, and why

| dup_groups |
|---|
| 4 |

All four `sentinel2`, all carrying `created_at` from May/August 2026 — rows
the sweep never rewrote:

| address | group_key | rows |
|---|---|---|
| 11775 Wadsworth Blvd, Broomfield, CO 80020 | 2015 | 2 |
| 225 Shearwater Parkway, Redwood City, California 94065 | 2026 | 3 |
| 24241 Atlantic Dr, Rodanthe, NC 27968 | 2018 | 3 |
| 4800 Telluride St, Denver, CO 80249 | 2021 | 2 |

Joining each to the M4 ledger rows the sweep itself wrote gives the cause in
one query — every one of the four is a `failed` / `stac_403` for that exact
`(parcel, sentinel2, year)`:

```
 address                                                | group_key | outcome | reason
 11775 Wadsworth Blvd, Broomfield, CO 80020             | 2015      | failed  | stac_403
 225 Shearwater Parkway, Redwood City, California 94065 | 2026      | failed  | stac_403
 24241 Atlantic Dr, Rodanthe, NC 27968                  | 2018      | failed  | stac_403
 4800 Telluride St, Denver, CO 80249                    | 2021      | failed  | stac_403
```

Planetary Computer rate-limited those year-chunk searches, so the run selected
nothing for those periods, and `reconcile_source_snapshots` — which
deliberately never deletes an *absent* group, because absence usually means a
failed search rather than a retired scene — had nothing to collapse against.
**This is not silent reconciliation failure**, which is what the ADR's change
condition is about: the ledger named all four, by parcel, source, group and
reason, without being asked. Fleet-wide the sweep produced 20 `stac_403` rows
(11 landsat, 9 sentinel2) against 2,925 `ok`.

### After the retry — 0

```
docker compose exec api python scripts/requeue_parcels.py \
    --from-ledger --skip-deploy-check --sources landsat,sentinel2
→ Done — queued 6 timeline request(s), skipped 0.
```

Ledger selection, not a hand-written list: `failed` is retryable, so the same
query `ledger_gaps.py` reports on picked the six affected parcels.

| dup_groups |
|---|
| **0** |

A follow-up `--from-ledger --dry-run` across all four imagery sources selects
**3** remaining groups, all `usgs_topo` `indeterminate` (TNM response hit its
row cap). Those are a whole-source key (`*`), carry no duplicate groups, and
have no bearing on the backfill.

Final state: **2,945 rows**, 1,174 distinct `(stac_collection,
stac_item_id)`, 0 duplicate groups.

---

## 3. Backfill run

`docker compose exec api python scripts/backfill_scenes.py --execute`, against
the post-sweep database at `alembic_version = 0015`:

```
imagery_snapshots rows: 2945
duplicate (parcel_id, source, group_key) groups: 0

planned scenes: 1262 (88 synthesized from mosaic URLs)
planned parcel_scenes: 2945

scenes already present: 0

Written:
  scenes inserted:        1262 (of which synthesized: 88)
  scenes already present: 0
  parcel_scenes inserted: 2945
  parcel_scenes present:  0
```

No anomalies reported: no set of snapshot rows disagreed about an item's
attributes, and no mosaic URL derived to an item the table already held.

Immediate re-run, unchanged:

```
  scenes inserted:        0 (of which synthesized: 0)
  scenes already present: 1262
  parcel_scenes inserted: 0
  parcel_scenes present:  2945
```

Row counts after: `1262|2945`. Idempotency observed, not asserted.

### Post-write checks

| Query | Result |
|---|---|
| `scenes` with `footprint IS NOT NULL` | 0 |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 |
| mosaic references not resolving to a `scenes` row | 0 |
| `parcel_scenes` rows with no corresponding snapshot row | 0 |
| `imagery_snapshots` rows after the run | 2,945 — unchanged |

| source | provenance | scenes | with platform | with bbox |
|---|---|---|---|---|
| landsat | snapshot | 618 | 618 | 618 |
| naip | mosaic_url | 88 | 0 | 0 |
| naip | snapshot | 200 | 0 | 200 |
| sentinel2 | snapshot | 213 | 213 | 213 |
| usgs_topo | snapshot | 143 | 0 | 143 |

141 `parcel_scenes` rows carry a mosaic, 162 references in total — exactly the
141 snapshot rows and 162 `additional_cog_urls` entries the source table holds,
so ADR rule 5 holds with nothing dropped.

---

## 4. Prediction scorecard

Full detail in `PREDICTION-STEP1.md`; the prediction half was committed
(`ea98325`) before the backfill ran and has not been edited.

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| `scenes` rows | 1262 | 1262 | confirmed |
| — `provenance = 'snapshot'` | 1174 | 1174 | confirmed |
| — `provenance = 'mosaic_url'` | 88 | 88 | confirmed |
| `parcel_scenes` rows | 2945 | 2945 | confirmed |
| duplicate groups encountered | 0 | 0 | confirmed |
| `scenes` with `footprint IS NOT NULL` | 0 | 0 | confirmed |
| `parcel_scenes` with `selected_by IS NOT NULL` | 0 | 0 | confirmed |
| mosaic URLs that failed to parse | 0 | 0 | confirmed |
| `imagery_snapshots` rows after the run | 2945 | 2945 | confirmed |

**Every line confirmed, no deviations.** The prediction file discloses that
the script's dry run had already reported 1262/88/2945 before the file was
written, and that the table was nevertheless derived independently in SQL so
the prediction is not a restatement of the code under test.

---

## 5. Findings

### F1 — A NAIP tile URL does not reliably yield its STAC item id

**Open. Mitigated by a schema column, not fixed.** The prompt and the ADR both
assume "NAIP filenames are the STAC item ids". Measured across the 312 NAIP
rows in the local table on 2026-08-28:

```sql
WITH n AS (SELECT stac_item_id, split_part(cog_url,'/',6) AS state,
                  regexp_replace(cog_url,'^.*/','') AS fname
           FROM imagery_snapshots WHERE source='naip')
SELECT count(*) AS naip_rows,
       count(*) FILTER (WHERE state||'_'||replace(fname,'.tif','') = stac_item_id) AS stem_equals_id,
       count(*) FILTER (WHERE stac_item_id LIKE state||'_'||replace(fname,'.tif','')||'%') AS stem_prefix_of_id
FROM n;
```

| naip_rows | stem_equals_id | stem_prefix_of_id |
|---|---|---|
| 312 | **99** | 303 |

So the derivation is exact for 99 rows, a proper prefix for 204 more (the id
carries a trailing publication date the filename omits), and wrong for the
remaining 8, where the two spell the resolution differently:

| stac_item_id | filename |
|---|---|
| `ca_m_3712240_sw_10_.6_20160529_20161004` | `m_3712240_sw_10_h_20160529.tif` |
| `ny_m_4207321_ne_18_.5_20150507_20151109` | `m_4207321_ne_18_h_20150507.tif` |
| `id_m_4311631_nw_11_.5_20130830_20131114` | `m_4311631_nw_11_h_20130830.tif` |

(five more of the same shape)

The capture date is unaffected — it is the first date field under either
naming, so `parse_naip_tile_url` reads it correctly in all cases.

**What was done about it.** Synthesized rows are marked
`provenance = 'mosaic_url'` on a `scenes` column the ADR's schema block does
not list, and `WHERE provenance = 'mosaic_url'` is the work queue for a later
pass that fetches the real items and fills `footprint`. Nothing may treat such
a row's `item_id` as a catalogued identifier until then.

**Why not `footprint IS NULL`, as the prompt proposed.** Nothing in
`imagery_snapshots` holds item geometry, so *every* row step 1 writes — Phase
A and Phase B alike — has a NULL footprint. Confirmed: 0 of 1,262 rows have
one. `footprint IS NULL` selects the whole table. A "does any snapshot row
carry this item id" query would work today and break at step 4, when
`imagery_snapshots` is retired.

**Why the run was not stopped.** The prompt's stop condition is "a URL fails to
parse or is not a NAIP URL". Neither occurred: all 88 local unmatched URLs are
`naip/v002` tile URLs, all parse, and all yield a capture date. What is
unreliable is the *item id*, which is a different claim, and one that a
refusal could not have improved — the whole population has this property, so
stopping would have blocked step 1 permanently on a fact that no amount of
re-running changes. A column that tells the truth about which ids are guesses
is the smaller, more durable answer. Recorded as STATUS.md NORM-4.

Also relevant to `scripts/remove_uncovered_snapshots.py:178-183`, which derives
an item id from a URL and refuses when it disagrees with the row's own
`stac_item_id`. Against these 213 rows that check would refuse. It is a
refusal, not a wrong deletion, so it is safe — but it means that tool cannot
currently verify a multi-tile mosaic on most NAIP rows. Not changed here;
outside this batch's scope.

### F2 — Duplicate-group counts are only as complete as the sweep behind them

**Resolved by procedure.** See §2: the 4 groups surviving the first sweep were
each an upstream 403 during that same sweep, visible in the M4 ledger. Any
future measurement of duplicate groups after a sweep — including the one the
production step-1 backfill will make — has to be read alongside that sweep's
ledger outcomes, or a transient upstream failure reads as a persistent data
defect. Recorded as STATUS.md NORM-3.

### F3 — Nothing stopped in Phase B

For the record, since the prompt asked specifically: **no mosaic URL failed to
parse and none was non-NAIP.**

```sql
WITH e AS (SELECT DISTINCT unnest(additional_cog_urls) u FROM imagery_snapshots
           WHERE additional_cog_urls IS NOT NULL AND array_length(additional_cog_urls,1) > 0)
SELECT count(*) AS distinct_urls,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)) AS unmatched,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)
                          AND u NOT LIKE 'https://naipeuwest.blob.core.windows.net/naip/v002/%') AS unmatched_non_naip
FROM e;
```

| distinct_urls | unmatched | unmatched_non_naip |
|---|---|---|
| 115 | 88 | **0** |

VERIFICATION item 6c sampled 5 of the then-112 unmatched URLs; the whole
population has now been checked, and by the script itself, which would have
refused on the first exception.

### F4 — Parcel duplication is carried forward unchanged

Pre-existing, restated. VERIFICATION §6b flagged four local parcels that look
like two real-world locations geocoded twice ("11775 Wadsworth Blvd" /
"…Boulevard"; "4800 Telluride St" / "…Street"). `parcel_scenes` keys off
`parcel_id`, so the split propagates. Normalization neither causes nor fixes
it. STATUS.md NORM-6.

---

## 6. Deviations from the prompt or the ADR

Each with its reasoning, per the prompt's invitation.

1. **`scenes.provenance` added.** Not in the ADR's schema block. F1 above is
   the reasoning: without it a URL-derived `item_id` is indistinguishable from
   a catalogued one, and the enumeration mechanism the prompt named
   (`footprint IS NULL`) does not distinguish them either.

2. **Two indexes added to `scenes`** — `idx_scenes_footprint` (GiST) and
   `idx_scenes_source_capture`. The ADR lists only `UNIQUE (collection,
   item_id)`. The GiST index is the one rule 4 promises ("the next geometry
   audit is a query over `scenes`, not a refetch"), and is empty until the
   enrichment pass fills footprints. Both are cheap and neither changes
   semantics.

3. **`platform` recognises `LT04` and `S2C`** beyond the prompt's
   LT05/LE07/LC08/LC09, S2A/S2B. Both appear in real local item ids
   (`SELECT DISTINCT substring(stac_item_id from 1 for 4) …` returns `LT04`,
   `LT05`, `LE07`, `LC08`, `LC09` and `S2A`, `S2B`, `S2C`) and both name a
   satellite as unambiguously as the listed prefixes; the ADR's list predates
   Sentinel-2C's launch. Anything outside the two sets is NULL.

4. **The local sweep covered the four imagery sources, not `census` and
   `property`.** Those write to `census_snapshots` and `property_events` and
   cannot affect an `imagery_snapshots` duplicate group, so including them
   would have spent external API quota to change nothing measured here.

5. **The sweep took two passes.** The prompt's item 1 describes one. §2
   explains why: the first pass left 4 groups behind transient PC 403s, and
   the ledger-selected retry is the sanctioned way to clear a `failed` group.
   The alternative — reporting 4 survivors and stopping — would have stopped
   on an upstream rate limit rather than on a finding.

6. **Phase A needed a tie-break rule the prompt did not specify.** Where
   several snapshot rows carry one item and disagree about a copied attribute,
   the newest `created_at` wins and the disagreement is reported as an
   anomaly. None occurred locally, but production has 12,884 rows over 6,156
   items and is where the ADR's "item facts can disagree" cost actually bites.

7. **`fetched_at` is the earliest `created_at` among the rows contributing to
   a scene** — when the item first entered the database, not when the backfill
   read it. The ADR does not say. The alternative (`now()`) would record the
   backfill's own clock as the item's age.

8. **Synthesized rows leave `resolution_m` NULL.** The prompt names
   `footprint` / `thumbnail_url` / `cloud_cover_pct`. The URL's directory
   segment does encode a resolution (`nj_030cm_2023`), but deriving it is a
   second guess layered on the first, and the enrichment pass that fixes
   `item_id` will have the real value.

9. **Dry run is the script's default**, `--execute` writes. Matching
   `scripts/remove_uncovered_snapshots.py`. The prompt did not specify.

---

## 7. Carried forward for step 3 — the read-site inventory

Reproduced **verbatim** from `docs/audits/2026-08-normalization-pre/VERIFICATION.md`
item 3 so step 3's session does not re-derive it a third time. It was derived
fresh at `c808d5d`; `INVESTIGATION.md §8` is *not* this list (it is "Consumers
of task status"), which is why VERIFICATION had to build it and why the ADR's
Costs section citing §8 is corrected in the amendment rather than in place.

> `grep -rn "imagery_snapshots\|ImagerySnapshot" backend --include="*.py"`,
> excluding the ORM class body and Alembic column-add/constraint boilerplate
> that doesn't read the table.
>
> | file:line | What it reads | In INVESTIGATION §4/§5? |
> |---|---|---|
> | `app/models/parcels.py:358` | ORM table definition (`class ImagerySnapshot`) | Implicit (§1.3), not a read site |
> | `app/services/imagery.py:908-920` (`count_imagery_snapshots`) | `SELECT COUNT(*) ... WHERE parcel_id, source` | No — mentioned only as a *consumer* in §8, not listed as a read site itself |
> | `app/services/imagery.py:1153-1157` | `SELECT id, stac_item_id, capture_date ... WHERE parcel_id, source` (reconciliation's existing-rows pull) | No |
> | `app/services/imagery.py:1188` | `DELETE FROM imagery_snapshots WHERE id = :id` (a write, listed for completeness) | No |
> | `app/services/imagery.py:1237,1268` | `INSERT INTO imagery_snapshots ...` (writes) | No |
> | `app/services/imagery.py:1330-1355` (`get_snapshot_by_id`) | Full-row `SELECT ... WHERE id = :id` | No |
> | `app/services/imagery.py:1357-1400` (`get_imagery_snapshots`) | Full-row `SELECT` filtered by parcel/source/date range, raw SQL to dodge GeoAlchemy2's `AsEWKB` on `bbox` | No |
> | `app/api/v1/imagery.py:199` | Calls `get_imagery_snapshots` for the timeline response | No |
> | `app/services/preview_renderer.py:70` | Calls `get_imagery_snapshots` to pick a preview scene | No |
> | `app/api/v1/featured.py:30-43` | Raw `SELECT parcel_id, id, capture_date FROM imagery_snapshots WHERE parcel_id IN (...)` for the featured-parcels thumbnail picker | No |
> | `app/services/imagery.py:1145,1167` (`encode_group_key` call sites inside reconciliation) | Not a table read, but consumes rows already selected above | N/A |
> | `scripts/revalidate_landsat.py:41-49` | `SELECT parcel_id FROM imagery_snapshots WHERE source = 'landsat' GROUP BY parcel_id` | **Yes — §5** |
> | `tests/conftest.py:164,266` | Test-DB `CREATE TABLE` / fixture cleanup list | No (test infra) |
> | `tests/test_featured.py:78` | Test fixture `INSERT` | No |
> | `tests/test_remove_uncovered_snapshots.py:103,181` | Test fixture `INSERT` / `SELECT id FROM imagery_snapshots` | No |
> | `tests/test_year_ledger.py:328,352,380` | Test fixture `SELECT COUNT`, `INSERT`, `SELECT stac_item_id ... WHERE capture_date` | No |
> | `tests/test_imagery.py:194-274,517,808-838` | Exercises `get_imagery_snapshots`/`upsert_imagery_snapshot` and one raw `SELECT stac_item_id ... WHERE parcel_id, source` | No |
> | `tests/test_timeline.py:366` | Patches `count_imagery_snapshots`, doesn't read the table directly | No |
> | `alembic/versions/0002_imagery_timeline.py`, `0007_imagery_additional_cog_urls.py`, `0008_usgs_topo.py` | Schema DDL only (create/alter/drop table, columns, constraints) | No |
>
> **No orphan sites in either direction that matter for the migration:** every
> production-code (non-test, non-migration) read site is one of `count_imagery_snapshots`,
> the reconciliation existing-rows pull, `get_snapshot_by_id`, `get_imagery_snapshots`,
> the featured-parcels raw query, and `revalidate_landsat.py`'s selection query.

**Two caveats on reusing it.** The line numbers are `c808d5d`'s; this batch
added `Scene` and `ParcelScene` to `app/models/parcels.py` and two blocks to
`tests/conftest.py`, so every citation in those two files has shifted. The
call sites themselves are unchanged — this batch modified no read path, and
the full suite passes with zero changes to any of them, which is the
constraint step 3 inherits and step 3 is the step that breaks.

---

## 8. State of the record

* ADR `0001` is **Accepted**, dated 2026-08-28, with an amendment section
  covering the synthesized-scenes mechanism, the
  `mosaic_scene_ids`-includes-synthesized rule, the 12,884 context update, the
  already-shipped rule 2, and step 1's prediction as it actually ran. Nothing
  above the amendment line was edited.
* STATUS.md carries a new **Imagery normalization — step 1** section with
  NORM-1 through NORM-6, a fix-commits row, and an updated Scheduled item 1
  saying step 1 is built and local-only.
* **Deploy state, stated plainly:** migration 0015 is committed and has run
  against the *local* database only. It has not been deployed, and
  `scripts/backfill_scenes.py` has never been run against production. Nothing
  in production has changed. A mitigation that isn't running isn't mitigating,
  and none of this is running.

**Later — 2026-08-28, same day:** the paragraph above is superseded and left
unedited. Migration 0015 was deployed (both apps on
`GH_SHA=4de57282c8692b9787564b62b0019fda149c2ba4`, alembic head `0015`) and
`scripts/backfill_scenes.py --execute` ran **once** against production,
writing 6,661 `scenes` and 12,884 `parcel_scenes`. Every predicted quantity
confirmed, idempotence observed. Production has changed, and this is running.
See `STEP1-PROD-REPORT.md`, the "Observed — production" section of
`PREDICTION-STEP1.md`, and STATUS.md NORM-1 / NORM-7 / NORM-8. Two figures in
this report are entries-level where the production run needed distinct URLs:
F1's and F3's "540 production" unmatched is **505 distinct of 578**, which is
the number of synthesized rows production actually holds.
