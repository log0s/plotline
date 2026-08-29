# Prediction — step 2's production sweep, staged

Written and committed **before** the pilot sweep ran, per the record rule
"predictions before actions". The Observed halves are appended afterwards and
this half is never edited.

Step 2 is the dual-write: `reconcile_source_snapshots` writes `scenes` and
`parcel_scenes` alongside `imagery_snapshots`, in one transaction. It is
deployed to production for the first time as of 2026-08-29 03:37:25Z. **No
production pipeline run has ever written `scenes` or `parcel_scenes`** — both
tables exist only because `scripts/backfill_scenes.py` and
`scripts/enrich_synthesized_scenes.py` filled them on 2026-08-28.

The sweep is staged: a 30-parcel pilot, a parity gate, then the remaining
159 parcels.

Code under test: `efa4c63` (HEAD), which contains `61d486b` (migration 0017),
`9526805` (the dual-write), `17c488e` (tests) — all verified ancestors of
HEAD by `git merge-base --is-ancestor`.

---

## 1. Deploy gates — all four pass, measured 2026-08-29 03:39–03:41Z

| Gate | Evidence | Result |
|---|---|---|
| a. Health SHA is the step-2 head | `fly ssh console -a log0s-plotline-api -C "curl -s localhost:8000/api/v1/health"` → `{"status":"ok","db":"connected","redis":"connected","version":{"sha":"efa4c63a07455c5fc776c431d345284fd4082ddd","built":"2026-08-29T03:37:25Z"}}`. `git merge-base --is-ancestor 61d486b HEAD` and `… efa4c63 HEAD` both exit 0 | **pass** |
| b. Both apps, every machine | `fly image show -a log0s-plotline-api` (machines `825d69b7e46618`, `48e0de9a713918`) and `-a plotline-worker` (`e7845415f57728`, `e2862966b306d8`): all four carry `GH_SHA=efa4c63a07455c5fc776c431d345284fd4082ddd` | **pass** |
| c. Migration head is 0017's own revision id | `SELECT version_num FROM alembic_version` → `0017`, read 03:39:48Z. The revision id is read from the file, not inferred from the filename: `backend/alembic/versions/0017_scenes_provenance_selection.py:49` declares `revision: str = "0017"` | **pass** |
| d. The CHECK actually admits `'selection'` | `pg_get_constraintdef` for `ck_scenes_provenance` → `CHECK ((provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text, 'enriched'::text, 'selection'::text])))` | **pass** |

(d) is queried, not assumed. "The migration ran" and "the migration applied
its intent" are different claims, and only the second lets a row carry the
new value.

## 2. The state the sweep starts from — read-only, 2026-08-29 03:41:38Z

Every probe opened its own connection and called
`conn.set_session(readonly=True)`.

| Quantity | Value | Expected by the prompt |
|---|---|---|
| `scenes` | **6,661** — 6,156 `snapshot`, 505 `enriched`, **0 `mosaic_url`, 0 `selection`** | 6156 / 0 / 505 / 0 — **match** |
| `scenes` by source × provenance | landsat/snapshot 3,174; naip/snapshot 1,102; naip/enriched 505; sentinel2/snapshot 1,111; usgs_topo/snapshot 769 | — |
| `parcel_scenes` | **12,884**; 576 rows carry a mosaic; **613** references; **578** distinct references; **0** with `selected_by` | — |
| dangling `mosaic_scene_ids` | **0** | 0 |
| duplicate `(parcel_id, source, group_key)` in `imagery_snapshots` | **0** | 0 |
| duplicate `(collection, item_id)` in `scenes` | **0** | 0 |
| duplicate `(parcel_id, source, group_key)` in `parcel_scenes` | **0** | — |
| `imagery_snapshots` | **12,884** (landsat 8,127 / naip 1,305 / sentinel2 2,259 / usgs_topo 1,193); `max(created_at)` **2026-08-27 19:41:01.190Z** | — |
| **parity, fleet-wide, both directions** | **0 / 0** | 0 / 0 — **match** |
| `scenes.footprint IS NULL` | 6,156 of 6,156 `snapshot`; 0 of 505 `enriched` | NORM-7's deferred queue, unchanged |
| NAIP `scenes.resolution_m` | `snapshot`: 1.0 on all 1,102. `enriched`: 0.3 (38), 0.5 (6), 0.6 (192), 1.0 (261) **plus the 8 noisy NORM-11 spellings** | — |
| NAIP `imagery_snapshots.resolution_m` | **1.0 on all 1,305 rows** — NORM-9's constant, table-wide | — |
| parcels | 189, all with imagery | — |
| `timeline_requests` | 1,110 `complete`, 40 `partial`, 3 `failed`; **none in flight** | — |

