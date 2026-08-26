# M4 ledger — prediction for the first full sweep after deploy

**Written:** 2026-08-25, before deploy. Nothing here is revised after the run.
**Commits under prediction:** `0814d7e` (schema), `ef2d0a2` (recorder + loops).
**HEAD when written:** `ef2d0a2`. **Deploy state: not yet deployed.**

The observed result goes in a scorecard beside this file, with a verdict per
item (confirmed / deviation / falsified). This file is not edited to match it.

Every number below is computed from the source configuration and the fleet
snapshot in `../2026-08-m4-design/INVESTIGATION.md` §7 (184 parcels, read
2026-08-24). Anything not traceable to code or to that snapshot is tagged
UNVERIFIED.

---

## 0. The ledger starts empty

`timeline_task_years` carries no history. It has no backfill and cannot have
one: the outcomes it records were never written down anywhere, which is the
finding. A parcel last fetched before deploy has **zero rows**, and its
absence from `scripts/ledger_gaps.py` output means "not yet swept", not
"healthy". Every count below is therefore a count for parcels the sweep
actually reaches, not for the fleet as it stands today.

---

## 1. Rows per parcel, per full run

From the source configs (`backend/app/tasks/timeline.py` `_SOURCES`,
`backend/app/services/census.py:74-75`) with `date.today().year == 2026`:

| ledger `source` | key | groups per run | basis |
|---|---|---|---|
| `landsat` | year | **43** | 1984–2026, `start_year: 1984`, `chunk_by_year` |
| `sentinel2` | year | **12** | 2015–2026, `start_year: 2015`, `chunk_by_year` |
| `naip` | year | **17** | 2010–2026, from the query's own `datetime_range` |
| `usgs_topo` | decade | **variable** | one per decade present in the TNM response |
| `census_decennial` | year | **4** | `DECENNIAL_YEARS = [1990, 2000, 2010, 2020]` |
| `census_acs5` | year | **6** | `ACS5_YEARS = [2009, 2012, 2015, 2018, 2021, 2023]` |
| `property` | — | **0** | no period key (INVESTIGATION §3h) |

**Fixed part: 82 rows per parcel per run** (43 + 12 + 17 + 4 + 6).

`usgs_topo` is the one source whose attempted set is not enumerable — one
untimed TNM query returns whatever exists, so the ledger records the decades
the response held, plus a `*` whole-source row when the search failed, came
back empty, or hit its 100-row cap. Historically topo landed 982 rows over
157 parcels (6.3/parcel); 27 parcels hold none.

**P1. Rows per parcel: exactly 82 plus that parcel's topo decade count.**
A parcel at 82 + 0 with no `usgs_topo` `*` row is a defect in the topo wiring,
not a parcel without topo.

## 2. Fleet total

**P2. A full 184-parcel sweep writes 16,100 ± 300 ledger rows.**

  184 × 82                       = 15,088
  topo decades, 157 × 6.3        ≈    989
  topo `*` rows, 27 parcels      =     27
                                  ────────
                                   ≈ 16,104

A second sweep adds the same again — rows are per (task, group), and each run
is a new request with new task rows. The ON CONFLICT reset in
`create_request_tasks` deletes a *redelivered* request's rows, not a previous
request's.

## 3. The O6 nine

`../2026-08-s2-year/LOGGING-FIX.md` §4 measured nine parcels holding zero 2015
Sentinel-2 rows, and found all nine have 2015 scenes in the archive that
contain the point — none below the 40 % cloud threshold the STAC query
carries. The fleet-wide minimum was 42.7 %.

**P3. After the sweep, `sentinel2` / `2015` reads `absent` /
`all_cloud_filtered` on at least these nine parcels:**

`e4a9bed5`, `fa12be75`, `1f0c42aa`, `eab6adf5`, `ad00ac68`, `7fb423de`,
`39286f1d`, `34efa7ae`, `177681ef`.

`no_scenes` on any of the nine falsifies the empty-chunk probe
(`timeline._classify_empty_chunk`) — the probe drops the cloud filter, so a
year with archive coverage cannot read `no_scenes` unless the probe failed or
was never run.

More than nine is expected and is not a deviation: the nine are the parcels
that ended at 11 S2 rows, and a parcel that lost 2015 *and* another year would
not have appeared in that count. UNVERIFIED: the fleet-wide 2015 S2 count.

## 4. `failed`

The last two sweeps' event counts (`../2026-08-s2-year/HEAL-SCORECARD.md`
§10-equivalent, `HEAL-SCORECARD-2.md` §10, §11.6):

