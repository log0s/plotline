# NORM-31 — the write-time rule and the heal, built locally

2026-08-29. Local session, **no production access taken and none needed**.
Commit `3849fec` — the rule, the heal and the tests. This file and the
STATUS.md NORM-31 update ship in the commit that adds them.

**What NORM-31 is.** Two of the 5,387 footprints the production snapshot heal
wrote fail `ST_IsValid` — both Sentinel-2 L2A, both self-intersecting, both
published that way by the Planetary Computer and stored faithfully
(`SNAPSHOT-ENRICH-PROD-REPORT-3.md` §6e). Every layer passed them because every
layer asked the same narrow question: `geometry(POLYGON,4326)` validates type,
`extract_footprint_wkt`'s branch tested type, and EP12 predicted type. None
asked about topology.

**What this session built.** The write-time rule, at the one function every
write path already goes through; the heal, as a mode of the existing script;
and the validity check, added to the invariant set that predictions carry.
**The two-row production heal is not run here** — that is a later authorized
session, and its expected queue is **2**.

---

## 1. The rule — `normalize_footprint`

`backend/app/services/stac.py:1564`, with the NORM-31 comment at its definition
(`:1519`).

```python
def normalize_footprint(geometry, *, item_id) -> tuple[BaseGeometry | None, str | None]
```

* A **valid** geometry is returned **untouched** — the same object, not an
  equal one. Repair must not perturb good data, and nothing is logged.
