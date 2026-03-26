.PHONY: up down migrate seed featured test logs shell-api shell-db lint fmt format clean prod

# ── Docker ──────────────────────────────────────────────────────────────────

up:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up --build -d
	@echo "Services started. API: http://localhost:8000  Frontend: http://localhost:5173"

down:
	docker compose down

down-volumes:
	docker compose down -v

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

# ── Database ─────────────────────────────────────────────────────────────────

migrate:
	docker compose exec api alembic upgrade head

migrate-down:
	docker compose exec api alembic downgrade -1

migrate-history:
	docker compose exec api alembic history

# ── Data ─────────────────────────────────────────────────────────────────────

seed:
	docker compose exec api python /app/scripts/seed.py

featured:
	docker compose exec api python /app/scripts/seed_featured.py

# ── Tests ────────────────────────────────────────────────────────────────────

test:
	docker compose exec api pytest tests/ -v --tb=short

test-cov:
	docker compose exec api pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

# ── Code Quality ─────────────────────────────────────────────────────────────

lint:
	docker compose exec api ruff check app/ tests/
	docker compose exec api mypy app/

fmt:
	docker compose exec api ruff format app/ tests/

format: fmt
	cd frontend && npm run fmt

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	docker compose down -v --remove-orphans
	@echo "All containers, volumes, and orphans removed."

# ── Production ───────────────────────────────────────────────────────────────

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

# ── Shells ───────────────────────────────────────────────────────────────────

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec postgres psql -U plotline -d plotline

# ── Local dev (without Docker) ───────────────────────────────────────────────

.PHONY: dev-install dev-api

dev-install:
	cd backend && pip install -e ".[dev]"

dev-api:
	cd backend && uvicorn app.main:app --reload --port 8000
