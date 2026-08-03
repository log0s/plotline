# First Architecture Audit — Prompt

*Issued 2026-05 (inferred from remediation commits; the audit itself was not
committed). Run in Claude Code plan mode. Reproduced verbatim.*

---

Perform a thorough architecture audit of this codebase. I'm a senior full-stack engineer using this as a portfolio project for job hunting — it needs to hold up to scrutiny from experienced interviewers. Be brutally honest. I'd rather fix problems now than get asked about them in an interview.

## What to evaluate

### 1. Project Structure
- Does the directory layout follow established conventions for the frameworks in use (FastAPI, React)?
- Are concerns properly separated (routes vs business logic vs data access)?
- Is there any logic in the wrong layer (e.g., business logic in route handlers, data access in services)?
- Are there files that are doing too much? Files that should be consolidated?
- Is the project navigable — could a new engineer find things quickly?

### 2. Tech Stack Coherence
- Do the technology choices make sense together?
- Are there redundant dependencies — libraries that overlap in functionality?
- Are there places where a simpler tool would do the job better?
- Are dependency versions pinned appropriately?
- Are there any dependencies that are unmaintained, deprecated, or have known issues?

### 3. API Design
- Are endpoints RESTful and consistently named?
- Are HTTP methods and status codes used correctly?
- Is the URL structure logical and predictable?
- Are request/response schemas consistent across endpoints?
- Is there proper input validation on all endpoints?
- Are error responses structured and useful (not just raw 500s)?
- Is there API versioning, and is it applied consistently?

### 4. Database Design
- Review every table, column, index, and constraint
- Are there missing indexes that would hurt query performance?
- Are there unnecessary indexes adding write overhead?
- Are foreign keys and cascades set up correctly?
- Is the use of JSONB justified where it appears, or should it be normalized?
- Are CHECK constraints appropriate and complete?
- Are there any potential data integrity issues (e.g., orphaned records, race conditions on writes)?
- Is PostGIS being used effectively — are spatial indexes present where needed?

### 5. Async Architecture
- Is the Celery task design sound?
- Are tasks idempotent (safe to retry)?
- Is error handling in tasks robust — does one source failure block others?
- Is the job status tracking (timeline_requests, timeline_request_tasks) working correctly?
- Are there any race conditions in the task pipeline?
- Is Redis being used appropriately for caching vs task brokering?

### 6. Configuration & Environment
- Are all secrets/credentials properly externalized (not hardcoded)?
- Is the pydantic-settings config comprehensive?
- Are there any config values that should be configurable but aren't?
- Does the Docker Compose setup work as documented?
- Are there dev vs prod configuration differences that could cause surprises?

### 7. External API Integration
- Are HTTP clients configured with appropriate timeouts?
- Is there retry logic with backoff for transient failures?
- Are external API responses validated before use?
- Are rate limits respected?
- Is there proper error handling when external services are down?
- Is SAS token / URL signing handled correctly and efficiently?

## Output Format

For each area, provide:
1. **What's done well** — things that demonstrate senior-level thinking
2. **Issues** — concrete problems with file paths and line numbers
3. **Recommendations** — specific changes, ordered by severity (critical → nice-to-have)

Don't soften the feedback. If something is bad, say it's bad and say why. If something looks junior-level, flag it — that's exactly what an interviewer would notice. If everything in a section looks solid, say so briefly and move on.
