# Geometry-class blast radius

Read-only investigation, 2026-08-11. No code changed, nothing re-queued.

**Method.** For every `imagery_snapshots` row, refetched the STAC item by
`stac_collection` + `stac_item_id` from the Planetary Computer items endpoint,
parsed `item["geometry"]` with shapely, and tested parcel point-in-footprint
against the `item["bbox"]` test the pipeline actually ran
(`stac.py:309-329`). Edge distance computed by projecting footprint and point
to the point's UTM zone. 1,239 distinct items fetched at concurrency 6 with
429 backoff.

**Two premise corrections up front:**

1. **Redis holds no STAC item cache.** The only cache is SAS signatures, keyed
   `sas:{url}` with a 600 s TTL (`stac.py:287`, `_SAS_CACHE_TTL`). Every
   geometry fetch hit the API. Cost was 1,239 requests, not the "dozens" the
   brief anticipated — still fine, but worth knowing before anyone plans a
   larger sweep.
2. **`usgs_topo` is not assessable and is excluded.** Its 260 rows carry
   `stac_collection = 'usgs-historical-topo'`, sourced from the USGS TNM API
   (`usgs_topo.py:19`), not PC STAC. There is no STAC item to fetch. The
   denominator throughout is the 2,897 PC-backed rows, not 3,157.

---

## 1. Class size

| Source | Rows | Assessable | Unfetchable | Geometry FAIL | % of assessable | Parcels hit |
|---|---|---|---|---|---|---|
| landsat | 1,761 | 1,761 | 0 | **29** | 1.6% | 8 / 41 |
| sentinel2 | 836 | 836 | 0 | **4** | 0.5% | 2 / 41 |
| naip | 300 | 283 | 17 | 2 | 0.7% | 2 / 41 |
| **total** | **2,897** | **2,880** | **17** | **35** | **1.2%** | — |

**No item lacked a `geometry` field.** The separate count the brief asked for is
zero — all three PC collections populate it. The only unassessable rows are 17
NAIP snapshots (6 distinct items, 6 parcels, years 2012–2021) where PC returned
**HTTP 403** on the item endpoint. Those are reported as unassessed, not as
passes. Note 403 rather than 404 — the items likely still exist but are
access-restricted at the item endpoint; this is not evidence of broken assets.

### The bbox-vs-geometry agreement matrix is the finding

| Source | bbox=Y, geom=Y | bbox=Y, geom=N | bbox=N, geom=N | bbox=N, geom=Y |
|---|---|---|---|---|
| landsat | 1,732 | **29** | 0 | 0 |
| sentinel2 | 832 | **4** | 0 | 0 |
| naip | 281 | 0 | 2 | 0 |

Read the columns:

- **`bbox=Y, geom=N` is the defect, exactly.** All 33 Landsat + S2 failures sit
  here. The bbox test admitted a granule whose real footprint excludes the
  address, precisely as diagnosed.
- **`bbox=N, geom=Y` is empty, and structurally must be.** A STAC bbox is the
  envelope of its geometry, so bbox ⊇ footprint always. **The bbox filter can
  never reject a genuinely-covering scene — it can only admit non-covering
  ones.** This is load-bearing for the Ocean NJ verdict below.
- **NAIP's 2 failures are `bbox=N`** — the bbox test would have caught them.
  They are *not* this defect. See §4.

### Landsat and S2 are both real, and Landsat dominates

Landsat is 3× the S2 rate and 4× the parcel spread. Both use identical spatial
code (`timeline.py:276-288`); the difference is exposure — 43 years of WRS-2
scenes vs 11 years of MGRS quarters, and rotated parallelogram footprints whose
envelopes overstate coverage more than MGRS squares do. **The remediation is not
S2-specific.**

### Every failure is recoverable, at near-zero cloud cost

For all 33 Landsat/S2 failures I re-ran the exact production search (1500 m
bbox, same year, `max_items=20`, `eo:cloud_cover < 40`) and tested every
returned item for true point containment:

- **33 of 33 had a covering item already in the same 20-item pool** (typically
  13–19 of 20 covered the point). Zero unrecoverable.
- The cloud-cover penalty for choosing correctly is negligible — usually under
  1 percentage point (e.g. RiNo 1987: chosen 0.0% non-covering vs 1.0%
  covering).
