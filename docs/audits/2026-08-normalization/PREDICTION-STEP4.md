# Prediction — step 4's local fleet sweep

Written before the sweep runs, and committed before it runs. Scored in a later
commit; this half is never edited.

---

## 0. Blindness, stated first

**This prediction is blind in the sense that matters and I will say exactly
where it is not.**

* **Not run:** the fleet sweep itself. `scripts/requeue_parcels.py` over all 45
  local parcels has not been run at this commit, in any mode, not even
  `--dry-run`. No outcome below has been observed.
* **Run, deliberately, and committed as artifacts:** two *pre-run* readings —
  `step4-pre-sweep.json` (`scripts/normalization_invariants.py`) and
  `step4-reads-t0.json` (`scripts/snapshot_reads.py`). A prediction of deltas
  needs a baseline, and every prior prediction in this arc took one the same
  way. §2 is that baseline; it is measurement, not outcome.
* **Run:** `scripts/normalization_invariants.py` exists because of this batch
  and its *first* execution was the §2 baseline. It has not been run against a
  post-sweep state.

The STEP3 §0 lesson — a prediction is worth exactly what its timing is worth —
is why this section leads. If the sweep turns out to need a fix to the battery
or to the requeue path before it can run at all, that is a deviation and it
goes at the top of the report, not in a footnote.

---

## 1. What is being run

```
docker compose exec -T api python scripts/requeue_parcels.py \
    --skip-deploy-check --sources naip,landsat,sentinel2,usgs_topo <45 parcel ids>
```

