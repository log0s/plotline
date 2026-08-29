# Step 3 — the serving reads cut over to `scenes` / `parcel_scenes`

Session of 2026-08-29. ADR 0001's third migration step: the five **serving**
read sites move off `imagery_snapshots` and onto `parcel_scenes` joined to
`scenes`, proven by a field-by-field parity harness run while both paths were
alive, and then the old reads are deleted.

**Built and verified locally. Not deployed.** Production still serves from
`imagery_snapshots`; nothing in production reads either new table today,
before or after this batch. §9 has the sequence a production session should
follow, and it is not "deploy HEAD".

**Outcome.** 3,082 rows compared on both paths across 45 parcels and 12,560
comparisons: **eleven of twelve fields exactly equal on every row**,
`additional_cog_urls` included; the old-id/new-id mapping a **bijection** over
12,373 pairs; **12 divergences, all `resolution_m`, all three rows of one
parcel**, with a mechanism that is the ADR's own opening cost rather than a
defect in this batch (F1 / NORM-18). Local suite 711 passed / 7 skipped, ruff
and mypy clean, and all five surfaces smoked against the running stack with
the old reads gone.

This batch's commits:

| Commit | Unit |
|---|---|
| `0181c54` | the five new reads, **alongside** the old ones, plus `scripts/compare_read_paths.py` |
| `dad8502` | `PREDICTION-STEP3.md` — before the scored parity run |
| `160e7ba` | the scored run's capture and the prediction's Observed half |
| `33d952a` | the shape freeze captured from the old path, and the cutover tests |
| `b1acf9a` | **the cutover** — old serving reads deleted, five sites rewired, step-4 measurement hook |
| *(this batch)* | ADR amendment, STATUS.md, this report |

---

## 1. Scope — the five sites, and the one that is not a site

The cutover's scope definition is `STEP1-REPORT.md` §7, the read-site
inventory carried forward verbatim from the pre-flight `VERIFICATION.md` item
3. Six production-code sites appear there; five are serving reads and moved:

| # | Was | Is | Consumers |
|---|---|---|---|
| 1 | `get_imagery_snapshots` | `get_served_scenes` | `api/v1/imagery.py` listing, `services/preview_renderer.py` |
| 2 | `get_snapshot_by_id` | `get_served_scene_by_id` | tile proxy, `/warmup`, the Titiler `/stac` callback |
| 3 | `count_imagery_snapshots` | `count_served_scenes` | `tasks/timeline.py` `items_found`, ×2 |
| 4 | `featured._snapshot_ids_for_parcels` | `imagery.served_scene_bounds` | `/featured`, `/featured/{slug}` |
| 5 | `revalidate_landsat.landsat_parcels` | `imagery.parcels_serving_source` | the fleet sweep's parcel selection |

**The sixth did not move, deliberately.** `reconcile_source_snapshots`' own
existing-rows pull still reads `imagery_snapshots`, because dual-write
continues until step 4 and the reconciler legitimately diffs this run's
selection against what the old table holds. So the delete-the-fix standard
this batch meets is **"no serving path touches `imagery_snapshots`"**, not
"no code touches it" — the latter is step 4's. That distinction is written
into `tests/test_read_cutover.py`'s module docstring so step 4's session
inherits it precisely rather than reading this report.

## 2. Design decisions

### 2a. No feature flag

Taken as given by the prompt and confirmed on inspection. The cutover is a
code change and its rollback is reverting the deploy — CI deploys on push to
main and `/api/v1/health` reports the running sha, both exercised repeatedly
in this arc. A flag would have to keep the old serving reads alive to have
anything to fall back to, which is exactly the thing the delete-the-fix
standard forbids: there would be nothing to delete and no test that could
fail.

### 2b. The served id changed, and that is the cutover's one changed value

`parcel_scenes.id` is a fresh UUID per row — the backfill minted one per
backfilled row, `_upsert_parcel_scene` mints one per insert — so it is never
equal to the `imagery_snapshots.id` for the same served period. The API now
hands out `parcel_scenes.id` at `/parcels/{id}/imagery` and `/featured`, and
resolves the same id space at `/imagery/{id}/tiles`, `/warmup` and `/stac`.

