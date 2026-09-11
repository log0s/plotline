# MCP v1 pre-flight — verification report

**Date:** 2026-09-11
**HEAD at time of writing:** `14dec9c`
**Mode:** report only. No code, dependency, migration or production write was
made. Production was read through `fly ssh console -a log0s-plotline-api
--machine 48e0de9a713918 -C`, `SELECT` only, every statement inside a
transaction opened with `BEGIN READ ONLY`.

The `mcp` 2.2.0 **sdist was downloaded to the session scratchpad and read**;
nothing was installed into any environment, and `backend/pyproject.toml` and
`backend/uv.lock` are untouched. SDK citations below are `file:line` into
`mcp-2.2.0/src/…` as published on PyPI.

---

## 1. SDK — **confirmed, with two constraints the build must carry**

### Version and Python floor

| Fact | Value | Evidence |
|---|---|---|
| Current stable | `mcp` **2.2.0** | `https://pypi.org/pypi/mcp/json` → `info.version` |
| Python floor | **`>=3.10`** | same, `info.requires_python` |
| Our floor | `>=3.12` | `backend/pyproject.toml:9`, `backend/uv.lock:3` |

**Verdict: compatible.** Our floor is stricter than the SDK's, so nothing
about Python versions blocks adoption.

### Dependency weight — the one genuine cost

`mcp==2.2.0` declares (from `info.requires_dist`):

```
anyio>=4.9 (>=4.10 on py3.14)   httpx2>=2.5.0        jsonschema>=4.20.0
mcp-types==2.2.0               opentelemetry-api>=1.28.0
pydantic>=2.12.0               pyjwt[crypto]>=2.10.1  python-multipart>=0.0.9
sse-starlette>=3.0.0           starlette>=0.27       typing-extensions>=4.13.0
typing-inspection>=0.4.1       uvicorn>=0.31.1
```

Checked against `backend/uv.lock` at HEAD:

| Dependency | Status | Our locked version |
|---|---|---|
| `anyio` | present, satisfies | 4.13.0 (`uv.lock:54-55`) |
| `pydantic` | present, satisfies | 2.13.4 (`uv.lock:1031-1032`) |
| `starlette` | present, satisfies | 1.6.0 (`uv.lock:1474-1475`) |
| `uvicorn` | present, satisfies | 0.47.0 (`uv.lock:1585-1586`) |
| `typing-extensions` | present, satisfies | 4.15.0 |
| `typing-inspection` | present, satisfies | 0.4.2 |
| `httpx2` | **new** | — |
| `jsonschema` | **new** | — |
| `mcp-types` | **new** (pinned `==2.2.0`) | — |
| `opentelemetry-api` | **new** | — |
| `pyjwt[crypto]` | **new** | — |
| `python-multipart` | **new** | — |
| `sse-starlette` | **new** | — |

**`httpx2` is not a typo and not our `httpx`.** It is httpx 2.x republished
under a new distribution name — version `2.12.0`, importing as `httpx2`,
pulling `httpcore2`, `truststore` and `idna>=3.18`
(`https://pypi.org/pypi/httpx2/json`). Our own code pins `httpx>=0.27.0`
(`pyproject.toml:23`, locked at 0.28.1, `uv.lock:537-538`). The two
distributions install side by side and do not conflict, but the API image will
carry **two HTTP client stacks**. `pyjwt[crypto]` additionally pulls
`cryptography`, and `jsonschema` pulls `referencing`/`rpds-py`/`attrs`.

**Changes for the build:** the `uv.lock` regeneration is not cosmetic. Expect
~15 new locked packages for a server with no auth and no client. Per
`CLAUDE.md` the lockfile ships in the same commit as the `pyproject.toml`
edit, and `uv sync --locked` must pass before results are reported.

### (a) Stateless streamable HTTP on 2026-07-28, dual-era — **confirmed**

The SDK speaks two eras and routes between them on the wire, with no option to
select one:

```python
HANDSHAKE_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MODERN_PROTOCOL_VERSIONS    = ("2026-07-28",)
```
`mcp-types/mcp_types/version.py:33-42`

Routing, verbatim from `mcp/server/streamable_http_manager.py:191-200`:

```python
header = MCP_PROTOCOL_VERSION_HEADER.encode("ascii")
pv = next((v.decode("latin-1") for k, v in scope["headers"] if k == header), None)
if pv is not None and pv not in HANDSHAKE_PROTOCOL_VERSIONS:
    await handle_modern_request(...)
    return
if self.stateless:
    await self._handle_stateless_request(pv, scope, receive, send)
else:
    await self._handle_stateful_request(scope, receive, send)
```

A 2026-07-28 client (which sends `MCP-Protocol-Version: 2026-07-28`) takes the
modern leg. A pre-2026 client's `initialize` arrives with a handshake version
or with **no header at all** (`pv is None`), and takes the legacy leg. Both are
served by the same ASGI app.

The **exact constructor options** are on `streamable_http_app()`, not on
`MCPServer(...)` (`mcp/server/mcpserver/server.py:1279-1291`):

```python
def streamable_http_app(
    self,
    *,
    streamable_http_path: str = "/mcp",
    json_response: bool = False,
    stateless_http: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE,   # 4 MiB
    session_idle_timeout: float | None = DEFAULT_SESSION_IDLE_TIMEOUT,
    max_sessions: int | None = DEFAULT_MAX_SESSIONS,
    transport_security: TransportSecuritySettings | None = None,
    host: str = "127.0.0.1",
) -> Starlette:
```

`MCPServer.__init__` (`server.py:157-186`) takes only identity and behaviour
(`name`, `title`, `description`, `instructions`, `version`, `icons`,
`website_url`, `lifespan`, `auth`, `middleware`, `log_level`, `debug`); it
takes no transport options at all.

