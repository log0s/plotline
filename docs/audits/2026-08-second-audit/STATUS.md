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
| M4 Partial census/Landsat failures | Open | `timeline.py:234-259`, `:588-658` (the census year loop moved into `_fetch_census_years` in b5a306a) — failures counted, never persisted, so nothing can target the gaps. Sharper than the finding states on the census half: a year the API has no data for returns `{}` and is skipped by `if data:` (`:598` decennial, `:625` ACS5) **without** incrementing `failed_requests` (`:612`, `:639`), so the all-failed check at `:651` cannot see it either. The gap is not merely unpersisted — it is invisible to the task's own failure arithmetic, which is why a parcel could sit at `complete` with four of six ACS years missing. One instance of that shape — years lost to the 2020 tract redistricting — is healed by b5a306a and its `scripts/heal_tract_vintage_gaps.py`; the general problem of persisting per-year failures is untouched. **Observed in production three times, from three independent upstreams.** (1) 2026-08-11: a burst of 21 SAS signing 429s in four seconds cost one parcel 20 of its 43 Landsat years. (2) 2026-08-12 00:45Z: a second parcel (Ocean County NJ) lost 8 Landsat years — after the incident, and **on production that did not have a536d07**. The throttle was committed 2026-08-11 and left unpushed; CI deploys on push, so the running release was still pre-throttle when those years were lost. Whatever else a536d07 does, it demonstrably did not prevent this: the loss is post-commit and pre-deploy, and no signing-throttle event appears in any log buffer. (3) 2026-08-12 01:25Z: four `httpx.ReadTimeout`s against `api.census.gov` cost a Maricopa parcel its acs5 2021 and decennial 2020 rows — the Census API, not our signing, so no throttle could have helped. Each of the three ended `complete`, and backfill only triggers on failed/missing tasks, so none of them has a healing path. **This row is not "mitigated".** Capping our own call rate narrows one of three doors; a year lost to a Census timeout, a TNM endpoint returning non-JSON (see the zero-topo parcel in the ops audit's §8), or any upstream we have not met yet is still silently dropped under a `complete` task. M4's per-year failure persistence is the actual fix, and it is now scheduled work rather than deferred design — see below. Evidence: `docs/audits/2026-08-ops-audit/FINDINGS.md` §0, HIGH-2, MEDIUM-2. **(4) 2026-08-12, from the geometry sweep: one parcel — `2f1b332e`, Racebrook Road, Orange, Connecticut — still holds only 5 census years (decennial 2010; acs5 2012, 2015, 2018, 2023) against 7–9 for its peers, *after* a full re-run. It is the sharpest instance yet, because nothing in the system can say whether those years re-failed or were never published: the task ended `complete`, no failure was recorded, and the 63 `Census API: no data for tract` 404s observed during the sweep are indistinguishable from genuine absence. Connecticut's 2022 county-to-planning-region change makes genuine absence entirely plausible — which is the point. Telling the two apart is exactly what per-year persistence would buy, and no heal script can be written until it can. Only 3 census rows across 2 parcels were gained sweep-wide, so the opportunistic ride-along did not reach it.** Evidence: `docs/audits/2026-08-geometry-audit/HEAL-SCORECARD.md` §6. *A later commentary restated that ride-along as a net **loss** of 3 rows across 44 parcels; it is a phantom, closed in `docs/audits/2026-08-geometry-audit/CENSUS_TRIAGE.md` — `census_snapshots` has no deletion path, so no census loss is reachable and no new M4 occurrence follows from it. (4) above remains the only occurrence from the sweep.* |
| M5 Sync I/O on the loop | Open | `geocode.py:55-57,146-151`; `timeline.py:310-360`. The worker half is accepted; the autocomplete half is not. |
| M6 Redis socket timeouts | Resolved (dd99cee) | `socket_timeout` and `socket_connect_timeout` of 2s on both clients, matching the DB probe's `statement_timeout`. |
| M7 ORM/schema drift | Open | Partial indexes in `0009:49`, `0010:67,83` absent from `models/parcels.py`; `conftest.py:55-190` still hand-written DDL. |
| M8 DO NOTHING freezes records | Open | `property_events.py:74`; `county_adapters.py:466,734`. |
| M9 Titiler callback path | Partially resolved (56d6647) | `/warmup` (30/min) and `/{id}/stac` (600/min) now carry rate limits. The routing itself is accepted — see below. |
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
| L6 TNM caps and ids | Partially resolved (ffb71b2) | Products with no `sourceId` are skipped instead of colliding on `stac_item_id=""`. Pagination accepted — see below. |
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
| G1 | **NAIP suppression is prospective-only.** 14b59af removes an uncovered year from the selection; `reconcile_source_snapshots` deliberately never deletes an *absent* group, because absence usually means a failed search. The two rules compose into a hole: the gate cannot clear a wrong card that already exists, which is every parcel the audit identified. Both 350 5th Ave 2023 cards still serve `nj_m_4007309_sw`. |
| G2 | **Rodanthe sentinel2 2015 Q3 unhealed.** Still the 25.04 % non-covering granule from Appendix A. Its 1.01 % covering sibling sits in Q4, a different quarter group, so the quarter-scoped selector never had to choose. 1 of the 15 featured cards remains wrong. |
| G3 | **One duplicate S2 quarter group.** Green Valley Ranch holds two 2026-Q1 rows, created 2026-06-12 and -06-17 — *before* this sweep and not caused by it. 2026-Q1 was not in the run's selection, so the absent-group rule left it alone; re-running cannot clear it. |
| G4 | **Signing storm on the request path during the sweep.** 41 × `SAS rate-limited; backoff exceeds wait budget, giving up`, 17 × `Band signing failed after retries`, 115 Titiler 500s across 5 snapshots. This is O1's act-two mismatch running the other way: the batch path exhausts PC's limit while the request path's 2 s `SIGN_WAIT_REQUEST` gives up at once. A user browsing during a sweep gets 500s. **Attribution now in question:** G5's mechanism produces an identical 500 with no signing failure preceding it, so an unknown share of the 115 is cache-pinned tokens rather than rate limiting. The two are separable in the logs — a G5 500 carries an `se` earlier than its own request time and has no `Band signing failed` line seconds before it on the same snapshot id. Testable post-deploy: whatever survives `cf0df2b` is genuinely G4. **Still untested as of 2026-08-12T20:49Z.** The post-deploy observation (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`) saw 0 Titiler 500s and 0 backoff-exhaustion lines, but no heal sweep was running during it — G4's premise is a batch path exhausting PC's limit *concurrently with* browsing, and that condition never obtained. The clean reading bears on G5/O8 only; G4's share of the 115 remains unmeasured and needs a browse observed during an actual sweep. |
| G5 | **Resolved (`cf0df2b`, 2026-08-12 — deployed 19:53Z, scored clean; see O8 and `../2026-08-titiler-cache/BOUNDARY-BASELINE.md`).** **Cause identified: Titiler's rio-tiler item LRU pinning a SAS token under the constant `/imagery/{id}/stac` URL.** `rio_tiler/io/stac.py:100-102` caches fetched items in a module-level `LRUCache(maxsize=512)` with **no TTL**, keyed on the URL — and Landsat's callback URL was constant per snapshot forever, so the token frozen in the item's band hrefs outlived its 45-minute expiry until eviction or restart. Two independent captures of the shape: `se=2026-08-12T00:00:52Z` at 03:34 (`../2026-08-geometry-audit/HEAL-SCORECARD.md` §4.5) and `se=2026-08-12T00:00:38Z` at 04:17 (`../2026-08-titiler-cache/FINDINGS.md`). **Correction to the original row and to the framing that these were one token:** they are two tokens minted 14 s apart, both expiring ~00:00:4xZ — which is what per-URL caching of per-snapshot items predicts and a single shared token does not. Fix versions the callback URL by the token's expiry. Full report: `../2026-08-titiler-cache/FINDINGS.md`. |
| G7 | **No single-flight on a cold container token.** `_container_token` (`stac.py:337-367`) has no in-flight coalescing, so concurrent misses each mint their own token. Measured: 120 band signings on a **warm** token cost 0 PC round-trips; on a **cold** token, 120. A live attempt at the same measurement drew an immediate 429 from `/api/sas/v1/token/landsateuwest/landsat-c2`. Predates `cf0df2b` and is a property of `_container_token`, not of the URL versioning — but the versioning sharpens the simultaneity, since every Landsat key now rotates on the same token boundary. Bounded, not unbounded: `PC_SIGNING_CONCURRENCY` (4) caps in-flight calls and a536d07 retries 429s. Unfixed by choice — bundling a concurrency change into a cache-key fix would make both harder to score. **Observability added (this commit, 2026-08-12):** every mint now logs `SAS container token minted container=<c> se=<ts> ms=<n>` at INFO from `app.services.stac` — one line per PC token call, so concurrent duplicate mints each appear. Counting those lines at a token boundary is the before/after any single-flight fix will be scored against. **Baseline captured 2026-08-12 (`../2026-08-titiler-cache/BOUNDARY-BASELINE.md`):** `BASELINE: 6 minted + 0 exhausted at boundary 2026-08-12T20:17:06Z; worker mints: none; ms range: 670–830`. 18 Landsat keys rotating together produced 6 concurrent mints from one API machine, all returning the identical `se` — the no-single-flight fan-out, confirmed in production rather than in a local harness. **Three refinements to this row's framing:** (1) the boundary is the 20-minute Redis TTL, not the 45-minute token lifetime, so rotations are 2.25× more frequent than the row assumed; (2) the fan-out is per concurrent *band signing*, not per request — one `/stac` callback signing three bands produced 3 mints at 19:56:48–49Z, so a single request is already concurrent with itself; (3) Landsat is not the largest herd — the same cold window produced 13 mints on `sentinel2-l2` and 8 on `naip`, so G7's scope is `_container_token`, not the Landsat path that surfaced it. The 6 is a floor: it was measured at concurrency 6 from one client, and the bound is mint latency (~0.8 s) × arrival rate. Nothing rate-limited at this load (`K` = 0). |
| G6 | **An ArcGIS query hit its row cap** (DC property layer, cap 20, 03:48:33Z). This is the evidence the counties reconciliation's item 13 said it was waiting for; pagination is no longer building against an unconfirmed hypothesis. |

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
  100 products. Not building against an unverified premise.
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