**Everything the prompt named as a stop condition is clean.** The parity
zero holds *before* any sweep, which is the expected shape: backfill plus
enrichment already made the two representations agree, so the sweep's job is
to keep them agreeing under a live pipeline, not to create the agreement.

### 2a. The ledger, read alongside (NORM-3)

The prompt asks for the last-24h outcome distribution. **It is empty.** The
ledger's newest row is `2026-08-27 22:00:44.962Z`, ~30 h before this
measurement; 35,377 rows total. So the last-24h window says nothing, and the
honest window to read is the last two fleet sweeps:

| source | outcome / reason | rows since 2026-08-25 |
|---|---|---|
| landsat | ok | 16,366 |
| landsat | **failed / read_timeout** | **17** — all `2026-08-26 09:42:19Z`, all on one parcel |
| naip | ok | 2,630 |
| naip | absent / no_scenes | 3,814 |
| naip | **failed / read_timeout** | **17** — all `2026-08-26 09:16:12Z`, same parcel |
| naip | indeterminate / item-cap truncation | 14 |
| naip | suppressed / naip_no_point_coverage | 19 |
| sentinel2 | ok | 4,530 |
| sentinel2 | absent / all_cloud_filtered | 18 |
| usgs_topo | ok | 2,387 |
| usgs_topo | absent / no_scenes | 1 |
| usgs_topo | indeterminate / TNM row cap | 3 |

Ledger rows by day: **16,587 on 2026-08-26, 18,790 on 2026-08-27** — two
full fleet sweeps on consecutive days (189 parcels × 43 Landsat years alone
is 8,127).

**All 34 `failed` rows are from the 08-26 sweep and all 34 are on one
parcel**, `6563dedf-23b1-4719-89db-ab135ed24fb3` (landsat 1984–1999, naip
2010–2026). **The 08-27 sweep recorded zero `failed` rows fleet-wide.** So
the pre-sweep parity zero does *not* rest on unretried upstream failure in
the most recent sweep — the NORM-3 reading, and it comes out clean. The
`indeterminate` rows (topo row cap, NAIP item cap) are pre-existing
truncation-risk markers on three parcels and are not failures.

## 3. Pilot selection — the rule, stated before the run

30 parcels of 189 (15.9%). No prior staged pilot exists in the audit record,
so the rule is stated here rather than inherited. It is deterministic and
reproducible from the baseline queries: **no parcel was excluded for being
risky.**

**Tier A — the hard cases (5).** Every parcel the ledger marks as difficult
is in the pilot, not out of it.

| Parcel | Why |
|---|---|
| `6563dedf-23b1-4719-89db-ab135ed24fb3` | the **only** parcel with `failed`/`read_timeout` rows in either recent sweep — 17 landsat years + 17 naip years, 08-26 |
| `fe065e2d-7818-408e-a1ff-d529bae67c57` | NAIP `indeterminate` (search hit its item cap) on 7 years, in **both** recent sweeps |
| `e513188c-7de4-435e-994e-98621d88a81b` | 350 5th Ave — 8 mosaic rows, `usgs_topo` `indeterminate`, and the geometry audit's uncovered-NAIP-2023 parcel |
| `09f35468-2695-49a1-b0ef-70823749b938` | landsat 1994 `read_timeout` on 08-26; 7 mosaic rows |
| `9c35ceb0-e922-4971-87a4-1ae9aab7c8d9` | Hudson Yards — **featured** (public surface), 9 mosaic rows / 10 references, `usgs_topo` `indeterminate` in both sweeps |

**Tier B — the mosaic population (4).** The four highest mosaic-row parcels
not already in tier A.

| Parcel | Mosaic rows / refs |
|---|---|
| `4146ec5f-8860-4b91-9842-42225096e9c9` | 13 / 13 |
| `34efa7ae-ea51-4c03-940f-98308439d4cc` | 12 / 12 |
| `39286f1d-baa2-457b-8e4a-1bee4e5fddce` | 11 / 11 |
| `dc493cc5-1b6e-4cad-b311-11b4418947c9` | 10 / 16 — also **featured** (Navy Yard), and the geometry heal's clean control |