- In one case the correct choice is *strictly better*: **Rodanthe 2015-07-26,
  chosen cloud 25.0%, best covering 1.0%.** The pipeline picked a scene that is
  both cloudier and non-covering, from a thin 4-item pool.

**This is the single most important number in the report.** The pool was never
the problem. The filter was. A geometry-aware point test fixes 100% of the
observed class with no measurable imagery-quality regression — and needs no
change to the query, the cap, or the ranking.

---

## 2. Ocean NJ (parcel `e0cb3db9`) — cannot be measured here, but the structure decides it

> **SUPERSEDED — measured against production; see the ADDENDUM at the end of
> this file.** Result: 0 geometry failures across all 64 rows, 8 missing Landsat
> years (not 20), all 8 recoverable. The parcel is unblocked; the gate moves to
> the parcel-wide script. The coastal-risk prediction below was wrong and is
> corrected in the addendum.

**Blocked on data, not on reasoning.** Parcel `e0cb3db9` does not exist in the
local database (41 parcels, all Denver/DC/NYC/CA dev + featured addresses), and
`e0cb3db9` appears nowhere in the repo — not in `docs/audits/`, not in
`scripts/`, not in DEVELOPMENT.md. It is production-only. I did not open a
tunnel to production to query it; that is a live-system action and I would want
explicit sign-off first. **Say the word and I'll run the same audit against prod
read-only.**

What *is* answerable read-only is the discriminator, and it is decisive.

### The two failure modes produce different, non-overlapping evidence

- **The signing 429 produces a MISSING year.** `validate_landsat_item`
  (`stac.py:675-713`) collapses five distinct causes into one `False`: missing
  red band, signing failure (the 429 path, `stac.py:691-697`), HEAD ≥ 400, and
  HEAD transport error. `validate_landsat_selection` then walks same-year
  fallbacks serially and, if all fail, drops the year — `"No valid Landsat item
  for year %d; skipping"` (`stac.py:779`). Result: **no row.**
- **The geometry defect produces a WRONG-GRANULE year.** It never deletes
  anything. Per the matrix above, the bbox filter is over-permissive only; it
  cannot exclude a covering scene. And `validate_landsat_item` checks asset
  *reachability*, never spatial coverage — a sliver granule's red band HEADs
  200 like any other. Result: **a row that is present and serving the wrong
  footprint.**

**Verdict: Ocean NJ's sparse Landsat — its *missing* years — is purely the
signing incident. The geometry defect is structurally incapable of deleting a
year.** That is not an inference from logs; it follows from bbox ⊇ geometry,
confirmed empirically by the empty `bbox=N, geom=Y` column across 2,880 rows.

Two riders that stop this being a clean "not indeterminate":

1. **Its surviving years are unassessed.** Ocean NJ is coastal and
   boundary-adjacent — the exact profile that produced failures at Rodanthe
   (also coastal, 2 S2 failures) and Hudson Yards (5 Landsat failures). Whether
   its ~23 surviving Landsat years serve correct footprints is **unknown and
   untestable from here.** The verdict is "missing years = signing, definitively;
   present years = unknown."
2. **The geometry defect plausibly amplified the burst.** The over-permissive
   filter inflates the candidate pool with non-covering granules, and the
   fallback loop signs candidates one at a time (`stac.py:762-776`) on top of
   the `asyncio.gather` over all ~43 years (`stac.py:744-746`) that produced the
   21-in-4-seconds burst. More admitted candidates means more signing calls
   under pressure. Contributory, not causal.

### Requeue implication: hold this parcel's heal until the fix lands

`scripts/revalidate_landsat.py` re-queues **every parcel with Landsat imagery**
(`revalidate_landsat.py:43-49`) and re-runs full selection — search, spatial
filter, cloud argmin. Running it today re-selects through the unfixed bbox
filter. For a coastal, boundary-adjacent parcel that is the highest-risk
configuration in the dataset.

**Yes — the requeue for this parcel should wait for the fix.** Healing now
restores the 20 lost years using the broken filter, and any that land on
non-covering granules would need a second heal to correct. Given the fix is
provably selection-changing (33/33 recoverable), healing twice is the default
outcome, not a tail risk.

---

## 3. Featured locations — 4 of 6 are currently serving wrong-footprint granules

