# Prediction — the NORM-31 footprint heal against production

Written and committed **before** `enrich_snapshot_scenes.py --revalidate-footprints
--execute` is launched. Session of 2026-08-29, ~20:30Z onward. Serving sha
`92ecf19d2d6353c0e6a037ef9cc58ff5623f7a8b`.

## E0 — what is and is not blind

Almost nothing about the *plan* is blind, and saying so is the point. The queue
was measured read-only at **20:33:59Z** (`norm31-preheal.json`) and is **2**;
both items were fetched from the public Planetary Computer catalogue during the
local build and their repairs were measured there (`NORM31-REPORT.md` §2); the
repair rule is unit-tested against one of the two real geometries byte-for-byte.

**What is genuinely unknown:**

1. Whether the write lands what the rule computed locally — the local
   measurement was shapely-in-a-container over a catalogue fetch, not a
   PostGIS round-trip through `ST_GeomFromEWKT` into a
   `geometry(POLYGON,4326)` column.
2. Whether the repaired geometry still contains the parcel points the raw ring
   contained — the serving property, never yet asked of production data.
3. Whether anything outside the two rows moves.
4. Whether the deployed script's revalidate mode behaves against real data as
   it did against a seeded local row.

## The reference the serving check is scored against

Computed here, **before the write**, by an even-odd ray cast over the raw ring
as stored in production — arithmetic, not shapely, so the library that performs
the repair does not also grade it (`NORM31-REPORT.md` §5's method).
`norm31-raw-ring-containment.json`:

| item | parcel | lon, lat | raw ring contains |
|---|---|---|---|
| `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` | `b494f235…` | -70.7948434, 42.1339997 | **true** |
| `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | `31929a9c…` | -86.029790650648, 39.967219365955 | **true** |
| `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | `d6cf2ac8…` | -86.276848, 39.9642377 | **true** |

## The predictions

| # | Quantity | Predicted |
|---|---|---|
| P1 | Queue at start (recorded, not blind) | **2**, both `sentinel2` / `snapshot`, ids `6d456449…` and `6b114490…` |
| P2 | Rows fetched / STAC requests | **2 / 2** |
| P3 | item GET 404 / 403 / errors | **0 / 0 / 0** |
| P4 | Footprints written / queue after | **2 / 0** |
| P5 | `ST_IsValid` on both rows after | **true, both** |
| P6 | `GeometryType` of both after | **`POLYGON`**, both — neither row is a multipart case (`NORM31-REPORT.md` §2) |
| P7 | `ST_Area` after, 8 dp | **0.76542450** and **1.03875393** — unchanged from the pre-heal reading |
| P8 | `ST_Contains(footprint, parcel.point)` after | **true on all 3 parcel points** above |
| P9 | `footprint_repaired_invalid_geometry` events | **2**, one per item, reasons `Self-intersection[-71.00403 41.90664113]` and `Self-intersection[-86.75983 39.91487413]`, `polygon_parts = 1`, `footprint_repair_discarded_area = 0.0` |
| P10 | `FOOTPRINT_INVARIANT_SQL` after | `not_polygon` **0**, `invalid` **0**, `equals_bbox` **0**, over **5,894** footprints |
| P11 | Footprint fingerprint **outside** the queue | **`b605a050fb49731dd45175d13e89ac9c`** over 6,661 rows — **unchanged** |
| P12 | Footprint fingerprint over all rows | **changed** from `54a1a8a55bd93e2bafd6aa0a1b51f4bc`; both rows' `footprint_md5` differ from `5ccd9329…` / `ecbad666…` |
| P13 | `bbox` fingerprint | **`f1809593fd050be14736aaaea4b09ed5`** over 6,663 rows — unchanged; both rows' `bbox_wkt` byte-identical |
| P14 | `resolution_m` fingerprint | **`b30a4fc5c7b6ff36aae6573714e049ec`** — unchanged; both rows still **10.0** |
| P15 | Row counts / provenance split | **6,663 / 12,884 / 12,884**; 6,156 snapshot / 505 enriched / 2 selection — unchanged |
| P16 | `.rc` | **0** |
| P17 | Wall time | **under 60 s** — one batch, two fetches, against 1,079–1,195 s for 5,187–5,387 rows |
| P18 | Dry re-run after the heal | queue **0**, rows fetched **0**, STAC requests **0**, `.rc` **0** |

### The instrument, item 6 — scored quantities of its own

| # | Quantity | Predicted |
|---|---|---|
| P19 | `scripts/snapshot_reads.py` in production | runs to completion, exit **0** |
| P20 | The pool after it | a **fresh** connection reads `default_transaction_read_only = off` **and** `transaction_read_only = off`; over a sample of 8 sequential fresh connections, **0 of 8 read-only** |
| P21 | Rows read from `imagery_snapshots` since t0 by the reconciler | `max(parcel_scenes.selected_at)` is `2026-08-29 04:41:26+00`, i.e. **before** t0 (`06:41:47.270470Z`), so **no selection has run since t0** and the reconciler's diff pull should account for **0** of any observed access. A nonzero `pg_stat` delta is therefore *not* predicted to be zero — Neon autovacuum/analyze and any uninstrumented reader also touch these counters — and any delta must be **enumerated and explained rather than waved at**. |
| P22 | `imagery_snapshots_read` structlog observations | a **floor**, never a count: `fly logs` serves a capped buffer, so the event count states a minimum and the coverage claim says so explicitly. |

## Stop conditions, as outcomes

* Queue ≠ 2 at launch → stop, reconcile, do not write.
* Any 404/403/error on the two items → stop; the rows stay invalid.
* `.rc` ≠ 0 → report the state as it is; do not relaunch blind.
* Any fingerprint outside the queue moving → stop and report; that is a heal
  that touched rows it does not name.
* A repaired row that fails P8 → stop and report: a valid geometry that lost
  its parcel is a worse outcome than an invalid one that kept it.

---

## Observed — production, the heal

Appended after the run at `20:36:43–20:36:45Z`. The prediction half above is
unedited; it was committed at `213ae77`, before the write.

**21 scoreable, 21 confirmed, 0 falsified.** The line-by-line score is
`NORM31-PROD-REPORT.md` §5; the readings are `norm31-postheal.json`,
`norm31-run.md`, `norm31-run.rc`, `norm31-dryrun-2.md` and `reads-t2.json`.

Three observations the prediction did not contain:

* **`ST_NPoints` fell 28 → 27 and 22 → 21.** The repair pinched off the
  zero-area spike, taking the duplicate vertex at the self-intersection with
  it. Area is preserved to 8 dp, so nothing covered was lost.
* **`fetched_at` did not move** on either row — the mode writes the footprint
  column and nothing else, shown by a timestamp rather than by a fingerprint.
* **`scenes.n_tup_upd` has moved +5,389 since the step-3 cooling t0** — 5,387
  from the big heal and exactly 2 from this one. The database's own write
  counter accounts for every `scenes` update this arc has made.

**P21 needs its wording read carefully rather than its verdict.** It predicted
that the reconciler would account for none of the observed delta, and
`imagery_snapshots.idx_scan` moved **+0**, so it is confirmed. What it does
*not* establish — and said so in advance — is that the reconciler is the only
reader, because the reconciler never ran in this window at all. That is why the
step-4 verdict in `NORM31-PROD-REPORT.md` §6d is **not yet**.