**Tier C — unremarkable (21).** The first 21 parcels by `id` ascending that
carry no mosaic row, are not featured, and are not in tier A or B:
`02d958d9`, `099336a2`, `0e0abf8c`, `0e7f4129`, `100c2b8f`, `1074e64b`,
`11b0f0c1`, `134ca8cd`, `13f20e3b`, `153b4e14`, `1754635c`, `177681ef`,
`189ff067`, `1a473e7c`, `1c5a3af3`, `1cc54096`, `1dbd9583`, `2003d090`,
`23125dc1`, `267aa62b`, `2758a216`.

**Two featured parcels** are in the pilot (Hudson Yards, Navy Yard) and four
are not (Stapleton, RiNo, Green Valley Ranch, Rodanthe) — enough to prove the
public-surface class without putting the whole landing page behind an
unproven write path.

### 3a. The pilot's own baseline, read-only 03:45:39Z

| Quantity | Value |
|---|---|
| `imagery_snapshots` | **2,075** — landsat 1,290 / naip 227 / sentinel2 357 / usgs_topo 201 |
| `parcel_scenes` | **2,075**; 76 carry a mosaic; **83** references |
| parity over the 30 parcels, both directions | **0 / 0** |
| NAIP `imagery_snapshots.resolution_m` | **1.0 on all 227** |

Landsat is **exactly** 1,290 = 30 parcels × 43 years. That is the
conservation invariant the geometry heal scored on, and it is exact here
before the run.

## 4. The command

```
python scripts/requeue_parcels.py --require-sha efa4c63 \
    --sources naip,landsat,sentinel2,usgs_topo <30 parcel ids>
```

run detached inside the API machine with output to a file (`nohup … &`), per
NORM-8 / the F5 rule: **a killed ssh client neither kills nor rolls back the
remote process.** The remainder is the same command over the other 159 ids.

Two choices worth stating rather than leaving implicit:

* **`--require-sha efa4c63`, not `--skip-deploy-check`.** The gate is
  satisfiable in production and this is exactly the case it exists for — a
  re-queue re-runs selection against whatever the worker is running.
* **`--sources naip,landsat,sentinel2,usgs_topo`, not full scope.** Step 2
  changed the imagery pipeline and nothing else. Full scope would also re-run
  property and census tasks, writing tables this batch has no claim about and
  adding load to a run whose request-path cost is already the G4 risk. The
  local step-2 sweep used the same four sources.

## 5. What this sweep can and cannot prove — stated in advance (NORM-12)

**Production's `parcel_scenes` and `scenes` are already backfilled and
enriched.** Every one of the 12,884 groups the sweep touches will pass
through the dual-write, and the overwhelming majority will find their scene
already present and their selection unchanged, and will therefore **write
nothing**. That is correct behaviour and, by itself, weak evidence.

**So this run proves the upsert path and fleet-scale parity. It does not
prove the insert path.** The insert path's correctness rests on the fourteen
mutation-verified tests in `backend/tests/test_scene_dual_write.py` and on
the two local probe parcels (`STEP2-REPORT.md` §3b), and production
exercises it only at the margin. **The report must not imply that 12,884
groups exercised new code**, and this paragraph is committed before the run
so that it cannot become a post-hoc excuse.

### 5a. The mosaic-tile insert population, derived read-only — and it is zero

The prompt names newly-catalogued NAIP mosaic tiles as "the largest
predictable insert population" and asks for its size to be derived from
`parcel_scenes.mosaic_scene_ids` joined to `scenes.provenance`. Derived:

| Target `scenes` row | Distinct tiles | References |
|---|---|---|
| naip / `enriched` | **505** | 540 |
| naip / `snapshot` | **73** | 73 |
| **total** | **578** | **613** |

**All 578 distinct mosaic tiles referenced anywhere in `parcel_scenes`
already exist as `scenes` rows, and every one of them carries a catalogued
`(collection, item_id)`** — the 505 because the 2026-08-28 enrichment pass
replaced their URL-derived candidate ids with catalogued ones, the 73 because
they were somebody's primary item. `_ensure_scene` looks a tile up by
`(collection, item_id)`; the selector derives that pair from the STAC item;
the enrichment derived it from the same catalog. **So a re-picked tile is a
hit, not an insert.**

