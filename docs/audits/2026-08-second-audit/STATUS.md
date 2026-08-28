# Second Audit — Status

Companion to `FINDINGS.md`, which is frozen as a record of what the code
looked like at 5f5fb42 (2026-07-29). This file is the living half: what each
finding's status is now, and where the open ones stand.

**Verified against HEAD e1006df on 2026-08-03** by reading each cited site,
not by trusting the annotations. The fourteen items triaged FIX NOW were then
executed in the five commits cited below, and their rows reflect that. Line
numbers are HEAD's, not the audit's.

The 2026-08-12 operational audit (`../2026-08-ops-audit/`) has its own section
below. Its findings are about the running system rather than the code, but two
of them bear directly on rows here — M4 above all — so they are tracked
together rather than in a second living document. The 2026-08-12 geometry
audit (`../2026-08-geometry-audit/`) is tracked the same way, in its own
section further down.

Nothing was incidentally resolved between the audit and the verification pass.
M6, L2, L5 and all six L12 items were checked specifically against the commits
most likely to have caught them — the Redis, reconciliation, and
geocoder-guard work — and none had.

## Summary

| | Resolved | Partially resolved | Open |
|---|---|---|---|
| High (6) | 6 | 0 | 0 |
| Medium (12) | **6** | **3** | 3 |
| Low (12) | 6 | 3 | 3 |

*2026-08-26: M3 moves Partially resolved → Resolved (in code; committed, not
deployed, and none of its three acceptance heals has run). The Medium row
above is updated rather than annotated because it is a count, and a stale
count is a lie rather than a record.*

*2026-08-27: M4 moves Open → Resolved. This is the one row this update
re-tallies — the rest of the table reflects the last full audit pass, not a
fresh recount of all 30 second-audit findings. See M4's own row for why: its
stated blocker ("Resolved" needs an actual heal, not just the code) was
`../2026-08-m3/HEAL-3-decennial-2000.md`'s fleet-wide P2 sweep,
`../2026-08-m3/HEAL-1-e513188c.md` and `../2026-08-m3/HEAL-2-crawford.md`,
all run and scored 2026-08-27. This file's newer families (O, G, X, Y, Z) are
not second-audit findings and are tracked in their own sections below, not in
this table — start there for anything past 2026-08-12.*

"Partially resolved" here always means the remainder is an explicit accept or
an explicit deferral, both recorded below — never an unfinished edit.

Two rows do not fit those buckets and are not recounted here. **M4** reads
"Instrumented" as of 2026-08-25: its per-year outcomes are now persisted, but
the heal path that acts on them is M3, so it stays inside the Open four rather
than moving. *2026-08-26: M3's heal path is now built (`ae740cf` → `b7c9cbb`),
so M4's stated blocker is gone in code — but it stays in the Open four until a
heal has actually run against it. "Resolved" means the fix is in the code;
M4's remedy is a heal, and no heal has run.* *2026-08-27: the blocker named in
the sentence just above is now false — M3's three acceptance heals (P1, P2,
P3) have all run and scored, per M3's own row above. M4 moves to Resolved in
the table above; it is no longer one of the two rows this paragraph's
"do not fit those buckets" describes.* **M7-5** is a row split out of M7, not a thirteenth Medium
finding.

**X1-X3** (2026-08-26) are not second-audit findings either and are not
counted above. They come out of the M4 sweep's gate and are tracked in their
own section below. All three are now resolved and deployed — see the
2026-08-26 addendum on X1/X2 below and `../2026-08-m4-ledger/GATE-STOP.md`'s
own addendum.

## The fix commits

| Hash | Covers |
|---|---|
| dd99cee | M6, M10 (advisory lock), L11 |
| 3269bbf | L5 |
| ffb71b2 | L2, L4, L6 (source id), L7, L9 |
| ae5793a | M2 (atomicity), M3 (cooldown), counties item 13 |
| 56d6647 | M9 (exposure), L12 (CORS) |
| 0814d7e, ef2d0a2 | M4 (per-year ledger — instrumentation half; the heal path is M3) |
| 822faca, 0fc0f64, b3f8e94, ea98325, d13026e, 382329e | NORM-1 (imagery normalization step 1 — `scenes` + `parcel_scenes`, built and run locally) |
| 93ee2ff, 80455b5 | NORM-1 (step 1 backfill run against production, 2026-08-28: prediction committed before the write, scored after — every line confirmed), NORM-7, NORM-8 |
| aa23709, 008d7b2, ce810d5 | NORM-7 (the STAC enrichment pass — migration 0016's `'enriched'` provenance, `scripts/enrich_synthesized_scenes.py`, prediction; built and run against the **local** database only, production pending), NORM-9 |
| 673ce05 | NORM-7 (production enrichment attempted 2026-08-28 and stopped at the dry-run gate; nothing written), NORM-9, NORM-10 (PC throttles `/search` with 403) |

## High — all resolved

| # | Commit | Verified at |
|---|---|---|
| H1 Housing chart | 6def10c, 1c1c069 | `census.py:57-64`; `scripts/backfill_census_housing.py` |
| H2 Log context | 90ea416 | `logging_config.py:28`; `celery_app.py:63-74` |
| H3 Demographics cache | 90ea416 | `demographics.py:37` |
| H4 Property outage | 256ed32 | `county_adapters.py:35-42,113-128`; `timeline.py:683-697`. *Later, 2026-08-27 (`48b7fd8`): the all-queries rule is unchanged and still the `failed` test, but it is no longer the only outcome below success — a property task now has `partial` for "some queries failed, some did not", which is the gap Z3 named. See Z3 and the `../2026-08-property-outcomes/REPORT.md` §4.* |
| H5 Address matcher | add8102 | `address_normalizer.py:34-52,76-87`; `tests/test_address_normalizer.py`. *Later, 2026-08-27 (`48b7fd8`): how many rows the matcher rejects is now on the task row as `rows_returned - rows_matched`, not only in a log line — Z4.* |
| H6 Landsat duplicates | 96a7962 | `imagery.py:414-503`; `timeline.py:365,454`; `revalidate_landsat.py:65-77` |

## Medium

| # | Status | Where it stands |
|---|---|---|
| M1 Geocoder decode | Resolved (949c1b3) | `geocoder.py:158,196`. The finding's retry-asymmetry aside (only timeouts retried) is unchanged; it was flagged as defensible, not as a defect. |
| M2 Rate limiting | Partially resolved (ae5793a) | INCR and EXPIRE now ship in one pipeline with `EXPIRE … NX`, so a death between them can no longer leave an immortal counter. The X-Forwarded-For handling is accepted — see below. |
| M3 Backfill scope | **Resolved, observed — all three acceptance heals run and scored (`ae740cf`, `c98de1b`, `a6c7800`, `b7c9cbb`, `bd03432`, `5f3aa7d`; deployed 2026-08-27T15:42Z, both machines confirmed on `5f3aa7d`, `alembic_version=0012`).** P1 (`e513188c`, NAIP wrong-place card) confirmed zero-deviation: `../2026-08-m3/HEAL-1-e513188c.md`. P3 (`6563dedf` Crawford, 33 groups no self-running path could reach) confirmed, recovery landing at the optimistic end of the prediction's two branches: `../2026-08-m3/HEAL-2-crawford.md`. **P2 — the fleet-wide decennial-2000 sweep — run 2026-08-27 16:50Z-17:08Z and confirmed with zero deviation: `../2026-08-m3/HEAL-3-decennial-2000.md`.** One invocation, exit 0, 139 census-only `origin='heal'` requests, all `complete`, one `census` task row each, zero skipped, zero unreached. The dry-run selection came back **139 through the script itself** — the number Y3's addendum could only reach by hand-written SQL, and the ride-along arithmetic (140 − 1, Crawford's full-scope heal having already taken one of the 64) was written down before the run. Recovery **48 → 111 `census_snapshots` `decennial`/`2000`, exactly 63 rows, every one on a tract ending `00`**; 76 re-recorded `absent`/`api_no_data`, splitting 60 real-suffix / 16 known-204 exactly as `../2026-08-census-decennial/REPORT.md` §1.5 listed. Scope held: `imagery_snapshots` byte-identical by row id (12,751, `md5` `8839c46e…986d`), zero non-census ledger rows from the run's tasks, zero `failed` rows. `_find_reusable_request` still returns the older **full-scope** request on all three probed healed parcels — the §2.2 trigger-6 guard observed in production, not just unit-tested. **The admission reserve is measured for the first time:** `depth=25` on all 236 admission lines, `cap=25`, `hard_cap=30`, 84 refusals / 84 wait episodes / 152 poll lines, longest wait 15.6 s, total 13.0 min. The heal ceiling held; **the reserve's effect on user traffic is still unmeasured** — no `origin='user'` request arrived during the window, so P2's own caveat stands. *2026-08-27, second measurement, first at full fleet scope: the retry/ops scoring sweep enqueued 189 full-scope requests over 57.5 minutes with `cap=25 depth=25 hard_cap=30` on all 814 admission lines, 142 refusals, 672 wait polls, 1958 s of the 5400 s budget unspent, exit 0, zero unreached. The ceiling held again at four times the request count. **And the user-traffic gap is unchanged: zero `origin='user'` requests arrived in that window either**, so the five reserved slots have now gone unused across two heals. The reserve is confirmed to bound heals and remains unobserved doing the thing it exists for. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §1, §8.* Two things this run did not settle are Y7 below (the ledger cannot mark a permanent absence, so the same 76 are selected again by the next `--include-absent-api` run) and a `fly logs` routing deviation recorded in §6 of the heal report. Watch: `../2026-08-m3/DEPLOY-WATCH.md`. **Census scope is per task, not per dataset: `--sources census_decennial` also runs ACS5, which is how heal 3 gained 28 unpredicted `acs5`/2009 rows (HEAL-3, ride-along). Decide whether dataset-level scope is worth a task split before the next census heal.** Original row follows. | A cooldown (`backfill_cooldown_hours`, default 6) bounds the per-visit cost and logs each suppression. The cooldown is dispatch-anchored — it reads the latest `TimelineRequest.created_at`, which includes a request the current visit may have just created — not completion-anchored; correct for cost-bounding, and the per-source work inherits it unless it deliberately changes it. Per-source scope is deferred, not accepted — see below. **Closed 2026-08-26.** `TimelineRequest.sources` carries the run's *declared* scope (all six sources for a full run, a subset for a scoped one) and `origin` says who asked; the worker intersects the declared scope with parcel eligibility and feeds the result to both the task-row creation and the coroutine fan-out, so a census-only request creates no imagery task, runs no imagery fetch and cannot reach `reconcile_source_snapshots` at all. `maybe_refetch_for_backfill` gains a ledger trigger — retryable groups per the `services/ledger.py` retry policy, folded onto the sources that would re-run them, dispatched as one scoped `origin='backfill'` request — which is the first code path able to see a `failed` year under a `complete` task. **The cooldown is still dispatch-anchored, as this row says, but is now per source:** it reads the latest request that *included* that source, so a census-only backfill at T no longer blocks a landsat backfill until T+6h and a fleet sweep no longer resets the clock on every source of every parcel at once. The three task-row triggers (census, property, topo) are **kept and none is subsumed** — a missing task row means the source never ran and so has no ledger rows, absence not being an outcome, and property writes no ledger rows in any circumstance; they keep dispatching full scope, which is also what keeps the topo trigger a one-shot latch (a topo-*scoped* run would leave the parcel's current full-scope request still lacking a topo task row and the trigger would fire every cooldown forever). Report: `../2026-08-m3/REPORT.md`; predictions for the three acceptance heals, written before any run: `../2026-08-m3/PREDICTION.md`. |
| M4 Partial census/Landsat failures | **Resolved, 2026-08-27 — see the M3 row above.** *This row's stated blocker was "M4's remedy is a heal, and no heal has run." That is now false: `../2026-08-m3/HEAL-1-e513188c.md` (P1), `../2026-08-m3/HEAL-3-decennial-2000.md` (P2, fleet-wide), and `../2026-08-m3/HEAL-2-crawford.md` (P3) all ran and scored 2026-08-27. Not deployed at the same commit M4's own instrumentation shipped under, but "resolved" tracks the fix landing and running, per this file's deploy-state convention — see M3's row for the deploy timestamps.* **Instrumented (`0814d7e`, `ef2d0a2`, 2026-08-25) — per-year outcomes persisted; heal path pending M3.** *2026-08-26: the heal path is built (M3 above, `../2026-08-m3/REPORT.md`) and committed, not deployed; no heal has run, so this row does not move. Two things found while building it belong here rather than below: a source that lost **every** year recorded nothing at all (Y2 — the instrument was silent exactly where the loss was total), and a group the code has stopped attempting keeps its stale outcome forever (Y3).* | **Every attempted year now records an outcome in `timeline_task_years`: `ok` / `failed` / `absent` / `suppressed` / `indeterminate`, with a machine reason. All seven per-year sites are wired (`docs/audits/2026-08-m4-ledger/REPORT.md` §4), `scripts/ledger_gaps.py` is the read query, and the design is `docs/audits/2026-08-m4-design/INVESTIGATION.md`. Two things this does *not* do. (a) **Task status semantics are unchanged** — a task with failed years still ends `complete`, and the census `{}` skip still increments nothing; the ledger is the record, and what to do with it is M3. (b) **The ledger starts at deploy and carries no history** — no backfill exists or can exist, since the outcomes it records were never written down. A parcel last fetched before deploy has zero rows, and its absence from `ledger_gaps.py` means "not yet swept", not "healthy". Committed, not yet deployed as of 2026-08-25; the prediction for the first full sweep is `docs/audits/2026-08-m4-ledger/PREDICTION.md`, written before deploy. The four occurrences below are what the ledger would now make visible; none is healed by this batch.** Original row follows. `timeline.py:234-259`, `:616-692` (the census year loop moved into `_fetch_census_years` in b5a306a; line numbers refreshed after c82ed51 shifted the file), **and `:434-506`, the topo path — a TNM response truncated at its cap (T3 below), or a product skipped for a missing `sourceId`, drops whole decades under a `complete` task exactly as the census and Landsat halves do, so topo/TNM is the third silent-drop door, not a footnote to the other two.** *Precision correction, 2026-08-15 (source inventory): this clause originally also named "a TNM search that fails", and that half was wrong — a **whole-search** TNM failure propagates out of `_search_and_persist_topo` to `_fetch_usgs_topo`, which marks the task **`failed`**, not `complete` (`timeline.py:457-462`). What does match this row as written is the cap (`usgs_topo.py:89-97`) and the missing-`sourceId` skip (`timeline.py:513-518`). Its sibling, the unparseable-`publicationDate` skip (`timeline.py:497-505`), is a **latent guard rather than a live door** — `select_topo_items` already drops items whose year will not parse (`usgs_topo.py:113-116`), which is the same reachability T2 below establishes for the 1900 fallback, so nothing reaches it.* — failures counted, never persisted, so nothing can target the gaps. Sharper than the finding states on the census half: a year the API has no data for returns `{}` and is skipped by `if data:` (`:639` decennial, `:666` ACS5) **without** incrementing `failed_requests` (`:653`, `:680`), so the all-failed check at `:692` cannot see it either. The gap is not merely unpersisted — it is invisible to the task's own failure arithmetic, which is why a parcel could sit at `complete` with four of six ACS years missing. One instance of that shape — years lost to the 2020 tract redistricting — is healed by b5a306a and its `scripts/heal_tract_vintage_gaps.py`; the general problem of persisting per-year failures is untouched. **Observed in production three times, from three independent upstreams.** (1) 2026-08-11: a burst of 21 SAS signing 429s in four seconds cost one parcel 20 of its 43 Landsat years. (2) 2026-08-12 00:45Z: a second parcel (Ocean County NJ) lost 8 Landsat years — after the incident, and **on production that did not have a536d07**. The throttle was committed 2026-08-11 and left unpushed; CI deploys on push, so the running release was still pre-throttle when those years were lost. Whatever else a536d07 does, it demonstrably did not prevent this: the loss is post-commit and pre-deploy, and no signing-throttle event appears in any log buffer. (3) 2026-08-12 01:25Z: four `httpx.ReadTimeout`s against `api.census.gov` cost a Maricopa parcel its acs5 2021 and decennial 2020 rows — the Census API, not our signing, so no throttle could have helped. Each of the three ended `complete`, and backfill only triggers on failed/missing tasks, so none of them has a healing path. **This row is not "mitigated".** Capping our own call rate narrows one of three doors; a year lost to a Census timeout, a TNM endpoint returning non-JSON (see the zero-topo parcel in the ops audit's §8), or any upstream we have not met yet is still silently dropped under a `complete` task. M4's per-year failure persistence is the actual fix, and it is now scheduled work rather than deferred design — see below. Evidence: `docs/audits/2026-08-ops-audit/FINDINGS.md` §0, HIGH-2, MEDIUM-2. **(4) 2026-08-12, from the geometry sweep: one parcel — `2f1b332e`, Racebrook Road, Orange, Connecticut — still holds only 5 census years (decennial 2010; acs5 2012, 2015, 2018, 2023) against 7–9 for its peers, *after* a full re-run. It is the sharpest instance yet, because nothing in the system can say whether those years re-failed or were never published: the task ended `complete`, no failure was recorded, and the 63 `Census API: no data for tract` 404s observed during the sweep are indistinguishable from genuine absence. Connecticut's 2022 county-to-planning-region change makes genuine absence entirely plausible — which is the point. Telling the two apart is exactly what per-year persistence would buy, and no heal script can be written until it can. Only 3 census rows across 2 parcels were gained sweep-wide, so the opportunistic ride-along did not reach it.** Evidence: `docs/audits/2026-08-geometry-audit/HEAL-SCORECARD.md` §6. *A later commentary restated that ride-along as a net **loss** of 3 rows across 44 parcels; it is a phantom, closed in `docs/audits/2026-08-geometry-audit/CENSUS_TRIAGE.md` — `census_snapshots` has no deletion path, so no census loss is reachable and no new M4 occurrence follows from it. (4) above remains the only occurrence from the sweep.* **Two mechanism gaps recorded 2026-08-15 by the source inventory (`../2026-08-source-inventory/INVENTORY.md`) and tracked as N1 and N2 below.** N1 is a **fourth door, not a fourth occurrence**: `_sas_get` retries only 429 (`stac.py:315-316`), so an unretried PC 5xx or connection error on the signing endpoint returns `False` from `_validate_asset` (`stac.py:1014-1021`), which `_validate_selection` reads as "item is broken" and answers by walking **every** same-period candidate against the same unhealthy endpoint (`stac.py:1111-1127`) before dropping the period (`stac.py:1130`) under a task that still ends `complete` (`timeline.py:435`). N2 names the mechanism behind instance (3): `CensusFetcher._request` has no retry at all (`census.py:249-253`), so **not one of that incident's four `httpx.ReadTimeout`s would have been retried** — this row recorded the outcome, never that the client did not try again. **Neither changes this row's remedy, only its occurrence surface.** Retry-policy work would reduce how *often* a year is lost; only per-year failure persistence makes a loss *visible*, and that is still the scheduled work below. **Deployed 2026-08-26T00:51:55Z. The first full sweep was authorised the same day and did not run — `../2026-08-m4-ledger/GATE-STOP.md`.** Migration `0011` never reached production (X1 below), so `timeline_task_years` does not exist there and the ledger holds nothing. `PREDICTION.md` is **unscored in full**: P1-P6 every one name a population the sweep did not create, and the file is not edited. No `HEAL-SCORECARD.md` and no `BASELINE.txt` exist for this run; a baseline captured before the ledger works would make every later sweep diff against a lie. **`2f1b332e` (Racebrook Road) is unchanged and the ledger still says nothing about it** — occurrence (4) above stands exactly as written, and telling re-failure from genuine absence remains impossible until X1 is fixed and the fleet is swept. Worse than a delay: X2 records that the deployed recorder now fails every timeline request against the missing table. **2026-08-26T01:29Z: X1 and X2 both resolved and deployed** (`edc13db`) — `0011` is applied, `timeline_task_years` exists, and no request was lost in the interim (zero `timeline_requests` created between the `00:52Z` deploy and the fix landing). The ledger now holds nothing only because it has not been swept, not because the table is missing. The sweep itself, and the four occurrences this row names, remain unaddressed. **First full production sweep, 2026-08-26 02:16:35Z-03:04:07Z — the ledger is populated and PREDICTION.md is scored: `../2026-08-m4-ledger/HEAL-SCORECARD.md`, baseline `../2026-08-m4-ledger/BASELINE.txt` (16,244 rows, captured 03:07Z under `3a86dd69211c460cee22245d30605941fdd55168`).** One `revalidate_landsat.py --max-wait-minutes 90` run reached **184 of 184** parcels, exit 0, zero skipped, zero unreached; all 184 requests ended `complete`. Two sentences above are now false and are corrected here rather than rewritten: the ledger no longer holds nothing, and occurrence (4) is no longer undiagnosed. **Every falsifiable prediction held.** P1 confirmed exactly — every parcel recorded 43 `landsat` / 12 `sentinel2` / 17 `naip` / 4 `census_decennial` / 6 `census_acs5` groups, no exceptions, plus 1-10 topo rows; P2 confirmed at 16,244 against 16,100 ± 300; P3 confirmed and tighter than written — Sentinel-2 2015 reads `absent`/`all_cloud_filtered` on **exactly** the nine O6 parcels and `no_scenes` on none, which was the stated falsifier for the empty-chunk probe; P4 confirmed at the floor with **zero `failed` rows fleet-wide**, matched by zero signing failures, zero STAC chunk failures and zero census timeouts in the log capture; P5 confirmed at 8 `indeterminate` (7 NAIP item-cap on one parcel, 1 TNM row-cap), **zero with the `no outcome` reason** — the residual pass that would have signalled a new dropped-group defect did not fire; P6a and P6b both zero. The `ok` set equals the served set row for row on `landsat` (7,912), `sentinel2` (2,199) and both census datasets. **One deviation inside P2, called out in the prediction itself:** the topo split came back 1,154 decade rows over 183 parcels plus 2 `*` rows, not ≈989 over 157 plus 27 — the ledger counts decades in the TNM response, the 6.3/parcel historical average counted decades that produced a snapshot, and PREDICTION §8 flagged that gap as UNVERIFIED before the run. **Snapshot churn was zero, not minimal:** the before-state (02:15:22Z) and after-state (03:07Z) captures of all 12,547 `imagery_snapshots` rows and 1,442 `census_snapshots` rows are identical, so the sweep created and deleted nothing — the fleet was already swept under the S2-year code on 2026-08-25 and reconciliation had nothing to do. **Occurrence (4), `2f1b332e` Racebrook Road, is answered.** Its five missing census years all read `absent`/`api_no_data` with the tract in `detail`: acs5 2009, acs5 2021, decennial 1990, 2000 and 2020 were each asked as *empty response for tract `09170157100`*, while every succeeding year but one was asked as tract `09009157100`. **Not a re-failure — the API returned nothing for the tract we asked about.** Fleet-wide it is the only parcel of 184 missing decennial 2020 and the only one missing acs5 2021, and the 1990/2000 absences are the fleet-wide pattern (decennial 1990 is `absent` on **all 184 parcels**; 2000 on 137; acs5 2009 on 75 — the first measurement ever taken of the `if data:` skip). Whether `09170` is the right tract to ask for a 2020/2021 vintage is a new question, tracked under To investigate. What is settled is that this row's stated blocker — that nothing could tell re-failure from genuine absence — no longer holds. The heal path itself is still M3. **Two findings this sweep produced, neither of them in the ledger:** (a) `e513188c` still *serves* a NAIP 2023 card built from tile `nj_m_4007309_sw_18_030_20230820_20231019` while this run's ledger records that group `suppressed`/`naip_no_point_coverage` on that same item id — the point-coverage gate (`14b59af`) refuses to write such a row but does not remove one already written, and it is the only instance in the fleet; tracked under To investigate. (b) The log capture lost 02:53-02:55Z, 8 of 184 requests, which is why three `suppressed` ledger rows on `8d9ee137` have no matching log line — the ledger held what the capture dropped, which is the instrument demonstrating its own purpose. **Occurrence (4) is resolved in code, pending requeue (`4ce1822`, 2026-08-25; committed, not deployed, and `2f1b332e` has not been re-run).** The mechanism is a **county-equivalent** change, not a tract redistricting: tract 1571 never moved, but Connecticut replaced its counties with planning regions for data tabulated in 2022 (`www2.census.gov/geo/pdfs/reference/ct_county_equiv_change.pdf`), so the same tract is `09009157100` through ACS 2021 and `09170157100` from ACS 2022. The parcel stores the current — planning-region — FIPS, and `_GEOGRAPHY_VINTAGES` named a vintage for only the four years that were failing when `b5a306a` was written; the other six fell through to the stored tract, which is exactly where the county-equivalent change lands. Every year the geocoder can serve now names its own vintage, and no Connecticut rule or crosswalk table was needed — the geocoder already draws the boundary where the data API does (`09009157100` at `Census2010_Current`/`Census2020_Current`/`ACS2021_Current`, `09170157100` at `ACS2022_Current`/`ACS2023_Current`), verified live. **Three of the five missing years come back, not five:** acs5 2009, acs5 2021 and decennial 2020. Decennial 1990 and 2000 are two separate defects found in the same investigation, neither caused by the county code and neither fixed — both are recorded under To investigate below. **One fleet-wide behaviour change rides along:** acs5 2009 now resolves at `Census2010_Current` instead of using the stored tract, so a parcel redistricted in 2010 is asked under its 2010 tract — never worse than today (the 2010 tract is strictly closer to 2009's 2000 geography than the 2020 tract is) and able only to add rows, but a future full-fleet re-run may gain acs5 2009 rows on parcels unrelated to this pass. Report, live API matrix and blast radius: `../2026-08-racebrook/REPORT.md`; the requeue prediction, written before the run, is `../2026-08-racebrook/PREDICTION.md`. **What this does not close:** the heal path is still M3, and the three other occurrences are untouched. **Requeue run and scored, 2026-08-26** (`../2026-08-racebrook/REPORT.md` §10, addendum to `PREDICTION.md`): one `scripts/requeue_parcels.py --require-sha 4330833 2f1b332e-…` invocation against the deployed SHA, exit 0, request `c8e28d15` reached `complete` in 38s with no admission wait. `census_snapshots` went 5 → 8 exactly as predicted — acs5 2009 (2757/1154), acs5 2021 (2453/1144), decennial 2020 (2604/1169), all `09009157100`; the five pre-existing rows unchanged. The ledger's ten census groups came back 8 `ok` / 2 `absent`, decennial 1990 and 2000 still `absent`/`api_no_data` against the stored tract, matching the prediction row for row. `imagery_snapshots` (68 rows, 43/12/6/7 by source) is byte-identical before and after by row id — zero churn. Four `Resolved tract for vintage` log lines, one per distinct vintage, zero fallback warnings. **Occurrence (4) is resolved, not merely resolved-in-code: every falsifiable clause of `PREDICTION.md` confirmed, zero deviations, zero anomalies.** The two other defects the same investigation found — decennial 1990's dead endpoint and 2000's tract-width mismatch — are untouched and remain open below; the heal path for the general M4 shape is still M3. **Both are now measured and fixed in code, 2026-08-26 (`e6afa9b`, committed, not deployed, no sweep run under it) — see their own entries under To investigate and `../2026-08-census-decennial/REPORT.md`.** The measurements in this row stand as taken and are not edited: they were taken over 184 parcels, the fleet is now 186, and the same query on 2026-08-26 reads decennial 1990 `absent` ×186, decennial 2000 `absent` 139 / `ok` 47, acs5 2009 `absent` 74 / `ok` 112. What changes is the reading of them — decennial 1990's fleet-wide uniformity was an endpoint that has never existed, and decennial 2000's was a tract width, on 80 of the 139. Neither was ever about the tracts having no data, which is precisely what an `absent` row asserted and what the reason split now prevents. The first sweep carrying the fix is predicted in `../2026-08-m4-ledger/PREDICTION.md` P7-P11. |
| M5 Sync I/O on the loop | Open | `geocode.py:55-57,146-151`; `timeline.py:310-360`. The worker half is accepted; the autocomplete half is not. |
| M6 Redis socket timeouts | Resolved (dd99cee) | `socket_timeout` and `socket_connect_timeout` of 2s on both clients, matching the DB probe's `statement_timeout`. |
| M7 ORM/schema drift | Open | Partial indexes in `0009:49`, `0010:67,83` absent from `models/parcels.py`; `conftest.py:55-190` still hand-written DDL. **Understated by three items the M4 design investigation found (§1.5): (4) `idx_parcels_address`, the GIN index created at `0001:67-73`, is absent from the ORM; (6) `index=True` on `TimelineRequest.parcel_id` and `TimelineRequestTask.timeline_request_id` implies `ix_*` names while the database carries `idx_timeline_requests_parcel_id` and `idx_trt_request` — harmless today, a duplicate-index hazard for any autogenerate. Item (5) has its own row below.** |
| M7-5 `ck_trt_*` name drift | Open | **The ORM declares `ck_trt_source` / `ck_trt_status` on `timeline_request_tasks` (`models/parcels.py:202-209`); the database has `ck_timeline_request_tasks_source` / `ck_timeline_request_tasks_status` (`0002:117-128`, replaced `0008:35-39`). An `op.drop_constraint("ck_trt_source", …)` written from the ORM would fail against production.** Split out of M7 because it is the only drift item that is a *trap for a future migration* rather than a missing declaration, and `timeline_request_tasks` is the table M4 hangs off. Migration `0011` avoids it by issuing no `ALTER` on that table and naming every new constraint explicitly, with the ORM repeating those names — so `timeline_task_years` starts without drift. UNVERIFIED, still: the prediction that the drop would fail is inferred from migration source, not from `pg_constraint` on production. |
| M8 DO NOTHING freezes records | Open | `property_events.py:74`; `county_adapters.py:473,741`. |
| M9 Titiler callback path | Partially resolved (56d6647) | `/warmup` (30/min as shipped in 56d6647; **60/min since `69b94e1`, 2026-08-04** — `api/imagery.py:624`; corrected here 2026-08-15, see N3) and `/{id}/stac` (600/min) now carry rate limits. The routing itself is accepted — see below. |
| M10 Migration on boot | Partially resolved (dd99cee) | A session-scoped `pg_advisory_lock` in `alembic/env.py` serializes concurrent boots. The worker-ahead-of-schema window is accepted — see below. **This row is now false, 2026-08-26. The advisory lock has never serialized anything, because the state it serializes against is rolled back before a second boot can read it — see X1 below.** Two API machines ran `0010 -> 0011` eighteen seconds apart, both reporting success, and the database stayed at `0010`. *Corrected 2026-08-26: that pair is not evidence about the lock in either direction — `825d69b7e46618` logged `Migrations complete.` at `00:52:28Z` and `48e0de9a713918` logged `Running database migrations...` at `00:52:40Z`, so the boots never overlapped and nothing was contended. The second boot re-ran the upgrade because the version bump had been rolled back.* The lock also silently discards every migration it guards, which is the larger half. Read this row as **Open** until X1 is fixed. **Re-marked 2026-08-26 after X1.** The row's accept still stands on its own terms — migrations to date are additive and the worker-ahead-of-schema window is seconds — and the *race* the lock was added for is real. What was wrong was the implementation, not the diagnosis: as written the lock silently rolled back every migration it guarded, so for 22 days the mitigation for M10 was strictly worse than no mitigation at all. *Dates in this row are UTC: `dd99cee` is authored `2026-08-03T17:56:19-06:00` = `2026-08-04T00:56Z`, and discovery is `2026-08-26`, giving 22 days. Differencing the local calendar dates gives 23, which is what this re-mark said until 2026-08-26; UTC is the convention, because every log timestamp the finding rests on is UTC.* **Resolved again at `edc13db`**, and this time the property has a test — `test_concurrent_boots_from_0010_converge_on_head` runs two real boots against one database from `0010`, holding the lock itself until both are provably blocked on it before releasing, so the contention is forced rather than hoped for. That property had never been tested. **First production observation, 2026-08-26T01:29Z:** `48e0de9a713918` ran the real upgrade and committed; `825d69b7e46618` booted 15s later, found `0011` already at head, and performed no upgrade. That is what the logs show, and it is the first boot pair to run against committed state. *They do not show a lock wait* — the first machine's head check is `01:29:41Z` and the second pulls its image at `01:29:51Z`, so the second boot may never have contended for the lock at all. The serialized outcome is observed; the serialization is not. Detail: `../2026-08-m4-ledger/GATE-STOP.md` addendum. |
| M11 Failures vanish from UI | Resolved (256ed32) | `ParcelInfo.tsx:131-133,268-275`; `DemographicsPanel.tsx:78-95`. |
| M12 Celery config | Resolved (05bb263) | `celery_app.py:31-33,55`; `timeline.py:950-958`. |

## Low

| # | Status | Where it stands |
|---|---|---|
| L1 STAC pagination loop | Open | `stac.py:145-167` — still no page counter. |
| L2 strict-zip landmine | Resolved (ffb71b2) | Groups filtered once, zipped over the filtered list; test covers an empty group. |
| L3 WHERE-clause escaping | Open | `county_adapters.py:48-58` escapes quotes only; anchoring still differs between `:236,:332,:425,:480` and `:697,:759`. |
| L4 STAC fetch host | Resolved (ffb71b2) | Allowlisted to `planetarycomputer.microsoft.com`, the only host any Landsat row carries. |
| L5 Geocoder county fallback | Resolved (3269bbf) | Fallback removed on both paths; `scripts/heal_county_fallback.py` clears rows already carrying one. Dev had zero. |
| L6 TNM caps and ids | Partially resolved (ffb71b2, c82ed51) | Products with no `sourceId` are skipped instead of colliding on `stac_item_id=""`. Pagination is still accepted — see below — but the cap is no longer silent: c82ed51 warns when a TNM query returns exactly its cap (T3 below). |
| L7 `_fetch_source` coordinates | Resolved (ffb71b2) | Defaults removed; two test call sites were relying on them. |
| L8 Autocomplete self-DoS | Partially resolved (the commit carrying this note) | **Clear-before-resolve half: resolved.** `SearchInput.tsx` now defers the clear behind the promise `ParcelInfo` returns from `mutateAsync` (`clearOnSettle`, all four former `setValue("")` sites), so a 422 or 502 leaves the typed address in the box — re-enabled, error underneath — and only success clears it. The three `it.fails` markers in `SearchInput.test.tsx` are gone; those tests are ordinary guards now (5 tests, all green). `SearchBar.tsx` was checked for the same shape and is **not affected, guarded by test**: it sets `value` to the selected address or leaves it alone and never calls `setValue("")`, and `SearchBar.test.tsx` now pins that through the real `useGeocodeMutation` on both captured error fixtures. **Autocomplete half: still open** — `useAddressAutocomplete.ts:12` is still a 150ms debounce against the 60/min/IP limit, and 429s are still swallowed to `[]`. That remainder is a policy-risk item, not only a robustness one: komoot's published posture for Photon is *"Extensive usage will be throttled or completely banned"* with heavy users told to self-host ([source landscape](../../research/SOURCELANDSCAPE202608.md#5-retrieval-pattern-findings-q7--the-rate-limit-gap) §5.5, which names L8's debounce as multiplying exactly the traffic that gets you banned), and per [N4](../2026-08-source-inventory/INVENTORY.md#n4-photon-failure-returns-an-empty-suggestion-list) a throttled or banned Photon is indistinguishable in our UI from an address with no matches, so we would not see it happen. Detail: `docs/audits/2026-08-frontend-tests/05-l8-clear-before-resolve-report.md` (trace) and `06-l8-fix-report.md` (fix). |
| L9 Tile-proxy input | Resolved (ffb71b2) | `z` capped at 0–24; `x`/`y` given one generous static bound, since anything inside it but outside the COG extent already returns a transparent tile. |
| L10 Raw error strings | Open | `schemas/imagery.py:25,38`; `timeline.py:198,402,650`. *2026-08-22: the log half the security audit reopened (SEC-4/SEC-7) is resolved in `52b0223` — `app/redact.py` at the log pipeline and the task-row sinks; the client-facing accept stands.* |
| L11 Prefork engine | Resolved (dd99cee) | `worker_process_init` → `engine.dispose(close=False)`. |
| L12 Misc | Partially resolved (56d6647) | CORS `allow_credentials` dropped. Still open: JSON vs JSONB (`models/parcels.py:323`/`:398`), "declined 0%" (`demographics.py:203-211`), the URL-normalization chain (`config.py:83-89` **and** `alembic/env.py:36-42`), `Dockerfile.fly` running as root with gcc, and DC's hardcoded permit layers (`county_adapters.py:403-411`). |

## Counties reconciliation

Items 1–12 and 14–16 are resolved by c296b3a; `SUPPORTED_COUNTIES.md` was
spot-checked against the adapters and matches, and its 2026-08-03 stamp is
true.

**Item 13 (row caps)** is partially resolved by ae5793a. Pagination is
accepted: five caps spread across three shared clients, built against a
hypothesis about overflow that nothing has yet confirmed. The half that
mattered is implemented instead — each client now logs a warning when a query
returns exactly its cap, naming the resource and the cap, so truncation is no
longer indistinguishable from a complete answer. If those warnings start
appearing in production, that is the evidence pagination was waiting for.

Of the "code oddities": the bare-`Exception` item is resolved by 256ed32; the
module docstring (`county_adapters.py:1-12`) and `parse_date`'s docstring
(`:62-67`) are **resolved in the 2026-08-19 readback batch — see R2 below for the
hash caveat**. The module docstring now names all three platforms rather than
only Socrata, and `parse_date` is described as the shared cross-platform
fallback it actually is, with its four call sites named. DC's unused
`APPRAISED_VALUE_CURRENT_TOTAL` (`:434`) remains open.
e1006df separately fixed the frontend's hardcoded county list, which the
reconciliation flagged in spirit (item 15) but not as a code finding.

## Ops audit (2026-08-12)

A separate read-only audit of *running production*, recorded in
`docs/audits/2026-08-ops-audit/`. Its findings are not second-audit findings;
they are tracked here because two of them change rows above, and because this
file is where the fix commits get cited.

O8 did not come from that audit. It came from a 2026-08-12 investigation of
reported Landsat 502s (`docs/audits/2026-08-titiler-cache/`) and is tracked in
this table because it is the third distinct cause of the same symptom O1 and
G4 describe, and telling the three apart is now the open question.

| # | Status | Where it stands |
|---|---|---|
| O1 Unsigned-href fallback | Resolved (c645208), **act two** (3b7b10e) | **New finding.** A signing failure fell back to the unsigned href at five call sites. Planetary Computer blob storage is private, so that href can only be rejected with a 409 — the audit tied 37 Titiler 500s across 10 snapshots to it, each preceded seconds earlier by a band-signing failure on the same snapshot id. The first audit read this fallback as graceful degradation; it is not degradation, it is a guaranteed user-visible failure manufactured out of a retryable one. Both tile paths now 502 with a curated message; the listing omits what it cannot sign; warmup and the preview renderer skip rather than render. `imagery.py` (API) and `preview_renderer.py:100-106`. No unsigned-fallback site remained in `stac.py` — every signing call there already goes through `sign_pc_url`, which carries the a536d07 limiter and retries. **Act two, 2026-08-12 — the fix's first contact with production.** Converting the fallback into a 502 was right, and it exposed that the thing being retried was tuned for the wrong caller. a536d07's retry honours `Retry-After`, which PC sets around 60s; the tile path's end-to-end budget is ~30s (frontend `AbortSignal` plus the proxy timeout). A Landsat scrub burst at 02:5x–03:00Z produced 23 backoffs — one captured at `attempt: 2, wait_s: 54.0` — and a 502 storm while Titiler itself stayed healthy: every rate-limited tile was being killed by its own client mid-sleep, so the curated message never reached anyone. 3b7b10e splits the policy by context (`SIGN_WAIT_BATCH` 60s for the worker, `SIGN_WAIT_REQUEST` 2s for the four request-path sites) and, structurally, moves blob signing onto PC's container-scoped tokens so the 429s largely stop happening. Two acts, not resolved-then-regressed: the first fix made the failure honest, and an honest failure is what made the latency mismatch legible. |
| O2 Stranded rows | Resolved (2afdfb5) | **New finding.** Eleven task rows sat non-terminal forever: three `processing` under failed "Task timed out" requests, eight `queued` under complete April requests. An OOM kill is a SIGKILL, so the soft-limit handler never runs. A `worker_ready` janitor now fails both shapes past the 45-minute threshold. Note the shape: the parent *requests* were already terminal, so a sweep of in-flight requests alone would have caught none of them. |
| O3 Worker OOM | Resolved (01cfdd6) | **New finding.** A live OOM kill inside a 20-minute log sample, on a 512 MB machine. `fly.worker.toml` now asks for 1 GB. Whether `WorkerLostError` should fail the request promptly is untouched; O2's janitor bounds the damage either way. |
| O4 Deployed-SHA visibility | Resolved (ba62922) | **New finding, and the process gap behind HIGH-1.** Nothing recorded what was deployed, so the audit had to infer the running release from image build dates — which is how it discovered that a536d07 was committed but never pushed. `GET /api/v1/health` now reports the image's git SHA and build time. |
| O5 Damaged parcels | **Resolved 2026-08-12** | Both are now at the full 43-year CONUS span, healed by a `requeue_parcels.py` run at **03:32:22Z** — six minutes *before* the geometry sweep, which added zero rows to either and therefore deserves no credit for it. `7397388e` (`3890 W 44th`) took 40 new Landsat rows across 23:00Z and 03:00Z; `e0cb3db9` (`141 rainbow drive brick`) took 27 at 01:00Z and 16 at 03:00Z. The prescribed ordering held: the throttle was deployed first, and neither re-run re-rolled the dice. Verified by DB, `HEAL-SCORECARD.md`. Original finding follows. `7397388e` (Denver, 20 Landsat years) and `e0cb3db9` (Ocean NJ, 8) were damaged. `scripts/requeue_parcels.py` (d1fadd4) takes ids and re-runs them; it has deliberately **not** been run. Heal only after the throttle is deployed, or the re-run rolls the same dice. The ops audit's Appendix A lists three more candidates (a census-gapped parcel, a vintage-break residue, a zero-topo parcel). |
| O7 Second worker machine "stopped since Aug 4" | **Struck — no action** | The ops audit's Appendix flagged `e7845415f57728` as possibly-unintentional half capacity. It is Fly's standby machine: the hardware-failover twin Fly provisions alongside the primary and keeps stopped until it is needed. Nothing was left behind on Aug 4 and there is nothing to start. The MEDIUM-1 sizing conclusion is unaffected — that was about the live machine's 512 MB, fixed in 01cfdd6. |
| O8 Titiler item cache pins expired SAS tokens | **Resolved (`cf0df2b`, 2026-08-12) — deployed 2026-08-12T19:53Z, prediction scored** | **New finding, and the third distinct cause of a Landsat 502.** Not O1's unsigned-href fallback and not its act-two latency mismatch: here the API signs correctly, all three bands `HEAD` 200, and Titiler still 500s — because rio-tiler caches the fetched STAC item in a module-level `LRUCache(maxsize=512)` with **no TTL** (`rio_tiler/io/stac.py:100-102`, read from the pinned 8.0.5 inside `titiler:1.2.1`), keyed on the item URL. Landsat is the only source whose Titiler URL omits the token — its bands are three separate COGs, so the proxy points Titiler at the constant `/imagery/{id}/stac` indirection — so the cached item pinned a token that outlived its 45-minute expiry until eviction or restart. At 04:17Z production served one expired 4h17m earlier; `?cb=1` on the same URL returned 200 instantly. 24 of 258 Landsat years failing across the six featured parcels. Fix versions the callback URL by the token's expiry, at both the tile proxy and warmup. **Two premise corrections this produced:** (1) `RIO_TILER_CACHE_TTL` does not exist — a first-pass draft added it to `fly.titiler.toml`; `grep -rn RIO_TILER_CACHE` across the running image returns 0, and rio-tiler 8.0.5 has no `CacheSettings`. It was removed before commit rather than shipped as a config line nothing reads. (2) The "4-hour entry shouldn't be possible" flag dissolves — an LRU has no expiry, which also explains why production self-cleared (RiNo 16/43 → 0/43 by 15:5xZ) through cache churn rather than repair. Full report and post-deploy prediction: `../2026-08-titiler-cache/FINDINGS.md`. **Scored 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`):** deployed 19:53Z; §5 items 1 and 2 **confirmed**, item 3 recorded as not independently testable (it is a counterfactual about code no longer running). Two 258-snapshot sweeps 49.2 min apart returned 258/258 200 OK each, the second after sweep A's entries had outlived the token they would have pinned; 432 herd requests straddling a live rotation returned 0 non-200; 0 Titiler 500s and 0 expiry-fallback warnings in the logs. **Correction the scoring produced:** the rotation boundary is the Redis key TTL (`_SAS_CACHE_TTL` = 1200 s), not the 45-minute token lifetime — keys rotate ~25 min *before* the token they name expires, so the fix is more conservative than §4 claimed and rotations are 2.25× more frequent than §5 assumed. Rotation cost is a one-wave latency spike (4.2× median, decayed within ~60 s), not errors. |
| O6 Sentinel-2 unassessed | **Assessed 2026-08-25** | The audit declined to apply a flat "healthy ≈ 30 quarters" threshold: observed counts run 13–35 in a smooth continuum with no bimodality, and cloud-cover filtering makes the expected count location-dependent. Sentinel-2 damage is unassessed, not cleared. Doing it properly needs a per-parcel expectation — available scenes versus selected. **Answered by G8 and measured by the completion sweep** (`../2026-08-s2-year/HEAL-SCORECARD-2.md` §3). Year grouping makes the expectation flat and location-independent — `current_year − 2014` = 12 — so the deficit is `12 − actual` per parcel. Fleet-wide after the 2026-08-25 sweeps: **175 of 184 parcels at exactly 12, nine at 11, none above 12, none holding a duplicate calendar year. The fleet is 9 rows short**, all of them the year 2015 on nine northern-tier parcels that held no 2015 row before the sweep either, with zero STAC failures in the capture to explain the absence. **Those 9 rows are not damage — corrected 2026-08-25 (`../2026-08-s2-year/LOGGING-FIX.md` §4).** The scorecard recorded the S2A-ramp reading as the leading explanation and explicitly unverified; the archive query it named has now been run — production's own bbox, year range and 20-item cap against PC, once with the cloud filter removed and once with it — and **nine of nine classify as cloud-filtered: zero `pipeline-missed`, zero `absent`.** Every one of the nine has 2015 coverage (2–9 scenes, earliest 2015-08-10) and not one scene is below the 40 % threshold; the fleet-wide minimum is 42.7 %, shared by the four Portland parcels on the 2015-10-04 acquisition. The ramp is real but shows up as *how few and how late* the 2015 scenes are, not as absence. No pool reached the 20-item cap, so G8's ordering question does not arise for 2015. **The shortfall is a correct answer to a cloudy year, and no heal exists that would fix it.** The smooth 13–35 continuum the audit saw was the quarter-grouping artefact, not location-dependent cloud filtering. **What remains unassessed is not the count but the *choice*:** the 20-item cap (G8, unfixed) confines 70.3 % of surviving rows to Q4 and 1.8 % to Q1, so each parcel has the right number of cards and a seasonally skewed selection of which scene fills each one. |
| O9 CI path filter diffed against the parent commit, not deployed prod | **Resolved (commit pending push, 2026-08-26)** | **New finding, discovered outside any formal audit.** `.github/workflows/deploy.yml`'s `changes` job diffed each push against its own parent commit, so it answered "did this push touch the backend" rather than "does prod match main." A 2026-08-26 GitHub Actions queue outage collapsed several pushes; when runs did execute, docs-only head commits reported no backend changes while `e6afa9b` (census fix), `794af9f` (pytest-socket guard) and others sat undeployed underneath — prod was on `4330833` with no CI test run covering anything after it. Fixed by diffing against the SHA `GET /api/v1/health` reports as deployed (**O4 is what made this possible** — before O4 there was no machine-readable record of what was actually running), fetched from `https://log0s-plotline-api.fly.dev/api/v1/health`, falling back to the parent commit (with a visible `::warning::`) if health is unreachable, the SHA is empty, or it isn't an ancestor of HEAD, and falling back further to "everything changed" (never to "no changes") if even that fails. The job now logs its base SHA, head SHA, and changed-path list in the step summary so a future queue incident is diagnosable from the run itself. |

## Geometry defect family (2026-08-12)

Measured in `../2026-08-geometry-audit/`, a read-only pass over every
PC-backed `imagery_snapshots` row: refetch the STAC item, parse
`item["geometry"]` with shapely, and compare a real point-in-footprint test
against the bbox test the pipeline actually ran.

**The finding.** 33 of 2,880 assessable rows — 1.2%, 29 Landsat and 4
Sentinel-2 — serve a granule whose footprint excludes the parcel. The
aggregate understates it: on the six featured pages, which are the public
demo surface, **four are affected and 15 timeline cards are wrong**, RiNo's
1987 and 1988 cards among them — the two oldest, the ones carrying the "how
it has changed" narrative.

**The root cause is a single absence.** Nothing in the pipeline read
`item["geometry"]` at all. A STAC bbox is the envelope of the geometry, so
for a rotated WRS-2 parallelogram it overstates coverage badly. The
agreement matrix makes the asymmetry exact: `bbox=N, geom=Y` is empty across
all 2,880 rows and structurally must be. **The bbox filter could never
reject a covering scene — only admit a non-covering one.** That is what
decides the Ocean NJ question below.

| Fix | Commit |
|---|---|
| Point filter tests `item["geometry"]`, falls back to bbox when absent | 2039e64 |
| Sentinel-2 gains Landsat's validation fallback walk | e7d4c6d |
| NAIP year suppressed when no selected tile contains the point | 14b59af |

**Heal executed 2026-08-12** — full-fleet revalidate sweep, 57 parcels,
03:38:30Z → 03:52:16.9Z, zero task failures. Scored against the prediction
below in `../2026-08-geometry-audit/HEAL-SCORECARD.md`. The geometry half
landed; the NAIP half did not fire at all and needs a second pass — the gate
is prospective-only, so the two known-wrong 350 5th Ave 2023 cards are still
being served.

**Remedies rejected on evidence — do not re-propose these without new
numbers.** Both were plausible and both are refuted in the report's §6:

- **`bbox` → `intersects` in the STAC query.** The premise was that the
  20-item cap truncates the covering tile before we see it. It does not
  happen: in **33 of 33** failures the covering item was already in the
  returned pool, typically 13–19 of 20. The one truncation-shaped case (NAIP
  2023 over Midtown) turned out to be genuine data absence. Directionally
  correct as cleanup; it is not remediation, and bundling it with the
  geometry fix would change result sets and muddy attribution of the
  deletion wave.
- **Coverage-aware ranking.** Its premise is scarcity — that we must choose
  between covering candidates on coverage quality. Scarcity never existed:
  13–19 covering candidates per pool, and the cloud-cover cost of choosing
  correctly is under 1 percentage point, occasionally negative (Rodanthe
  2015 improves 25.0% → 1.0%). Revisit only if post-fix spot checks show
  covering-but-marginal picks.

**NAIP is a different defect in the same family, and a recurrence pattern.**
NAIP had zero bbox-vs-geometry failures — its near-axis-aligned quads make
the two nearly identical. What it had instead: the viewport path optimises
coverage *area* and never tests point containment, so a year with no
covering tile is served as the nearest neighbours. Both 350 5th Ave parcels
served a 2023 mosaic that is entirely New Jersey imagery for a Midtown
Manhattan address. That path is the *first* audit's praised "sophisticated
path" — the second time a praised path has been found harbouring its own
version of the failure it was praised for handling. The unsigned-href
fallback (O1) was the first.

**Predicted heal impact, written before the heal runs.** 33 fix-attributable
deletions on the local dataset, each a one-for-one replacement in the same
year/quarter group — the wrong granule deleted, the covering one inserted.
**No timeline should lose a card to the geometry fix.** Separately, the NAIP
gate removes exactly one card: 2023 from each of the two 350 5th Ave
parcels, where PC has no covering tile. Hudson Yards keeps its 2023 card —
`nj_m_4007416_se` contains the point, which is the mosaic design working;
the brief that commissioned this batch expected it to lose one, and that is
wrong. Total churn will exceed 33 for reasons unrelated to the fix (PC's
catalogue has moved since these rows were written), so 33 is the
fix-attributable floor. The worker logs after the heal confirm or falsify
this paragraph.

**Observed, 2026-08-12 — heal executed, sweep 03:38:30Z → 03:52:16.9Z, 57
parcels, 0 failures.** Full scoring in
`../2026-08-geometry-audit/HEAL-SCORECARD.md`; deduped capture at
`/tmp/sweep-capture.log` (≈half the sweep window has no log coverage, so
volume numbers are DB-derived). 119 Landsat rows and 55 Sentinel-2 rows
written; Landsat is **exactly conserved** — 2,451 rows = 57 × 43, every
parcel at 43, zero duplicate year groups — so the one-for-one claim and
"no timeline loses a card" both hold, and Landsat deletions are exactly 119.
Of those, 15 are capture-year 2026 recency and 104 are selection-changing.
On the featured parcels **13 of the 15 named cards were replaced at exactly
the named years**, the only extra year anywhere is 2026, and both parcels
the audit called clean came back clean (Navy Yard: untouched). **Verdict:
confirmed-with-noted-deviation on the geometry half, falsified on the NAIP
half.** Two deviations: Rodanthe's sentinel2 2015 Q3 was not healed (its
covering sibling is in a different quarter group, so the quarter-scoped
selector never had to choose), and the count "33" was measured on the
41-parcel *local* database — none of Appendix A's parcel ids exist in
production, which has 57 parcels and different UUIDs; deduplicated by
address the prod-side target was 22, not 33. **The NAIP prediction is
falsified: zero NAIP rows were created or deleted and both 350 5th Ave
cards survive** — 14b59af drops the uncovered year from the selection, and
`reconcile_source_snapshots` never deletes an *absent* group, so the gate is
prospective-only and cannot clear rows that already exist. Hudson Yards
keeping 2023 is confirmed (its row carries a 3-tile mosaic). The original
pre-revision prediction additionally missed **fallback-upgrade churn** —
parcels whose prior run predated the throttle re-selecting primaries over
stored fallbacks, the mechanism Ocean's `deleted:8` exposed; here it shows
up as 40 of the 55 Sentinel-2 additions landing on just seven parcels.