| Featured location | Rows | Failures | Detail |
|---|---|---|---|
| **RiNo Art District** | 63 | **6** | landsat 1987, 1988, 2007, 2008, 2010, 2011 |
| **Hudson Yards** | 74 | **5** | landsat 2013, 2016, 2017, 2019, 2020 |
| **Green Valley Ranch** | 67 | **2** | landsat 2006, 2012 |
| **Rodanthe, Outer Banks** | 83 | **2** | sentinel2 2015, 2017 |
| Navy Yard / Capitol Riverfront | 75 | 0 | clean |
| Stapleton / Central Park | 63 | 0 | clean |

**This is the urgency-setting fact, and it is worse than the 1.2% aggregate
suggests.** The aggregate is diluted by 41 mostly-inland dev parcels. On the six
pages that are the public demo surface, **four are affected and 15 timeline
cards are serving a granule whose footprint excludes the location the page is
about.** RiNo's failures include the two oldest Landsat cards in the timeline
(1987, 1988) — the ones that carry the "how it has changed" narrative.

Marginal cases on featured pages: Hudson Yards NAIP 2023 sits 124 m inside its
footprint edge.

---

## 4. NAIP — flagging loudly, but it is a *different* defect

NAIP came back clean of the bbox-vs-geometry defect exactly as predicted: **zero
`bbox=Y, geom=N`.** Its near-axis-aligned quarter-quads make bbox ≈ footprint.

But it has 2 genuine failures, and they are worth the flag:

**Both 350 5th Ave parcels (Empire State Building), NAIP 2023.** The primary
tile is `nj_m_4007309_sw` — a New Jersey quad. I checked whether the mosaic
rescues it: it does not. The one additional tile (`nj_m_4007424_ne`) also
excludes the point. **The entire served 2023 mosaic is New Jersey imagery for a
Midtown Manhattan address.**

Cause is *not* misselection. I re-ran the 2023 NAIP search over that bbox: PC
returns exactly 3 items, all New Jersey quads, **none containing the point.**
There is no covering 2023 NAIP tile in the collection. This is a **data gap**.

The defect is that nothing suppresses the card. NAIP's path uses
`filter_items_intersecting_bbox` against the viewport (`timeline.py:277`) and a
greedy scorer optimizing *viewport area*, never point containment — so when a
year has no covering tile, it serves the nearest neighbours and labels the card
2023. **NAIP needs a point-coverage guard, not a geometry fix.** Distinct
remedy, tracked separately below.

Incidentally this vindicates the mosaic design elsewhere: Hudson Yards' 2023
mosaic *is* rescued by its second tile (`nj_m_4007416_se` contains the point).

---

## 5. The edge-proximity tail

Passing rows within N metres of their footprint edge:

| Source | <200 m | <500 m | <1000 m |
|---|---|---|---|
| landsat | 1 (0.1%) | 2 (0.1%) | 7 (0.4%) |
| sentinel2 | 5 (0.6%) | 14 (1.7%) | 45 (5.4%) |
| naip | 6 (2.1%) | 44 (15.7%) | 121 (43.1%) |

**The tail is thin where it matters and thick where it doesn't.**

- **Landsat: no tail.** 7 rows within 1 km of a 185 km scene edge. Its 1.6%
  failure rate is not the leading edge of a larger latent class — the failures
  are parcels genuinely near scene boundaries, and everything else is deep
  inside. Fixing the 29 fixes Landsat.
- **Sentinel-2: a modest real tail.** 45 rows (5.4%) within 1 km. Four parcels
  recur — notably 16th Street Mall, Denver, with four S2 cards sitting **77–78 m**
  from a footprint edge. Those pass today and are one granule-geometry revision
  or reprojection wobble from flipping. S2's true exposure is nearer 1% than
  0.5%.
- **NAIP's 43% is an artefact, not a signal.** Quarter-quads are ~6 km, so a
  1 km edge buffer covers most of the tile's area. Ignore this row; the <200 m
  figure (2.1%) is the meaningful one, and mosaicking is designed to absorb it.

---

## 6. Remedies, ranked by the numbers

### R1 — Read `item["geometry"]` in the point filter (root fix). Do this one.

Replace the bbox comparison in `filter_items_containing_point` (`stac.py:319-328`)
with a shapely `contains` against `item["geometry"]`, falling back to the
current bbox test when geometry is absent.

- **Fixes:** 33 of 33 observed failures — the entire measured class — across
  both affected sources, at a cloud-cover cost under ~1pp and occasionally
  negative (Rodanthe 2015 improves 25.0% → 1.0%).