**The premise is therefore falsified before the run, and predicted as such:
mosaic tiles contribute 0 new `scenes` rows for any NAIP group whose
selection does not change.** The mosaic-tile insert population is a *subset*
of the churn population, not a separate and larger one. If it comes back
nonzero beyond what NAIP churn explains, that is a finding about
`(collection, item_id)` not being the key the enrichment made it — the same
falsification `PREDICTION-STEP2.md` §3 named, now against 505 production rows
instead of 88 local ones.

### 5b. So the insert population is churn, and here is its measured anchor

The two consecutive fleet sweeps in the ledger give a direct measurement of
what one day of drift costs, which is better than an argument:

| Sweep day | landsat | naip | sentinel2 | usgs_topo | total rows inserted |
|---|---|---|---|---|---|
| 2026-08-26 (1 day after 08-25) | 112 | 15 | 24 | 20 | **171** |
| 2026-08-27 (1 day after 08-26) | 104 | 18 | 43 | 10 | **175** |

and the pilot's own share of it:

| Sweep day | pilot rows inserted |
|---|---|
| 2026-08-26 | **101** (landsat 69, naip 9, s2 12, topo 11) |
| 2026-08-27 | **36** (landsat 18, naip 6, s2 12) |

08-26 is inflated for the pilot because tier A's `6563dedf` had 34
read-timeout groups to refill. **08-27 is the clean anchor: 36 pilot rows,
175 fleet rows, for a one-day gap.**

The mechanism behind the historic-year churn is not new: the Landsat and
Sentinel-2 validation walks re-sign assets live, so a year that fell back to
a different item last time may not this time, and both sources cap at 20
items per year against a newest-first catalog, so the 2026 candidate pool is
a sliding window (`timeline.py:76,87`; `HEAL-SCORECARD.md` §1).

The gap for this run is **2026-08-27 19:41Z → ~2026-08-29 04:00Z ≈ 32 h**,
about 1.35 days.

## 6. The quantities — pilot

| # | Quantity | Prediction |
|---|---|---|
| PP1 | Parity violations over the 30 pilot parcels, both directions | **0 / 0** |
| PP2 | Duplicate `(parcel_id, source, group_key)` in `imagery_snapshots`, pilot | **0** |
| PP3 | Duplicate `(collection, item_id)` in `scenes`, table-wide | **0** — see §6a |
| PP4 | Dangling `mosaic_scene_ids`, table-wide | **0** |
| PP5 | New `scenes` rows | **20–75, most likely 30–55**, all `provenance = 'selection'`. Derivation: 36 pilot snapshot rows at a 1-day gap × ~1.35 ≈ 49 changed groups; 80–95% of changed items are new to `scenes` (a churned item can already be held by another parcel — landsat runs 2.56 `parcel_scenes` rows per scene) |
| PP6 | `scenes` rows deleted | **0** — the dual-write is insert-only and nothing else writes the table |
| PP7 | `scenes` with `provenance = 'mosaic_url'` | **0**, unchanged |
| PP8 | Pilot `parcel_scenes` with `selected_by` non-NULL | **= the number of rows inserted or changed, 20–75 — not 2,075.** NORM-12: an unchanged selection is left completely alone, no `selected_at` bump, no `selected_by`. `selected_by` will be the literal `efa4c63a07455c5fc776c431d345284fd4082ddd` |
| PP9 | NAIP `imagery_snapshots.resolution_m` over the pilot | **no longer uniformly 1.0**: 3–12 rows carrying a real gsd (0.3 / 0.5 / 0.6), the rest still 1.0. **This is NORM-9 observable in production for the first time.** Every value is a two-decimal number — no NORM-11 noise spelling — because `normalize_resolution_m` rounds at write time |
| PP10 | Pilot `imagery_snapshots` row count | **2,075 ± 3**, and **landsat exactly conserved at 1,290** (30 × 43). A group is replaced in place, not added; movement happens only when a period newly appears or disappears |
| PP11 | Pilot `parcel_scenes` row count | **= pilot `imagery_snapshots` row count** (PP2 makes them equal by definition) |
| PP12 | Ledger `failed` rows in the pilot window | **0 expected**; any that appear are named, and any group with a `failed` row is named as one the parity zero does not cover (NORM-3) |

### 6a. PP3 is the load-bearing one, and it is F1's collision class