`stateless_http=True` **only affects the legacy leg** — the version header is
read before `self.stateless` is consulted, so the modern path never sees it.
The modern path is unconditionally stateless: `handle_modern_request` builds a
fresh `Connection.from_envelope(...)` per POST and "Never sets
`Mcp-Session-Id`" (`mcp/server/_streamable_http_modern.py:365-380`,
`mcp/server/connection.py:258-297`). Set it anyway — it is what makes the
legacy leg stateless too.

### ⚠️ (a-bis) The `host` default will 421 every production request

`streamable_http_app`'s `host` defaults to `"127.0.0.1"`, and
`mcp/server/lowlevel/server.py:739-745` reads:

```python
if transport_security is None and host in ("127.0.0.1", "localhost", "::1"):
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
```

`TransportSecurityMiddleware.validate_request` then returns
`Response("Invalid Host header", status_code=421)` for any other `Host`
(`mcp/server/transport_security.py:98-123`), and this runs on the modern leg
too (`_streamable_http_modern.py:383-386`). A default-constructed
`streamable_http_app()` mounted on the Fly app therefore answers **421** to
every request carrying `Host: log0s-plotline-api.fly.dev`, and works perfectly
in local development — the worst possible failure shape.

**Changes for the build:** pass either the real public host, or an explicit
`transport_security=TransportSecuritySettings(...)` naming the allowed hosts.
A test that asserts a non-localhost `Host` header gets 200, not 421, is
cheap and is exactly the test local development cannot fail.

### (b) Mounting into the existing FastAPI app — **confirmed, with a hard requirement**

`streamable_http_app()` returns a `Starlette` instance, mountable with
`app.mount(...)` / `Mount(...)`. **The host app's lifespan must enter the
session manager**, because a mounted sub-application's own lifespan never
runs:

```python
@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield
```
(`mcp/server/streamable_http_manager.py:130-146`, docstring verbatim)

This is not optional and is **not** limited to the legacy leg:
`_handle_request` raises `RuntimeError("Task group is not initialized. Make
sure to use run().")` before the era-routing branch
(`streamable_http_manager.py:184-189`), and `handle_modern_request` is handed
`self._lifespan_state`, which is only populated inside `run()`
(`streamable_http_manager.py:155-160`).

Two ordering constraints follow:

1. `mcp.session_manager` raises `RuntimeError` if read before
   `streamable_http_app()` has been called — the manager is created lazily
   inside it (`mcp/server/mcpserver/server.py:310-319`,
   `lowlevel/server.py:677-690`, `:748-752`). So `streamable_http_app()` must
   be called during `create_app()`, and `session_manager.run()` entered in the
   lifespan that `create_app()` already installs (`backend/app/main.py:26-49`).
2. `run()` can only be entered **once per instance**
   (`streamable_http_manager.py:148-155`). The existing lifespan is a single
   `asynccontextmanager` so this is satisfied, but a test suite that builds
   several apps from one module-level `MCPServer` will trip it.

To mount at `/mcp` rather than `/mcp/mcp`:
`Mount("/mcp", app=mcp.streamable_http_app(streamable_http_path="/"))`.

### (c) JSON response (non-SSE) — **confirmed**

`json_response: bool = False` on `streamable_http_app()`. On the modern leg it
short-circuits the SSE stream for every method except `subscriptions/listen`
(`_streamable_http_modern.py:455`); on the legacy leg it reaches
`StreamableHTTPServerTransport(is_json_response_enabled=…)`
(`streamable_http_manager.py:214`, `:314`). Note the `Accept` check at
`_streamable_http_modern.py:395-398`: with `json_response=True` a client
sending only `Accept: application/json` is served; without it, a client that
does not also accept `text/event-stream` gets **406**.

### (d) Per-request `clientInfo` on 2026-07-28 — **confirmed**

It rides in `params._meta` under a reserved key:

```python
PROTOCOL_VERSION_META_KEY   = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY        = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY= "io.modelcontextprotocol/clientCapabilities"
```
`mcp-types/mcp_types/_types.py:53-62`

Protocol version and client capabilities are **required** envelope keys;
**client info is optional** and a mis-shaped value degrades to not-supplied
rather than failing the request (`mcp/shared/inbound.py:435-446`,
`mcp/server/connection.py:270-297`).

From inside a tool handler the readable path is:

* `ctx.protocol_version` → `str | None` (`mcpserver/context.py:296-299`)
* `ctx.client_capabilities` → `ClientCapabilities | None` (`:318-326`)
* `ctx.session.client_params.client_info` → `Implementation | None`
  (`mcpserver/context.py:328-331` → `mcp/server/session.py:65-67` →
  `mcp/server/connection.py:242-246`)
* `ctx.headers` → request headers, or `None` on stdio (`:281-289`)

**Changes for the build:** the structured-log field for "who called" is
`ctx.session.client_params.client_info` and it is **nullable on the modern
era** — the logging call must treat absence as normal, not as an anomaly.
`ctx.request_id` (`:291-294`) is the per-request correlation id.

### (e) Typed returns, annotations, prompts — **confirmed**

* **Structured output.** The return type annotation *is* the output schema; it
  is published as `output_schema` in `tools/list`, and every result is
  validated against it before it leaves the server. Pydantic `BaseModel`,
  `TypedDict` and `@dataclass` all produce an object schema; a scalar return
  is wrapped as `{"result": …}`. Override with `structured_output: bool | None`
  on the decorator (`None` = auto-detect from the annotation).
  (`py.sdk.modelcontextprotocol.io/servers/structured-output/`;
  `mcpserver/server.py` `tool()` docstring.)
* **Annotations.** `@mcp.tool(annotations=ToolAnnotations(...))`. Field names
  are **snake_case in Python, camelCase on the wire**:
  `read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`,
  `title` (`mcp-types/mcp_types/_types.py:1365-1410`). All are `bool | None`
  and all are explicitly hints, not enforcement.
