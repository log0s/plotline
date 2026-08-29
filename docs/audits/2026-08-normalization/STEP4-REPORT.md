# Step 4 — `imagery_snapshots` retired, built locally

Session of 2026-08-29. ADR 0001's fourth and final migration step, built as
**two deploys**; neither is deployed and nothing here touched production.

* **Deploy-1, the code cutover** — `329a8a6`, `41f7e76`, `03867c4`.
* **Deploy-2, the drop** — `cb088f8`. Ships alone, gated on the cooling span.
* **Prediction and scoring** — `87bf025` (before the sweep), scoring commit
  alongside this file.

**No production access of any kind was used or attempted.** Every number below
comes from the local PostGIS database or from the test suite, and each is
followed by the file, commit or run it came from.

---

## 1. The ordering, and why it amends §6d

`NORM31-PROD-REPORT.md` §6d lists four conditions for step 4. The plan of
record amends their **ordering** — deliberately, and this is the batch's
central structural decision.

§6d assumed one deploy: the table stays wired to the reconciler through the
cooling period, and the period's question is "is the reconciler the *only*
reader". That question needs condition 1's "`idx_scan` still moving *only* by
the reconciler's own pulls, accounted for row by row" — an accounting exercise
over a nonzero number, and one §6d itself found hard: the step-3 reading's +15
`seq_scan` had to be explained by arithmetic (193,260 ÷ 12,884 = exactly 15)
rather than attributed, because ad-hoc probes leave counters moved and no
trace of who moved them.

Shipping the **code first** replaces that with a stronger question. With no
caller left, the expected access count is **exactly zero, from anything**.
Zero needs no accounting; any nonzero value is a finding. The conditions in
their amended form:

| §6d, as written | amended form |
|---|---|
| 1. A span with real fleet traffic, `idx_scan` moving only by reconciler pulls | A span with real fleet traffic and **every** `imagery_snapshots` counter at **+0** |
| 2. Log coverage as a span, not a page | **Dropped as unnecessary.** The event named the one legitimate caller; there is no caller. An event that never fires is not a measurement, and its absence proves nothing about an uninstrumented reader — which the counters cover and always did |
| 3. Attributed, not explained, seq-scans | `scripts/shared/probe.py` — every audit scan logs `audit_probe(table, purpose)` first (`41f7e76`) |
| 4. Then, seven days with (1) and (2) | Then, seven days with (1) and (3) |

Condition 2 being *dropped* rather than met is the part most worth stating
plainly: this batch removed an instrument. It is defensible only because
removing the reader is what removed the need for it, and because the surviving
instrument answers the harder question — "did anything at all touch this
table" — which the log never could.

## 2. NORM-14: closed, not narrowed

The prompt flagged this as the critical design point. **The accepted
atomicity gap is gone.**

**Before.** `upsert_imagery_snapshot` committed per row, inside the persist
loop. The `ok` ledger row for a group was written uncommitted immediately
before it, so the two landed in one transaction — the ledger's honesty
mechanism. `reconcile_source_snapshots` then committed the `parcel_scenes`
work separately. A crash between the loop and the reconcile committed `ok`
rows and snapshot rows for the groups already done, with no `parcel_scenes`
row for any of them (`app/services/imagery.py`, step-2 shape; STATUS.md
NORM-14).

**The design question this batch had to answer.** Deleting the snapshot write
also deletes the commit the `ok` row was riding. The `ok` row then needs a
transaction of its own, or a different one to ride.

**The resolution: the `ok` row rides the reconciler's transaction** — the same
one that writes `scenes`, `parcel_scenes` and the suppressed deletes
(`app/services/imagery.py:1451` docstring; `app/tasks/timeline.py:708-721`).
Nothing in the persist loop commits at all. The alternative — a per-group
commit of its own — was rejected because it would have *recreated* the window
in a smaller form: the ledger would commit ahead of the served row again, just
with a shorter gap.

**The property is preserved and strengthened.** "A crash cannot record `ok`
for unpersisted work" held before by *ordering* two commits so the weaker one
landed first. It now holds because there is one commit: the ledger row and the
row it claims are literally the same transaction.

**Measured, not argued.** `timeline_task_years.created_at` defaults to
`now()`, which in PostgreSQL is transaction start time, so distinct
`created_at` values among one task's `ok` rows counts the transactions that
wrote them. Six Landsat tasks from each of two sweeps on the same day, 43 `ok`
rows each:

| sweep | code | distinct `created_at` per task |
|---|---|---|
| 21:50–22:01Z | pre-step-4 | **43** |
| 22:03–22:08Z | `329a8a6` | **1** |

**The cost, accepted deliberately and stated where someone would act on it**
(`app/tasks/timeline.py`, at the reconcile call): a source that dies at group
40 of 45 now keeps none of the 40, where before it kept them in the old table
only. The next run redoes the source from its search. This is affordable
because nothing between the loop's start and the commit performs I/O — every
STAC fetch and asset validation finishes before the session opens — so the
transaction is short in wall-clock terms whatever the group count.

## 3. What the reconciler does now

`reconcile_source_snapshots` reads `parcel_scenes` joined to `scenes` and
takes the stored `group_key` rather than re-deriving one from a capture date
(the old shape had no such column and had no choice).

**The absent-group rule survives verbatim.** Its docstring paragraph is
unedited: "A group missing from the selection is ambiguous: it can mean the
source no longer offers it, but more often it means that chunk's search failed
and was skipped, and deleting on that basis would turn a transient upstream
error into permanent data loss. So absent groups are always left alone." The
three properties that make the `suppressed` exception safe — this run only,
item ids not periods, `suppressed` only — are likewise unchanged.

**The one delete left is the suppressed case.** Superseding a group this run
*did* select is now an upsert of the one row for that group, because
`UNIQUE (parcel_id, source, group_key)` makes the row unique. The old shape
needed a DELETE for it, since its key was `(parcel_id, stac_item_id)` and a
re-validated Landsat year inserted alongside instead of replacing.

**Return value.** Still "how many served periods did this run supersede" —
replaced-in-place plus suppressed-deleted. It was a delete count only because
replacement used to be spelled as a delete.

## 4. Findings

### F1 — the tuple form of `selected` stopped being implementable

`reconcile_source_snapshots(… selected: Iterable[tuple[str, date] | SelectedScene])`
accepted a bare `(item_id, capture_date)` for a caller that knew a group was
superseded but held no item facts.

Superseding is now an upsert, and an upsert needs the new scene. A tuple
caller would have matched a superseded row, had **nothing to replace it
with**, and returned having changed nothing — a silent no-op wearing the
signature of a reconcile. The old shape hid this because a DELETE needs no
facts about the replacement.

Removed rather than left as a trap. No production caller ever passed it; both
sites in `app/tasks/timeline.py` pass `SelectedScene`. **STATUS.md NORM-33's
sibling; recorded in the ADR amendment.**

### F2 — three reconciliation tests had fixtures that stopped being representable

NORM-20 predicted carnage and named its shape. The mechanical half was
mechanical. The interesting half is that three tests seeded **two or more rows
for one (parcel, source, period)** — G3's shape — in order to prove the
reconciler cleaned it up:

* `test_reconcile_replaces_a_revalidated_landsat_scene` (two Landsat rows for
  1987)
* `test_reconcile_keeps_every_tile_of_a_naip_mosaic` (three NAIP tiles as
  three rows for 2020)
* `test_reconcile_sentinel_year_scope_collapses_the_whole_year` (four
  Sentinel-2 rows across 2020)

That state is now refused by the schema, so the fixtures cannot be written and
the mechanism they tested does not exist. Coverage went to
`tests/test_scenes_schema.py` (the constraint that makes it impossible) and to
rewritten tests asserting replacement-in-place and mosaic references. Each
site names where its coverage went.

**The generalisation, which is NORM-20's own point restated one migration
later:** a test that proves a defect gets *cleaned up* dies when the defect
becomes *impossible*, and the honest replacement asserts the impossibility.

### F3 — a scope mismatch now produces two rows for one period, not one stale row

`test_reconcile_year_scope_would_miss_a_cross_year_topo_replacement` guarded
the finding that `scope` must match the selector. Its consequence changed with
the shape.

Old: a year-scoped topo run left the superseded sheet in place — one stale
row. New: the stored `group_key` is the decade the row was written under, so a
year-scoped run compares `'1950s'` against `'1957'`, matches nothing, leaves
the sheet — **and inserts a second row keyed `'1957'`**. One decade, two
cards. The unique constraint cannot catch it, because the two rows genuinely
differ in `group_key`: it is a mismatch between two encodings of the same
period, not a duplicate of one.

`scope` is per-source configuration and constant, so this is latent. Recorded
as **STATUS.md NORM-33** and asserted by the rewritten test.