`STEP1-PROD-REPORT.md` F1 / NORM-7 described the failure this way: a
synthesized `scenes` row and a real catalogued write become two rows for one
physical tile, differing in `item_id`, so `UNIQUE (collection, item_id)` is
satisfied and the duplicate lands silently. The 2026-08-28 enrichment pass
closed it by making all 505 candidate ids catalogued — **an argument from the
code and from a dry run, never yet tested by a live write.**

**The pilot is that test.** It is the first time the dual-write has ever
inserted into a production `scenes` table the enrichment prepared. PP3 = 0 is
the first live evidence for the NORM-7 argument at production scale, and a
nonzero PP3 falsifies it.

### 6b. Request-path degradation is expected and accepted for the window (G4)

`HEAL-SCORECARD.md` §4 item 4 measured it during the 2026-08-12 fleet sweep:
41 × `SAS rate-limited; backoff exceeds wait budget, giving up`, 17 × `Band
signing failed after retries`, 115 Titiler 500s. The mechanism is unchanged —
the batch path's signing load exhausts Planetary Computer's limit while the
request path's 2 s `SIGN_WAIT_REQUEST` budget gives up immediately, so a user
browsing during a sweep gets 500s.

**Predicted: the same signature appears again, in both the pilot and the
remainder windows.** It is accepted for the duration of the sweep and is not
a stop condition. It *is* recorded with timestamps as its own finding if it
appears, and its absence would itself be worth noting — the pilot is a sixth
the fleet, so a pilot that produces no signing storm does not prove the
remainder will not.

## 7. The quantities — remainder (159 parcels)

Scored after the pilot gate passes. Bands derived the same way: the 08-27
fleet sweep inserted 175 rows of which 36 were the pilot's, so **139 rows for
the remaining 159 parcels at a one-day gap.**

| # | Quantity | Prediction |
|---|---|---|
| PR1 | Parity, fleet-wide, both directions | **0 / 0** |
| PR2 | Duplicate `(parcel_id, source, group_key)`, fleet-wide | **0** |
| PR3 | Duplicate `(collection, item_id)`, table-wide | **0** |
| PR4 | Dangling references, table-wide | **0** |
| PR5 | New `scenes` rows from the remainder | **80–300, most likely 120–190**, all `'selection'` |
| PR6 | `scenes` total after both sweeps | **6,661 + (PP5 + PR5)** → band **6,760–7,036**, most likely **~6,830–6,900** |
| PR7 | `scenes` deleted / `mosaic_url` | **0 / 0** |
| PR8 | Fleet `parcel_scenes` with `selected_by` | **= PP5-and-PR5's changed-row count, 100–375 of 12,884.** The other ~97% stay NULL, and that is correct, not a failure — NORM-12 |
| PR9 | Fleet `imagery_snapshots` row count | **12,884 ± 15**, landsat exactly conserved at **8,127** (189 × 43) |
| PR10 | Fleet `parcel_scenes` = fleet `imagery_snapshots` | **equal** |
| PR11 | NAIP `imagery_snapshots.resolution_m` ≠ 1.0, fleet-wide | **15–60 rows**; the remaining ~1,250 stay 1.0 and **that is NORM-13's backlog, to be recorded and not healed** |
| PR12 | `scenes` `snapshot` rows with NULL `footprint` | **still 6,156** — NORM-7's deferred pass is not this run's job, and insert-only means a re-encountered row is untouched |

### 7a. Insert-only, checked rather than assumed

Three `enriched` `scenes` rows that a sweep selection re-encounters will be
queried before and after and compared field by field. **Predicted:
byte-identical** — same `item_id`, `footprint`, `resolution_m` (including a
noisy NORM-11 spelling if one is in the sample), `provenance`, `fetched_at`.
`ON CONFLICT DO NOTHING` means a present row is left exactly as it is.

## 8. Stop conditions

The gate between pilot and remainder, and the conditions under which nothing
is scored and the run stops:

* **PP3 / PR3 > 0** — a duplicate `(collection, item_id)` means the key the
  whole design rests on is not a key. Investigate, do not re-run.
* **Parity ≠ 0 in either direction**, for any cause that is not one of the
  designed divergences `PREDICTION-STEP2.md` §5 lists (mosaics as references,
  NAIP resolution by row age, `selected_by` on change only, four provenance
  values).