**Ocean NJ (`e0cb3db9`) — the geometry defect did not cause its gaps.**
Structural, not observational: the bbox filter cannot delete a year, so the
missing years are the signing incident, as O5 has it. Its *surviving* years
are unassessed and it has exactly the coastal, boundary-adjacent profile
that failed at Rodanthe and Hudson Yards. Heal it after the fix is
deployed — `scripts/requeue_parcels.py`'s `--require-sha` gate exists to
make that ordering mechanical rather than remembered.

**Open items the 2026-08-12 sweep surfaced.** G1–G6 were flagged and not
investigated, each evidenced in `../2026-08-geometry-audit/HEAL-SCORECARD.md`
§4. **G5 has since been investigated and fixed** — its row carries the cause
and the commit, and it is the reason G4's attribution is now in question. G7
was found while fixing G5 and is evidenced in
`../2026-08-titiler-cache/FINDINGS.md` §4.2, not in the scorecard. **G8 was not
surfaced by that sweep either** — it is the 2026-08-25 change to the
Sentinel-2 grouping key, filed here because it is the common root of G2, G3
and O6, and because this is where the fix commits get cited.

**The 2026-08-25 S2-year sweep was invoked by a Claude session, not by Ryan**, under a one-time written exception in that session's prompt, so log capture could start before the sweep rather than mid-way through — the §0 problem the geometry scorecard records. It passed a four-line gate first: worker image `GH_SHA=bc1125cd…818f1` and `/api/v1/health` `sha` matching it, zero `queued`/`processing` timeline requests, a DB before-state captured to diff against, and a continuous log stream started 61 s ahead. The only production write was the one `revalidate_landsat.py` invocation; everything else was `SELECT`s and log reads.

**The completion sweep of the same day was invoked the same way, under the same written exception**, and finished the 154 parcels the first run never reached (`../2026-08-s2-year/HEAL-SCORECARD-2.md`). It passed a **five**-line gate: worker image `GH_SHA=37f7931…070a38` on both machines and `/api/v1/health` reporting the same SHA (built `21:38:31Z`), zero `queued`/`processing` timeline requests, a `--dry-run` returning exactly 154 parcels with all six featured present and zero overlap with the 30 already swept, a DB before-state captured to diff against, and a continuous log stream started 26 s ahead. `--since 2026-08-25T19:09:45Z` was used rather than `--skip-swept-since` because the SHA that ran the first sweep is no longer deployed — the case that flag was added for. The only production write was again the one `revalidate_landsat.py` invocation. **Neither run captured the script's exit code**, which is a method gap recorded in that scorecard's §11.2.