### F4 — the local fleet sweep has a deploy gate nobody had written down

**The first sweep ran against the old code and falsified P1 outright**
(`PREDICTION-STEP4.md` §0). The `worker` service bind-mounts `./backend:/app`,
so its files were current, but Celery does not reload modules and the
processes had been up 29 hours — since before the cutover. The counters showed
exactly the old pipeline: `imagery_snapshots` `idx_scan` **+3,265**, `n_tup_upd`
**+3,069**, `n_tup_ins` **+8**, `n_tup_del` **+8**.

`requeue_parcels.py` carries `--require-sha` against `/api/v1/health` written
for precisely this failure in production. Locally the image reports
`GIT_SHA=dev` and the gate cannot check anything, so `--skip-deploy-check` is
routine — and the local equivalent, "restart the worker", was written down
nowhere. **STATUS.md NORM-32.**

**It also produced a control the prediction did not think to ask for.** The
same measurement, same fleet, same day, under the old code, is loudly nonzero.
P1's zero on the re-run is therefore not "an idle window" — which is exactly
the weakness §6d identified in the step-3 fourteen-hour reading.

### F5 — a third decoder for `mosaic_scene_ids`

`imagery._mosaic_ids` was made public as `decode_mosaic_scene_ids` so
`remove_uncovered_snapshots.py` could reuse it rather than hand-roll the
Postgres-`uuid[]`/SQLite-JSON split a third time.
`enrich_synthesized_scenes._id_array` is the third copy and is **left as it
is**: that pass has already run everywhere it will ever run, and editing a
finished script for no behavioural gain is not a migration. Noted at the site
and in **STATUS.md NORM-34**.

## 5. Scripts: what was deleted, what was ported

**Deleted: `scripts/backfill_scenes.py`** (and `tests/test_backfill_scenes.py`).
Single-use — it fills `scenes`/`parcel_scenes` *from* the retired table — and
unrunnable once its input is gone. It ran once locally and once in production
(`STEP1-PROD-REPORT.md`). Two of its tests were about the **schema**, not the
backfill, and moved to `tests/test_scenes_schema.py` with a docstring saying
where they came from; a third tested `platform_for`, which survives, and moved
with them.

**Ported, not deleted: `scripts/remove_uncovered_snapshots.py`.** This is a
live capability the reconciler cannot replace — the absent-group rule means a
re-run can never clear a wrong card that already exists, which is the whole
reason the tool was written. It now reads `parcel_scenes ⋈ scenes` and deletes
the `parcel_scenes` row, leaving the `scenes` row catalogued (a scene that
does not cover *this* parcel is a perfectly good item other parcels may
serve). A mosaic reference resolving to no row is a **refusal** rather than a
dropped entry, unlike the serving path: the serving path can render a mosaic
with a tile missing; a deletion tool cannot condemn one on partial evidence.

**A cheaper evidence path exists and was deliberately not taken.**
`scenes.footprint` now holds real geometry, so `ST_Contains(footprint, point)`
could condemn without a network call. That is a different tool with a
different failure mode — it trusts stored geometry where this one re-derives
the answer from Planetary Computer — and swapping the evidence standard inside
a deletion tool is not a migration. **STATUS.md NORM-35.**

**Added: `scripts/normalization_invariants.py`**, the battery steps 2 and 3
ran as ad-hoc SQL, and **`scripts/shared/probe.py`**, §6d.3's named path. The
battery's `dangling_mosaic` check is the one that can actually fail:
`mosaic_scene_ids` is a `uuid[]` and PostgreSQL has no per-element foreign
key, so it is the reason the battery exists rather than a comment asserting
the constraints hold.

## 6. The pin, and what it costs

`tests/test_no_imagery_snapshots_references.py` walks `backend/app/` and
`scripts/` and fails if any file contains the token `imagery_snapshots`.

* **Confirmed red** by restoring `ImagerySnapshot` to
  `app/models/parcels.py` — delete-the-fix on the deletion itself.
* **One allowlist entry**, `scripts/snapshot_reads.py`, and the exception is
  principled rather than convenient: it queries `pg_stat_user_tables` and
  never the table, so the name appears only as a value in a `relname IN (…)`
  filter. It is also the thing that proves the claim — a measurement of
  "nothing accessed this table" has to name the table.
* **Frozen docs and alembic history are out of scope** and are not walked.
  `docs/` is frozen by CLAUDE.md; `alembic/versions/` must spell the name in
  both the create and the drop or neither could run.
