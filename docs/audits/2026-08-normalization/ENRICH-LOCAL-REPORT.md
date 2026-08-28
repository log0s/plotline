# STAC enrichment of synthesized scenes — build and local run

NORM-7's remedy, option 2: fetch the real STAC item for every
`provenance = 'mosaic_url'` row, replace its URL-derived candidate `item_id`
with the catalogued one, and fill the item facts — so `(collection, item_id)`
is a trustworthy key for the whole `scenes` table before step 2's dual-write
starts inserting against it.

**Outcome: the local queue is empty. 88 of 88 rows enriched, 0 merged, 0
unmatched, 0 errors, every predicted quantity confirmed.** Prediction
committed before the run as `ce810d5`; scored in `PREDICTION-ENRICH.md`,
"Observed — local run".

**Production was not touched.** No `fly ssh`, no production credentials, no
query against Neon. The one external service this session reached is the
Planetary Computer STAC API, from the local container, read-only: 145 requests
across the whole run, plus 4 during the investigation.

Built on `177b5c3`; this batch's commits:

| Commit | Unit |
|---|---|
| `aa23709` | migration `0016_scenes_provenance_enriched.py`, ORM + test DDL |
| `008d7b2` | `scripts/enrich_synthesized_scenes.py` + 10 tests |
| `ce810d5` | `PREDICTION-ENRICH.md`, before the run |
| *(this batch)* | the same file's Observed half, this report, STATUS.md, CLAUDE.md |

---

## 1. Investigation — the cheapest reliable lookup path

Prompt item 1, capped at 30 minutes. Four live requests against Planetary
Computer, chosen to test the two paths rather than to survey the population.

### What was tested

| Probe | Result |
|---|---|
| `GET /collections/naip/items/ca_m_3712230_se_10_060_20180804_20190210` (candidate carries a publication date) | **200**; `assets.image.href` equals the row's `cog_url` exactly |
| `GET …/items/ca_m_3712230_se_10_060_20200524` (candidate carries **one** date) | **200**; href matches |
| `GET …/items/ca_m_3712230_se_10_h_20160531` (the `_h_` resolution-spelling class) | **404** |
| `POST /search`, `collections=[naip]`, 1500 m bbox around the referencing parcel, `datetime=2016-01-01/2016-12-31` | **2 items**, one of whose `image` hrefs equals the row's `cog_url`; its id is `ca_m_3712230_se_10_.6_20160531_20161004` |

### Four findings, and the design they produced

**(a) Both paths work, and the second is small.** A NAIP year inside a 3 km
box returns a handful of items, not a page: this search returned 2. So the
fallback is one cheap request, not a scan.

**(b) The candidate id is a *usable* address even though it is not
evidence.** 31 of 88 candidates turned out to be the catalogued id. Addressing
the item endpoint with it costs one small request and settles those rows
outright — but the answer is only accepted after `extract_cog_url(item) ==
row.cog_url`, so the id is doing lookup work, never identification work.

**(c) A candidate with a single date field can still be exact.**
`ca_m_3712230_se_10_060_20200524` — the shape F1 associates with the
"proper prefix" class — hit 200 with a matching href, because the 2020 CA NAIP
vintage is catalogued without a publication date. **Filename shape does not
predict the id form**; only the catalog does. This is why the pass tries the
GET on every row rather than pre-classifying by filename, and why the
prediction's `already-exact` floor was 12 (the pubdate-carrying candidates)
with the estimate well above it.

**(d) The referencing parcel is the right bbox, and its buffer matters.** The
2018 CA tile's own bbox is `[-122.3148, 37.4982, -122.2476, 37.5643]`, and the
referencing parcel sits at `-122.2464` — **outside the tile, 100 m east of its
edge**. That is not a defect: these are *additional* mosaic tiles, selected to
cover the display viewport, and a viewport tile need not contain the address.
A point search would therefore have missed it. The pass searches
`point_to_bbox(parcel, 1500 m)` — the exact box `app/tasks/timeline.py:1570`
searched with when the tile was selected — which makes the fallback a re-run
of the original search rather than a new guess.

### The path taken, and one rejected

Adopted: **GET by candidate id, then search on any non-200.** Worst case 2
requests per row, measured 145 for 88 rows.

Rejected: **search-only, batched by (parcel, year).** It looked cheaper —
88 rows fall into 87 distinct (parcel, year) groups, so one search each would
be 87 requests against 145. It was rejected because the saving is illusory and
the coupling is real: 87 vs 88 means these mosaics carry essentially one
synthesized tile per parcel-year, so batching saves one request, while making
every row's resolution depend on the referencing parcel's stored coordinates.
The GET path depends on nothing but the candidate id, and is the only path
that still works for a row no `parcel_scenes` row references. Two independent
paths, tried in cost order, beat one cheaper coupled path.

Also rejected: **deriving the tile bbox from the quarter-quad name**
(`m_4007424_ne` → lat 40, lon 074, quad 24, NE quadrant). It removes the
parcel join entirely, but it is a second derivation layered on the URL parse
that produced the wrong ids in the first place, and it would be doing spatial
inference to save a table read that is free.