- **Doesn't fix:** NAIP (different path entirely, `bbox=N` failures); partial /
  sliver granules whose *footprint polygon* contains the point but whose valid
  pixels do not — the polygon is the granule extent, not a validity mask;
  the 17 rows behind 403s.
- **Cost:** the covering item is already in the pool in 100% of cases, so this
  is a filter change with no query, cap, or ranking change. Lowest-risk fix
  available.
- **Note:** shapely is already imported in `stac.py:16-17` (used only for the
  UTM buffer today), so no new dependency.

### R2 — NAIP point-coverage guard (distinct defect, real user impact)

After `select_naip_items`, verify the selected group's footprints collectively
contain the point; if not, either drop the year or mark the card as
non-covering.

- **Fixes:** the Empire State Building 2023 case — currently serving New Jersey
  for Midtown. Prevents a whole class of "wrong place entirely" cards wherever
  NAIP has a year gap.
- **Doesn't fix:** anything in the Landsat/S2 class.
- **Judgement call for you:** dropping the year loses a timeline card; keeping
  it labelled is more honest but needs UI. Worth deciding deliberately rather
  than defaulting.

### R3 — S2 relaxed-threshold fallback mirroring Landsat's (the half-fixed twin)

S2 has no equivalent of `validate_landsat_selection`'s fallback walk
(`stac.py:761-779`) and no cloud-threshold relaxation; a quarter where
everything is ≥40% cloud silently vanishes.

- **Worth doing on principle** — it is a real asymmetry between twins, and
  Rodanthe 2015's 4-item pool shows thin quarters exist.
- **But the numbers do not make it urgent:** it addresses *missing* quarters,
  and this audit measured *wrong* granules. It fixes none of the 33. Deliberately
  ranked below R1/R2 on evidence.

### R4 — `bbox` → `intersects` in the STAC query

- **The numbers do not justify this.** The hypothesis was that the 20-item cap
  truncates the covering tile before we see it. **It does not happen:** in all
  33 failures the covering item was in the returned pool (13–19 of 20). And the
  one truncation-shaped case (NAIP 2023) turned out to be genuine data absence —
  the covering tile does not exist in PC.
- Still directionally correct (a point predicate is what we mean), but it is
  cleanup, not remediation. **Do not bundle it with R1** — it changes result
  sets and would muddy attribution of the deletion wave.

### R5 — Coverage-aware ranking

- **Not justified.** Its premise is that we must choose between covering
  candidates on coverage quality; with 13–19 covering candidates per pool and
  sub-1pp cloud spread, R1's binary containment test already lands on a good
  scene. Revisit only if post-fix spot checks show covering-but-marginal picks.

---

## 7. The deletion wave, predicted

`reconcile_source_snapshots` (`imagery.py:579-665`) deletes rows whose
`stac_item_id` is not in the new selection **and** whose capture date falls in a
group this run actually re-selected. Absent groups are deliberately left alone
(`imagery.py:608-611`), so this is bounded, not a wipe.

**Predicted fix-attributable deletions, local dataset: 33 rows** — 29 Landsat,
4 S2 — 1.1% of the 2,880 assessable, across 10 of 41 parcels. Each is a
one-for-one replacement: the wrong granule deleted, the covering one inserted in
the same year/quarter group. **No timeline should lose a card.**

Two caveats on that number:

- **Actual churn will exceed 33.** A re-run also re-selects every other group,
  and PC's catalogue has changed since these rows were written (new items, cloud
  metadata revisions, the 6 items now 403ing). Expect additional replacements
  unrelated to this fix. 33 is the fix-attributable floor, not the total.
- **Production will scale differently, and probably worse.** 1.2% here reflects
  41 mostly-inland dev parcels. The featured set — 4 of 6 affected — is the
  better predictor for a real user population, and coastal/boundary-adjacent
  addresses like Ocean NJ are over-represented among the reports that prompted
  this. Do not plan capacity against 1.2%.

---

## 8. Sequencing flag

**Land R1 before any requeue or heal work runs.**

The class is small in percentage terms but it *is* selection-changing —
provably, in 33 of 33 cases. `revalidate_landsat.py` re-queues every
Landsat-bearing parcel and re-runs full selection. Run it pre-fix and it
re-selects through the broken filter; run it post-fix and the same pass heals
the signing gaps *and* corrects the footprints, with reconciliation cleaning up
in one deletion wave instead of two.