* An **invalid** one is repaired with shapely's `make_valid` (the same GEOS
  call as PostGIS's `ST_MakeValid`; run Python-side because the parse already
  is) and the repair is **reported**: one structlog event
  `footprint_repaired_invalid_geometry` per occurrence, carrying
  `stac_item_id`, `invalidity_reason` (shapely's `explain_validity`),
  `repair_type`, `polygon_parts` and `footprint_repair_discarded_area`.

**One function, both paths — with a deviation from the prompt's letter, stated
plainly.** The prompt asked for the function "next to `normalize_resolution_m`"
in the shared layer. `normalize_resolution_m` is in
`backend/app/services/imagery.py:1157`; footprint extraction is in
`stac.py`, and **`extract_footprint_wkt` is already the single function all
three write paths call** — the step-2 dual-write
(`imagery.py:1219`, inside `SelectedScene.from_stac_item`),
`scripts/enrich_snapshot_scenes.py:392` and
`scripts/enrich_synthesized_scenes.py:358`. Putting the repair anywhere else
would have created a second place for a geometry rule to live, which is the
shape NORM-10's extraction rules out. So `normalize_footprint` sits adjacent to
`extract_footprint_wkt` in `stac.py`, and `extract_footprint_wkt` delegates to
it. The adjacency requirement is met against the function that actually shares
the paths, not against the one that shares a naming convention.

**A consequence worth naming:** `extract_footprint_wkt` can now return a
footprint *and* a complaint together, where before a complaint always meant
NULL. All three callers said "footprint left NULL" on any complaint, and that
sentence is now sometimes false — so all three were corrected to say which of
the two actually happened (`imagery.py:1219-1237`,
`enrich_snapshot_scenes.py:392-406`, `enrich_synthesized_scenes.py:392-399`).

---

## 2. The MultiPolygon decision, and the measurement behind it

`make_valid` over a self-intersecting ring can return a Polygon, a MultiPolygon
(a bowtie splits into two lobes) or a GeometryCollection (a polygon plus the
zero-area lineal spike the self-intersection pinched off). The column is
`geometry(POLYGON,4326)`, so the rule cannot be left to the column to decide by
crashing.

**First, what the two real rows actually do.** Both items were fetched from the
public Planetary Computer catalogue — an upstream read, not a production one —
and repaired under the container's own shapely:

| item | raw | `explain_validity` | `make_valid` result | area before → after |
|---|---|---|---|---|
| `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747` | Polygon, 28 pts, invalid | `Self-intersection[-71.00403 41.90664113]` | GeometryCollection(Polygon, **zero-area LineString**) | 0.7654244991823305 → 0.7654244991823305 |
| `S2B_MSIL2A_20190602T162839_R083_T16TEK_20201005T212018` | Polygon, 22 pts, invalid | `Self-intersection[-86.75983 39.91487413]` | GeometryCollection(Polygon, **zero-area LineString**) | 1.0387539307012852 → 1.038753930701285 |

**Neither production row is a multipart case at all.** Each repairs to exactly
one polygon of identical area, plus a spike with no area. The reasons and
coordinates match STATUS.md NORM-31's record of the production rows exactly, so
the fixture is the same geometry the database holds.

**The rule, and the argument.**

1. **Lineal and puntal members are dropped without comment.** They are
   artifacts of the repair, not coverage. This is the branch both real rows
   take, and it loses nothing: area is preserved to 1e-12 relative.
2. **Where more than one polygon survives, store the largest by area and
   report the discarded fraction** — in the complaint, and in the log event's
   `footprint_repair_discarded_area`.

The argument for (2) is what the footprint is *for*. The serving question is
point-in-footprint: `filter_items_containing_point`
(`backend/app/services/stac.py:768`) asks exactly it in Python today, and ADR
rule 4's promise that "the next geometry audit is a query over `scenes`, not a
refetch" means the column must answer it in SQL. A largest-part footprint can
only ever **under**-claim coverage — false negatives (a parcel in a discarded
lobe reads as uncovered) and never false positives (claiming coverage the image
does not have). A false positive is the defect the 2026-08 geometry audit
measured 33 rows of; a false negative is one scene fewer in a timeline. The
asymmetry is the whole decision.

**The alternative, costed rather than dismissed.** Widening `scenes.footprint`
to `MULTIPOLYGON` (or `GEOMETRY`) loses nothing at all, and is strictly better
on coverage. Against it: it is a production schema migration; it breaks the
"all footprints are `ST_Polygon`" invariant every prediction file in this arc
carries (`PREDICTION-SNAPSHOT-ENRICH.md:682`, `:985`, and five more); and in
the population that actually exists it buys **zero** area, because both rows
repair to a single polygon.

> **Flagged, and written into the code comment at
> `backend/app/services/stac.py:1519`:** if
> `footprint_repair_discarded_area` ever appears in the logs with a fraction
> worth naming, **widen the column — do not tune the rule.** The largest-part
> rule is correct for a population where the discard is zero, and it is a
> silent loss of coverage in one where it is not.

A third member of the repair — no polygon at all (a fully degenerate ring
repairs to a LineString) — returns None with a complaint, which leaves the
footprint NULL and the row in the fill queue, the pre-existing behaviour for an
unstorable geometry.

---

## 3. The heal — `--revalidate-footprints`

A mode of `scripts/enrich_snapshot_scenes.py` (`:752`), not a new script. Same
fetch layer, same pacing, same batching, same commit cadence, same report
mechanics, same exit-code contract. Two things change:

**The queue** (`:200`, `:206`):

```sql
footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> 'usgs_topo'
```

**Not scoped to `provenance = 'snapshot'`,** unlike the fill queue, and that is
deliberate: the dual-write stores `item["geometry"]` through the same function
this pass does, so a `'selection'` row can carry exactly the same
self-intersection. Scoping a sweep to the provenance the finding happened to be
observed in is how one class becomes two. `usgs_topo` stays excluded for the
existing reason — `usgs-historical-topo` is not a Planetary Computer
collection, so there is no item to GET — and topo footprints are NULL anyway,
so the exclusion is free.

**The write set:** footprint only. Those rows already have a bbox and a
resolution some earlier pass decided; rewriting them under a geometry sweep
would be churn against columns this finding does not name, and it would make
the sweep's diff unreadable. Disagreements are still *reported*.

**Resume is the queue re-derivation, unchanged** — a repaired footprint is
valid, so the row is gone from the next read, exactly as a filled footprint
leaves the fill queue. No new resume state exists.

**Queue 0 is a clean run**, in both dry-run and `--execute` form: no fetches, a
report written, exit `0`. That is the post-heal state and it is the local
state.

**PostGIS is required and says so.** `load_queue(mode=revalidate)` raises
rather than returning an empty queue on a non-PostGIS session
(`enrich_snapshot_scenes.py:221`): `ST_IsValid` has no SQLite answer worth
inventing, and a sweep that silently returns nothing would read as "clean".

**Expected production queue: 2.** Both rows named in STATUS.md NORM-31.

---

## 4. Detection joins the invariant set

The invariant every prediction in this arc carried — "footprints all
`ST_Polygon`, none equal to its own bbox" — is the one that passed two
self-intersecting rows. It now asks the third question, as one query
(`enrich_snapshot_scenes.py:275`, `FOOTPRINT_INVARIANT_SQL`), run in the
script's own post-run verification in **both** modes and **both** dry run and
execute, and printed into the report:

```sql
SELECT count(*) FILTER (WHERE GeometryType(footprint) <> 'POLYGON') AS not_polygon,
       count(*) FILTER (WHERE NOT ST_IsValid(footprint))            AS invalid,
       count(*) FILTER (WHERE ST_Equals(footprint, ST_Envelope(footprint))) AS equals_bbox
  FROM scenes WHERE footprint IS NOT NULL;
```

All three must be `0`. **This is the query for future prediction files** — one
place, so a prediction, a post-run check and the script cannot drift into
asking different questions, which is how EP12 came to be literally true and
substantively false.

**One correction found while writing it.** The natural spelling of "equal to
its own bbox" is `footprint ~= ST_Envelope(footprint)`, and it is wrong: since
PostGIS 2.4 the `~=` operator compares **bounding boxes**, so that predicate is
true for every row on earth. It reported `2 of 2` and then `1 of 1` in the
tests before `ST_Equals` replaced it. A check of that shape reports 100% and
means nothing — this finding's own mistake, arriving in a different column, and
noted at the query (`:267`).

---

## 5. Tests — delete-the-fix, six clauses

`backend/tests/test_footprint_validity.py`, fixture
`backend/tests/fixtures/norm31_invalid_footprint.json` — **one of the two real
production items**, `S2B_MSIL2A_20181226T153639_R111_T19TCG_20201008T131747`,
geometry byte-for-byte as PC publishes it. A synthetic bowtie carries the
multipart rule, because the real rows do not reach that branch.

| Test | Asserts |
|---|---|
| `test_the_real_norm31_footprint_is_repaired_to_a_valid_geometry` | invalid in, valid `Polygon` out, area preserved, no complaint |
| `test_the_repaired_footprint_still_contains_the_points_the_raw_ring_did` | **the serving property**: every one of 100+ grid points the raw ring encloses is contained by the repair |
| `test_a_valid_footprint_is_returned_untouched` | identity, geometric equality, **and no log event** |
| `test_the_repair_is_reported_with_the_reason` | one event, item id, `Self-intersection` reason, parts and discard |
| `test_a_bowtie_stores_the_largest_part_and_reports_the_discard` | the multipart rule of §2 and its reported fraction |
| `test_a_repair_with_no_polygon_left_stores_nothing_and_says_so` | None + complaint, not a crash |
| `test_extract_footprint_wkt_hands_back_a_valid_polygon_for_the_real_item` | the shared function, end to end |
| `test_revalidate_mode_refuses_a_session_without_postgis` | no faked SQLite answer |
| `test_the_revalidate_queue_finds_invalid_rows_and_ignores_valid_ones` | seeded invalid rows of two provenances found; valid and topo not |
| `test_the_invariant_query_counts_the_invalid_rows` | the §4 query, against PostGIS |
| `test_revalidate_run_repairs_a_seeded_invalid_row` | **a real heal end to end**: refetch, repair, rewrite, row now `ST_IsValid`, bbox and resolution untouched, queue re-derives to empty |
| `test_an_empty_revalidate_queue_is_a_clean_run` | queue 0: 0 fetches, report written, exit code 0 |

**Two method points worth keeping.**

* **The serving property is asserted against arithmetic, not against shapely.**
  The reference answer for "what did the raw geometry cover" is an even-odd ray
  cast over the raw ring, written out in the test. Asking shapely what the raw
  geometry contains would be asking the library under test to grade its own
  repair — and its answer over an invalid geometry is exactly the thing that is
  undefined.
* **The valid-passthrough test needed strengthening, and this was found by
  running the delete-the-fix, not by reading it.** With only `equals_exact`,
  removing the `is_valid` early return **did not** turn the test red:
  `make_valid` over an already-valid polygon returns an equal polygon. The
  clause was false as first written. The test now asserts object identity and
  the absence of a log event, and the clause is red.

**Delete-the-fix, performed, one clause at a time:**

| Clause removed | Tests turned red |
|---|---|
| the `is_valid` early return (repair unconditionally) | 1 |
| the `make_valid` call (store the input as-is) | 6 |
| the `_polygonal_parts` filter (keep every member) | 3 |
| `NOT ST_IsValid(...)` in the revalidate queue predicate | 4 |
| the `invalid` column in `FOOTPRINT_INVARIANT_SQL` | (same run as above) |

**SQLite/PostGIS split, per NORM-29 — the limit is stated, not faked.**
`normalize_footprint` is pure shapely and runs anywhere. Everything that needs
`ST_IsValid` runs against a real Postgres in a throwaway database, skips
without `TEST_POSTGRES_URL`, and **fails rather than skips under `CI`**, which
sets it (`.github/workflows/deploy.yml:171`).

**Suite: 763 passed / 3 skipped** with `TEST_POSTGRES_URL` set; 754 passed / 12
skipped without it (the 4 PostGIS tests in this file, plus 8 pre-existing). `ruff check`,
`ruff format --check` and `mypy` clean over `app/` and `tests/`. The five ruff
findings in `scripts/seed_featured.py` are pre-existing and untouched.

---

## 6. The local run — a queue-0 exercise, not a heal

**Local has no invalid rows.** Checked before assuming, against the local
container's Postgres:

```
scenes                                          1342
footprint IS NOT NULL                           1194
footprint IS NOT NULL AND NOT ST_IsValid(...)      0
```

So the local run is **the queue-0 exercise**, and it is reported as such — no
local heal happened, because there was nothing local to heal.

**Dry run**, `20:22:08Z`:

```
queue (footprint IS NOT NULL AND NOT ST_IsValid(footprint), source <> 'usgs_topo'): 0 row(s)
Rows fetched: 0. STAC requests issued: 0.
```

`.rc` = **`0`**. Report at `/tmp/norm31-local-dryrun.md`, headed
`# Footprint revalidation — dry run`. Post-run invariants:
`not_polygon 0 / equals_bbox 0 / invalid 0`.

**`--execute` form**, same queue: 0 rows, 0 fetches, `.rc` = **`0`**, report
written.

What this run does and does not prove: it exercises the queue predicate against
real PostGIS, the mode's reporting, the invariant check and the exit-code
contract on an empty queue. **It exercises no repair** — the repair path on
real production geometry is exercised by
`test_revalidate_run_repairs_a_seeded_invalid_row`, which seeds the actual
production geometry into a Postgres table and heals it. Reporting the queue-0
run as evidence that the heal works would be the mistake NORM-29's corollary
names.

---

## 7. State left behind

* **The rule is in the code, on every write path, and not deployed.** `3849fec`
  is committed to `main` and **not pushed**. Until it deploys, the dual-write
  and both enrichment scripts in production still store `item["geometry"]`
  unvalidated, so the class can still grow by one row per new
  self-intersecting scene.
* **The heal is built and has never run against production.** Expected
  production queue: **2**, both rows named in STATUS.md NORM-31. A later
  session runs it under a written authorization naming the worker SHA.
* **The two production rows are still invalid.** Nothing in this session
  touched production, by prompt and by check.
* **Open question this session did not settle:** whether a
  `CHECK (ST_IsValid(footprint))` constraint should follow the heal. It would
  make the class impossible to land again rather than merely repaired on the
  way in, and it needs the two rows fixed first. Recorded in STATUS.md rather
  than decided here.