## 2. The provenance decision — a third value, not a relabel

**Flagged prominently because the prompt asked for it: enriched rows get
`provenance = 'enriched'`, added by migration 0016. They are not flipped to
`'snapshot'`.**

Both options satisfy the two stated requirements — "not yet trustworthy" stays
distinguishable from "trustworthy", and the `WHERE provenance = 'mosaic_url'`
queue empties as rows are enriched — so the decision turns on what else each
one does.

`'snapshot'` already has a meaning, written into three places that are frozen
records: migration `0015`'s docstring, `Scene.VALID_PROVENANCE`'s comment, and
the ADR's 2026-08-28 amendment. It means **copied from an `imagery_snapshots`
row**. An enriched row never was one: it exists precisely because no snapshot
row carried that tile's URL as its own `cog_url`, which is the condition under
which the backfill synthesized it. Writing `'snapshot'` onto it would make
those three documents false about the rows they describe, and would erase — in
the only column that records it — the difference between a fact copied from a
served row and a fact verified against the catalog. It is also lossy in one
direction: after the flip, nothing can tell the two apart again, so the cost
of being wrong is unrecoverable.

The cost of the alternative is one Alembic revision that drops and recreates
one CHECK — 0016, pure DDL, verified `upgrade` → `downgrade` → `upgrade`
against the local database — plus the mirrored SQLite CHECK in
`tests/conftest.py` and the ORM constraint. No read path changes, because
nothing reads `scenes` yet; and the query a reader actually wants, "is this
`item_id` catalogued", is `provenance <> 'mosaic_url'` before and after.

A three-value column that keeps its meaning is worth one pure-DDL migration.

## 3. The run

Dry run 18:03:28Z, execute 18:03:52Z, both against the post-step-1 local
database at `alembic_version = 0016`. Full captures written by the script
itself: `enrich-local-dryrun.md`, `enrich-local-run.md`.

```
queue (provenance = 'mosaic_url'): 88 row(s)

| already-exact (candidate id was catalogued)      | 31 |
| id-corrected (found by search under another id)  | 57 |
| merged into an existing scenes row               |  0 |
| unmatched (left in the queue)                    |  0 |
| error                                            |  0 |

Rows enriched in place: 88. Queue after this run: 0.
```

The dry run planned exactly this — 31 / 57 / 0 / 0 / 0 — and wrote nothing;
the two modes share one `apply_resolutions`, so a plan that disagreed with the
write would be a bug rather than a surprise.

### Post-write checks

| Query | Result |
|---|---|
| `scenes` by provenance | 1,174 `snapshot` + **88 `enriched`**, 0 `mosaic_url` |
| `enriched` rows with `footprint` / `bbox` / `resolution_m` | 88 / 88 / 88 |
| footprint geometry type | **`ST_Polygon`** on all 88 — no MultiPolygon, so the column's type held |
| `scenes` rows total | 1,262 — unchanged, since nothing was deleted |
| `parcel_scenes` rows | 2,945 — unchanged, and **not touched at all** (0 merges) |
| dangling `mosaic_scene_ids` references | 0 |
| `imagery_snapshots` rows | 2,945 — neither read nor written by this pass |
| `snapshot` rows with a footprint | **0** — deliberately: see §5 |

### Idempotence, observed rather than asserted

The immediate re-run, with `--execute`:

```
queue (provenance = 'mosaic_url'): 0 row(s)
Nothing to enrich.
```

Zero rows, **zero PC requests** — the queue is the work list, so an empty
queue costs nothing — and zero writes. Counts after: 1,174 `snapshot` + 88
`enriched`, unchanged.

## 4. Findings

### F1 — 403 is item-scoped, not quad-scoped (and did not occur here)

**New, and it settles a question the prediction raised.** Zero of the 88 item
GETs returned 403; every non-200 was a 404. Three queue rows sit on
`va_m_3807708_se_18`, the quad carrying four of the six items the 2026-08
geometry audit found PC answering 403 for (`FINDINGS.md` Appendix C) — at
different dates. All three enriched normally, all `already-exact`. So the
audit's 403 population is a property of those items, not of that quad.

**What this does *not* establish.** The pass's design assumption that a 403 on
the item endpoint is recoverable via the search was never exercised, because
no 403 occurred. It remains an untested branch. Production's 505-row queue is
where it gets tested, and the production session should expect to be the first
to learn the answer.

### F2 — `imagery_snapshots.resolution_m` for NAIP is a constant, and it is wrong for most vintages

**New, unfixed, and now measurable because the enriched rows carry the real
value.** Every one of the 200 local NAIP `provenance = 'snapshot'` scenes rows
carries `resolution_m = 1.0`. The 88 enriched rows carry the item's actual
`gsd`:

| `resolution_m` | `snapshot` rows | `enriched` rows |
|---|---|---|
| 0.3 | 0 | 9 |
| 0.5 | 0 | 1 |
| 0.6 | 0 | 30 |
| 1.0 | 200 | 48 |

