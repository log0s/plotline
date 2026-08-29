# Step 2 against production — the staged sweep

Session of 2026-08-29, 03:37–04:52 UTC. The dual-write
(`reconcile_source_snapshots` writing `scenes` and `parcel_scenes` alongside
`imagery_snapshots`, in one transaction) deployed to production at 03:37:25Z
and was exercised over all 189 parcels in two stages: a 30-parcel pilot, a
parity gate, then the remaining 159.

**Outcome: every safety property confirmed; every volume estimate falsified
low, all for one reason.** Parity is **0 violations in both directions over
12,884 groups**, duplicate groups 0, duplicate `(collection, item_id)` 0,
dangling mosaic references 0, `provenance = 'mosaic_url'` still 0, and
**613 of 613** mosaic references resolve to a scene whose `cog_url` is in the
same group's `additional_cog_urls`. The sweep wrote **7 rows**: 3 distinct
Sentinel-2 2026 items, of which 2 were new `scenes` rows and 1 was already
held. Nineteen of twenty-six predicted quantities confirmed; seven falsified,
and all seven are downstream of a single wrong churn estimate.

**Two production writes were made**, both `scripts/requeue_parcels.py` sweep
invocations under the owner-authorized exception in this session's prompt.
No heal, no requeue outside those two, no delete, no schema change, no
deploy, no code change. Every verification probe opened its own connection
and called `conn.set_session(readonly=True)`.

This batch's commits:

| Commit | Unit |
|---|---|
| `7770e5e` | `PREDICTION-STEP2-PROD.md` + baseline captures — **before** the pilot |
| `fb120b8` | pilot captures + the pilot's Observed half — **before** the remainder |
| *(this batch)* | remainder captures, the remainder's Observed half, this report, STATUS.md |

---

## 1. Deploy gates — four of four pass

| Gate | Evidence | Result |
|---|---|---|
| a. Health SHA | `curl localhost:8000/api/v1/health` inside the API machine, 03:39:12Z → `sha efa4c63a07455c5fc776c431d345284fd4082ddd`, `built 2026-08-29T03:37:25Z`. `git merge-base --is-ancestor 61d486b HEAD` exits 0, as does `… efa4c63 HEAD` — so the deployed image carries migration 0017, the dual-write `9526805`, and the tests `17c488e` | **pass** |
| b. Both apps, all machines | `fly image show`: API machines `825d69b7e46618` / `48e0de9a713918` and worker machines `e7845415f57728` / `e2862966b306d8`, all four labelled `GH_SHA=efa4c63a…` | **pass** |
| c. Migration head | `SELECT version_num FROM alembic_version` → `0017`, 03:39:48Z. Read against the revision id declared in the file (`0017_scenes_provenance_selection.py:49`), not inferred from the filename | **pass** |
| d. The CHECK admits `'selection'` | `pg_get_constraintdef` → `CHECK ((provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text, 'enriched'::text, 'selection'::text])))` | **pass** |

(d) is queried rather than assumed, for the reason `ENRICH-PROD-REPORT-2.md`
gave: "the migration ran" and "the migration applied its intent" are
different claims.

## 2. Baseline — clean, and matching the prompt's expectation exactly

Read-only at 03:41:38Z (`prod-step2-baseline.txt`). The prompt named a STOP
condition on any deviation from 6156 / 0 / 505 / 0; the reading was **6,156
`snapshot` / 0 `mosaic_url` / 505 `enriched` / 0 `selection`**, 6,661 total.
`parcel_scenes` 12,884 with 613 mosaic references over 576 rows and 0
`selected_by`; `imagery_snapshots` 12,884; duplicate groups 0; duplicate
`(collection, item_id)` 0; dangling references 0; NAIP `resolution_m` = 1.0
on all 1,305 snapshot rows.

**Parity was already 0 / 0 before any sweep**, which is the expected shape and
was predicted as such: backfill plus enrichment had already made the two
representations agree. The sweep's job was to keep them agreeing under a live
pipeline, not to create the agreement. No unexplained write had occurred in
the intervening period.

