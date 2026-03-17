# Geospatial Time Machine — Claude Code Project Brief

## Project Overview

Build a full-stack web application called **Plotline**. A user enters any US address and receives a rich, scrollable timeline showing how that location has changed over time: aerial/satellite imagery across decades, property history events, and demographic shifts in the surrounding area.

This is a portfolio project for a senior full-stack engineer with 12 years of experience and a background in Earth Observation / GIS systems. The code quality, architecture, and developer experience (README, Docker setup, etc.) should reflect that seniority.

---

## Tech Stack

### Backend
- **Language**: Python 3.12+
- **Framework**: FastAPI
- **Database**: PostgreSQL 16 + PostGIS 3.4
- **Async Jobs**: Celery + Redis
- **Image Tile Serving**: Titiler (FastAPI-based dynamic tile server for Cloud-Optimized GeoTIFFs)
- **Key Python Libraries**: SQLAlchemy (with GeoAlchemy2), Shapely, Rasterio, httpx (async HTTP client), pydantic, alembic (migrations)

### Frontend
- **Framework**: React 18+ with TypeScript
- **Bundler**: Vite
- **Map**: MapLibre GL JS (open-source Mapbox GL fork)
- **Styling**: Tailwind CSS
- **State Management**: Zustand or React Query (your call — keep it simple)
- **Timeline UI**: Custom component, animated with Framer Motion

### Infrastructure
- **Docker Compose**: Single `docker-compose up` to run everything locally (PostgreSQL/PostGIS, Redis, FastAPI API, Celery worker, React dev server)
- **Alembic** for database migrations
- **Pre-commit hooks**: ruff (Python linting/formatting), eslint + prettier (TypeScript)

---

## Data Sources

All free, public, no API keys required unless noted:

| Source | What It Provides | API / Access Method |
|--------|-----------------|-------------------|
| **US Census Geocoder** | Address → lat/lng + census tract/block | REST API, no key needed |
| **NAIP via Planetary Computer** | Aerial imagery ~1m resolution, 2003–present | STAC API (Microsoft Planetary Computer), no key needed |
| **Landsat via Planetary Computer** | Satellite imagery 30m, 1984–present | STAC API, no key needed |
| **USGS Historical Topos** | Scanned topographic maps, early 1900s–present | STAC API or direct download |
| **US Census Bureau API** | Decennial + ACS demographic data by tract | REST API, free key (register at census.gov) |
| **OpenStreetMap / Overpass** | Current building footprints, land use | Overpass API, no key needed |
| **Denver Open Data** | Property sales, permits (Denver metro scope) | Socrata API, no key needed |

---

## Phase 1 — Foundation (Build This First)

**Goal**: Wire the full stack end-to-end. User enters an address, it gets geocoded, stored in PostGIS, and displayed on a map. No imagery, no timeline yet — just prove the plumbing works.

### What to build:

#### Database
- Set up PostgreSQL + PostGIS via Docker
- Create initial Alembic migration with these tables:

```sql
-- Core parcel table
CREATE TABLE parcels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address TEXT NOT NULL,
    normalized_address TEXT, -- cleaned version from geocoder
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    point GEOMETRY(POINT, 4326) NOT NULL, -- SRID 4326 = WGS84
    census_tract_id TEXT,
    county TEXT,
    state_fips TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_parcels_point ON parcels USING GIST (point);
CREATE INDEX idx_parcels_address ON parcels USING GIN (to_tsvector('english', address));

-- Async job tracking
CREATE TABLE timeline_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID REFERENCES parcels(id),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'complete', 'failed')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);
```

#### API Endpoints

```
POST /api/v1/geocode
  Body: { "address": "1600 Pennsylvania Ave, Washington DC" }
  Response: {
    "parcel_id": "uuid",
    "address": "normalized address",
    "latitude": 38.8977,
    "longitude": -77.0365,
    "census_tract": "110010062021"
  }
  Behavior:
    1. Call US Census Geocoder API to geocode
    2. Check if we already have this parcel (dedupe by proximity — within 50m)
    3. If new, insert into parcels table
    4. Return parcel data

GET /api/v1/parcels/{parcel_id}
  Response: Full parcel record

GET /api/v1/health
  Response: { "status": "ok", "db": "connected", "redis": "connected" }
```

#### Frontend

- Clean landing page with:
  - Project title and one-line description
  - Address search bar (prominent, centered)
  - A few "Try these" example addresses as clickable chips below the search bar
- On search:
  - Call POST /api/v1/geocode
  - Transition to a map view centered on the returned coordinates
  - Drop a marker on the location
  - Show the normalized address and census tract info in a sidebar or overlay