That applies with particular force to Ocean NJ, whose profile (coastal,
boundary-adjacent, 20 years to restore) is where a pre-fix heal is most likely
to write rows that need rewriting.

**Heal once, not twice.**

---

## Appendix A — Failing pairs (Landsat + S2, all 33)

`chosen` = cloud cover of the served non-covering granule; `best cov.` = lowest
cloud cover among covering candidates in the same pool.

| Source | Date | Parcel | Location | Pool | Covering | chosen | best cov. |
|---|---|---|---|---|---|---|---|
| landsat | 1987-10-21 | c78a1019 | **RiNo Art District** | 20 | 14 | 0.0 | 1.0 |
| landsat | 1988-10-23 | c78a1019 | **RiNo Art District** | 20 | 16 | 0.0 | 5.0 |
| landsat | 2007-09-26 | c78a1019 | **RiNo Art District** | 20 | 18 | 0.0 | 1.0 |
| landsat | 2008-10-30 | c78a1019 | **RiNo Art District** | 20 | 19 | 0.0 | 1.0 |
| landsat | 2010-11-05 | c78a1019 | **RiNo Art District** | 20 | 17 | 0.0 | 1.0 |
| landsat | 2011-10-23 | c78a1019 | **RiNo Art District** | 20 | 17 | 0.0 | 2.0 |
| landsat | 2013-08-20 | 5c27245c | **Hudson Yards** | 20 | 18 | 4.08 | 1.0 |
| landsat | 2016-10-15 | 5c27245c | **Hudson Yards** | 20 | 17 | 0.01 | 0.43 |
| landsat | 2017-10-18 | 5c27245c | **Hudson Yards** | 20 | 16 | 0.01 | 0.05 |
| landsat | 2019-10-24 | 5c27245c | **Hudson Yards** | 20 | 16 | 0.01 | 0.04 |
| landsat | 2020-07-06 | 5c27245c | **Hudson Yards** | 20 | 15 | 1.44 | 1.58 |
| landsat | 2006-08-29 | c8ecf010 | **Green Valley Ranch** | 20 | 15 | 1.0 | 1.0 |
| landsat | 2012-10-08 | c8ecf010 | **Green Valley Ranch** | 20 | 15 | 0.0 | 1.0 |
| sentinel2 | 2015-07-26 | 14518754 | **Rodanthe, Outer Banks** | 4 | 3 | 25.04 | 1.01 |
| sentinel2 | 2017-09-28 | 14518754 | **Rodanthe, Outer Banks** | 19 | 16 | 0.07 | 0.04 |
| landsat | 2013-08-20 | d2a82e6b | 350 5th Ave, NY | 20 | 18 | 4.08 | 1.0 |
| landsat | 2016-10-15 | d2a82e6b | 350 5th Ave, NY | 20 | 17 | 0.01 | 0.43 |
| landsat | 2017-10-18 | d2a82e6b | 350 5th Ave, NY | 20 | 16 | 0.01 | 0.05 |
| landsat | 2019-10-24 | d2a82e6b | 350 5th Ave, NY | 20 | 16 | 0.01 | 0.04 |
| landsat | 2020-07-06 | d2a82e6b | 350 5th Ave, NY | 20 | 15 | 1.44 | 1.58 |
| landsat | 2013-08-20 | 81b2d663 | 350 5th Ave, NY | 20 | 18 | 4.08 | 1.0 |
| landsat | 2016-10-15 | 81b2d663 | 350 5th Ave, NY | 20 | 17 | 0.01 | 0.43 |
| landsat | 2017-10-18 | 81b2d663 | 350 5th Ave, NY | 20 | 16 | 0.01 | 0.05 |
| landsat | 2019-10-24 | 81b2d663 | 350 5th Ave, NY | 20 | 16 | 0.01 | 0.04 |
| landsat | 2020-07-06 | 81b2d663 | 350 5th Ave, NY | 20 | 16 | 1.44 | 1.58 |
| landsat | 2019-09-12 | d1879711 | 9311 S Cimarron Rd, Las Vegas | 20 | 16 | 0.0 | 0.03 |
| landsat | 2022-06-08 | d1879711 | 9311 S Cimarron Rd, Las Vegas | 20 | 19 | 0.0 | 0.02 |
| landsat | 2026-06-11 | d1879711 | 9311 S Cimarron Rd, Las Vegas | 20 | 19 | 0.0 | 0.06 |
| landsat | 2021-11-07 | e032a469 | 12804 Emerson St, Thornton CO | 20 | 19 | 0.1 | 0.19 |
| landsat | 2006-08-29 | 2b0bdcba | 4800 Telluride St, Denver | 20 | 15 | 1.0 | 1.0 |
| landsat | 2012-10-08 | 2b0bdcba | 4800 Telluride St, Denver | 20 | 13 | 0.0 | 1.0 |
| sentinel2 | 2016-11-10 | ebe2e829 | 1361 Leyner Dr, Erie CO | 20 | 18 | 0.30 | 0.39 |
| sentinel2 | 2017-11-25 | ebe2e829 | 1361 Leyner Dr, Erie CO | 20 | 19 | 0.17 | 0.26 |