* **Tool decorator, full signature** (`mcpserver/server.py`, `def tool(`):
  `name`, `title`, `description`, `annotations`, `icons`, `meta`,
  `structured_output`.
* **Prompts.** `@mcp.prompt(name=…, title=…, description=…, icons=…)`;
  arguments and their `required` flags are derived from the function
  signature, the docstring becomes the description
  (`mcpserver/server.py` `def prompt(` at :959).

**Changes for the build:** the five tools carry
`ToolAnnotations(read_only_hint=True, idempotent_hint=True,
open_world_hint=False)` — `open_world_hint=False` is correct because every
tool reads our own database and `lookup_parcel` deliberately does **not**
reach the geocoder for unindexed addresses (check 2). Return Pydantic models,
which the project already requires for every API schema, and the output
schemas come free.

---

## 2. Write side effects on the read paths — **confirmed; the safe set is small and clean**

### Every `maybe_refetch_for_backfill` call site

| Call site | Route | Reachable by MCP? |
|---|---|---|
| `backend/app/api/v1/geocode.py:292` | `POST /api/v1/geocode` | **No — must not be called** |
| `backend/app/api/v1/imagery.py:96` | `POST /api/v1/parcels/{parcel_id}/timeline` | **No — must not be called** |

Those are the only two in application code (`backend/app/services/imagery.py:573`
is the definition). The remaining matches are tests
(`backend/tests/test_imagery.py`, `test_admission.py`, `test_geocode.py`) and
prose in `scripts/requeue_parcels.py:15`, `scripts/ledger_gaps.py:43`,
`backend/app/services/ledger.py:7`.

### Functions the MCP tools **must not** call

| Function | Write |
|---|---|
| `services/parcels.get_or_create_parcel` (`parcels.py:81`) | inserts a `parcels` row (`:155-156`); also commits a census-metadata backfill onto an existing parcel (`:125`); calls `ensure_admission` (`:139`) |
| `services/imagery._create_queued_request` (`imagery.py:244`) | inserts `timeline_requests`, calls `ensure_admission` |
| `services/imagery.get_or_create_timeline_request` (`imagery.py:343`) | reaches `_create_queued_request`; **also writes on the read-looking path** — a stale in-flight request is marked `failed` via `update_timeline_request_status` (`:352-358`) |
| `services/imagery.create_queued_request_waiting` (`imagery.py:297`) | same, plus blocks waiting for an admission slot |
| `services/imagery.maybe_refetch_for_backfill` (`imagery.py:573`) | inserts a scoped or full-scope `timeline_requests` row |
| `services/imagery.dispatch_timeline_task` (`imagery.py:380`) | enqueues a Celery job; marks the request `failed` if the broker is down |
| `services/imagery.update_timeline_request_status` (`imagery.py:516`) | commits a status change |
| `services/imagery.sweep_stranded_work` (`imagery.py:828`) | worker-side sweep |
| `services/imagery.reconcile_source_snapshots` (`imagery.py:1457`) | worker-side write of `scenes`/`parcel_scenes` |
| `services/demographics.upsert_census_snapshot` (`demographics.py:46`) | commits (`:139`) — worker only today |
| `services/property_events.upsert_property_event` (`property_events.py:43`) | commits (`:94`) — worker only today |
| `services/year_ledger` writers (`year_ledger.py:204`, `:305`) | worker only today |
| `services/geocoder.remember_served_coordinates` (`geocoder.py:88`) | writes Redis; reached from `GET /geocode/autocomplete` (`geocode.py:154`) |

### Functions the MCP tools **may safely call** (pure reads, verified)

| Tool | Function | Site |
|---|---|---|
| `lookup_parcel` | `services.parcels.find_nearby_parcel` | `parcels.py:45` — one `SELECT`, no commit, no admission gate |
| `lookup_parcel` | `db.query(Parcel).filter(Parcel.id == …)` | as `api/v1/parcels.py:33` |
| `get_imagery_years` | `services.imagery.get_served_scenes` | `imagery.py:1806` |
| `get_imagery_years` | `services.imagery.get_served_scene_by_id` / `count_served_scenes` / `served_scene_bounds` | `imagery.py:1845`, `:1859`, `:1876` |
| `get_property_history` | `services.property_events.get_property_events` | `property_events.py:111` |
| `get_property_history` | `services.property_events.compute_price_summary` | `property_events.py:183` — pure function |
| `get_demographics` | `services.demographics.get_census_snapshots` | `demographics.py:155` |
| `get_demographics` | `services.demographics.compute_subtitles` | `demographics.py:249` — pure function |
| `describe_coverage` | `services.county_adapters.get_adapter_for_county` / `get_supported_county_display_names` | `county_adapters.py:981`, `:992` |
| any | `services.imagery.get_timeline_request` | `imagery.py:407` — pure read |

**The existing read routers are already write-free.** `grep` for
`db.commit()` / `db.add(` over `backend/app/api/v1/` returns nothing, and
`GET /parcels/{id}/demographics` and `GET /parcels/{id}/events` call only the
read functions above.

**The trap to name in the build prompt:** `get_or_create_timeline_request`
*looks* like a read and is not; and a v1 tool calling
`api/v1/imagery.py:list_imagery`'s service path is fine, but that route's own
handler additionally signs Planetary Computer URLs
(`api/v1/imagery.py:233-240`), which is an outbound network fan-out with its
own rate budget. `get_imagery_years` should return years and metadata and
**not** signed COG URLs.

### How a new address enters the pipeline today

| | |
|---|---|
| Route | `POST /api/v1/geocode` (`backend/app/api/v1/geocode.py:173-332`) |
| Rate limit | `RateLimit(times=10, seconds=60, fail_closed=True)` — `geocode.py:190` |
| Second door | `POST /api/v1/parcels/{parcel_id}/timeline`, `RateLimit(times=20, seconds=60, fail_closed=True)` — `api/v1/imagery.py:65`. Existing parcels only; 404s on an unknown id. |
| Autocomplete | `GET /api/v1/geocode/autocomplete`, `RateLimit(times=60, seconds=60)`, fail-open — `geocode.py:46` |
| Global gate | `ensure_admission` — kill switch `accept_new_parcels` (default `True`), cap `max_inflight_timeline_requests=30`, `user_admission_reserve=5` (`backend/app/config.py:87-99`, `backend/app/services/admission.py`) |