* **A duplicate `(parcel_id, source, group_key)` with no `failed` ledger row
  for that exact group** — a duplicate with a clean ledger is silent
  reconciliation failure, the ADR's change condition.
* **`scenes` count falls.**
* **Dangling `mosaic_scene_ids` > 0.**
* **A ledger `failed` row this session cannot explain.**

A stop is an outcome, not a failure: captures and scoring are committed
either way, and no sweep batch is re-run on a client-side interruption
without first reading the remote process and the database (NORM-8 / F5).

## 9. What this predicts nothing about

Step 3. No read path moves in this session, no read site is touched, and
nothing in production reads `scenes` or `parcel_scenes` after this sweep any
more than before it. Step 3 is unblocked by a clean battery, not performed by
one.

---

## Observed — the pilot, 2026-08-29

*(appended after the pilot ran; the half above is unedited)*

The pilot enqueued 03:50:36 → 03:52:29Z (113 s): **30 queued, 0 skipped, exit
0, 0 unreached**. The last of the 30 requests reached terminal at 03:59:29Z.
The battery ran 03:59:42Z. Captures: `step2-pilot-sweep.txt`,
`step2-pilot-battery.txt`, `step2-pilot-worker-log.txt`.

**Outcome: every safety property held, and the sweep wrote nothing at all.**

### Pilot scorecard

| # | Quantity | Predicted | Observed | Verdict |
|---|---|---|---|---|
| PP1 | Parity, pilot, both directions | 0 / 0 | **0 / 0** (also 0 / 0 fleet-wide) | confirmed |
| PP2 | Duplicate `(parcel_id, source, group_key)` | 0 | **0** | confirmed |
| PP3 | Duplicate `(collection, item_id)` | 0 | **0** | confirmed |
| PP4 | Dangling `mosaic_scene_ids` | 0 | **0** | confirmed |
| PP5 | New `scenes` rows | 20–75 | **0** — `scenes` still 6,661, 0 `'selection'` | **falsified** |
| PP6 | `scenes` rows deleted | 0 | **0** | confirmed |
| PP7 | `provenance = 'mosaic_url'` | 0 | **0** | confirmed |
| PP8 | Pilot `parcel_scenes` with `selected_by` | 20–75 | **0** — NULL on all 2,075 | **falsified** |
| PP9 | Pilot NAIP `resolution_m` no longer uniformly 1.0 | 3–12 real gsd | **1.0 on all 227** | **falsified** |
| PP10 | Pilot `imagery_snapshots` count | 2,075 ± 3; landsat exactly 1,290 | **2,075 exactly; landsat exactly 1,290** | confirmed |
| PP11 | Pilot `parcel_scenes` = pilot `imagery_snapshots` | equal | **2,075 = 2,075** | confirmed |
| PP12 | Ledger `failed` rows in the window | 0 | **0** | confirmed |
| §6b | G4 request-path signing storm | expected | **0 signals of any kind** | **falsified** |

### The three falsifications are one fact, and it is not a defect

**Zero rows were inserted into `imagery_snapshots` in the pilot window** —
the query returns an empty result for every source. The pipeline re-selected
*exactly* the item already served for all 2,075 groups, so no `scenes` row
was needed (PP5), no `parcel_scenes` row was inserted or changed and
therefore none took a `selected_by` (PP8), and no NAIP row was inserted and
therefore none carried a real `gsd` (PP9). One upstream fact, three
downstream zeroes.

The forecast that failed was the **churn estimate**, not the dual-write.
§5b's anchor — 36 pilot rows for a one-day gap on 08-27, 101 on 08-26 — did
not carry over to a 32-hour gap: the observed value is 0, below a band whose
floor was 20. The mechanism §5b named (Landsat/Sentinel-2 validation walks
re-signing assets live, so a fallback taken last time may not be taken this
time) cuts both ways, and this run took no fallbacks: the worker log carries
**zero** signing warnings, zero rate-limit events and zero retries across all
90 STAC searches. A quiet Planetary Computer produces a stable selection.
**The prediction is not edited to fit.**

### What the pilot did and did not prove

**Proved, at production scale for the first time:** a full pipeline run over
30 parcels leaves `imagery_snapshots` and `parcel_scenes` in exact agreement
— 0 violations in both directions over 2,075 groups, and 0 / 0 fleet-wide
over 12,884 — with no duplicate group, no duplicate `(collection, item_id)`,
and no dangling reference. Landsat is exactly conserved at 1,290 = 30 × 43.