against the local PostGIS database at migration **0018** (0019 is committed
and **not applied** — the local table still physically exists, which is
deploy-1's production state exactly), with the code cutover `329a8a6` in
place. Then, once the worker drains:

```
docker compose exec -T api python scripts/normalization_invariants.py --out …
docker compose exec -T api python scripts/snapshot_reads.py \
    --baseline /tmp/step4-reads-t0.json --out …
```

The census and property sources are out of scope: they write neither table,
and including them would spend upstream calls on a question this sweep is not
asking.

## 2. Baseline, read 2026-08-29T21:45–21:46Z

`step4-pre-sweep.json`:

| quantity | value |
|---|---|
| `parcels` | **45** |
| `scenes` | **1,342** |
| `parcel_scenes` | **3,082** |
| every zero-check | **0** (7 of 7) |
| `scenes` by provenance | snapshot 1,174 · enriched 88 · selection 80 |
| landsat per parcel | **43**, on all 45 parcels (1,935 rows) |

Ledger, latest outcome per (parcel, source, group): landsat ok 1,933 / failed
2; naip ok 323 / absent 437 / suppressed 5; sentinel2 ok 539 / absent 1;
usgs_topo ok 285 / indeterminate 3.

`step4-reads-t0.json`, the counters this sweep is differenced against:

| table | seq_scan | idx_scan | ins / upd / del |
|---|---|---|---|
| `imagery_snapshots` | 794 | 48,352 | 3,764 / 10,066 / 682 |
| `parcel_scenes` | 272 | 55,325 | 3,082 / 0 / 0 |
| `scenes` | 982 | 73,110 | 1,342 / 1,119 / 0 |

Migration 0018 applied cleanly against this database at 21:44Z, which is
itself a measurement: a validating CHECK is refused while any row fails it, so
all 1,342 `scenes` rows already satisfy `footprint IS NULL OR
ST_IsValid(footprint)`.

---

## 3. The load-bearing prediction

**P1. `imagery_snapshots` takes ZERO reads and ZERO writes across the whole
sweep.** Every counter delta is exactly `+0`: `seq_scan`, `seq_tup_read`,
`idx_scan`, `idx_tup_fetch`, `n_tup_ins`, `n_tup_upd`, `n_tup_del`.

This is the prediction the batch exists to make. It is not "small" or "only
the reconciler" — it is zero, from anything, and **any nonzero value is a
finding**, not a rounding.

*Why it should hold:* no file under `app/` or `scripts/` names the table
(`tests/test_no_imagery_snapshots_references.py`), the two audit instruments
read `pg_stat_user_tables` and the normalized tables only, and nothing else
runs against this database during the window.

*The one way it could move without being a finding, named in advance so it
cannot be invented afterwards:* an autovacuum or ANALYZE on the table. Neither
increments `seq_scan` (they are not query-plan scans) and autovacuum has no
work with zero writes, so I predict this does not happen either — but if
`n_live_tup` moves while every scan counter stays 0, that is the explanation
and it is a deviation, not a falsification of P1.

**P1 is falsified by any nonzero delta on any of the seven counters.**

## 4. The sweep's own shape

**P2. The sweep writes almost nothing, and that is correct.** NORM-12: a
*current* database cannot exercise an insert path. This database was swept
during step 2 and has not been touched since, so nearly every group will
re-select the item it already serves and `_upsert_parcel_scene`'s `unchanged`
early return will fire.

* **P2a.** `parcel_scenes.n_tup_ins` delta **0–20**. I predict **0** as the
  single most likely value; anything above 20 means upstream published items
  for periods this fleet did not previously serve, which is possible and would
  be reported rather than treated as an error.
* **P2b.** `parcel_scenes.n_tup_del` delta **exactly 0**. A delete now requires
  a `suppressed` outcome naming a served item, and the baseline's 5 naip
  suppressions are already reflected in the current state.
* **P2c.** `scenes.n_tup_ins` delta **0–40**, most likely **0**. Bounded above
  by P2a plus mosaic tiles.
* **P2d.** `parcel_scenes.n_tup_upd` delta **0–10**. An update means a period
  changed which item it serves — Landsat re-validation picking a different
  scene is the live case.

**P3. `parcel_scenes` and `scenes` both take substantial index traffic.**
`parcel_scenes.idx_scan` delta **> 3,000** and `scenes.idx_scan` delta
**> 3,000**. This is the control on P1: a window in which nothing read
anything proves nothing about which table is read, and §6d called that out as
the weakness of the step-3 reading. If P1 holds and P3 fails, the sweep did
not happen and P1 is worthless.

## 5. Invariants after the sweep

**P4. All seven zero-checks are still 0.** duplicate_groups,
dangling_primary, dangling_mosaic, primary_in_own_mosaic, invalid_footprints,
non_polygon_footprints, duplicate_items.

`invalid_footprints` is the one with a live mechanism behind it: every
pipeline-written footprint goes through `normalize_footprint`, and 0018's
CHECK would refuse the insert if one did not. A nonzero value here would mean
0018 is not doing what its docstring says, which is the strongest single
finding this sweep could produce.

**P5. Landsat is conserved per parcel: 43 rows on all 45 parcels, 1,935
total.** Per parcel, not in aggregate — a total conserves while two parcels
swap. A parcel that *gains* a Landsat year is not a violation and would be
reported; a parcel that loses one is.

**P6. `parcels` stays 45 and `parcel_scenes` is ≥ 3,082**, equal to 3,082 +
P2a. It cannot shrink: P2b says zero deletes.

**P7. `scenes` provenance keeps `mosaic_url` at 0.** The class the step-1
backfill created is closed for new rows (step 2's amendment); `snapshot` stays
at exactly **1,174** and `enriched` at exactly **88**, because both are
historical populations no writer produces. Any growth in `selection` equals
P2c.

## 6. The ledger

**P8. The outcome distribution is stable in shape.** Read per NORM-3 (latest
row per parcel/source/group), I predict:

* `landsat/ok` **≥ 1,930** and `landsat/failed` **≤ 5**. The baseline's 2
  failures are a single parcel-year class; a re-run may clear them or
  reproduce them, and both are ordinary.
* `naip/absent` **within ±40 of 437** — this is the largest population in the
  ledger and the one most sensitive to upstream, and a rule that treated its
  movement as a defect would treat NAIP's actual coverage as a defect.
* `usgs_topo/indeterminate` **stays at 3 or falls**. It must not rise: an
  `indeterminate` is a confession that a group reached the end of the persist
  loop with no verdict, and the step-4 rewrite of that loop is exactly the
  kind of change that could introduce one.

**P8 has a hard clause:** `indeterminate` rising above 3 on any source is a
**finding against this batch**, because the loop that emits it is the loop
this batch rewrote.

**P9. No source's task ends `failed` for a reason attributable to the
rewrite.** Upstream 403/429/timeout are ordinary and expected in a 45-parcel
sweep. A `failed` whose message names a missing table, a missing function, or
a NOT NULL/CHECK violation on `scenes`/`parcel_scenes` is a finding.

## 7. After 0019 is applied locally

Run only once §3–§6 have been scored.

**P10. The suite is green with the table gone**, and the count is unchanged
from the pre-0019 run: 749 passed, 12 skipped. No test constructs the table,
so dropping it should be invisible to every one of them — and if any test goes
red here, it was reaching the table through a path the reference-pinning test
does not cover, which is a finding about the pin.

**P11. A second invariant battery after the drop is identical to the first**
on every quantity except that `snapshot_reads.py` reports `imagery_snapshots:
not present`. `scenes` and `parcel_scenes` counters continue from where they
were; the battery never read the dropped table, so nothing in it changes.

**P12. The 0019 downgrade/upgrade round trip leaves the database at head with
the table absent**, and the intermediate downgraded state has the table
present with **0 rows** — the migration's central claim, exercised against the
real local database rather than only against a throwaway.

---

## 8. What would make me stop rather than report

* **P1 nonzero.** The cooling measurement's premise is that the code cannot
  touch the table. A nonzero delta means it can, and the deploy-2 gate is not
  met by anything this session produced.
* **P4's `invalid_footprints` nonzero.** 0018 would be admitting rows it
  claims to refuse.
* **P8's `indeterminate` above 3.** The rewritten loop dropping a group
  silently is the failure mode the ADR's own norms name first.
