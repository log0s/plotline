# First Architecture Audit — Findings

*Run 2026-05 in Claude Code plan mode against the codebase at approximately
c1ac879 (2026-05-22). Reconstructed from the reported results; near-complete.
Remediated across the 2026-05-22/23 hardening block (430a2a6, bc40127, 3d7c414
and siblings).*

---

**Overall verdict:** This is a strong codebase. The architecture is well-layered, the async patterns are correct, the data model is thoughtful, and the tech choices are coherent. Most issues below are polish/hardening, not fundamental design flaws. An interviewer would come away impressed — but these are the things they'd probe on.

## 1. Project Structure

### What's done well
- Clean FastAPI convention: api/v1/ routes, services/ for business logic, models/ for ORM, schemas/ for Pydantic. Route handlers are thin — they delegate to services, which is exactly right.
- Each service owns one concern: geocoder.py handles Census API, stac.py handles Planetary Computer, demographics.py handles Census data transforms. A new engineer could navigate this quickly.
- Frontend mirrors this discipline: api/ for HTTP, hooks/ for React Query, components/ for UI, types/ for shared interfaces. Zustand store is tiny (55 lines) and correctly scoped to UI-only state.

### Issues
SOURCE_LABELS is copy-pasted 4 times across MapView.tsx:24, CompareView.tsx:22, ParcelInfo.tsx:32, Timeline.tsx:43. Same object, same values, four definitions. EVENT_TYPE_CONFIG is duplicated twice (Timeline.tsx:55, ParcelInfo.tsx:108). An interviewer would flag this as a DRY violation — it's the kind of thing that drifts.

Two large frontend components could use extraction. DemographicsPanel.tsx (677 lines) contains 5+ chart sub-components inline. ParcelInfo.tsx (521 lines) has EventDetail (~85 lines) and SearchInput (~140 lines) as nested components that could be their own files. These aren't critically oversized, but an interviewer will notice 600+ line components and ask why.

### Recommendations
1. Create src/constants.ts with SOURCE_LABELS and EVENT_TYPE_CONFIG — single source of truth, import everywhere. Low effort, high signal to interviewers.
2. Extract EventDetail and the inline charts into their own files. Not urgent, but improves testability.

## 2. Tech Stack Coherence

### What's done well
- Every dependency earns its place. MapLibre (not Mapbox — no API key), React Query + Zustand (not Redux — right-sized), httpx (async-native HTTP), Celery (real task queue, not background threads). An interviewer would see deliberate choices.
- Frontend versions are well-pinned (caret ranges with lockfile). No bloat: 10 runtime deps total.
- Ruff for Python linting is the modern choice. mypy --strict with pydantic plugin shows rigor.

### Issues
psycopg2-binary in production (pyproject.toml:17). The psycopg2 maintainers explicitly warn against this for production deployments — the binary wheels bundle their own libpq, which can conflict with the OS SSL/libpq versions in the Docker image. The Dockerfile already installs libpq-dev, so building from source would work. This is exactly the kind of thing a backend-focused interviewer will catch.

No Python lock file. pyproject.toml uses >= for all deps (e.g., fastapi>=0.111.0). There's no requirements.lock, poetry.lock, or uv.lock. Builds are not reproducible — installing today and next month could yield different behavior. Frontend has package-lock.json (good), but the backend is unprotected.

Titiler pinned to latest in production (fly.titiler.toml:10). Docker Compose correctly pins titiler:1.2.1, but the Fly.io deployment uses ghcr.io/developmentseed/titiler:latest. A breaking upstream release would silently break production tile serving.

httpx appears in both main and dev deps (pyproject.toml:23 and :41). It's a runtime dependency (services use it for external HTTP calls), so having it in dev too is redundant but harmless. Minor.

### Recommendations
1. Change psycopg2-binary to psycopg2 in pyproject.toml. The Dockerfile already has the build deps. This is an easy, high-signal fix.
2. Add uv.lock or pip-compile output. Pin exact versions for reproducible builds. Modern Python projects are expected to have this.
3. Pin Titiler version in fly.titiler.toml to match docker-compose (1.2.1).

## 3. API Design

