# Sleep / suspend recon — 2026-11-02

Report only. No config, code, or machine state was changed. Production access
was `fly scale show`, `fly image show`, `fly logs --no-tail` only.

Legend: **[V]** verified (command run or file:line read), **[I]** inferred.

**Access gap.** `fly machine list -a <app> --json` was **denied by the
permission layer** (three attempts, including the bare command). I did not
route around it (no `fly status`, Machines API, or ssh). Everything that only
that command shows is marked **UNKNOWN** below. Re-run it yourself to fill the
gaps in section 1 (state, per-machine region, standby, swap, guest cpu_kind).

Deployed SHA on api and worker: `bac725c5a7d196a8cd8c7aa4f6da84c7bb063bda` [V]
(`fly image show` GH_SHA label). HEAD of the repo is `bb28a5b`, so the running
code may lag the tree I read [I; not diffed].

---

## 1. Machine inventory

Commands: `fly scale show -a <app>`, `fly image show -a <app>`.

| app | machine id | count/kind | CPU | memory | region |
|---|---|---|---|---|---|
| log0s-plotline-api | 825d69b7e46618, 48e0de9a713918 | 2, shared | 1 | 512 MB | lax(2) |
| plotline-worker | e2862966b306d8, e7845415f57728 | 2, shared | 1 | 1024 MB | lax(2) |
| plotline-titiler | 825d6ea73e9278, 080e603a732098 | 2, shared | 1 | 1024 MB | lax(2) |

[V] for all of the above. Not obtainable without `machine list`:

- state per machine: **UNKNOWN**
- standby flag: **UNKNOWN** (no `standbys` key in any toml [V]; two machines per
  app with no volumes suggests plain HA pairs, not standbys [I])
- swap: **UNKNOWN live**; no `swap_size_mb` in any toml [V]
- image size: **not reported** — `fly image show` (table) has no size column.
  `--json` was part of a denied command. UNKNOWN.

Image refs [V]: api/worker are `registry.fly.io/<app>:deployment-01M1WY8H…`
(api digest `sha256:2253d63e…`, worker `sha256:e0eee73e…`). Titiler is
`ghcr.io/developmentseed/titiler:1.2.1`, digest `sha256:9cc74708…`.

**Drift to know about:** the working tree's `fly.titiler.toml` (uncommitted)
pins titiler **2.4.0** by digest `5b739117…`; production runs **1.2.1**. The
SEC-17 fix is not deployed [V]. Any Titiler redeploy is also a cold start that
discards any suspend snapshot (see 2).

## 2. fly.toml config

**fly.toml (api)** — `fly.toml:26-31` [V]
`[http_service]` internal_port 8000, force_https, `auto_stop_machines = "off"`,
`auto_start_machines = true`, `min_machines_running = 1`. `[[vm]]` 512mb shared
1 cpu (`fly.toml:33-36`). No `[[http_service.checks]]`, no `[http_service.concurrency]`
(proxy defaults), no `swap_size_mb`, no `[processes]`, no `release_command`.
Env: `TITILER_URL=https://plotline-titiler.fly.dev`,
`API_INTERNAL_URL=https://log0s-plotline-api.fly.dev` (public URLs, `fly.toml:15-17`).

**fly.worker.toml** [V] — `[processes] worker = 'celery -A app.tasks.celery_app
worker --loglevel=info --concurrency=2'` (line 13). **No `[http_service]` or
`[[services]]`** at all, so Fly Proxy has nothing to autostop/autostart for this
app. 1024mb shared 1 cpu. No checks, no swap.

**fly.titiler.toml** (working tree, uncommitted; prod differs, see 1) [V] —
`[http_service]` internal_port 8000, `auto_stop_machines = 'off'`,
`auto_start_machines = true`, `min_machines_running = 1`; 1024mb shared 1 cpu.
No checks, no concurrency block, no swap. `MAX_WORKERS=2`, `VSI_CACHE_SIZE`
256 MB, `GDAL_CACHEMAX=200`. Titiler holds an in-process STAC item cache
(LRUCache 512, no TTL — see the toml comment).

Health checks: none defined in any toml [V]. The Dockerfile installs curl "for
healthchecks" but nothing uses it [V]. Live machine-level `checks` UNKNOWN.

**Suspend restrictions** — Fly docs, https://docs.fly.io/reference/suspend-resume
(fetched today; the fly.io URL 301s there):

