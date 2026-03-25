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