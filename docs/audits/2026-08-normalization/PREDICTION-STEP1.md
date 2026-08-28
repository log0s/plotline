# Prediction — normalization step 1 backfill

Written **2026-08-28**, before `scripts/backfill_scenes.py --execute` has
been run against any database. Step 1 of
`docs/adr/0001-imagery-normalization.md`: create `scenes` and
`parcel_scenes` (migration `0015`, commit `822faca`) and backfill them from
`imagery_snapshots`.

Per the project's prediction rule, the Observed section below is appended
after the run and this half is never edited to match it.

---

## Local database

### State the prediction is made against

The local sweep (this batch's item 1) ran first, so local's duplicate state
matches production's. Post-sweep, `alembic_version = 0015`:

```sql
SELECT count(*) AS snapshot_rows,
       count(DISTINCT (stac_collection, stac_item_id)) AS distinct_items
FROM imagery_snapshots;
```

| snapshot_rows | distinct_items |
|---|---|
| 2945 | 1174 |

```sql
WITH e AS (SELECT DISTINCT unnest(additional_cog_urls) u FROM imagery_snapshots
           WHERE additional_cog_urls IS NOT NULL AND array_length(additional_cog_urls,1) > 0)
SELECT count(*) AS distinct_mosaic_urls,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)) AS matched,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)) AS unmatched,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM imagery_snapshots s WHERE s.cog_url = e.u)
                          AND u NOT LIKE 'https://naipeuwest.blob.core.windows.net/naip/v002/%') AS unmatched_non_naip
FROM e;
```

| distinct_mosaic_urls | matched | unmatched | unmatched_non_naip |
|---|---|---|---|
| 115 | 27 | 88 | 0 |

```sql
WITH g AS (
  SELECT parcel_id, source,
    CASE WHEN source = 'usgs_topo'
         THEN ((EXTRACT(YEAR FROM capture_date)::int / 10) * 10)::text || 's'
         ELSE EXTRACT(YEAR FROM capture_date)::int::text END AS group_key
  FROM imagery_snapshots)
SELECT count(*) FROM (
  SELECT count(*) FROM g GROUP BY parcel_id, source, group_key HAVING count(*) > 1) d;
```

→ **0** duplicate groups (269 before the sweep).

### Predicted

| Quantity | Predicted | Derivation |
|---|---|---|
| `scenes` rows | **1262** | 1174 distinct `(stac_collection, stac_item_id)` + 88 distinct unmatched mosaic URLs |
| — of which `provenance = 'snapshot'` | **1174** | one per distinct catalogued item |
| — of which `provenance = 'mosaic_url'` | **88** | one per distinct unmatched mosaic URL |
| `parcel_scenes` rows | **2945** | one per `imagery_snapshots` row |
| duplicate groups encountered | **0** | the sweep cleared all 269; a nonzero count aborts the run before any write |
| `scenes` with `footprint IS NOT NULL` | **0** | `imagery_snapshots` holds no item geometry, Phase A or B |
| `parcel_scenes` with `selected_by IS NOT NULL` | **0** | history never recorded the selecting SHA |
| mosaic URLs that fail to parse | **0** | all 88 unmatched are `naip/v002` tile URLs with a date-suffixed filename |

**Two ways `scenes` could come out below 1262, both of which the script
reports rather than swallows.** A synthesized `(collection, item_id)` could
collide with a Phase A key — the URL matched no row's `cog_url` but derives
to an item some row already carries — or two distinct unmatched URLs could
derive to the same candidate id. Either would make the total smaller by the
number of collisions and would appear in the run's anomalies list. Neither
is predicted to occur.

**Nothing is predicted to change in `imagery_snapshots`.** The script only
reads it; the row count after the run must still be 2945.

**Disclosure about how these numbers were reached.** The script was run in
its dry-run mode before this file was written, and its planner reported the
same 1262 / 88 / 2945. The table above is nevertheless derived from the SQL
shown, independently of the script, precisely so the prediction is not
merely a restatement of the code under test. A disagreement between the two
would itself have been the finding.

---

## Production

Not run this session — production is untouched, and the inputs below were
derived read-only on 2026-08-28 and given to this session rather than
measured by it.

| Input | Value |
|---|---|
| distinct `(stac_collection, stac_item_id)` | 6,156 |
| `imagery_snapshots` rows | 12,884 |
| duplicate `(parcel_id, source, group_key)` groups | 0 |
| `additional_cog_urls` entries | 613 total, 73 matched, 540 unmatched |

Predicted, when the production backfill runs:

* `scenes` = **6,156 + D**, where D is the count of *distinct* unmatched
  mosaic URLs. D ≤ 540, since 540 counts entries and not distinct URLs — the
  local ratio was 88 distinct out of 112 entries, so D well under 540 is the
  expectation, but the exact value is derived at run time and is not
  predicted here.
* `parcel_scenes` = **12,884**.
* duplicate groups encountered = **0**.

**The `parcel_scenes` figure assumes no intervening writes, and that
assumption is not safe.** Production keeps taking traffic: every timeline
request that fetches imagery inserts and reconciles `imagery_snapshots`
rows, so 12,884 is a 2026-08-28 reading, not a constant. The production
prediction to score is therefore "`parcel_scenes` equals the
`imagery_snapshots` row count read in the same transaction as the backfill",
and the run must record that count rather than compare against 12,884. A
difference from 12,884 alone is drift, not a deviation.

The ADR's context section says 14,534 rows / 184 parcels from a 2026-08-24
snapshot. Prod is now 12,884; the delta is consistent with the G8 completion
sweep's Sentinel-2 quarter-deduplication deletions. The original figure is
left in place and the update is recorded in the ADR's dated amendment, per
the frozen-record rule.

---

## Observed

*Appended after the local run; see the same-batch entry below.*