**Changes for the build:** `lookup_parcel` on an unindexed address returns
`not_indexed` plus a deep link and calls **none** of the above. The deep link
is the only thing that can create a parcel, and it does so through the
browser, under the existing per-IP limit and the existing admission gate —
which is exactly why the design is right. The MCP endpoint adds no new door
into the pipeline and therefore needs no new admission accounting.

---

## 3. Slider URL-state — **partially confirmed: the parcel is addressable, year and source are not**

### What opens a parcel

`frontend/src/router.tsx:9-20`:

```
/                      → LandingPage
/explore/:parcelId     → ExplorePage
/featured/:slug        → FeaturedRedirectPage   (redirects to /explore/:parcelId)
*                      → NotFoundPage
```

So a deep link is `https://plotline.land/explore/<parcel uuid>`.
`/featured/:slug` 302s to the same shape (`FeaturedRedirectPage.tsx`,
`<Navigate to={`/explore/${data.parcel_id}`} replace />`).

### What is URL-addressable inside the page

**One query parameter exists: `?snap=<snapshot uuid>`.**

* Applied once on load, only if it matches a loaded snapshot
  (`ExplorePage.tsx:120-131`).
* Written on explicit user selection only, with `{ replace: true }`
  (`ExplorePage.tsx:133-148`). Auto-select and deep-link application
  deliberately do not write it.
* If `?snap=` is present, auto-select is skipped (`ExplorePage.tsx:112`).

**Year and source are not URL-addressable.** `selectedYear` is *derived* from
the selected snapshot in the store (`frontend/src/store.ts:19-25`,
`parseInt(selectedSnapshot.capture_date.slice(0, 4), 10)`) and never read from
or written to the URL. `source` exists only as a field on the snapshot.
`compareMode` and `compareSnapshots` are store-only too.

**Consequence for MCP v1:** a tool can link to *a parcel*, and can link to *a
specific snapshot* if it knows the snapshot UUID — which `get_imagery_years`
would have to return for the link to be constructible. It cannot say "1955,
topo" in a URL.

### Smallest frontend change that would make year + source addressable (shape only)

Three edits, no new dependency, no new route:

1. **Read.** Extend the existing one-shot deep-link effect
   (`ExplorePage.tsx:120-131`) to resolve, in order: `?snap=<uuid>` exactly as
   today; else `?year=<yyyy>` (+ optional `?source=<naip|landsat|sentinel2|usgs_topo>`)
   by picking from `snapshots` the entry whose `capture_date` year matches,
   preferring the named source, then NAIP, then most recent. No match → fall
   through to today's auto-select rather than erroring.
2. **Write.** In `handleSnapshotSelect` (`ExplorePage.tsx:133-148`), set
   `year` and `source` alongside `snap` (or instead of it — see the decision
   list), keeping `{ replace: true }`.
3. **Nothing in the store changes.** `selectedYear` is already derived; the
   URL becomes a second input to the same one-shot resolver, not a second
   source of truth.

A `?year=` link is stable across a re-fetch that changes snapshot UUIDs;
`?snap=` is not. That is the argument for making `year`+`source` the canonical
MCP-emitted form.

---

## 4. Data sizing (production, read-only) — **confirmed; the ADR 0002 number is ~8.8k tokens**

Method: `fly ssh console -a log0s-plotline-api --machine 48e0de9a713918 -C
"sh -c 'echo <b64> | base64 -d | python -'"`, two scripts, 2026-09-11. The DSN
came from `app.config.get_settings().database_url`, not `os.environ` — the raw
env value carries the `postgresql+asyncpg://…?ssl=` shape that `config.py:128-141`
normalizes and psycopg2 rejects unnormalized.

**Read-only proof, inside the same transaction it proves:**

```
BEGIN READ ONLY;
UPDATE parcels SET address = address WHERE false;
-- → cannot execute UPDATE in a read-only transaction
ROLLBACK;
```

`current_setting('transaction_read_only')` read `on` inside the reporting
transaction. No session-level `SET` was issued anywhere (NORM-30).

### Queries, verbatim

Distribution, run once per `T` in `{parcel_scenes, census_snapshots, property_events}`:

```sql
SELECT count(*)                                        AS parcels_with_rows,
       sum(c)                                          AS total_rows,
       max(c)                                          AS max_rows,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY c) AS p95_rows,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY c) AS median_rows
FROM (SELECT parcel_id, count(*) AS c FROM T GROUP BY parcel_id) s;

SELECT parcel_id, count(*) AS c FROM T GROUP BY parcel_id ORDER BY c DESC, parcel_id LIMIT 3;
```

Raw-row JSON size:

```sql
SELECT length(coalesce(json_agg(to_jsonb(t))::text, '[]'))
FROM (SELECT * FROM T WHERE parcel_id = %s) t;
```

API-shaped JSON size (the fields the existing response schemas actually serve
— `raw_data` excluded):