### What's done well
- Endpoints are RESTful and consistent: POST /parcels/{id}/timeline (trigger), GET /timeline-requests/{id} (poll), GET /parcels/{id}/imagery (list). HTTP methods and status codes are correct — 202 for async job creation, 404 for missing resources, 502 for upstream failures.
- Error handling is exemplary. The geocode endpoint (geocode.py:153-261) has a proper exception hierarchy (GeocoderUnavailableError → 502, AddressNotFoundError → 422), structured logging, and graceful degradation if timeline dispatch fails.
- Pydantic schemas for all request/response types. Input validation on query params (min_length=3, max_length=200 on autocomplete). No raw dicts crossing API boundaries.
- API versioning via URL prefix (/api/v1/) applied consistently to all routes.

### Issues
Health endpoint creates a new Redis client on every call (health.py:33). redis_client.from_url(settings.redis_url, socket_connect_timeout=2) instantiates a fresh client instead of using the shared db.get_redis() / db.check_redis_connection() that already exists. This means a new TCP connection (potentially with TLS) per health check. The shared helper at db.py:102-107 does exactly what this endpoint needs.

featured.ts silently swallows errors (featured.ts:10,19). When the API returns non-200, the frontend returns [] or null instead of throwing. This means network failures, 500s, and auth errors are invisible — the landing page just shows empty cards with no feedback. The rest of the API client correctly throws ApiRequestError via handleResponse<T>().

### Recommendations
1. Replace the inline Redis client in health.py with check_redis_connection() from db.py. Three lines of code, removes redundant connection overhead.
2. Make featured.ts throw on error like the other API modules. Use handleResponse<T>() from client.ts, catch at the component level for graceful degradation.

## 4. Database Design

### What's done well
- Comprehensive constraints: CHECK constraints on all status/type/source/dataset enum columns. Unique constraints prevent duplicate data on upsert (e.g., (parcel_id, stac_item_id) on imagery, (parcel_id, dataset, year) on census). Foreign keys with CASCADE delete are used correctly throughout.
- PostGIS indexes where needed: GIST index on parcels.point for ST_DWithin deduplication, GIST index on imagery_snapshots.bbox for spatial queries. Composite indexes on (parcel_id, capture_date) and (parcel_id, event_date) for timeline queries.
- Smart use of nullable columns: Census data (CensusSnapshot) has nullable fields for every metric because not every Census dataset/year has every variable. This is the correct approach vs. trying to normalize sparse time-series data.
- JSONB used judiciously: PropertyEvent.raw_data stores the original county data source response for debugging. CensusSnapshot.raw_data archives the raw Census API response. Both are read-only archival — not queried — so JSONB without a GIN index is appropriate.

### Issues
No domain constraints on coordinates (parcels.py:41-42). latitude and longitude accept any Double value. There's no CHECK constraint enforcing valid ranges (-90 to 90, -180 to 180). The data comes from the Census Geocoder so it's unlikely to be invalid, but an interviewer might ask why there's no constraint.

PropertyEvent unique constraint has a null hole (parcels.py:398-403). The unique constraint is (parcel_id, source, source_record_id), but source_record_id is nullable (parcels.py:376). In PostgreSQL, NULL != NULL, so multiple rows with source_record_id = NULL don't violate the constraint. This could allow duplicate events from sources that don't provide record IDs.

No updated_at on TimelineRequest (parcels.py:89-143). If a worker crashes mid-processing, the request stays in "processing" status forever. There's no timestamp to detect stale requests. The completed_at field only gets set on terminal states, so there's no way to identify stuck jobs.

Redundant coordinate storage (parcels.py:41-46). latitude, longitude, and point (PostGIS POINT) all store the same location. The PostGIS column is needed for spatial queries, and the scalar columns are convenient for API responses. This is a reasonable trade-off, but an interviewer might probe whether a computed property or SQL expression column would be cleaner.

### Recommendations
1. Add updated_at to TimelineRequest with auto-update on status change. This enables stale-job detection (e.g., "processing for >30 minutes = stuck"). High value for operational reliability.
2. Add CHECK constraints for lat/lon bounds — one line each, signals attention to data integrity.
3. Consider a partial unique index on PropertyEvent that handles NULLs: CREATE UNIQUE INDEX ... WHERE source_record_id IS NULL on (parcel_id, source, event_type, event_date).

## 5. Async Architecture