| # | Item |
|---|---|
| G1 | **Resolved on `e513188c`, 2026-08-27 — `../2026-08-m3/HEAL-1-e513188c.md`.** `requeue_parcels.py e513188c-… --require-sha 5f3aa7d --sources naip` (deployed SHA `5f3aa7d`) re-suppressed 2023 on the same two tile ids and `reconcile_source_snapshots` deleted exactly that one row on item-id authority; the other 8 NAIP rows and every other source's snapshots are byte-identical before/after, zero admission wait, request `complete`. The parcel's live timeline no longer serves the wrong-place 2023 card. **Premise correction, checked live 2026-08-27: production holds exactly one `350 5th Ave` parcel — `e513188c`, now healed.** `SELECT id, address FROM parcels WHERE address ILIKE '%350 5th%'` returns one row. The frozen record's "two 350 5th Ave parcels" (this row's own text below, and `../2026-08-geometry-audit/FINDINGS.md`'s `81b2d663`/`d2a82e6b`) describes the **local** geometry-audit dataset that heal was run against, not production — neither prefix exists in the production `parcels` table. This row's own blast-radius measurement names `1754635c` (Chattanooga, TN) and `8d9ee137` (a different address) as the fleet's other `suppressed` rows; neither is a 350 5th Ave parcel and neither has a served row to delete (both `False` on the served-snapshot check, per the measurement below). **There is no second production target of this shape — G1 has no further pending heal.** Original row follows, describing the gate as it stood before this heal. **The gate can now clear a wrong card it already wrote — fix landed `a6c7800`, 2026-08-26; committed, not deployed, and `e513188c`'s 2023 card is still served as of 18:07Z that day.** `reconcile_source_snapshots` takes the group keys **this run** recorded `suppressed` together with the item ids the suppression positively named, and deletes a served row in one of those groups whose item id is named — even though the group is absent from the selection, which is what rule 3 otherwise protects. Three conditions keep it narrow, and all three are in the docstring where someone would go to widen it: **this run's outcomes, not a ledger query** (a suppression corrected since must not license a delete years later); **item ids, not periods** (a different item that happens to fall in the same year was never judged and is left alone); and **`suppressed` only** — `naip absent/no_scenes` alone is 1,848 latest ledger rows fleet-wide, so a rule that deleted on absence would delete on the largest population in the ledger, and `failed` knows strictly less than `absent`. `suppressed/no_cog_url` is carried alongside `naip_no_point_coverage`, which the design investigation §4.3 asked to be decided separately: the item-id condition is exactly what makes it safe, and zero production rows have ever carried that reason. Topo's suppressions are **not** carried — `topo_no_source_id` fires precisely because the product has no id to match on. **Blast radius, re-measured 2026-08-26 18:18Z:** nine `suppressed` rows are latest fleet-wide and a served-snapshot check is `True` for exactly one of them (`e513188c`/2023); the other eight (`1754635c` ×5, `8d9ee137` ×3) are `False`, so a full sweep under this rule should delete **one row, total**, and deleting more would mean the item-id condition is not working. The pending heal and its falsifiers are `../2026-08-m3/PREDICTION.md` P1; the delete-the-fix pair is `test_reconcile_deletes_a_group_this_run_suppressed` and its inverse `test_reconcile_does_not_delete_on_an_absent_outcome`, which matters more. `scripts/remove_uncovered_snapshots.py` is not superseded — it is the hand-verified, network-proving deletion tool for a row no run will re-suppress; this closes the case where a re-run *does*. Original row follows. **NAIP suppression is prospective-only. Tool committed (`56a82ec`, 2026-08-12); production execution pending, so both production cards are still wrong as of that date.** 14b59af removes an uncovered year from the selection; `reconcile_source_snapshots` deliberately never deletes an *absent* group, because absence usually means a failed search. The two rules compose into a hole: the gate cannot clear a wrong card that already exists, which is every parcel the audit identified. Both 350 5th Ave 2023 cards still serve `nj_m_4007309_sw`. **Condemnation re-verified against live PC STAC 2026-08-12** (read-only, production search parameters): the 2023 NAIP search over both parcels' bbox returns exactly 3 items — `nj_m_4007424_ne_18_030_20230820_20231019`, `nj_m_4007416_se_18_030_20230820_20231019`, `nj_m_4007309_sw_18_030_20230820_20231019` — all New Jersey quads, **none containing the point**, unchanged from the audit's 2026-08-11 check. Still a data gap, so the remedy is deletion, not re-selection. **Remedy: `scripts/remove_uncovered_snapshots.py`**, the system's first intentional deletion outside reconciliation. Named `--parcel-id`/`--source`/`--year` triples only — no pattern matching, no all-parcels mode, no source-wide mode; dry-run by default, and in that mode it makes no network calls at all; `--execute` refuses unless every tile of each target row's mosaic is fetched from PC and shown to exclude the parcel point, and refuses on unverifiable evidence (an unmappable tile URL, an item PC won't serve) rather than deleting on partial proof. Deletions run in one transaction, each logged with parcel, source, year, stac_item_id and the reason string. Tests: `backend/tests/test_remove_uncovered_snapshots.py` (13). The guard is load-bearing, not decorative: pointed at Hudson Yards — whose 2023 row carries the *same* primary item — it refuses, because that parcel's point falls inside both `nj_m_4007309_sw` and `nj_m_4007416_se`. **Deletion is permanent rather than a dice re-roll**, traced and replayed against live PC: the gate at `timeline.py:292` → `stac.py:627` (→ `stac.py:574`) drops 2023 from the NAIP selection (`[…2021, 2022, 2023]` → `[…2021, 2022]`), so the `groups` set `reconcile_source_snapshots` builds (`imagery.py:626-628`) carries no 2023 bucket and its stale test (`imagery.py:646`) can never mark a 2023 row — no delete cascade, no re-insert. **Run against the local database only** (2 rows deleted, NAIP 300 → 298, Hudson Yards' 2023 row intact); the production execution is Ryan's, post-push. The prediction for that run is written in `../2026-08-geometry-audit/HEAL-SCORECARD.md` (addendum, 2026-08-12) *before* it happens: exactly one row per named parcel, both timelines losing exactly the 2023 card, Hudson Yards and every other NAIP row untouched, and no `naip` 2023 group re-created by a subsequent re-run. |
| G2 | **Rodanthe sentinel2 2015 Q3 unhealed. Expected resolved by the S2-year sweep; unscored.** Still the 25.04 % non-covering granule from Appendix A. Its 1.01 % covering sibling sits in Q4, a different quarter group, so the quarter-scoped selector never had to choose. 1 of the 15 featured cards remains wrong. **The grouping key that caused it is gone as of G8 (`6489018`)** — under year grouping both granules sit in one 2015 group, the 1.01 % sibling wins on cloud, and reconciliation deletes the 25.04 % row. Prediction P5 in `../2026-08-s2-year/PREDICTION.md` states the expected end state (exactly one 2015 row, dated 2015-10-21) and what would falsify it. Not scored: the fix is committed, not deployed, and no sweep has run as of 2026-08-25. **Scored 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD.md` §6): unscored, unchanged.** The S2-year sweep ran that day against the deployed fix but reached only 30 of 184 parcels — it aborted on an uncaught `AdmissionRefused: queue_full` at parcel 31 — and Rodanthe was not among them. Its 34 S2 rows are byte-identical before and after: 2015 still holds both the 25.04 % granule (2015-07-26) and its 1.01 % sibling (2015-10-21), and 2017 still holds four rows. The featured card is still wrong. P5's Rodanthe half is neither confirmed nor falsified; it needs a sweep that reaches this parcel. **Resolved — scored 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD-2.md` §6): P5 confirmed exactly.** The completion sweep reached Rodanthe. Its 34 S2 rows collapsed to **12**. 2015 now holds exactly one row — `S2A_MSIL2A_20151021T155022_R011_T18SVE_20210412T184030`, 2015-10-21 at 1.007 % — and the 25.04 % 2015-07-26 granule is deleted, which is the item id and date P5 named. 2017's four rows (02-12, 05-03, 09-20, 12-14) collapsed to one, 2017-02-12 at 0.038 %, the lowest-cloud member. **The featured card is now right**, and Rodanthe carries no duplicate calendar year. |
| G3 | **One duplicate S2 quarter group. Expected resolved by the S2-year sweep; unscored.** Green Valley Ranch holds two 2026-Q1 rows, created 2026-06-12 and -06-17 — *before* this sweep and not caused by it. 2026-Q1 was not in the run's selection, so the absent-group rule left it alone; re-running cannot clear it. **G8 (`6489018`) does not change the absent-group rule — it makes the group reachable.** 2026 is now one group holding all four of GVR's 2026 rows (03-08, 03-26, 06-29, 07-11), so the run selects it and reconciliation collapses it to one. Prediction P5 in `../2026-08-s2-year/PREDICTION.md` calls the pick as 2026-08-20 (0.00 % cloud, an insert) and predicts fleet-wide zero parcels holding two S2 rows in one calendar year. Not scored: committed, not deployed, no sweep run as of 2026-08-25. **Scored 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD.md` §7): unscored, unchanged.** Green Valley Ranch was not among the 30 parcels the sweep reached (see G2). Its 22 S2 rows are unchanged and 2026 still holds four (03-08, 03-26, 06-29, 07-11). P5 named 2026-08-20 at 0.00 % as the pick; a *different* swept parcel in the same Denver tile (`d42a8170`) did take `S2C_MSIL2A_20260820T173901_R098_T13TDE…` at 0.0084 %, which corroborates the replay and nothing more. Untested here. **Resolved — scored 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD-2.md` §7): P5 confirmed exactly.** The completion sweep reached Green Valley Ranch. Its 22 S2 rows collapsed to **12**, and 2026's four rows (03-08, 03-26, 06-29, 07-11) collapsed to **one**: `S2C_MSIL2A_20260820T173901_R098_T13TEE_20260820T223509`, **2026-08-20 at 0.0002 %** — the exact date P5 called, at the cloud it called, and an insert as it called. The prior-corroboration note above is now a direct confirmation. Fleet-wide, **zero** parcels hold two S2 rows in one calendar year. |
| G4 | **Signing storm on the request path during the sweep.** 41 × `SAS rate-limited; backoff exceeds wait budget, giving up`, 17 × `Band signing failed after retries`, 115 Titiler 500s across 5 snapshots. This is O1's act-two mismatch running the other way: the batch path exhausts PC's limit while the request path's 2 s `SIGN_WAIT_REQUEST` gives up at once. A user browsing during a sweep gets 500s. **Attribution now in question:** G5's mechanism produces an identical 500 with no signing failure preceding it, so an unknown share of the 115 is cache-pinned tokens rather than rate limiting. The two are separable in the logs — a G5 500 carries an `se` earlier than its own request time and has no `Band signing failed` line seconds before it on the same snapshot id. Testable post-deploy: whatever survives `cf0df2b` is genuinely G4. **Still untested as of 2026-08-12T20:49Z.** The post-deploy observation (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`) saw 0 Titiler 500s and 0 backoff-exhaustion lines, but no heal sweep was running during it — G4's premise is a batch path exhausting PC's limit *concurrently with* browsing, and that condition never obtained. The clean reading bears on G5/O8 only; G4's share of the 115 remains unmeasured and needs a browse observed during an actual sweep. |
| G5 | **Resolved (`cf0df2b`, 2026-08-12 — deployed 19:53Z, scored clean; see O8 and `../2026-08-titiler-cache/BOUNDARY-BASELINE.md`).** **Cause identified: Titiler's rio-tiler item LRU pinning a SAS token under the constant `/imagery/{id}/stac` URL.** `rio_tiler/io/stac.py:100-102` caches fetched items in a module-level `LRUCache(maxsize=512)` with **no TTL**, keyed on the URL — and Landsat's callback URL was constant per snapshot forever, so the token frozen in the item's band hrefs outlived its 45-minute expiry until eviction or restart. Two independent captures of the shape: `se=2026-08-12T00:00:52Z` at 03:34 (`../2026-08-geometry-audit/HEAL-SCORECARD.md` §4.5) and `se=2026-08-12T00:00:38Z` at 04:17 (`../2026-08-titiler-cache/FINDINGS.md`). **Correction to the original row and to the framing that these were one token:** they are two tokens minted 14 s apart, both expiring ~00:00:4xZ — which is what per-URL caching of per-snapshot items predicts and a single shared token does not. Fix versions the callback URL by the token's expiry. Full report: `../2026-08-titiler-cache/FINDINGS.md`. |
| G7 | **Resolved (`2168124`, 2026-08-12 — deployed in `b2019e4` at 2026-08-12T21:13Z and verified running at a live boundary; see the post-fix scoring at the end of this row).** **No single-flight on a cold container token.** `_container_token` (`stac.py:422-467`; this row cited `337-367` from the moment it was written, which was never that function — a stale pointer predating this batch, corrected here) has no in-flight coalescing, so concurrent misses each mint their own token. Measured: 120 band signings on a **warm** token cost 0 PC round-trips; on a **cold** token, 120. A live attempt at the same measurement drew an immediate 429 from `/api/sas/v1/token/landsateuwest/landsat-c2`. Predates `cf0df2b` and is a property of `_container_token`, not of the URL versioning — but the versioning sharpens the simultaneity, since every Landsat key now rotates on the same token boundary. Bounded, not unbounded: `PC_SIGNING_CONCURRENCY` (4) caps in-flight calls and a536d07 retries 429s. Unfixed by choice — bundling a concurrency change into a cache-key fix would make both harder to score. **Observability added (this commit, 2026-08-12):** every mint now logs `SAS container token minted container=<c> se=<ts> ms=<n>` at INFO from `app.services.stac` — one line per PC token call, so concurrent duplicate mints each appear. Counting those lines at a token boundary is the before/after any single-flight fix will be scored against. **Baseline captured 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`):** `BASELINE: 6 minted + 0 exhausted at boundary 2026-08-12T20:17:06Z; worker mints: none; ms range: 670–830`. 18 Landsat keys rotating together produced 6 concurrent mints from one API machine, all returning the identical `se` — the no-single-flight fan-out, confirmed in production rather than in a local harness. **Three refinements to this row's framing:** (1) the boundary is the 20-minute Redis TTL, not the 45-minute token lifetime, so rotations are 2.25× more frequent than the row assumed; (2) the fan-out is per concurrent *band signing*, not per request — one `/stac` callback signing three bands produced 3 mints at 19:56:48–49Z, so a single request is already concurrent with itself; (3) Landsat is not the largest herd — the same cold window produced 13 mints on `sentinel2-l2` and 8 on `naip`, so G7's scope is `_container_token`, not the Landsat path that surfaced it. The 6 is a floor: it was measured at concurrency 6 from one client, and the bound is mint latency (~0.8 s) × arrival rate. Nothing rate-limited at this load (`K` = 0). **The fix (`2168124`, 2026-08-12).** One in-flight `asyncio.Task` per (event loop, container); followers await it shielded so a caller that gives up cannot cancel the mint the others need. Sited inside `_container_token`, below the per-request band gather, because refinement (2) above means a single request is already concurrent with itself — coalescing above the gather would not have caught the 19:56 shape. Per-container, so it covers `sentinel2-l2` and `naip` as well as `landsat-c2`. The `30caec4` log line is unchanged in format and emission point and now fires once per cold miss, which is what makes it the before/after instrument. **Accepted bound: one mint per process per container per boundary, not one globally.** Two API machines can still mint two. A Redis `SET NX` lock would close that at the cost of a poll loop and a Redis-down failure mode on the cold path, to remove a second mint that measured harmless — 13 concurrent mints on `sentinel2-l2` and 8 on `naip` in one cold window drew 0 429s and 0 errors (`K` = 0). The assumption this rests on — that PC's token endpoint tolerates a low-tens-per-boundary mint rate — is recorded as a comment in `_container_token` at the site where anyone would add the lock. It should be revisited if machine count grows well past 2 or if boundary 429s appear. **Refresh-ahead: rejected, not deferred.** See the FINDINGS addendum for the evidence that would reopen it. **Related, separate commit (`e8c857c`, 2026-08-12, deployed in `b2019e4` the same date):** the container-token cache TTL now derives from the token's own `se` less a 300 s margin instead of the fixed `_SAS_CACHE_TTL` (1200 s). Refinement (1) above identified that constant as the rotation cadence; investigating it found it inherited rather than derived (600 s in `9ea33d9` against a believed ~30 min token life, doubled in `3b7b10e` when 45 min was measured) and found no constraint requiring a 25-minute margin — every URL-issue-to-blob-read path is a single request bounded by a 10–30 s client timeout, and the `/stac` `Cache-Control` is already capped at the token's own remaining life. Rotations now fall ~40 min apart rather than ~20, so the herd arrives 2.25× less often. Consequence carried in the same commit: `_STAC_URL_BUCKET_S` drops 600 → 120, since the wall-clock fallback bucket must stay under the life a cached token is guaranteed to have left, and that guarantee is now 300 s. **Scored post-deploy 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`, addendum):** `POST-FIX: 2 minted (1 per machine) + 0 exhausted at boundary 2026-08-12T22:04:12Z; worker mints: none; ms: 238, 657; cadence 40 min 0 s; spike 4.3× one wave, decayed in 113 s`. Three of the four prediction clauses confirmed outright — ≤1 mint per process per container (18 keys rotating together now cost one mint per machine, against 6 from one machine pre-fix; cold-start `sentinel2-l2` 13 → 1 and `naip` 8 → 1), `K` = 0 with 0 429s and 0 non-200 of 308 client requests, and the cadence at exactly 40 min 0 s between consecutive mints under continuous demand. The fourth is a partial deviation, recorded rather than smoothed: the latency spike matched on magnitude (4.3× against a predicted ~4.2×, one wave) but decayed in 113 s against the predicted ~60 s. Attributed to measurement — this run's waves were ~28 s apart against the baseline's ~21 s, and its item cache was colder — and specifically *not* to the fix, since mint count fell 6 → 2 and mint latency 670–830 ms → 238/657 ms, so a mint-dominated spike would have shrunk and did not. The refresh-ahead reopening condition (`K` > 0 or boundary 429s with both fixes deployed) did not appear, so refresh-ahead stays rejected. Not exercised by this run: the post-fix *boundary* for `sentinel2-l2` and `naip` — both keys died inside the capture but no request arrived to trigger a mint, so their 13 → 1 and 8 → 1 figures are cold-start, not boundary. |
| G6 | **An ArcGIS query hit its row cap** (DC property layer, cap 20, 03:48:33Z). This is the evidence the counties reconciliation's item 13 said it was waiting for; pagination is no longer building against an unconfirmed hypothesis. |
| G8 | **Sentinel-2 now groups by calendar year, not quarter (`6489018`, 2026-08-25; committed, not deployed, and no sweep run as of that date). This is a selection-changing edit with a deletion wave behind it — prediction written first, in `../2026-08-s2-year/PREDICTION.md`; full report in `../2026-08-s2-year/REPORT.md`.** The quarter key is the common root of O6, G2 and G3, and the gate that authorised the change found the mechanism behind all three to be something none of those rows names. **The cause of half-empty quarter groups is not cloud filtering.** Measured over 5 parcels × 47 quarters against live PC STAC, read-only, 2026-08-25: of 118 empty quarter groups, **0** were cloud-filtered, **10** were pre-mission (2015 Q1/Q2 on every parcel — S2A's first usable scene over the sample is 2015-07-26), and **108** had scenes that passed the 40 % threshold and that the pipeline could never see. The reason is the interaction of two things already in the record: the year-chunked S2 search caps at 20 items per year (`timeline.py:81`) and `search_stac` sends no `sortby` (`stac.py:132-137`). **PC's observed ordering is strictly newest-first** — 60/60 year-searches came back non-increasing in datetime — so a saturated parcel-year's entire candidate pool runs from late December backwards to a cutoff in Q4 or Q3, and **Q1/Q2 are structurally unreachable whatever the sky did**. Production's Q3/Q4-heavy S2 rows are that signature, and the only years carrying Q1/Q2 rows are the unsaturated ones (2015, partial mission; 2026, partial year). **This refines, and partly corrects, T4/T5's ordering finding:** the STAC spec does promise nothing about unsorted ordering — that stands — but the server's behaviour is not arbitrary, and the difference is load-bearing, because a deterministic newest-first order empties Q1/Q2 *systematically* rather than sparsely. Recorded as measurement, not contract: PC could change it without notice. **What changed:** three S2-only sites — `selection_scope` `"quarter"` → `"year"` (`timeline.py:88`), `select_sentinel_items` buckets `by_year` (`stac.py:930-956`), and `validate_sentinel_selection`'s period lambda becomes `d.year` (`stac.py:1197-1218`). `SELECTION_SCOPES["quarter"]` is **kept and marked unused** (`imagery.py:591-599`); Landsat, NAIP and topo derivations are byte-identical to `17dc9be`, which P4 states as a falsifiable zero-churn claim. Four docstrings/comments that asserted quarter grouping were corrected in the same commit, including `reconcile_source_snapshots`'s scope table (`imagery.py:621-623`) — the contract its whole safety argument rests on. **Tests (471 passing, from 469):** delete-the-fix verified by actually reverting each half — selector+validator reverted gives 3 failures, `selection_scope` reverted *alone* gives 2, which is why `test_every_stac_source_scope_matches_its_selector` exists: it runs every STAC source's selector over two scenes one quarter apart and asserts the scope's bucket function agrees, so a scope/selector disagreement — the one way reconciliation deletes rows the selector never reconsidered — cannot ship green. **What this unlocks for O6:** the expected count becomes `current_year − 2014` (12 in 2026) and the deficit `12 − actual` becomes a per-parcel damage figure. O6 is not resolved by this batch and its row is untouched; it becomes *answerable*, and P6 records the prediction for that measurement before it is run. **Newly recorded, unfixed, and the real next defect: the 20-item cap itself.** It costs a saturated year 75–95 % of its candidate pool and confines survivors to Q3/Q4 — under quarter grouping that emptied half the groups; under year grouping it only biases *which* scene a year holds, which is why this pass does not fix it. The cheapest remedy is one line — send `sortby: eo:cloud_cover` ascending, so the cap keeps the scenes the selector is about to minimise over. Landsat carries the same cap and the same no-`sortby` search (`timeline.py:69`); its grouping is already annual so no group is lost, but its per-year pick is drawn from the same December-backwards window. Unmeasured, out of scope for an S2 pass. **Deployed 2026-08-25T18:57:59Z and swept the same day; scored in `../2026-08-s2-year/HEAL-SCORECARD.md`.** The sweep reached **30 of 184 parcels** and stopped: `revalidate_landsat.py` catches `IntegrityError` around `_create_queued_request` but not `AdmissionRefused`, so the first `queue_full` refusal — inevitable at parcel 31, since `max_inflight_timeline_requests` is 30 — aborted the batch. **Prediction vs observed:** P1 **confirmed exactly** (30/30 parcels at precisely 12 S2 rows, one per calendar year 2015–2026, zero duplicate years, zero parcels below 12); P7 **confirmed** (Q4 share of surviving rows 42.1 % → 70.0 %); P4 **falsified in letter, upheld in substance** — 2 Landsat rows and 31 topo rows moved against a predicted zero, but NAIP churn was exactly zero, Landsat is conserved parcel-by-parcel at 43, both Landsat swaps are one-for-one inside the open year 2026, and all 31 topo rows are first-fetch backfill on four parcels that held **no** topo rows at all, so no closed group outside S2 was touched and the leak reading the prediction was written to catch is not supported; P2, P3, P5 and P6 **unscored** because the population they name was not swept. Measured churn on the 30: **423 S2 rows deleted, 6 added**, all six in the open year 2026 and five of them genuine recency — 777 → 360 rows, which is 30 × 12 with no residual. Log and DB agree to the row (31 reconcile events summing to 425 deletions = 423 S2 + 2 landsat) on a capture with **no gaps**, the stream having started 61 s before the sweep. **The 154 unswept parcels still carry the quarter-grouped shape — every one of them holds at least one duplicate calendar year, including all six featured parcels — so the user-visible half of this change has not shipped.** **Resolved as of `d6b21b3` (2026-08-25; committed, not deployed and not yet swept as of that date): the `AdmissionRefused` gap is G9.** The 154 unswept parcels are still unswept; the completion sweep has its own dated prediction in `../2026-08-s2-year/PREDICTION.md` (addendum A1–A7), calibrated from the 30 — ~1,788 S2 deletions and ~31 additions on those 154, not the ~2,170 a rate-based extrapolation gives, because the swept 30 averaged 25.9 S2 rows against the remaining 154's 23.4. **Observed, full fleet, 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD-2.md`):** the completion sweep reached **all 154** remaining parcels and every request completed (154/154 `complete`, 0 `failed`), so the fleet of 184 is now swept under year grouping. **A1 confirmed on both falsifiable clauses** — zero parcels above 12 and **zero parcels holding two rows in one calendar year, fleet-wide** — with 145 of 154 at exactly 12 and nine at 11, all nine missing only 2015 and all nine having held no 2015 row before the sweep either. Fleet total **2,199** S2 rows against A1's 2,208 estimate; the 9-row shortfall is exactly those nine. **A2 confirmed on both bands:** **1,818 deleted** (predicted ~1,788, band 1,700–1,900) and **52 added** (predicted ~31, band 10–80); the identity `3,605 − 1,818 + 52 = 1,839` holds exactly, vindicating the identity over the rate — the brief's rate-based ~2,170 was 19 % high. Of the 52 additions, 42 are open-year re-picks, 9 are first-fetch backfill on `bd70afa6` and **one** is a genuine closed-year selection change (`f54492d9` 2024, taking 0.0078 % over an existing best of 0.0171 %). **A3 confirmed:** all 154 parcels at exactly 43 Landsat rows, **zero closed-year deletions**, all 9 Landsat deletions one-for-one swaps inside 2026 — and 8 of the 9 traded *down* on cloud, 1 equal, none better, which with the first sweep's 2 makes 10 of 11. **A4 confirmed on topo and falsified in letter on NAIP:** all **23** zero-topo parcels gained rows (150 total), zero topo deletions, nothing added to a parcel that already had topo; NAIP was predicted at exactly zero but gained **6** rows — all on `bd70afa6`, the one parcel of the 154 holding zero NAIP, which A4's own inputs table records and its NAIP line then did not account for. Nothing was deleted from NAIP or topo anywhere, so the leak reading P4/A4 were written to catch is again **not** supported. **A3's named unknown resolved:** `bd70afa6` gained on three sources at once — landsat 34→43, sentinel2 5→12, naip 0→6 — so its missing years were transient search failures, not real absences. **A5 falsified on its named population:** `bd70afa6` is *not* below 12, and the nine that are form a northern-tier cluster (38.7–47.5° N; eight PNW/NorCal, one Lake Michigan shore), not the coastal/boundary set P6 named. **A6 confirmed on all six featured parcels** — 16, 16, 22, 23, 34, 23 → **12 each**, no duplicate calendar year on any of them, so **the user-visible half of this change has now shipped**; the first scorecard's "has not shipped to any featured page" is no longer true. **The 20-item cap finding sharpens rather than softens:** fleet-wide Q4 share of surviving S2 rows goes 48.3 % → **70.3 %**, reproducing the 30-parcel sweep's 70.0 % to within 0.3 points on a population five times larger and differently distributed. **70 % of every S2 card Plotline now serves is an October–December scene and 1.8 % is a Q1 scene** — the cap remains unfixed and is still the standing explanation. Log and DB reconcile to the row (163 reconcile events summing to 1,827 deletions = 1,818 S2 + 9 landsat) on a capture with **no gaps**. |
| G9 | **The re-queue script family aborted the whole batch on an admission refusal. Resolved (`d6b21b3`, 2026-08-25; committed, not deployed, and the completion sweep has not run as of that date).** `revalidate_landsat.py`, `requeue_parcels.py` and `requeue_empty_property.py` all caught `IntegrityError` around `_create_queued_request` and nothing else, so the first `AdmissionRefused` propagated out of `main` and abandoned every parcel behind it. With `max_inflight_timeline_requests` at 30 (`app/config.py:92`) and a sweep that enqueues far faster than the worker drains, that refusal is the steady state rather than an exception: the 2026-08-25 S2-year sweep reached **30 of 184 parcels** and died at parcel 31, 13 s in (`../2026-08-s2-year/HEAL-SCORECARD.md` §2, §11.1). **Why 2026-08-12 never hit it: the cap did not exist.** `app/services/admission.py` was introduced by `b606d18` on 2026-08-22 — ten days after the geometry sweep — and the file is absent at `b606d18~1`, so that sweep's 57 parcels enqueued under no admission regime at all. The scripts were written before the callee could refuse; this is not a regression. **The fix:** `wait_for_admission_slot` (`app/services/admission.py:81-140`) polls `inflight_depth` — the same query `ensure_admission` gates on, so the wait and the gate cannot disagree about what full means — and `create_queued_request_waiting` (`app/services/imagery.py:137-173`) wraps `_create_queued_request` in it, keeping the return contract and the `IntegrityError` behaviour. All three scripts gain `--max-wait-minutes` (default 60), name the parcels they never reached, and exit non-zero, so an incomplete sweep cannot read as a complete one from an exit code — which is how the 30/184 truncation went unnoticed until the rows were counted. The kill switch is deliberately never waited out. `revalidate_landsat.py` also gains `--skip-swept-since <sha>` / `--since <ISO>` so a follow-up run completes a fleet instead of re-running it. **Accepted limitation, load-bearing and commented at the site:** nothing in `timeline_requests` records which code a request ran under (no SHA column), so `--skip-swept-since` resolves the SHA against the running `/api/v1/health` and uses that image's **build** time, which precedes rollout by the tail of the CI job; a request created in that gap ran on the old code and would still be skipped, and `--since` exists to be exact. **Tests:** 14 added, 483 passing, delete-the-fix run on both halves. Full report, citations and UNVERIFIED register: `../2026-08-s2-year/ADMISSION-FIX.md`. **First production run, 2026-08-25 (`../2026-08-s2-year/HEAL-SCORECARD-2.md` §2): the fix works, and its instrument does not reach the operator.** Deployed as `37f7931…070a38`, `revalidate_landsat.py --since 2026-08-25T19:09:45Z --max-wait-minutes 60` reached **all 154** parcels, printed `Done — queued 154 timeline request(s), skipped 0.`, and emitted no `unreached:` line and no traceback. `wait_for_admission_slot` was exercised **112 times**: the 112 `Admission refused` warnings and the 112 inter-arrival gaps ≥ 1 s measured from `created_at` agree exactly — one refusal, one wait, every wait opening a slot. Total time waiting **1,994.9 s of a 2,007.2 s enqueue span (99.4 %)**; mean 17.8 s, median 15.5 s, longest **50.7 s**; the 60-minute budget was never approached. **Newly recorded defect, unfixed:** `configure_logging()` is called only from `app/main.py:24` and `app/tasks/celery_app.py:70`, and no script calls it, so a script's root logger has no handler and Python's last-resort handler emits WARNING-and-above only, to stderr, stripped of structured fields. The `Admission refused` warnings arrived as the bare two-word message and **all 112 `Waiting for an admission slot` INFO lines — carrying the `depth`/`cap`/`wait_remaining_s` fields `d6b21b3` added precisely so an operator could watch a wait — were discarded**. Every wait figure above had to be reconstructed from DB timestamps. The fix is instrumented; the instrument is not connected, and the same is true by inspection of `requeue_parcels.py`, `seed.py` and the heal scripts. **Also recorded:** neither sweep captured the script's exit code, so A7's exit-code clause is inferred from the output rather than measured — a method gap in the sessions, not in the script. **Instrument connected (`b05458b`, 2026-08-25; committed, not deployed and no sweep run under it as of that date).** `configure_script_logging()` (`app/logging_config.py:77-99`) is `configure_logging` with a caller-supplied renderer — always console, colours only on a tty, because a script's stdout is an operator's terminal and `app_env == "production"` would otherwise render JSON at a human — and it is now the first statement of `main()` in nine of the ten entry points in `scripts/`. **The defect was never specific to the three scripts `d6b21b3` touched: none of the ten configured logging**, and the two that called `logging.basicConfig(level=INFO, format="%(message)s")` mid-`main()` stripped the structured fields anyway; both lost it. `seed.py` is the one deliberate exception — it imports nothing from `app`, emits no log records, and the import would break its documented repo-root invocation — recorded as a comment at the site with the condition that ends it. **Tests: 2 added, 485 passing, delete-the-fix run** (removing the call from `requeue_parcels.main()` makes the wait line vanish from stdout entirely, not merely lose its fields); the assertion is on **stdout, not `caplog`**, because pytest attaches its own handler to the root logger and a caplog-based test passes with the fix deleted. An inventory test fails on any future script that logs into the void. Report: `../2026-08-s2-year/LOGGING-FIX.md`. **`b05458b`'s instrument was inert under CI's environment (`LOG_LEVEL=WARNING` set by `tests/conftest.py`, mirroring a production-tuned deploy): `configure_script_logging()` read `settings.log_level` same as `configure_logging()`, so the root logger stayed at WARNING and every admission-wait INFO line was dropped again, one layer above the original defect. Fixed in `b537953` (2026-08-25; committed, not deployed): `configure_script_logging()` now forces `level=logging.INFO` unconditionally. Verified under both a normal shell and `env -i`; 488 tests passing, delete-the-fix run both ways. Addendum: `../2026-08-s2-year/LOGGING-FIX.md` §6.** **`b537953` deployed 2026-08-26T00:51:55Z and is still unobserved in production.** Its only planned exercise was the M4 sweep, which stopped at the gate before any parcel was enqueued (`../2026-08-m4-ledger/GATE-STOP.md`), so the `depth`/`cap` fields on the admission-wait line have now been verified under CI and under a local shell, and never once against a real sweep. The exit-code method gap noted above is likewise still open for the same reason. **First production observation, 2026-08-26 (`../2026-08-m4-ledger/HEAL-SCORECARD.md` §2.1): `b537953` works, and both open items above are closed.** Under `3a86dd69…`, `revalidate_landsat.py --max-wait-minutes 90` reached all 184 parcels and the admission-wait line arrived complete with its structured fields — first captured line, verbatim: `2026-08-26T02:16:49.226244Z [info     ] Waiting for an admission slot  [app.services.admission] cap=30 depth=30 poll_seconds=5.0 wait_remaining_s=5389.9`. **`depth` and `cap` appeared: yes.** **135** wait episodes over **460** poll lines, every one reading `depth=30 cap=30`; total wait **2,342.4 s of a 2,379.0 s enqueue span (98.5 %)**, mean 17.4 s, median 15.3 s, longest **30.5 s**, 1-6 polls per episode, and `wait_remaining_s` never fell below ~3,010 of 5,400. Unlike 2026-08-25, none of this was reconstructed from `created_at` — it is parsed from the log lines. **The exit-code method gap is closed too:** the run was invoked with the exit code captured and returned **0**, printing `Done — queued 184 timeline request(s), skipped 0.` with no `unreached:` line. **Newly recorded, unfixed:** the wait lines reach the operator only on the `fly ssh console` channel — `fly logs -a log0s-plotline-api` carried **zero** matches for them across the whole 53-minute window, because the script is not the machine's main process. A sweep whose stdout is not captured at the invocation site leaves no record of its waits anywhere. |

## Topo/NAIP coverage review (2026-08-13)

A review of what the imagery paths can and cannot know about their own
coverage. Not an audit of running production and not a second-audit finding —
tracked here for the same reason the ops and geometry sections are: one of its
items changes the M4 row, and this file is where fix commits get cited.

| # | Item |
|---|---|
| T1 | **Topo survey dates do not exist in any reachable structured source. Negative result — recorded so nobody spends a day hunting for the API parameter.** A topo sheet's *publication* year is not the year its content depicts; a quad published in 1965 can carry a survey a decade older, and photorevision adds a third date. Every date we can obtain is the publication one: the TNM `/products` response carries `publicationDate` and nothing else date-bearing, and the FGDC XML reachable via a product's `vendorMetaUrl` tags its date range `<current>publication date</current>` — i.e. the metadata explicitly declares its own dates to be publication dates. Survey and photorevision dates are printed in the **map collar** — the marginalia of the scanned sheet itself — so recovering them means OCR over the collar, per sheet, with per-series layout variation. That is the whole cost of the feature, and it is why the honest remedy was presentational. **Remedy shipped (`94443cf`, 2026-08-13):** topo cards render "Published 1965" rather than the capture-date format "Jan 1965", and the three surfaces that show a topo date carry a one-sentence caveat (`TOPO_DATE_CAVEAT` in `frontend/src/constants.ts`) saying publication is not survey. No migration and no schema change — `capture_date` still holds Jan 1 of the publication year; the fix is that the UI stops asserting a precision the column never had. **Provenance caveat on this row:** the TNM-and-FGDC negative result is carried over from the coverage review that commissioned this batch and was **not** re-verified against a live TNM response or a live `vendorMetaUrl` fetch in the batch that wrote this row. The remedy does not depend on it; a future reader who wants to reopen the question should re-check those two responses first. |
| T2 | **The 1900 fallback. Resolved (`c82ed51`, 2026-08-13).** `extract_publication_date` was `year = _publication_year(item) or 1900`, so a product whose `publicationDate` would not parse was persisted as `1900-01-01` and rendered as a genuine 1900 sheet — a fabricated date, indistinguishable from a real one, in the column the timeline sorts on. It now returns `None` and the persistence loop skips the product with a warning, matching the `sourceId` skip added a few lines below it in ffb71b2. The task still reports `complete`: one dropped sheet is a gap, not a failure, and "complete with zero" and "failed" stay distinct states. **The fallback was latent, not live** — `select_topo_items` (`usgs_topo.py:113-117`) already drops items whose year will not parse, so nothing reached `extract_publication_date` with a bad date, and no existing row can carry a fabricated 1900. It was a landmine under any future caller, and the guard now sits in the loop where such a caller would land. Grep for the shape found no other `or <literal year>` / `or <sentinel date>` fallback in the backend; the one near-miss, `str(i.get("publicationDate", "9999"))` at `usgs_topo.py:126`, is a sort-key default that is never persisted. |
| T3 | **The topo cap was unverified and silent. Mitigated (`c82ed51`, 2026-08-13); pagination deliberately not built.** `search_usgs_topo` issues one un-paginated TNM query with `max=100`, and TNM documents no ordering guarantee — so a response holding exactly 100 products was indistinguishable from a complete answer, and a truncated pool would drop whole decades (`select_topo_items` picks one sheet per decade from whatever it is given). Pagination is **not** the remedy, for the reason counties item 13 gave: it would be built against an overflow hypothesis nothing has confirmed — the L6 accept records that no one has verified a real quad exceeds 100 products, and that is still true. The accepted instrument is the same one instead: the client now logs `TNM query hit its row cap — results are truncated` with the resource and the cap, in the message shape the ArcGIS/CKAN/Socrata clients gained in ae5793a, so all four grep together. That instrument has already paid once — G6 is the DC ArcGIS cap-hit that turned item 13's hypothesis into evidence — and this is the same bet on the same terms: if the line appears in production, that is when pagination gets built. The check counts raw products before the GeoTIFF filter, because truncation happens upstream of that filter. *2026-08-27 — **the line has now appeared in production a second time, on a new parcel, and the bet's terms are met on both sides.** The retry/ops scoring sweep produced a `TNM query hit its row cap` warning and moved `e513188c`'s `usgs_topo` `*` group from `absent` to `indeterminate`, taking the fleet's `usgs_topo` `indeterminate` count 1 → 2 (`../2026-08-ops-batch/SWEEP-SCORECARD.md` §6). The same run wrote **nine new `ok` topo decade triples** for that parcel — 1880s, 1890s, 1900s, 1930s, 1940s, 1950s, 1960s, 1980s, 1990s — where the ledger had held a bare `absent`. So the instrument caught a real truncation on a parcel that gained coverage in the same breath: TNM answered with more than it did before, hit the cap, and the ledger declined to call the remainder absent. This was flagged as a deviation by the sweep's regression check, which expected zero new `indeterminate` sites; it is recorded as one, and it is better data rather than worse. **Two cap-hits on two parcels is the evidence L6 said was missing.** Whether that is enough to build pagination is a decision, not an observation, and it has not been made.* |
| T4 | **NAIP early-year truncation — OPEN HYPOTHESIS, not supported by the evidence available locally. No code change.** The claim under test: NAIP is the only imagery source not chunked by year — one search over 2003→present with `max_items=50` — and result ordering causes early years to fall off the pool on dense-coverage parcels, indistinguishable from a real flight gap. **Both mechanism premises are confirmed in code.** NAIP is un-chunked: `"chunk_by_year": False` (`timeline.py:54`) sends it down the single-search branch at `timeline.py:260-271`, one query over `2003-01-01/<current year>-12-31` with `max_items=50` (`:49`); Landsat (`:66`, from 1984) and Sentinel-2 (`:78`, from 2015) take the year-chunk loop at `:224-259` at 20 items per year. And the pool really is one page: `search_stac` sets `limit = min(max_items, 100)` = 50 and only follows a `next` link while `len(items) < max_items` (`stac.py:136,149`), so a first page of 50 ends the walk — NAIP never paginates in practice. **The ordering premise is a separate finding, and it is worse than the hypothesis states.** `search_stac`'s payload (`stac.py:132-137`) carries `collections`, `bbox`, `datetime`, `limit` and an optional `query` — **no `sortby`**. STAC leaves unsorted ordering unspecified, so which 50 items survive the cap is not a property we control or have observed; it is not "newest first". The comment at `timeline.py:222` asserting a "default 'newest first' ordering" as the *reason* for chunking is an unverified claim in the code, and it should be read as motivation rather than fact. **Local measurement (41 parcels, 298 NAIP rows, read-only) does not support the hypothesis and inverts its predicted signature.** The prediction is early years absent on parcels with many NAIP rows and present on sparse ones. Observed: no parcel holds a single row before **2010**, the fleet-wide year histogram starts at 2010 (5 parcels) and 2011 (32), and 2003–2009 is empty everywhere — across CO, NY, DC, CA, NC, NV, UT, ID, IL, PA and OH. Grouped by pool size, parcels with 5 rows and parcels with 10 rows alike hold **zero** 2003–2010 rows, while the only two parcels holding any sit at 9 and 11 rows; the parcels reaching furthest back (both 350 5th Ave parcels, Hudson Yards, Philadelphia — 2010) are the *densest*, not the sparsest. A cap that ate early years would have eaten theirs first. The pattern that is present — CA parcels starting 2012, UT 2011, CO 2011 — has the shape of state NAIP flight cycles and of the collection's own start, not of a per-parcel cutoff. **Verdict: refuted on the correlation it predicts; the underlying truncation *risk* is confirmed as real and remains unmeasured.** What the local DB cannot see is the raw returned pool — we persist one row per selected year, never the search's item count — so no local query can say whether any parcel's search returned exactly 50. That is the gap; the SQL below cannot close it, and the honest instrument would be the T3 treatment applied to `search_stac` (warn when a search returns exactly its cap). Not built here — this task was investigate-only. **The 350 5th Ave 2023 case is NOT evidence for this hypothesis.** It was investigated and closed as genuine data absence: PC returns exactly 3 items for that bbox and year, all New Jersey quads, none containing the point (`../2026-08-geometry-audit/FINDINGS.md` §4, and R4, which records the truncation hypothesis it was tested against and rejected). Citing it as truncation evidence inverts the record. The same parcel holds 2010 and 2013 NAIP rows (Appendix D of that report), which is a second point against. **Read-only SQL for production, to be run by Ryan — not run from here:** `SELECT naip_rows, count(*) AS parcels, round(avg(early_rows),2) AS avg_2003_2010, count(*) FILTER (WHERE early_rows = 0) AS parcels_with_no_early FROM (SELECT parcel_id, count(*) AS naip_rows, count(*) FILTER (WHERE extract(year FROM capture_date) BETWEEN 2003 AND 2010) AS early_rows FROM imagery_snapshots WHERE source='naip' GROUP BY 1) t GROUP BY 1 ORDER BY 1;` and `SELECT extract(year FROM capture_date)::int AS yr, count(*) AS rows, count(DISTINCT parcel_id) AS parcels FROM imagery_snapshots WHERE source='naip' GROUP BY 1 ORDER BY 1;` — production has 57 parcels against the local 41, so it is the larger sample, but it is the same measurement and inherits the same blind spot. |
| T5 | **T4's three loose ends, closed (`3a2e716`, 2026-08-13; committed, not yet deployed as of 2026-08-13).** *(a) The 2010 floor is the collection's edge, not a symptom.* The Planetary Computer `naip` collection's own temporal extent starts 2010: `GET /api/stac/v1/collections/naip` returns `"temporal": {"interval": [["2010-01-01T00:00:00Z", "2023-12-31T00:00:00Z"]]}` (fetched read-only this session; the interval's *end* trails the data and is not treated as a ceiling). So 2003–2009 NAIP rows are structurally impossible from this source, everywhere, for every parcel. This is the whole explanation of T4's fleet-wide 2010 histogram floor — it is not truncation, and it is not flight cycles; T4's residual "state flight cycle" reading applies only to the 2011/2012 state-by-state variation *above* the floor. Recorded for the same reason as T1's negative result: nobody should investigate a gap that is the source's own edge. *(b) The config now matches.* `start_date` moves `2003-01-01` → `2010-01-01` (`timeline.py:56`) with the extent cited at the site. **Result-set-neutral by construction:** the removed range is empty at the source, so the item set the search draws from is identical before and after. **The load-bearing evidence for that emptiness is T4's measurement, not the collection record's authority** — zero pre-2010 rows across 41 parcels and 298 NAIP rows, in eleven states; the collection's declared start is the confirmation of *why*, not the proof. The asymmetry matters and is deliberate: a collection's start date is a curation decision, and here observation corroborates it, so clamping the query to it is safe; a collection's end date is ingestion lag, which the holdings can outrun at any time and which no measurement can confirm as an edge — the fleet's NAIP rows stop at 2023, exactly where the extent does, so the two readings are indistinguishable there and the conservative choice is not to clamp. The same metadata is trusted at one edge and distrusted at the other because the evidence differs at each edge, not because the document is authoritative.  the cap therefore selects from the same pool under the same (unspecified) ordering, and the per-year selector sees the same years. The change stops the query asserting six years the source never had — it cannot add or remove a row. *(c) The undecidable half is now instrumented.* T4 could not say whether any NAIP search ever returned exactly its 50-item cap, because only selected rows are persisted, never search counts. The un-chunked branch (`timeline.py:295`) now logs `STAC search hit its item cap — results are truncated` with source, collection, cap and date range — the ae5793a message shape the ArcGIS/CKAN/Socrata clients and T3's TNM check carry, so all five grep together. **Deliberately NOT blanket:** it lives on the un-chunked branch rather than inside `search_stac`, because Landsat and Sentinel-2 saturate their 20-item per-year pools as routine operation on dense years and a blanket warning would bury the one signal this exists to catch. Pagination remains unbuilt on the same terms as T3 and counties item 13: if the line appears in production, that is when it gets built. *(d) The false ordering comment is gone.* `timeline.py:228-233` now states that no `sortby` is sent, that STAC leaves unsorted ordering unspecified, and that chunking exists to bound the per-year candidate pool regardless of server ordering — replacing the "default newest first" claim T4 identified. **Not changed, and deliberately:** the user-facing "2003" copy in `README.md` (:17, :24, :28, :77, :209) and the seeded featured-location description in `scripts/seed_featured.py:31`. Product wording is the owner's call; the code no longer agrees with it. |
| T6 | **The user-facing "2003" copy, corrected (`518c965`, 2026-08-13; committed, not yet deployed as of 2026-08-13). Production's `featured_locations` rows are NOT yet updated — the SQL exists, unrun.** T5 left the product wording to the owner; this closes it. Three range claims in `README.md` move to the verified floor: the intro (`:17`) and the data-source table (`:77`) now say 2010, and the caveats section (`:209`) says the NAIP *program* dates to 2003 but the Planetary Computer collection Plotline reads begins 2010, with the two-year state flight cycle noted — a parcel's first aerial is usually 2011 or 2012, which is what T4's histogram shows (2010: 5 parcels; 2011: 32). **Two of the items were not overstated ranges but false claims on the demo surface.** The Stapleton and Green Valley Ranch featured blurbs promised "NAIP imagery from 2003 shows [demolition / empty grassland]" while the timeline a visitor actually gets starts 2011 — measured this session, read-only: both parcels hold exactly 7 NAIP rows, 2011/2013/2015/2017/2019/2021/2023, alongside annual Landsat 1984–2026, Sentinel-2 from 2015, and 7 topo sheets from 1890. The pre-2010 half of each story is Landsat's, not NAIP's. **New, not in T4's inventory: the Navy Yard blurb (`README.md:30`) carried the same false claim** — "NAIP imagery from the early 2000s shows rail yards and warehouses" — against measured NAIP coverage of 2011–2023 (10 rows). Fixed in the same batch. The `scripts/seed_featured.py` blurbs for the same two locations were also *already* drifted from the README's (the seeded Green Valley Ranch text asserted no year at all); both files now carry identical imagery sentences. **Visual-content claims were removed rather than re-dated, deliberately.** A claim about what a picture shows cannot be checked from the database — only the years can — so the corrected blurbs assert coverage and dates only. Re-dated visual narratives were drafted as proposals for the owner and are not in the repo. **The live rows need SQL, and the seed script is not the safe path to it.** `seed_featured.py` does upsert on `slug` (`:174-186`), so re-running it would fix the descriptions — but it re-geocodes every address first and waits on timeline jobs, so it is a write path against production parcels for a text change. `scripts/featured_naip_copy_2026-08-13.sql` is the narrow instrument: a read-only SELECT of the current descriptions plus each parcel's real NAIP coverage, then two `UPDATE ... WHERE slug = ...` in a transaction. **Prediction, recorded before the run:** STEP 1 returns the two old "2003" descriptions and NAIP `first_year` 2011 for both; STEP 2 reports `UPDATE 1` twice. The years in the SQL's text were verified against the *local* 41-parcel database — if production's rows for these slugs show a different first year, the wording is wrong and the run should stop. Outcome to be recorded here. |