* **The token is the table name only**, not `ImagerySnapshot`. Matching the
  class name would catch `ImagerySnapshotResponse` in `app/schemas/imagery.py`
   — the API response model, named for the domain concept the endpoint still
  serves. Restoring the ORM model cannot dodge the narrower token anyway: it
  carries `__tablename__ = "imagery_snapshots"`, two constraint names and the
  `Parcel.imagery_snapshots` relationship.
* **The cost, paid deliberately:** prose that said "moved off
  `imagery_snapshots`" now says "moved off the denormalized table", in about a
  dozen comments across `app/` and `scripts/`. A comment naming a dropped
  table is how the next reader concludes it still exists, and a pin with
  comment-shaped false positives erodes until someone deletes it. The name
  lives in ADR 0001 and in the frozen audit trail.

**`tests/conftest.py`'s SQLite DDL drops the table in the deploy-1 commit** —
*before* migration 0019 removes it from PostgreSQL. Deliberate: it makes the
test database the stricter of the two, so any surviving access fails with "no
such table" in CI rather than succeeding locally against a table production is
about to lose.

## 7. Migration 0018, the CHECK rider

`CHECK (footprint IS NULL OR ST_IsValid(footprint))` on `scenes`. Pure DDL,
independently revertable.

Its precondition is met and could not have been earlier: a validating CHECK is
refused while any row fails it, and the NORM-31 heal took production's queue
2 → 0 on 2026-08-29 against a fleet invariant over all 5,894 rows with a
footprint. It applied to the **local** database at 21:44Z with no violations,
which is itself a measurement of the same thing locally.

**The semantics, because the constraint is easy to misread as the rule.** The
application rule is repair-loudly — `normalize_footprint` repairs whatever an
item's geometry turns out to be and complains about what it did, and every
write path goes through it. This CHECK is **bypass detection**: it fires only
for a row that reached the table without that function, which is NORM-31's
exact history. **If it fires, the fix is routing the writer through
`normalize_footprint`, never loosening the constraint.**

NULL is admitted explicitly rather than relying on `ST_IsValid(NULL)` being
NULL: `usgs_topo` rows carry no geometry and the deferred enrichment queue is
defined by NULL, so a reader should not need three-valued logic to read the
intent.

**Not mirrored in the SQLite conftest**, with NORM-29's rule stated at the DDL:
SQLite has no PostGIS, so an imitation there would be a predicate the test
file invented, and a passing test would prove the file agrees with itself. It
is exercised in `tests/test_migrations_postgres.py` against a real server, and
the limitation is stated rather than hidden — a footprint PostGIS would reject
can be inserted in the test database.

## 8. Migration 0019, the drop

Pure DDL. **Ships alone**, stated in the docstring and in STATUS.md: the basis
for running it is a cooling period during which the *deployed code*
demonstrably did not touch the table, and a code change riding along means the
code running at the moment of the drop is not the code that was measured.

**The downgrade recreates the schema and not the data**, and says so. It
rebuilds the cumulative state at 0018 — 0002's table, CHECK, unique constraint
and both indexes, 0007's `additional_cog_urls`, 0008's widened CHECK — empty.
There is no backfill and there cannot be one: a snapshot row carried per-parcel
copies of item facts that normalization collapsed to one, and reconstructing
the others would mean inventing rows. **The recovery path for the data is Neon
PITR.** An empty table with the right shape is a *worse* failure than a
missing one — a serving read against it returns nothing rather than failing.

## 9. Sweep scorecard

Full detail and every verdict in `PREDICTION-STEP4.md`'s Observed half.
**17 scoreable, 14 confirmed, 3 deviations, 0 falsified**, plus P1 falsified
on the F4 run that was not the predicted run.

| | |
|---|---|
| **P1 — `imagery_snapshots` +0 on all seven counters** | **CONFIRMED** |
| P3 — the control: `parcel_scenes` +3,787 and `scenes` +8,081 index scans in the same window | CONFIRMED |
| P4 — 7 of 7 zero-checks at 0 | CONFIRMED |
| P5 — landsat 43 on all 45 parcels, 1,935 total | CONFIRMED |
| P2a–d — the sweep wrote **nothing** (NORM-12: a current database cannot exercise an insert path) | CONFIRMED |
| P8 — `landsat/failed` 12 vs predicted ≤ 5 | DEVIATION, all `stac_403` |
| P10 — 16 skips vs predicted 12 | DEVIATION, this batch's own four postgres-gated tests |

