## Project
Plotline - user enters any US address and receives a rich, scrollable timeline showing how that location has changed over time: aerial/satellite imagery and historical topo maps across decades, property history events, and demographic shifts in the surrounding area.

## Stack

### Backend
- Language: Python 3.12+
- Framework: FastAPI
- Database: PostgreSQL 16 + PostGIS 3.4
- Async Jobs: Celery + Redis
- Image Tile Serving: Titiler
- Key Python Libraries: SQLAlchemy (with GeoAlchemy2), Shapely, pyproj, httpx, pydantic, alembic (migrations), Pillow, structlog

### Frontend
- Framework: React 18+ with TypeScript
- Bundler: Vite
- Map: MapLibre GL JS
- Styling: Tailwind CSS
- State Management: Zustand (UI-interaction state) + React Query (server state)
- Timeline UI: Custom component, animated with Framer Motion

### Infrastructure
- Docker Compose: Single `docker-compose up` to run everything locally (PostgreSQL/PostGIS, Redis, FastAPI API, Celery worker, Titiler, React dev server)
- Alembic for database migrations (run automatically on container start via entrypoint.sh)
- Linting: ruff + mypy via `make lint` (backend); eslint + prettier via npm scripts (frontend). No pre-commit hooks are configured
- CI/CD: GitHub Actions runs backend tests and deploys API/worker/Titiler to Fly.io on push to main; frontend deploys via Cloudflare Pages

## Structure
plotline/
├── docker-compose.yml           # Full local stack: PostGIS, Redis, API, Worker, Titiler, Frontend
├── docker-compose.prod.yml      # Production overrides: nginx frontend, no mounts, multi-worker API
├── Dockerfile.fly               # Backend image used by the Fly.io deploys
├── fly.toml                     # Fly.io config — API
├── fly.worker.toml              # Fly.io config — Celery worker
├── fly.titiler.toml             # Fly.io config — tile server
├── .github/workflows/deploy.yml # CI: backend tests + Fly.io deploys on push to main
├── Makefile
├── README.md
├── DEVELOPMENT.md               # Process journal + analysis. Build Log entries are FROZEN —
│                                #   never rewrite them; add dated "Later:" notes only. The
│                                #   analysis section and structure are editable under explicit
│                                #   instruction from Ryan, never on your own initiative.
├── docs/
│   ├── audits/                  # Frozen findings docs + STATUS.md (the living ledger)
│   └── provenance/              # Git-history analysis behind DEVELOPMENT.md's numbers
├── SUPPORTED_COUNTIES.md        # County data source documentation
├── prompts/                     # Phase prompts used to build the project
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh            # Runs migrations, then starts the service
│   ├── pyproject.toml
│   ├── uv.lock                  # Locked Python dependencies — Docker builds install from these
│   ├── alembic.ini
│   ├── alembic/                 # Database migrations
│   ├── static_data/             # Pre-rendered featured-location preview images
│   ├── app/
│   │   ├── main.py              # FastAPI app factory
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── db.py                # Database session management
│   │   ├── logging_config.py    # structlog setup (JSON in prod, console in dev)
│   │   ├── models/              # SQLAlchemy + GeoAlchemy2 models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── api/v1/              # geocode, parcels, imagery, demographics, events, featured, health
│   │   ├── services/            # geocoder, stac, usgs_topo, census, demographics, imagery, parcels,
│   │   │                        #   property_events, county_adapters (+ arcgis/socrata/ckan clients),
│   │   │                        #   address_normalizer, preview_renderer
│   │   └── tasks/               # celery_app + timeline task (imagery, census, property fetch)
│   └── tests/
├── frontend/
│   ├── Dockerfile               # Dev image (Vite); Dockerfile.prod + nginx.conf for production
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx             # Entry point
│   │   ├── router.tsx           # Routes: /, /explore/:parcelId, /featured/:slug
│   │   ├── store.ts             # Zustand store (UI-interaction state only)
│   │   ├── pages/               # Landing, Explore, FeaturedRedirect, NotFound
│   │   ├── components/          # SearchBar, MapView, Timeline, DemographicsPanel, CompareView, …
│   │   ├── hooks/               # queries.ts (React Query), address autocomplete, media queries
│   │   ├── api/                 # Typed API client functions
│   │   ├── types/
│   │   └── utils/
│   └── index.html
└── scripts/
    ├── seed.py                  # Seed example parcels
    ├── seed_featured.py         # Pre-compute featured location timelines
    ├── revalidate_landsat.py    # Re-queue timelines to replace broken Landsat scenes
    ├── heal_county_fallback.py  # Data heal: NULL out tract-name garbage in parcels.county
    ├── heal_tract_vintage_gaps.py # Data heal: backfill ACS years lost to the 2020 tract split
    └── requeue_parcels.py       # Re-queue specific parcels (deployment-gated — see docstring)

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

## The record moves with the code

STATUS.md (docs/audits/2026-08-second-audit/STATUS.md) is the living ledger of
every audit finding, deferred decision, and accepted risk. Findings documents
under docs/audits/ are frozen records — never edited, only annotated with
dated additions (e.g. "**Resolved:** <hash>, <date>"). DEVELOPMENT.md's Build
Log is frozen the same way.

A change is not complete until the record reflects it. Concretely:

1. **Fixing anything a finding describes** → the same batch adds the Resolved
   annotation (with the real commit hash — verify it exists and is an ancestor
   of HEAD; amended commits change hashes) and updates the STATUS.md row.
2. **Deciding not to fix something** → STATUS.md records it as accepted, with
   the one-sentence rationale that would survive a skeptical reader. If the
   rationale rests on a load-bearing assumption (topology, scale, upstream
   behavior), that assumption also lands as a code comment at the site where
   someone would act on it.
3. **Discovering something new** (a defect, a tried-and-rejected approach, a
   mechanism that explains observed behavior) → it enters STATUS.md in the
   same batch, even if unfixed. Especially if unfixed: undocumented knowledge
   of a live issue is how 131-day residents happen.
4. **Predictions before actions**: any heal, sweep, or migration with an
   expected outcome gets that expectation written into STATUS.md before the
   run. Afterward, the observed result lands next to it with a verdict
   (confirmed / deviation / falsified). Never edit the prediction to match
   the outcome.
5. **Deploy-state honesty**: "Resolved" means the fix is in the code. If a
   fix is committed but known to be undeployed at writing time, say so
   ("committed, not yet deployed as of <date>") — a mitigation that isn't
   running isn't mitigating.

Before reporting any task complete, check: does STATUS.md (or the relevant
doc) still say something this batch made false? If yes, the batch isn't done.
Prose written *about* code drifts; prose written *alongside* code in the same
commit is the only kind that stays true. When you cannot update the record
(out of scope, uncertain finding), say so explicitly in your report rather
than leaving it silently stale.

## Commit conventions

Conventional commits (feat:/fix:/docs:/chore:). Every commit carries the
Co-Authored-By trailer for the model that wrote it — the repo's own
provenance analysis documents what the 31% unstamped era cost. Never push;
push, deploy, and heal execution belong to Ryan.