## Source inventory (2026-08-15)

A read-only inventory of every external source the codebase talks to,
recorded in `../2026-08-source-inventory/INVENTORY.md` (commit `7e93c02`) and
commissioned to brief an external research pass on alternative and additional
sources. Like the ops, geometry and topo sections above, its findings are not
second-audit findings; they are tracked here because two of them bear on the
M4 row, one corrects the M9 row, and this file is where the fix commits get
cited.

It is a **code pass, not an observational one**: the local stack was not
running, so nothing in it rests on a row count, and nothing in it can be read
as evidence about production. Every claim carries a `file:line` — 589 of them,
all resolved and range-checked against `103ddab`, and re-verified against HEAD
`7e93c02` when these rows were written. `7e93c02` changed no code, so no
premise moved between the two.

N1–N5 are **recorded, not fixed**, and no remedy is proposed for any of them
beyond what the inventory itself states. That absence is deliberate: N1 and N2
are retry-policy decisions that interact with M4's scheduled work, and picking
a retry policy before deciding where per-year outcomes live would fix the
cheap half first.

| # | Status | Where it stands |
|---|---|---|
| N1 | **Resolved (`70437e6`, 2026-08-27), deployed 2026-08-27T18:29Z at `7807c4d` — swept, and the retry is still unobserved: pending first transient.** The 189-parcel scoring sweep (`../2026-08-ops-batch/SWEEP-SCORECARD.md`) met **zero** SAS signing failures — no 429, no 5xx, no transport error — so `_sas_get`'s new retry loop was never entered in production. Zero `"SAS signing failed; backing off"`, zero budget give-ups, zero `sign_5xx` / `read_timeout` / `connect_error` ledger rows, zero `failed` rows of any kind. P-2 confirmed at zero; **P-1 scored `not exercised`, which is not a pass.** The code is running and untested against a real outage. Log capture covered 183 of 189 requests, so the count is a lower bound; the ledger check, which is exact, agrees. | **SAS signing retries only 429; a transient PC 5xx or connection error is terminal.** `_sas_get` branches on `resp.status_code != 429` and calls `raise_for_status()` on the spot (`stac.py:315-316`), and `httpx.RequestError` is never caught inside the loop at all — so a 503 from `/api/sas/v1/token/…`, or a reset connection, fails on the **first** attempt, with none of the 4 attempts, the semaphore, or the wait budget applying. The function's own docstring argues that a 429 means "slow down", not "this asset is broken" (`stac.py:297-299`); the same is true of a 503, and the code does not act on it. **The worker path is where it costs a year.** `_validate_asset` catches the raised error and returns `False` (`stac.py:1014-1021`); `_validate_selection` reads that as "item is broken" and answers by walking **every** same-period candidate (`stac.py:1111-1127`) — each of which signs against the same unhealthy endpoint — then drops the period with `WARNING "No valid %s item for %s; skipping"` (`stac.py:1130`) under a task that still ends `complete` (`timeline.py:435`). Note the asymmetry with the search path, which does retry `{429, 500, 502, 503, 504}` **and** `RequestError` (`timeline.py:94, 125-130`). Recorded against M4 above as a fourth silent-gap door, not a fourth occurrence. *2026-08-27, `70437e6`: the retry set is now Microsoft's own — `[429, 500, 502, 503, 504]` from `urllib3.util.retry.Retry` in `planetary_computer/sas.py`, read from source — plus `ConnectError` / `ReadTimeout` / `RemoteProtocolError`. 4xx other than 429 stays terminal. Backoff is jittered upward by <=25%, applied after the budget decision and clamped to the remaining budget so a 54 s `Retry-After` under the 60 s batch budget still sleeps rather than giving up. `SIGN_WAIT_BATCH` / `SIGN_WAIT_REQUEST` are unchanged in value but now bound **elapsed** time rather than sleep alone — see the accepted row below for why, and `../2026-08-ops-batch/REPORT.md` §1 for the request-path worst case (12 s in `_sas_get`, 42 s end to end on a tile, +2 s against before). Committed, not deployed as of 2026-08-27; prediction in `../2026-08-ops-batch/PREDICTION.md`.* |
| N2 | **Resolved (`8a86fad`, 2026-08-27), deployed 2026-08-27T18:29Z at `7807c4d` — swept, retry unobserved: pending first transient.** The scoring sweep ran the census task on all 189 parcels — ~9 Census API requests each — and met **zero** retryable failures: no `ReadTimeout`, no `ConnectError`, no 5xx. Zero `"Census API request failed; retrying"` lines, zero `http_5xx` ledger rows, P-3 confirmed with `http_404` still at zero. Census wrote **no rows at all**: every dataset/year id- and content-checksum is byte-identical across the sweep. **But the sweep did meet one transient census-path failure, and `8a86fad` does not cover it** — see Z6 below. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §0, §6. | **The Census data API client has no retry at all.** `CensusFetcher._request` issues one `GET` and converts any `httpx.HTTPError` — timeout, connect error, read error — straight into `CensusApiError` (`census.py:249-253`). No attempt loop, no backoff, no distinction between a retryable and a permanent failure. The only pacing anywhere on the path is `await asyncio.sleep(0.5)` between years (`timeline.py:689, 715`), which is politeness, not retry. **This is the mechanism behind M4's instance (3):** four `httpx.ReadTimeout`s against `api.census.gov` cost a Maricopa parcel its acs5 2021 and decennial 2020 rows, and **not one of those four would have been retried**. M4 recorded the outcome; nothing on this ledger recorded that the client never tried again. Both the geocoder (`geocoder.py:30, 139-147`) and the STAC search (`timeline.py:97-135`) retry — among our three upstream clients this one is the outlier. *2026-08-27, `8a86fad`: `_get_with_retry` (`census.py:414`) takes 3 attempts over `ReadTimeout`, `ConnectError` and `{500, 502, 503, 504}`, jittered, honouring `Retry-After`. 4xx stays terminal so `CensusHttpStatusError` from `e6afa9b` keeps doing its job. The 65 s per-request budget is sized against the task that contains it: 3 x `census_api_timeout` (30 s) + backoff = 93 s per request, 9 requests per parcel, ~841 s against `soft_time_limit=1800` (`tasks/timeline.py:1608-1609`); a test pins that arithmetic to both constants. Committed, not deployed as of 2026-08-27.* |
| N3 | **LOW (record drift) — corrected in this commit** | **The M9 row above stated the `/warmup` limit as 30/min; it has been 60/min since `69b94e1` (2026-08-04).** 56d6647 did ship 30 — `RateLimit(times=30, seconds=60)` at that commit — and `69b94e1` ("perf: warm a snapshot once per session, not once per scrub hop") raised it to 60 without the row following; `api/imagery.py:624` reads `RateLimit(times=60, seconds=60)` at HEAD. The `/{id}/stac` half (600/min) is still accurate (`api/imagery.py:721`). The M9 row is corrected in place in the same commit as this row. It is recorded rather than silently fixed because the drift, not the number, is the finding: the row was true when written and nothing made it false out loud. *2026-08-22: `/warmup` is now 120/min (`api/imagery.py:658`, `52b0223`), and the bucket is per route template rather than per snapshot (SEC-3).* |
| N4 | **LOW — Open** | **A Photon failure returns an empty suggestion list.** Both `httpx.RequestError` and `httpx.HTTPStatusError` are answered with `return []` (`api/geocode.py:77-82`), so a Photon outage, a 429, and "no US address matches this prefix" reach the caller — and the user — as the same empty dropdown. It is the complete-with-zero shape the second audit named as this system's characteristic reflex, on the one path where **nothing is persisted**: unlike census or property, no backfill, heal or query could ever notice. *2026-08-27: still open, and deliberately so — it is the same shape as the Socrata 404 collapse fixed in `2c3f468`, and the grep for that shape (`../2026-08-ops-batch/REPORT.md` §4) found it again at `api/geocode.py:80, :83`. It ships with L8 in the frontend pass, not here.* Contained, which is why it is LOW and not MEDIUM — a typed address still geocodes through the Census geocoder, and the 300 s cache does not store empty-on-failure any differently from empty-on-success. |
| N5 | **LOW (second-order) — Open** | **The host allowlist guards one of the five paths that hand a stored URL to a fetcher.** `_ALLOWED_STAC_HOSTS` (`api/imagery.py:336-340`) constrains the API's own Landsat item fetch, and the comment above it gives the reason: without it "a `cog_url` written by a compromised upstream would make the API fetch an attacker-chosen URL from inside the network" (`api/imagery.py:330-335`). The same stored values also reach Titiler as the `url` query parameter on four other paths — `_proxy_cog_tile` (`api/imagery.py:484-486`), warmup (`api/imagery.py:646-648, 665-668`), the Landsat callback URL (`api/imagery.py:556-557`) and the preview renderer (`preview_renderer.py:113-116`) — with **no host check on any of them**, for NAIP, Sentinel-2 and USGS topo alike. Topo is the widest case: that URL comes straight out of TNM's `urls.GeoTIFF` and is never inspected (`usgs_topo.py:134-140`). The exposure is the same second-order shape the existing comment already reasons about — it needs a compromised or malicious upstream, and the value is written by our own worker — but the mitigation landed on one path and not the other four. `CPL_VSIL_CURL_ALLOWED_EXTENSIONS = '.tif,.tiff'` (`fly.titiler.toml:19`) narrows what GDAL will open; it does not constrain the host. **2026-08-22: resolved by P5 in `52b0223` — one shared allowlist now guards all five paths; see the security-audit section below.** *2026-08-27, re-verified for the retry/ops batch, which had it queued as still-open: `prd-tnm.s3.amazonaws.com` is on the allowlist (`stac.py:293`) and the topo tile path goes through `_refuse_unlisted_host` (`api/imagery.py:486`). Production read: 1183 `usgs_topo` rows in `imagery_snapshots`, **one** distinct host over `cog_url` / `thumbnail_url` / `additional_cog_urls`, and it is that one — nothing needed allowlisting. What was missing was coverage of the route rather than the function: `6daf621` adds both halves, an unlisted host 502ing without reaching Titiler and the real TNM host being served, each verified by deletion.* |

## Readback (2026-08-19)

A whole-system read of the codebase against HEAD `3487647`, commissioned to
prepare for an external technical review rather than to find defects. It is
recorded here because it found one, and because it is the first pass whose
purpose was *explaining* the system rather than auditing it — which turns out
to surface a different class of problem: prose that has drifted, and code
nothing has had to justify out loud.

**The commits.** `9d07dbb` carries the R2 prose corrections and no code;
`297976c` fixes the container tool-cache ownership problem the readback tripped
over (root-owned `.ruff_cache` / `.mypy_cache` / `.pytest_cache` written into
the bind mount, after which the same tools fail on the host). This section is
their ledger counterpart, in the fix-then-record order `518c965` → `103ddab`
used. **Committed, not yet deployed** as of 2026-08-19 — irrelevant to
behaviour here, since neither commit changes any running code path.

**A note on line numbers, because this batch is its own illustration.** The
R2 docstring edits shifted every line below them, which invalidated ~50
citations in the briefing that prompted this section and 18 lines of citations
*in this file* — rows written by earlier passes, still accurate in substance,
silently wrong in their pointers. All of them are refreshed against HEAD here
(`stac.py` +4, `db.py` +5, `celery_app.py` +2, `county_adapters.py` +2 before
`parse_date`, +7 after). The frozen documents under `docs/audits/` are **not**
refreshed and should not be: they are records of a moment, and this file's
header already states that line numbers here are HEAD's, not the audit's.
Correcting prose about code is itself an edit that dates other prose about
code — which is R2's own finding, arriving one level up.

| # | Status | Item |
|---|---|---|
| R1 | **HIGH — Open, scheduled** | **The NAIP mosaic selector's viewport branch has zero test coverage, and it is the function that produced G1.** `select_naip_items` (`stac.py:734-867`) has two behaviours: a legacy single-tile path when `viewport is None`, and the greedy multi-tile mosaic path when a viewport is supplied. **The production pipeline only ever calls the second** — `timeline.py:314-317` passes `viewport_bbox` for every NAIP run — and `pytest --cov` reports `stac.py:772-865` uncovered, which is that entire branch: the viewport-area guard, the greedy candidate loop, the coverage-target early exit, and the residual-rectangle update. Both `select_naip_items(` call sites in `tests/test_stac.py` (`:82`, `:98`) pass no viewport, so the 83 tests in that file exercise only the path production never takes. The gap matters more than a coverage number because of what the untested code does: it tracks "remaining uncovered viewport" as **a single rectangle**, and says so at `stac.py:821-825` — "This is an approximation (a union of tiles is not a rectangle), but good enough for a few-tile mosaic." That approximation has never been tested against a case where it is wrong. It is also the path behind the geometry family's NAIP half: the selector optimises coverage *area* and never asks whether any tile contains the point, which is how both 350 5th Ave parcels came to serve an all-New-Jersey 2023 mosaic for a Midtown address (G1). Note the asymmetry that makes this sharp — **the downstream gate is tested and the algorithm is not**: `filter_groups_containing_point` has two direct tests (`test_stac.py:1692, 1703`), neither of which routes through `select_naip_items`. So the safety net has coverage and the thing it is catching does not. Scheduled below. |
| R2 | **LOW (record drift) — corrected in `9d07dbb`** | **Five pieces of prose described code that HEAD contradicts.** All five are corrected in the same batch as this row; none is a code change. (1) **`scripts/requeue_parcels.py:17-26`** stated in the present tense that "the imagery point filter tests each STAC item's *bbox envelope* rather than its real footprint" — true when the deploy gate was written, false since `2039e64` (2026-08-11). The gate's *rationale* was unaffected and remains correct, so the paragraph now names the three selection-time commits it exists to order against (`2039e64`, `e7d4c6d`, `14b59af`) instead of describing a defect that is fixed. This was the most misleading of the five: a reader could reasonably have concluded the geometry defect was still live. (2) **`README.md`, cross-source comparison** claimed "The timeline reprojects and crops to a shared bounding box." Plotline reprojects nothing and crops nothing — Titiler warps each COG to `WebMercatorQuad` per tile request, and only the *primary* raster source carries `bounds` (`applyImageryLayer.ts:70-83`). Rewritten to say the shared frame is the tile grid, and to state plainly that nothing resamples to a common ground resolution and each source carries a fixed display stretch. (3) **`tasks/celery_app.py:1-7`** still read "Phase 1: The worker is wired up and running, but tasks are no-ops. Phase 2 will add real tasks" — false since Phase 2 in March. (4) **`services/stac.py:1-9`** called itself a "STAC API client"; it is 1,172 lines that also own spatial filtering, three per-source selectors, asset extraction and validation. (5) **`app/db.py:1-11`** read "synchronous session for Phase 1 simplicity" and did not mention the two loop-keyed Redis client families the module also owns. Plus the two county docstrings the counties section had already flagged (see above). **The finding is the shape, not the five instances**, and it is the same shape the analysis in DEVELOPMENT.md names: prose written *about* code drifts, prose written *alongside* it survives. Four of these five sat in files that were edited repeatedly after the docstring stopped being true — the docstring is simply not what anyone reads when they open a file to change one function. |

**Not corrected, deliberately.** Two stale claims were found and left alone
because the documents holding them are frozen by policy:

- **DEVELOPMENT.md's "110 commits" and "Four and a half months."**
  `git rev-list --count HEAD` is **179** at `3487647`, spanning 2026-03-16 →
  2026-08-19; 70 commits landed after `6def10c`, the HEAD the provenance
  analysis was run against. The number is not wrong, it is *anchored* — and
  `docs/provenance/ANALYSIS.md:3-5` states the anchor explicitly. The Build Log
  is frozen and the analysis section is editable only on the owner's
  instruction, so this is recorded rather than fixed. Anyone who runs the count
  will notice; the honest answer is that the figure describes the analysed
  window, not HEAD.
- **`../2026-05-first-audit/FINDINGS.md:132`**, the Redis caching claim.
  Already handled correctly and needs nothing: the document stays frozen, and
  `../2026-08-source-inventory/INVENTORY.md`'s caching ledger is the annotated
  correction of record.

## Security audit (2026-08)

A read-only security assessment of the public surface, recorded in
`../2026-08-security-audit/` (`SURFACE.md`, `FINDINGS.md`, `URGENT.md`, all
frozen at `8c8907f`). Its findings are not second-audit findings; they are
tracked here for the same reason the ops, geometry, topo and source-inventory
sections are — one of them re-triages the M9 accept below, and this file is
where the fix commits get cited. Remediation batch 1 is `52b0223` (Group A),
`b606d18` (Group B), `6c34335` (Group C); the process record is
`../2026-08-security-audit/REMEDIATION-1.md`. **All three commits are
committed, not yet deployed as of 2026-08-22** — the findings carry working
exploit sketches, so the report and the fixes ship in one push. Line numbers
are HEAD's (`6c34335`).