```sql
-- property events (PropertyEventResponse)
SELECT length(coalesce(json_agg(to_jsonb(t))::text, '[]')), count(*)
FROM (SELECT id, event_type, event_date, description, sale_price, permit_type,
             permit_description, permit_valuation, source
      FROM property_events WHERE parcel_id = %s ORDER BY event_date) t;

-- census snapshots (CensusSnapshotResponse)
SELECT length(coalesce(json_agg(to_jsonb(t))::text, '[]')), count(*)
FROM (SELECT year, dataset, tract_fips, total_population, median_household_income,
             median_home_value, median_year_built, total_housing_units,
             occupied_housing_units, owner_occupied_units, renter_occupied_units,
             vacancy_rate, median_age, median_gross_rent
      FROM census_snapshots WHERE parcel_id = %s ORDER BY year) t;

-- imagery "years" shape
SELECT length(coalesce(json_agg(to_jsonb(t))::text, '[]')), count(*)
FROM (SELECT ps.source, ps.group_key, sc.capture_date, sc.resolution_m,
             sc.cloud_cover_pct, sc.platform
      FROM parcel_scenes ps JOIN scenes sc ON sc.id = ps.scene_id
      WHERE ps.parcel_id = %s ORDER BY sc.capture_date) t;
```

### Results — row counts (196 parcels)

| Table | Parcels with rows | Total rows | Max/parcel | p95 | Median | Max held by |
|---|---|---|---|---|---|---|
| `parcel_scenes` | 196 | 13,347 | **75** | 72.0 | 68.0 | `1445b762-5611-4698-8c64-e3ac20fff658` |
| `census_snapshots` | 196 | 1,635 | **9** | 9.0 | 9.0 | `099336a2-1680-4500-843b-06c2b208ec30` (9 parcels tie) |
| `property_events` | **20** | 383 | **69** | 64.25 | 10.5 | `dc493cc5-1b6e-4cad-b311-11b4418947c9` (1300 4th St SE, Washington DC) |

Max distinct imagery **years** on one parcel: **52**.
Note the p95 basis: it is over parcels that have ≥1 row in that table. For
`property_events` that is 20 of 196 parcels, so its p95 describes the covered
minority, not the fleet.

### Results — JSON size

**Raw rows, every column including `raw_data`:**

| Table | Parcel | Rows | Chars | ~Tokens (chars/4) |
|---|---|---|---|---|
| `parcel_scenes` | `1445b762…` | 75 | 22,299 | 5,574 |
| `parcel_scenes` joined to `scenes`, geometry excluded | `1445b762…` | 75 | 57,632 | 14,408 |
| `census_snapshots` | `099336a2…` | 9 | 7,231 | 1,807 |
| `property_events` | `dc493cc5…` | 69 | 103,743 | **25,935** |
| Sum of the three maxima (different parcels) | — | — | 133,273 | 33,318 |
| Worst *single* parcel, all three raw | `64a47cd8…` (2 Broadway, NY) | 145 | 139,709 | **34,927** |

**API-shaped — what an MCP tool would actually return:**

| Parcel | events | census | years | TOTAL chars | ~Tokens |
|---|---|---|---|---|---|
| `dc493cc5…` 1300 4th St SE, DC | 22,458 (69 rows) | 2,976 (8) | 9,947 (72) | **35,381** | **8,845** |
| `64a47cd8…` 2 Broadway, NY | 19,138 (64) | 3,341 (9) | 9,959 (72) | 32,438 | 8,109 |
| `1445b762…` (imagery max) | 2 (0) | 3,342 (9) | 10,362 (75) | 13,706 | 3,426 |

**The number to cite in ADR 0002: the entire history of the single largest
parcel in production — every imagery year, every census year, every property
event — serializes to ~35 KB, ≈8.8k tokens, in the shape the API already
serves.** The raw-row figure is 4× that, and the whole difference is
`census_snapshots.raw_data` and `property_events.raw_data` (`models/parcels.py:546`,
`:626`), which no response schema exposes and no MCP tool should.

**Changes for the build:**

* The fleet is 196 parcels. Whole-corpus retrieval is not a scaling question
  yet; the ADR's argument is that the *unit* — one parcel — fits in a prompt,
  and it does with an order of magnitude to spare.
* `get_property_history` is the only tool that can get large, and it is large
  on 20 of 196 parcels. Give it a `limit` and a date filter mirroring
  `GET /parcels/{id}/events` (`api/v1/events.py:38-40`); do not paginate the
  other tools.
* Never select `raw_data`. Explicit column lists, not `SELECT *`.

---

## 5. Adapter coverage — **confirmed, with one premise of the prompt falsified**

### How "no adapter for this county" is represented today

`backend/app/tasks/timeline.py:1295-1313`: no adapter → task status
`skipped`, `coverage='no_adapter'`, `queries_run=0`, `queries_failed=0`,
`items_found` cleared, message `"Property data not yet available for {county}
County"`.

`backend/app/tasks/timeline.py:1322-1344`: adapter exists but `covers(city)`
is false → also `skipped`, `coverage='not_covered'`, with a city-specific
message. The two are deliberately the same status distinguished by `coverage`.

`coverage` is constrained to `('covered', 'not_covered', 'no_adapter')` or
NULL (`backend/app/models/parcels.py:221`, `:279`).

**Production state, read 2026-09-11** (`timeline_request_tasks` grouped by
source/status/coverage):

```
property  complete  (null)        171
property  complete  covered        27
property  failed    (null)          1
property  skipped   (null)        670
property  skipped   no_adapter       6
property  skipped   not_covered      6
```

The 670 + 171 NULL rows predate migration 0014 and are exactly what STATUS.md
AA5 and AA6 describe. **A `describe_coverage` tool must derive coverage from
the adapter registry, not from `timeline_request_tasks.coverage`** — the
column is right only on rows written since 0014 deployed.

### `covers(city)` at HEAD — **confirmed present**

| | |
|---|---|
| Base, default `True` | `county_adapters.py:175-188` |
| Adams override (DENYlist) | `county_adapters.py:374-378` |
| Santa Clara override (ALLOWlist) | `county_adapters.py:638-642` |
| Denver / DC / New York | inherit the default — no boundary below the county |
| Only production caller | `backend/app/tasks/timeline.py:1322` |

A `None` city never denies, at every level (`:184-188`). The city is parsed
from `normalized_address` by `city_from_address`
(`backend/app/services/address_normalizer.py:109-140`) — STATUS.md AA2's
accepted mailing-city-vs-jurisdiction risk.