## Appendix B — NAIP failures (distinct cause)

| Date | Parcel | Location | Primary tile | Mosaic rescues? |
|---|---|---|---|---|
| 2023-08-20 | 81b2d663 | 350 5th Ave, NY | `nj_m_4007309_sw` | **No** — extra tile also excludes |
| 2023-08-20 | d2a82e6b | 350 5th Ave, NY | `nj_m_4007309_sw` | **No** — extra tile also excludes |

PC has no covering 2023 NAIP tile for this location (3 items returned, all NJ).

## Appendix C — Unassessable (17 rows, HTTP 403)

6 distinct items across 6 parcels, years 2012–2021:
`ut_m_4011118_sw_12_1_20160627_20161017`, `ut_m_4011125_sw_12_060_20211105`,
`va_m_3807708_se_18_060_20181019_20190212`, `va_m_3807708_se_18_1_20120511_20120709`,
`va_m_3807708_se_18_1_20140927_20141126`, `va_m_3807708_se_18_1_20160718_20160928`.
All NAIP. Counted as unassessed, not as passes.

## Appendix D — Marginal tail (<200 m inside footprint edge)

| Source | Date | Distance | Location |
|---|---|---|---|
| sentinel2 | 2015-08-28 | 77.3 m | 16th Street Mall, Denver |
| sentinel2 | 2020-12-22 | 77.7 m | 16th Street Mall, Denver |
| sentinel2 | 2022-12-17 | 77.7 m | 16th Street Mall, Denver |
| sentinel2 | 2021-12-19 | 78.4 m | 16th Street Mall, Denver |
| naip | 2010-07-31 | 80.9 m | 350 5th Ave, NY |
| landsat | 2012-11-19 | 88.9 m | 9311 S Cimarron Rd, Las Vegas |
| naip | 2023-08-20 | 124.2 m | **Hudson Yards** |
| naip | 2013-08-02 | 136.5 m | 350 5th Ave, NY |
| naip | 2015-07-29 | 136.5 m | 350 5th Ave, NY |
| naip | 2017-07-19 | 136.5 m | 350 5th Ave, NY |
| naip | 2010-07-31 | 141.6 m | 350 5th Ave, NY |
| sentinel2 | 2021-09-21 | 162.8 m | 1 Infinite Loop, Cupertino |

---

# ADDENDUM — Ocean NJ measured against production (authorized, read-only)

Run 2026-08-11, `fly ssh console` against `log0s-plotline-api` / `plotline-worker`.
SELECT-only queries plus STAC GETs. No writes, no queueing. **This supersedes the
"cannot be measured" status in §2.**

**Parcel `e0cb3db9-a7d5-4cf5-9c72-9be8f9a968c2` — "141 rainbow drive brick"**
(Brick Township, Ocean County NJ), 40.061291, -74.096304 — Barnegat Bay.

## Result: zero geometry failures. Completely clean.

| Source | Rows | Geometry FAIL | Marginal (<1 km from edge) |
|---|---|---|---|
| landsat | 35 | **0** | 0 |
| sentinel2 | 22 | **0** | 0 |
| naip | 7 | **0** | 7 (191–469 m) |
| **total** | **64** | **0** | 7 |

All 64 PC-backed rows fetched successfully — no 403s, no missing geometry.