**Production size, 2026-08-22:** 180 parcels, 334 timeline requests (read-only
count, FINDINGS probe #19 and REMEDIATION-1.md §4). `HEAL-SCORECARD.md`'s 57
is the 2026-08-12 sweep-time count and is cited as a denominator in the
geometry rows above; it was correct then and is stale now.

| # | Status | Where it stands |
|---|---|---|
| SEC-1 Titiler open fetcher | **Code resolved (`52b0223`); operator steps pending** | Every Titiler call carries `?access_token=` from one setting when it is set — `services/titiler.py:10-18`, used at `api/imagery.py:512, 584, 681, 704` and `preview_renderer.py:119` — and is byte-identical to before when unset (`config.py:110`; test `test_titiler_params_unset_is_byte_identical`), which is what makes API-first deploy ordering safe. `fly.titiler.toml:16` disables `/mosaicjson`. The token itself is two Fly secrets Ryan sets in the order `../2026-08-security-audit/DEPLOY-SEC-1.md` gives; until step 3 of that file runs, Titiler is still the open fetcher URGENT.md describes. Flycast/private addressing (URGENT step 3) is deferred with the M9 re-open below. |
| SEC-2 Unbounded creation via client coordinates | **Resolved (`b606d18`), prospective; undeployed** | Root defect was trusting `lat`/`lon`. Autocomplete now records every pair it serves (`geocoder.py:41-66`, Redis, 6 h) and the reverse fallback runs only for a served pair (`api/geocode.py:218-234`); anything else is the existing 422, and a Redis it cannot ask is treated as "not served" (`api/geocode.py:163-170`, fails closed). Global admission control on top: `services/admission.py:52-73` refuses a new parcel (`parcels.py:139`) or a new request row (`services/imagery.py:108`) when `ACCEPT_NEW_PARCELS=false` or queued+processing ≥ `MAX_INFLIGHT_TIMELINE_REQUESTS` (30, `config.py:87-92`), logging each refusal with its reason; routes answer 503 + `Retry-After: 120` (`api/geocode.py:267-269`, `api/imagery.py:85-91`). Dedup hits and complete requests are served before either gate, so existing parcels stay browsable; a refused backfill returns None quietly (`services/imagery.py:403-410`). Counter design (queue depth in Postgres, not a Redis window) and the rejected alternative are in `b606d18`'s message. Prediction block below. |
| SEC-3 Per-id limiter keys | **Resolved (`52b0223`); undeployed** | Key is the route template (`rate_limit.py:44-51`), so `/warmup`, `/{id}/stac` and `/{id}/timeline` share one bucket per IP. `/warmup` 60 → 120/min (`api/imagery.py:658`) because one session warms ~80 snapshots into what is now one bucket. Grep-for-the-shape found no other Redis key or metric built from a concrete request path (REMEDIATION-1.md §3). |
| SEC-4 Census key in `str(HTTPStatusError)` | **Resolved (`52b0223`); undeployed. Key rotation is Ryan's call** | Fixed at the sinks, not the call sites: `app/redact.py` masks `key=`, the SAS family (`sig/se/sp/st/sr/sv/sk*`), `access_token=`/`token=` and `scheme://user:pass@`; it runs as a structlog processor after `format_exc_info` (`logging_config.py:35-36`) so a rendered exception is scrubbed as text, and at the two task-row `error_message` sinks (`services/imagery.py:275, 290`) that `GET /timeline-requests/{id}` serves to clients — which also closes SEC-7's log half. The three geocoder messages carry a status code instead of `{exc}` (`geocoder.py:127-132, 199, 327, 429`). Written as if the log sink is external. The key has reached Fly logs on every Census 5xx until this deploys; rotate if any log was ever exported (FINDINGS §9). |
| SEC-5 Parcel poisoning | **Resolved prospectively (`b606d18`); existing rows need evidence** | On the served-coordinate path `normalized_address` is now the Photon display name the backend served, never the submitted text (`api/geocode.py:234`). Not closed for rows that exist: production holds **71** parcels with the reverse-path signature `normalized_address = address` (read-only count, 2026-08-22), all inside CONUS (0 outside `_US_BBOX`) and all with a census tract — indistinguishable from legitimate autocomplete fallbacks without asking Photon. `scripts/remove_unverified_reverse_parcels.py` is the tool: dry-run default lists them, `--verify` asks Photon per row, `--execute` deletes only rows no suggestion lands within 250 m of, and refuses the whole run if any row is inconclusive. **Not run.** Residual: `parcels.address` is still the submitted text on every path, as it always was for the forward path too — a dedup hit shows the first submitter's spelling; the NAIP-gate lesson applies and is why the script exists. |
| SEC-6 Limiter fails open | **Partially resolved (`52b0223`); rest accepted** | `RateLimit(fail_closed=True)` on the two routes that create parcels or dispatch worker runs (`api/geocode.py:190`, `api/imagery.py:65`) answers 503 + `Retry-After: 30` when Redis is unreachable (`rate_limit.py:88-97`); autocomplete, `/warmup` and `/{id}/stac` keep failing open. The classification is pinned by `test_dispatching_routes_fail_closed_and_read_routes_fail_open` over the live route table. Accepted: the tile proxy, listing and `/parcels/{id}` stay unlimited (read-only, cache-backed, and the tile path must survive a Redis blip); IPv6 `/128` keying stays (REMEDIATION-1.md G2). |
| SEC-7 Task rows / Titiler bodies carry URLs | **Log half resolved via SEC-4; client half accepted (L10)** | `error_message` sinks scrub at `services/imagery.py:275, 290`; the `titiler_body` log lines pass through the same processor. Upstream *host* disclosure to clients is the L10 accept, unchanged. |
| SEC-8 Geocoder endpoints as free proxies | **Deferred** | Needs a global Photon/Census budget — a second global counter with its own degrade-to-cache behaviour. Not a one-constant fix, and it interacts with the N4 empty-dropdown shape; next batch. |
| SEC-9 Floating actions | **Resolved (`52b0223`)** | All four actions pinned to commit SHAs with the version in a trailing comment (`deploy.yml:25, 29, 60, 76, 92, 106`; flyctl `master` was `ed8efb3` = tag 1.6 on 2026-08-22). `test_every_action_is_pinned_to_a_commit_sha` fails on any unpinned `uses:`. Token scoping (`fly tokens create deploy`) and branch protection remain Ryan's (FINDINGS §7, §9). |
| SEC-10 Dependency advisories | **Resolved for the reachable three (`6c34335`)** | pillow 12.2.0 → 12.3.0, starlette 1.0.1 → 1.6.0, react-router 7.14.0 → 7.18.2. pip-audit over the exported lock 26 → 1 (pydantic-settings 2.14.1, GHSA-4xgf-cpjx-pc3j, left alone); npm audit 11 → 9, all remaining build-time or unreachable transitive (listed in the commit). 465 backend tests, mypy, ruff, tsc, eslint and the Vite build all clean; no behaviour change observed. |
| SEC-11 Security headers, public `/docs` | **Open, deferred** | Not in batch 1 by design (FINDINGS §6 item 10). |
| SEC-12 Neon owner role; root + gcc | **Open, deferred** | Neon least privilege is awkward while Alembic runs at boot (M10); Dockerfile.fly (L12) unchanged. Named out of scope in the batch brief. |
| SEC-13 Residential addresses in `docs/audits/` | **Open — Ryan's decision** | Not a code change. |
| P5 Outbound host allowlist | **Resolved (`52b0223`); undeployed** | One shared constant, `stac.ALLOWED_UPSTREAM_HOSTS` (`stac.py:236-248`), derived from the distinct hosts in production `imagery_snapshots` on 2026-08-22 (query and output in REMEDIATION-1.md §4) plus the Landsat band container. Gates the tile proxy and warmup before a stored URL reaches Titiler's `url=` (`api/imagery.py:354-366, 486, 687`), the preview renderer (`preview_renderer.py:102`), the worker's validation `HEAD` (`stac.py:1042`) and STAC pagination next-links (`stac.py:156`). The Landsat item fetch keeps its narrower PC-only check (`api/imagery.py:347`). Absorbs N5. |

**Prediction block — SEC-2/SEC-6 (B4), written 2026-08-22 before any deploy.**
Specific enough to be falsified; the observation lands next to each line,
never by editing the prediction.

1. *Normal session.* One person creates at most 10 parcels/minute/IP (unchanged)
   and, across the whole site, never sees the global cap unless ≥30 pipeline
   runs are already queued or processing — at the measured drain (median 42 s,
   concurrency 2 ≈ 170/hour, 248 runs over 30 days) that is ≥10 minutes of
   backlog, which no legitimate day since 2026-08-12's sweep has produced
   (1–9 requests/day, probe #19). Autocomplete → search keeps working: the
   served-coordinate marker outlives the 300 s suggestion cache by 6 h. **Two
   legitimate flows that do change:** (a) typing a house-number address and
   picking a suggestion when Census cannot match the typed text now stores the
   suggestion's display name as `normalized_address` instead of the typed
   text — visible on the parcel header, which prefers `normalized_address`;
   (b) the four example chips on the landing page carry hard-coded
   coordinates the backend never served, so if the Census forward geocode of
   one of those famous addresses fails, the chip returns the 422 "could not
   match" message instead of falling back. Neither trips the cap.
   *Observed:* —
2. *Flood.* Per IP, the 11th `POST /geocode` in a minute is a 429 as before.
   Across IPs, parcel rows and queued runs grow until queued+processing
   reaches 30, then every *new* address — attacker's or visitor's — gets a 503
   with "Plotline is busy right now and new address searches are paused.
   Existing timelines are still available" and `Retry-After: 120`. Log lines:
   `Admission refused` (`what=parcel`, `reason=queue_full`, `depth=30`,
   `cap=30`) once per refused request, and for the coordinate variant
   `Refusing coordinates this backend did not serve` with no parcel row and
   no Census reverse call. Parcel row growth during a sustained flood is
   bounded by the worker's drain rate (~170/hour) instead of by the attacker.
   A visitor browsing an *existing* parcel during the flood sees nothing
   different: its page loads, its tiles render, its deep-link `POST /timeline`
   reuses the complete request. A visitor searching a *new* address sees the
   503 text above in the search box. **This is the one prediction that would
   look like a regression if it fired under a legitimate share** — a real
   burst beyond ~30 concurrent first-time searches gets the same 503. That is
   the intended trade (FINDINGS §6 item 7); if it fires on real traffic the
   knob is `MAX_INFLIGHT_TIMELINE_REQUESTS`, not the gate.
   *Observed:* —
3. *Kill switch (`ACCEPT_NEW_PARCELS=false`) on a page load for an existing
   parcel.* Identical to today: `GET /parcels/{id}`, `GET …/imagery`, tiles,
   demographics and events have no gate; the explore page's `POST /timeline`
   returns 202 with the existing complete request; a parcel whose backfill
   would have been due logs `Backfill suppressed — admission refused` and
   returns the existing request instead of a new one. Only a parcel with *no*
   reusable request (never run, or last run failed — 3 such parcels today,
   probe #19) shows "Could not start timeline: Plotline is busy right now…"
   in the banner. A *new* address search returns the same 503. Setting the
   secret restarts the API (one action), ~30 s of deploy.
   *Observed:* —
4. *Redis unreachable, per path class.* `POST /geocode` and `POST
   /parcels/{id}/timeline`: 503 + `Retry-After: 30` before any upstream call
   (`Rate limit check failed closed` in the log). `GET /geocode/autocomplete`,
   `POST …/warmup`, `GET …/stac`: proceed (`Rate limit check failed open`).
   A served-coordinate lookup that cannot reach Redis refuses the
   coordinates (422) while the forward path is unaffected. The admission gate
   itself does not touch Redis, so the cap keeps working through a Redis
   outage; dispatch to a dead broker still marks the request failed as
   before. Tiles keep serving (the tile proxy never consulted Redis for
   limiting; its SAS cache already degrades to a fresh sign).
   *Observed:* —

## M4 ledger sweep — stopped at the gate (2026-08-26)

The first full-fleet sweep after the M4 deploy was authorised and did not run.
Gate line 2 failed and the run was abandoned before any production write. The
report is `../2026-08-m4-ledger/GATE-STOP.md`. Tracked here rather than as a
numbered second-audit finding, for the same reason the ops and geometry
sections are: it changes the M4, M10 and G9 rows, and this file is where the
fix commit will get cited.

| # | Status | Where it stands |
|---|---|---|
| X1 | **Resolved (`edc13db`, 2026-08-26; committed, not deployed, and production is still at `0010` as of that date).** | **Migration `0011` has never been applied to production, and `alembic upgrade head` reported success both times it ran. The cause is `alembic/env.py:96-109` — the advisory lock `dd99cee` added for M10.** `connection.execute(pg_advisory_lock)` is the connection's first statement, so SQLAlchemy 2.0 autobegins a transaction on it; `context.configure(connection=...)` then sets `MigrationContext._in_external_transaction = True` (`alembic/runtime/migration.py:158-160`), and `context.begin_transaction()` answers `if self._in_external_transaction: return nullcontext()` (`:416-417`) — alembic concludes an external caller owns the commit and declines to issue one. `env.py` has no such caller: it believed alembic would commit. The DDL and the `UPDATE alembic_version` run inside the autobegun transaction, the `finally` unlock joins it, and `with connectable.connect()` exiting rolls the whole thing back on `Connection.close()`. **Alembic exits 0, `set -e` is satisfied, and the container serves.** *Observed on production 2026-08-26:* `alembic_version` = `0010`, `alembic current` = `0010`, `timeline_task_years` does not exist — against deploy logs showing `Running upgrade 0010 -> 0011` at `00:52:27Z` on `825d69b7e46618` and again at `00:52:45Z` on `48e0de9a713918`, both followed by `Migrations complete.`. **That second run is the tell:** the second machine read `0010` eighteen seconds after the first machine "succeeded", because the first machine's work had already been discarded. *Corrected 2026-08-26: the 00:52Z boots did not overlap — `825d69b7e46618` logged `Migrations complete.` at `00:52:28Z` and `48e0de9a713918` logged `Running database migrations...` at `00:52:40Z` — so no lock contention occurred, and this pair observes nothing about serialization in either direction. The second boot re-ran `0010 -> 0011` because the version bump had been rolled back, not because it waited on anything.* *Reproduced locally, both directions:* real `alembic upgrade head` against a local database standing at `0010` prints the same upgrade line and leaves `alembic current` at `0010` with `to_regclass('timeline_task_years')` NULL; a standalone harness using alembic's own `MigrationContext` persists the DDL with the lock statement removed and discards it with the lock statement present, `_in_external_transaction` flipping with it. **`0011` is the first migration in the project's history to run under this code and the first to be silently discarded** — `dd99cee` is 2026-08-03, `0010` was committed 2026-06-12 (`86aae50`) and applied before the lock existed, and no migration existed in between. No prior migration is at risk and no data was lost. **Not fixed here; no code was changed.** The remedy is to stop the lock statement owning alembic's transaction — a separate connection, an explicit `connection.begin()` env.py commits itself, or `AUTOCOMMIT` execution options on the lock statement — and the regression test has to run alembic against a real Postgres, which is a CI change as much as a code one (see X3). **The fix (`edc13db`).** `alembic/env.py:141-194` takes the lock, calls `context.configure` and runs the migrations inside one explicit `with connection.begin():` that this function owns and commits, and the lock becomes `pg_advisory_xact_lock` on the same key. Both halves are needed and each closes a different hole: the explicit transaction is what makes something commit at all, and the transaction-scoped lock is what makes the release simultaneous with the version bump becoming visible — a session-scoped lock released while the bump was still uncommitted would reopen exactly the race M10 added it for. Ordering is preserved and now stated at the site: the lock precedes `context.run_migrations()`, which is where alembic reads the current revision (`MigrationContext.run_migrations` → `get_current_heads`, `alembic/runtime/migration.py:488`); `context.configure` reads nothing. `context.begin_transaction()` is deliberately gone — inside the explicit block it can only return a `nullcontext`, and its presence is what made the original read as if it committed. **Second half, and the one that would have caught this: `_verify_at_head` (`env.py:52-86`).** After a head-destined upgrade the version is read back **on a fresh connection** — `poolclass=pool.NullPool` makes it a new session, so it sees committed state and not the runner's own uncommitted view — and compared to `ScriptDirectory.get_heads()`; both are logged, and a mismatch raises. A boot that logs `Migrations complete.` against the wrong head can no longer exit 0. Scoped by `_destination_is_head()` (`:36-52`) so `alembic current`, `stamp` and `downgrade` still work against a database deliberately behind head — found by running them, not by reasoning about them. **Tests: 3 added, 525 passing** (`backend/tests/test_migrations_postgres.py`). **Delete-the-fix run both ways:** reverting the explicit transaction alone fails at the head check (`RuntimeError: … database=[], scripts=['0011']`), and reverting the head check as well fails at the test's own assertion (`assert [] == ['0011']`) — neither on a connection error, which is what makes it a test of the commit rather than of the harness. Report: `../2026-08-m4-ledger/GATE-STOP.md` §11. **Deployed 2026-08-26T01:29Z.** Observed on production, on the deploy that carried `edc13db`: `48e0de9a713918` ran the real, committed upgrade (`Running upgrade 0010 -> 0011` immediately followed by `Migration head check: database=['0011'] scripts=['0011']`); `825d69b7e46618` booted 15s later, found `0011` already at head, and logged the head check with no upgrade line — the second boot found committed state and ran no upgrade, the first boot pair in this project's history to do so. *No log line shows either boot waiting on the lock:* the first machine's head check is `01:29:41Z` and the second pulls its image at `01:29:51Z`, so the outcome is consistent with serialization without being an observation of it (see M10 below). Fresh-connection read confirms `alembic current` = `0011 (head)`. Full addendum: `../2026-08-m4-ledger/GATE-STOP.md`. |
| X2 | **Resolved (`edc13db`, deployed 2026-08-26T01:29Z).** | **`ce307e35` deploys the M4 recorder against a database with no ledger table, and the recorder is on the mandatory path.** `_run_timeline` moves the request to `processing` (`timeline.py:1374`) and then calls `create_request_tasks` (`:1383`), which runs `clear_task_year_outcomes(db, timeline_request_id, source)` **for every source on every request, not only on a Celery redelivery** (`imagery.py:287-288`). That issues `DELETE FROM timeline_task_years …` (`year_ledger.py:195-217`) against a table that does not exist → `psycopg2.errors.UndefinedTable`. Nothing catches it — `record_year_outcome` and `clear_task_year_outcomes` carry no guard, deliberately, because a ledger row is meant to commit atomically with its snapshot. The task boundary (`timeline.py:1577-1601`) marks the request `failed` and re-raises, so the error contract holds and no raw 500 escapes; the feature simply does not work. **Every timeline request that reaches the worker fails at the first write, before any imagery, census or property fetch is attempted.** *Why nothing has broken yet:* zero `timeline_requests` rows have been created since the deploy at `2026-08-26T00:52Z` — 519 `complete`, 3 `failed`, 0 `queued`, 0 `processing`, latest `created_at` `2026-08-25 22:20:00Z`, database clock `2026-08-26 00:59:39Z`. That is the absence of arrivals, not the absence of the fault, and the worker log buffer holds no `UndefinedTable` line because the path has never been exercised. **The 184-parcel sweep this session was authorised to run would have exercised it 184 times.** **Closed, observed 2026-08-26T01:36Z.** `edc13db` deployed at `01:29Z`; `0011` applied for real (see X1); `timeline_task_years` exists with its full constraint/index set, 0 rows. Casualty check: zero `timeline_requests` created between the `00:52Z` deploy boundary and the `01:36Z` observation — the entire window this bug was live, across both the broken boot and the fixed one — so no request ever hit the missing table. Full addendum: `../2026-08-m4-ledger/GATE-STOP.md`. The M4 sweep is now runnable; running it was out of scope for the observe-only session that closed this row. |
| X3 | **Resolved (`edc13db`, 2026-08-26).** | `.github/workflows/deploy.yml` contains **no alembic step**, and `backend/tests/conftest.py` builds its schema as hand-written DDL against an in-memory SQLite engine (`conftest.py:33-223`). The migration directory is therefore never executed anywhere in the pipeline. The 522-test suite that ships with `0011` passes because `_create_test_tables()` creates its tables, not because the migration works. *Count corrected 2026-08-26: this row read 488 until now. 488 is the pre-ledger count at `fa3ea89`, per `../2026-08-m4-ledger/REPORT.md` §6 — "522 passed, 0 failed … up from 488 at `fa3ea89`"; `pytest --collect-only -q` at `ce307e35`, the SHA that shipped `0011` to production, collects 522. The correction does not change what this row argues: a suite that builds its own tables is no more a test of the migration at 522 than at 488.* This is the same hand-written-DDL fact M7 already records as an ORM/schema-drift risk; what M7 does not say is that it is also a **migration-execution** risk, and X1 is what that costs. Any fix for X1 whose test runs on SQLite or on `Base.metadata.create_all` is not a test of X1. **The `test` job gains a `postgis/postgis:16-3.4-alpine` service and `TEST_POSTGRES_URL`** (`.github/workflows/deploy.yml:56-96`) — PostGIS rather than plain Postgres because migration `0001` creates the extension. `tests/test_migrations_postgres.py` runs the real migration path against it: each test creates a throwaway database, migrates that, and drops it, so the database the URL names is never touched and a developer pointing it at their working database loses nothing. **Required, not merely present:** the file skips without a server, but `test_postgres_migration_tests_are_not_silently_skipped` fails when `CI` is set and the URL is not — verified by running the suite three ways (URL set, URL unset locally → 2 skipped, URL unset under `CI=true` → failed). **What is not fixed:** `conftest.py` still builds its schema as hand-written SQLite DDL, so M7's ORM/schema-drift half stands unchanged; what closes here is the migration-*execution* gap, which M7 never named. **One incidental defect found and fixed in the same file:** running alembic in-process ran `env.py`'s `fileConfig(config.config_file_name)`, which disables every existing logger and silently broke `caplog` for 10 later tests — the in-process `Config` is now built without an ini file, and the subprocesses (whose logging dies with them) still pass `-c`. |

## M3 build — per-source backfill reading the ledger (2026-08-26)

Five commits, `ae740cf` → this batch. Nothing pushed, nothing deployed, and
none of the three acceptance heals has run. Report `../2026-08-m3/REPORT.md`;
predictions, written before any run, `../2026-08-m3/PREDICTION.md`. Tracked
here rather than as numbered findings for the same reason the ops, geometry
and M4-sweep sections are: it changes the M3, M4, G1 and M9 rows, and this is
where the fix commits get cited.

| # | Status | Where it stands |
|---|---|---|
| Y1 | **Resolved, observed (`ae740cf`, `c98de1b`, 2026-08-26; deployed 2026-08-27T15:42Z).** Migration 0012 ran on boot (`Running upgrade 0011 -> 0012`, one machine; both machines' fresh-connection head check read `database=['0012'] scripts=['0012']`). Backfill matched the predicted 40 exactly: `SELECT status='partial'` = 40, all with ≥1 failed and ≥1 complete task; `origin`='user' on all 710 rows, all cardinality(sources)=6. Crawford County's own request (`b1392b23-63ad-46d2-b9ab-97cd09d61a2e`, parcel `6563dedf`) is among the 40 and its live status endpoint now returns `"status":"partial"` with the NAIP/Sentinel-2 failures and no error banner. Full detail: `../2026-08-m3/DEPLOY-WATCH.md`. | **A timeline request could read `complete` with failed task rows under it, and that is the state production was in.** `_run_timeline_inner` marked a request `failed` only when *every* task failed, and `complete` otherwise — so Crawford County parcel `6563dedf` reads `complete` while its NAIP and Sentinel-2 tasks both read `failed`, 33 years are lost, and the parcel serves **zero** NAIP and **zero** Sentinel-2 snapshots. `aggregate_request_status` now folds the task rows three ways: `complete` when nothing failed, **`partial`** when some failed and some did not, `failed` when all did. `skipped` is not a failure, and a request with no task rows stays `complete`. Migration 0012 widens `ck_timeline_requests_status` and backfills: **40 of production's 707 `complete` requests flip to `partial`**, 0 flip to `failed`, and the 3 already-`failed` rows are left alone (they are janitor-stranded runs, and promoting one to `partial` would make it reusable again and stop its parcel ever being re-run). Every reader of request status was checked and is listed in `../2026-08-m3/REPORT.md` §A4; see also the `partial` note under *Notes for future readers*. |
| Y2 | **Resolved (this batch, 2026-08-26; deployed 2026-08-27T15:42Z). First post-fix observation, 2026-08-27 — `../2026-08-m3/HEAL-2-crawford.md`:** `6563dedf`'s full-scope heal is the first request to hit the fixed flush on a total-loss source since deploy. Its Sentinel-2 task recorded **12 ledger rows, all `ok`** — the first `sentinel2` rows this parcel has ever had — confirming the flush fires on success too, not only on the every-year-failed branch the fix targeted; no total-loss case has recurred to exercise that branch live. | **A source that lost *every* year recorded nothing, while a source that lost *some* recorded everything.** Found while reading `6563dedf` for the M3 predictions: its Sentinel-2 task is `failed`, it serves no Sentinel-2 snapshots, and the ledger holds **zero** `sentinel2` rows for it — beside 16 recorded `failed` Landsat years and 17 recorded `failed` NAIP years from the same run. The chunked search branch stages each failed year in a `YearOutcomeLog` and then, when `failed_years == len(years)`, does `raise last_exc` **before any persist session opens**, so the whole staged log dies with the exception; the un-chunked branch already flushed before its raise. Landsat and Sentinel-2 are the two chunked sources and both were exposed; NAIP's whole-search failure is on the flushing branch, which is why its 17 rows exist. **This inverts what the ledger is for** — the instrument was silent exactly where the loss was total — and it defeats ledger-driven selection precisely on the worst case, since nothing can be selected that was never written. Fixed by flushing before the raise, with the reason at the site; delete-the-fix is `test_a_source_whose_every_year_failed_still_records_them`. **The fix cannot retro-record `6563dedf`'s twelve lost Sentinel-2 years** — they were never written and there is no history to recover them from, so that parcel needs a separate full-scope run and `../2026-08-m3/PREDICTION.md` P3 says so rather than predicting a recovery it cannot produce. **How many other parcels hold a `failed` task with no ledger rows under it was not measured.** |
| Y3 | **Resolved:** `bd03432`, 2026-08-26 — `imagery.attempted_group_keys(source)` plus `ledger.is_stale` (used inside `is_retryable`) exclude a group outside the current attempted set from selection under any flag; `ledger_gaps.py` reports it in a new `stale` bucket instead of hiding it; `--groups` added to `requeue_parcels.py` as separate operator scope. Corrected dry-run (read-only SQL against prod; not deployed): 140 parcels/140 groups, not 187/327 — `../2026-08-m3/PREDICTION.md` P2 addendum. Committed, **not deployed** as of 2026-08-26 — a mitigation that isn't running isn't mitigating; the deployed worker is still `b599c25`, pre-`ae740cf`. | **A group the code no longer attempts keeps its stale latest outcome forever, and is permanently "retryable" under a flag.** `e6afa9b` removed 1990 from `DECENNIAL_YEARS` because the endpoint never existed. A re-run therefore does not attempt 1990, writes no new ledger row for it, and the 187 `census_decennial`/`1990` rows reading `absent`/`api_no_data` from the pre-trim sweep stay the latest outcome indefinitely. Consequence, measured 18:15Z: `requeue_parcels.py --from-ledger --sources census_decennial --include-absent-api` selects **187 parcels and 327 groups**, not the 80 the tract-width trim can actually help — and it will select the same 187 on every future run, because nothing will ever overwrite a 1990 row. **The general shape is "the ledger has no way to say a group is retired",** and it will recur for any source whose attempted set shrinks. Two candidate remedies, neither chosen here: a `--groups` filter on `--from-ledger` (narrow, and it only hides the symptom), or a retirement marker the selection honours (correct, and it needs a decision about who writes it and when). Named in `../2026-08-m3/PREDICTION.md` P2 with its cost — 107 of the 187 parcels would spend ~9 Census API calls each and change nothing — so the run is not mistaken for a targeted one. |
| Y4 | **Scoped, not built — 2026-08-26.** | **Property is the one source with no ledger, and its axis is not time.** `_fetch_and_persist_property` fans out over exactly two feeds, `adapter.fetch_sales` and `adapter.fetch_permits`, and then **collapses them**: the task is marked `failed` only when `queries_failed == queries_attempted` across both, so **sales succeeding while permits fails entirely is recorded `complete`** — the M4 complete-with-zero shape, one level up from years. If property gets a ledger its `group_key` is the **feed**, not a period: `"sales"` and `"permits"`, with `WHOLE_SOURCE_GROUP_KEY` (`"*"`) for an adapter-level failure that precedes both — the same move topo already made. That would turn `requeue_empty_property.py`'s predicate into a ledger query like the other two, and would distinguish "this address genuinely has no permits" from "the permits endpoint was down", which is the distinction that script exists because we could not make. Not built: it needs its own vocabulary decision (`absent` wants a reason that is not `no_scenes`) and nothing in M3 depends on it. Until then `requeue_empty_property.py` remains the only heal whose subject has no ledger, which is why M3 had to teach its latest-request join about scope by hand. |
| Y5 | **Resolved (`b7c9cbb`, 2026-08-26).** | **`scripts/heal_tract_vintage_gaps.py` is deleted, not ported.** Its selection reconstructed the ledger in Python from a "2021 or 2023 present" proxy its own comment admitted stood in for "was this parcel ever fetched"; the ledger answers that with a fact. Its *dispatch* was the anti-pattern: it called `_fetch_census` in place against a **reused** request, so the old run's task row was mutated, its ledger rows were overwritten on `(task_id, group_key)` rather than added to, and the re-run left no trace that there had been two attempts. **That is why `attempts` was untrustworthy** — the design investigation measured 2,270 of 2,283 non-`ok` latest rows at `attempts = 1` — and deleting it is what makes the retry policy's `indeterminate` "retry once, then never" rule implementable, since every path now creates its own request. Grep: no reference remains in any `.py`, `.yml`, `.toml`, `.sh` or `.json`. One deliberate mention survives as a comment in `app/services/ledger.py`, naming it as the pattern that made `attempts` a lie. **Every mention of it elsewhere in this file is historical** — it no longer exists, and the sentences that propose it as a remedy (the Racebrook row under *To investigate*, the ops-audit and source-inventory references) are superseded by `requeue_parcels.py --from-ledger`. The audit documents that name it are frozen and stay as written. |
| Y6 | **Resolved (this batch, 2026-08-26).** | **Two tests `../2026-08-m3/REPORT.md` carried as "pre-existing, environment-only" failures are now decided, not footnoted.** `test_health.py::test_health_survives_missing_build_identity` asserts `Settings().git_sha == "unknown"`, but pydantic-settings reads `GIT_SHA` from the process environment, and `docker-compose.yml:32-36` deliberately bakes `GIT_SHA=dev` into every local image (Fly-build parity — the comment there says local images should report "dev"), so the assertion is one a compose container can never satisfy. `skipif(GIT_SHA == "dev", ...)` (`test_health.py:48`); CI's `test` job never sets `GIT_SHA` at all — only the later, separate `--build-arg GIT_SHA=${{ github.sha }}` step does (`.github/workflows/deploy.yml:222`) — so the test still runs, and passes, there and on a bare host. `test_workflow_pins.py::test_every_action_is_pinned_to_a_commit_sha` reads `.github/workflows/*.yml` via a path resolved from `__file__`, but the compose container only bind-mounts `./backend` and `./scripts` (`docker-compose.yml:56-58`), not the repo's `.github/`, so the directory is genuinely absent there. `skipif(not _WORKFLOWS.exists(), ...)` (`test_workflow_pins.py:15`), still resolved from `__file__` rather than the CWD, so it runs anywhere `.github/` exists — CI, a bare clone, or compose with the directory mounted in. Also added: `test_imagery_start_years_agree_with_the_timeline_task` (`test_ledger_selection.py`), asserting `imagery.attempted_group_keys`'s floor and `tasks/timeline.py`'s `_SOURCES` table agree on `IMAGERY_SOURCE_START_YEAR` for all three imagery sources — the last open thread from Y3's investigation comment. **Counts of record, run three ways:** compose (`docker compose exec api pytest`, `GIT_SHA=dev` baked) — 590 passed, 7 skipped, 0 failed; CI-equivalent (real Postgres, `.github/` mounted, `GIT_SHA` unset as CI's own test job leaves it) — **592 passed, 5 skipped, 0 failed — the count of record.** A bare-host run without any container could not be measured here: the host has no `pg_config`/libpq headers, so `psycopg2` fails to build outside a container, which is a pre-existing gap in what this environment can run, not a new finding — `docker-compose up` is this project's documented local stack. |

| Y7 | **Resolved — observed, `2190e57`/`1367302`/`07db132`, deployed and run 2026-08-27.** `same_deployed_sha` (`ledger.py`) gates `NEEDS_CLOUD_FLAG`/`NEEDS_ABSENT_API_FLAG` selection on the recording request's `deployed_sha` differing from the SHA now running; a `NULL` recorded SHA (every pre-`0013` row) counts as "changed", so the first post-deploy `--include-absent-api` run selected the current absent population once (127 groups, 78 parcels — exactly the prediction's Claim 2) and the second selected **zero** (Claim 3, exact). All 127 groups now carry `same_sha` in `ledger_gaps.py`. Prediction: `../2026-08-y7-y8/PREDICTION.md`. Scorecard, run and scored: `../2026-08-y7-y8/SCORECARD.md`. | `absent` groups are re-selected by every `--include-absent-api` run (76 today, HEAL-3 §4). Not a marker problem: "permanent" is the wrong concept — the 16 known-204 tracts became recoverable when the trim landed. Rule to implement: retry an `absent` group only if the deployed code has changed since it was recorded. Needs `deployed_sha` on `timeline_requests` (absent per `docs/audits/2026-08-m3-design/INVESTIGATION.md` §1c; `/api/v1/health` publishes it). Scheduled with Y8 as one migration, after the retry/ops batch. *2026-08-27: the worker deploy that carries this fix stalled after a partial CI run (API rolled, worker didn't) and needed a manual re-trigger before the observation heal could run safely — see `SCORECARD.md` §1, §6.1. The observation heal itself recovered zero rows (both target groups are still `absent/api_no_data` fleet-wide after the run) — Y7 doesn't claim recovery, only that the second dry-run stops re-paying for a group nothing has changed about, and that held.* |
| Y8 | **Resolved — observed, `2190e57`/`1367302`/`07db132`, deployed and run 2026-08-27.** `census_snapshots.updated_at` (migration 0013) is written on every upsert conflict, including an idempotent re-run with identical values — pinned by test, not incidental. Backfilled to `created_at` on migration (1574 rows, zero guessed). Prediction: `../2026-08-y7-y8/PREDICTION.md`. Scorecard, full row-level diff: `../2026-08-y7-y8/SCORECARD.md`. | `census_snapshots` has no `updated_at`, and its upsert rewrites values in place (386f3e3). Row-id checksums cannot prove 2010/2020 values were untouched by heal 3 (HEAL-3 §5); content checksums are recorded there as the interim diff source. Fix: one column, default `now()`, refreshed in the `ON CONFLICT DO UPDATE` set. Same migration as Y7. *2026-08-27: the interim method was exercised for the first time by the retry/ops scoring sweep and **held** — `decennial` 2010 `584fa0ed…38d0f` and 2020 `21d3aa8a…1cd6a` reproduce HEAL-3 §5.5 byte for byte, and every other dataset/year checksum is unchanged too, with zero census rows created. Two caveats the run surfaced, both arguing the column is still worth building: the fleet grew 187 → 189 parcels, so the comparison only works by restricting to rows created before heal 3's window — a step someone has to remember — and a checksum still cannot detect a write that rewrites a value to itself. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §6.* **2026-08-27, first real production observation with the column live:** the census-scoped observation heal moved `updated_at` on exactly 575 rows — the 78 healed parcels' `{2010,2020} decennial × {2009,2012,2015,2018,2021,2023} acs5` rows, zero leakage outside that set, zero rows outside it left untouched. All 575 kept identical content checksums (Claim 6's idempotent-upsert case) and zero rows had a checksum change with `updated_at` unchanged (the falsifier, absent). `SCORECARD.md` §5.4.* |
| Y9 | **Resolved, `1367302`, 2026-08-27.** `requeue_parcels.py --sources` takes one comma-separated flag value instead of `nargs='+'`; a variadic `--sources` could consume a trailing positional parcel id as an invalid source. Delete-the-fix: `test_sources_does_not_swallow_a_trailing_parcel_id` (`backend/tests/test_requeue_parcels.py`), parametrized over both token orders. | **`--sources`'s `nargs='+'` can swallow a trailing positional.** Noted while reading `requeue_parcels.py` for HEAL-1 (`../2026-08-m3/HEAL-1-e513188c.md`, "nargs='+' on --sources greedily swallow the UUID") and HEAL-2; not fixed at the time because neither heal's actual invocation hit it (both passed a single source before the positional). Queued here rather than fixed inline, per the M3 build's own note. |

## Retry/ops batch — upstream errors that read as success (2026-08-27)

Five commits, `70437e6` → `6daf621`, plus this one. **Deployed
2026-08-27T18:29:57Z at `7807c4d`** (both machines confirmed, `/api/v1/health`
agreeing, `alembic_version=0012` with no migration in the batch), and **scored
by a full-fleet sweep the same day: `../2026-08-ops-batch/SWEEP-SCORECARD.md`.**
Report `../2026-08-ops-batch/REPORT.md`; the prediction for the first full sweep
after deploy, written before it, `../2026-08-ops-batch/PREDICTION.md`. Tracked
here for the same reason the ops, geometry, M4 and M3 sections are: it moves
the N1, N2, N4 and N5 rows above and the Adams row below, and this is where
the fix commits get cited.

The theme, and the thing to check any future client against: **an exhausted
retry is a failure, and a failure is never a smaller success.**

| # | Status | Where it stands |
|---|---|---|
| Z1 | **Resolved (`533bc3b`, 2026-08-27), deployed 2026-08-27T18:29Z at `7807c4d` — swept, retry unobserved: pending first 429.** The scoring sweep ran **79 ArcGIS queries** across Denver, DC and Adams and every one answered 200. Zero `"ArcGIS rate-limited; backing off"`, zero `ArcGISError`, zero error-level lines from `arcgis.py`. P-8 confirmed: Denver's `complete:0` count did not move and its one historical `failed` task did not recur. The 429 branch has never run in production. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §5. | **`arcgis.py` had no 429 branch.** Esri acknowledges server-side rate limiting on hosted feature services with no published number (SOURCE-LANDSCAPE §0.2, §5.6); a 429 fell through the generic non-200 path and became an `ArcGISError` on the first try. Denver and Adams both run on hosted services, and R4/R5 would add traffic to the same client. Now: `Retry-After` capped at 20 s (Esri publishes no bound, and a longer sleep would spend the query's budget without asking again) or a jittered exponential backoff, up to 3 attempts, **inside** the caller's existing `timeout` rather than extending it — an attempt starts only while `spent + wait <= timeout` (`arcgis.py:110-143`). An unclearing 429 raises naming the status, so `_collect` counts a failed query rather than returning rows that were never fetched. |
| Z2 | **Resolved (`2c3f468`, 2026-08-27), deployed 2026-08-27T18:29Z at `7807c4d` — swept, and observed to change nothing, as predicted.** The scoring sweep ran **15 Socrata queries** against NYC's three 4x4 ids and all answered 200: `ipu4-2q9a` returned rows on 4 of 5 calls, `w2pb-icbu` and `usep-8jbt` on 1 of 5 each, nine zero-row responses, **zero 404s**. P-6 confirmed at its most-likely value of 0 — no NYC task moved from `complete:0` to a failed query. All three resource ids are live; the fix stays what it was written as, insurance against a future retirement rather than a diagnosis of a current one. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §5. | **`socrata.py:73-78` answered a 404 with `[]`.** A retired or renamed 4x4 resource id — the ids are string constants in `county_adapters.py` — read as "this address has no records", `_collect` counted a success with no rows, and the property task completed with zero. Property has no per-year ledger (m3-design §6), so the task status is the whole record and nothing was left behind for a later reader to correct. Now a 404 raises like any other non-200. Grepped for the shape across all five county adapters, `arcgis.py` and `ckan.py`: this was the only status collapsed to an empty list in the property path (`../2026-08-ops-batch/REPORT.md` §4). |
| Z3 | **Resolved-observed (`48b7fd8`, 2026-08-27), deployed `fbdc2f7` 2026-08-27T23:17Z, scored `../2026-08-property-outcomes/SCORECARD.md` P-4 (2026-08-27T23:48Z).** All 11 Denver parcels re-ran `queries_run=2`, `queries_failed=0`, `status='complete'` — zero `partial` observed, and fleet-wide zero `complete` task shows `queries_failed>0`. The `partial` path itself (a task with some but not all queries failing) did not fire in this run — no 429s hit — so `partial`'s status-CHECK and aggregation logic are confirmed live-reachable (schema, `DEPLOY-WATCH.md`) but the branch itself remains unexercised by production traffic; that is unchanged from before this batch, not a gap this batch could close (P-4 predicted 0 `partial` as the most likely outcome, and that is what happened). A property task now has `partial`: `complete` means every query answered (zero rows included), `partial` means at least one failed and at least one did not, `failed` stays H4's all-failed rule (`tasks/timeline.py:1456`). `partial` was not on the task-level CHECK — 0012 added it to `timeline_requests` only — so migration 0014 adds it there and to `_TERMINAL_TASK_STATUSES`, and `queries_run`/`queries_failed` are written on every property task so the state is readable rather than inferred. **Request aggregation needed a change and did not already follow**: `aggregate_request_status` counted only `failed`, so a partial task would have landed in the `complete` bucket — the same defect one level up. It now folds `failed | partial` into the request's `partial`, while the request's `failed` still requires every task to be genuinely failed (`imagery.py:501-533`). `maybe_refetch_for_backfill` retries a partial property task for the same reason it retries a failed one. The pre-existing test that asserted `complete` on this shape was the defect written down as an expectation; it was rewritten and its reversion observed. `../2026-08-property-outcomes/REPORT.md` §4, `PREDICTION.md` P-4. | **A throttled query thins a property task that still says `complete`.** H4's rule fails a task only when *every* query fails (`tasks/timeline.py:1289-1302`), and there is no `partial` status for a property task — `partial` exists only at the request level. So a 429-exhausted query on Adams (1 query) correctly marks the task `failed`, but one on Denver (2 permit layers) with the other succeeding leaves `complete` with a silently thinner `items_found`; DC's 7 layers are weaker still. Both confirmed by test in `533bc3b`. Recorded rather than fixed because inventing a fourth task status is a design decision, not a retry fix. Z1 at least makes the failed query *counted*, so a future partial rule has something to read. |
| Z4 | **Resolved-observed (`48b7fd8`, 2026-08-27), deployed `fbdc2f7` 2026-08-27T23:17Z, scored `../2026-08-property-outcomes/SCORECARD.md` P-3 (2026-08-27T23:48Z).** All 7 DC parcels populated `rows_returned`/`rows_matched` live, `rows_returned >= rows_matched` on every row with zero exceptions, and four rows show the raw/matched split in the database rather than only the log line: `1300 4th St SE` 180→53, both `1600 Pennsylvania Ave NW` rows 15→10, and `2827 27th St NW` 1→0 — the last is exactly the parcel `PREDICTION.md` P-3 guessed as the likely carrier of a `>0/=0` row. The database now distinguishes "matched" from "returned" for every county, closing the gap this row named. Every property task now writes `rows_returned` and `rows_matched` (migration 0014), so "the LIKE pulled records in and the matcher rejected all of them" and "the portal returned nothing" are different rows. `rows_returned` is deliberately the count entering the matcher, not raw portal rows, so `rows_returned - rows_matched` is exactly the rejection count and nothing else — a raw-row count would have been a different, also-useful number that broke that subtraction. The `"Property events filtered"` log line stays; it is no longer the only record. DC's live `1 → 0` instance is the one `PREDICTION.md` P-3 expects to become visible first. `../2026-08-property-outcomes/REPORT.md` §3. | **"Rows returned, all rejected by the address matcher" is invisible in the database, for every county.** `_fetch_property` filters events by `is_address_match` after the adapters return, and `items_found` counts persisted events — so a broad `LIKE` that matched 40 records and kept none looks identical to a portal that returned nothing. The raw/matched split exists only in the worker log line `"Property events filtered"` (`tasks/timeline.py:1314-1321`). This is the one genuinely undistinguished case left in the property path after Z1 and Z2. *2026-08-27, read for the first time across a whole fleet sweep — 31 `"Property events filtered"` lines, and they do separate the two cases the database cannot. **Adams is no longer an instance of this row**: its `raw_count` is 0, and the portal check closed it as a jurisdiction gap rather than a matcher rejection (see the Adams entry under *To investigate*). DC shows both shapes in one run — `raw_count 180 → matched 53`, `15 → 10`, and once `1 → 0`, a task that would read `complete:0` with a row actually returned. NYC likewise, `234 → 100` and `100 → 25`. **So Z4 is not hypothetical: at least one task in this sweep persisted zero events out of a non-zero raw count**, and only the log says so. The line is doing its job; the defect is that it is the only place the split exists, and `fly logs` dropped ~3% of this run's stream. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §5, §9.2.* |
| Z5 | **Deferred — no row existed for it before now.** | **PC STAC search results are never cached.** ~43 Landsat + ~12 S2 year-chunks + 1 NAIP search per parcel per run, every run, cache nothing (SOURCE-LANDSCAPE §5.3; INVENTORY caching ledger). PC's maintainers call the search endpoint a shared resource with 503/504 under load and advise retry-with-backoff, which the search path already does (`timeline.py:97-135`); what the guidance implies and the code lacks is the caching. A Redis cache keyed on (collection, bbox-hash, year) with a 24 h TTL would cut re-run traffic to near zero. Dropped from this batch as a design question, not a retry fix — the TTL interacts with reconciliation and with how a heal decides a year is genuinely absent. **S/M.** This row exists so the item stops being orphaned in a research doc. |
| Z6 | **Resolved (`4275908`, 2026-08-27), committed, not yet deployed. Blast radius swept read-only, production, 2026-08-27: zero.** `_vintage_get_with_retry` (`geocoder.py`) gives `lookup_tract_at_vintage` the same policy N2 (`8a86fad`) gave `CensusFetcher`: `ReadTimeout`, `ConnectError` and `{500, 502, 503, 504}` retry up to 3 attempts with jittered backoff; a 4xx is terminal on the first attempt. More load-bearing than the retry itself: `_VintageTracts.tract_for` (`timeline.py:1003`) no longer catches an exhausted `GeocoderError` and falls back to the stored tract — it propagates, and the per-year loops in `_fetch_census_years` record `failed`/`<reason>` for that year (vintage and geocoder path in `detail`) and skip the fetch instead. Checked every `(parcel, dataset, year)` census row in production (1,574 rows, 756 distinct `(parcel, vintage)` geocoder calls, paced 0.6 s) against a fresh lookup at the same vintage today, including the sweep's own instance (parcel `64a47cd8-0ff6-4250-b02a-70cb1fbe2ec1`, tract `36061000900`): **zero mismatches**. The one ConnectError this batch met landed on a tract stable across every vintage the geocoder serves, so its fallback happened to be right — luck, not a property the old code guaranteed, which is why the fix stands regardless. `../2026-08-z6-vintage-lookup/REPORT.md`. | **Superseded — see the resolution cell.** The geocoder's vintage tract lookup had no retry for anything but `httpx.TimeoutException` (flat 1 s sleep); `ConnectError` and any 5xx raised on the first attempt. Its caller caught every `GeocoderError` unconditionally and silently substituted the stored tract, with no trace in the row or the ledger that the value came from a fallback rather than a resolved lookup — a wrong row the ledger reads as `ok`. Observed once, live, during the scoring sweep: an `httpx.ConnectError` at 18:55:14Z, degraded to the stored tract, and (per the resolution cell) that particular substitution was correct. Filed as N2's outlier — the census-path client the retry batch did not widen. `../2026-08-ops-batch/SWEEP-SCORECARD.md` §9.1. |
| Z7 | **New — open, not fixed.** | **Worker deploy lag, undetected by CI.** On 2026-08-27 the worker was three commits behind the API (`07db132` vs its prior image); caught by the Y7/Y8 gate's two-app SHA check (`docs/audits/2026-08-y7-y8/SCORECARD.md` §1), not by CI. Cause: `changes` (1c037f2) takes its diff base from the API's health SHA only, so a lagging worker never shows as "changed." Fix pending: base = the *older* of the API health SHA and the worker's `fly image show` GH_SHA (CI has `flyctl` authenticated for deploys). Until then, every gate keeps checking both apps. |

Notes for future readers: a fallback that substitutes a plausible value for a
failed lookup is a silence — the ledger only records what the code admits
happened. `resolved or self._stored` inside a bare `except GeocoderError` is
indistinguishable, at the row and at the ledger, from a lookup that actually
succeeded; the tract this batch's one instance produced was right, but
nothing checked that it was, and Denver 41.11 (`4ce1822`) already proves a
point where the same substitution would have been wrong. The fix is not "add
a retry" — N2 and Z1 both already had retries before this row existed — it is
refusing to let an exhausted retry masquerade as success.

## Property outcomes batch (2026-08-27)

Z3, Z4 and the Adams jurisdiction row, fixed together because they are one
shape: a state the database could not tell from success. Migration 0014 adds
`queries_run`, `queries_failed`, `rows_returned`, `rows_matched` and
`coverage` to `timeline_request_tasks`, plus `partial` at the task level and a
nullable `items_found`. Property has no period key, so it writes no
`timeline_task_years` rows in any circumstance — the task row is its ledger,
which is why the counts land there. Full report:
`../2026-08-property-outcomes/REPORT.md`; predictions written before any run:
`../2026-08-property-outcomes/PREDICTION.md`.

| # | Status | Where it stands |
|---|---|---|
| AA1 | **New — resolved in the same batch (`1f7e398`, 2026-08-27).** | **The ORM named two constraints the database has never had.** `TimelineRequestTask.__table_args__` spelled them `ck_trt_source` and `ck_trt_status`; the server carries `ck_timeline_request_tasks_source` / `_status`, set by 0002. Found by running 0014, not by reading it: `alembic upgrade head` failed with `constraint "ck_trt_status" of relation "timeline_request_tasks" does not exist`. Every other table in the model uses the long form, so this one table was the outlier. The migration targets the real names and the ORM labels were corrected to match — metadata only, no DDL. **The general lesson is the one X1 already taught in a different key:** a name that only ever appears in code the database never executes is unverified until something executes it. Nothing else in `models/parcels.py` drifts — checked against `\d` output for every table this batch touched. |
| AA2 | **New — accepted risk, with the assumption recorded at the site.** | **The coverage gate reads a mailing city, not a jurisdiction.** `city_from_address` takes the second comma component of `normalized_address`, which is the Census geocoder's `matchedAddress` — a postal address. An unincorporated Adams parcel whose mail is addressed to Thornton, Northglenn, Westminster, Commerce City, Federal Heights, Aurora or Arvada will resolve to `not_covered` and never be queried. **Accepted because the failure is in the safe direction** — "we did not ask" rather than a fabricated "there is nothing here", which is the state this whole batch exists to remove — and because the alternative (a point-in-polygon test against municipal boundaries) needs a boundary layer, a fetch path and a cache that nothing else in the pipeline would use. The assumption is a comment on `AdamsCountyAdapter.NOT_COVERED_CITIES` (`county_adapters.py:312-373`), where anyone adding a city would act on it, and it states the evidence shape a new entry needs: a house-number band the layer holds nothing in. **Never observed** — the fleet holds one Adams parcel and it is genuinely in Thornton. Denver and Brighton are excluded from the list for exactly this reason, with geocoded evidence. **The gate reads a city parsed from the formatted address string (`city_from_address`); a city-level geocode like "Cupertino, California 95014" parses to None and fails open (P-2's pinned weak spot). The right source is the geocoder's structured `city` (Photon returns it on every hit) — one nullable column on `parcels` if it isn't stored — and after that, municipal boundaries (TIGER places, the census ingest pass). Neither is this batch.** **Observed live, 2026-08-27T23:48Z (`../2026-08-property-outcomes/SCORECARD.md` P-2): the Cupertino parcel's re-run property task resolved `coverage='covered'`, `queries_run=3`, `rows_returned=0`, `rows_matched=0` — the fail-open predicted here happened exactly as described, on the first live run under the deployed coverage gate.** |
| AA3 | **New — open, not fixed; read-only finding from this batch.** | **The pipeline sends one street-name token and no suffix, so `LIKE` breadth — not `ST` vs `STREET` — is the real exposure.** `extract_search_terms` returns the house number and the first street-name word after an optional directional; `"12804 EMERSON ST"` goes out as `("12804", "EMERSON")`. Every adapter's pattern is suffix-agnostic and correct for that input (per-adapter table in `../2026-08-property-outcomes/REPORT.md` §7). The two genuine exposures are different: **ordinal stripping** turns `17TH` into `17`, so `"245 E 17TH ST"` queries Denver and DC as `LIKE '245 %17%'` and matches `1170`, `X17Y` and anything else with those digits (the rule is correct for NYC DOB, which stores `17`, which is why it exists); and a **multi-word street name** queries on its first word only — `"500 MARTIN LUTHER KING BLVD"` as `LIKE '500 %MARTIN%'`. Both are absorbed by the H5 address matcher, so they are noise rather than loss — and after Z4 that noise is *visible* as `rows_returned >> rows_matched` instead of invisible. **A fix** would pass the full normalized street line alongside the two terms and let each adapter tighten its own pattern where its column supports it. Not attempted: it changes what every adapter fetches, which this batch was explicitly scoped away from. **S.** |
| AA4 | **New — open, not fixed. Data quality, found by this batch's production read (2026-08-27).** | **City-level geocode accepted as a parcel.** `Cupertino, California 95014` is a fleet parcel with no street — a point that isn't a property, with every source run against it. Photon's `osm_value` distinguishes a city/town hit from an address; the geocode path does not check it. **Decide: gate at geocode** (reject non-address hits with a clear message), **flag the existing row, or delete it.** Not this batch — it is a geocode-path change, and this batch was scoped to the property path. Surfaced here because the coverage gate is the first thing that has to reason about such a row: `city_from_address` returns None for it and the gate fails open, which is the right default for an unreadable city and the wrong answer for a parcel that should not exist. **Note it under the MCP `lookup_parcel` design too** — a public tool must not return a city as a parcel. No committed MCP doc exists to annotate yet (the tool-description draft is uncommitted, per the census-decennial report §; ADR 0001 sequences the server after M3/M4), so this row is the placeholder that draft must pick up. **S/M**, depending on which of the three options is chosen. |

## Imagery normalization — step 1 (2026-08-28)

First of the four additive steps in `../../adr/0001-imagery-normalization.md`,
which moved Proposed → **Accepted** in this batch with a dated amendment.
Steps 2 (dual-write), 3 (read cutover) and 4 (retirement) are not started.
Report: `../2026-08-normalization/STEP1-REPORT.md`; prediction written before
the run and scored after: `../2026-08-normalization/PREDICTION-STEP1.md`;
pre-flight: `../2026-08-normalization-pre/VERIFICATION.md`.

| # | Status | Where it stands |
|---|---|---|
| NORM-1 | **New — built, run locally, then RUN AGAINST PRODUCTION on 2026-08-28. Prediction scored twice, every line confirmed both times.** | **`scenes` and `parcel_scenes` exist and are filled from `imagery_snapshots`, locally and in production.** Migration 0015 (`822faca`) is pure DDL; ORM models and the mirrored SQLite test DDL are `0fc0f64`; `scripts/backfill_scenes.py` is `b3f8e94`; tests `382329e`. Locally: 2,945 snapshot rows → **1,262 scenes** (1,174 catalogued + 88 synthesized) and **2,945 parcel_scenes** (`ea98325` predicted, `d13026e` scored). **Production, 2026-08-28:** 0015 was deployed and applied ahead of the run (alembic head `0015`, both apps on `GH_SHA=4de5728`), and `--execute` ran **once** at 17:05:22–17:15 UTC → **6,661 scenes** (6,156 from distinct `(stac_collection, stac_item_id)` + 505 synthesized from mosaic URLs) and **12,884 parcel_scenes** over 189 parcels. Predicted `93ee2ff` *before* the write; **every line confirmed, no deviations**. `imagery_snapshots` unchanged at 12,884/6,156; 0 duplicate groups; 0 non-NULL `footprint`; 0 non-NULL `selected_by`; 613 mosaic references over 576 rows matching the source table exactly, none dangling. Idempotence observed, not asserted: the immediate re-run plans the identical 6,661/505/12,884 and writes **0**. Report `../2026-08-normalization/STEP1-PROD-REPORT.md`; captures `prod-backfill-dryrun.txt`, `prod-backfill-run.txt` (truncated — NORM-8), `prod-backfill-recheck.txt`. **No read path moved and `reconcile_source_snapshots` is unmodified — nothing in production reads either new table yet**; steps 2 and 3 own that. |
| NORM-2 | **New — resolved in the same batch. Local-only; production was already correct.** | **The local database's 269 duplicate `(parcel_id, source, group_key)` groups are gone.** VERIFICATION item 6b measured 269 across 43 parcels (266 sentinel2, 3 naip) — the state of a dev database that had never been swept under the G8 quarter→year regrouping production got on 2026-08-25. A full imagery re-queue of all 43 parcels took it to **4**, and a ledger-selected retry of the failures took it to **0**. The backfill refuses to run while any exist, so this was a precondition, not a cleanup. |
| NORM-3 | **New — mechanism, resolved by design in this batch.** | **A sweep cannot repair a duplicate group in a period whose re-fetch failed.** The 4 groups surviving the first local sweep were each a `failed`/`stac_403` year in that same sweep's ledger: Planetary Computer rate-limited the year-chunk search, so the run selected nothing for that period and `reconcile_source_snapshots` — which by design never deletes an *absent* group — had nothing to collapse against. Not a reconciliation defect and not silent: the M4 ledger named all four, and `requeue_parcels.py --from-ledger` cleared them. **The general shape:** duplicate-group counts measured after a sweep are only as complete as that sweep's upstream success rate, so the ledger must be read alongside them. Written down because the production step-1 backfill will make the same measurement. |
| NORM-4 | **Open in production; resolved locally 2026-08-28 by the enrichment pass.** | **A NAIP tile URL does not reliably yield its STAC item id, so 88 local and **505 production** `scenes` rows carry a candidate id rather than a catalogued one.** *(2026-08-28: the earlier "540" counted `additional_cog_urls` entries; the distinct-URL population Phase B synthesizes from is 505 of 578, and the production run wrote exactly 505 such rows — all NAIP, all with NULL `footprint` and NULL `resolution_m`.)* The ADR assumed the filename *is* the item id. Measured across 312 local NAIP rows: it matches in 99, is a proper prefix in 204 more (the id carries a trailing publication date the filename omits), and in 8 is neither (`_.6_` / `_.5_` in the id vs `_h_` in the filename). Capture date is unaffected — it is the first date field either way. **Mitigated, not fixed**, by a `provenance` column on `scenes` (`'snapshot'` \| `'mosaic_url'`) that the ADR's schema block does not list; `WHERE provenance = 'mosaic_url'` is the work queue for a later pass that fetches the real items and fills `footprint`. **`footprint IS NULL` cannot serve as that flag** — `imagery_snapshots` holds no item geometry at all, so every step-1 row has a NULL footprint — and a "does a snapshot row carry this id" query would stop working at step 4. **Until that pass runs, nothing may treat a `mosaic_url` row's `item_id` as a catalogued identifier.**  **2026-08-28, later the same day: the enrichment pass ran locally and the local half of this population no longer exists** — all 88 local `mosaic_url` rows now carry catalogued ids and real footprints (`provenance = 'enriched'`, NORM-7 below). **Production's 505 rows are unchanged and this finding stands there in full.** |
| NORM-5 | **New — open, not fixed; noted for step 3.** | **`INVESTIGATION.md §8` is not an `imagery_snapshots` read-site enumeration**, and no section of that document is. VERIFICATION item 3 derived the list fresh (20 call sites; six in production code) and STEP1-REPORT.md carries it forward verbatim so step 3's session inherits it rather than re-deriving it a third time. The ADR's Costs section still cites §8; left as written per the frozen-record rule, corrected in the amendment. |
| NORM-6 | **Pre-existing, restated — open. Out of scope for normalization, but normalization propagates it.** | **Four local parcels look like two real-world locations geocoded twice** ("11775 Wadsworth Blvd" / "…Boulevard", "4800 Telluride St" / "…Street", plus two South Lemay Avenue rows), first flagged in VERIFICATION §6b. `parcel_scenes` keys off `parcel_id`, so the split is carried forward unchanged — normalization neither causes nor fixes it. Adjacent to AA4 (a city-level geocode accepted as a parcel); both are geocode-path questions. |
| NORM-7 | **Remedy built and run LOCALLY 2026-08-28; OPEN IN PRODUCTION — the production run was attempted the same day and stopped at its dry-run gate (NORM-10). Still the forward risk step 2 must settle there before it writes.** | **A synthesized scene and a real catalogued write can become two `scenes` rows for one physical item, without tripping `UNIQUE (collection, item_id)`.** 505 production rows carry an `item_id` parsed from a tile URL (NORM-4), and such an id equals the catalogued id only sometimes — far more often it is a proper prefix, occasionally neither. So when step 2's dual-write inserts a scene for the real catalogued NAIP item that is physically the same tile, the two rows differ in `item_id`, the unique constraint is satisfied, and the duplicate lands silently. **The constraint is on the wrong key for this failure**: it catches duplicate ids, and the failure is one item under two ids. **Step 2 must do one of two things:** reconcile by `cog_url` before insert — the tile's actual address, and the key the backfill itself matched on, so a lookup finds the synthesized row and updates it in place — **or** run the STAC enrichment pass over `WHERE provenance = 'mosaic_url'` first, so `(collection, item_id)` is trustworthy table-wide before dual-write begins. **Enrichment-first is the more durable of the two** (it removes the class of problem rather than routing around it) and is work the ADR already anticipates; `cog_url` reconciliation is required regardless if enrichment has not run. `STEP1-PROD-REPORT.md` §9.  **2026-08-28 — option 2 is built and has run against the local database.** `scripts/enrich_synthesized_scenes.py` (`008d7b2`) enriches a `mosaic_url` row only when a catalogued item's image asset href equals the row's `cog_url` **exactly** — the candidate `item_id` addresses a cheap first lookup and is never evidence (NORM-4) — replacing the id and filling `footprint` / `bbox` / `resolution_m`, and merging rather than skipping when the catalogued id is already held by another `scenes` row. Enriched rows become `provenance = 'enriched'` (migration 0016, `aa23709`), **not** `'snapshot'`: that value means "copied from an `imagery_snapshots` row", which an enriched row never was, and the relabel would be lossy one way. "Is this `item_id` catalogued" stays one predicate, `provenance <> 'mosaic_url'`. **Local result: queue 88 → 0** — 31 already-exact, 57 id-corrected, **0 merged, 0 unmatched, 0 errors**, 0 capture-date disagreements, 88 footprints written, `parcel_scenes` untouched, re-run fetches and writes nothing. Predicted `ce810d5` before the run; every line confirmed (`../2026-08-normalization/PREDICTION-ENRICH.md`, `.../ENRICH-LOCAL-REPORT.md`). **Production is untouched: 505 rows still carry candidate ids and NULL footprints, and the collision NORM-7 describes is still live there.** *(Migration 0016 was not deployed when this was written; it deployed later the same day — see the next paragraph.)* **2026-08-28, later still: the production run was attempted and did not write.** Migration 0016 is deployed (health sha `99e33f2`, `alembic_version` = `0016`, `ck_scenes_provenance` verified to admit `'enriched'`) and the pre-run counts were exactly step 1's — 6156 `snapshot` / 505 `mosaic_url` / 0 `enriched`, `parcel_scenes` 12884 with 576/613 mosaic references, no drift. The **dry run** resolved the whole 505-row queue in 28 s: **196 already-exact, 303 id-corrected, 0 merged, 0 unmatched, 6 `error`**, 0 capture-date disagreements, 0 planned merges (production's own re-run of the two structural queries returns 0 as well). The six errors are PC throttling the *search* endpoint with 403 (NORM-10), not a property of those rows — all six succeed on replay — so the session stopped at the gate its own prediction set (`PREDICTION-ENRICH.md` §7: any `error` outcome stops the run) and **`--execute` was never issued. Production is unchanged: 505 rows still carry candidate ids and NULL footprints, and 0 rows carry `provenance = 'enriched'`.** No production prediction was written, because the run it would predict did not happen; it belongs to the session that fixes NORM-10 and runs the pass. `../2026-08-normalization/ENRICH-PROD-REPORT.md`. Step 2 must not start against production until this pass has run there or step 2 reconciles by `cog_url`. **Deferred, not forgotten:** enriching the 6,156 production (1,174 local) `provenance = 'snapshot'` rows with footprints is a *separate* pass and was not done here. It is what makes ADR rule 4 — "the next geometry audit is a query over `scenes`, not a refetch" — actually true; today every `snapshot` row's `footprint` is still NULL. |
| NORM-8 | **New — open. Operational, not a data defect. Belongs to whoever runs the next long production script.** | **A `fly ssh console -C` session is not a supervisor: killing the client leaves the remote process running.** The production backfill's client was killed by a 2-minute client-side timeout ~2 minutes into a ~10-minute run; pid 655 kept going and committed normally. Everything the script printed after the connection banner is **unrecoverable** — the `Written:` block and the structlog summary at `scripts/backfill_scenes.py:622` both went to a dead client's stdout, and `fly logs` carries the app's uvicorn process, not an SSH session's. **A timeout there is neither an abort nor a rollback, and treating it as either is wrong in both directions**: re-running risks a double write, reporting failure would have been false. Resolved *for this run* by reading instead of re-running — `/proc`, `pg_stat_activity` and `pg_locks` showed the live transaction, and the committed state was then measured directly and cross-checked by the idempotence re-run. **What is fully verified: all row counts and distributions. What is not: the `anomalies`/`drift` lists the run would have printed** — predicted zero, and indirectly evidenced (an anomaly lowers the scene total below plan, and the total hit the planned 6,661 exactly; `drift` is empty by construction on a first run into empty tables). **Fix for next time:** a long production script should write its report to a file inside the machine, or log through a channel `fly logs` carries. `prod-backfill-run.txt` carries an inline note so the truncated capture cannot be misread later. `STEP1-PROD-REPORT.md` §7 F5. |
| NORM-9 | **New — open, unfixed. Data quality in the *pipeline*, surfaced by the enrichment pass. Belongs to step 2's dual-write.** | **`imagery_snapshots.resolution_m` for NAIP is a per-source constant, not the item's resolution, and it is wrong for most vintages.** `app/tasks/timeline.py:712` writes `source_cfg["resolution_m"]`, which is the literal `1.0` declared at `timeline.py:67`; the item's own `gsd` is never read. Measured locally 2026-08-28, after the enrichment pass filled the real values: all 200 NAIP `provenance = 'snapshot'` scenes rows say 1.0 m, while the 88 `enriched` rows carry 0.3 m (9), 0.5 m (1), 0.6 m (30) and 1.0 m (48) — so **40 of 88 tiles were recorded at a resolution they do not have**, and by the same mechanism so is every NAIP row in `imagery_snapshots`, locally and in production. NAIP has flown at 0.6 m since ~2016 and 0.3 m in the newest state-years. **User-visible:** `frontend/src/components/MapView.tsx:298-301` renders it as a "1m res" chip. **Consequence to hold until it is fixed:** NAIP `scenes` rows now disagree about resolution by provenance — enriched rows are right, snapshot rows are the constant — so anything reading `scenes.resolution_m` is reading two different things. Not fixed in the enrichment batch: the fix changes what the pipeline writes, which is step 2's commit, not this pass's queue. `../2026-08-normalization/ENRICH-LOCAL-REPORT.md` F2. **2026-08-28, later the same day: the production distribution is still unmeasured.** The production enrichment run stopped at its dry-run gate (NORM-10) without writing, and `gsd` reaches `scenes.resolution_m` only through an enrichment write — a dry run resolves items in memory and stores nothing — so production's 505 NAIP rows still carry NULL `resolution_m` and its 6,156 `snapshot` rows still carry the `1.0` constant. The prod-scale numbers this row wants arrive with the run that finally writes them. `../2026-08-normalization/ENRICH-PROD-REPORT.md` §8. |
| NORM-10 | **New — open, unfixed. Script defect, invisible at local scale; it is what blocks the production enrichment run.** | **The Planetary Computer throttles `/search` with HTTP 403, not 429, and the enrichment script treats a 403 as a permanent refusal.** `_RETRYABLE_STATUSES` is `{429, 500, 502, 503, 504}` (`scripts/enrich_synthesized_scenes.py:119`); `search` then calls `raise_for_status()` (`:338`) and `resolve_row` records the resulting `HTTPStatusError` as an `error` outcome (`:416`), leaving the row unenriched. Excluding 403 is **right for the item endpoint** — the geometry audit's per-item 403 means "PC will not serve this item", and retrying it is four wasted requests — but the two paths share one constant, so the search path inherits a rule written for a different failure. Measured 2026-08-28: the production dry run issued **~814 requests in 28 s** (505 item GETs + 309 searches, concurrency 6, no inter-request delay ≈ 29 req/s) and **6 of 309 searches came back 403**; the local run's 145 requests saw none. **It is the rate, not the rows:** all six searches were replayed sequentially with a 2 s gap and all six returned 200, each carrying the item its row needs (`ENRICH-PROD-REPORT.md` §5). **Consequence:** the run cannot be scored or predicted honestly while a retryable throttle is recorded as a per-row failure, so `--execute` was not run and production is untouched. **Shape of the fix, not applied here** (a script bug found against production data is stop-and-report for a run session): give the two endpoints different retryable sets rather than one shared constant, and pace the run so it does not provoke the limiter; the `error` outcome must stay an `error` — turning a throttled search into `unmatched` would collapse a failure into a smaller success. `../2026-08-normalization/ENRICH-PROD-REPORT.md` F6. |

## Accepted, with reasons

- **The SAS wait budgets now bound elapsed time, not sleep time.**
  `SIGN_WAIT_BATCH` (60 s) and `SIGN_WAIT_REQUEST` (2 s) keep their values and
  their split; what changed in `70437e6` is that `_sas_get` measures `spent`
  with `time.monotonic()` across the whole loop rather than summing its own
  sleeps. Counting sleep alone was equivalent while only fast 429s were
  retried. It stopped being equivalent the moment a `ReadTimeout` became
  retryable: a timed-out attempt costs `_SIGN_CLIENT_TIMEOUT_S` (10 s) of wall
  clock and no sleep at all, so four of them would have run 40 s on a route
  whose end-to-end budget is ~30 s. The new rule is strictly tighter than the
  old one — elapsed is never less than sleep — and it is what makes "give up
  inside the budget" true rather than nominal. **The assumption it rests on is
  that the signing client's timeout is 10 s**; that is now the named constant
  `_SIGN_CLIENT_TIMEOUT_S` used both to build the client and to state the
  worst case, so the two cannot drift, and the sentence is written at
  `_sas_get`.

- **ArcGIS retries 429 only; a 5xx there is still terminal on the first try.**
  Deliberate scope, not an oversight, and the asymmetry with the signing path
  (which retries 5xx after N1) is recorded rather than assumed away. Two
  reasons to leave it. A property query has one 30 s budget and several
  sibling queries, so a failed one costs a thinner result rather than a lost
  year — the cost that justified N1's 5xx retry does not exist here. And Esri
  documents the 429 and nothing else, so a 5xx retry set would be invented
  rather than sourced. Revisit with R4/R5, which add counties to the same
  client. The reasoning is at `arcgis.py:104-109`, where someone would act on
  it.

- **PC subscription key — lever unavailable.** Microsoft stopped issuing
  accounts/keys when the Hub retired (2024-06; microsoft/PlanetaryComputer#347,
  maintainer comment) and removed the key requirement from every dataset
  (#351). The APIM portal (planetarycomputer.developer.azure-api.net) exposes
  no sign-in and no subscribable product as of 2026-08-28; #464 (Dec 2025)
  asking whether existing keys still work is unanswered. Dropped from the
  retry/ops batch. N1's retry alignment and container-scoped signing
  (3b7b10e) carry the 429 regime. The other documented lever — compute in
  Azure West Europe — does not apply to Fly.
- **M4 ledger, the empty-year cloud probe costs one extra STAC request per
  empty year.** `eo:cloud_cover < 40` rides in the STAC query itself, so a
  year whose every scene is cloudy and a year the satellite never imaged both
  arrive as the same empty list — `absent/all_cloud_filtered` is not
  observable from the response. `timeline._classify_empty_chunk` re-runs the
  year once with the cloud filter dropped and `max_items=1`, only for empty
  years and only for sources carrying a cloud query. **The load-bearing
  assumption is that empty years are rare** — fleet Landsat sits at 43 of 43
  years for most parcels — so this is a handful of requests per run against
  the 55 the run already makes. It is written at the function. If a future
  source has mostly-empty years, this doubles its request count.
- **M4 ledger, `get_task_id` fails soft.** A `task_id` that will not parse as
  a UUID logs a warning and returns `None`, so the fetch continues with no
  ledger rather than raising. A fetch should not die over bookkeeping; the
  cost is that a broken task row makes the ledger silent instead of loud, and
  a source's rows going missing fleet-wide would read as "not swept".
- **M4 ledger, `idx_tty_task` is redundant.** `(task_id)` is a prefix of the
  index `uq_tty_task_group` already creates. It is built as specified; on a
  table projected to grow ~23× faster than its parent it is a small standing
  write cost, and dropping it is a one-line follow-up migration.
- **M2, client identification.** `Fly-Client-IP` takes precedence and Fly's
  proxy overwrites it on every inbound request, so the spoofable
  `X-Forwarded-For` branch is unreachable in production. This makes the
  deployment topology load-bearing, and the assumption is written into
  `rate_limit.py` at the branch itself so nobody has to find this document to
  learn it.
- **M9, routing.** Internal `.internal` addressing was implemented and
  reverted in c6213d5 — Fly private DNS is IPv6-only and it broke
  API→Titiler. The doubled public request load is the price of that
  constraint, not an oversight. Recorded next to `API_INTERNAL_URL` in
  `fly.toml` as well as here, because the temptation to "fix" it recurs.
  **Re-triaged 2026-08-22 (security audit SEC-1), accept not reversed.** The
  accept weighed doubled public request load against IPv6-only private DNS.
  Nobody had priced in the third term: with Titiler public *and* stock, the
  public endpoint was an unauthenticated open fetcher — any `url=` fetched
  from inside Plotline's Fly organisation, including `.internal` 6PN
  addresses and the container's own filesystem (URGENT.md). What that
  changes: the routing question is no longer "double load vs. IPv6" but "is
  a shared secret enough". For now it is — `52b0223`'s access token closes
  the open-fetcher half regardless of where the traffic goes, and
  `TITILER_API_DISABLE_MOSAIC` closes the fan-out half — so the accept
  stands with the token as its precondition. The structural fix (Flycast
  IPv4 private addressing, which would not hit the c6213d5 problem) needs
  its own investigation with a hypothesis for why `.internal` failed, and
  is scheduled as the M9 re-open, not done here.
- **M10, worker-ahead-of-schema.** Migrations to date are additive, the window
  is seconds, and closing it means serializing two deploy jobs to prevent a
  failure that has not occurred.
- **M5, worker half.** The sync persist phase stalls sibling coroutines but
  cannot deadlock; at one worker it costs seconds per run.
- **L6, TNM pagination.** The audit never verified that a real quad exceeds
  100 products. Not building against an unverified premise. Still accepted as
  of 2026-08-13, now with the cap-hit warning that would supply the missing
  premise if it ever fires — see T3.
- **L10.** Traced and confirmed no credential leak; exposing upstream URLs is
  hygiene, and curated messages cost more than the disclosure is worth.
- **L12, JSON vs JSONB.** Cosmetic; costs a migration and a column rewrite.
  `CensusSnapshot.raw_data` is never queried by content.
- **L12, DC permit layers.** An annual manual chore. The honest mitigation is
  a reminder, not code.

## Deferred, not accepted

- **M3, per-source scope.** The cooldown bounds the cost; it does not fix the
  shape. The open decision is whether scope lives as a `sources` column on
  `TimelineRequest` or is derived per-run from the previous request's task
  rows.
  *Decided and built 2026-08-26 — no longer deferred; see the M3 row above and
  `../2026-08-m3/REPORT.md`.* Shape A: a `sources TEXT[]` column holding
  **declared intent**, not the derived set. The derivation shape (B) was
  rejected on the ground the design investigation found rather than on taste:
  all three candidate shapes leave `_find_reusable_request` and
  `requeue_empty_property.py` reading a scoped request as if it were a full
  one, and B is the only one that stores no intent anywhere to filter on.
  Declared rather than derived because the derived set is 4, 5 or 6 wide
  depending on whether the parcel has a census tract and a county, so it
  cannot express "full scope" as a stable value — and "the parcel's current
  request is the latest full-scope one" is precisely the filter that stops a
  census-only backfill from firing the topo trigger on every page view
  forever.
- **M9, authenticating the Titiler callback.** The rate limits in 56d6647 are
  an interim mitigation, and the batch that added them established that a
  counter is the wrong instrument here: every legitimate call to `/stac`
  arrives from Titiler's single egress IP, so a per-IP limit is one shared
  bucket for all users rather than a per-visitor budget, and 600/min is set
  loose enough not to throttle real tile serving. Properly distinguishing
  Titiler from the public needs a shared secret or a signed callback. The
  routing half stays accepted regardless — this is about who may call the
  endpoint, not where the traffic goes.
  *2026-08-22:* the security audit corrected the premise — it was one
  bucket per snapshot *per IP*, not one shared bucket (SEC-3, fixed in
  `52b0223` by keying on the route template) — and supplied the shared
  secret in the other direction (API→Titiler). The Titiler→API `/stac`
  callback is still unauthenticated; the 600/min limit is now a real
  per-IP bound. Still deferred.
  *2026-08-26, and it is a partial answer rather than a fix:*
  `TimelineRequest.origin` (`user | backfill | heal`, migration 0012) is the
  first thing in the system that records **who asked** for a piece of work. It
  does not touch the Titiler callback — that is a different caller and a
  different endpoint — but it settles the shape of the question this row keeps
  running into. The instrument was missing, not the policy: nothing could
  distinguish a first-time visitor's geocode from a six-year-old Landsat gap
  being retried, so no admission policy could prefer one. With `origin` it can,
  and does (`user_admission_reserve`, default 5, holds slots back from
  `backfill`/`heal`). The same move — record the caller, then let policy read
  it — is what `/stac` needs, and a shared secret is the version of it that
  works across a process boundary. Still deferred.
- **H1's decennial half — the Housing chart still cannot show a decennial
  year.** 6def10c fixed the ACS side of the impossible-combination finding;
  the other side of the same sentence in FINDINGS.md is still true.
  `_DECENNIAL_CONFIGS` (`census.py:27-56`) fetches population and total units
  only, and `HousingChart.tsx:33-37` requires a total *plus* an owner/renter
  split, so 1990/2000/2010/2020 rows are structurally excluded from the chart
  even when fully populated. Confirmed again during the tract-vintage work,
  which is what made it visible: Stapleton's 2010 row exists and carries
  1,773 units, and the chart still will not draw it. The prerequisite is
  verifying occupancy variable names against the live Census API per vintage
  — names drift across decades, the known pattern being P001001 (2000/2010)
  vs P1_001N (2020), and an unavailable variable makes the API reject the
  whole request. Worth doing: it would extend the Housing chart from ~2009
  back to 1990.
  *Corrected 2026-08-26 (`e6afa9b`): the decennial floor is **2000**, not
  1990, and 1990 is not reachable from this API at all
  (`../2026-08-census-decennial/REPORT.md` §2) — so fixing H1's decennial
  half extends the Housing chart back to 2000, and only for the 111 parcels
  decennial 2000 answers for once the tract-width fix is swept; the other 75
  floor at 2010. The row above's "1990/2000/2010/2020 rows are structurally
  excluded" is now "2000/2010/2020". The prerequisite is unchanged and the
  work is still deferred.*
- **M7, M8, M5 (autocomplete half), L1, L3, L8 (autocomplete half), L10 hygiene, L12
  Dockerfile.** Real, and larger than a one-liner or touching shared surface.
  See the second audit's triage for the design decision each one turns on.

## Scheduled

*2026-08-27: the remediation arc (M4 → M3 → ops batch → Z6 → Y7/Y8 → property
outcomes) is closed and scored — last scorecard
`../2026-08-property-outcomes/SCORECARD.md` (014aa1c). The forward sequence
below was decided the same day; it replaces ad-hoc ordering with a stated one
so the reasons aren't only in conversation. Note on labels: "R#" is ambiguous
in this repo — geometry-audit remedies (FINDINGS.md §6) vs SOURCE-LANDSCAPE
recommendations (§1) — never cite a bare R-number below; qualified by
document.**

1. **Imagery normalization** (`docs/adr/0001-imagery-normalization.md`) —
   `scenes` + `parcel_scenes`, four additive steps, each with a prediction
   before it runs. This is the first structural change to the imagery model;
   the NAIP-selector coverage item below and any new imagery source wait on
   it so their waves write against the new shape once instead of twice.
   **2026-08-28: step 1 is DONE, in production. The ADR is Accepted.**
   Migration 0015 is deployed and applied, and the backfill ran once against
   production — 6,661 `scenes` and 12,884 `parcel_scenes`, every predicted
   quantity confirmed, idempotence observed (NORM-1 above,
   `../2026-08-normalization/STEP1-PROD-REPORT.md`). **Steps 2–4 not
   started, and nothing in production reads either new table yet.** Next
   action is step 2 (dual-write in `reconcile_source_snapshots`), which must
   first settle NORM-7 — reconcile by `cog_url` or run the STAC enrichment
   pass over `WHERE provenance = 'mosaic_url'`, or a real catalogue write can
   silently create a second `scenes` row for a tile the backfill already
   synthesized. **2026-08-28, later the same day: the enrichment pass is
   built and has run against the LOCAL database only** — local queue 88 → 0,
   every predicted quantity confirmed (NORM-7). **Production still holds its
   505 unenriched rows.** *(When this was written, migration 0016 was not yet
   deployed; it deployed later the same day, and the production enrichment run
   was then attempted and stopped at its dry-run gate without writing —
   NORM-10.)* The next actions in order are: fix NORM-10 (403 from `/search`
   is a throttle, not a refusal), re-run the enrichment dry run against
   production, commit a production prediction, execute it once, then step 2.
2. **Census tabular ingest** — ACS5/decennial + TIGER tracts, replacing
   `tract_for`. Retires the `4ce1822` vintage-map stopgap (Racebrook-class
   gaps), returns 1990 via NHGIS, and gives AA2's mailing-city-vs-jurisdiction
   question a spatial answer instead of a string-parse one.
3. **MCP server v1** — four read-only tools on the normalized schema. AA4
   (a city-level geocode is not a parcel) is a design input to `lookup_parcel`,
   not an afterthought bolted on after the tool ships.
4. **G8** — measure first (the 70.3% Q4 baseline is already on record,
   `../2026-08-ops-batch/SWEEP-SCORECARD.md` §9), then the remedy, then its
   sweep. Ordered after normalization so the wave writes `parcel_scenes`
   rather than the model being retired under it.
5. **Gap-fill imagery** — NYC 1924/1951 historic orthos and Landsat MSS
   1972–84 (`../2026-08-source-landscape/SOURCE-LANDSCAPE.md` §1, its R1/R2),
   ingested as scenes on the new model.

Cut line if timing tightens: after normalization, ship the MCP server and
defer census ingest — the MCP server does not depend on the census pass.

**Backlog, none blocking:**

- CI diff base = older of the API-health SHA and the worker's
  `fly image show` SHA (the fix for the 2026-08-27 worker-lag row).
- `.venv` named-volume compose fix.
- CHECK-predicate assertion in the Postgres migration test.
- Cupertino/AA4 decision (gate at geocode, flag, or delete the row).
- Per-dataset census scope.
- AA2's structured-city source (Photon's `city`, then TIGER places).
- AA3 street-name matching (full normalized street line to adapters).
- Photon 429 handling + the L8 remainder.
- Prediction baselines come from a stated query at writing time, not a prior
  document's table (see the property SCORECARD's Denver 9-vs-11 mismatch).