### What each adapter states about its own coverage

| Adapter | Sales | Permits | Jurisdiction | Time extent as stated in code |
|---|---|---|---|---|
| `DenverAdapter` (`:216`) | **none** — `fetch_sales()` permanent stub | 2 ArcGIS layers, 100 rows each, `DATE_ISSUED DESC` | county-wide (city-county) | **not stated anywhere** |
| `AdamsCountyAdapter` (`:310`) | **none** — permanent stub | 1 ArcGIS layer, 100 rows, `CaseOpened DESC` | **unincorporated only**; 7-city denylist (`:359-369`) | **not stated anywhere** |
| `DCAdapter` (`:450`) | last sale **only**, 20 rows | 7 year-specific layers, 50 rows each | county-wide | **2020–2026**, implicit in `PERMIT_LAYERS` (`:467-476`) |
| `SantaClaraAdapter` (`:606`) | **none** — permanent stub | 3 CKAN resources, 100 rows each, **unordered** | **City of San Jose only** (`COVERED_CITIES`, `:632`) | **not stated anywhere** |
| `NewYorkCountyAdapter` (`:745`) | annualized + rolling, 200 rows | DOB permits, 100 rows | **Manhattan / borough 1 only** | sales **2016+** (docstring `:747-752`) |

**Falsified premise:** the prompt's "Adams … and post-2011". **No 2011 claim
exists anywhere at HEAD** — not in `county_adapters.py`, not in
`SUPPORTED_COUNTIES.md`, not in any docstring (`grep -rn 2011` over both is
empty). The Adams adapter states unincorporated-only and nothing about a start
year. If a 2011 floor is real it is an unrecorded observation, and
`describe_coverage` must not assert it.

**Second finding:** the richest coverage statements in the repo —
`SUPPORTED_COUNTIES.md`'s row caps, date extents, field lists and
"Known coverage gaps" — live in a markdown file **last verified 2026-08-03**
that no code can read. `describe_coverage` built from the registry today can
report jurisdiction and which of sales/permits exist; it cannot report time
extent without new declarations.

### Smallest per-adapter coverage descriptor

One frozen dataclass and one property on the base class, both in
`county_adapters.py`, next to the `covers()` it complements:

```python
@dataclass(frozen=True)
class AdapterCoverage:
    """What this adapter can and cannot answer for. Serves describe_coverage."""
    jurisdiction: str                  # "unincorporated Adams County only"
    has_sales: bool
    has_permits: bool
    earliest_year: int | None = None   # None = not established; never guess
    caveat: str | None = None          # one sentence, user-facing
```

```python
class CountyAdapter(ABC):
    @property
    @abstractmethod
    def coverage(self) -> AdapterCoverage: ...
```

Abstract, for the same stated reason `display_name` is abstract
(`county_adapters.py:166-173`): a new adapter must not be registrable without
one. `earliest_year=None` is the honest default and is what Denver, Adams and
Santa Clara get today; DC gets `2020` from `PERMIT_LAYERS`, NYC `2016` from
its docstring. `not_covered`'s user-facing message
(`timeline.py:1335-1339`) can then be built from `caveat` instead of being
spelled out at the call site.

That is five new lines per adapter and one new abstract property. Anything
larger (a coverage registry, a per-dataset extent table) is a second source of
truth alongside `SUPPORTED_COUNTIES.md`.

---

## 6. Geocoding path — **confirmed on all three sub-questions**

### (a) Is the address→point path async throughout? — **yes for geocoding; no for autocomplete**

`services/geocoder.geocode_address` (`geocoder.py:187-306`) and
`reverse_geocode` (`:310`) use `httpx.AsyncClient` throughout
(`geocoder.py:215`, `:347`, `:543`). No sync HTTP anywhere on the address→point
path.

The DB work on that path is sync SQLAlchemy but is correctly pushed off the
loop: `api/v1/geocode.py:260-266` and `:321` wrap
`parcels_service.get_or_create_parcel` and the timeline dispatch in
`run_in_threadpool`, and `:218` does the same for the Redis served-coordinate
check.

**M5's autocomplete half is still open at HEAD**, exactly as STATUS.md line
115 records: `GET /geocode/autocomplete` is `async def` and calls the
**synchronous** Redis client directly on the event loop at
`api/v1/geocode.py:57` (read), `:149` (write) and `:155`
(`remember_served_coordinates`). MCP v1 does not touch this route, so it is
not a blocker — but `lookup_parcel` must not be built on top of the
autocomplete handler.

### (b) Point → nearest parcel — **exists, and the index it needs is in production**

`services/parcels.find_nearby_parcel` (`parcels.py:45-78`) is exactly the
query `lookup_parcel(lat, lon)` needs: `ST_DWithin` on the geography cast,
ordered by `ST_Distance`, `LIMIT 1`, **no commit and no admission gate**. It
is currently only called from `get_or_create_parcel` (`parcels.py:103`), but
it is a pure read and is safe to call directly.

The index question is settled empirically. `EXPLAIN` against production of the
`find_nearby_parcel` shape:

```
Limit  (cost=58.30..58.30 rows=1 width=24)
  ->  Sort  (cost=58.30..58.30 rows=1 width=24)
        Sort Key: (st_distance((point)::geography, '…'::geography, true))
        ->  Index Scan using idx_parcels_point_geog on parcels
              Index Cond: ((point)::geography && _st_expand('…'::geography, '50'))
              Filter: st_dwithin((point)::geography, '…'::geography, '50', true)
```

`pg_indexes` on `parcels` (production):

```
idx_parcels_address    gin (to_tsvector('english', address))
idx_parcels_point      gist (point)
idx_parcels_point_geog gist (((point)::geography))
parcels_pkey           btree (id)
```

