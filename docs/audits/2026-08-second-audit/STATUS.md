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
| Medium (12) | 4 | 4 | 4 |
| Low (12) | 6 | 2 | 4 |

"Partially resolved" here always means the remainder is an explicit accept or
an explicit deferral, both recorded below — never an unfinished edit.

## The fix commits

| Hash | Covers |
|---|---|
| dd99cee | M6, M10 (advisory lock), L11 |
| 3269bbf | L5 |
| ffb71b2 | L2, L4, L6 (source id), L7, L9 |
| ae5793a | M2 (atomicity), M3 (cooldown), counties item 13 |
| 56d6647 | M9 (exposure), L12 (CORS) |

## High — all resolved

| # | Commit | Verified at |
|---|---|---|
| H1 Housing chart | 6def10c, 1c1c069 | `census.py:57-64`; `scripts/backfill_census_housing.py` |
| H2 Log context | 90ea416 | `logging_config.py:28`; `celery_app.py:61-72` |
| H3 Demographics cache | 90ea416 | `demographics.py:37` |
| H4 Property outage | 256ed32 | `county_adapters.py:33-40,106-121`; `timeline.py:683-697` |
| H5 Address matcher | add8102 | `address_normalizer.py:34-52,76-87`; `tests/test_address_normalizer.py` |
| H6 Landsat duplicates | 96a7962 | `imagery.py:414-503`; `timeline.py:365,454`; `revalidate_landsat.py:65-77` |

## Medium