**Portfolio, alongside:** migration-lock post (three steps from publishing),
"instrument the silences" post (chat opened), scorecard-methodology LinkedIn
post, Summary-table re-tally.

- **R1, test coverage for the NAIP mosaic selector. HIGH PRIORITY.**
  `select_naip_items`' greedy viewport branch (`stac.py:772-865`) is the only
  path production takes and has **no test coverage at all**; the two existing
  tests call it without a viewport and exercise the legacy path instead
  (`test_stac.py:82, 98`). Two things make this the highest-priority coverage
  gap rather than one item on a list. First, it is the most intricate function
  in the codebase and it carries a documented approximation — "remaining
  uncovered" viewport is tracked as a single rectangle when the true residual
  is a union (`stac.py:821-825`) — that has never been exercised against a case
  where it fails. Second, it already produced a user-visible defect: G1, the
  all-New-Jersey 2023 mosaic served for a Midtown Manhattan address, and two of
  those cards were still live in production as of 2026-08-12.

  **The minimum set, and why each case exists:**
  1. *Single covering tile* — one tile fully containing the viewport returns a
     group of one, and does not consume a second slot.
  2. *Two-tile mosaic* — a viewport straddling two quads returns both, primary
     first, and the primary is the larger-overlap tile.
  3. *The mid-summer tie-break* — two tiles with identical overlap area select
     the one nearer DOY 196.
  4. *`max_tiles_per_year` is respected* — four candidate tiles, none reaching
     the coverage target, return exactly three.
  5. *`coverage_target` short-circuits* — tiles that reach 95 % at two stop at
     two even when a third would add area.
  6. *A zero-gain candidate does not get appended* — `gain <= 0` with a
     non-empty selection breaks (`stac.py:816-817`).
  7. *Degenerate viewport* — zero or negative area falls back to the legacy
     single-tile pick (`stac.py:773-776`).
  8. *Tiles with a missing or malformed `bbox`* — taken and terminated
     (`stac.py:805-808`), scored at zero area (`:791-792`).
  9. **The approximation's failure case.** Construct a year whose true residual
     is an L-shape, so the largest-residual-rectangle heuristic
     (`stac.py:846-863`) picks a rectangle that discards genuinely uncovered
     viewport, and assert the *observed* behaviour rather than the desired one.
     Whether the result is acceptable is a product judgement; the test's job is
     to make the approximation's cost visible instead of latent.

  Case 9 is the one that would have caught the shape of G1, and it is the one
  most likely to be skipped as awkward. It should be written first. The
  suppression gate (`filter_groups_containing_point`) already has tests
  (`test_stac.py:1692, 1703`) and does not need more — the gap is upstream of it.