| event | sweep 1 (30 parcels) | sweep 2 (154 parcels) |
|---|---|---|
| STAC 403 | 2 (Landsat 2016, 2017) | 0 |
| `STAC year chunk failed after retries` | 2 | 0 |
| `Band signing failed after retries` | 0 | 0 |
| `SAS rate-limited … giving up` | 0 | 0 |
| `USGS topo fetch failed` | — | 1 (TNM 500) |

**P4. `failed` rows across a full sweep: single digits, 0–10, and
topo-dominated.** Concretely: 0–4 `landsat`/`sentinel2` rows with reason
`stac_403` or `stac_5xx`, 0–2 `usgs_topo` `*` rows with reason `other` or
`stac_5xx`, and **zero** rows with reason `sign_429` or `sign_5xx` unless a
signing incident occurs during the window.

A double-digit `failed` count means an upstream incident during the sweep, and
the ledger is then doing its job — the number is a measurement, not a target.
The one shape that would be a *defect*: `validation_failed` on many groups at
once, which would mean `_validate_asset` is now reporting a reason where it
used to report a bare drop.

## 5. `indeterminate` — the confession sites

Four sites can emit it. Every one is a follow-up, listed in `REPORT.md`.

| site | reason text names | expected count |
|---|---|---|
| NAIP absent year under a saturated 50-item pool | `naip search hit its item cap` | **low; 1 parcel in 154 hit the NAIP cap in sweep 2** |
| topo `*` under a capped 100-row TNM response | `TNM response hit its row cap` | **low; 2 TNM cap warnings in sweep 2** |
| `_classify_empty_chunk` probe itself failing | `cloud-probe failed` | **0 expected** |
| an attempted group reaching the end of `_search_and_persist_source` with no verdict | `no outcome` | **0 expected — a non-zero count is a finding** |

**P5. Total `indeterminate`: under 20 fleet-wide, and zero of them with the
`no outcome` reason.**

The last row is the one that matters. It is the residual pass: a group the
run attempted and that no branch classified. If it fires, some path between
search and persist is dropping groups in a way this batch did not find, and
that is a new defect, not noise.

## 6. The falsifiable one

**P6a. Zero `(parcel, source, group_key)` triples whose latest ledger outcome
is `ok` and which hold no matching snapshot row.** This is the lie direction —
the ledger claiming a row that is not there. The `ok` write is uncommitted
immediately before `upsert_imagery_snapshot`, whose own commit carries both,
so a crash between them cannot leave this shape. If it appears, the atomicity
argument is wrong.

```sql
SELECT y.source, y.group_key, r.parcel_id
FROM timeline_task_years y
JOIN timeline_request_tasks t ON t.id = y.task_id
JOIN timeline_requests r      ON r.id = t.timeline_request_id
WHERE y.outcome = 'ok'
  AND y.source IN ('naip', 'landsat', 'sentinel2', 'usgs_topo')
  AND NOT EXISTS (
      SELECT 1 FROM imagery_snapshots s
      WHERE s.parcel_id = r.parcel_id
        AND s.source    = y.source
        AND y.group_key = CASE
              WHEN y.source = 'usgs_topo'
                THEN ((EXTRACT(YEAR FROM s.capture_date)::int / 10) * 10)::text || 's'
              ELSE EXTRACT(YEAR FROM s.capture_date)::int::text
            END
  );
```

**P6b. Zero snapshot rows created inside the sweep window whose group has no
`ok` ledger row.** The other direction, scoped by `created_at` because the
ledger has no history: a row a *previous* run landed for a group this run
found absent is correct and expected — reconciliation deliberately leaves
absent groups alone — so only rows this sweep wrote are under prediction.

```sql
SELECT s.parcel_id, s.source, s.capture_date
FROM imagery_snapshots s
WHERE s.created_at >= :sweep_start
  AND NOT EXISTS (
      SELECT 1
      FROM timeline_task_years y
      JOIN timeline_request_tasks t ON t.id = y.task_id
      JOIN timeline_requests r      ON r.id = t.timeline_request_id
      WHERE r.parcel_id = s.parcel_id
        AND y.source    = s.source
        AND y.outcome   = 'ok'
        AND y.group_key = CASE
              WHEN s.source = 'usgs_topo'
                THEN ((EXTRACT(YEAR FROM s.capture_date)::int / 10) * 10)::text || 's'
              ELSE EXTRACT(YEAR FROM s.capture_date)::int::text
            END
  );
```

Census has the same pair against `census_snapshots`, keyed
`(parcel_id, dataset, year)` with ledger source `census_decennial` /
`census_acs5`.

## 7. What the scorecard diffs against

`scripts/ledger_gaps.py` — read-only, `--source` / `--parcel` / `--outcome`,
`--all` to list beyond the actionable rows. Its default listing is `failed`
and `indeterminate` only, which is P4 plus P5; its summary block is P1 and P2.

Capture the full `--all` output at the end of the sweep. It is the baseline
every later sweep's ledger is compared against, and there is no way to
reconstruct it afterwards.

