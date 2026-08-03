# Second Architecture Audit — Findings

*Run 2026-07/08 (Claude Fable 5, plan mode) against approximately 5f5fb42
(2026-07-29). Reconstructed from the reported results; this document sustained
transmission damage in places — unrecoverable passages are marked
[passage lost in transcription]. Finding IDs, severities, and file:line
citations survived; some explanatory prose did not.*

*Some open security-relevant findings are summarized rather than detailed.*

---

**Reviewer's summary:** Nothing rose to Critical (no data-corruption, injection, or auth-bypass path survived scrutiny — the parameterized SQL, the quote-escaping in the SoQL/ArcGIS builders, and the one-inflight partial index all held up). The top tier is High: several user-facing features are silently broken or silently degraded in ways nothing in the codebase would ever tell you about.

## High

### H1. The Housing chart can never render — the two datasets never produce the field combination it requires

**Resolved:** 6def10c, 2026-08-03 (test fixtures: 1c1c069, 2026-08-03)

backend/app/services/census.py:26-68, frontend/src/components/demographics/HousingChart.tsx:28-33, backend/app/services/demographics.py:59-63

Scenario: ACS5 fetches B25003_001E (occupied units) but never B25001_001E (total housing units) — _ACS5_VARIABLES has no total-units variable. Decennial fetches only P1_001N/H1_001N (population + total units) — no occupied/owner/renter. So every census_snapshots row has either total_housing_units or the occupancy splits, never both. HousingChart filters on s.total_housing_units != null && (owner != null || renter != null) — an impossible combination — so data is always empty and the component returns null for every parcel in production. The same missing pairing means vacancy_rate in upsert_census_snapshot (needs total_housing and occupied) is always NULL — a dead column with a dead computation.

Why no one noticed: tests/test_census.py:360-376 asserts vacancy_rate ≈ 0.0597 by passing data={"occupied_housing_units": 1764, "total_housing_units": 1876} — hand-built input the real pipeline can never produce. The test proves the formula, not the system.

Fix: Add "B25001_001E": "total_housing_units" (and optionally B25002_003E for vacant) to _ACS5_VARIABLES; add a test that runs fetch_acs5 → upsert → HousingChart-shaped assertions on the actual variable set. Existing rows need a backfill (the census upsert does refresh on conflict, so a re-run heals them).

### H2. All structured log context is silently discarded — in the API and the worker

**Resolved:** 90ea416, 2026-08-03

backend/app/logging_config.py:23-49, backend/app/tasks/celery_app.py (no logging hookup at all)

Scenario: Every module logs via stdlib logging.getLogger(__name__) with extra={"parcel_id": ..., "source": ..., "error": ...}. Those are "foreign" records to structlog, and ProcessorFormatter's foreign_pre_chain (line 48) does not include structlog.stdlib.ExtraAdder() — without it, extra attributes are dropped from the rendered event. Your production JSON log for "STAC year chunk failed" contains the message and nothing else: no source, no year, no error. Worse: the Celery worker — where the entire pipeline runs — never calls configure_logging() at all, so it doesn't even get JSON output; it uses Celery's default formatter. [passage partially lost in transcription — the surviving fragment reads: "…is meticulously instrumented and none of the instrumentation reaches the logs."] CLAUDE.md's own standard ("Log geocoder calls, DB writes, job status changes") is technically met and practically void.

Fix: Add structlog.stdlib.ExtraAdder() to shared_processors, and wire the worker via Celery's setup_logging signal calling configure_logging(get_settings()). Verify with one grep of actual prod output.

### H3. Demographics responses are browser-cached for 1 hour, hiding exactly the late-arriving data the backfill system exists to deliver

**Resolved:** 90ea416, 2026-08-03

backend/app/api/v1/demographics.py:34

Scenario: (1) User geocodes a parcel during a Census API outage → census task failed, request complete. (2) [reconstructed from fragments] The frontend fetches /demographics → empty snapshot list, response carries Cache-Control: public, max-age=3600. (3) User reloads; ExplorePage's auto-trigger (ExplorePage.tsx:71-87) fires backfill, census now succeeds, rows land in the DB a minute later. (4) Every reload for the next hour re-serves the cached empty response from the browser's HTTP cache — the panel shows "No census or property data available yet" while the data sits in Postgres. This exact class was already fixed for imagery (commit message "prevent browser cache from hiding late-arriving imagery" added no-cache to list_imagery); demographics never got the same treatment. [fragment lost in transcription]