- **M4, per-year failure persistence.** No longer deferred design — it is the
  next piece of real work. Three production instances from three independent
  upstreams (see the M4 row) have now produced the same permanent gap under a
  `complete` task, and the response to each has been a hand-written heal
  script. The recurring chore is the argument: `revalidate_landsat.py`,
  `requeue_empty_property.py`, `heal_tract_vintage_gaps.py` and now
  `requeue_parcels.py` all exist because a task cannot say which years it
  failed to fetch. *(`heal_tract_vintage_gaps.py` is historical from
  2026-08-26 — deleted in `b7c9cbb`, see Y5.)* The open design question is where per-year outcomes live —
  a column on `timeline_request_tasks`, or a per-year row — and it should be
  answered against what backfill needs to read, not what is cheapest to write.
  **First case where the ledger's `absent` outcome would have saved real work,
  2026-08-25:** O6's nine-parcel 2015 shortfall took a production read plus 18
  archive queries to tell "searched, nothing cleared 40 % cloud" from "the
  fetch failed" — a distinction a persisted per-year `absent` outcome would
  have carried in the row itself (`../2026-08-s2-year/LOGGING-FIX.md` §4).

  **Built 2026-08-25, `0814d7e` + `ef2d0a2` — the design question is answered
  and the instrumentation half is done.** A per-year *table*
  (`timeline_task_years`), not a JSONB column: the test harness is SQLite with
  neither `jsonb_each` nor GIN, the codebase has never queried JSON by content
  anywhere, and every consumer is a set query across parcels or runs
  (`../2026-08-m4-design/INVESTIGATION.md` §4, §9). What remains scheduled is
  **M3**, the half that acts on it — `maybe_refetch_for_backfill` still
  triggers on three all-or-nothing task-status probes, still has no imagery
  trigger at all, and still produces an untargeted full-pipeline re-run. Until
  it reads the ledger, the ledger is a record nothing consumes. Committed, not
  deployed as of 2026-08-25.

- **Census tract ingest with a real spatial join.** Not previously written
  down anywhere in this record — added 2026-08-25 because a stopgap now
  depends on it. Today a parcel's tract comes from one geocoder call at the
  current vintage (`geocoder.py:25,28`), stored as a string on the parcel, and
  every historical year is resolved by asking the Census geocoder again at
  another vintage (`census.py:107-116`, `timeline.py:976-1003`). That is four
  network round-trips per census fetch to answer a question a TIGER tract
  table and a `ST_Contains` would answer locally, and it makes the fetch
  depend on an upstream that has already been observed to time out (N2).
  Ingesting TIGER tract geometry per vintage retires:

  - **`4ce1822`'s vintage map** (the Connecticut fix above) — a spatial join
    against per-vintage geometry needs no `(dataset, year) → vintage` table to
    maintain, and no one has to remember to add a row when a new ACS year is
    queried. **`4ce1822` is explicitly a stopgap on those terms**, and it will
    go quietly wrong the first time a year is added to `ACS5_YEARS` without a
    matching vintage entry: the year falls back to the stored tract and, for
    any state that changes county-equivalents again, silently loses the year
    the way Connecticut just did. A test that fails on an unmapped year would
    narrow that, and is not written.
  - **The tract-code width guessing** the decennial 2000 finding below would
    otherwise require: the ingest carries each vintage's own codes.
  - **The geocoder as a runtime dependency of the census path**, which is what
    makes a geocoder outage cost historical years today (mitigated, not
    removed, by the stored-tract fallback at `timeline.py:989-997`).

  Not scheduled against a date, and no design exists yet. The open questions
  are which vintages to hold (1990 and 2000 tract geometry exist in TIGER but
  the API has no 1990 decennial data to join to — see below), and whether the
  join runs at geocode time or per request.

- ~~**Retry/ops batch.**~~ **Built 2026-08-27, deployed 2026-08-27T18:29Z at
  `7807c4d`, and scored the same day by a 189-parcel sweep
  (`../2026-08-ops-batch/SWEEP-SCORECARD.md`) — every retry site shipped
  unexercised.** `70437e6` → `6daf621`. N1 5xx retry alignment, N2 census retry, ArcGIS 429
  branch, Socrata 404 collapse; `prd-tnm` was already allowlisted by `52b0223`
  and needed verification and a route-level test, not an allowlist edit. See
  the "Retry/ops batch" section above and `../2026-08-ops-batch/REPORT.md`.
  Two new open rows came out of it (Z3, Z4) and one orphaned research item now
  has a row (Z5). **The sweep added a third row (Z6, the geocoder vintage
  lookup's missing retry) and falsified one prediction (P-5); Z6 itself was
  resolved same-day (`4275908`) once its blast radius was swept at zero
  — see the Z6 row.**

- **Y7 + Y8 migration (`deployed_sha` on requests; `updated_at` on census
  snapshots).** Decided 2026-08-27; see the Y7 and Y8 rows above. Scheduled
  after the retry/ops batch. **Built same day — moved out of Scheduled, see
  the Y7/Y8/Y9 rows above.**

## To investigate

- **`2f1b332e` (Racebrook Road, Orange CT) asks the wrong tract vintage, and
  the ledger now shows it.** From the first M4 sweep
  (`../2026-08-m4-ledger/HEAL-SCORECARD.md` §11.1): every census year this
  parcel is missing recorded `absent`/`api_no_data` with detail *"empty
  response for tract `09170157100`"* — acs5 2009, acs5 2021, decennial 1990,
  2000, 2020 — while acs5 2012/2015/2018 and decennial 2010 all succeeded
  against tract **`09009157100`**. acs5 2023 succeeds against `09170157100`.
  `09009` is New Haven County; `09170` is the Greater New Haven Planning
  Region that replaced it in Connecticut's 2022 county-to-planning-region
  change. **The open question is not whether the years failed — they did not
  fail, the API returned empty — but whether asking `09170` for a 2020/2021
  vintage is the right question.** Fleet-wide this is the only parcel of 184
  missing decennial 2020 and the only one missing acs5 2021, so the tract
  choice is the only thing distinguishing it. `scripts/heal_tract_vintage_gaps.py`
  already exists for this shape and has not been evaluated against it.
  *(Historical from 2026-08-26: that script is deleted, `b7c9cbb`. It was
  evaluated first — see the paragraph below — and could not see this parcel
  anyway. Its replacement for this shape is `requeue_parcels.py
  --from-ledger`.)* This
  supersedes M4 occurrence (4)'s "nothing in the system can say whether those
  years re-failed or were never published"; the system now says.

  **Answered and fixed in code, 2026-08-25 (`4ce1822`; committed, not
  deployed, and the requeue has not run).** `../2026-08-racebrook/REPORT.md`.
  Asking `09170` for a 2020/2021 vintage is **not** the right question, and
  the API says so unambiguously: across all ten of this parcel's
  `(dataset, year)` pairs, exactly one of `09009157100` / `09170157100`
  answers and never both. `09009` answers for acs5 2009-2021 and for
  decennial 2010 **and 2020**; `09170` answers only from ACS 2022 on. The
  Census geocoder draws the same boundary — the point resolves to `09009157100`
  at `Census2010_Current`, `Census2020_Current` and `ACS2021_Current`, and to
  `09170157100` at `ACS2022_Current` and `ACS2023_Current` — which is why the
  fix is a vintage map and not a Connecticut rule. Two corrections to what is
  written above, recorded rather than rewritten: **(a)** `09170` is the
  **South Central Connecticut Planning Region**, not the "Greater New Haven
  Planning Region" (Census name, from `2022/acs/acs5`
  `get=NAME&for=county:*&in=state:09`) — the same misnaming is in the frozen
  `../2026-08-m4-ledger/HEAL-SCORECARD.md` §11.1 and stays there; **(b)**
  `scripts/heal_tract_vintage_gaps.py` (deleted 2026-08-26, `b7c9cbb`; this
  evaluation is what it was worth) has now been evaluated against it and
  **cannot see this parcel**: its selection needs a missing 2012/2015/2018
  (`:39`, `:43`, `:77-79`) and those are precisely the years Racebrook already
  has, so it would correctly report nothing to do. Three of the five years are
  recovered by the fix; decennial 1990 and 2000 are the two separate defects
  below.

  **Closed, 2026-08-26.** The requeue ran under the deployed SHA
  (`4330833`) and is scored in full in `../2026-08-racebrook/REPORT.md` §10:
  acs5 2009, acs5 2021 and decennial 2020 all recovered at `09009157100`
  with the exact predicted population and housing figures, the ledger and
  imagery matched the prediction row for row, and zero churn or anomalies
  appeared. This entry is answered; see M4 occurrence (4) above for the
  scorecard. Decennial 1990 and 2000 remain open under their own entries
  below — this closure does not touch them.

- **`_DECENNIAL_CONFIGS[1990]` points at an endpoint that has never existed,
  and the ledger has been recording it as data absence.** `census.py:49-55`
  fetches `https://api.census.gov/data/1990/dec/sf1`, which returns a Tomcat
  **404** for every tract in every state; `api.census.gov/data/1990.json` lists
  37 datasets for the 1990 vintage (CPS, CBP, PEP, SIPP) and **no `dec/*` at
  all**. `_request` maps 404 → `None` → `{}` → `absent`/`api_no_data`
  (`census.py:289-295`, `timeline.py:1069-1076`), so an endpoint error has been
  arriving in the ledger as "the API has no data for this tract". This is the
  complete explanation of the M4 sweep's *decennial 1990 is `absent` on all 184
  parcels* — the sharpest reading available of that measurement, and it says
  the fleet-wide uniformity was never about the tracts. **Unfixed and not
  attempted here:** the remedy is either dropping 1990 from `DECENNIAL_YEARS`
  or sourcing it elsewhere (the 1990 STF files exist outside the API), and
  which one is a product call. Whichever it is, an endpoint 404 and a tract
  with no data should stop being the same ledger row. Evidence:
  `../2026-08-racebrook/REPORT.md` §4.3.

  **Fixed in code 2026-08-26 (`e6afa9b`); committed, not deployed, and no
  sweep has run under it.** `../2026-08-census-decennial/REPORT.md` §2, §5.
  Two things were established beyond the earlier reading, and one correction:
  the entry above says *37 datasets*, and the discovery endpoint says **36**
  — a small number, corrected here rather than rewritten above. The stronger
  evidence is that `api.census.gov/data.json` itself, all **1,798** datasets,
  carries `dec/*` at vintages **2000, 2010 and 2020 only**; the 1990 absence
  is a property of the API's own catalogue, not of one path 404ing. Both
  halves of the remedy landed: 1990 is out of `DECENNIAL_YEARS` and
  `_DECENNIAL_CONFIGS` (so the impossible group stops being recorded — 186
  fewer `absent` rows per sweep), and the endpoint-error-as-absence collapse
  is closed — a 4xx/5xx now raises `CensusHttpStatusError` and lands as
  `failed`/`http_<status>` with the dataset path in `detail`. Where 1990
  lives is written at the config site: NHGIS or `www2.census.gov/census_1990/`,
  a download, so it returns with the census tabular ingest under Scheduled
  and not by re-adding a config. **The product claim is a separate open item**
  — see the user-facing 1990 copy entry below. Prediction for the first sweep
  carrying this: `../2026-08-m4-ledger/PREDICTION.md` P7, P10.

- **`2000/dec/sf1` addresses Connecticut tracts with four characters, and we
  always send six.** `for=tract:*&in=state:09 county:009` on that dataset
  returns `0000`, `1201`, `1202`, `1251`, … — no two-digit suffix. Our
  `157100` 204s; **`1571` returns 200** (`P001001` = 2207, `H001001` = 891).
  The same query against Denver (`state:08 county:031`) returns six-character
  codes, so the width is not uniform across states in that dataset and
  `parse_tract_fips`'s single six-character form cannot be right for both.
  This is at least part of the M4 sweep's *decennial 2000 `absent` on 137 of
  184 parcels*, which has been read as genuine absence. **Unfixed:** deriving
  a width per state from a wildcard probe is a design decision, not a patch,
  and the structural answer is the tract ingest below. **Measured on two
  counties only** — whether the width varies by state, by county, or by
  something else is unestablished. Evidence:
  `../2026-08-racebrook/REPORT.md` §4.2, §9.

  **Measured, and fixed in code 2026-08-26 (`e6afa9b`); committed, not
  deployed.** `../2026-08-census-decennial/REPORT.md` §1. The entry above
  reads this as a Connecticut width quirk of unknown breadth; it is neither
  Connecticut-specific nor a width that varies by state. **The rule is
  mechanical:** `2000/dec/sf1` addresses a tract by its basic code plus a
  *real* suffix — four characters when the tract has no suffix, six when it
  does — while 2010 and 2020 pad every code to six, which is the form a
  parcel stores. Denver's six-character codes and Connecticut's four-character
  ones are the same rule seen from two counties whose tracts happen to differ
  in whether they carry suffixes. Verified against the dataset's own tract
  inventory: **3,088 tracts, 8 counties, 8 states — no six-character code
  ends in `00`, and no four-character code padded with `00` collides with a
  six-character one.** So dropping a trailing `00` re-encodes the same tract;
  it is not a per-state guess and not a fallback to a parent.

  **Blast radius, from the ledger, all 186 parcels:** `ok` 47 / `absent` 139,
  and the split against the stored tract is perfect in both directions —
  every `ok` parcel's tract does *not* end in `00`, every one of the 80 that
  does reads `absent`, across 27 states. Asked live under the four-character
  form, **64 of those 80 answer 200**; the other 16 are listed by tract in
  §1.5. The 59 `absent` tracts that do not end in `00` are a different thing
  — a real suffix that did not exist in 2000 — and the fix deliberately
  cannot reach them, because trimming a real suffix would substitute a
  coarser geography and label it with the parcel's tract.

  **The fix is per-dataset and in one place:** a `trim_empty_tract_suffix`
  flag on the 2000 config entry, applied by `_tract_for_dataset` in
  `census.py`. Racebrook (`09170157100`) **stays absent and is the only
  parcel in the fleet expected to** — its stored county is a planning region,
  decennial 2000 has no `_GEOGRAPHY_VINTAGES` entry, and adding one is a
  separate change with its own fleet-wide behaviour (recorded under To
  investigate below). Prediction: `../2026-08-m4-ledger/PREDICTION.md` P8.

  **Healed fleet-wide, 2026-08-27 — `../2026-08-m3/HEAL-3-decennial-2000.md`.**
  One `requeue_parcels.py --from-ledger --sources census_decennial
  --include-absent-api` run against `5f3aa7d`, 139 parcels, exit 0.
  `census_snapshots` `decennial`/`2000` went **48 → 111**; the ledger's latest
  `2000` outcomes are now `ok` 111 / `absent` 76. **All 63 gained rows are on
  tracts ending `00`, and the 76 that stayed absent are 60 real-suffix tracts
  plus exactly the 16 §1.5 named — no other tract in either set.** The blast
  radius above is therefore confirmed in both directions from production, and
  the "64 of those 80 answer 200" figure can drop its UNVERIFIED marker: 63 of
  79 answered, the missing one being `6563dedf`, whose tract also ends `00` and
  which a full-scope ride-along healed 13 minutes before the sweep. Racebrook
  (`09170157100`) stayed absent and was, as this entry predicted, the only
  parcel expected to. **What this does not close:** the 76 permanent absences
  are indistinguishable in the ledger from a request that has since been fixed,
  so every future `--include-absent-api` run re-selects them — Y7 below.

- **Every user-facing "1990" claim is now false, and the copy batch has not
  run.** Recorded 2026-08-26 with the census decennial fix (`e6afa9b`). The
  decennial floor in production is **2000 for 111 parcels and 2010 for the
  other 75** once the fix is deployed and swept; 1990 has never held a single
  row in `census_snapshots` and cannot until the census tabular ingest lands.
  Inventoried with file:line and **deliberately not edited** — the copy batch
  is separate, as the NAIP 2003→2010 correction was:
  `README.md:81` ("Nationwide, **1990–2023**"), `README.md:205` ("the 1990
  data may represent a much larger geographic area"), `README.md:207` ("A
  median income of $40,000 in 1990" — median income is an ACS variable the
  decennial config never requested, so this one is doubly false),
  `README.md:17` and `README.md:28` ("Census demographic data across **four
  decades**" — three), and `scripts/seed_featured.py:59` (the Green Valley
  Ranch blurb, same count). Checked and clean: all frontend copy (no
  year-range or decade-count claim anywhere in `frontend/src`),
  `DEVELOPMENT.md`, and the MCP tool-description draft, which is not
  committed. **One deploy-state fact worth carrying into the copy batch:**
  production's `featured_locations` Green Valley Ranch row does *not* contain
  the seed script's "four decades" sentence — the deployed text is the older
  NAIP-only copy, so the false claim is in the script and would reach
  production the next time it is run. The only 1990s claim live in production
  is Hudson Yards' *"Landsat imagery from the 1990s"*, which is true.
  `census.py`'s own docstring said "Decennial Census (1990–2020)" and was
  corrected in `e6afa9b` — it is the code's claim, not product copy. Evidence:
  `../2026-08-census-decennial/REPORT.md` §3.

  **Resolved, this commit, 2026-08-26.** All six lines corrected to the true
  floor (decennial 2000, ACS5 2009); before/after and the re-verified prod
  comparison are `../2026-08-census-decennial/REPORT.md` §10. Prod's
  `green-valley-ranch` blurb still carries the older NAIP-only text, not
  the script's now-fixed sentence — confirmed unchanged and not reconciled,
  per §10. Guard added: `test_readme_decennial_floor_matches_config` in
  `backend/tests/test_census.py`, delete-the-fix verified against the
  pre-edit README.

- **`socrata.py` reads a 404 as "this county has no records" — the same
  collapse the census fix just closed, one path over.** Found 2026-08-26 by
  grepping for the shape while splitting the census reason
  (`../2026-08-census-decennial/REPORT.md` §4). `socrata.py:73-78` maps a 404
  to `return []`, and a 404 on a Socrata resource means the dataset id is
  wrong or the resource was removed — a failure — not an empty result set.
  Every other outbound client was checked and is clean: TNM
  (`usgs_topo.py:106`) raises for status and the task ends `failed`, `arcgis`
  and `ckan` raise on non-200, `stac.py:1120-1127` treats a `>= 400` as a
  broken asset and keeps the status. **Unfixed and lower-stakes than the
  census one for a structural reason: the property path has no ledger source**
  — the M4 sweep's sources are `census_*`, `landsat`, `sentinel2`, `naip`,
  `topo` — so nothing is recording the wrong answer, and nothing would read a
  right one either. Fixing it properly means deciding what the property path
  records, which is M3-adjacent work, not a patch. Recorded because an
  undocumented live instance of a shape we just spent a batch closing is
  exactly what norm 3 is for.

- **Decennial 2000 has no geocoder vintage, and whether it should is
  unanswered.** Recorded 2026-08-26. `_GEOGRAPHY_VINTAGES` maps eight
  (dataset, year) pairs; decennial 2000 is not one, because its geography
  predates `Census2010_Current`, the geocoder's oldest vintage. That costs
  2000 **only** where the stored county-equivalent is not the one the 2000
  vintage answers under, which today is exactly one parcel — `2f1b332e`,
  Racebrook, whose stored county is a planning region and which therefore
  stays `absent` for 2000 even with the tract width fixed. Mapping decennial
  2000 to `Census2010_Current` would recover it, and the argument is the same
  one already accepted for acs5 2009 in `4ce1822`: the 2010 tract is strictly
  closer to 2000 geography than the 2020 one, a redistricted parcel gets the
  same 204 it gets today, so it is never worse and can only add rows. **Not
  done** — it is a fleet-wide behaviour change (three more geocoder calls per
  fetch and a different tract asked for 186 parcels) to recover one parcel,
  and it was outside the brief that found it. Whoever does it should predict
  the fleet effect first, the way the acs5 2009 ride-along was not.

- **A Connecticut parcel's `county` is now a planning-region name, and the
  property adapters have never seen one.** The geocoder writes
  `parcels.county = "South Central Connecticut"` for `2f1b332e` (production,
  2026-08-25), because that is the county-equivalent `BASENAME` the current
  vintage returns (`geocoder.py:352`). `get_adapter_for_county` matches on
  that string, so any future Connecticut adapter has to be keyed to planning
  regions, and `SUPPORTED_COUNTIES.md` will disagree with what the geocoder
  produces for the state. No adapter exists for Connecticut today, so nothing
  is broken now; recorded because the first one written will be written
  against the wrong key otherwise.

- **A served NAIP card is built from a tile the point-coverage gate rejects.**
  `e513188c` serves an `imagery_snapshots` row for NAIP 2023
  (`nj_m_4007309_sw_18_030_20230820_20231019`, created 2026-05-23), and the
  2026-08-26 sweep recorded that same group `suppressed` /
  `naip_no_point_coverage` naming that same item id — *"selected tiles do not
  contain the parcel"*. The gate (`14b59af`) refuses to **write** such a row;
  it does not remove one already written, and reconciliation leaves suppressed
  groups alone by the same rule that protects absent ones. So the gate has
  positively identified a served card as not covering its parcel and the card
  is still served. **One instance fleet-wide** — the other eight `suppressed`
  rows (`1754635c` ×5, `8d9ee137` ×3) have no served snapshot for their
  groups. Evidence: `../2026-08-m4-ledger/HEAL-SCORECARD.md` §5, §13.1.