Three fleet sweeps ran: one on old code (F4), one on the cutover with the
table present — **deploy-1's production state exactly** — and one after the
local drop. The third is identical to the second on every quantity.

**Deviation P8 in full:** all 12 Landsat and 2 Sentinel-2 failures are
`stac_403` from Planetary Computer rate-limiting three fleet sweeps inside 30
minutes. The old-code sweep produced the same class in the same window, which
is the evidence that it is upstream and not the rewrite. P9 — no failure
naming a missing table, function or constraint violation — is confirmed.

**The hard clause held.** `usgs_topo/indeterminate` stayed at 3. The one new
`sentinel2/indeterminate` after the third sweep was traced rather than
counted: its reason is `_classify_empty_chunk`'s cloud-probe 403, a named
pre-existing site that refuses to guess, not the persist loop. The loop's own
silent-drop reason ("attempted group reached the end of
`timeline._search_and_persist_source` with no outcome") appears **zero** times
across all three sweeps.

**One observation the prediction did not cover.** `scenes.seq_scan` moved +43
during the sweep (57,706 tuples ÷ 1,342 rows = exactly 43 whole scans) with
zero writes, and no `audit_probe` event falls in that window — both batteries
ran outside it. The honest reading is planner behaviour on a 1,342-row table.
It concerns a live serving table, not the retired one, and P1 is untouched.
Noted so a future reading starts from a known figure.

## 10. Local verification

* Suite **749 passed, 16 skipped** with the table present and again with it
  dropped; **762 passed, 3 skipped** with `TEST_POSTGRES_URL` set. The four
  extra skips are this batch's own postgres-gated migration tests.
* `ruff check`, `ruff format --check`, `mypy app/` all clean.
* Reference pin confirmed red by restoring the ORM model.
* 0018's two tests confirmed red with `op.create_check_constraint` removed.
* Round trip against the real local database: `downgrade 0018` recreates the
  table with **0 rows**, 13 columns including `additional_cog_urls`, and all
  four indexes; `upgrade head` removes it; `scenes` 1,342 and `parcel_scenes`
  3,082 untouched throughout.

## 11. State left behind

* **Step 4 is BUILT and NOT DEPLOYED.** Both deploys' commits are on `main`,
  local only, unpushed. Production still runs the step-3 code and still has
  the table, with the reconciler still reading and writing it.
* **The local database is at 0019 with the table dropped.** Production is at
  0017.
* **The deploy-2 gate is not met by anything in this session** and cannot be:
  it requires a production cooling span against deployed deploy-1 code.
* **ADR rule 1 still holds.** `timeline_task_years` references neither table
  and this batch did not make it: the model's docstring lost only the phrase
  naming the dropped table, and `tests/test_no_imagery_snapshots_references.py`
  would fail if a reference appeared.
* **Nothing is pushed.**

## 12. Deviations from the prompt

1. **The sweep ran three times, not once** (F4). The first was against stale
   worker code and is reported as a falsification of P1 with its cause; the
   second is the scored run; the third is item 11's post-drop sweep.
2. **The tuple form of `selected` was removed** (F1). Not in the prompt's
   list; it stopped being implementable and would otherwise have been a silent
   no-op.
3. **`scripts/remove_uncovered_snapshots.py` was ported rather than deleted**,
   and `scripts/backfill_scenes.py` deleted rather than ported. The prompt
   said "every remaining reference" goes; these two needed a judgement about
   which capability survives its storage.
4. **The pin's token is the table name only, not the ORM class name** (§6),
   because the class name collides with the API response model.
5. **§6d's condition 2 is dropped rather than met** (§1). The batch removed
   the instrument that condition was about.
6. **`imagery._mosaic_ids` was made public** as `decode_mosaic_scene_ids` so
   the ported script would not hand-roll a fourth copy of the array decoding.
7. **A pre-existing, unrelated test-isolation bug was found and not fixed.**
   `tests/test_year_ledger.py:238` computes `_SCRIPTS_DIR` as
   `parents[2] / "scripts"`, which resolves to `/scripts` inside the container
   and does not exist; `test_ledger_gaps_reports_the_latest_outcome_per_group`
   therefore passes only when another test has already put the right path on
   `sys.path`, and fails when the file is run alone. Out of this batch's
   scope, and recorded here rather than silently carried.