The geography **expression** index is what the query uses, and the plain
geometry GIST index is not the one that serves it. `idx_parcels_point_geog`
was created by `backend/alembic/versions/0010_review_hardening.py:83`; it is
**absent from `backend/app/models/parcels.py:83-87`**, which declares only
`idx_parcels_point`. That is a new instance of STATUS.md M7's ORM/schema
drift, in the index `lookup_parcel` depends on.

**Nothing needs to be added for point→parcel. Nothing must be removed either
— dropping `idx_parcels_point_geog` on the strength of the ORM would turn
both the dedup path and `lookup_parcel` into sequential scans.**

### (c) Ties and city-level matches — **the refusal has to be built, and the Census geocoder is not where it belongs**

**Ties.** The Census one-line geocoder returns `result.addressMatches` as an
array. `geocoder.py:250-251` raises `AddressNotFoundError` on an empty array
and `:254` then takes `address_matches[0]` **unconditionally** — a
multi-match response is silently resolved to its first entry, and the count
never reaches the caller. `GeocodeResult` (`geocoder.py:175-185`) has no field
for it.

**City-level matches.** The Census forward geocoder does not match a bare
city, so AA4's `Cupertino, California 95014` parcel did not arrive that way.
It arrived through the **autocomplete → reverse-geocode fallback**: Photon
returns city/town nodes, `AutocompleteSuggestion` carries
`place_type=props.get("osm_value", …)` (`api/v1/geocode.py:137`), but
`GeocodeRequest` has no `place_type` field and `POST /geocode` never sees it —
so when forward geocoding fails and the coordinates were served by this
backend, `reverse_geocode` accepts them (`geocode.py:207-236`). The stored row
then has no street line, and `city_from_address` returns `None` for it
(`address_normalizer.py:124-132`), which makes the coverage gate fail open —
STATUS.md AA4 and AA2's P-2, both observed in production.

**Changes for the build:**

1. `lookup_parcel` in v1 **reads the database only**. It does not call the
   Census geocoder, so ties are not its problem — a parcel row either exists
   or the answer is `not_indexed`.
2. What it must refuse is a **stored** row that is not a property. The
   available test at HEAD is structural: `normalized_address` with no street
   component — the same condition `city_from_address` already detects, which
   returns `None` when the second comma component contains digits. Surfacing
   that as `not_a_parcel` rather than as a normal hit is the AA4 decision
   landing in the tool, and it needs Ryan's choice among gate / flag / delete
   before the tool can be written to it.
3. If a later version does geocode, `len(addressMatches) > 1` must become a
   refusal (`ambiguous`, with the candidates), not a silent `[0]`.

---

## 7. Neon read-only role — **confirmed; creation is Ryan's, and one pooler constraint matters**

### How the API's database URL is configured

| Layer | Detail |
|---|---|
| Setting | `Settings.database_url: str = Field(...)` — **required**, no default (`backend/app/config.py:39-42`) |
| Source | environment / `.env`, via `SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")` (`config.py:19-24`). The env var is `DATABASE_URL`. |
| Normalization | `@field_validator("database_url")` (`config.py:128-141`) rewrites `postgresql+asyncpg://` → `postgresql://`, `postgres://` → `postgresql://`, and `?ssl=…` → `?sslmode=require`. **Production's stored value uses the asyncpg scheme and `?ssl=`**, so anything reading `os.environ["DATABASE_URL"]` directly and handing it to psycopg2 fails — confirmed by an actual `psycopg2.ProgrammingError: invalid dsn` during check 4. |
| Engine | one module-level `create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)` at import time (`backend/app/db.py:22-37`), one `SessionLocal`, one `get_db()` dependency (`:40-46`) |
| Deployment | a Fly secret on `log0s-plotline-api` and `plotline-worker`. `fly.toml`'s `[env]` block carries only `APP_ENV`, `TITILER_URL`, `API_INTERNAL_URL` — no database URL. (`fly secrets list` was not run: the command was denied in this session. The secret's existence is evidenced by `config.py`'s required field and the running process.) |
| Endpoint | the value points at a Neon **`-pooler`** host, i.e. Neon's PgBouncer endpoint |

**Adding a second URL is mechanically trivial and touches three places:**
one more `Field` on `Settings` (`mcp_database_url: str | None = None`), a
second engine + sessionmaker in `db.py` alongside the existing pair, and a
`get_mcp_db()` dependency for the MCP tools to `Depends()` on. No existing
call site changes. `config.py`'s validator is a `@field_validator` bound to
the `database_url` field name — the new field needs its own validator, or the
validator needs `@field_validator("database_url", "mcp_database_url")`.
Forgetting that is how the asyncpg scheme reaches psycopg2 again.

### Hand-created or migrated?

**By hand (Ryan), not by migration.** Both facts point the same way:

* Neon's own guidance: roles created through the Console/CLI/API are granted
  `neon_superuser`; *"To create roles with limited privileges, use SQL"* —
  `CREATE ROLE <name> WITH LOGIN PASSWORD '…'`, minimum 60 bits of entropy
  (`neon.com/docs/manage/roles`). A SQL-created role gets only default
  `public` schema privileges, which is the right starting point for a
  read-only role, and then needs explicit `GRANT CONNECT` / `GRANT USAGE ON
  SCHEMA public` / `GRANT SELECT ON ALL TABLES` plus `ALTER DEFAULT
  PRIVILEGES … GRANT SELECT` so new tables inherit it.
* `CLAUDE.md`: production writes — and `CREATE ROLE` is a write — belong to
  the owner. No session may run one.

Putting it in a migration is worse than by-hand on three counts: the password
would live in the repo or in a migration-time env var; `alembic upgrade head`
runs on **every API container start** (`backend/entrypoint.sh:5-11`), so the
DDL would re-run in CI and locally; and no existing migration issues any
`GRANT`/`CREATE ROLE` (`grep` over `backend/alembic/versions/` is empty), so
it would be the first. Keep migrations schema-only.

### pgbouncer transaction mode (NORM-30)