- Map: MapLibre GL JS with a clean base style (use MapTiler's free tier for tiles, or OpenFreeMap)

#### Docker Compose

```yaml
# Services needed:
# - postgres (with PostGIS extension)
# - redis
# - api (FastAPI, with hot-reload via uvicorn)
# - worker (Celery — can be a no-op for Phase 1, but wire it up)
# - frontend (Vite dev server with proxy to API)
```

Include a `Makefile` or `justfile` with common commands:
- `make up` — start everything
- `make down` — stop everything
- `make migrate` — run Alembic migrations
- `make seed` — insert a few example parcels for testing
- `make test` — run backend tests

#### Tests

Write tests for:
- Geocoding endpoint (mock the Census API response)
- Parcel deduplication logic
- Database spatial query (point within polygon)
- Health check endpoint

Use pytest + pytest-asyncio for the backend. Don't worry about frontend tests yet.

---

## Project Structure

```
parcel-history/
├── docker-compose.yml
├── Makefile
├── README.md
├── DEVELOPMENT.md          # Claude Code process documentation
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml       # Use modern Python packaging
│   ├── alembic/
│   │   ├── alembic.ini
│   │   └── versions/
│   ├── app/
│   │   ├── main.py          # FastAPI app factory
│   │   ├── config.py        # Settings via pydantic-settings
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic request/response schemas
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── geocode.py
│   │   │       └── parcels.py
│   │   ├── services/        # Business logic
│   │   │   ├── geocoder.py  # Census Geocoder client
│   │   │   └── parcels.py
│   │   ├── tasks/           # Celery tasks (stub for Phase 1)
│   │   └── db.py            # Database session management
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── SearchBar.tsx
│   │   │   ├── MapView.tsx
│   │   │   └── ParcelInfo.tsx
│   │   ├── hooks/
│   │   ├── api/             # API client functions
│   │   └── types/
│   └── index.html
└── scripts/
    └── seed.py              # Seed example parcels
```

---

## Code Quality Expectations

This is a senior engineer's portfolio project. Accordingly:

- **Type everything.** Python: use type hints everywhere, run mypy. TypeScript: strict mode.
- **No `any` types** in TypeScript unless absolutely unavoidable (and add a comment explaining why).
- **Pydantic models** for all API request/response schemas. Don't pass dicts around.
- **Dependency injection** in FastAPI — use `Depends()` for DB sessions, config, etc.
- **Async where it matters** — the geocoder HTTP call should be async (httpx), DB queries can be sync via SQLAlchemy for simplicity in Phase 1.
- **Environment-based config** — all secrets/URLs via environment variables, validated by pydantic-settings.
- **Meaningful commit messages** — if you're committing on my behalf, use conventional commits (feat:, fix:, chore:, etc.).
- **Error handling** — don't let raw 500s escape. Geocoder down? Return a clear 502 with a message. Bad address? 422 with details.
- **Logging** — use structured logging (structlog or just Python's logging with JSON formatter). Log geocoder calls, DB writes, job status changes.

---

## Design Sensibility

For the frontend — keep it clean, modern, and slightly opinionated:

- Dark mode by default (maps look better on dark backgrounds)
- Minimal chrome — the map should dominate the viewport
- The search bar on the landing page should feel like a Google-tier search experience: fast, centered, inviting
- Use a monospace or semi-mono font for data labels (coordinates, tract IDs)
- Subtle transitions between the landing/search view and the map view
- Color palette: dark grays/navy for the UI shell, a single accent color (something earthy — amber, terracotta, or sage green) for interactive elements

---

## Future Phases (Don't build yet, but design for them)

The schema and architecture should accommodate these future additions without major refactors:

- **Phase 2**: NAIP/Landsat imagery timeline (async job fetches imagery metadata from STAC API, stores snapshots, frontend renders scrollable timeline)
- **Phase 3**: Census demographic overlays (population, income, housing data by decade, shown as charts alongside the map)
- **Phase 4**: Property history events from county open data (sales, permits, zoning changes)
- **Phase 5**: Side-by-side "then vs now" image comparison, shareable URLs, polished landing page with featured examples

Design the database, API routing, and component structure so these phases plug in naturally.

---

## Getting Started

1. Set up Docker Compose with PostGIS + Redis
2. Scaffold the FastAPI backend with the project structure above
3. Create the initial Alembic migration
4. Implement the geocode endpoint (calling the Census Geocoder)
5. Scaffold the React frontend with Vite + TypeScript + Tailwind
6. Build the landing page with search bar
7. Wire up the map view with MapLibre
8. Connect everything end-to-end
9. Write tests
10. Write the README with setup instructions

Take it step by step. After each major piece, verify it works before moving on.