- **A total `/featured` outage renders as a healthy landing page — M11's shape,
  on the flagship surface.** `FeaturedCards.tsx:129-130` is
  `apiLocations && apiLocations.length > 0 ? apiLocations : PLACEHOLDER_CARDS`,
  and the component destructures only `data` from `useQuery` (`:110-114`) — no
  `isLoading`, no `isError`, no `status`. Loading, fetch failure and
  `{"locations": []}` therefore collapse into one branch: `data` is `undefined`
  both before the query resolves and after it fails, and `[]` when the response
  is empty. **The six fallback cards are not skeletons.** They carry real
  editorial names and blurbs (`:20-22`), render through the identical card JSX
  as live data with no dimming or shimmer (`:147-185`), and each is wrapped in
  `<Link to={`/featured/${card.slug}`}>` (`:154-155`) whose six slugs are
  byte-identical to the six real seeded slugs — verified 2026-08-24 against a
  captured `/featured` payload (`frontend/src/test/fixtures/featured-list.ts`).
  On a 5xx the client throws (`api/featured.ts:119-125` →
  `api/client.ts:38-46`), `retry: 1` (`main.tsx:12`) gives two attempts, and
  then the page sits on placeholders **permanently with no error indication
  anywhere**. The failure surfaces only one click later and on a different
  page: `FeaturedRedirectPage.tsx:45-60` for the 5xx, `:26-43` (404) for the
  unseeded case — which is also the only place the two are distinguishable.
  **The empty-response fallback is deliberate and documented** (`:3-4`, "falls
  back to static placeholders if the API returns nothing (e.g. before
  seeding)"); the failure case silently inherited it, because `apiLocations &&`
  cannot tell "returned nothing" from "failed to return". This is the same
  class as the M11 row above (Medium, `Resolved (256ed32)`, which fixed
  `ParcelInfo.tsx` and `DemographicsPanel.tsx`) — the landing page was not in
  that sweep's scope. **Not fixed, deliberately: recorded before acting**, and
  the fix is a product decision, not a mechanical one. Splitting the branch is
  two lines, but *what* an outage should show — stale placeholders with a
  banner, an empty state, or the cards suppressed — is a call about the
  flagship page that belongs to Ryan. Observed by code reading, not by
  reproducing an outage; nothing was fixed or changed in `FeaturedCards.tsx`.

- **Adams County property returns empty, every time.** The single Adams parcel
  has run five property tasks across two months — two of them after the H4
  fix shipped — and every one reported `complete` with `items_found: 0`.
  `property_events` for Adams holds zero rows, ever. H4's fix only fails a
  task when *all* queries fail, so a silently-empty adapter is
  indistinguishable from a genuinely empty result, and the database cannot
  tell them apart no matter what is queried. **This needs a ten-minute manual
  check against the county's portal before any code is written** — the answer
  determines whether this is an adapter bug, a retired endpoint, or a parcel
  with genuinely no records. Santa Clara is weaker but similar: two parcels,
  one event between them. Ops audit MEDIUM-3.

  *2026-08-27, narrowed by the retry/ops batch without any code — and the
  narrowing is the answer to half the question. Production now shows **8**
  Adams property tasks, every one `complete` with `items_found: 0`. Adams runs
  exactly **one** query, through `query_feature_service`, and **every** non-200
  from that client already raised `ArcGISError` before this batch, a 429
  included. One query, one failure, `all_queries_failed`, task `failed`. No
  Adams task has ever been `failed`. **Therefore no Adams query has ever
  errored: the portal answered 200.** So this was never a swallowed error, and
  the remaining possibilities are two, not three — the feature service returns
  zero features for that WHERE clause, or it returns rows the address matcher
  rejects (Z4 above). The manual portal check is still owed and is now a
  narrower question: does Eye On Adams return features for this address at
  all? The batch predicts Adams stays `complete:0`
  (`../2026-08-ops-batch/PREDICTION.md` P-7) — it changes nothing here, and
  saying so before the run is the point. Santa Clara is on CKAN, which never
  collapsed a status either; 16 of its 23 tasks are `complete:0` and this
  batch does not move them.*

  **CLOSED as a data question, 2026-08-27 — this is a jurisdiction gap, not
  an adapter bug, and it is confirmed twice from two independent directions.**

  *(1) Portal check, run 2026-08-27 — the ten-minute check this row has been
  asking for since the ops audit.* The exact pattern the adapter sends returns
  **`count=3`** against the county layer, so **the WHERE clause is correct**
  and the "does `CombinedAddress` hold this address in this form" candidate is
  dead. Eye On Adams's Emerson St coverage runs house numbers **5600–8371** —
  the unincorporated pocket south of roughly 84th Ave — returned ascending
  with **no `exceededTransferLimit`**, so the list is complete rather than
  truncated. **12804 Emerson is on the 128th Ave block, inside Thornton, which
  issues its own permits.** The county layer is not missing this property's
  records; it was never the authority for them.

  *(2) The scoring sweep, 2026-08-27 — `../2026-08-ops-batch/SWEEP-SCORECARD.md`
  §5.* P-7 confirmed: the task ran, completed, `items_found: 0`. The chain is
  in the worker log — `ArcGIS Feature Service query` on
  `Building_Permits_Eye_On_Adams/FeatureServer/0` with
  `where: upper(CombinedAddress) LIKE '12804 %EMERSON%'`, then
  `ArcGIS response rows: 0`, then `Property events filtered raw_count: 0
  matched_count: 0`. **`raw_count=0` is exactly what the portal check
  predicts**: a correct query against a layer whose jurisdiction excludes the
  address. The two observations were made independently and agree.

  **Nothing is owed on the portal.** All three of the previous paragraph's
  candidates are resolved: the clause is right, the list is complete, and the
  parcel's permits exist — in Thornton.

  **What is owed is code, and it is a new shape: a municipality coverage
  gate.** The adapter needs `covers(city)` at the adapter level, so an address
  inside a home-rule municipality the county layer does not serve resolves to
  the existing **skipped / not-covered** task state rather than to
  `complete:0`. This is the same distinction H4 and Z2 drew one level down —
  "we did not ask" is not "we asked and there is nothing" — and Adams is the
  first case where the boundary is jurisdictional rather than technical.
  Denver and DC are city-counties and so cannot show it; any future
  county adapter over a metro with incorporated municipalities can.

  **Z4 is not the explanation here and no longer cites Adams.** It stays open
  for the other counties, where the sweep did prove it real (DC returned
  `raw_count 1 → matched 0` on one task).

  **Two notes that survive this closure.** Eye On Adams is **2011-onward and
  status-filtered**, so even a covered address gets a partial permit history
  from it — a coverage limit, not a bug, and one nothing currently records.
  And **which `street_name` form the pipeline passes is still unanswered**:
  this parcel's query went out as `%EMERSON%` with no suffix, which happened
  not to matter here because the jurisdiction excluded it anyway. That
  question applies to **Denver and DC**, whose non-zero results could be
  thinner than they look for the same reason, and it is not closed by
  anything above.

  *Santa Clara, re-checked in the same sweep: 7 parcels, 2 with events (2
  items between them), 5 `complete:0`, zero CKAN errors across 21 queries —
  P-9 confirmed, unmoved, as predicted.*

  **Resolved-observed, deployed `fbdc2f7` 2026-08-27T23:17Z, scored
  `../2026-08-property-outcomes/SCORECARD.md` P-1/P-2 (2026-08-27T23:48Z).**
  A 32-parcel targeted requeue (`--sources property`) fired the gate live
  for the first time: the Adams parcel and four Palo Alto/Mountain View
  Santa Clara parcels resolved `skipped`/`coverage='not_covered'`/
  `queries_run=0`; both San Jose parcels stayed `covered`; **the pinned
  weak spot fired exactly as predicted** — Cupertino's city-level geocode
  (`city_from_address` returns `None`) resolved `covered` and ran 3 queries
  against nothing, `rows_returned=0`. See AA2 below for that annotation.
  Zero falsifiers triggered across all five checked conditions (SCORECARD
  §9). `CountyAdapter.covers(city)` defaults to True
  (Denver, DC and NYC are city-counties or a borough and have nothing to gate
  on); Adams denies a list of mailing cities, Santa Clara allows San Jose
  only. An address that fails the gate resolves to `skipped` with
  `coverage='not_covered'`, `items_found` NULL and **zero queries run** — the
  same "we did not ask" state the no-adapter skip already had, one level down,
  now distinguished from it by `coverage` (`no_adapter` vs `not_covered`).

  **The rule's sources, and one that turned out not to be one.** The prompt
  expected the county layer's definition query to carry the jurisdiction; read
  2026-08-27, `Building_Permits_Eye_On_Adams/FeatureServer/0?f=json` has a
  null `definitionExpression` and a `definitionQuery` that filters
  `ApplicationStatus` only — **no jurisdiction at all**. So the rule is
  derived from what the layer holds: the portal check above, plus a fresh
  house-number sample taken for this batch (2026-08-27, HURON / YORK /
  WASHINGTON / EMERSON, 4,013 house numbers spanning 741–16610, **zero**
  anywhere in 9000–13600 — the Thornton/Northglenn/Federal Heights band).
  DENVER and BRIGHTON are deliberately *not* denied: `8601 EMERSON CT, DENVER,
  CO, 80229` and `16610 YORK ST, BRIGHTON, CO, 80602` both geocode to Adams
  County and the layer holds records for both, so denying on mailing city
  alone would have lost them. **Santa Clara's "weaker but similar" note is
  closed by the same gate**: four of its seven parcels (three Palo Alto, one
  Mountain View) become `not_covered` at the next run; the Cupertino parcel
  does not, and `PREDICTION.md` P-2 says so before the run and explains why.

  **Two things this does not fix.** Eye On Adams's 2011-onward,
  status-filtered coverage is still unrecorded — `coverage='covered'` says the
  county is the authority, not that its feed is complete. And the
  `street_name` question the paragraph above left open is now answered and
  filed as **AA3**: no adapter ever receives a suffix at all, so the ST/STREET
  framing was the wrong one. `../2026-08-property-outcomes/REPORT.md` §5, §7.
- **Incidental, from the same finding:** the 2026-08-11 incident parcel
  recorded `property complete:0` during the burst window while its five Denver
  peers hold 10–33 events each. Suggestive, not conclusive.
- **A task row carries an error message its own timestamps predate — and no
  code path can produce that.** Local dev DB, task
  `39e83483-9e9b-40ed-abbb-28e20eb95b80` (request
  `377e9f11-efb0-416b-94f3-7ce1ea11e125`, parcel `70a496c7`): `error_message`
  is `All Denver County property queries failed`, a string that enters the
  tree only at 256ed32 (2026-08-03, `timeline.py:840`), while its
  `started_at`/`completed_at` read 2026-03-26 and the parent request's
  `updated_at` reads 2026-05-23. The second failed property row
  (`71448f76`, 2026-08-03 20:57) is entirely self-consistent, so this is a
  one-off, not a pattern. **The code read is done** (see the Notes entry
  below): every writer of `timeline_request_tasks.status`/`error_message`
  also sets `completed_at` in the same statement, so no path leaves the
  timestamp stale while rewriting the message. If a path *did* exist it
  would mean task timestamps cannot be trusted to describe the outcome they
  sit next to — which is why this is written down rather than dismissed.
  What is left is not a code question but a provenance one: whether this row
  was hand-edited in psql during development, which is the likeliest
  explanation and would make it dev-only noise. **Do not build a fix on this
  row.** Anyone tempted to should first confirm the anomaly reproduces
  somewhere other than one developer's long-lived volume.

- **The ledger recorded its first production `failed` rows — 34 of them, six
  hours after the baseline said zero — and today's backfill cannot reach
  either parcel.** Found 2026-08-26 while gathering prod numbers for the M3
  design investigation (`../2026-08-m3-design/INVESTIGATION.md` §8.3).
  `BASELINE-failed.txt` (03:07Z, SHA `3a86dd69`) reads *"No ledger rows
  match"* and P4 was confirmed at zero `failed` fleet-wide; by ~10:00Z there
  are 34, all `read_timeout`, on two parcels created the same morning.
  (1) **`09f35468`** (New York County NY, created 08:04:56Z): `landsat/1994`
  `failed`/`read_timeout` under a `landsat` task that reads `complete` with
  `items_found` 42, request `complete`. One silently lost year — the M4 shape
  exactly. (2) **`6563dedf`** (Crawford County MI, created 09:14:34Z): **16
  contiguous Landsat years (1984-1999) and all 17 NAIP years (2010-2026)
  failed**, task rows `naip` **failed** / `sentinel2` **failed** / `landsat`
  `complete` (27 items) / `usgs_topo` `complete` / `census` `complete` /
  `property` `skipped`, **request `complete`**, and the parcel serves **27
  Landsat, 0 NAIP, 0 Sentinel-2** snapshots. **Neither is reachable by any
  self-running code path.** Walk `maybe_refetch_for_backfill`
  (`imagery.py:347-471`) against `6563dedf`: the census task exists and is
  `complete` (no trigger); `get_adapter_for_county('Crawford')` is `None`, so
  trigger 4 short-circuits and the `skipped` property task is never consulted
  (no trigger); a `usgs_topo` task row exists, and that check tests row
  absence only (no trigger). `needs_refetch` stays false on every page view,
  forever. `revalidate_landsat.py` would not find it by selection either —
  its predicate is parcels *holding* Landsat rows, and this one holds 27.
  **Three things this establishes.** (a) The instrument works: before the
  ledger, `09f35468` was undetectable and `6563dedf` was "a parcel with no
  NAIP, cause unknown" — the same sentence occurrence (4) took an
  investigation to answer. (b) The M4 row's "zero `failed` rows fleet-wide"
  was true as measured at 03:07Z and is **not edited**; this is the later
  measurement. (c) It is M3's sharpest acceptance case — a live parcel whose
  page shows no aerial imagery at all, with two `failed` task rows and 33
  `failed` ledger rows naming exactly which years to re-ask for. Whether the
  timeouts were a single upstream burst (both parcels are within 70 minutes of
  each other) or a per-parcel condition is unestablished; the logs for
  08:00-09:20Z were not read. **`6563dedf` healed, 2026-08-27 —
  `../2026-08-m3/HEAL-2-crawford.md`, scoring `../2026-08-m3/PREDICTION.md`
  P3.** Two explicit-exception writes against deployed SHA `5f3aa7d`: a
  `--from-ledger` requeue recovered all 33 `failed` groups on the first
  re-attempt (16 Landsat `ok`, 6 NAIP `ok`, 11 NAIP `absent`/`no_scenes`,
  zero re-failures), then a full-scope requeue gave Sentinel-2 its
  first-ever ledger rows (12/12 `ok` — see Y2's addendum). The parcel now
  reads `complete` and serves 43 Landsat, 6 NAIP, 12 Sentinel-2, 3 topo, 9
  census rows; no cross-source regression. **`09f35468` (New York County
  NY) is untouched and remains unfixed** — it was not in scope for this
  batch and needs its own requeue.

  **Both parcels re-checked by the retry/ops scoring sweep, 2026-08-27 —
  `../2026-08-ops-batch/SWEEP-SCORECARD.md` §4.** `6563dedf`'s 33 groups were
  all re-attempted under the new code and **none re-failed**: 16 Landsat `ok`,
  6 NAIP `ok`, 11 NAIP `absent`/`no_scenes` — group for group the same 22/11
  partition heal 2 produced a day earlier. The 11 absences are therefore
  stable rather than intermittent, which is what "real absence" was supposed
  to mean and had not been re-tested. **`09f35468` landsat 1994 is now fixed,
  and by a plain re-run rather than by anything in the batch.** It came back
  `ok` with a new snapshot row (`LT05_L2SP_013032_19941028_02_T1`,
  1994-10-28), against an explicit prediction that it would not heal
  (`../2026-08-ops-batch/PREDICTION.md` P-5, **falsified** — the guess was
  recorded so the outcome could not be read backwards, and the guess was
  wrong). No retry ran on this parcel; the mechanism is the Crawford-era one,
  a whole second task run. **The ledger now holds zero `failed` rows
  fleet-wide** — the first time that has been true since 2026-08-26 03:07Z,
  and this time it is a measurement over 16,691 recorded triples rather than
  over an empty table. The open question this row raised — single upstream
  burst or per-parcel condition — is now answered in favour of the burst: two
  parcels 70 minutes apart, both fully recovered on re-attempt, nothing
  recurring in a 189-parcel sweep.

## Notes for future readers

- **Heal invocations via `fly ssh console -C` write their stdout to the ssh
  session, not to `fly logs`. Capture the invocation's stdout to a file in
  addition to both log streams (HEAL-3 §2).**
- **A deploy is two apps. `/api/v1/health` reports one of them.** Check
  `fly image show -a plotline-worker` before any sweep or heal (Z7).
- **`partial` is terminal and serving. It is not an error state, and the day
  something renders it as one is the day this note exists for.** A `partial`
  timeline request finished, at least one source failed, and at least one did
  not — a Crawford County parcel showing Landsat and topo while NAIP and
  Sentinel-2 both timed out. There is a timeline on the page; it has a hole in
  it. Everywhere that used to ask `status === "complete"` before unblocking a
  dependent query or stopping a poll now asks `isTimelineDelivered` or
  `isTimelineTerminal` (`frontend/src/utils/timelineStatus.ts`), and the two
  places that render an error — `ParcelInfo.tsx`'s "Timeline failed" line and
  `Timeline.tsx`'s "We couldn't build the timeline" block — deliberately still
  test `=== "failed"` and must keep doing so. Which sources failed is on the
  **task** rows, which is where `ParcelInfo`'s `unavailableSources` already
  reads it from. **`partial` deliberately carries no `error_message`**: both
  renderers of that field are gated on `failed` today, so setting one would be
  invisible now and one refactor away from becoming a red banner over a working
  timeline. The worker logs the failed source list instead. Two failure modes
  are worth naming because neither is loud: a `partial` request that is not
  treated as terminal polls forever, and a `partial` request that is not
  treated as delivered leaves demographics and property events permanently
  disabled on a page that is otherwise fine.
- **Declared scope is intent; eligibility is fact; the worker intersects
  them.** `TimelineRequest.sources` on a full run names all six sources even
  for a parcel with no county, and the worker still runs no property task. It
  is tempting to "fix" that by writing the derived set instead — don't: the
  derived set is 4, 5 or 6 wide depending on the parcel, so it cannot express
  "full scope" as a stable value, and `_find_reusable_request`'s
  `cardinality(sources) = 6` filter is what stops a scoped backfill from
  becoming the parcel's current request and firing the topo trigger on every
  page view forever. The same reasoning is why `normalize_sources` dedupes and
  sorts at the one write site: cardinality is only a sound test for full scope
  if the array cannot hold a duplicate.
- **`dd99cee`'s advisory lock silently rolled back every migration that ran
  under it; `0011` was the first.** An audit fix introduced a silent failure
  of the thing it protected — the second time (O1 was the first). Both were
  found only by measuring production against what the fix claimed, and in
  both cases the fix's own logging said it was working. The general lesson is
  in the X1 remedy rather than in the diagnosis: the runner now reads back
  what it just wrote, on a connection that cannot see its own uncommitted
  work, and refuses to exit 0 if the two disagree.
- **The M4 ledger starts at deploy and carries no history.**
  `timeline_task_years` has no backfill and cannot have one — the outcomes it
  records were never written down anywhere, which is the finding. A parcel
  last fetched before deploy has zero rows. **Absence from
  `scripts/ledger_gaps.py` output means "not yet swept", not "healthy",** and
  it stays that way until every parcel has been swept once. That is also why
  `revalidate_landsat.py` and `heal_tract_vintage_gaps.py` are not deleted
  even though the ledger subsumes their selection logic: a ledger-driven
  selection would miss every parcel the sweep has not reached.
  *Updated 2026-08-26: the fleet has since been swept once — zero parcels have
  no ledger rows — so the premise of that last sentence no longer holds, and
  `heal_tract_vintage_gaps.py` is deleted (`b7c9cbb`, Y5). The caveat itself
  stands unchanged for any parcel added after a sweep, and it is why
  `revalidate_landsat.py` keeps its fleet-wide sweep: "re-run everything under
  the new code" is not a ledger query and never will be.*
- **The ledger deliberately references no snapshot row**, and that is a
  decision, not an omission. `docs/adr/0001-imagery-normalization.md` rule 1:
  ledger rows carry `(task_id, source, group_key, outcome)` and the served row
  for a group is looked up by `(parcel_id, source, group_key)` at read time.
  That decoupling is what lets the normalization pass replace
  `imagery_snapshots` with `scenes` + `parcel_scenes` without touching this
  table. **Do not add a `snapshot_id` column, even as a nullable
  convenience.** Rule 2 of the same ADR makes `group_key` the shared
  encoding — it is defined once in `services/imagery.py` beside
  `SELECTION_SCOPES`, and `parcel_scenes.group_key` is meant to speak it too.
- **A rename can turn a mocked test into a live one, and the suite has no
  network guard.** Found 2026-08-25 while wiring the ledger: the topo path
  moved from `search_usgs_topo` to `search_usgs_topo_products`, and three
  tests in `test_timeline.py` that patched the old name began making real
  requests to `tnmaccess.nationalmap.gov` — HTTP 200, 152 KB, row-cap warning
  and all — while still passing. They now patch what the code calls. Nothing
  in the harness would have caught it; `-p no:cacheprovider` style network
  blocking is not configured. Worth a `socket`-blocking conftest hook if this
  recurs. **Resolved:** 794af9f, 2026-08-26 — `pytest-socket` with
  `--disable-socket --allow-hosts=127.0.0.1,localhost,::1` added to
  `backend/pyproject.toml`; full suite re-run clean under the guard (532
  passed under CI env), delete-the-fix confirmed on one of the three named
  tests (live-passes without the guard, blocked-fails with it), and a sweep
  of all 72 `patch`/`monkeypatch.setattr` module-path targets in `tests/`
  found none stale. See `docs/audits/2026-08-test-network-guard/REPORT.md`.
  Every "N passing" count reported before this commit may include live-
  network passes the guard would now catch.
- **M9 reads as an oversight; it isn't.** See the accept rationale above —
  c6213d5 predates the audit by three months.
- **L12's URL-normalization item cites no file.** The code is
  `config.py:83-89`, duplicated verbatim in `alembic/env.py:36-42`. Both
  copies miss `ssl=True` capitalization.
- **H4 is resolved, but bare excepts are not gone.** The adapters are clean;
  the pattern persists in the caller — `timeline.py:196, 400, 501, 650, 997,
  1000, 1024`, `imagery.py:603`, `preview_renderer.py:103`.
- **Test coverage.** `maybe_refetch_for_backfill` gained two cases via 256ed32
  and two more with the cooldown; its full decision table is still not
  covered.
- **FINDINGS.md's Redis caching claim is stale, and that document is frozen.**
  The first audit recorded "SAS tokens are cached for 10 minutes (tokens last
  ~30 minutes). stac.py handles signing gracefully — if signing fails, falls
  back to unsigned URL" (`../2026-05-first-audit/FINDINGS.md:132`). Three of
  its clauses are now false. (1) The TTL is **1200 s**, not 600
  (`_SAS_CACHE_TTL`, `stac.py:183`). (2) `sas:{url}` is no longer the sole key
  and no longer the blob path's key at all — blob hrefs sign with a
  container-scoped token cached under `sas-token:{account}/{container}` on a
  TTL derived from the token's own `se` (`stac.py:450, 491-508, 547-550`), and
  **four** other key families share the instance: `stac:{snapshot_id}` (3600 s,
  `api/imagery.py:739, 768`), `autocomplete:{q}` (300 s, `api/geocode.py:34,
  52, 147-151`), `ratelimit:{path}:{ip}` (`rate_limit.py:59, 67-70`), and
  Redis's separate role as the Celery broker and result backend
  (`celery_app.py:39-44`). (3) The unsigned-URL fallback is gone from every
  site — that is O1. **`../2026-08-source-inventory/INVENTORY.md`, "Caching
  ledger", is the correction of record**, including its list of what is cached
  nowhere. FINDINGS.md stays frozen and unedited, under the same rule that
  governs the Build Log.
- **The census upsert did not refresh `tract_fips`.** Found while triaging the
  phantom net-loss flag (`docs/audits/2026-08-geometry-audit/CENSUS_TRIAGE.md`
  §4), not by either audit. `demographics.py` refreshed all eleven demographic
  columns and `raw_data` on conflict but left `tract_fips` at its first-written
  value, so a re-run resolving a different ancestor tract for a year would
  overwrite the numbers while keeping the old tract's label. **Fixed in
  386f3e3**, with a regression test for the changed-tract case
  (`test_census.py::test_upsert_relabels_when_tract_changes`); the pre-existing
  idempotency test passed the same tract twice and never reached it. No
  existing row is mislabeled — see that commit message for why the pre-fix code
  paths cannot have produced one, and why no query can prove it directly.
  Unrelated to M4: no new occurrence data came out of the triage.
- **A frontend test harness exists as of 1a8bb3c (2026-08-24).** Vitest +
  @testing-library/react + jsdom, run with `npm test` in `frontend/`; the
  suite is 17 tests across `HousingChart`, `DemographicsPanel`, `ParcelInfo`,
  `useAddressAutocomplete`, `SearchInput`, `SearchBar` and the types contract
  test (15 at 1a8bb3c; L8's fix converted three `it.fails` into guards and
  added `SearchBar.test.tsx`). CI runs
  it as the `test-frontend` job behind a `frontend/**` path filter.
  **Blocking as a signal from the commit carrying this note**
  (`continue-on-error` removed): a red run is visible on the PR and has to be
  dealt with. The L8 clear-before-resolve tests landing in `07b55e0` met the
  first of the two old triggers, so **the 2026-09-30 backstop is retired** — it
  has been acted on.
  **This gates no deploy, by design.** The job is deliberately absent from
  every deploy job's `needs`, because the frontend ships through the Cloudflare
  Pages GitHub integration, which watches the repo directly and never reads an
  Actions result — adding it to `needs` would change what a red run looks like
  without stopping a byte from reaching production. A real gate is **deferred
  to its own pass**: move the Pages deploy into a `deploy-frontend` job behind
  `needs: [changes, test-frontend]` driven by `wrangler pages deploy`, and
  disconnect the Pages GitHub integration. That pass has to re-create preview
  deploys and add a Pages API token, which is why it is not this one. The
  rejected cheaper alternative — `npm ci && npm test` inside the Pages build
  command — puts the gate in dashboard config where no review sees it. Full
  trade-off in report `05-…` under `docs/audits/2026-08-frontend-tests/`.
- **A gating CI will block L8's own fix, and that is intended.** Vitest counts
  an `it.fails` test whose body throws as a *pass* — the suite is green and
  exits 0 today with four such tests in it (H1's decennial half, and L8's
  three). When the underlying bug is fixed, those tests report "Expect test to
  fail" and the run exits non-zero. `test-frontend` is blocking as of the
  commit carrying this note, so the commit that fixes L8 — or H1's decennial
  half — turns CI red until the same commit removes the corresponding `.fails`
  marker and converts the test into an ordinary regression guard. Written down
  because a fixer who does not know this reads a red CI on a correct fix as a
  broken test. Measured, not assumed: `npm test` exits **0** with all four
  `it.fails` tests present (15 passed), and **1** when an ordinary assertion is
  broken. **Observed, 2026-08-24 — confirmed:** the L8 fix commit removed its
  three markers in the same batch, exactly as predicted here, and `npm test`
  exits 0 with 17 passed. The prediction's mechanism was also re-measured
  against the fix: with `clearOnSettle` reverted to a synchronous clear, the
  suite reports **3 failed | 2 passed** plus two unhandled rejections, so the
  three tests do bite on the real defect and the empty rejection handler is
  load-bearing rather than decorative. Fixtures under `frontend/src/test/fixtures/` are real captured API
  payloads with provenance headers (endpoint, parcel, capture date, backend
  SHA), never objects built from the TypeScript types — DEVELOPMENT.md records
  what hand-built input cost the backend suite.
- **Fixture provenance is a correctness property, not bookkeeping — the first
  version of these tests got it wrong.** 7a273fd shipped a
  `demographics`/`events` pair captured from a fresh geocode *before its census
  task ran*, and paired it with a hand-typed `censusStatus="complete"`. The
  payloads were real; the combination was not. That parcel's census task in
  fact completed with **7** items and property with **9**, so the state under
  test — "completed, and there is genuinely nothing here" — was never the state
  captured. Corrected in the commit carrying this note: the complete-with-zero
  case now uses the Adams County parcel `e032a469` (9 census snapshots, zero
  property events, property task `complete` at 0 items — payloads and task rows
  from the same run), and a separate coherent in-flight triple
  (`*-inflight.ts`, all three captured in one instant, request `processing`,
  every task `queued`) covers the not-yet-fetched state. Tests now read task
  status *out of* a captured timeline-request fixture via a `statusOf` helper
  rather than typing the literal, so a status can no longer drift from the
  payload it describes. **Never hand-edit a field inside a captured fixture** —
  a fixture with one edited value is a hand-built fixture wearing a provenance
  header, which is worse than an obviously synthetic one.
- **One frontend test is expected to fail, on purpose** (H1's decennial half).
  *Was four until L8's fix; the three L8 markers were removed in the same
  commit that fixed it — see the L8 row and the gating note above.*
  `HousingChart.test.tsx` asserts via `it.fails` that a decennial year with a
  housing-unit total appears in the chart. It does not — that is H1's open
  decennial half. The captured Stapleton fixture shows the real shape: 2010 and
  2020 carry `total_housing_units` (1,773 and 2,642) with a null tenure split,
  because that is what the decennial tables return. When H1 is fixed the
  assertion starts passing and `it.fails` reports it as a **failure** — that is
  the signal to delete `.fails`, not to weaken the assertion.
- **Frontend/backend schema drift was measured across the whole surface, and
  it is two fields.** The `TimelineRequestTask` omission found earlier was not
  the tip of a pattern; it was very nearly all of it. The sweep diffed all 19
  backend `BaseModel` classes against all 16 frontend interfaces, field by
  field, and assigned every captured fixture to its declared type under `tsc`.
  Result across ~102 declared fields and 16 type pairs: **two** backend-declared
  fields missing from the frontend (`started_at`, `completed_at` on
  `TimelineRequestTask`, from `schemas/imagery.py:23-24`), **one** optionality
  mismatch (`supported_counties`), and **zero** frontend-only fields, zero
  renamed-in-transit fields, zero type mismatches. Both are fixed in the commit
  carrying this note: the timestamps land as `string | null` rather than `?`
  because no route sets `exclude_none`/`exclude_unset`/`exclude_defaults`
  (grepped: zero hits in `app/api/` and `app/main.py`) so the keys are always
  present and may be null; `supported_counties` becomes required because
  `api/v1/events.py` always populates it from
  `get_supported_county_display_names()`.
- **No backend finding: the API returns exactly its own contract.** Every
  captured fixture's key set equals its Pydantic schema's key set exactly, top
  level and nested, in both directions, across all 12 fixtures. Nothing escapes
  the response model.
- **What the contract test locks, and what it does not.**
  `src/test/types.contract.test.ts` gates on `npm run typecheck`, not `npm
  test` — Vitest strips types without checking them, so the suite passing
  proves nothing; `tsc --noEmit` is the gate, and `npm run build` already runs
  it. It **locks** 6 endpoints: `POST /geocode`, `GET
  /parcels/{id}/demographics`, `GET /parcels/{id}/events`, `GET
  /timeline-requests/{id}`, `GET /parcels/{id}/imagery`, and `GET /featured` —
  and through the last two, the `ImagerySnapshot` and `FeaturedLocation`
  element types. It does **not** cover
  `GET /parcels/{id}` (`ParcelResponse`), `GET /geocode/autocomplete`
  (`AutocompleteSuggestion`), `POST /parcels/{id}/timeline`, or `GET /health`
  (`HealthResponse`, `VersionInfo` — the frontend never calls it). Those four
  are held only by the hand diff above, which is the same process that produced
  the drift in the first place.
- **The contract test is structurally blind to optional-vs-required, and
  `supported_counties` is the proof.** All three events fixtures carried the
  field; the frontend declared it `supported_counties?: string[]`; an optional
  property accepts a present value, so `tsc` said nothing. The evidence was
  sitting in the fixtures the whole time and no amount of running the check
  would have surfaced it. Only the hand diff against the Pydantic schema found
  it. **A green contract test means no missing, extra, or mistyped field — it
  does not mean the optionality is right.** Anything that becomes optional on
  the frontend has to be justified against the backend schema by hand.
- **The check needs two mechanisms, because plain assignment is half-blind.**
  TypeScript's excess-property check fires only on object *literals*; the
  fixtures are imported consts, so `const x: T = fixture` silently accepts a
  payload carrying fields `T` never declared — which is exactly how the
  original drift survived. The test therefore pairs an assignability check
  (via a homomorphic `Mutable<T>` that strips `as const` while keeping
  `bbox`'s 4-tuple from decaying to `number[]`) with a recursive `ExtraKeys`
  walker. Both directions were confirmed by deliberate breakage and restored.
- **`PropertyEventType` declares two members no backend path can produce.**
  `zoning_change` and `assessment` have no producer: `classify_permit`
  (`services/county_adapters.py:861-890`) emits six `permit_*` values and the
  adapters emit `"sale"` directly — seven in total against the union's nine.
  Both are *read* (`constants.ts:70,75`; `Timeline.tsx:87-88` groups them under
  the "Other" filter), so they are unreachable branches rather than dead code.
  Left in place deliberately: pruning them is a product decision about future
  event types, not a drift fix. Recorded here so nobody re-derives it. No union
  is too *narrow* — every value the backend can emit is representable, checked
  for `ImagerySnapshot.source`, both `status` unions, and `dataset`.
- **`imagery-stapleton.ts` carries the one sanctioned fixture edit, and it is
  mechanical.** This contradicts the "never hand-edit a captured fixture" rule
  three bullets up, so it is written down rather than left for someone to
  discover. 20 of its 70 snapshots (`naip`, `sentinel2`) had `cog_url` values
  signed at response time with Azure SAS tokens; everything through the `?` is
  verbatim and the query string is replaced with the literal `<SAS-REDACTED>`.
  The tokens were read-only delegated SAS for Planetary Computer's *public*
  containers with a ~25h expiry — anyone can mint one anonymously — so nothing
  of value was removed, but a signature parameter does not belong in git
  history and would be stale within a day regardless. `cog_url` is `string` on
  both sides, so the redaction cannot affect what the fixture measures. The
  rule it bends is still the right rule: the edit is uniform, applied by
  pattern rather than by hand to individual values, and stated in the fixture's
  own header. **A per-value edit would not be acceptable on the same reasoning.**
  Note also that `additional_cog_urls` is null on all 70 rows, so the NAIP
  mosaic branch is declared but unexercised, and every nullable field on
  `FeaturedLocation` is non-null across all 6 rows in `featured-list.ts`.
- **Recharts leaves a text-measurement span on `document.body`, and it
  survives `cleanup()`.** It holds the last string Recharts measured, so a
  bare `getByText("2023")` on a chart test matches twice — once in the real
  `<tspan>`, once in that orphan — and fails with "found multiple elements"
  rather than anything that names the cause. Cost a debugging cycle on the
  first chart test. **Scope chart queries to the render's `container`**, e.g.
  `container.querySelectorAll(".recharts-xAxis .recharts-cartesian-axis-tick-value")`,
  never to `screen`. Noted at both sites: `HousingChart.test.tsx` and
  `src/test/setup.ts`.
- **R-numbers collide across the geometry audit (FINDINGS.md §6 remedies) and
  SOURCE-LANDSCAPE (§1 recommendations); qualify every R-citation with its
  document.**
