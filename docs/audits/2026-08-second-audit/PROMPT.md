# Second Architecture Audit — Prompt

*Issued 2026-07/08 (inferred from remediation commits). Run in Claude Code plan
mode against the codebase at approximately 5f5fb42 (2026-07-29). Reproduced
verbatim. Note for readers of the DEVELOPMENT.md analysis: this prompt is
substantially more adversarial than the first audit's — that difference is one
of the four confounds discussed there.*

---

Do a deep, critical code review of this codebase. This is a SECOND review — a prior architecture audit was already completed and all its findings (dependency pinning, Celery timeouts, row locking, thread-safe Redis, constants extraction, error handling, etc.) have been fixed. Do NOT re-report those. I want you to find what the first pass missed.

Default to criticism. I'm a senior engineer using this as a portfolio project, and I want the things a skeptical staff-level interviewer would find on a careful read — not surface-level praise. Skip the "what's done well" sections entirely unless something is genuinely non-obvious and worth calling out as a deliberate strength. Assume every file has a problem in it and your job is to find it. If a file is actually clean, say so in one line and move on. Spend your effort on the problems.

For every issue: give the exact file:line, explain the concrete failure scenario (not "this could be problematic" — describe the actual input or sequence of events that breaks it), rate severity (Critical / High / Medium / Low), and give a specific fix. If you're not sure something is a bug, say so and explain what you'd need to verify — don't pad the report with hypotheticals you don't believe.

Go deep on these dimensions:

## Correctness & edge cases
- Off-by-one errors, boundary conditions, empty-collection handling
- What happens with null/None at each layer boundary? Trace the actual paths.
- Timezone handling — are naive and aware datetimes ever mixed? Are dates compared across timezones? Census/imagery capture dates vs UTC task timestamps.
- Float precision in coordinate math, bbox calculations, the UTM zone logic, area buffers
- String handling in the address normalizer — unicode, empty strings, addresses that normalize to nothing, addresses with no street number
- What happens when an external API returns a 200 with an empty body, malformed JSON, or a partial response?

## Concurrency & race conditions (beyond the row-lock fix)
- The backfill detection logic — can two concurrent requests for the same parcel both decide to re-fetch and stomp each other?
- Redis cache races — check-then-act patterns on the tile cache, SAS token cache, STAC item cache. Can two requests both miss, both fetch, both write?
- Is there any shared mutable state in the FastAPI app that isn't request-scoped?
- Celery: if the same parcel gets two timeline requests dispatched close together, what actually happens to the imagery_snapshots and the two timeline_request rows?
- asyncio.gather with shared session objects — verify each coroutine truly has its own DB session and they're never accidentally shared

## Resource lifecycle & leaks
- Every httpx client, DB session, Redis connection, file handle — is it always closed, including on the exception path? Look for missing async-with, missing finally, early returns that skip cleanup.
- The module-level singleton httpx clients — are they ever closed on shutdown? Is there a lifespan handler? What happens to in-flight connections on SIGTERM during a Fly deploy?
- Connection pool sizing — are the httpx clients and the SQLAlchemy engine pool sized sensibly for the worker concurrency, or can they exhaust under load?
- Any unbounded growth? Lists that accumulate across a long-running task, caches without TTL, etc.

## Failure modes & partial failure
- Trace what the USER sees for every failure path. If census succeeds but imagery fails, what's the final state of the timeline_request and what does the frontend render?
- Is partial data ever presented as if it's complete? Can a timeline show "complete" when a source silently returned zero results vs actually failed?
- Idempotency under retry: when the Celery task retries after a partial completion, does it correctly skip already-fetched data, or does it redo work / create inconsistency?
- The SoftTimeLimitExceeded handler — does it actually leave the system in a clean state, or can it fire mid-write and leave a half-updated request?
- What happens if the worker is killed between writing imagery_snapshots and updating timeline_request status?

## Data integrity
- Can orphaned or inconsistent rows ever exist? (e.g., timeline_request_tasks without a parent, snapshots for a deleted parcel if CASCADE misfires)
- Are there any writes that should be in a transaction but aren't, allowing partial writes?
- The upserts — are the ON CONFLICT targets actually correct for every real-world duplicate scenario, or are there dup paths the constraints don't cover?
- Numeric overflow — sale_price, valuation, population as integers. Any chance of values exceeding int range or negative values sneaking in?

## Security (deeper than headers)
- SQL injection — any raw SQL or string-interpolated queries anywhere, including in the Socrata $where clause construction (that one builds query strings from address parts — scrutinize it hard)
- SSRF — the tile proxy takes a COG URL and fetches it. Can a user influence that URL to make the server fetch arbitrary internal endpoints? Is there any validation that the URL points to an expected host?
- Are the Planetary Computer / Census / Socrata responses ever trusted in a way that's exploitable (e.g., a URL from an API response used unsanitized)?
- Input validation gaps — the geocode endpoint, the query params. Can oversized input, deeply nested input, or pathological regex input (ReDoS in the address normalizer) cause problems?
- Information disclosure in error responses — does any 500 leak a stack trace, query, or internal path to the client?
- Rate limiting — is there any? What stops someone from hammering the geocode endpoint and running up your Census API usage or Fly bill?

## Performance & efficiency
- N+1 query patterns — anywhere a loop issues a query per iteration that could be a single query
- Missing pagination — any endpoint that returns an unbounded list?
- Are the spatial queries actually using the GIST indexes, or are there queries that force a sequential scan? Look for functions wrapping indexed columns.
- Redundant external API calls — anywhere the same thing is fetched twice that could be fetched once
- Frontend: unnecessary re-renders, missing memoization on expensive components, the map layer switching — does it leak map sources/layers on repeated selection?
- Are large payloads (the JSONB raw_data) being loaded and serialized when they don't need to be?

## Test quality (not coverage — quality)
- Are the tests actually asserting meaningful behavior, or do they just assert status codes and that something didn't throw?
- Are there tests that would still pass if the function body were deleted or returned a constant?
- Is mocking hiding real bugs? (e.g., mocks that return perfectly-shaped data the real API would never return)
- Are edge cases and error paths tested, or only happy paths?
- Are there tests coupled to implementation details that would break on a harmless refactor?
- What critical behavior has NO test at all? (Be specific about the highest-risk untested paths.)

## Maintainability & subtle smells
- Functions doing too much / unclear single responsibility
- Implicit coupling between modules — changing one thing silently requires changing another
- Magic numbers and magic strings that should be named constants
- Inconsistent error handling patterns across similar code
- Anything that's clever in a way that will confuse the next reader (or you in six months)
- Abstractions that don't earn their keep, or missing abstractions where the same pattern is hand-rolled repeatedly

## Output
Organize by severity, Critical first. Within each issue: file:line, the concrete breaking scenario, severity, and the specific fix. At the very end, give me a short honest paragraph: if you were interviewing me and had read this code, what's the ONE thing you'd push hardest on? Don't soften it.

Be thorough and take your time. I would genuinely rather you find 30 real issues than tell me it looks good.
