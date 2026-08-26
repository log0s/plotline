# Plotline

Enter any US address → a scrollable timeline of how that location has changed:
aerial/satellite imagery and historical topos across decades, property history,
and demographic shifts in the surrounding area.

## Stack

Backend: Python 3.12, FastAPI, SQLAlchemy + GeoAlchemy2, Alembic, Celery + Redis,
PostgreSQL 16 + PostGIS 3.4, Titiler, structlog. Frontend: React 18 + TypeScript,
Vite, MapLibre GL JS, Tailwind, Zustand (UI-interaction state only) + React Query
(server state), Framer Motion for the timeline.

`docker-compose up` runs the full local stack; migrations run on container start
via `backend/entrypoint.sh`. Lint with `make lint` (ruff + mypy) and the frontend
npm scripts (eslint + prettier); no pre-commit hooks. CI
(`.github/workflows/deploy.yml`) runs backend tests and deploys API, worker, and
Titiler to Fly.io on push to main; the frontend deploys via Cloudflare Pages.

## Code standards

TypeScript: no `any` — use `unknown` and narrow. Never skip error handling; always
surface feedback to the user.

Python: catch specific exceptions, never bare `Exception`. Business logic lives in
`backend/app/services/`, not route handlers. `# type: ignore` needs a comment
saying why. Pydantic models for every API schema — don't pass dicts around.
`Depends()` for DB sessions and config. All secrets and URLs via environment,
validated by pydantic-settings. No raw 500s escape: geocoder down → 502 with a
message; bad address → 422 with details. Structured logging for geocoder calls,
DB writes, and job status changes.

## Engineering norms

- **Investigate before implementing.** When a premise is uncertain, produce a
  report first and act second; stop if the premise breaks. Prompts say which mode
  they're in.
- **Grep for the shape before closing a bug.** A fix isn't done until the same
  pattern has been searched for elsewhere.
- **Delete-the-fix is the test standard.** A regression test counts only if it
  fails with the fix removed.
- **"Complete with zero" and "failed" are different states, everywhere.** Never
  convert an upstream failure into a smaller success.
- **Reports are files, not chat.** Write investigation output to a markdown file
  under `docs/audits/<date>-<topic>/`; terminal paste garbles.

## The record moves with the code

`docs/audits/2026-08-second-audit/STATUS.md` is the living ledger of every audit
finding, deferred decision, and accepted risk. Everything else in the audit trail
is frozen: findings docs under `docs/audits/` and DEVELOPMENT.md's Build Log are
never edited, only annotated with dated additions (`**Resolved:** <hash>, <date>`
or a "Later:" note). DEVELOPMENT.md's analysis section is editable only on
explicit instruction from Ryan, never on your own initiative.

A change is not complete until the record reflects it, in the same batch:

1. **Fixing something a finding describes** → add the Resolved annotation with the
   real commit hash (verify it's an ancestor of HEAD; amends change hashes) and
   update the STATUS.md row.
2. **Deciding not to fix** → STATUS.md records it as accepted with a one-sentence
   rationale that survives a skeptical reader. If the rationale rests on an
   assumption (topology, scale, upstream behavior), that assumption also becomes a
   code comment at the site where someone would act on it.
3. **Discovering something new** — a defect, a rejected approach, a mechanism —
   → it enters STATUS.md even if unfixed. Especially if unfixed: undocumented
   knowledge of a live issue is how 131-day residents happen.
4. **Predictions before actions.** Any heal, sweep, or migration gets its expected
   outcome written into STATUS.md before the run, and the observed result lands
   next to it with a verdict (confirmed / deviation / falsified). Never edit the
   prediction to match the outcome.
5. **Deploy-state honesty.** "Resolved" means the fix is in the code. If it's
   committed but not deployed, say so with the date — a mitigation that isn't
   running isn't mitigating.

Before reporting a task complete: does STATUS.md still say something this batch
made false? If yes, the batch isn't done. If the record can't be updated (out of
scope, uncertain finding), say so in the report rather than leaving it silently
stale.

## Commits

- Conventional commits (feat:/fix:/docs:/chore:). Every commit carries the
`Co-Authored-By` trailer for the model that wrote it — the provenance analysis
documents what the unstamped era cost. One session writes the repo at a time;
per-session instructions don't transfer between concurrent sessions. Never push:
push, deploy, and heal execution belong to Ryan.
- Dependency changes ship with the lockfile. Any edit to `backend/pyproject.toml` dependencies is committed together with the regenerated `backend/uv.lock` (`uv lock`). Run tests with `uv sync --locked` before reporting results — that is what CI runs, and a stale lockfile fails there even when tests pass locally.

## Production access

Production is read-only from any session, and reads go through Fly:

    fly ssh console -a log0s-plotline-api -C "<command>"
    fly ssh console -a plotline-worker -C "<command>"
    fly logs -a <app>

- Use `-C`, not the interactive console. SQL is `SELECT` only.
- Never point a local process at production: no `docker compose exec` with a prod
  `DATABASE_URL`, no prod credentials in a local `.env`, no local `psql` against
  Neon. If a command needs the prod database, it runs inside the Fly machine.
- Writes are the owner's: every `scripts/*heal*.py` and `scripts/requeue_*.py`,
  `scripts/revalidate_landsat.py`, any `UPDATE`. A session runs one only under a
  written exception in its prompt that names the SHA the worker must be on,
  verified first with `fly image show -a plotline-worker` (`GH_SHA` label) before
  invoking anything.
- If `fly ssh` is denied, stop and say so. Do not find another route.