Neon's pooled endpoint is **PgBouncer in `pool_mode=transaction`**
(`neon.com/docs/connect/connection-pooling`). Unsupported through it:
`SET`/`RESET` session variables, `LISTEN`/`NOTIFY`, `WITH HOLD` cursors,
SQL-level `PREPARE`/`DEALLOCATE`, `LOAD`, and **session-level advisory
locks**.

Three consequences:

1. **A read-only role cannot be made read-only by session `SET`.** That is
   NORM-30 restated: the setting outlives the connection's lease. The
   enforcement must be in the **role's grants** (`SELECT` only), which is
   exactly what a Neon SQL-created role gives, plus `ALTER ROLE … SET
   default_transaction_read_only = on` if belt-and-braces is wanted — note
   that `ALTER ROLE … SET` is a *catalog* setting applied at connection
   start, not a runtime `SET`, so it is compatible with the pooler.
2. **Existing code is already safe.** `parcels._lock_parcel_location`
   (`backend/app/services/parcels.py:27-42`) uses `pg_advisory_xact_lock`,
   which is transaction-scoped and *is* supported; it is session-level
   advisory locks the pooler forbids. And `db.check_db_connection`
   (`backend/app/db.py:49-68`) already uses `SET LOCAL statement_timeout`
   inside an explicit transaction, with a comment saying why.
3. The MCP session factory should follow the same discipline: no `SET`, and
   if a statement timeout is wanted for the public path, `SET LOCAL` inside
   the transaction.

---

## 8. Client acceptance (documentation only) — **confirmed for all four**

| Client | Accepts an unauthenticated remote MCP server? | Citation |
|---|---|---|
| **claude.ai custom connectors** | **Yes.** The supported-auth table lists type `none` — *"No authentication (authless server)"* — as **"Supported. An optional partial-auth mode is experimental."** Works with a Universal URL. | `https://claude.com/docs/connectors/building/authentication` |
| **Claude Desktop** | **Yes.** *"Custom connectors using remote MCP are available on Claude, Cowork, and Claude Desktop for users on Free, Pro, Max, Team, and Enterprise plans"*; the auth page states the same infrastructure backs Claude.ai, Desktop, mobile, Claude Code and Cowork. Free plans are limited to one custom connector. | `https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp`; auth page as above |
| **Claude Code** | **Yes.** `claude mcp add --transport http <name> <url>`; HTTP is the recommended transport for remote servers, and no `--header` is needed when the server requires no credentials. SSE is documented as deprecated. | `https://code.claude.com/docs/en/mcp` |
| **ChatGPT connectors** | **Yes**, with a caveat. Developer mode states *"Authentication supported: OAuth, No Authentication, and Mixed Authentication"* and *"Supported MCP protocols: SSE and streaming HTTP."* But the connector guidance adds that for deep research and company knowledge *"your MCP server should implement two read-only tools: `search` and `fetch`"* — our five tools are not those two. | `https://developers.openai.com/api/docs/guides/developer-mode`; `https://developers.openai.com/api/docs/mcp` |

**Changes for the build:** nothing blocks the no-auth design on any of the
four. Two documented facts that shape it:

* Anthropic's outbound traffic to an MCP server originates from
  `160.79.104.0/21`. That is the range to use if per-IP limiting on the MCP
  path is ever wanted — and it is also why per-IP limiting would be nearly
  useless there: every claude.ai user arrives from the same block. **Bound the
  MCP path by query cost, not by source IP.**
* ChatGPT's `search`/`fetch` convention is a v2 question, not a v1 one. If
  ChatGPT discoverability matters, it costs two more tools that wrap the five,
  not a redesign.

The empirical test — actually connecting each client — remains Ryan's.

---

## Needs your decision

1. **AA4 / `lookup_parcel`.** The tool cannot be written until the
   city-level-parcel question is answered: gate at geocode, flag the row, or
   delete it. v1's minimum is whether `lookup_parcel` returns the Cupertino
   row as a normal hit or refuses it as `not_a_parcel`. STATUS.md's AA4 row
   names this report as the committed MCP doc it was waiting for.
2. **URL shape for imagery deep links.** `?snap=<uuid>` exists today and is
   unstable across re-fetches; `?year=&source=` does not exist and would be
   stable. Does the frontend change (three edits, check 3) ship with the MCP
   build, or does v1 link to `/explore/:parcelId` only?
3. **DNS-rebinding setting.** Pass the real public host to
   `streamable_http_app(host=…)`, or disable the check explicitly with a
   `TransportSecuritySettings`? The first is narrower; the second is more
   obvious to a reader. Either way it must be deliberate — the default is a
   production-only 421.
4. **Dependency weight.** `mcp==2.2.0` brings ~15 new locked packages,
   including a second HTTP stack (`httpx2` + `httpcore2`), `cryptography` via
   `pyjwt[crypto]`, and `opentelemetry-api`. Acceptable for the API image, or
   is a separate Fly app for the MCP server preferable?
5. **Read-only role.** Confirm the role is created by hand in Neon with
   `CREATE ROLE … WITH LOGIN PASSWORD` + explicit `SELECT` grants + `ALTER
   DEFAULT PRIVILEGES`, its URL added as a second Fly secret
   (`MCP_DATABASE_URL`), and the pooled `-pooler` endpoint used. No session
   will create it.

## Explicitly not established

* **`fly secrets list` was denied in this session**, so the secret *names* on
  `log0s-plotline-api` and `plotline-worker` are inferred from `config.py` and
  from the running process, not read.
* **Adams's "post-2011" extent is unrecorded** (check 5). If it is real it
  needs a source before `describe_coverage` can assert it.
* **No heal, sweep or migration was run**, so `CLAUDE.md`'s prediction rule
  has nothing to bind. Every production statement in this report is a
  `SELECT` or an `EXPLAIN` inside a `BEGIN READ ONLY` transaction.