Fix: no-cache (or short max-age) on demographics, matching imagery. If you want cacheability, key it on data version (ETag from max created_at).

### H4. A total county-portal outage is recorded as property: complete — indistinguishable from "no records", and never retried

**Resolved:** 256ed32, 2026-08-03 (follow-ups: b98a851 re-queue script, f1ffae3 decode wrap, both 2026-08-03)

backend/app/services/county_adapters.py:176, 266, 358, 409, 505, 618, 678; backend/app/tasks/timeline.py:659-682

Scenario: Denver's ArcGIS service is down. Both _query closures catch Exception, log a warning, and return []. _fetch_and_persist_property sees zero events, saves nothing, and marks the task complete with whatever count exists (0). The frontend renders "no property history" as authoritative truth. And because maybe_refetch_for_backfill (imagery.py:333) only refetches property tasks that are missing or skipped — not complete — this parcel never fetches property data again. You already fixed this exact failure shape for census (timeline.py:536-545: "Every single request erroring is an outage, not 'tract has no data'"); the property path has the identical hole. It also violates your own repo standard ("Don't catch bare Exception — catch specific exceptions") seven times over in this one file.

Fix: Catch the specific client errors (ArcGISError, SocrataError, CKANError, httpx errors) and return a sentinel or re-raise so the caller can distinguish "all queries errored" (→ failed) from "queries ran, zero rows".

### H5. The fuzzy address matcher rejects legitimate records whenever the county spells directionals or ordinals differently

**Resolved:** add8102, 2026-08-03

backend/app/services/address_normalizer.py:36, 91-111

Scenario: Parcel normalized address from the Census geocoder: 245 E 17TH ST. NYC DOB permit street_name: EAST 17 STREET (DOB conventionally spells out directionals and drops ordinals). After normalize_address: {E, 17TH, ST} vs {EAST, 17, ST} → overlap = 1/3 = 0.33 < 0.7 → every permit for the building is silently discarded, and the task still reports complete. Even the milder case — [reconstructed] {E, MAIN, ST} vs {EAST, MAIN, ST} scoring 0.67 — falls below the 0.7 threshold, so any county that spells out directionals loses all its records. The DIRECTIONALS set at line 36 exists but is only used to skip a token in extract_search_terms — it's never used to normalize, which is the actual need. The docstring even celebrates that N vs S scores 0.67 — the same score an identical street gets for a spelling variant. There is no test file for this module at all, the highest-leverage pure-logic module in the property pipeline.

Fix: In normalize_address, map spelled-out directionals to abbreviations (EAST→E etc.) and strip ordinal suffixes (17TH→17). Then add the table-driven test file this module should always have had (real DOB/Denver/DC address formats as cases).

### H6. Landsat re-validation accretes duplicate years instead of replacing broken scenes — the maintenance script's premise is false

**Resolved:** 96a7962, 2026-08-03

backend/app/services/imagery.py:426 (conflict target), backend/app/models/parcels.py:272-276, scripts/revalidate_landsat.py:4-7, 55-63

Scenario: Run 1 selects Landsat scene LT05_…_A for 1987; it later breaks on Planetary Computer. You run revalidate_landsat.py, whose docstring claims the pipeline "will replace broken snapshots … via upsert_imagery_snapshot." The re-run's validation picks fallback scene LT05_…_B — a different stac_item_id — so the upsert (conflict target (parcel_id, stac_item_id)) inserts a new row and leaves the broken one in place. The timeline now shows two 1987 Landsat cards, one of which 502s on every tile. Nothing constrains one snapshot per (parcel, source, year), which is the selection algorithm's actual invariant. Separately, the script inserts TimelineRequest(status="queued") directly (revalidate_landsat.py:57) — if any parcel has an in-flight request (including one the script itself just queued on a previous run), the partial unique index uq_timeline_requests_parcel_inflight [reconstructed: raises an integrity error] and the script dies mid-batch.