The cause is not a copy error. `app/tasks/timeline.py:712` passes
`source_cfg["resolution_m"]` into every snapshot row, and that is the
per-source constant `1.0` declared at `timeline.py:67` — the item's own `gsd`
is never read. NAIP has flown at 0.6 m since roughly 2016 and 0.3 m in the
newest state-years, so **40 of these 88 tiles are recorded at a resolution
they do not have**, and by the same mechanism so is every NAIP row in
`imagery_snapshots`, locally and in production.

It is user-visible: `frontend/src/components/MapView.tsx:298-301` renders the
value as a "1m res" chip on the imagery card.

**Not fixed here.** Fixing it means changing what the *pipeline* writes
(`timeline.py`), which is neither this pass's scope nor its queue — and the
fix belongs with step 2's dual-write, which is the commit that revisits what
gets written per item. Recorded as STATUS.md **NORM-9** so it is not
rediscovered a third time. One consequence to note now: after this pass, NAIP
`scenes` rows disagree about resolution by provenance — enriched rows are
right, snapshot rows are the constant — and anything that reads
`scenes.resolution_m` before NORM-9 is fixed is reading two different things.

### F3 — the candidate id was exact 3.5 points more often than F1 predicted

Not a defect; a measurement. F1 measured the state-prefixed filename stem
equal to the catalogued id in 99 of 312 NAIP snapshot rows (31.7%). This
queue — a different population, tiles that were never a snapshot row's primary
— measured 31 of 88 (35.2%). Inside the prediction's band and inside the noise
at n=88. Reported so the production run has a second point to compare against:
if 505 rows also land near a third, the id/filename relationship really is a
property of the catalogued vintage rather than of how Plotline used the tile,
which is the assumption the prediction's band was drawn around.

The sub-structure held exactly: all 12 candidates whose filename already
carried a publication date were exact, and 19 of the 76 single-date candidates
were exact too (25.0%).

## 5. What was deliberately not done

* **The 1,174 `provenance = 'snapshot'` rows still have NULL footprints**, and
  that is not this pass's queue. Filling them is what makes ADR rule 4 — "the
  next geometry audit is a query over `scenes`, not a refetch" — actually
  true, and it is a separate pass over a 6,156-row production population.
  Explicitly deferred, recorded in STATUS.md NORM-7 so it is deferred rather
  than forgotten.
* **`thumbnail_url` is not filled** on enriched rows, though the fetched items
  carry `rendered_preview` hrefs. The pass's job is identity and geometry; a
  display convenience is not worth widening the write surface of a pass whose
  invariant is "touch only what `cog_url` equality justifies".
* **`fetched_at` is left as the backfill wrote it** — when the item first
  entered the database, not when this pass read it. Overwriting it with the
  enrichment's own clock would lose the row's age to record a fetch.
* **`resolution_m` on snapshot rows is not corrected** (F2), and **nothing
  outside `provenance = 'mosaic_url'` was written** at all, merges aside —
  which were zero, so `parcel_scenes` was not touched.

## 6. Deviations from the prompt

1. **`--report` is a required flag rather than a positional argument**, and
   the report is written in dry-run mode too. The prompt asked for a path
   argument; making it required in both modes is what makes NORM-8's lesson
   enforceable rather than optional — a run that forgets it cannot start.
2. **A third provenance value, with a migration** (§2). The prompt left the
   choice open and asked for it to be justified and flagged; this is the
   flag.
3. **Any non-200 on the item GET falls through to the search**, not only 404.
   The prompt's sketch had the search as the miss path; treating 403 the same
   way costs one request and is what would have recovered the geometry audit's
   six items had any been in this queue.
4. **A synthesized row referenced as a `parcel_scenes.scene_id` is reported as
   an error rather than merged.** It cannot happen by construction — only
   `additional_cog_urls` entries are synthesized — but a merge deletes a row,
   and the check costs nothing.
5. **`resolution_m` comes from the item's `gsd`**, not from the source
   constant. That is what surfaced F2.

## 7. State of the record

* `PREDICTION-ENRICH.md` carries the prediction (committed `ce810d5`, before
  the run) and the Observed section scoring it. The prediction half is
  unedited.
* STATUS.md: **NORM-7** updated — remedy built, run locally, production
  pending, with the deferred full-table footprint pass named explicitly.
  **NORM-4** updated: the local half of its population is gone. **NORM-9**
  new, for F2.
* CLAUDE.md: one line added beside the production-access rules — a production
  command expected to outlive the ssh client timeout writes its report to a
  file on the machine or runs detached, because a killed client neither kills
  nor rolls back the remote process (NORM-8 / STEP1-PROD-REPORT F5).
* **Deploy state, stated plainly:** migration 0016 is committed and has been
  applied to the **local** database only. It has not been deployed, and
  `scripts/enrich_synthesized_scenes.py` has never run against production.
  **Production still holds 505 `provenance = 'mosaic_url'` rows with candidate
  ids and NULL footprints, and NORM-7's forward risk to step 2 is still live
  there.** A mitigation that isn't running isn't mitigating; this one is
  running locally and nowhere else.