**The coastal-risk hypothesis was wrong for this parcel, and worth correcting
explicitly.** §2 predicted its profile was "the highest-risk configuration in the
dataset." It is not. Not one Landsat or S2 row sits within even 1 km of its
footprint edge — the parcel sits deep inside WRS-2 paths 013032/014032 and well
inside its MGRS tile. **Coastal is not the same as tile-boundary-adjacent**, and
this is the counterexample: the failures in §1 clustered on Manhattan and Denver
addresses that happen to fall near scene edges, not on the coast. Only NAIP shows
edge proximity (191–469 m), which is unremarkable for ~6 km quarter-quads and is
what mosaicking exists to absorb.

## Damage is purely the signing incident — confirmed, not inferred

The structural argument in §2 holds and is now empirically confirmed on the
parcel itself: bbox ⊇ geometry means the filter cannot delete a year, and here it
demonstrably deleted none — every surviving row is correct.

**But the gap is 8 years, not 20:** missing 1986, 1987, 1988, 1989, 1994, 1996,
2016, 2023 out of 43 (1984–2026); 35 present.

The state is fresher than the brief assumed. There is exactly **one**
`timeline_requests` row (created 2026-08-12 00:45:28 UTC, `complete` at
01:00:13 UTC), and **all 35 Landsat rows were written in that single run** at
01:00 UTC — roughly two hours before this audit. The "20 of 43" in
`docs/audits/2026-08-second-audit/STATUS.md` describes an earlier state that this
run already partially recovered.

**That run still predates the throttle.** `a536d07` was committed
2026-08-12T00:52:13 UTC and reached the worker in **v42 (~01:59 UTC)**; the run
executed on **worker v41, the Aug 4 image**. So the 8 gaps are pre-throttle
signing losses, and the fix was never in play for them. The throttle is live now
(worker v43, API v51 — `_get_sign_semaphore` and `_retry_after_seconds` both
present on both machines).

## All 8 missing years are recoverable right now

Re-ran the production search per missing year (1500 m bbox, `max_items=20`,
`eo:cloud_cover < 40`) and called the real `validate_landsat_item` on the
best covering non-LE07 candidate:

| Year | Pool | Covering | Best candidate | Cloud | Validates |
|---|---|---|---|---|---|
| 1986 | 14 | 14 | `LT05_L2SP_013032_19860328_02_T1` | 1.0% | ✅ |
| 1987 | 18 | 18 | `LT05_L2SP_013032_19871212_02_T1` | 2.0% | ✅ |
| 1988 | 20 | 20 | `LT05_L2SP_013032_19881027_02_T1` | 1.0% | ✅ |
| 1989 | 19 | 19 | `LT05_L2SP_014032_19890701_02_T1` | 1.0% | ✅ |
| 1994 | 16 | 16 | `LT05_L2SP_014032_19941104_02_T1` | 4.0% | ✅ |
| 1996 | 19 | 19 | `LT05_L2SP_014032_19961024_02_T1` | 1.0% | ✅ |
| 2016 | 20 | 20 | `LC08_L2SP_014032_20161015_02_T1` | 0.43% | ✅ |
| 2023 | 20 | 20 | `LC08_L2SP_013032_20231028_02_T1` | 0.09% | ✅ |

**8 of 8 recoverable**, all covering the point, all non-LE07, all low cloud, all
passing live signing + HEAD on the now-throttled code path. Every pool was
100% covering — further confirmation this parcel has no boundary exposure.

## Verdict on sequencing: this parcel is unblocked

**Its heal is purely the signing requeue. It does not need the geometry fix
deployed first.** With zero geometry failures, zero Landsat/S2 edge proximity,
and 100%-covering candidate pools, re-selection here cannot land on a
non-covering granule. The §2 recommendation to gate this parcel on the fix was
correct given what was known then; the measurement removes the basis for it.

**One carry-over, and it is about the tool, not the parcel.**
`revalidate_landsat.py` re-queues *every* Landsat-bearing parcel
(`revalidate_landsat.py:43-49`). Running it globally pre-fix still re-selects
the 8 affected parcels in §1 through the broken filter. So:

- **Heal Ocean NJ individually now** — safe, and recovers 8 years on the
  throttled worker.
- **Keep the global `revalidate_landsat.py` run gated on R1.** The gate belongs
  on the parcel-wide script, not on this parcel.

If there is no per-parcel heal path today, the simplest correct move is to land
R1 first and run the sweep once — which is the §8 recommendation unchanged.