### What's done well
- Per-source isolation is excellent. Each imagery source (NAIP, Landsat, Sentinel-2, USGS Topo, Census, property) runs as an independent coroutine via asyncio.gather(..., return_exceptions=True) (timeline.py:801-803). A Landsat STAC timeout doesn't block NAIP. Each coroutine manages its own DB session. This is the right pattern.
- Idempotent by design. All data upserts use ON CONFLICT DO UPDATE (imagery) or ON CONFLICT DO NOTHING (census, property events). Safe to retry.
- Smart retry logic in _search_stac_with_retry() (timeline.py:82-120): exponential backoff, retryable HTTP status allowlist (429, 500, 502, 503, 504), non-retryable 4xx propagates immediately.
- Backfill detection (imagery.py:164-235): when new data sources are added (e.g., USGS Topo), revisiting a parcel automatically detects missing sources and triggers a re-fetch. This is sophisticated and well-implemented.

### Issues
No row-level locking on timeline request status transitions (timeline.py:708-710). The code does a plain SELECT to load the TimelineRequest, then updates its status. If two Celery workers somehow process the same request (e.g., duplicate task dispatch, Celery retry race), both would read status="queued", both would set "processing", both would proceed. Adding .with_for_update() to the SELECT would acquire an exclusive row lock. In practice this is unlikely given the current single-worker setup, but an interviewer familiar with Celery will ask about it.

No task timeout (timeline.py:849). The Celery task decorator has max_retries=3 but no soft_time_limit or time_limit. If all upstream APIs hang simultaneously (Planetary Computer down, Census API down), the task blocks forever, consuming the worker slot. With concurrency=2 on the Fly worker, two hung tasks = total worker stall.

bind=True but self is unused (timeline.py:850). The task is bound (receives self) but never uses self.request.id for deduplication or self.retry() for structured retries. The catch-and-reraise pattern at line 865-892 means Celery retries the task, but the retry doesn't clean up the "processing" status first — so the retry sees a request already in "processing" and proceeds anyway.

Geocoder creates a new AsyncClient per retry (geocoder.py:89). Inside the retry loop, async with httpx.AsyncClient(...) creates and tears down a client (and its connection pool / TLS state) on each attempt. For 3 retries, that's 3 TLS handshakes to the Census Bureau. The client should be created once outside the loop.

### Recommendations
1. Add soft_time_limit=1800, time_limit=2100 (30min soft, 35min hard) to the Celery task decorator. This is the highest-priority async fix — prevents worker stalls.
2. Add .with_for_update() to the timeline request SELECT at timeline.py:708. Prevents theoretical race conditions.
3. Hoist the httpx.AsyncClient outside the retry loop in geocoder.py. Minor efficiency fix.

## 6. Configuration & Environment

### What's done well
- pydantic-settings with lru_cache singleton (config.py:88-91). Clean, validated, one instance.
- Database URL validator (config.py:72-85) normalizes driver schemes and SSL params — handles the common Heroku/Fly postgres → postgresql migration.
- check_db_connection() in db.py:44-63 uses SET LOCAL statement_timeout = '2s' scoped to the transaction — prevents a slow-but-alive Postgres from making health checks hang. This is a detail that shows operational experience.
- .env is gitignored, .env.example is tracked, .env was never committed to git history (verified).
- All secrets are externalized via environment variables.

### Issues
Redis client initialization is not thread-safe (db.py:75-82, 85-92). The get_redis() and get_async_redis() functions use a check-then-set pattern on module globals without synchronization. If two threads call get_redis() simultaneously when _redis_client is None, both could create separate clients. In practice this is unlikely to cause problems (both clients would work, one just gets orphaned), but it's a classic interview question about singletons and thread safety.

CORS origins are hardcoded defaults (config.py:44). The defaults ["http://localhost:5173", "http://localhost:3000"] are fine for development and overridden in production via env var. But the production value isn't documented in .env.example. Someone deploying this would need to know to set CORS_ORIGINS='["https://plotline.land"]'.

### Recommendations
1. Add thread-safe double-checked locking to Redis initialization in db.py.
2. Add CORS_ORIGINS to .env.example with a comment about JSON array format.

## 7. External API Integration

### What's done well
- Timeouts on all external calls: Census geocoder (20s), Census data API (30s), STAC search (via httpx client defaults), Titiler tile proxy (30s). These are configurable via settings.
- STAC URL signing with Redis cache: SAS tokens are cached for 10 minutes (tokens last ~30 minutes). stac.py handles signing gracefully — if signing fails, falls back to unsigned URL.
- Retry with backoff: Both the geocoder (geocoder.py:83-100) and STAC search (timeline.py:82-120) implement bounded retries with exponential backoff. Retryable vs. fatal errors are distinguished.
- Connection pooling: STAC and signing clients are module-level singletons with connection reuse (stac.py).