Both ends move in one commit, so the ids stay internally consistent, and the
harness proved the substitution is well-defined: **12,373 id pairs recorded
across four sites resolved to exactly 3,082 distinct old ids and 3,082
distinct new ids**, with no inconsistency and no collision. Two costs are
accepted rather than avoided:

* a browser holding a rendered page across the deploy has stale ids and 404s
  on tile requests until it refetches the listing — one page load;
* every `stac:{snapshot_id}` Redis key is cold on the first request after,
  which costs one refetch of an immutable STAC item, not an error.

Nothing durable stores a snapshot id: `featured_locations` computes its
earliest/latest at request time, and the frontend reads ids out of the
responses it just fetched.

### 2c. Still raw SQL, and the AsEWKB dodge is inherited on purpose

The old `get_imagery_snapshots` used raw SQL to avoid GeoAlchemy2 emitting
`AsEWKB` on `bbox`. The new read does the same thing for the same reason, and
the reason is now stronger: `scenes` carries **two** `Geometry` columns
(`footprint` and `bbox`), so `select(Scene)` would make GeoAlchemy2 emit
`ST_AsEWKB` on a value the response wants four floats of, and the SQLite test
database has no such function at all. `_bbox_select_sql("s.bbox")` selects
`ST_XMin`/`ST_YMin`/`ST_XMax`/`ST_YMax` and `_bbox_select_sql_sqlite()` hands
back NULLs, so one query text runs on both databases. The helper gained a
`column` parameter (it was hardcoded to an unaliased `bbox`) and lost its
default, since there is exactly one caller now.

