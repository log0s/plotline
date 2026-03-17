# Plotline — Geospatial Time Machine

Enter any US address and explore how that location has changed over time: aerial and satellite imagery across decades, property history events, and demographic shifts in the surrounding area.

> **Phase 1** — Foundation: full-stack plumbing. Address → geocode → PostGIS → map. No imagery yet.

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 24+
- [Docker Compose](https://docs.docker.com/compose/) v2 (ships with Docker Desktop)
- `make` (standard on macOS/Linux; Windows users can use `.\scripts\make.ps1` or run commands directly)

### 1. Clone and configure

```bash
git clone https://github.com/youruser/plotline.git
cd plotline
cp .env.example .env   # edit if needed — defaults work for local dev
```

### 2. Start everything

```bash
make up
```

This builds the images, starts PostgreSQL/PostGIS, Redis, the FastAPI API, the Celery worker, and the Vite dev server.

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| API docs (ReDoc) | http://localhost:8000/redoc |
| Health check | http://localhost:8000/api/v1/health |

### 3. Run database migrations

```bash
make migrate
```

### 4. (Optional) Seed example parcels

```bash
make seed
```

Inserts 5 well-known US addresses via the geocode API.

---

## Make Commands

| Command | Description |
|---------|-------------|
| `make up` | Build and start all services (detached) |
| `make down` | Stop all services |
| `make down-volumes` | Stop and delete persistent volumes |
| `make migrate` | Run Alembic migrations (upgrade head) |
| `make migrate-down` | Roll back one migration |
| `make seed` | Insert example parcels |
| `make test` | Run backend test suite |
| `make test-cov` | Run tests with coverage report |
| `make lint` | Run ruff + mypy |
| `make fmt` | Auto-format with ruff |
| `make logs` | Tail logs from all services |
| `make logs-api` | Tail API logs only |
| `make shell-api` | Bash shell inside the API container |
| `make shell-db` | psql shell inside the PostgreSQL container |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Compose                        │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │   Frontend   │   │   FastAPI    │   │ Celery Worker  │  │
│  │  React/Vite  │──▶│  API (:8000) │   │  (Phase 2+)    │  │
│  │    (:5173)   │   │              │   │                │  │
│  └──────────────┘   └──────┬───────┘   └───────┬────────┘  │
│                             │                   │           │
│                    ┌────────▼───────────────────▼──────┐    │
│                    │  PostgreSQL 16 + PostGIS 3.4       │    │
│                    │           (:5432)                  │    │
│                    └───────────────────────────────────┘    │
│                                                             │
│                    ┌───────────────────────────────────┐    │
│                    │        Redis 7 (:6379)             │    │
│                    │   (Celery broker + result backend) │    │
│                    └───────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

External:
  ┌────────────────────────────────────────────────┐
  │  US Census Geocoder API (geocoding.geo.census.gov) │
  │  Microsoft Planetary Computer STAC (Phase 2)       │
  └────────────────────────────────────────────────┘
```

### Key design decisions

- **PostGIS for all spatial work** — proximity deduplication uses `ST_DWithin` on geography type for metre-accurate distances. Future phases will use `ST_Intersects`, `ST_Within`, and raster operations.
- **Async geocoder** — the Census Geocoder HTTP call uses `httpx` async client, keeping FastAPI's event loop free.
- **Celery wired but dormant** — the worker registers a `build_timeline` task stub. Phase 2 will fill it with STAC imagery fetching.
- **Schema designed for future phases** — `timeline_requests` table is Phase 2 scaffolding; parcel table has `census_tract_id`/`state_fips` columns for Phase 3 demographic joins.

---

## API Reference

### `POST /api/v1/geocode`

Geocode a US address.

```json
// Request
{ "address": "1600 Pennsylvania Ave NW, Washington, DC" }

// Response 200
{
  "parcel_id": "3a8f1c2d-...",
  "address": "1600 Pennsylvania Ave NW, Washington, DC",
  "normalized_address": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
  "latitude": 38.8977,
  "longitude": -77.0365,
  "census_tract": "11001006202",
  "is_new": true
}
```

Error responses: `422` (bad/unmatched address), `502` (Census API unavailable).

### `GET /api/v1/parcels/{parcel_id}`

Retrieve a parcel by UUID.

### `GET /api/v1/health`

```json
{ "status": "ok", "db": "connected", "redis": "connected", "version": "0.1.0" }
```

---

## Data Sources

| Source | What It Provides | Phase |
|--------|-----------------|-------|
| [US Census Geocoder](https://geocoding.geo.census.gov/) | Address → lat/lng + census tract | 1 |
| [NAIP via Planetary Computer](https://planetarycomputer.microsoft.com/dataset/naip) | Aerial imagery ~1m, 2003–present | 2 |
| [Landsat via Planetary Computer](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2) | Satellite imagery 30m, 1984–present | 2 |
| [USGS Historical Topos](https://www.usgs.gov/programs/national-geospatial-program/topographic-maps) | Scanned topo maps, early 1900s–present | 2 |
| [US Census Bureau API](https://www.census.gov/data/developers/data-sets.html) | Decennial + ACS demographic data | 3 |
| [OpenStreetMap / Overpass](https://overpass-api.de/) | Building footprints, land use | 4 |
| [Denver Open Data](https://www.denvergov.org/opendata) | Property sales, permits (Denver metro) | 4 |
| [OpenFreeMap](https://openfreemap.org/) | Base map tiles (no API key) | 1 |

---

## Development

### Running tests locally

```bash
# Inside the API container (recommended)
make test

# Or directly with a local Python environment
cd backend
pip install -e ".[dev]"
pytest tests/ -v
```

### Backend structure

```
backend/app/
├── main.py          # FastAPI app factory
├── config.py        # pydantic-settings — all env vars validated here
├── db.py            # SQLAlchemy engine + session dependency
├── logging_config.py
├── api/v1/
│   ├── geocode.py   # POST /geocode
│   ├── parcels.py   # GET /parcels/{id}
│   └── health.py    # GET /health
├── models/
│   └── parcels.py   # SQLAlchemy ORM models (Parcel, TimelineRequest)
├── schemas/
│   ├── geocode.py   # Pydantic request/response schemas
│   └── parcels.py
├── services/
│   ├── geocoder.py  # Census Geocoder async HTTP client
│   └── parcels.py   # get_or_create_parcel with ST_DWithin dedup
└── tasks/
    ├── celery_app.py
    └── timeline.py  # Stub tasks (Phase 2)
```

### Adding a new migration

```bash
docker compose exec api alembic revision --autogenerate -m "add my_table"
make migrate
```

### Environment variables

See `.env.example` for all available variables. The most important:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `CENSUS_API_KEY` | No | — | Free Census API key for higher rate limits |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Roadmap

- **Phase 2**: NAIP/Landsat imagery timeline — async Celery job fetches imagery metadata from Planetary Computer STAC, stores scene references, frontend renders a scrollable decade-by-decade timeline.
- **Phase 3**: Census demographic overlays — population, income, housing cost by decade shown as charts alongside the map.
- **Phase 4**: Property history events from county open data — sales, permits, zoning changes on a timeline.
- **Phase 5**: Side-by-side "then vs now" image comparison, shareable URLs, polished landing with featured examples.

---

## License

MIT