### Issues
No request timeout on frontend fetch calls (client.ts). The fetch API has no default timeout. If the backend hangs, the frontend waits indefinitely. Consider AbortSignal.timeout(30_000).

Nginx has no security headers (nginx.conf). Missing: X-Content-Type-Options: nosniff, X-Frame-Options: SAMEORIGIN, Strict-Transport-Security (HSTS), Content-Security-Policy. Fly.io handles TLS termination and force_https, but the nginx config should add defense-in-depth headers. An interviewer with security awareness will notice.

### Recommendations
1. Add security headers to nginx.conf — standard hardening, 5 lines.
2. Add AbortSignal.timeout() to frontend fetch — prevents indefinite waits on slow responses.

## Summary: Prioritized Fix List

### Tier 1 — Interview red flags (fix before showing the repo)

**Resolved:** psycopg2-binary, lock file, Titiler pin — 430a2a6, 2026-05-22.
Celery task timeout, health endpoint Redis client — bc40127, 2026-05-23.
SOURCE_LABELS / EVENT_TYPE_CONFIG extraction — 3d7c414, 2026-05-23.

| Issue | Location | Effort |
|-------|----------|--------|
| psycopg2-binary → psycopg2 | pyproject.toml:17 | 1 min |
| Add Python lock file (uv.lock or pip-compile) | backend/ | 10 min |
| Pin Titiler version in prod | fly.titiler.toml:10 | 1 min |
| Extract SOURCE_LABELS / EVENT_TYPE_CONFIG to shared constants | frontend/src/constants.ts | 15 min |
| Add Celery task timeout | timeline.py:849 | 1 min |
| Fix health endpoint Redis client | health.py:33 | 5 min |

### Tier 2 — Shows operational awareness

**Resolved:** `updated_at` on TimelineRequest, lat/lon CHECK constraints — a64696f, 2026-05-22.
`.with_for_update()`, thread-safe Redis init, nginx security headers — bc40127, 2026-05-23.
featured.ts error swallowing — 3d7c414, 2026-05-23.

| Issue | Location | Effort |
|-------|----------|--------|
| Add updated_at to TimelineRequest for stale-job detection | parcels.py, migration | 30 min |
| Add .with_for_update() to timeline request loading | timeline.py:708 | 5 min |
| Thread-safe Redis initialization | db.py:75-92 | 10 min |
| Nginx security headers | nginx.conf | 5 min |
| Fix featured.ts error swallowing | frontend/src/api/featured.ts | 10 min |
| Add lat/lon CHECK constraints | parcels.py, migration | 15 min |

### Tier 3 — Nice to have

**Resolved:** CORS_ORIGINS in .env.example — 430a2a6, 2026-05-22.
PropertyEvent null-source_record_id dedup index — a64696f, 2026-05-22.
AsyncClient hoisted out of the geocoder retry loop — bc40127, 2026-05-23.
Frontend fetch timeout, component extraction, `ComponentType<any>` — 3d7c414, 2026-05-23.

| Issue | Location | Effort |
|-------|----------|--------|
| Frontend fetch timeout (AbortSignal) | client.ts | 5 min |
| Hoist AsyncClient outside geocoder retry loop | geocoder.py:89 | 5 min |
| Extract large component sub-sections | ParcelInfo.tsx, DemographicsPanel.tsx | 30 min |
| Fix ComponentType<any> → proper icon type | ParcelInfo.tsx:108, Timeline.tsx:57 | 5 min |
| Add CORS_ORIGINS to .env.example | .env.example | 1 min |
| Handle PropertyEvent null source_record_id uniqueness | migration | 20 min |

## What not to change

- The overall architecture is sound. Don't refactor the project structure.
- The Zustand + React Query split is correct and well-implemented.
- The per-source isolation in Celery tasks is excellent design.
- The PostGIS model, spatial indexes, and CASCADE deletes are all correct.
- The Pydantic schema/validation approach is clean.
- Backend test coverage exists (10 test files covering all major routes/services). Frontend tests are absent — worth mentioning if asked, but not a blocker for a portfolio project.