| # | Status | Where it stands |
|---|---|---|
| M1 Geocoder decode | Resolved (949c1b3) | `geocoder.py:158,196`. The finding's retry-asymmetry aside (only timeouts retried) is unchanged; it was flagged as defensible, not as a defect. |
| M2 Rate limiting | Partially resolved (ae5793a) | INCR and EXPIRE now ship in one pipeline with `EXPIRE … NX`, so a death between them can no longer leave an immortal counter. The X-Forwarded-For handling is accepted — see below. |
| M3 Backfill scope | Partially resolved (ae5793a) | A cooldown (`backfill_cooldown_hours`, default 6) bounds the per-visit cost and logs each suppression. The cooldown is dispatch-anchored — it reads the latest `TimelineRequest.created_at`, which includes a request the current visit may have just created — not completion-anchored; correct for cost-bounding, and the per-source work inherits it unless it deliberately changes it. Per-source scope is deferred, not accepted — see below. |
| M4 Partial census/Landsat failures | Open | `timeline.py:234-259`, `:616-692` (the census year loop moved into `_fetch_census_years` in b5a306a; line numbers refreshed after c82ed51 shifted the file), **and `:434-506`, the topo path — a TNM response truncated at its cap (T3 below), or a product skipped for a missing `sourceId`, drops whole decades under a `complete` task exactly as the census and Landsat halves do, so topo/TNM is the third silent-drop door, not a footnote to the other two.** *Precision correction, 2026-08-15 (source inventory): this clause originally also named "a TNM search that fails", and that half was wrong — a **whole-search** TNM failure propagates out of `_search_and_persist_topo` to `_fetch_usgs_topo`, which marks the task **`failed`**, not `complete` (`timeline.py:457-462`). What does match this row as written is the cap (`usgs_topo.py:89-97`) and the missing-`sourceId` skip (`timeline.py:513-518`). Its sibling, the unparseable-`publicationDate` skip (`timeline.py:497-505`), is a **latent guard rather than a live door** — `select_topo_items` already drops items whose year will not parse (`usgs_topo.py:113-116`), which is the same reachability T2 below establishes for the 1900 fallback, so nothing reaches it.* — failures counted, never persisted, so nothing can target the gaps. Sharper than the finding states on the census half: a year the API has no data for returns `{}` and is skipped by `if data:` (`:639` decennial, `:666` ACS5) **without** incrementing `failed_requests` (`:653`, `:680`), so the all-failed check at `:692` cannot see it either. The gap is not merely unpersisted — it is invisible to the task's own failure arithmetic, which is why a parcel could sit at `complete` with four of six ACS years missing. One instance of that shape — years lost to the 2020 tract redistricting — is healed by b5a306a and its `scripts/heal_tract_vintage_gaps.py`; the general problem of persisting per-year failures is untouched. **Observed in production three times, from three independent upstreams.** (1) 2026-08-11: a burst of 21 SAS signing 429s in four seconds cost one parcel 20 of its 43 Landsat years. (2) 2026-08-12 00:45Z: a second parcel (Ocean County NJ) lost 8 Landsat years — after the incident, and **on production that did not have a536d07**. The throttle was committed 2026-08-11 and left unpushed; CI deploys on push, so the running release was still pre-throttle when those years were lost. Whatever else a536d07 does, it demonstrably did not prevent this: the loss is post-commit and pre-deploy, and no signing-throttle event appears in any log buffer. (3) 2026-08-12 01:25Z: four `httpx.ReadTimeout`s against `api.census.gov` cost a Maricopa parcel its acs5 2021 and decennial 2020 rows — the Census API, not our signing, so no throttle could have helped. Each of the three ended `complete`, and backfill only triggers on failed/missing tasks, so none of them has a healing path. **This row is not "mitigated".** Capping our own call rate narrows one of three doors; a year lost to a Census timeout, a TNM endpoint returning non-JSON (see the zero-topo parcel in the ops audit's §8), or any upstream we have not met yet is still silently dropped under a `complete` task. M4's per-year failure persistence is the actual fix, and it is now scheduled work rather than deferred design — see below. Evidence: `docs/audits/2026-08-ops-audit/FINDINGS.md` §0, HIGH-2, MEDIUM-2. **(4) 2026-08-12, from the geometry sweep: one parcel — `2f1b332e`, Racebrook Road, Orange, Connecticut — still holds only 5 census years (decennial 2010; acs5 2012, 2015, 2018, 2023) against 7–9 for its peers, *after* a full re-run. It is the sharpest instance yet, because nothing in the system can say whether those years re-failed or were never published: the task ended `complete`, no failure was recorded, and the 63 `Census API: no data for tract` 404s observed during the sweep are indistinguishable from genuine absence. Connecticut's 2022 county-to-planning-region change makes genuine absence entirely plausible — which is the point. Telling the two apart is exactly what per-year persistence would buy, and no heal script can be written until it can. Only 3 census rows across 2 parcels were gained sweep-wide, so the opportunistic ride-along did not reach it.** Evidence: `docs/audits/2026-08-geometry-audit/HEAL-SCORECARD.md` §6. *A later commentary restated that ride-along as a net **loss** of 3 rows across 44 parcels; it is a phantom, closed in `docs/audits/2026-08-geometry-audit/CENSUS_TRIAGE.md` — `census_snapshots` has no deletion path, so no census loss is reachable and no new M4 occurrence follows from it. (4) above remains the only occurrence from the sweep.* **Two mechanism gaps recorded 2026-08-15 by the source inventory (`../2026-08-source-inventory/INVENTORY.md`) and tracked as N1 and N2 below.** N1 is a **fourth door, not a fourth occurrence**: `_sas_get` retries only 429 (`stac.py:311-312`), so an unretried PC 5xx or connection error on the signing endpoint returns `False` from `_validate_asset` (`stac.py:1010-1017`), which `_validate_selection` reads as "item is broken" and answers by walking **every** same-period candidate against the same unhealthy endpoint (`stac.py:1107-1123`) before dropping the period (`stac.py:1126`) under a task that still ends `complete` (`timeline.py:435`). N2 names the mechanism behind instance (3): `CensusFetcher._request` has no retry at all (`census.py:249-253`), so **not one of that incident's four `httpx.ReadTimeout`s would have been retried** — this row recorded the outcome, never that the client did not try again. **Neither changes this row's remedy, only its occurrence surface.** Retry-policy work would reduce how *often* a year is lost; only per-year failure persistence makes a loss *visible*, and that is still the scheduled work below. |
| M5 Sync I/O on the loop | Open | `geocode.py:55-57,146-151`; `timeline.py:310-360`. The worker half is accepted; the autocomplete half is not. |
| M6 Redis socket timeouts | Resolved (dd99cee) | `socket_timeout` and `socket_connect_timeout` of 2s on both clients, matching the DB probe's `statement_timeout`. |
| M7 ORM/schema drift | Open | Partial indexes in `0009:49`, `0010:67,83` absent from `models/parcels.py`; `conftest.py:55-190` still hand-written DDL. |
| M8 DO NOTHING freezes records | Open | `property_events.py:74`; `county_adapters.py:466,734`. |
| M9 Titiler callback path | Partially resolved (56d6647) | `/warmup` (30/min as shipped in 56d6647; **60/min since `69b94e1`, 2026-08-04** — `api/imagery.py:624`; corrected here 2026-08-15, see N3) and `/{id}/stac` (600/min) now carry rate limits. The routing itself is accepted — see below. |
| M10 Migration on boot | Partially resolved (dd99cee) | A session-scoped `pg_advisory_lock` in `alembic/env.py` serializes concurrent boots. The worker-ahead-of-schema window is accepted — see below. |
| M11 Failures vanish from UI | Resolved (256ed32) | `ParcelInfo.tsx:131-133,268-275`; `DemographicsPanel.tsx:78-95`. |
| M12 Celery config | Resolved (05bb263) | `celery_app.py:29-31,53`; `timeline.py:950-958`. |

## Low

