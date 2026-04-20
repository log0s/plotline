## Project
Plotline - user enters any US address and receives a rich, scrollable timeline showing how that location has changed over time: aerial/satellite imagery across decades, property history events, and demographic shifts in the surrounding area.

## Stack

### Backend
- Language: Python 3.12+
- Framework: FastAPI
- Database: PostgreSQL 16 + PostGIS 3.4
- Async Jobs: Celery + Redis
- Image Tile Serving: Titiler
- Key Python Libraries: SQLAlchemy (with GeoAlchemy2), Shapely, Rasterio, httpx, pydantic, alembic (migrations)

### Frontend
- Framework: React 18+ with TypeScript
- Bundler: Vite
- Map: MapLibre GL JS
- Styling: Tailwind CSS
- State Management: Zustand or React Query (your call — keep it simple)
- Timeline UI: Custom component, animated with Framer Motion

### Infrastructure
- Docker Compose: Single `docker-compose up` to run everything locally (PostgreSQL/PostGIS, Redis, FastAPI API, Celery worker, React dev server)
- Alembic for database migrations
- Pre-commit hooks: ruff (Python linting/formatting), eslint + prettier (TypeScript)

## Structure
plotline/
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

## Code Standards

### Typescript

- Don't use `any` — use `unknown` and narrow the type
- Don't skip error handling — always show user feedback

### Python

- Don't catch bare Exception — catch specific exceptions
- Don't put business logic in route handlers — use services/
- Don't use # type: ignore without a comment explaining why
- Pydantic models for all API request/response schemas. Don't pass dicts around
- Dependency injection in FastAPI — use `Depends()` for DB sessions, config, etc
- Environment-based config: all secrets/URLs via environment variables, validated by pydantic-settings
- Error handling: don't let raw 500s escape (e.g. Geocoder down? Return a clear 502 with a message. Bad address? 422 with details)
- Logging: use structured logging (structlog or just Python's logging with JSON formatter). Log geocoder calls, DB writes, job status changes