`footprint` is never selected. It is not in the response contract, most rows
still have none (NORM-7's deferred pass), and selecting it would reintroduce
the geometry decode this dodge exists to avoid.

### 2d. `additional_cog_urls` is reconstructed in Python, not in SQL

One extra query per listing gathers `SELECT id, cog_url FROM scenes WHERE id
IN (…)` for every id any row's `mosaic_scene_ids` names, and the per-row list
is then assembled **in the stored array's order**.

Keeping the order in SQL needs `unnest(...) WITH ORDINALITY`, which the
SQLite test database cannot express, so the SQL route would have meant two
dialect branches for the one property most worth testing. In Python it is one
code path, order preservation is a visible loop, and
`test_mosaic_urls_come_back_in_mosaic_scene_ids_order` can assert it on
either database — it reverses the stored array and requires the reconstructed
URLs to reverse with it, which a set-based resolution passes by accident in
the forward direction and fails here.

Cost: one query per listing page that has any mosaic at all, batched across
every row. Locally, the Hudson Yards NAIP listing resolves 10 mosaic rows and
15 tiles in that one query.

**A reference that resolves to no `scenes` row is logged as an error and
dropped from that row's list.** `mosaic_scene_ids` is a `UUID[]` with no
foreign key, so a dangling entry is representable even though neither
database has ever held one (0 dangling across 613 production references,
`STEP2-PROD-REPORT.md` §5.1). Refusing the whole listing would turn one
missing tile into a dead timeline; the primary COG still renders and the gap
is the same one an unsignable mosaic component already leaves at
`api/v1/imagery.py:260-266`. The primary itself cannot dangle —
`parcel_scenes.scene_id` has a real foreign key.

### 2e. The listing's sort gained a tie-break

Both queries say `capture_date ASC`. The old one left rows sharing a date in
whatever order the plan produced, and the new one would have done the same —
the harness's first run found **20 parcels** where the two arrangements
differed. Two *sources* can land on one capture date; within a source a tie
is impossible, because `group_key` is derived from `capture_date`, so one
date is one group is one row.

The new read orders by `capture_date ASC, source ASC`, which is fully
deterministic. This is a behaviour change and is recorded as one: it does not
break an old contract, because there was no old order to break — the
endpoint's documented promise is "sorted chronologically" and both shapes
keep it. The harness classifies these separately (`row_order_within_date`,
counted and not a divergence) precisely so the distinction is auditable
rather than asserted; after the tie-break, `row_order` divergences are 0 and
same-date reorderings are 20.

### 2f. `ImagerySnapshotRow` became `ServedSceneRow`

The field set is unchanged — that is the frozen contract — but the name is
now a claim about where the row comes from, and it would have been false. A
name that only ever appears in code, describing a source it no longer has, is
the shape AA1 records the cost of. The rename touches two application files
and their tests and changes no behaviour;
`tests/fixtures/step3_served_shape.json` is what actually holds the shape
still.

`created_at` stays `None`. It has *always* been `None` on this dataclass —
the old query selected the column and never assigned it — and redefining it
as `parcel_scenes.selected_at` would silently change a field's meaning inside
a commit whose whole claim is that the shape did not change.

### 2g. `served_scene_bounds` moved into the service layer

The featured-cards query was raw SQL in the route handler. Rewriting it
anyway, it went to `app/services/imagery.py`, where CLAUDE.md says business
logic lives, and where the harness could call the same function the endpoint
calls.

## 3. The parity harness

`scripts/compare_read_paths.py`, committed at `0181c54` **before** any old
read was deleted, because it needs both.

* **Row identity.** Rows are joined on `(source, group_key)`, the natural key
  both shapes produce — the old side derives `group_key` from `capture_date`
  through `encode_group_key`, the same function `parcel_scenes` stored its
  value with (ADR rule 2). `id` is excluded from field equality and checked
  as a bijection instead.
* **Coverage.** Every parcel; the listing unfiltered, once per source, and
  twice over a date window; every row fetched individually by id on both
  sides; the per-source counts; the featured bounds compared as the rows they
  name rather than as id strings; and `revalidate_landsat`'s parcel set.
  Twelve fields per row pair.
* **A population check the per-row sites cannot give.** `_item_fact_
  disagreement` counts, per item fact, the served rows whose two copies
  disagree — the same question as a population, which is the form F1 needs.
* **Read-only, and provably.** It sets `default_transaction_read_only = on`
  and **commits that**, because the setting applies to transactions that
  *start* after it; leaving it inside SQLAlchemy's already-open implicit
  transaction would have set the flag and then run every query under the one
  transaction it does not cover. Verified directly: an `UPDATE … WHERE false`
  after the set raises `ReadOnlySqlTransaction`.

## 4. Parity scorecard

Full detail in `PREDICTION-STEP3.md`, whose prediction half was committed
before the scored run and has not been edited; capture in
`step3-parity-local.md`.

**19 of 19 predicted quantities confirmed. No unpredicted divergence class.**

| | |
|---|---|
| parcels | 45 |
| rows, old path / new path | 3,082 / 3,082 |
| row and count comparisons | 12,560 |
| id pairs → distinct old / new ids | 12,373 → 3,082 / 3,082 |
| fields per row pair | 12 |
| **divergences** | **12** — all `resolution_m`, 3 rows × 4 sites |
| `count`, `featured`, `revalidate_landsat`, `row_order` | 0 each |
| `missing_from_*`, `*_duplicate_group`, `id_map_*`, `row_absent` | 0 each |
| same-date reorderings (not a divergence, §2e) | 20 |
| item-fact disagreement table | one field: `resolution_m`, 3 rows / 3 scenes |

**The prediction was not blind, and says so in its own §0.** The harness had
already been run twice during development before the prediction was written,
so what this scores is that the committed code behaves as the debugged code
did and that no class was missed — not foresight. That is a real weakening of
the evidence and it is recorded at the top of the prediction rather than in a
footnote. §8 deviation 1.

## 5. The step-4 measurement hook

ADR step 4 retires `imagery_snapshots` "after one cooling period with no reads
(measured, not assumed — log every read; expect zero)". Two instruments were
built, because the prompt's mechanism is necessary and not sufficient.

**`log_imagery_snapshots_read(caller, …)`** emits a structlog
`imagery_snapshots_read` event at every remaining application read. After
this cutover there is exactly one caller,
`reconcile_source_snapshots.existing_rows`. **Cost:** one line per (parcel,
source) reconcile — ~4 per parcel-run, ~756 in a 189-parcel fleet sweep,
against the ~3,300 lines such a sweep already emits (`STEP2-PROD-REPORT.md`
§5.6). That is the whole cost; it is not on the request path at all, since no
serving read touches the table any more.

**What it cannot do, stated so step 4 does not over-read it.** Grepping for
the event with a `caller` other than the reconciler catches a new
*instrumented* reader. A read that does not call the function does not log,
so the measurement is only as complete as the discipline maintaining it —
which is precisely the assumption "expect zero" must not rest on.

**`scripts/snapshot_reads.py`** is the half that closes it: a read-only
reading of `pg_stat_user_tables` for `imagery_snapshots`, `parcel_scenes` and
`scenes`, taken at the start and end of the cooling period and differenced.
It counts every scan by anything, instrumented or not, at the cost of naming
none of them — the complement of the log. Two traps are written into its
docstring rather than left to be rediscovered: the counters are incremented
by writes too (the reconciler's `DELETE ... WHERE id` costs an `idx_scan`),
so a nonzero delta means "something touched this table" and the log is what
splits it; and the counters reset, so the script compares `stats_reset` and
says the deltas are incomparable rather than reporting a negative number.

Taken together they are the measurement: the counters say how many accesses
happened, the log says how many were the reconciler, and the difference is
the population the cooling period is looking for. Deviation §8.3.

## 6. Tests, to the delete-the-fix standard

`backend/tests/test_read_cutover.py`, ten tests. The fixture seeds rows that
exist **on one side only, in both directions** — a served period with no
`imagery_snapshots` row, and an `imagery_snapshots` row no `parcel_scenes`
row names — so a read that had quietly kept its old source returns the wrong
*set*, not a subtly wrong field.

Mutations applied and reverted, each run against the whole module:

| Mutation | Result |
|---|---|
| All five reads restored to their pre-cutover bodies and aliased onto the new names | **8 of 9 site tests fail** |
| `mosaic_scene_ids` resolved without preserving array order (`sorted(ids)`) | **the order test fails, alone** |
| One field dropped from the row mapping (`resolution_m=None`) | **the shape freeze fails, alone** |
| `log_imagery_snapshots_read` call removed | **its own test fails, alone** |
| *(none)* | 9 pass, then 10 with the hook test |

The one test that survives the first mutation is
`test_a_row_with_no_mosaic_has_no_additional_cog_urls`, which is an auxiliary
assertion about the empty case and true of both paths. Recorded rather than
strengthened: making it fail would mean asserting something it is not about.

**The shape freeze.** `tests/fixtures/step3_served_shape.json` was captured
from `get_imagery_snapshots` at `33d952a` — the commit before the deletion,
which is the only moment it could be — by
`test_step3_shape_freeze_capture.py`, which asserted the old path still
produced it and was deleted by the cutover. `test_read_cutover.py` now
asserts the new path against the same file. `id` is tokenised, since it is
the field the cutover is supposed to change; the other eleven are frozen
verbatim. One documented normalisation: on the test database
`imagery_snapshots.additional_cog_urls` is TEXT rather than TEXT[], so the
mirror stores the list as JSON and the capture decodes it — a SQLite storage
artifact, not a difference between the read paths, and the paths' agreement
on that field was measured on PostgreSQL over 148 mosaic rows.

**Four existing tests were themselves findings.** F3.

## 7. Findings

### F1 — the cutover makes the surviving copy of a disagreeing item fact the served one, and insert-only makes it the oldest

**New. Open, unfixed. NORM-18. The most useful thing this batch produced.**

The prompt's prior was zero divergences, on the strength of step 2's
both-sides fidelity work. That prior is right about everything the write path
controls and wrong about one thing it does not.

`scenes` is insert-only (`_ensure_scene`) and `upsert_imagery_snapshot`'s
`ON CONFLICT DO UPDATE` never touches `resolution_m` (NORM-13). So the two
shapes agree perfectly about any row they were *written together* from one
`SelectedScene` — which is what step 2 proved over 12,884 production groups —
and they can still disagree about a row written at two different times,
because **neither table has any mechanism for refreshing an item fact it
already holds**.

The local database has three such rows, and their history is the ADR's
opening paragraph in miniature. NAIP item
`md_m_3807708_se_18_030_20230901_20231018` is served by four parcels. Three
carry `resolution_m = 1.0`, written 2026-03 under the pre-NORM-9 constant;
one carries the item's real `0.3`, written 2026-08-28 after the fix. The
step-1 backfill collapsed those four copies into **one** `scenes` row and its
newest-`created_at` tie-break took a 2026-03 row, so the surviving copy says
1.0. Insert-only has kept it there since.

**After the cutover all four parcels serve 1.0** — three unchanged, and the
fourth changed from 0.3 m to the source constant, visible as the `1m res`
chip at `frontend/src/components/MapView.tsx:298-301`. That is normalization
working exactly as designed (one copy of an item fact) and picking, in this
instance, the wrong copy.

**It does not block the cutover, and the reason is a production measurement
rather than an argument.** The disagreement needs a NAIP row rewritten after
the NORM-9 deploy against a `scenes` row written before it, and production
has none: on 2026-08-29 all 1,305 NAIP `imagery_snapshots` rows and all 1,102
NAIP `provenance = 'snapshot'` `scenes` rows carried 1.0
(`STEP2-PROD-REPORT.md` §9). Every copy of that fact already agrees there.

**What to do about it, in order of durability.** (a) The item-fact refresh
mechanism ADR rule 4 promises and nothing implements — a scene's facts
corrected in one row. (b) A one-off heal that rewrites `scenes.resolution_m`
from the item for the affected rows. (c) Nothing, and accept that the served
value is whichever copy was written first. This batch does (c) by default
because step 3 is a read change and cannot write; the decision belongs to
whoever owns NORM-13.

**The population is measurable in one command before any of that**, which is
the point of building it: `scripts/compare_read_paths.py`'s item-fact table,
or the query behind it, run against production at `160e7ba`.

### F2 — the served id space moved, and nothing durable was holding the old one

**New. Accepted, with the two costs stated.** §2b. Recorded as a finding
rather than only a design note because "the API's ids all changed" is the
kind of fact that reads as an incident if it is discovered rather than
expected. NORM-19.

### F3 — four tests were proving their fixture's table, not the behaviour

**New. Resolved in the same batch. Method finding, and it generalizes.**

The cutover broke 23 tests. Nineteen were mechanical (an import of a deleted
function, a `patch()` naming it). **Four were findings:**

* `tests/test_featured.py::_seed` seeded `imagery_snapshots` and the test
  asserted `/featured` returns earliest/latest snapshot ids. After the
  cutover the endpoint correctly returns no bounds — the test had been
  proving that *the featured query reads the table the fixture wrote*, which
  is not the behaviour anyone wanted asserted.
* `tests/test_imagery.py::_insert_snapshot` and `_insert_topo_snapshot` seed
  the rows behind sixteen tile-proxy, `/warmup` and `/stac` tests, and did so
  through `upsert_imagery_snapshot`, reading the id back out of
  `get_imagery_snapshots`. Every one of those tests was resolving an id no
  serving read can resolve any more.
* `test_get_imagery_snapshots_returns_sorted` and `_source_filter` tested a
  function that no longer exists.

**The general shape:** a test that seeds the storage a read *used to* use
keeps passing while the read is where it was, and says nothing about the read
once it moves. Only the tests that seed through a shared helper survive such
a move, which is why the fix is `conftest.seed_served_scene` rather than four
local edits. The two tests of the deleted function are deleted, with a
comment at the site naming their replacements in `test_read_cutover.py` so
the coverage is traceable rather than merely gone.

### F4 — the harness's own docstring names the wrong step for its death

**Minor, and left uncorrected in place per the frozen-record rule.**
`scripts/compare_read_paths.py`'s docstring at `0181c54` says the script
"dies with the old reads in step 4". The old reads die in **step 3** — this
batch — and the script was deleted here, because it imports two functions the
cutover removes and leaving it would have put broken code in the tree. Step 4
retires the *table*, not the reads. The docstring is a frozen artifact of the
commit that introduced it; this sentence is the correction.

## 8. Deviations from the prompt

1. **The prediction was written after two development runs of the harness,
   not before any run.** The prompt's item 4 puts it before the local parity
   run. `PREDICTION-STEP3.md` §0 states this at the top of the file, says
   what is lost (the blind test of the zero prior) and what the scored run
   still establishes, and the prediction was still committed before the
   scored run and never edited. The two divergence classes are reported as
   findings on their own merits rather than as a prediction's catch.

2. **The prediction is not zero, and §4 of it argues why.** The prompt's
   strong prior was zero. F1 is the mechanism that makes it 12; the reasoning
   was written down before the scored run rather than offered after it.

3. **A second measurement instrument was built.** The prompt asked for the
   lightweight version — a structlog event naming the caller — and invited a
   materially better measurement. The event alone cannot see an
   uninstrumented reader, which is the failure mode "expect zero" is most
   exposed to, so `scripts/snapshot_reads.py` reads the database's own
   counters as the complement. ~140 lines, read-only, no production access
   used. §5.

4. **`scripts/compare_read_paths.py` was deleted in the cutover commit, not
   left for step 4.** F4.

5. **The listing's sort gained a `source` tie-break.** Not asked for; §2e has
   the reasoning, and it is what takes `row_order` divergences from 20
   parcels to 0 without inventing a contract.

6. **`ImagerySnapshotRow` was renamed and `_snapshot_ids_for_parcels` moved
   into the service layer.** Neither is a behaviour change; §2f and §2g.

7. **`conftest.seed_served_scene` was added** rather than fixing four test
   sites locally. F3's reasoning.

## 9. What this does not do — and the sequence production needs

* **Nothing is deployed.** Production serves from `imagery_snapshots` and
  reads neither new table. A mitigation that isn't running isn't mitigating,
  and none of this is running.
* **No write path changed.** `reconcile_source_snapshots` is byte-identical
  apart from the added log line; dual-write continues; `imagery_snapshots` is
  not altered and nothing deletes from it.
* **No API contract changed.** No new response field, no changed field
  meaning, no frontend change. The one changed *value* is the id (§2b).
* **NORM-17's qualification is carried forward unchanged:** step 2's insert
  path has been exercised exactly **twice** in production. "Cutover verified"
  is a statement about which table the reads come from, and is **not**
  evidence that the write path is battle-tested at fleet scale.

**The production sequence, and it is not "deploy HEAD".** The harness needs
both paths alive, so the only way to run it against production is to deploy
the both-paths commit first:

1. Deploy **`160e7ba`** (both read paths alive, nothing rewired). Gate on the
   health sha and `GH_SHA` on every machine of both apps, as step 2 did.
2. Run `python scripts/compare_read_paths.py --out /tmp/parity.md` inside the
   API machine — read-only, detached or file-output per NORM-8 — and retrieve
   it. **Write a production prediction before it**, and expect F1's
   `resolution_m` population to be **0** there on today's numbers; a nonzero
   count is the finding, and its size is what decides whether NORM-18 needs a
   heal before the cutover rather than after.
3. Only then deploy **`b1acf9a`** or later. Rollback is redeploying the
   previous sha.

Step 4 does not run in the same batch as step 3, and its cooling period
starts at (3), measured with both instruments in §5.

## 10. State of the record

* ADR `0001` gains a dated amendment for step 3: the no-flag decision, the id
  substitution, the mosaic reconstruction, the tie-break, and F1's mechanism.
  Nothing above the amendment line is edited.
* STATUS.md's normalization section gains **NORM-18** and **NORM-19**, and
  NORM-1 gains a step-3 addendum that says built-not-deployed in those words
  and carries NORM-17's qualification verbatim.
* `PREDICTION-STEP3.md` carries both halves, the prediction committed before
  the run it scores, unedited — with §0's disclosure that it was not blind.