| # | Status | Where it stands |
|---|---|---|
| L1 STAC pagination loop | Open | `stac.py:141-163` — still no page counter. |
| L2 strict-zip landmine | Resolved (ffb71b2) | Groups filtered once, zipped over the filtered list; test covers an empty group. |
| L3 WHERE-clause escaping | Open | `county_adapters.py:46-56` escapes quotes only; anchoring still differs between `:236,:332,:425,:480` and `:697,:759`. |
| L4 STAC fetch host | Resolved (ffb71b2) | Allowlisted to `planetarycomputer.microsoft.com`, the only host any Landsat row carries. |
| L5 Geocoder county fallback | Resolved (3269bbf) | Fallback removed on both paths; `scripts/heal_county_fallback.py` clears rows already carrying one. Dev had zero. |
| L6 TNM caps and ids | Partially resolved (ffb71b2, c82ed51) | Products with no `sourceId` are skipped instead of colliding on `stac_item_id=""`. Pagination is still accepted — see below — but the cap is no longer silent: c82ed51 warns when a TNM query returns exactly its cap (T3 below). |
| L7 `_fetch_source` coordinates | Resolved (ffb71b2) | Defaults removed; two test call sites were relying on them. |
| L8 Autocomplete self-DoS | Open | `useAddressAutocomplete.ts:12` (150ms); `SearchInput.tsx:35,44,57,112` still clears the input before the geocode resolves. |
| L9 Tile-proxy input | Resolved (ffb71b2) | `z` capped at 0–24; `x`/`y` given one generous static bound, since anything inside it but outside the COG extent already returns a transparent tile. |
| L10 Raw error strings | Open | `schemas/imagery.py:25,38`; `timeline.py:198,402,650`. |
| L11 Prefork engine | Resolved (dd99cee) | `worker_process_init` → `engine.dispose(close=False)`. |
| L12 Misc | Partially resolved (56d6647) | CORS `allow_credentials` dropped. Still open: JSON vs JSONB (`models/parcels.py:323`/`:398`), "declined 0%" (`demographics.py:203-211`), the URL-normalization chain (`config.py:83-89` **and** `alembic/env.py:36-42`), `Dockerfile.fly` running as root with gcc, and DC's hardcoded permit layers (`county_adapters.py:396-404`). |

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
module docstring (`county_adapters.py:1-9`, still "Socrata API quirks" for a
registry that is now 3 ArcGIS, 1 CKAN, 1 Socrata), `parse_date`'s docstring
(`:59`), and DC's unused `APPRAISED_VALUE_CURRENT_TOTAL` (`:434`) remain open.
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
| O6 Sentinel-2 unassessed | Open | The audit declined to apply a flat "healthy ≈ 30 quarters" threshold: observed counts run 13–35 in a smooth continuum with no bimodality, and cloud-cover filtering makes the expected count location-dependent. Sentinel-2 damage is unassessed, not cleared. Doing it properly needs a per-parcel expectation — available scenes versus selected. |

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
`../2026-08-titiler-cache/FINDINGS.md` §4.2, not in the scorecard.