Fix: After a source completes, delete rows for that (parcel_id, source) whose stac_item_id isn't in the fresh selection (mosaic-aware). In the script, reuse get_or_create_timeline_request per parcel.

## Medium

### M1. Census geocoder's known 200-with-HTML failure mode produces a raw 500

backend/app/services/geocoder.py:111, 117-118, backend/app/api/v1/geocode.py (handler catches only GeocoderError subclasses)

Scenario: The Census geocoder returns its maintenance page with HTTP 200 (a behavior your own census.py:207 comment documents and guards against — "The Census API sometimes returns its HTML error page with a 200"). response.json() at geocoder.py:111 raises JSONDecodeError, which is not a GeocoderError, escapes the route's except clauses, and surfaces as an unhandled 500 — violating your own "Geocoder down? Return a clear 502" standard. [reconstructed] coords["coordinates"] / coords["y"] are similarly unguarded KeyErrors. Also note the retry loop retries only timeouts; a transient 503 fails immediately (defensible, but undocumented asymmetry).

Fix: Wrap parse + field extraction; raise GeocoderUnavailableError on decode/shape failure, mirroring census.py's guard.

### M2. Rate limiting is bypassable and can permanently lock out an IP

M2 (rate limiting): client-identification and counter-atomicity weaknesses identified in `backend/app/api/rate_limit.py`; details withheld pending fix.

### M3. Backfilling one missing source re-runs the entire five-source pipeline, on every visit, forever

backend/app/services/imagery.py [line partially lost], frontend/src/pages/ExplorePage.tsx:71-87

Scenario: A tract where one census vintage persistently errors (or a parcel whose census task failed and keeps failing — e.g. Census retired the 2009 ACS endpoint). Every page view POSTs /timeline → maybe_refetch_for_backfill sees census_task.status == "failed" → dispatches a full pipeline: ~43 Landsat year-chunk STAC searches with retries, Landsat HEAD-validation, NAIP, Sentinel-2, TNM, the county portals — 30+ upstream calls and several minutes of worker time to re-attempt one source. Each cycle also inserts a new TimelineRequest row (unbounded growth per parcel; old rows are never pruned). It's visit-driven rather than an infinite loop (the earlier loop bug you fixed), but a popular parcel with one stuck source is a standing cost amplifier.