- ≤ 2 GB memory: **api 512, worker 1024, titiler 1024 all pass** [V].
- "No swap configured": none in tomls [V]; live UNKNOWN.
- "No schedule configured": none [V].
- "Been updated since June 20, 2024 20:00 UTC": all machines were created/updated
  later (deploys are from 2026) [I].
- "Snapshots are tied to the exact code and state of the machine they were taken
  from. If you deploy new code, the old snapshot … will be discarded." Every
  deploy therefore cold-starts the first wake. Also discarded on host migration,
  lost snapshot, maintenance.
- "On resume, the machine thinks its network connections are still live.
  External systems … may disagree." Listed symptoms: ECONNRESET, timeouts on
  first request, database pool errors.
- "On resume, the clock can lag a few seconds until NTP syncs."
- "Some logs may be lost after resume." "Suspending many machines at once is
  not recommended."
- Resume is "a few hundred ms"; cold start "~2+ seconds for common apps" (docs'
  figures, not measured here).
- Config reference: `min_machines_running` applies "in the primary region only";
  proxy suspends "exactly one Machine" per region per cycle ("every few
  minutes"); with one machine in a region it suspends on zero traffic.
  Docs https://docs.fly.io/reference/fly-proxy-autostop-autostart.
- Not stated in the docs I read: GPU limits, max suspended duration. The
  `[processes]` section of the config reference was not read verbatim.

Implication of `min_machines_running = 0` with both machines in lax [I from the
quoted rule]: they suspend one per cycle until none run.

## 3. Boot path

- API image: `ENTRYPOINT ["/entrypoint.sh"]`, `CMD uvicorn app.main:app --host
  0.0.0.0 --port 8000` (`Dockerfile.fly`, last lines) [V]. Entrypoint
  (`backend/entrypoint.sh`) runs `alembic upgrade head` unless `$1 == celery`.
  **Premise holds: the API migrates on every boot** [V].
- Worker: the process command starts with `celery`, so the entrypoint skips
  migrations [V]. That Fly passes `[processes]` as the CMD with ENTRYPOINT kept
  is [I] (consistent with the entrypoint comment and the migration comment that
  only API boots migrate).
- Lock cost: `alembic/env.py:181` `SELECT pg_advisory_xact_lock(8675309)` inside
  `connection.begin()`. It was a session-scoped `pg_advisory_lock` originally
  (M10/dd99cee) and is now transaction-scoped (X1 fix) [V]. Uncontended cost is
  one round trip plus the migration-context head read, and then
  `_verify_at_head` opens a second connection and re-reads the version
  (`env.py:~197`) [V]. **Not timed**: the log tail I pulled had no boot lines.
  Contended case: a second booter blocks until the first commits (test:
  `test_migrations_postgres.py:185`).
- Other API startup work: `lifespan` calls `stac_service.schedule_startup_mint()`
  (`main.py:34`) → background SAS mints for `STARTUP_MINT_CONTAINERS`; fire and
  forget, never blocks startup (`stac.py:627-659`). Production logs show the
  paired mints (naip, sentinel2) landing at boot, 150-540 ms each [V, `fly logs`
  2026-11-01T21:01, 2026-11-02T17:17].
- No cache priming, no preview rendering at boot. `preview_renderer` is only
  imported by `scripts/seed_featured.py:247` (admin) [V].
- Worker startup: `worker_ready` → `sweep_stranded_work` (janitor, section 5)
  [V]. `worker_process_init` disposes the inherited engine.
- After suspend/resume none of this reruns [I]: entrypoint, migrations, lifespan
  mint and the janitor all run only on cold start (first boot after a deploy, a
  discarded snapshot, or a stop). So a resumed API gets no fresh SAS mint; cached
  SAS tokens (Redis, `stac.py:533-566`) may be past expiry after a long sleep and
  are re-minted on demand at the request-path wait of 2.0 s (`stac.py` comment
  at 627-640: a PC 429 can blow that budget).

## 4. Celery topology

- **Beat: does not exist.** No `beat_schedule`, no `-B`/`--beat`, no beat
  process in `fly.worker.toml`, `docker-compose.yml:95`, `docker-compose.prod.yml`
  or Makefile (grep over repo) [V]. **Zero scheduled tasks** — premise "beat
  running somewhere" is false. The janitor is signal-driven, not scheduled.
- Registered task: `tasks.fetch_imagery_timeline` only (`timeline.py:1754`),
  `soft_time_limit=1800`, `time_limit=2100` [V].
- Worker command: `celery -A app.tasks.celery_app worker --loglevel=info
  --concurrency=2` (`fly.worker.toml:13`) [V]; prefork, 2 children.
- Config actually set (`celery_app.py:46-62`) [V]: json serializers,
  `task_ignore_result=True`, `task_acks_late=True`,
  `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`.
- **Not configured anywhere** [V by grep]: `broker_transport_options`,
  `visibility_timeout`, `broker_heartbeat`, `--without-gossip`,
  `--without-mingle`, `--without-heartbeat`, `-E`. So Celery/kombu defaults
  apply: visibility_timeout 3600 s (the repo's own comment at `timeline.py:1750`
  says "default 3600s"), gossip + mingle + heartbeat on [I from Celery defaults].
- Result backend: `backend=_redis_url`, same Redis as the broker
  (`celery_app.py:41`) [V]; results are ignored, so it stores nothing [V].
- Broker URL: `settings.redis_url`, `ssl_cert_reqs=CERT_REQUIRED` appended for
  `rediss://` (`celery_app.py:23-33`) [V]. Provider: the code comments say
  Upstash/Fly Redis; the actual secret value was not read.
- **Idle command volume [I, not measured]:** each worker machine runs the kombu
  Redis consumer loop (blocking pop with ~1 s poll), plus gossip/heartbeat events
  published on the `celeryev` fanout and the pidbox control channel. I expect
  on the order of a few commands per second per machine while idle, i.e. roughly
  10^5 to 10^6 commands/day across the two worker machines. I had no way to read
  Upstash usage; the Upstash dashboard's daily command count with workers idle is
  the real number. An API machine adds nothing idle (no Celery consumer; Redis
  only on requests).

## 5. Janitor (O2)

Code: `celery_app.py:89-116` (`worker_ready.connect(sweep_stranded_work)`,
never fatal on `SQLAlchemyError`) → `imagery.sweep_stranded_work`
(`imagery.py:828-920`) [V].

- Threshold: `_STALE_INFLIGHT = timedelta(minutes=45)` (`imagery.py:139`), tested
  against `TimelineRequest.updated_at` (`_is_stale_inflight`, `imagery.py:235`).
  Task hard limit is 35 min.
- Rows it fails:
  1. `timeline_requests` with status in (`queued`,`processing`) and
     `updated_at` older than 45 min → `failed`, `completed_at` now,
     `error_message = "Stranded: worker died mid-task (janitor)"`, plus every
     non-terminal task row under it. Rows locked `FOR UPDATE SKIP LOCKED`.
  2. Task rows in (`queued`,`processing`) whose parent request is already
     terminal (`complete`/`partial`/`failed`) and whose request `updated_at` is
     older than 45 min → `failed`, same message.
  Nothing else; it does not look at Redis.

**Trace: request enqueued while the worker is stopped, picked up 2+ h later.**

1. `POST /parcels/{id}/timeline` → `_create_queued_request` commits a row,
   status `queued`, no task rows (they are created by the worker,
   `timeline.py:~1590`) [V]; then `dispatch_timeline_task` does `.delay()`
   (`imagery.py:392`). Redis accepts the message even with no consumer, so
   dispatch succeeds and the API returns 202 [V by reading; no live test].
2. Row sits `queued`, `updated_at` frozen at creation. The message sits in
   Redis (no TTL set; Redis list, not subject to visibility_timeout until
   delivered).
3. Frontend polls every 2 s (`queries.ts:30`), stops polling at 45 min
   (`POLL_GIVE_UP_MS`, `queries.ts:37`). Page left open past 45 min stops
   updating; the row is still `queued`.
4. **Any new POST for that parcel after 45 min** hits the stale takeover in
   `get_or_create_timeline_request` (`imagery.py:354-362`): the old row is set
   `failed` ("Worker never completed the request") and a **new** request + a
   **second** Celery message are created. The queue now holds two messages for
   the same parcel [V by reading].
5. Worker boots (wake): `worker_ready` runs the janitor. Any request still
   `queued`/`processing` and >45 min old is failed with the Stranded message.
6. The task for the old message then runs. `_run_timeline`
   (`timeline.py:1525-1552`) loads the row `FOR UPDATE`, checks only that it
   exists and has a parcel, and **sets status `processing` unconditionally**
   — it never checks for `failed`. So a request failed by the janitor (or by
   takeover) is resurrected to `processing`, runs the full pipeline, and ends
   `complete`/`partial` [V by reading].
7. Side effects: `error_message` is not cleared on the later success path
   (only set on `failed`, `timeline.py:1725` etc.), so a `complete` row can
   carry "Stranded: …" [I; frontend gates rendering of error_message on
   `status === 'failed'`, `timeline.py:1705`]. If the second (takeover)
   message also runs, two pipelines execute for one parcel.
8. Ordering of janitor vs first message: the janitor runs synchronously in the
   `worker_ready` handler on the main process, before the worker event loop
   delivers messages, so I expect the sweep to precede the first task [I; not
   tested]. If it did not, `SKIP LOCKED` plus `_run_timeline`'s `FOR UPDATE`
   would make the outcome the same either way.
9. User-visible window: between sweep and task start the status endpoint
   returns `failed`; `isTimelineTerminal` treats `failed` as terminal and stops
   polling (`timelineStatus.ts:19`). A client still polling in that window sees
   an error while the run silently completes; the next visit finds a reusable
   `complete` request [I].

Not a clean state transition either way: "stale" is measured on DB time, but the
message's liveness is Redis time. They are not coupled.

## 6. Enqueue sites

Whole-repo grep for `send_task|.delay(|.apply_async|chain(|group(|chord(`,
`backend/app`, `scripts`, `backend/scripts` [V]:

- **Only one real site:** `backend/app/services/imagery.py:392`
  `fetch_imagery_timeline.delay(str(request.id))` inside
  `dispatch_timeline_task`. No chains, groups, chords, apply_async, send_task.
- Callers of `dispatch_timeline_task`: `api/v1/imagery.py:~108` (user path,
  `POST /parcels/{id}/timeline`, rate limit 20/60 s fail-closed) [V]. Other
  callers (backfill, `_create_queued_request_waiting`/heal paths:
  `imagery.py:~696` and scripts `requeue_parcels.py`, `requeue_empty_property.py`,
  `revalidate_landsat.py`, `heal_county_fallback.py`) call into the service
  rather than `.delay` directly; they are owner-run writes [I for the exact
  call chains; not each traced]. `seed.py`/`seed_featured.py` are admin.
- `maybe_refetch_for_backfill` (`imagery.py` in the same route) can also create a
  replacement request and dispatch on a plain GET-driven visit [V by reading
  `trigger_timeline`].

## 7. Inbound traffic that keeps machines awake

- Fly health checks: none defined (2) [V].
- External monitors: no uptime service in the repo (grep for
  uptime/statuscake/pingdom/healthchecks/cron: nothing outside audit docs) [V].
  Whether one is configured outside the repo is UNKNOWN.
- CI: `deploy.yml:43-58` curls `/api/v1/health` once per deploy to read the live
  SHA [V]. This wakes the API on each push to main and the check treats an
  unreachable/empty result as "unknown" (`deploy.yml:57-58`).
- `/api/v1/health` pings DB and Redis (`health.py`, `db.py:140`); it is a real
  dependency probe, not cheap, and returns 503 if either fails [V].
- Frontend polling [V]: timeline request status every 2 s while non-terminal
  (`queries.ts:30,102`), 10 s on error (`:34`), gives up after 45 min (`:37`);
  imagery list refetch every 3 s while `timelineActive` (`queries.ts:81-82`).
  Both only while a user has the page open. Query default staleTime 5 min
  (`main.tsx:11`). No health polling from the frontend (grep "health" in
  `frontend/src`: none).
- Cloudflare Pages functions: **none** — no `frontend/functions` directory
  [V]; `public/_redirects` is an SPA fallback only.
- API→Titiler non-user-triggered calls: none at runtime. The only
  non-request Titiler caller is `preview_renderer.py:132` via
  `scripts/seed_featured.py` (admin) [V]. The browser-fired
  `POST /imagery/{id}/warmup` (`warmup.ts`, 250 ms debounce after selection;
  `imagery.py:638-720`) is user-triggered but is the first call that wakes
  Titiler. The tile proxy calls Titiler (`_fetch_titiler`), and Titiler then
  calls **back** into the public API `/stac` endpoint for Landsat signed items
  (`fly.toml:10-14`, `imagery.py:765`), so one cold tile can wake both apps
  and needs the API awake while Titiler is mid-request [V by reading; the
  round trip was not exercised].
- Worker: no inbound traffic; not under proxy control (2).

## 8. Cold-path latency budget

Timeline submit path:
- Browser `apiFetch` timeout: `API_TIMEOUT_MS = 30_000` (`client.ts:3`),
  applied at `client.ts:82`; on expiry throws `ApiRequestError(0, "Request timed
  out")` (`client.ts:88-93`). Applies to POST timeline, status GET, imagery
  list, geocode, etc. (all go through `apiFetch`) [V].
- Geocode/parcels on the submit path also traverse the API's upstream timeouts
  (census geocoder 20 s `config.py:60`, census API 30 s `config.py:56`) [V].
- Status poll `useTimelineRequestQuery` retry 3, delay 2/4/6 s
  (`queries.ts:104-105`) [V]; default query retry 1 (`main.tsx:12`).
- Redis client timeouts `_REDIS_TIMEOUT = 2` s socket/connect (`db.py:84`);
  rate limiter on POST is `fail_closed=True` (`imagery.py:62`) [V], so a Redis
  error on the first request after resume fails the POST rather than skipping
  the limit [I that a stale socket would surface as such an error; redis-py's
  internal retry may absorb it].

Tile path:
- MapLibre fetches `${apiBase}/api/v1/imagery/{id}/tiles/{z}/{x}/{y}`
  (`applyImageryLayer.ts:80,92`) — **no app-level AbortSignal**, only
  MapLibre's own request handling; `apiFetch`'s 30 s does not apply [V].
- API→Titiler: `httpx.AsyncClient(timeout=30)` (`imagery.py:336`); failure →
  502 "Titiler upstream unreachable" (`imagery.py:416-418`) [V].
- API→PC STAC item fetch: 15 s (`imagery.py:374`); SAS sign attempt 10 s,
  request-path wait `SIGN_WAIT_REQUEST` 2.0 s (`stac.py` comments 202-250) [V].
- Warmup is best-effort, fail-open (`imagery.py:653-720`).
- Proxy/nginx: `frontend/nginx.conf` is the compose/local proxy only; prod
  frontend is Cloudflare Pages with `VITE_API_BASE_URL` pointing at the API
  (`Dockerfile.prod:7`, `FeaturedCards.tsx:14`). No proxy timeout in repo for
  prod; Fly Proxy / Cloudflare defaults apply, UNKNOWN [V that none is in repo].
- Worst-case cold tile chain [I]: API wake + Titiler wake + Titiler→API `/stac`
  callback, all inside the API→Titiler 30 s client timeout.

---

## Implications for suspend/autostop (ranked)

1. **HIGH — Worker wake-on-enqueue changes the janitor's meaning.** Messages and
   DB rows have separate clocks. A request waiting >45 min for a worker is
   failed by the janitor (or a re-POST takeover), then resurrected by the task
   (no status guard in `_run_timeline`), and a takeover creates a duplicate
   message/pipeline. Today the worker is always on, so this window does not
   exist. (Section 5.)
2. **HIGH — Dispatch has no worker-liveness signal.** `.delay()` succeeds with
   no consumer, so the API returns 202 for work that nothing is running.
   Nothing in the repo starts the worker; wake-on-enqueue would have to hook the
   single site `imagery.py:392` (section 6).
3. **MEDIUM — Cold chain on the tile path.** API→Titiler (30 s) plus
   Titiler→API `/stac` callback; both apps asleep means two wakes serialized
   inside one tile request, with no app-level timeout on the browser side
   (section 8). Titiler's in-process caches and warm GDAL state are lost on cold
   start (section 2).
4. **MEDIUM — Every deploy discards snapshots** (docs), and the deploy workflow
   itself curls `/health` (wakes the API). The first request after each deploy
   is a cold start with migrations + SAS mint (section 3).
5. **MEDIUM — Post-resume stale connections.** Redis sync/async clients and
   SQLAlchemy pool connections survive in the snapshot but the remote side
   (Upstash, Neon via pooler) will have closed them; the POST rate limiter is
   fail-closed (section 8). SAS tokens in memory/Redis may be expired.
6. **LOW — Idle Redis cost is from workers only** and is unmeasured; with no
   beat there is no scheduled traffic. A suspended or stopped worker removes it
   (section 4).
7. **LOW — Rolling-state unknowns:** machine states, standby flags, live swap,
   per-machine health checks, and image sizes could not be read (`machine list`
   denied). All pass the documented ≤2 GB rule on the evidence available.
8. **LOW — Titiler tree/prod drift** (2.4.0 pinned in tree, 1.2.1 live): the
   next Titiler deploy is a cold start regardless.

## Record

`docs/audits/2026-08-second-audit/STATUS.md` was **not** updated by this
report (report-only instruction). Items 1-2 above (the janitor/stale-takeover
race and the `_run_timeline` status-guard gap) are new findings that belong in
the ledger; that is left for the owner to place.