### 2a. The ledger's last-24h window was empty, and what was read instead

The prompt asks for the M4 ledger's last-24h outcome distribution. **It
contained nothing**: the newest ledger row was `2026-08-27 22:00:44Z`, about
30 hours earlier. Rather than report a vacuous zero, the window read was the
last two fleet sweeps — 16,587 rows on 08-26 and 18,790 on 08-27.

**All 34 `failed`/`read_timeout` rows in that period are from the 08-26 sweep
and all 34 are on one parcel** (`6563dedf`, landsat 1984–1999 and naip
2010–2026). **The 08-27 sweep recorded zero failures fleet-wide.** So the
pre-sweep parity zero did not rest on unretried upstream failure. That parcel
was put *into* the pilot rather than excluded from it.

## 3. Pilot selection rule, stated before the run

No prior staged pilot exists in the audit record, so the rule was written
into `PREDICTION-STEP2-PROD.md` §3 and committed before the sweep. 30 of 189
parcels (15.9%), deterministic and reproducible from the baseline queries:

* **Tier A, 5 — the hard cases.** `6563dedf` (the only parcel with `failed`
  rows in either recent sweep), `fe065e2d` (NAIP item-cap `indeterminate` on
  7 years, twice), `e513188c` (350 5th Ave — 8 mosaic rows, topo
  `indeterminate`, the geometry audit's uncovered-NAIP-2023 parcel),
  `09f35468` (landsat `read_timeout`, 7 mosaic rows), `9c35ceb0` (Hudson
  Yards — **featured**, 9 mosaic rows, topo `indeterminate`).
* **Tier B, 4 — the mosaic population.** The four highest mosaic-row parcels
  not already in tier A: `4146ec5f` (13), `34efa7ae` (12), `39286f1d` (11),
  `dc493cc5` (10 rows / 16 refs, also **featured** — Navy Yard).
* **Tier C, 21 — unremarkable.** First 21 by `id` ascending with no mosaic
  row, not featured, not in A or B.

**No parcel was excluded for being risky**, and every parcel the ledger marks
difficult is in the pilot. Two featured parcels are included and four are
not — enough to prove the public-surface class without putting the whole
landing page behind an unproven write path.

## 4. The two sweeps

Both `scripts/requeue_parcels.py`, the project's established mechanism, run
**detached** inside the API machine with output to an on-machine file and
retrieved afterwards by `fly ssh sftp get` — the F5 rule, and NORM-8's
lesson that a killed ssh client neither kills nor rolls back the remote
process.

```
python scripts/requeue_parcels.py --require-sha efa4c63 \
    --sources naip,landsat,sentinel2,usgs_topo $(cat /tmp/pilot_ids.txt)
```

`--require-sha`, not `--skip-deploy-check`: the gate is satisfiable in
production and this is the case it exists for. `--sources` limited to the
four imagery sources because step 2 changed the imagery pipeline and nothing
else; full scope would have re-run property and census tasks, writing tables
this batch has no claim about.

| Stage | Enqueue | Result | Terminal |
|---|---|---|---|
| Pilot, 30 parcels | 03:50:36 → 03:52:29Z (113 s) | **30 queued, 0 skipped, exit 0, 0 unreached** | 03:59:29Z |
| Remainder, 159 parcels | 04:02:47 → 04:41:20Z (38.5 min) | **159 queued, 0 skipped, exit 0, 0 unreached** | 04:50:09Z |

A dry run preceded the pilot and passed the gate (`Deploy gate passed — prod
is running efa4c63a…`), listing exactly 30 parcels with no unknown ids. The
remainder's 38.5-minute enqueue is the admission cap doing its job: 25 heal
slots, 5 reserved, polled rather than refused.

**189 requests `complete`, 756 tasks `complete`, 0 `failed`, 0 `partial`,
none in flight.**

## 5. Results

### 5.1 The safety battery — clean at every level

| Check | Pilot | Fleet, after both |
|---|---|---|
| Parity, `imagery_snapshots` → `parcel_scenes` | **0** | **0** |
| Parity, `parcel_scenes` → `imagery_snapshots` | **0** | **0** |
| Duplicate `(parcel_id, source, group_key)` in `imagery_snapshots` | 0 | **0** |
| Duplicate `(parcel_id, source, group_key)` in `parcel_scenes` | 0 | **0** |
| Duplicate `(collection, item_id)` in `scenes` | 0 | **0** |
| Dangling `mosaic_scene_ids` | 0 | **0** |
| `provenance = 'mosaic_url'` | 0 | **0** |
| `scenes` rows deleted | 0 | **0** |
| `parcel_scenes` = `imagery_snapshots` | 2,075 = 2,075 | **12,884 = 12,884** |
| Landsat conservation | exactly 1,290 = 30 × 43 | **exactly 8,127 = 189 × 43** |

**Duplicate `(collection, item_id)` = 0 is the load-bearing one.** NORM-7 /
`STEP1-PROD-REPORT.md` F1 described a collision in which a synthesized row
and a real catalogued write become two rows for one physical tile under two
different ids, satisfying `UNIQUE (collection, item_id)` and landing
silently. The 2026-08-28 enrichment pass closed it by making all 505
candidate ids catalogued — **an argument from the code, never tested by a
live write.** This sweep is that test: the first time the dual-write has
inserted into a production `scenes` table the enrichment prepared. It comes
back 0.

### 5.2 What the sweep wrote — 7 rows, and every mechanism in them

189 pipeline runs over 12,884 groups changed **7** selections, all Sentinel-2,
all group `2026`, resolving to 3 distinct items:

| Item | Capture | Parcels | `scenes` effect |
|---|---|---|---|
| `S2C_MSIL2A_20260820T173901_R098_T13TEE_…` | 2026-08-20 | 4 | **0 inserts** — already held as a `'snapshot'` row fetched 2026-08-25 |
| `S2B_MSIL2A_20260828T160819_R140_T17TPH_…` | 2026-08-28 | 2 | **1 insert**, then 1 hit |
| `S2B_MSIL2A_20260827T163859_R126_T16TER_…` | 2026-08-27 | 1 | **1 insert** |

**7 lookups → 3 distinct items → 2 inserts, 5 hits.** `scenes` 6,661 → 6,663.

Three design properties are visible in those seven rows:

1. **Insert-only, and one row per item.** The 4-parcel item was found, not
   duplicated — the shape the local DC probe showed (71 lookups, 71 hits, 0
   inserts), now against production.
2. **Sharing observed inside a single sweep.** Parcel `b0ca9bbc` inserted
   `S2B_…20260828` at 04:29:19.342Z; parcel `d38891fc` re-selected the same
   item at 04:37:26 and pointed at the existing row. One item, one row,
   however many parcels — the ADR's premise, measured live.
3. **Update-in-place with deletion mirrored.** `imagery_snapshots` is 12,884
   before and after with 7 inserts, so 7 superseded rows were deleted;
   `parcel_scenes` is also 12,884 before and after, so those selections were
   updated in place, same primary key, new `scene_id`. `STEP2-REPORT.md`
   §1e's first case. The worker log carries 7 × `Replaced superseded imagery
   snapshots`, each `deleted: 1, suppressed_deleted: 0`.

Both new `'selection'` rows carry `footprint` (`ST_Polygon`), `bbox`,
`resolution_m`, `cloud_cover_pct` and `platform` **from birth**. The
requirement is met in production: the synthesized-candidate class cannot
grow, and `mosaic_url` stayed 0 through 189 pipeline runs.

`selected_by` is `efa4c63a07455c5fc776c431d345284fd4082ddd` on exactly those
7 rows and NULL on the other 12,877 — **NORM-12's shape at fleet scale.**
0.05% attributed is correct behaviour, not a failure: an unchanged selection
is left completely alone.

### 5.3 Insert-only, checked at full-population granularity

The prompt asks for 3 `enriched` rows spot-checked. All **505** were, twice —
after the pilot and after the remainder. Both readings: 505 rows, 505 with a
footprint, `max(fetched_at)` **2026-08-27 17:52:36Z**, and a row digest over
every column of every row of
**`d17c4eee14c2155cb4e4528b265f87ab`**, identical between the two, with a
`resolution_m` distribution matching the pre-sweep baseline in all eleven
buckets — including each of the eight NORM-11 noise spellings at its exact
count. **No `enriched` row was touched by 189 pipeline runs.** A single
rewritten row would move the digest.

### 5.4 Mosaics

Unchanged in every dimension: 576 rows carrying a mosaic on each side, 613
references, 578 distinct tiles (505 `enriched` + 73 `snapshot`), 0 dangling —
and **613 of 613** references resolving to a `scenes` row whose `cog_url` is
a member of the same group's `additional_cog_urls`. That is the strong check
`STEP2-REPORT.md` §3f ran over 176 local references, now run over every
production reference.

The prediction derived, read-only and before the run, that **all 578
referenced tiles already existed as `scenes` rows with catalogued ids, so
re-picking one is a lookup hit and contributes nothing to the insert
population.** The prompt had named newly-catalogued mosaic tiles as "the
largest predictable insert population"; the derivation falsified that before
the sweep rather than after it, and the sweep confirmed the derivation: **0
mosaic-tile inserts.**

### 5.5 The ledger, whole window (NORM-3)

03:50:00Z → 04:51Z: **14,770 rows, 0 `failed`.** Non-`ok` outcomes are all
pre-existing classes — naip `absent`/`no_scenes` 1,892, naip `suppressed` 9,
naip `indeterminate` (item cap) 7, sentinel2 `absent`/`all_cloud_filtered` 9,
usgs_topo `absent` 7, usgs_topo `indeterminate` (TNM row cap) 2.

The 9 `indeterminate` rows are all from the pilot window and all on the three
tier-A parcels chosen for them. They are markers that an absent group *may*
be truncation, not failures, and under the absent-group rule they cost no row
in either table.

**Every one of the 12,884 groups was swept in this window and not one search
failed, so the parity zero rests on nothing unretried.** That is the
strongest form of the NORM-3 reading and neither database has produced it
before: the local sweep's zero rested on 2 unretried `stac_403` groups, and
the 08-26 production sweep's on 34.

### 5.6 Request-path damage (G4) — none, and that does not clear it

`HEAL-SCORECARD.md` §4 item 4 measured, during the 2026-08-12 fleet sweep, 41
SAS rate-limit give-ups, 17 band-signing failures and 115 Titiler 500s. The
prediction said the same signature was expected here and would be accepted
for the sweep window.

**Observed: zero.** Across 3,337 captured worker lines and 567 STAC searches
there is no `rate-limited`, no `Band signing failed`, no `backoff exceeds`,
no Titiler 500; 4 SAS container tokens were minted without incident, and the
API stream is quiet. The only 12 warnings in the whole run are 9 NAIP
suppressions and 3 truncation caps.

**Log coverage is complete rather than sampled**, which is the HEAL-SCORECARD
§0 lesson applied: the continuous `fly logs` stream was started at 03:49:30Z,
**before** the 03:50:36Z enqueue, and never dropped. It carries **189
`fetch_imagery_timeline task started` and 189 `Timeline request finished`
events for 189 parcels** — against the geometry heal's ~50% coverage, where
every log-derived count was a floor.

So G4 did not fire. **That is not evidence it is fixed**; see F-PROD-1.

## 6. Scorecard

Full detail in `PREDICTION-STEP2-PROD.md`, whose two prediction halves were
committed before the runs they predict and have not been edited.

**Confirmed (19):** PP1–PP4, PP6, PP7, PP10–PP12, PR1–PR4, PR7, PR9, PR10,
PR12, §7a insert-only, and the §5a mosaic derivation.

**Falsified (7):** PP5, PP8, PP9, PR5, PR6, PR8, PR11 — every new-row,
attribution and NAIP-resolution estimate — plus §6b's G4 expectation.

**All seven volume falsifications are one fact:** the sweep changed 7
selections where the estimate said 100–375. Nothing about the dual-write's
behaviour was falsified; the estimate of how much work it would have to do
was, by a factor of about 35.

## 7. Findings

### F-PROD-1 — the churn anchor measured PC's health, not selection drift

**New. Open, unfixed, and the most useful thing this run produced.**

The prediction's band came from the two fleet sweeps in the ledger: 171 rows
inserted on 08-26 and 175 on 08-27, of which ~104–112 a day were Landsat
historic years. It attributed those to the validation walks re-signing assets
live, so a year that fell back to a different item once may not the next
time.

This run changed **zero** historic years on **any** of 189 parcels, and the
worker log says why: **not one signing failure, rate-limit event or retry
across 567 STAC searches.** The same variable — Planetary Computer being
healthy — explains both the absent churn and the absent G4 storm. They are
one observation, not two.

Two consequences:

1. **Neither result generalizes.** A sweep run while PC throttles would
   likely show both. **G4 is not retired by this run; it was not exercised
   by it**, and a future sweep should not cite this one as evidence the
   request path is safe.
2. **The 08-26/08-27 historic-year churn may not have been improvement.** If
   ~100 Landsat rows a day were rewritten because signing failed and the
   validation walk fell back to a different item, those sweeps were writing
   signing noise into the database rather than better selections — and a
   quiet PC, as here, changes nothing. **This is a hypothesis, not a claim.**
   This session has no logs from 08-26 or 08-27 and did not go looking; the
   check is cheap next time (correlate signing-failure counts with
   historic-year row writes) and expensive to rediscover.

### F-PROD-2 — a zero-write sweep is not distinguishable from a dead dual-write, and the pilot was one

**Method finding; NORM-12 in its sharpest form.** The pilot's 30 parcels,
2,075 groups, produced **zero** writes of any kind. From the tables alone
that is identical to a run in which the dual-write never executed, and the
pilot gate could not have caught a dual-write that silently did nothing.

The reconciler *does* log — `Replaced superseded imagery snapshots`, once per
changed group — but it logs nothing on a no-op, so the pilot produced no such
line either. What separated the two hypotheses was the remainder: 7
replacement log lines, 2 `'selection'` rows, and 7 attributed
`parcel_scenes` rows.

**The implication for anyone repeating this:** a staged pilot gates on safety
properties, and safety properties are all satisfied trivially by a run that
does nothing. A pilot proves the write path only if it writes. Sizing the
pilot for *expected churn* rather than for parcel count would have been the
better rule, and was not the rule used here.

### F-PROD-3 — NORM-9 is deployed but still unobserved in production

**New. Open.** NORM-9's fix (read the item's `gsd` rather than the per-source
constant) is deployed and ran 189 times. **It remains unobserved**, because
the only rows it can affect are NAIP rows the pipeline *inserts*, and this
sweep inserted none: NAIP `imagery_snapshots.resolution_m` is still **1.0 on
all 1,305 rows**, and NAIP `scenes` `snapshot` rows still 1.0 on all 1,102.

The 7 rows written carry `resolution_m = 10.0`, which is the Sentinel-2
source constant and **not** evidence of the `gsd` read: S2 items carry no
item-level `gsd`, so the fallback is the correct path and proves nothing.
NORM-11's rounding rule was likewise not exercised by live data.

So the production evidence for NORM-9/NORM-11 is still the fourteen
mutation-verified tests and the local probe parcels. Recorded so that
"deployed" is not read as "observed".

### F-PROD-4 — the ledger's 24-hour window is the wrong instrument between sweeps

**Minor, operational.** The prompt's "last-24h outcome distribution" returned
an empty set, because the fleet is swept every day or two and the last sweep
was ~30 hours old. A fixed-width window over an event-driven ledger reports
nothing whenever the gap exceeds the width, and "no rows" reads like "no
failures" to a hurried reader. The reading that carries information is
per-sweep: group the ledger by its own `created_at` day, or by request.

## 8. Deviations from the prompt

1. **The mosaic-tile insert population was derived as zero and predicted as
   zero**, against the prompt's statement that it is "the largest predictable
   insert population". §5.4 has the derivation, which was committed before
   the pilot rather than offered afterwards. The sweep confirmed it.
2. **The ledger's last-24h read was empty and was replaced** by the last two
   fleet sweeps' distribution. §2a; F-PROD-4.
3. **The §7a spot-check covered all 505 `enriched` rows rather than 3.** A
   digest over the whole population is strictly stronger and no more work.
4. **`--sources` limited to the four imagery sources** rather than full
   scope. §4 has the reasoning.
5. **The full 1.0 MB worker stream is not committed** —
   `step2-sweep-worker-log.txt` carries the event and level histograms, the
   G4 scan, all 7 reconciliation lines and every warning line in full. The
   raw stream stays in the session scratchpad.

## 9. What this does not do

* **No read path moved.** The six production read sites carried forward in
  `STEP1-REPORT.md` §7 are untouched. Nothing in production reads `scenes` or
  `parcel_scenes` today, before or after this sweep. Step 3 owns the cutover.
* **No heal.** The 6,156 `snapshot` `scenes` rows with NULL `footprint`
  (NORM-7's deferred pass) are unchanged at **6,156**. The NAIP rows carrying
  the 1.0 constant are unchanged at **1,305** `imagery_snapshots` + **1,102**
  `scenes` — NORM-13's backlog, recorded and not touched.
* **No retry.** The 34 `failed`/`read_timeout` groups from the 08-26 sweep
  were re-swept as part of the fleet and came back `ok`; nothing was
  separately retried.
* **The 8 noisy NORM-11 rows are unchanged**, as the digest shows.

## 10. State left behind in production

* `scenes`: **6,663** — 6,156 `snapshot` + 505 `enriched` + **2 `selection`**,
  0 `mosaic_url`.
* `parcel_scenes`: **12,884**, of which **7** carry
  `selected_by = efa4c63a…` and 12,877 NULL; 576 carry a mosaic, 613
  references, 0 dangling.
* `imagery_snapshots`: **12,884** (landsat 8,127 / naip 1,305 / sentinel2
  2,259 / usgs_topo 1,193), 0 duplicate groups.
* `alembic_version`: `0017`. Both apps on `efa4c63`.
* Ledger: 14,770 new rows in the sweep window, 0 `failed`, 9 `indeterminate`
  on three parcels.
* On machine `825d69b7e46618`: `/tmp/step2-pilot-sweep.txt`,
  `/tmp/step2-remainder-sweep.txt`, `/tmp/step2-pilot-battery.txt`,
  `/tmp/step2-fleet-battery.txt`, `/tmp/step2-detail.txt` (all retrieved and
  committed here), `/tmp/pilot_ids.txt`, `/tmp/remainder_ids.txt`, the two
  runner scripts, and six read-only probe scripts
  `/tmp/probe_{gates,base,pilot,pilot2,churn,post,detail,inflight,inflight2}.py`.
  Nothing was written to the database outside the two sweep invocations.

## 11. Step 3

**Unblocked.** The gate step 3 needed was that the two shapes agree under a
live production pipeline, and they do: parity 0 in both directions over all
12,884 groups, with no duplicate of either kind, no dangling reference, and
every group in the measurement actually swept with zero upstream failures —
so the zero is not resting on unswept groups.

**With one qualification that belongs in step 3's prompt rather than in a
footnote:** the insert path was exercised **twice** in production. Its
correctness still rests on the fourteen mutation-verified tests and the local
probe parcels, exactly as it did before this run. That is enough to unblock a
*read* cutover — step 3 changes which table is read, and the read is
validated by the parity this run measured — but it is not the fleet-scale
insert-path evidence a reader might assume "swept in production" implies.