Fix: Persist per-source scope on the request (e.g. a sources column) and have _run_timeline fetch only the missing/failed sources on backfill; add a retry ceiling or cooldown (e.g. don't backfill if the last attempt was < N hours ago).

### M4. Partial per-year census failures are counted as complete and are permanently unrecoverable

backend/app/tasks/timeline.py:225-253, 500-545

Scenario: 3 of 10 census year-requests fail with transient 500s. failed_requests != total so the task is marked complete; the missing years are gaps in the charts forever, because backfill only triggers on failed/missing tasks (M3's logic). Same for Landsat: a year-chunk that exhausts retries is logged and skipped ("a gap, not a wipeout"), then complete. The design comment acknowledges the tradeoff for Landsat, but there is no path that ever heals these gaps, and the UI presents the result identically to genuinely-absent data.

Fix: Record which years failed (e.g. in error_message or a JSON column) and let backfill target them; or mark the task failed above a failure-fraction threshold.

### M5. Sync blocking I/O on the event loop — in the API's hottest autocomplete path and inside the worker's gather

backend/app/api/v1/geocode.py:56, 147; backend/app/tasks/timeline.py:308-351, 488-523

Scenario 1: autocomplete is async def but calls the sync Redis client (get_redis().get/set) directly — every keystroke-triggered request blocks the API's event loop for a Redis round-trip; with no socket_timeout configured (see M6) a stalled Redis freezes the whole API process, not just autocomplete. The same file carefully wraps DB work in run_in_threadpool — the inconsistency suggests it's an oversight. [reconstructed] Scenario 2: In the worker, _search_and_persist_source runs sync DB work (upsert + commit per group, ~30 commits) synchronously inside the async task, stalling the concurrent census/property/topo coroutines during every persist phase; _set_task_status adds more sync round-trips. Doesn't deadlock, but the "run all sources concurrently" design is partially defeated.

Fix: [reconstructed] get_async_redis() in autocomplete; asyncio.to_thread (or batch the commits) for the worker's persist phase.

### M6. No Redis socket timeouts anywhere — a half-dead Redis hangs health checks, rate limiting, and SAS signing

backend/app/db.py:89, 101

Scenario: Redis's TCP connection is established but the server stops responding (VM stall, network partition mid-connection). check_redis_connection()'s ping() blocks indefinitely → /health hangs → the load balancer's picture of the instance is wrong in whichever direction its timeout defaults to. Every rate-limit check and SAS-cache read awaits forever (the except (RedisError, OSError) fail-open never fires). You gave the DB probe a 2-second statement_timeout for precisely this reason (db.py:44-53) — Redis got no equivalent.

Fix: from_url(..., socket_timeout=2, socket_connect_timeout=2) on both clients (and health-check-specific shorter values if you like).

### M7. ORM metadata has drifted from the real schema — the concurrency invariant exists only in migrations

backend/app/models/parcels.py (absent), backend/alembic/versions/0009_schema_hardening.py:47-52, 0010_review_hardening.py (partial indexes), backend/tests/conftest.py:47-190

Scenario: uq_timeline_requests_parcel_inflight, uq_property_events_null_source_record, and idx_parcels_point_geog exist in migrations but not in the ORM metadata. `alembic revision --autogenerate` will emit drop_index for all three; a reviewer who trusts autogenerate ships a migration that deletes the one-in-flight-per-parcel invariant. Meanwhile conftest hand-maintains a parallel schema (~190 lines of CREATE TABLE) that must be manually kept in sync with every migration — it currently matches, but nothing enforces that, and the day it drifts your tests validate a schema production doesn't have.

Fix: Represent the partial indexes in the models (Index(..., postgresql_where=...), sqlite_where=...), and derive the test schema from Base.metadata.create_all instead of hand-written DDL.

### M8. ON CONFLICT DO NOTHING freezes records at first fetch — DC resales never appear; same-day NYC sales collapse

backend/app/services/property_events.py [line partially lost], backend/app/services/county_adapters.py:384, 643

Scenario 1 (DC): DC sales use SSL (the parcel identifier) as source_record_id and the dataset only carries LAST_SALE_*. Property sells again in 2027 → new price/date arrives under the same SSL → DO NOTHING → the event stays frozen at whatever sale was current at first fetch, showing a stale price. Scenario 2 (NYC): source_id = f"{block}-{lot}-{sale_dt}" — two legally distinct same-day transfers on one lot (package deals, corrected deeds) produce one key; the second is silently dropped. Contrast with the imagery upsert, which deliberately refreshes on conflict.

Fix: For DC, make the record id SSL + sale_date (new sale = new event) or switch to DO UPDATE. For NYC, include price (or a document id if present) in the key.

### M9. Titiler→API callback traffic goes over the public internet, doubling public request load per Landsat tile

M9 (tile-serving path): inter-service routing and unauthenticated-endpoint exposure identified around the Titiler callback and COG warmup paths; details withheld pending fix.

### M10. alembic upgrade head [heading partially lost — concurrency past one machine]

backend/entrypoint.sh:5-9, fly.toml (single machine today)

Scenario: You scale the API to 2 machines (or a deploy briefly overlaps old/new). Both boot, both run alembic upgrade head concurrently, both read the same alembic_version, both apply the same migration; one hits a duplicate-DDL error and crash-loops. Fine today at min_machines_running = 1; a booby trap for the first scale-up. Also note deploy-api and deploy-worker run in parallel in CI — the worker can start executing new task code against the old schema for the window before the API machine's migration lands.

Fix: Take pg_advisory_lock around the upgrade (alembic's documented pattern), or move migrations to a release-command step.

### M11. After completion, per-source failures vanish from the UI and the empty-state copy is wrong

**Resolved:** 256ed32, 2026-08-03

frontend/src/components/ParcelInfo.tsx (timeline status block: tasks are only listed while isTimelineProcessing), frontend/src/components/DemographicsPanel.tsx ("Data will appear once the timeline finishes processing.")

Scenario: Census task fails; request completes. During processing the user briefly saw a red dot; after completion ParcelInfo shows only "42 items" and the demographics panel says data "will appear once the timeline finishes processing" — but the timeline is finished and the data will not appear (until a future backfill). The user is given a promise the system knows is false. This is the front half of H4/M4: partial failure exists in the data model (tasks[].status) but is never surfaced in the terminal UI state.

Fix: Keep failed/skipped rows visible after completion ("Property data unavailable — we'll retry on your next visit"), and gate the empty-state copy on task status.

### M12. Celery config: dead retry semantics, disabled TLS verification, results stored for nobody

backend/app/tasks/celery_app.py:20-25, 30-47

Three in one file: (1) max_retries=3 on the task is inert — nothing calls self.retry and there's no autoretry_for; the decorator implies retry semantics that don't exist. (2) _redis_url_with_ssl appends ssl_cert_reqs=CERT_NONE, disabling certificate verification for the broker carrying your task queue — while db.py's clients use the raw URL and verify certs against the same server, proving verification works; use CERT_REQUIRED. (3) A result backend is configured and every result is stored with a 1-day TTL, but no caller ever reads results (delay() fire-and-forget) — set task_ignore_result=True. Also worth knowing: acks_late + Redis visibility_timeout (default 1h) > hard limit (35m) is safe from double-execution — but only by 25 minutes of margin; document that coupling, because raising time_limit past 3600 silently enables duplicate runs.

## Low

L1. STAC pagination can loop forever on a pathological server. stac.py:141-162 — while len(items) < max_items with a next link and empty features pages never terminates. Add a max-page counter.

L2. validate_landsat_selection strict-zip landmine. stac.py:659-664 — the gather comprehension filters empty groups (if g) but zip(..., strict=True) iterates all groups; the first-ever empty group raises ValueError and fails the whole Landsat source. Unreachable with today's selectors — which is exactly how it'll bite after a refactor. Filter once into a variable, zip over that.

L3 (county WHERE-clause escaping): input-escaping gaps identified in county_adapters.py's literal escaping, plus inconsistent LIKE anchoring across adapters; details withheld pending fix. Assessed as a fuzz-hazard, not injection.

L4 (outbound STAC fetch): missing destination-host validation identified on the STAC item fetch in imagery.py; details withheld pending fix. Assessed as second-order only — it requires upstream compromise to reach.

L5. Geocoder county fallback stores garbage. geocoder.py:139, 242 — when the Counties layer is absent, county gets the tract NAME ("Census Tract 62.02"); it's stored, truthy, and therefore never healed by parcels.py's only-if-empty backfill, and it breaks adapter lookup for that parcel permanently. Drop the fallback.

L6. TNM search caps at 100 products, no pagination. usgs_topo.py:62-88 — dense quads (many editions × scales) can exceed 100; decades silently missing. Not verified against a real dense-area response — check one (e.g. the DC featured parcel) before fixing. Also extract_source_id returns "" on missing sourceId; multiple such items collide on the unique key and overwrite each other; skip them like the property path does.

L7. _fetch_source's lat=0.0, lng=0.0 defaults. timeline.py:168-169 — the elif lat is not None guard [reconstructed: means the defaults] mean a caller who forgets the args silently point-filters against (0,0) in the Gulf of Guinea and drops every scene. Make them required.

L8. Autocomplete self-DoS. useAddressAutocomplete.ts:12 (150ms debounce) vs the 60/min/IP limit — one fast typer refining a search a few times can exhaust the bucket; everyone behind a corporate NAT shares it; 429s are swallowed to [] so suggestions just silently stop. Debounce ≥300ms and surface the degraded state. Related UX bug: SearchInput.tsx clears the input before the geocode resolves, so a 422 leaves the user with an error and an empty box — clear on success only.

L9. Tile-proxy input hygiene. [partially lost — surviving fragment:] z/x/y accept any int (z=50, negatives) and ride to Titiler, which errors into your 502 path; clamp z to 0–24. Snapshot cache: expired entries linger until LRU pressure and _get_cached_snapshot doesn't evict; capped at 500 entries.

L10. Task error_message passes raw exception strings to the client. schemas/imagery.py exposes it; str(httpx.HTTPStatusError) includes full upstream URLs. I traced the Census-key case specifically — the key does not leak (census errors are re-wrapped without the URL) — so this is hygiene, not disclosure: map to curated messages at the boundary.

L11. Prefork + module-level SQLAlchemy engine. db.py:19 — engine is created at import in the Celery parent and inherited by forked children. Safe today only because the parent never uses it before fork; add a worker_process_init → engine.dispose(close=False) hook so it stays safe by construction.

L12. Misc. CensusSnapshot.raw_data is JSON while PropertyEvent.raw_data is JSONB — pick one (JSONB). compute_subtitles renders "Population declined 0%" when the delta rounds to zero. [fragment lost] URL normalization via chained .replace() silently misses variants (ssl=True). Dockerfile.fly runs as root with gcc left in the final image. CORS allow_credentials=True (main.py) with no cookie auth — drop it. DC PERMIT_LAYERS hardcodes 2026 as the newest layer (county_adapters.py:321-329) — an annual manual chore that fails silently when forgotten.

## Test quality (the pattern, beyond H1's instance)

- The riskiest logic has no tests at all: address_normalizer.py (no test file — see H5), maybe_refetch_for_backfill (only ever mocked, at test_geocode.py:112 — its decision table, the trickiest state machine in the app, is untested), select_naip_items' greedy mosaic path (tests cover only the legacy single-tile branch), and the Landsat validate-and-swap flow's strict-zip edge (L2).
- Fixtures encode impossible states: H1's test_census.py:360 is the sharpest case; more broadly, the census fixtures are uniformly well-shaped payloads, so the known real-world failure shapes (200-with-HTML — M1 — is handled in census.py and [reconstructed: yet] no test distinguishes them) are invisible.
- SQLite + raise_server_exceptions=True (conftest.py:237) means the things production actually does — partial-index conflict recovery in _create_queued_request, [fragment lost — references PostgreSQL-only behaviors: geography-cast index usage, JSONB behavior, and what a client actually receives on an unhandled error] — are all structurally untestable in this suite. That's a deliberate tradeoff for CI speed, but nothing (a small Postgres-marked test tier, even run only in CI) covers the gap.
- What is tested — retry/backoff, status transitions, selectors, parsers — is tested well, with behavioral assertions; this is genuinely better than status-code theater. The problem is coverage aim, not assertion quality.

**Clean files, one line each:** api/v1/parcels.py, api/v1/health.py (modulo M6), api/v1/events.py, api/v1/featured.py, schemas/* (well-bounded input validation — GeocodeRequest even handles inf/nan), services/parcels.py (the advisory-lock dedup design is sound; ditto the per-event-loop client maps in stac.py/db.py — that's a subtle correctness decision done right), store.ts, client.ts (thoughtful AbortSignal fallbacks), applyImageryLayer.ts (clean source/layer lifecycle — no leak on repeated selection, which I checked specifically), MobileBottomSheet.tsx, ErrorBoundary/router/useMediaQuery.

## If I were interviewing you

I'd push on one question until it hurt: "How would you know?" This codebase has a consistent reflex — when an upstream dependency misbehaves, convert it into a smaller success: property outage becomes complete: 0 (H4), a mismatched address becomes a silently dropped record (H5), a partially-failed census becomes complete-with-gaps (M4), a dead chart just doesn't render (H1) — and then the observability layer that should catch all of this drops every field of context you carefully attached (H2), while the test suite validates hand-built inputs the real system can't produce. [reconstructed] Each choice is defensible as graceful degradation; together they mean you cannot currently distinguish "this parcel has no permits" from "the integration has been broken for a month," and neither can any test, log, dashboard, or user. The row-locks and retries from the first audit hardened the paths that fail loudly; the remaining risk is concentrated in the paths that fail silently, and I'd want to hear you talk about completeness signals — per-source failure surfaced to the UI and to metrics, tests pinned to real upstream payload shapes, and an explicit answer to "what does this system do when [final fragment lost in transcription]" — before I believed the pipeline at production scale.