| # | Item |
|---|---|
| G1 | **NAIP suppression is prospective-only. Tool committed (`56a82ec`, 2026-08-12); production execution pending, so both production cards are still wrong as of that date.** 14b59af removes an uncovered year from the selection; `reconcile_source_snapshots` deliberately never deletes an *absent* group, because absence usually means a failed search. The two rules compose into a hole: the gate cannot clear a wrong card that already exists, which is every parcel the audit identified. Both 350 5th Ave 2023 cards still serve `nj_m_4007309_sw`. **Condemnation re-verified against live PC STAC 2026-08-12** (read-only, production search parameters): the 2023 NAIP search over both parcels' bbox returns exactly 3 items — `nj_m_4007424_ne_18_030_20230820_20231019`, `nj_m_4007416_se_18_030_20230820_20231019`, `nj_m_4007309_sw_18_030_20230820_20231019` — all New Jersey quads, **none containing the point**, unchanged from the audit's 2026-08-11 check. Still a data gap, so the remedy is deletion, not re-selection. **Remedy: `scripts/remove_uncovered_snapshots.py`**, the system's first intentional deletion outside reconciliation. Named `--parcel-id`/`--source`/`--year` triples only — no pattern matching, no all-parcels mode, no source-wide mode; dry-run by default, and in that mode it makes no network calls at all; `--execute` refuses unless every tile of each target row's mosaic is fetched from PC and shown to exclude the parcel point, and refuses on unverifiable evidence (an unmappable tile URL, an item PC won't serve) rather than deleting on partial proof. Deletions run in one transaction, each logged with parcel, source, year, stac_item_id and the reason string. Tests: `backend/tests/test_remove_uncovered_snapshots.py` (13). The guard is load-bearing, not decorative: pointed at Hudson Yards — whose 2023 row carries the *same* primary item — it refuses, because that parcel's point falls inside both `nj_m_4007309_sw` and `nj_m_4007416_se`. **Deletion is permanent rather than a dice re-roll**, traced and replayed against live PC: the gate at `timeline.py:292` → `stac.py:623` (→ `stac.py:570`) drops 2023 from the NAIP selection (`[…2021, 2022, 2023]` → `[…2021, 2022]`), so the `groups` set `reconcile_source_snapshots` builds (`imagery.py:626-628`) carries no 2023 bucket and its stale test (`imagery.py:646`) can never mark a 2023 row — no delete cascade, no re-insert. **Run against the local database only** (2 rows deleted, NAIP 300 → 298, Hudson Yards' 2023 row intact); the production execution is Ryan's, post-push. The prediction for that run is written in `../2026-08-geometry-audit/HEAL-SCORECARD.md` (addendum, 2026-08-12) *before* it happens: exactly one row per named parcel, both timelines losing exactly the 2023 card, Hudson Yards and every other NAIP row untouched, and no `naip` 2023 group re-created by a subsequent re-run. |
| G2 | **Rodanthe sentinel2 2015 Q3 unhealed.** Still the 25.04 % non-covering granule from Appendix A. Its 1.01 % covering sibling sits in Q4, a different quarter group, so the quarter-scoped selector never had to choose. 1 of the 15 featured cards remains wrong. |
| G3 | **One duplicate S2 quarter group.** Green Valley Ranch holds two 2026-Q1 rows, created 2026-06-12 and -06-17 — *before* this sweep and not caused by it. 2026-Q1 was not in the run's selection, so the absent-group rule left it alone; re-running cannot clear it. |
| G4 | **Signing storm on the request path during the sweep.** 41 × `SAS rate-limited; backoff exceeds wait budget, giving up`, 17 × `Band signing failed after retries`, 115 Titiler 500s across 5 snapshots. This is O1's act-two mismatch running the other way: the batch path exhausts PC's limit while the request path's 2 s `SIGN_WAIT_REQUEST` gives up at once. A user browsing during a sweep gets 500s. **Attribution now in question:** G5's mechanism produces an identical 500 with no signing failure preceding it, so an unknown share of the 115 is cache-pinned tokens rather than rate limiting. The two are separable in the logs — a G5 500 carries an `se` earlier than its own request time and has no `Band signing failed` line seconds before it on the same snapshot id. Testable post-deploy: whatever survives `cf0df2b` is genuinely G4. **Still untested as of 2026-08-12T20:49Z.** The post-deploy observation (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`) saw 0 Titiler 500s and 0 backoff-exhaustion lines, but no heal sweep was running during it — G4's premise is a batch path exhausting PC's limit *concurrently with* browsing, and that condition never obtained. The clean reading bears on G5/O8 only; G4's share of the 115 remains unmeasured and needs a browse observed during an actual sweep. |
| G5 | **Resolved (`cf0df2b`, 2026-08-12 — deployed 19:53Z, scored clean; see O8 and `../2026-08-titiler-cache/BOUNDARY-BASELINE.md`).** **Cause identified: Titiler's rio-tiler item LRU pinning a SAS token under the constant `/imagery/{id}/stac` URL.** `rio_tiler/io/stac.py:100-102` caches fetched items in a module-level `LRUCache(maxsize=512)` with **no TTL**, keyed on the URL — and Landsat's callback URL was constant per snapshot forever, so the token frozen in the item's band hrefs outlived its 45-minute expiry until eviction or restart. Two independent captures of the shape: `se=2026-08-12T00:00:52Z` at 03:34 (`../2026-08-geometry-audit/HEAL-SCORECARD.md` §4.5) and `se=2026-08-12T00:00:38Z` at 04:17 (`../2026-08-titiler-cache/FINDINGS.md`). **Correction to the original row and to the framing that these were one token:** they are two tokens minted 14 s apart, both expiring ~00:00:4xZ — which is what per-URL caching of per-snapshot items predicts and a single shared token does not. Fix versions the callback URL by the token's expiry. Full report: `../2026-08-titiler-cache/FINDINGS.md`. |
| G7 | **Resolved (`2168124`, 2026-08-12 — deployed in `b2019e4` at 2026-08-12T21:13Z and verified running at a live boundary; see the post-fix scoring at the end of this row).** **No single-flight on a cold container token.** `_container_token` (`stac.py:337-367`) has no in-flight coalescing, so concurrent misses each mint their own token. Measured: 120 band signings on a **warm** token cost 0 PC round-trips; on a **cold** token, 120. A live attempt at the same measurement drew an immediate 429 from `/api/sas/v1/token/landsateuwest/landsat-c2`. Predates `cf0df2b` and is a property of `_container_token`, not of the URL versioning — but the versioning sharpens the simultaneity, since every Landsat key now rotates on the same token boundary. Bounded, not unbounded: `PC_SIGNING_CONCURRENCY` (4) caps in-flight calls and a536d07 retries 429s. Unfixed by choice — bundling a concurrency change into a cache-key fix would make both harder to score. **Observability added (this commit, 2026-08-12):** every mint now logs `SAS container token minted container=<c> se=<ts> ms=<n>` at INFO from `app.services.stac` — one line per PC token call, so concurrent duplicate mints each appear. Counting those lines at a token boundary is the before/after any single-flight fix will be scored against. **Baseline captured 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`):** `BASELINE: 6 minted + 0 exhausted at boundary 2026-08-12T20:17:06Z; worker mints: none; ms range: 670–830`. 18 Landsat keys rotating together produced 6 concurrent mints from one API machine, all returning the identical `se` — the no-single-flight fan-out, confirmed in production rather than in a local harness. **Three refinements to this row's framing:** (1) the boundary is the 20-minute Redis TTL, not the 45-minute token lifetime, so rotations are 2.25× more frequent than the row assumed; (2) the fan-out is per concurrent *band signing*, not per request — one `/stac` callback signing three bands produced 3 mints at 19:56:48–49Z, so a single request is already concurrent with itself; (3) Landsat is not the largest herd — the same cold window produced 13 mints on `sentinel2-l2` and 8 on `naip`, so G7's scope is `_container_token`, not the Landsat path that surfaced it. The 6 is a floor: it was measured at concurrency 6 from one client, and the bound is mint latency (~0.8 s) × arrival rate. Nothing rate-limited at this load (`K` = 0). **The fix (`2168124`, 2026-08-12).** One in-flight `asyncio.Task` per (event loop, container); followers await it shielded so a caller that gives up cannot cancel the mint the others need. Sited inside `_container_token`, below the per-request band gather, because refinement (2) above means a single request is already concurrent with itself — coalescing above the gather would not have caught the 19:56 shape. Per-container, so it covers `sentinel2-l2` and `naip` as well as `landsat-c2`. The `30caec4` log line is unchanged in format and emission point and now fires once per cold miss, which is what makes it the before/after instrument. **Accepted bound: one mint per process per container per boundary, not one globally.** Two API machines can still mint two. A Redis `SET NX` lock would close that at the cost of a poll loop and a Redis-down failure mode on the cold path, to remove a second mint that measured harmless — 13 concurrent mints on `sentinel2-l2` and 8 on `naip` in one cold window drew 0 429s and 0 errors (`K` = 0). The assumption this rests on — that PC's token endpoint tolerates a low-tens-per-boundary mint rate — is recorded as a comment in `_container_token` at the site where anyone would add the lock. It should be revisited if machine count grows well past 2 or if boundary 429s appear. **Refresh-ahead: rejected, not deferred.** See the FINDINGS addendum for the evidence that would reopen it. **Related, separate commit (`e8c857c`, 2026-08-12, deployed in `b2019e4` the same date):** the container-token cache TTL now derives from the token's own `se` less a 300 s margin instead of the fixed `_SAS_CACHE_TTL` (1200 s). Refinement (1) above identified that constant as the rotation cadence; investigating it found it inherited rather than derived (600 s in `9ea33d9` against a believed ~30 min token life, doubled in `3b7b10e` when 45 min was measured) and found no constraint requiring a 25-minute margin — every URL-issue-to-blob-read path is a single request bounded by a 10–30 s client timeout, and the `/stac` `Cache-Control` is already capped at the token's own remaining life. Rotations now fall ~40 min apart rather than ~20, so the herd arrives 2.25× less often. Consequence carried in the same commit: `_STAC_URL_BUCKET_S` drops 600 → 120, since the wall-clock fallback bucket must stay under the life a cached token is guaranteed to have left, and that guarantee is now 300 s. **Scored post-deploy 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`, addendum):** `POST-FIX: 2 minted (1 per machine) + 0 exhausted at boundary 2026-08-12T22:04:12Z; worker mints: none; ms: 238, 657; cadence 40 min 0 s; spike 4.3× one wave, decayed in 113 s`. Three of the four prediction clauses confirmed outright — ≤1 mint per process per container (18 keys rotating together now cost one mint per machine, against 6 from one machine pre-fix; cold-start `sentinel2-l2` 13 → 1 and `naip` 8 → 1), `K` = 0 with 0 429s and 0 non-200 of 308 client requests, and the cadence at exactly 40 min 0 s between consecutive mints under continuous demand. The fourth is a partial deviation, recorded rather than smoothed: the latency spike matched on magnitude (4.3× against a predicted ~4.2×, one wave) but decayed in 113 s against the predicted ~60 s. Attributed to measurement — this run's waves were ~28 s apart against the baseline's ~21 s, and its item cache was colder — and specifically *not* to the fix, since mint count fell 6 → 2 and mint latency 670–830 ms → 238/657 ms, so a mint-dominated spike would have shrunk and did not. The refresh-ahead reopening condition (`K` > 0 or boundary 429s with both fixes deployed) did not appear, so refresh-ahead stays rejected. Not exercised by this run: the post-fix *boundary* for `sentinel2-l2` and `naip` — both keys died inside the capture but no request arrived to trigger a mint, so their 13 → 1 and 8 → 1 figures are cold-start, not boundary. |
| G6 | **An ArcGIS query hit its row cap** (DC property layer, cap 20, 03:48:33Z). This is the evidence the counties reconciliation's item 13 said it was waiting for; pagination is no longer building against an unconfirmed hypothesis. |

## Topo/NAIP coverage review (2026-08-13)

A review of what the imagery paths can and cannot know about their own
coverage. Not an audit of running production and not a second-audit finding —
tracked here for the same reason the ops and geometry sections are: one of its
items changes the M4 row, and this file is where fix commits get cited.

| # | Item |
|---|---|
| T1 | **Topo survey dates do not exist in any reachable structured source. Negative result — recorded so nobody spends a day hunting for the API parameter.** A topo sheet's *publication* year is not the year its content depicts; a quad published in 1965 can carry a survey a decade older, and photorevision adds a third date. Every date we can obtain is the publication one: the TNM `/products` response carries `publicationDate` and nothing else date-bearing, and the FGDC XML reachable via a product's `vendorMetaUrl` tags its date range `<current>publication date</current>` — i.e. the metadata explicitly declares its own dates to be publication dates. Survey and photorevision dates are printed in the **map collar** — the marginalia of the scanned sheet itself — so recovering them means OCR over the collar, per sheet, with per-series layout variation. That is the whole cost of the feature, and it is why the honest remedy was presentational. **Remedy shipped (`94443cf`, 2026-08-13):** topo cards render "Published 1965" rather than the capture-date format "Jan 1965", and the three surfaces that show a topo date carry a one-sentence caveat (`TOPO_DATE_CAVEAT` in `frontend/src/constants.ts`) saying publication is not survey. No migration and no schema change — `capture_date` still holds Jan 1 of the publication year; the fix is that the UI stops asserting a precision the column never had. **Provenance caveat on this row:** the TNM-and-FGDC negative result is carried over from the coverage review that commissioned this batch and was **not** re-verified against a live TNM response or a live `vendorMetaUrl` fetch in the batch that wrote this row. The remedy does not depend on it; a future reader who wants to reopen the question should re-check those two responses first. |
| T2 | **The 1900 fallback. Resolved (`c82ed51`, 2026-08-13).** `extract_publication_date` was `year = _publication_year(item) or 1900`, so a product whose `publicationDate` would not parse was persisted as `1900-01-01` and rendered as a genuine 1900 sheet — a fabricated date, indistinguishable from a real one, in the column the timeline sorts on. It now returns `None` and the persistence loop skips the product with a warning, matching the `sourceId` skip added a few lines below it in ffb71b2. The task still reports `complete`: one dropped sheet is a gap, not a failure, and "complete with zero" and "failed" stay distinct states. **The fallback was latent, not live** — `select_topo_items` (`usgs_topo.py:113-117`) already drops items whose year will not parse, so nothing reached `extract_publication_date` with a bad date, and no existing row can carry a fabricated 1900. It was a landmine under any future caller, and the guard now sits in the loop where such a caller would land. Grep for the shape found no other `or <literal year>` / `or <sentinel date>` fallback in the backend; the one near-miss, `str(i.get("publicationDate", "9999"))` at `usgs_topo.py:126`, is a sort-key default that is never persisted. |
| T3 | **The topo cap was unverified and silent. Mitigated (`c82ed51`, 2026-08-13); pagination deliberately not built.** `search_usgs_topo` issues one un-paginated TNM query with `max=100`, and TNM documents no ordering guarantee — so a response holding exactly 100 products was indistinguishable from a complete answer, and a truncated pool would drop whole decades (`select_topo_items` picks one sheet per decade from whatever it is given). Pagination is **not** the remedy, for the reason counties item 13 gave: it would be built against an overflow hypothesis nothing has confirmed — the L6 accept records that no one has verified a real quad exceeds 100 products, and that is still true. The accepted instrument is the same one instead: the client now logs `TNM query hit its row cap — results are truncated` with the resource and the cap, in the message shape the ArcGIS/CKAN/Socrata clients gained in ae5793a, so all four grep together. That instrument has already paid once — G6 is the DC ArcGIS cap-hit that turned item 13's hypothesis into evidence — and this is the same bet on the same terms: if the line appears in production, that is when pagination gets built. The check counts raw products before the GeoTIFF filter, because truncation happens upstream of that filter. |
| T4 | **NAIP early-year truncation — OPEN HYPOTHESIS, not supported by the evidence available locally. No code change.** The claim under test: NAIP is the only imagery source not chunked by year — one search over 2003→present with `max_items=50` — and result ordering causes early years to fall off the pool on dense-coverage parcels, indistinguishable from a real flight gap. **Both mechanism premises are confirmed in code.** NAIP is un-chunked: `"chunk_by_year": False` (`timeline.py:54`) sends it down the single-search branch at `timeline.py:260-271`, one query over `2003-01-01/<current year>-12-31` with `max_items=50` (`:49`); Landsat (`:66`, from 1984) and Sentinel-2 (`:78`, from 2015) take the year-chunk loop at `:224-259` at 20 items per year. And the pool really is one page: `search_stac` sets `limit = min(max_items, 100)` = 50 and only follows a `next` link while `len(items) < max_items` (`stac.py:132,145`), so a first page of 50 ends the walk — NAIP never paginates in practice. **The ordering premise is a separate finding, and it is worse than the hypothesis states.** `search_stac`'s payload (`stac.py:128-133`) carries `collections`, `bbox`, `datetime`, `limit` and an optional `query` — **no `sortby`**. STAC leaves unsorted ordering unspecified, so which 50 items survive the cap is not a property we control or have observed; it is not "newest first". The comment at `timeline.py:222` asserting a "default 'newest first' ordering" as the *reason* for chunking is an unverified claim in the code, and it should be read as motivation rather than fact. **Local measurement (41 parcels, 298 NAIP rows, read-only) does not support the hypothesis and inverts its predicted signature.** The prediction is early years absent on parcels with many NAIP rows and present on sparse ones. Observed: no parcel holds a single row before **2010**, the fleet-wide year histogram starts at 2010 (5 parcels) and 2011 (32), and 2003–2009 is empty everywhere — across CO, NY, DC, CA, NC, NV, UT, ID, IL, PA and OH. Grouped by pool size, parcels with 5 rows and parcels with 10 rows alike hold **zero** 2003–2010 rows, while the only two parcels holding any sit at 9 and 11 rows; the parcels reaching furthest back (both 350 5th Ave parcels, Hudson Yards, Philadelphia — 2010) are the *densest*, not the sparsest. A cap that ate early years would have eaten theirs first. The pattern that is present — CA parcels starting 2012, UT 2011, CO 2011 — has the shape of state NAIP flight cycles and of the collection's own start, not of a per-parcel cutoff. **Verdict: refuted on the correlation it predicts; the underlying truncation *risk* is confirmed as real and remains unmeasured.** What the local DB cannot see is the raw returned pool — we persist one row per selected year, never the search's item count — so no local query can say whether any parcel's search returned exactly 50. That is the gap; the SQL below cannot close it, and the honest instrument would be the T3 treatment applied to `search_stac` (warn when a search returns exactly its cap). Not built here — this task was investigate-only. **The 350 5th Ave 2023 case is NOT evidence for this hypothesis.** It was investigated and closed as genuine data absence: PC returns exactly 3 items for that bbox and year, all New Jersey quads, none containing the point (`../2026-08-geometry-audit/FINDINGS.md` §4, and R4, which records the truncation hypothesis it was tested against and rejected). Citing it as truncation evidence inverts the record. The same parcel holds 2010 and 2013 NAIP rows (Appendix D of that report), which is a second point against. **Read-only SQL for production, to be run by Ryan — not run from here:** `SELECT naip_rows, count(*) AS parcels, round(avg(early_rows),2) AS avg_2003_2010, count(*) FILTER (WHERE early_rows = 0) AS parcels_with_no_early FROM (SELECT parcel_id, count(*) AS naip_rows, count(*) FILTER (WHERE extract(year FROM capture_date) BETWEEN 2003 AND 2010) AS early_rows FROM imagery_snapshots WHERE source='naip' GROUP BY 1) t GROUP BY 1 ORDER BY 1;` and `SELECT extract(year FROM capture_date)::int AS yr, count(*) AS rows, count(DISTINCT parcel_id) AS parcels FROM imagery_snapshots WHERE source='naip' GROUP BY 1 ORDER BY 1;` — production has 57 parcels against the local 41, so it is the larger sample, but it is the same measurement and inherits the same blind spot. |
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
| N1 | **MEDIUM — Open** | **SAS signing retries only 429; a transient PC 5xx or connection error is terminal.** `_sas_get` branches on `resp.status_code != 429` and calls `raise_for_status()` on the spot (`stac.py:311-312`), and `httpx.RequestError` is never caught inside the loop at all — so a 503 from `/api/sas/v1/token/…`, or a reset connection, fails on the **first** attempt, with none of the 4 attempts, the semaphore, or the wait budget applying. The function's own docstring argues that a 429 means "slow down", not "this asset is broken" (`stac.py:293-295`); the same is true of a 503, and the code does not act on it. **The worker path is where it costs a year.** `_validate_asset` catches the raised error and returns `False` (`stac.py:1010-1017`); `_validate_selection` reads that as "item is broken" and answers by walking **every** same-period candidate (`stac.py:1107-1123`) — each of which signs against the same unhealthy endpoint — then drops the period with `WARNING "No valid %s item for %s; skipping"` (`stac.py:1126`) under a task that still ends `complete` (`timeline.py:435`). Note the asymmetry with the search path, which does retry `{429, 500, 502, 503, 504}` **and** `RequestError` (`timeline.py:94, 125-130`). Recorded against M4 above as a fourth silent-gap door, not a fourth occurrence. |
| N2 | **MEDIUM — Open** | **The Census data API client has no retry at all.** `CensusFetcher._request` issues one `GET` and converts any `httpx.HTTPError` — timeout, connect error, read error — straight into `CensusApiError` (`census.py:249-253`). No attempt loop, no backoff, no distinction between a retryable and a permanent failure. The only pacing anywhere on the path is `await asyncio.sleep(0.5)` between years (`timeline.py:689, 715`), which is politeness, not retry. **This is the mechanism behind M4's instance (3):** four `httpx.ReadTimeout`s against `api.census.gov` cost a Maricopa parcel its acs5 2021 and decennial 2020 rows, and **not one of those four would have been retried**. M4 recorded the outcome; nothing on this ledger recorded that the client never tried again. Both the geocoder (`geocoder.py:30, 139-147`) and the STAC search (`timeline.py:97-135`) retry — among our three upstream clients this one is the outlier. |
| N3 | **LOW (record drift) — corrected in this commit** | **The M9 row above stated the `/warmup` limit as 30/min; it has been 60/min since `69b94e1` (2026-08-04).** 56d6647 did ship 30 — `RateLimit(times=30, seconds=60)` at that commit — and `69b94e1` ("perf: warm a snapshot once per session, not once per scrub hop") raised it to 60 without the row following; `api/imagery.py:624` reads `RateLimit(times=60, seconds=60)` at HEAD. The `/{id}/stac` half (600/min) is still accurate (`api/imagery.py:721`). The M9 row is corrected in place in the same commit as this row. It is recorded rather than silently fixed because the drift, not the number, is the finding: the row was true when written and nothing made it false out loud. |
| N4 | **LOW — Open** | **A Photon failure returns an empty suggestion list.** Both `httpx.RequestError` and `httpx.HTTPStatusError` are answered with `return []` (`api/geocode.py:77-82`), so a Photon outage, a 429, and "no US address matches this prefix" reach the caller — and the user — as the same empty dropdown. It is the complete-with-zero shape the second audit named as this system's characteristic reflex, on the one path where **nothing is persisted**: unlike census or property, no backfill, heal or query could ever notice. Contained, which is why it is LOW and not MEDIUM — a typed address still geocodes through the Census geocoder, and the 300 s cache does not store empty-on-failure any differently from empty-on-success. |
| N5 | **LOW (second-order) — Open** | **The host allowlist guards one of the five paths that hand a stored URL to a fetcher.** `_ALLOWED_STAC_HOSTS` (`api/imagery.py:336-340`) constrains the API's own Landsat item fetch, and the comment above it gives the reason: without it "a `cog_url` written by a compromised upstream would make the API fetch an attacker-chosen URL from inside the network" (`api/imagery.py:330-335`). The same stored values also reach Titiler as the `url` query parameter on four other paths — `_proxy_cog_tile` (`api/imagery.py:484-486`), warmup (`api/imagery.py:646-648, 665-668`), the Landsat callback URL (`api/imagery.py:556-557`) and the preview renderer (`preview_renderer.py:113-116`) — with **no host check on any of them**, for NAIP, Sentinel-2 and USGS topo alike. Topo is the widest case: that URL comes straight out of TNM's `urls.GeoTIFF` and is never inspected (`usgs_topo.py:134-140`). The exposure is the same second-order shape the existing comment already reasons about — it needs a compromised or malicious upstream, and the value is written by our own worker — but the mitigation landed on one path and not the other four. `CPL_VSIL_CURL_ALLOWED_EXTENSIONS = '.tif,.tiff'` (`fly.titiler.toml:19`) narrows what GDAL will open; it does not constrain the host. |

## Accepted, with reasons

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
- **M9, authenticating the Titiler callback.** The rate limits in 56d6647 are
  an interim mitigation, and the batch that added them established that a
  counter is the wrong instrument here: every legitimate call to `/stac`
  arrives from Titiler's single egress IP, so a per-IP limit is one shared
  bucket for all users rather than a per-visitor budget, and 600/min is set
  loose enough not to throttle real tile serving. Properly distinguishing
  Titiler from the public needs a shared secret or a signed callback. The
  routing half stays accepted regardless — this is about who may call the
  endpoint, not where the traffic goes.
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
- **M7, M8, M5 (autocomplete half), L1, L3, L8, L10 hygiene, L12
  Dockerfile.** Real, and larger than a one-liner or touching shared surface.
  See the second audit's triage for the design decision each one turns on.

## Scheduled

- **M4, per-year failure persistence.** No longer deferred design — it is the
  next piece of real work. Three production instances from three independent
  upstreams (see the M4 row) have now produced the same permanent gap under a
  `complete` task, and the response to each has been a hand-written heal
  script. The recurring chore is the argument: `revalidate_landsat.py`,
  `requeue_empty_property.py`, `heal_tract_vintage_gaps.py` and now
  `requeue_parcels.py` all exist because a task cannot say which years it
  failed to fetch. The open design question is where per-year outcomes live —
  a column on `timeline_request_tasks`, or a per-year row — and it should be
  answered against what backfill needs to read, not what is cheapest to write.

## To investigate

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
- **Incidental, from the same finding:** the 2026-08-11 incident parcel
  recorded `property complete:0` during the burst window while its five Denver
  peers hold 10–33 events each. Suggestive, not conclusive.

## Notes for future readers

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
  (`_SAS_CACHE_TTL`, `stac.py:179`). (2) `sas:{url}` is no longer the sole key
  and no longer the blob path's key at all — blob hrefs sign with a
  container-scoped token cached under `sas-token:{account}/{container}` on a
  TTL derived from the token's own `se` (`stac.py:446, 487-504, 543-546`), and
  **four** other key families share the instance: `stac:{snapshot_id}` (3600 s,
  `api/imagery.py:739, 768`), `autocomplete:{q}` (300 s, `api/geocode.py:34,
  52, 147-151`), `ratelimit:{path}:{ip}` (`rate_limit.py:59, 67-70`), and
  Redis's separate role as the Celery broker and result backend
  (`celery_app.py:37-42`). (3) The unsigned-URL fallback is gone from every
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