**Did not prove: the insert path, at all.** It was executed zero times.
NORM-12 predicted this branch would dominate; it did not merely dominate, it
was total. The pilot is therefore indistinguishable, from the tables alone,
from a run in which the dual-write never executed — and there is no log line
to separate the two, because `reconcile_source_snapshots` emits none.
`efa4c63` is the deployed SHA and contains `9526805`, which is the only
positive evidence available. **This is stated here, before the remainder
runs, so it cannot be softened afterwards.**

### Insert-only, checked rather than assumed (§7a, taken early)

The full 505-row `enriched` population was fingerprinted rather than a
3-row sample:

* count **505**, all with a non-NULL footprint;
* `max(fetched_at)` = **2026-08-27 17:52:36Z** — before the sweep;
* `resolution_m` distribution **identical to the pre-sweep baseline in all
  eleven buckets**, including each of the eight NORM-11 noise spellings at
  its exact count (0.5999999999999901 ×2, and one each of
  0.5999999999999975 / 0.5999999999999994 / 0.6000000000000011 /
  0.6000000000000012 / 0.600000000000007 / 0.6000000000000097);
* row digest `d17c4eee14c2155cb4e4528b265f87ab` over every column, recorded
  here as the baseline for the remainder sweep.

A single rewritten row would move the digest and, for the noisy eight, the
distribution. Neither moved.

### Mosaics, checked the strong way

**613 of 613** mosaic references resolve to a `scenes` row whose `cog_url` is
a member of the same group's `additional_cog_urls` array — the two
representations name the same tiles, not merely the same count. This is the
check `STEP2-REPORT.md` §3f ran over 176 local references, now run over all
613 production references. 576 rows carry a mosaic on each side; 578 distinct
tiles, 505 `enriched` + 73 `snapshot`, unchanged. **§5a's derivation holds:
no mosaic tile needed inserting.**

### The ledger for the window (NORM-3)

2,343 rows: landsat 1,290 `ok`; naip 227 `ok` / 270 `absent`/`no_scenes` / 6
`suppressed`/`naip_no_point_coverage` / **7 `indeterminate`**; sentinel2 357
`ok` / 3 `absent`/`all_cloud_filtered`; usgs_topo 177 `ok` / 4 `absent` / **2
`indeterminate`**. **Zero `failed` rows.** 30 requests `complete`, 120 tasks
`complete`, none in flight.

The 9 `indeterminate` rows are on the three tier-A parcels chosen for exactly
this reason and are the two known truncation classes, unchanged from the
08-26 and 08-27 sweeps: `fe065e2d` NAIP item cap on 2010/2019/2020/2022/
2024/2025/2026, `9c35ceb0` and `e513188c` TNM row cap. They are markers that
an absent group *may* be truncation, not failures, and under the absent-group
rule they cost no row in either table. **So the pilot's parity zero rests on
zero unretried failures** — the NORM-3 reading, and it is clean.

The 6 `suppressed` rows are the NAIP no-covering-tile gate firing, matched by
6 `Suppressing imagery year with no covering tile` warnings in the worker
log. Under the absent-group rule they delete nothing — HEAL-SCORECARD §3's
prospective-only finding, observed again and unchanged.

### G4 did not fire, and the pilot cannot clear the remainder

Predicted: the 2026-08-12 signature (41 SAS rate-limit give-ups, 17 band
signing failures, 115 Titiler 500s). **Observed: none.** Across 621 captured
worker lines the only 9 warnings are the 6 suppressions and the 3 truncation
caps; there is no `rate-limited`, no `Band signing failed`, no Titiler 500,
and the API stream is quiet.

Log coverage is complete rather than sampled, unlike the geometry heal's
~50%: the continuous stream was started **before** the sweep and carries all
30 `fetch_imagery_timeline task started` and all 30 `Timeline request
finished` events, 90 STAC searches (3 sources × 30) and 30 topo searches.

§6b said in advance that a quiet pilot does not clear the remainder, and that
holds: the pilot is a sixth of the fleet and ran 30 requests through an
admission cap of 25.

### Gate

**PASS.** Parity 0 in both directions, duplicates 0 of both kinds, dangling
references 0, and every ledger row that is not `ok` is named and explained
with zero `failed` among them. Proceeding to the remaining 159 parcels.