## 8. Not predicted

- **Topo decade counts per parcel.** UNVERIFIED — 6.3/parcel is a historical
  `imagery_snapshots` average, and the ledger counts decades *in the
  response*, which is ≥ the number selected only if every decade yields a
  usable product. The two should agree; nothing measured says they must.
- **NAIP `absent` vs `suppressed` split.** The point-coverage gate
  (`14b59af`) fires on parcels with no covering tile for a year; how many
  parcel-years that is fleet-wide has never been counted.
- **Census `absent/api_no_data` count.** The `if data:` skip has never been
  instrumented — that is the entire point. Whatever number comes back is the
  first measurement of it, and `2f1b332e` (Racebrook Road, 5 census years
  against 7–9 for its peers, M4 occurrence 4) is the parcel to read first.

---

# Addendum, 2026-08-26 — the next fleet sweep, after the census decennial batch

Written before the sweep, against commit `e6afa9b` (committed, **not
deployed**). Scored by the sweep that first runs a worker carrying it. The
baseline is the production state read 2026-08-26 and recorded in
`../2026-08-census-decennial/REPORT.md` §1.1: **186 parcels**, decennial 1990
`absent` ×186, decennial 2000 `ok` 47 / `absent` 139, acs5 2009 `ok` 112 /
`absent` 74. If the fleet is a different size when the sweep runs, scale the
per-parcel claims and say so; do not edit them.

## P7 — decennial 1990 rows vanish from the ledger entirely

`census_decennial` / `1990` recorded groups: **186 → 0**. Not `absent` → some
other outcome; the group is never attempted, so no row exists. Fleet-wide
`absent` census rows drop by **186** on this account alone.

Falsifier: any `timeline_task_years` row with `source = 'census_decennial'`
and `group_key = '1990'` created after the deploy.

## P8 — decennial 2000 gains 64 parcels

`census_decennial` / `2000`: **`ok` 47 → 111, `absent` 139 → 75.**
`census_snapshots` for `(dataset='decennial', year=2000)`: **47 → 111 rows.**

The 64 are exactly the parcels whose stored `census_tract_id` ends in `00`
**and** whose four-character form answered 200 on 2026-08-26 (§1.5 of the
report lists the 16 that did not, by tract). The 47 already-`ok` parcels are
untouched — none of their tracts ends in `00`, so the trim does not fire.

Falsifiers, any one of which is a deviation to write down rather than explain
away:

* a parcel whose tract does **not** end in `00` changing outcome at all;
* fewer than 64 gained — the difference is either a tract that has changed
  since the probe or an upstream change, and the report's per-tract list says
  which parcels to check;
* more than 64 gained — the trim is firing somewhere the probe did not
  predict, which means the rule in §1.4 is narrower than the code.

`09170157100` (Racebrook) **stays `absent`** and is the only parcel in the
fleet expected to. Its stored county is a planning region; decennial 2000 has
no `_GEOGRAPHY_VINTAGES` entry, so it is still asked as `09170`/`1571`.

## P9 — acs5 2009 gains from the Racebrook ride-along

`4ce1822` mapped acs5 2009 to `Census2010_Current`, so a parcel redistricted
in 2010 is now asked under its 2010 tract instead of its 2020 one. **74
parcels currently have no acs5 2009 row** (`ok` 112 / `absent` 74).

Predicted: **between 0 and 74 gained, and never a loss.** This is deliberately
not a point estimate — the ride-along was never measured fleet-wide, and
§4.4 of `../2026-08-racebrook/REPORT.md` shows the recovery only works where
the 2010 tract is also the 2000 tract. The falsifiable half is the floor: any
parcel moving acs5 2009 from `ok` to `absent` falsifies the "never worse"
claim the fix was accepted on.

## P10 — no `absent` census row hides an HTTP status

After the reason split, **every** remaining `absent`/`api_no_data` census row
carries a 200-with-empty-body or a 204, and **no `failed`/`http_*` census row
exists at all** unless the worker log shows the matching status in the same
window.

Falsifier: an `absent`/`api_no_data` row for a (dataset, year) whose log line
in the same request shows a 4xx/5xx. That would mean a second collapse
survives somewhere upstream of the ledger.

A `failed`/`http_*` row appearing **is not** a falsification — it is the
instrument working. What it must come with is a log line carrying the same
status and the same dataset path.

## P11 — the decennial floor, stated plainly

After the sweep, production's decennial coverage is **2000 for 111 parcels,
2010 for the remaining 75, and 2020 for all 186**. There is no 1990 anywhere
and there will not be until the census tabular ingest lands. Any user-facing
copy still claiming 1990 is false on the day this sweep finishes — the copy
batch is tracked separately in STATUS.md.
