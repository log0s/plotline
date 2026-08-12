# Plotline operational audit — 2026-08-12

Read-only audit of production. No fixes, no config changes, no writes. Everything
below is evidence gathered from the Fly log buffers and read-only queries against
the production database.

---

## 0. Which world is this?

**The signing-throttle fix is NOT deployed.**

| | |
|---|---|
| Local `HEAD` | `19463b5` (docs: record the signing-burst year loss under M4) |
| `origin/main` | `cff2a52` (docs: sharpen M4 and record the decennial housing gap) |
| Deployed release | API `v48` / worker `v41`, both **Aug 4 2026 21:32** |
| Titiler release | `v6`, **Jun 13 2026** (`developmentseed/titiler:1.2.1`) |

`a536d07` ("throttle Planetary Computer SAS signing and retry 429s") and `19463b5`
are committed locally and **unpushed**. CI deploys on push to `main`, so production
is still running the pre-throttle code. Confirmed independently from the logs: the
event string `"SAS signing rate-limited; backing off"` (`stac.py:259`, introduced by
`a536d07`) appears **zero** times across all three buffers, while its failure mode
does not.

The tract-vintage fix (`b5a306a`) *is* deployed — it is inside `cff2a52`/v48.

**This single fact changes the reading of every signing-related finding below.**

---

## 1. Window and span covered

### Logs (snapshot)

`fly logs --no-tail` returns a **hard ~100-line page per machine**, not the whole
buffer. There is no depth flag (`fly logs --help` exposes only `-a/-c/-m/-r/-s/-j/-n`).
I widened coverage by pulling each machine separately and de-duplicating; that is
the ceiling available.

| App | Unique lines | Window (UTC) | Span |
|---|---|---|---|
| `log0s-plotline-api` | 200 (2 machines) | `2026-08-11T21:20:02Z` → `2026-08-12T01:44:33Z` | 4h 24m |
| `plotline-worker` | 100 (1 live machine) | `2026-08-12T01:24:44Z` → `2026-08-12T01:45:00Z` | **20m** |
| `plotline-titiler` | 142 (2 machines) | `2026-08-12T01:26:06Z` → `2026-08-12T01:30:23Z` | **4m** |

The second worker machine (`e7845415f57728`) is **stopped**; its log fetch hung and
was abandoned. Its buffer was not read.

**The worker window does not reach the 2026-08-11 ~23:28Z incident.** Everything
said about that incident below comes from the database, not the logs. The worker
is the chatty component, so its 100-line page covers the least wall-clock time —
the component that matters most for imagery is the one with the worst retention.

### Database (history)

| | |
|---|---|
| `timeline_requests` span | `2026-04-13T23:01:55Z` → `2026-08-12T01:44:32Z` |
| Volume | 41 parcels · 136 requests · 709 tasks |
| Imagery | 3,128 snapshots · 310 census · 276 property events |

Note: the earliest request is **2026-04-13**, not March. The prompt's "since March"
does not match the data; either earlier rows were pruned or the project's first
request landed in April.

At this size every query is a trivial full scan — nothing here was expensive, and no
bounded/sampled variants were needed.

---

## 2. Findings by severity

### 🔴 HIGH-1 — The mitigation for the known incident is not in production

**Contradicts `docs/audits/2026-08-second-audit/STATUS.md`.** The M4 row reads:

> "`a536d07` mitigates the trigger (signing concurrency capped, 429s retried with
> backoff) but not the defect"

That sentence describes a deployed mitigation. It is not deployed — it is an
unpushed local commit (§0). Anyone reading STATUS.md would conclude the trigger is
capped in production. It is not.

**Evidence:** deployed release v48 = Aug 4; `a536d07` = Aug 11, unpushed. Zero
`"SAS signing rate-limited; backing off"` events in any buffer.

**Why it matters:** this is the highest-value thing this audit caught — a
mitigation recorded as applied that is not actually running. And it is not
theoretical: HIGH-2 shows fresh damage after the incident.

**Suggested action:** push `main`. Then re-read STATUS.md's M4 row and date the
mitigation to its actual deploy, not its commit.

---

### 🔴 HIGH-2 — Landsat year loss is ongoing, with a new casualty after the known incident

Ground truth from `imagery_snapshots` (not `items_found` — see §4): **38 of 41
parcels hold exactly 43 distinct Landsat years, 1984–2026.** Three do not.

| Parcel | County | Years | Missing | Latest landsat request |
|---|---|---|---|---|
| `7397388e-9b2f-40af-8c4b-cd92aa2184c5` | Denver | **23** | 20 | `dc9ebd08-…` 2026-08-11 23:18:18Z |
| `e0cb3db9-a7d5-4cf5-9c72-9be8f9a968c2` | Ocean | **35** | 8 | `2fb395b0-…` **2026-08-12 00:45:28Z** |
| `d6cf2ac8-b93b-4c78-add8-bd7ddecc4663` | Boone | **42** | 1 (2026) | `e730ef7e-…` **2026-08-12 00:43:02Z** |

The Denver parcel is the known incident, confirmed exactly: 43 − 20 = 23, request
`dc9ebd08-5f9c-49ba-a5e0-59fc97124cee`, completed 23:28:33Z. Task status
`complete`. **The damage is still there** — nothing healed it.

The important finding is the second row. `e0cb3db9` (Ocean County NJ) lost 8 years
in a request that ran **2026-08-12 00:45Z — after the known incident, on
undeployed-fix production.** This is not an old casualty surfacing; it is new
damage. The control is decisive: `caf73bab` is a *different parcel in the same
county* with all 43 years, so the missing years are not a genuine coverage gap.

Missing years, `e0cb3db9`: 1986, 1987, 1988, 1989, 1994, 1996, 2016, 2023.
Missing years, `7397388e`: 1995–2003, 2011, 2012, 2014–2019, 2023, 2024, 2025.

`d6cf2ac8` is missing only 2026 and is plausibly benign (current-year scene not yet
selected); I would not heal it on this evidence alone.

**Why it matters:** every one of these tasks reported `complete`, so backfill will
never retry them (M4). The gaps are permanent until healed by hand. And loss is
still accruing at roughly one damaged parcel per handful of requests.

**Suggested action:** push the throttle fix first (HIGH-1), then heal
`7397388e` and `e0cb3db9`. Healing before deploying re-runs the same dice.

---

### 🔴 HIGH-3 — Broken map tiles in production: signing failure → unsigned href → Azure 409 → Titiler 500

Not previously recorded in any audit doc. The API buffer holds **37 Titiler 500
errors across 10 distinct snapshots**, every one with the same upstream body:

```
{"detail":"HTTP response code: 409"}
```

The cause is visible in the same buffer. Each 500 is preceded, seconds earlier, by
a band-signing failure on the *same snapshot id*:

| Snapshot | `Band signing failed` | `Titiler returned 500` |
|---|---|---|
| `7f8effeb-…` | 21:20:08Z (blue, blue, green, red) | 21:20:08Z |
| `b078dfa3-…` | 23:13:37Z (green) | 23:13:39Z |
| `635d3d6e-…` | 01:25:40Z (blue) | 01:25:43Z |
| `b4c654d1-…` | 01:27:15Z (blue, blue, green) | 01:27:17Z |
| `c5ea434d-…` | 01:30:21Z (blue) | 01:30:23Z |

`imagery.py:666` catches the signing failure and falls back to the **unsigned**
href. Planetary Computer then rejects the unsigned blob read with 409, Titiler
surfaces that as a 500, and the user gets a broken tile. The fallback converts a
recoverable signing error into a guaranteed user-visible failure.

12 `"Band signing failed; using unsigned href"` and 1 `"URL signing failed, falling
back to unsigned"` in a 4h24m window.

**Why it matters:** this is the *same signing endpoint* as HIGH-1/HIGH-2, failing on
the read path instead of the ingest path. The throttle fix targets `stac.py`
signing; it will not necessarily fix this path. This is live, user-facing, and
happening now.

**Suggested action:** treat "unsigned fallback" as a failure, not a degradation —
it cannot succeed against a private PC blob. Retry the signing instead. Also note
the log event carries `band` and `snapshot_id` but **not the underlying error**, so
the reason signing failed is unknowable from logs.

---

### 🟠 MEDIUM-1 — The worker is being OOM-killed on a 512 MB machine

Not previously recorded. Captured live in the 20-minute worker window:

```
2026-08-12T01:24:50Z  Process 'ForkPoolWorker-4' pid:719 exited with 'signal 9 (SIGKILL)'
2026-08-12T01:24:50Z  [618717.299420] Out of memory: Killed process 719 (celery)
                      total-vm:766204kB, anon-rss:207076kB, file-rss:48kB, UID:0
2026-08-12T01:24:50Z  [error] Task handler raised error:
                      WorkerLostError('Worker exited prematurely: signal 9 (SIGKILL) Job: 14.')
```

`plotline-worker` runs `shared-cpu-1x:512MB`. An OOM kill appeared within a
20-minute sample — it is not rare.

This very likely explains the three `failed` requests whose `error_message` is
`"Task timed out"` and which each left a `landsat` task stranded in `processing`:

| Request | Parcel | Created |
|---|---|---|
| `790191df-…` | `2a4ca7b9-…` | 2026-06-16 20:54:24Z |
| `20d3e412-…` | `56677086-…` | 2026-07-02 21:57:19Z |
| `648390c3-…` | `90b3acd5-…` | 2026-08-03 22:24:09Z |

A SIGKILL'd worker cannot update its task rows, which is exactly the observed
signature. All three parcels have since been re-run to a full 43 years, so no data
loss survives — but that was luck, not recovery logic.

**Suggested action:** raise worker memory, or bound per-task memory. Consider
whether `WorkerLostError` should mark the request failed promptly rather than
waiting for the 30-minute timeout.

---

### 🟠 MEDIUM-2 — Census per-year loss is live, and confirms M4 is unmitigated

The 20-minute worker window caught M4 happening in real time. Four
`httpx.ReadTimeout`s against `api.census.gov`:

```
01:25:11Z error   Census API request failed   url=.../1990/dec/sf1     ReadTimeout
01:25:11Z warning Census decennial failed     year=1990
01:25:28Z error   Census API request failed   url=.../2020/dec/dhc     ReadTimeout
01:25:28Z warning Census decennial failed     year=2020
01:25:49Z error   Census API request failed   url=.../2018/acs/acs5    ReadTimeout
01:25:49Z warning Census ACS5 failed          year=2018
01:26:04Z error   Census API request failed   url=.../2021/acs/acs5    ReadTimeout
01:26:04Z warning Census ACS5 failed          year=2021
```

The database shows the consequence. Parcel `2b398698-…` (Maricopa), request
`8335124f-…`, created 01:24:39Z, **task `census` status `complete`, items_found 5**:

| dataset | years present |
|---|---|
| acs5 | 2012, 2015, 2018, 2023 — **2021 missing** |
| decennial | 2010 — **2020 missing** |

Permanently gapped, marked complete, unreachable by backfill. This is M4's exact
predicted failure, observed today. The Census API's timeouts — not our signing —
are the trigger here, so the throttle fix would not have helped.

Also `177681ef-…` (Chelan) was **re-fetched today** and *still* lacks acs5 2018 —
it is the sole surviving parcel matching the vintage-break signature (§3), and a
fresh run did not repair it, because a complete-with-gaps task is never retried.

---

### 🟠 MEDIUM-3 — Adams County property returns empty every time; H4's fix does not cover it

**Partially contradicts STATUS.md**, which lists `H4 Property outage` as
**resolved** by `256ed32`.

`256ed32` only marks a task `failed` when **all** queries fail
(`SourceFetchResult.all_queries_failed`). A partial failure — or a silently empty
adapter — still yields `complete` with `items_found = 0`, indistinguishable from a
genuine empty.

Adams County, the single Adams parcel `ebe38b44-…`, every property task ever run:

| Request | Created | Status | items_found |
|---|---|---|---|
| `5e109290-…` | 2026-06-13 05:29:17Z | complete | 0 |
| `b196337c-…` | 2026-08-03 21:08:03Z | complete | 0 |
| `755f34f7-…` | 2026-08-03 21:21:17Z | complete | 0 |
| `fa06ee9a-…` | 2026-08-03 22:23:02Z | complete | 0 |
| `e1cb6472-…` | 2026-08-03 22:23:35Z | complete | 0 |

`property_events` for Adams: **0 rows, ever.** Five runs across two months, an
adapter-supported county, never a single event. The last two ran *after* release
v43 (Aug 3 22:21) — i.e. after the property fix shipped — and still returned a
clean-looking zero. That is the "cluster from one county" the audit brief asked
me to treat as suspicious.

Santa Clara is weaker but similar: 2 parcels, **1** property event total, one task
`complete:0`.

Counties that clearly work: Denver (101 events), DC (89), New York (85 — and NYC
recovered from `complete:0` in June to 37/48 in August).

One genuine failure is correctly recorded: `property | All Denver County property
queries failed` — the H4 path working as designed when *everything* fails.

**Suggested action:** verify the Adams adapter against its upstream by hand. The
DB cannot distinguish "county has no records for this parcel" from "adapter is
silently broken" — that distinction needs per-query instrumentation.

**Also note:** the incident parcel `7397388e` (Denver) recorded
`property complete:0` during the same burst window, while its five Denver peers
hold 10–33 events each. Suggestive, not conclusive.

---

### 🟡 LOW-1 — 1990 decennial has never once succeeded

`SELECT count(*) FROM census_snapshots WHERE dataset='decennial' AND year=1990` → **0**,
across all 41 parcels and the project's whole life. The worker log shows why it is
still being attempted (`.../1990/dec/sf1` → ReadTimeout).

Coverage by year: decennial 2000 → 8 parcels, 2010 → 41, 2020 → 40.
acs5 2009 → 18, 2012 → 41, 2015 → 41, 2018 → 40, 2021 → 40, 2023 → 41.

A dataset that has never returned a single row in four months is either retired at
the endpoint or misconfigured. Every run pays its timeout cost.

**Suggested action:** confirm whether `1990/dec/sf1` still exists; if not, drop it
from `_DECENNIAL_CONFIGS` rather than timing out on it forever.

---

### 🟡 LOW-2 — Eleven task rows permanently stranded

Tasks in `queued`/`processing` whose parent request has already finished:

- **8 `queued`** under three **`complete`** requests, all 2026-04-23 (`1ef35396-…`,
  `32d32beb-…`, `b75f2ee3-…`) — landsat/sentinel2/census/naip.
- **3 `processing`** under the three **`failed`** "Task timed out" requests (MEDIUM-1).

No request is currently stuck: the live check for `queued`/`processing`
**requests** returned zero rows, so there is no in-flight work hung right now.

Harmless to users, but any query counting task states must exclude them or it will
misreport. They also mean `timeline_request_tasks` is not a reliable "what is
running" view.

---

### 🟡 LOW-3 — Geocoder forward-lookup falls back to reverse about half the time

API window: 21 `"Geocode request received"`, 21 `"Calling Census Geocoder"`, but
**10 × `"Forward geocode failed, falling back to reverse"`** and only 8
`"Census Geocoder match found"`. Three `"Address not geocodable"` warnings.

The fallback works — 18 `"Geocode complete"`, 15 new parcels created, 3 dedup hits —
so this is not user-visible breakage. But a ~48% forward-miss rate against the
Census Geocoder is high enough to be worth understanding rather than absorbing.

---

## 3. Instrumentation from recent fixes — is it firing?

Presence across all three de-duplicated buffers:

| Instrumentation | Event string | Count | Reading |
|---|---|---|---|
| PC signing throttle | `SAS signing rate-limited; backing off` | **0** | **Not deployed** (§0) |
| County truncation | `… hit its row cap — results are truncated` | 0 | No query hit its cap in window. Only Denver/DC/NYC/Santa Clara ran; nothing near a cap. Cannot confirm it works from this window. |
| Backfill cooldown | `Backfill suppressed — last attempt is inside the cooldown` | 0 | Never fired. Traffic in-window was all fresh parcels, which don't trigger backfill. Untested here. |
| Tract vintage | `Resolved tract for vintage` | **8** | ✅ **Working.** Paired with 4 × `Looking up tract at vintage`. |
| Reconciliation | `Replaced superseded imagery snapshots` | 0 | ✅ **Quiesced** — and the DB confirms it (below). |
| Our API's 429s | (none — see below) | 0 | **Not observable.** |
| Stale-request takeover | `Taking over stale in-flight timeline request` | 0 | Not fired. |
| Per-year STAC loss | `STAC year chunk failed after retries; skipping` | 0 | Not in window. |
| Landsat year give-up | `No valid Landsat item for year …; skipping` | 0 | Not in window. |

### Tract vintage — confirmed working, in logs *and* data

**15 parcels now hold two distinct `tract_fips` values** across their census years,
which is the fix doing its job. Example, parcel `a3628fd4-…`:

| dataset | year | tract |
|---|---|---|
| decennial | 2010 | `11001006202` |
| acs5 | 2012, 2015, 2018 | `11001006202` |
| decennial | 2020 | `11001980000` |
| acs5 | 2021, 2023 | `11001980000` |

Note the provenance: the 2020/2021/2023 rows were written **2026-04-14 / 06-24 /
07-22** (pre-fix), and the 2010–2018 rows were written **2026-08-04 21:35–21:37**
(post-fix backfill). The fix corrected the *older* years against their own vintage.
I initially read the `980000` tract as the fix misfiring; it is not — see §5.

### Reconciliation — quiesced, and verifiably so

Not just "no log lines". The data confirms accretion is gone:

- Landsat duplicate years (>1 row per parcel-year): **0 rows.**
- NAIP / topo duplicate groups: **0 rows.**
- Sentinel-2 duplicate quarters: **1** (`2a4ca7b9-…`, 2026 Q1, 2 rows) — trivial residue.
- For **every** parcel, the latest complete landsat task's `items_found` **exactly
  equals** the live count of distinct snapshot years. Zero mismatches.

### Our API's rate limits are unobservable

`rate_limit.py:75-79` raises `HTTPException(429, …)` **without logging**, and
`uvicorn.access` is pinned to WARNING in `logging_config.py:66`. So a client hitting
the geocode (10/60s), autocomplete (60/60s), imagery (20/60s), warmup (60/60s) or
STAC (600/60s) limiter leaves **no trace at all**.

I cannot answer "is anyone hitting the limits?" — not "no one is". The only event in
that module, `"Rate limit check failed open"` (Redis unreachable), also did not fire,
which at least means Redis was healthy throughout the window.

---

## 4. `items_found` does not mean what its name suggests

Worth recording, because it shapes every query in this report.

`timeline.py:379` sets it from `count_imagery_snapshots(db, parcel_id, source_name)`
— the **cumulative row count for that parcel+source at that moment**, not the number
of items that run found. Consequences:

- It is a *historical* value: a later run's number is not comparable to an earlier one.
- Historical maxima are inflated by since-cleaned accretion — the all-time landsat
  max is **85**, twice the 43-year ceiling, which is residue from before `96a7962`.
- Mean `items_found` per source is therefore not a health metric.

**All damage findings above use live `imagery_snapshots` as ground truth instead.**
As of now the two agree perfectly (§3), so `items_found` is currently accurate — it
just cannot be trusted historically.

Per-source task outcomes over all time, for the record:

| source | complete | failed | skipped | queued | processing |
|---|---|---|---|---|---|
| naip | 131 | 3 | — | 2 | — |
| landsat | 131 | — | — | 2 | 3 |
| sentinel2 | 133 | 1 | — | 2 | — |
| usgs_topo | 86 | 3 | — | — | — |
| census | 126 | 8 | — | 2 | — |
| property | 41 | 1 | 34 | — | — |

`error_message` census for failed tasks:

| count | source | message |
|---|---|---|
| 6 | census | `All Census API requests failed` |
| 3 | naip | *(null)* |
| 2 | usgs_topo | `Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` |
| 2 | census | `Census API key is required. Get a free key at …` |
| 1 | property | `All Denver County property queries failed` |
| 1 | usgs_topo | *(null)* |
| 1 | sentinel2 | *(null)* |

Two things stand out: **five failed tasks carry a null `error_message`** (nothing to
diagnose from), and the two `usgs_topo` JSON-decode errors are the TNM endpoint
returning non-JSON — the `f1ffae3` decode-error wrapping caught it, but the message
is the parser's, not a useful description.

The 2 `Census API key is required` failures are a config gap that has since resolved
(census now succeeds), but they are worth noting as a deploy that ran without a key.

---

## 5. Working as designed, but worth knowing

**The White House sits in a water/federal tract.** Three parcels —
`1600 Pennsylvania Ave NW` (twice, two geocodings) and `Reflecting Pool` — resolve
to tract `11001980000` for 2020-vintage years. The `98xxxx` series is Census's
special land-use/water range. Their timelines therefore show:

| year | tract | population |
|---|---|---|
| 2015 | `11001006202` | 117 |
| 2018 | `11001006202` | 60 |
| 2021 | `11001980000` | **17** |
| 2023 | `11001980000` | **17** |

That 60 → 17 cliff is a tract-boundary artifact, not a demographic change, and it is
almost certainly on a featured location. The vintage fix is behaving correctly —
each year genuinely maps to a different tract — but the chart still tells a
misleading story. Same three parcels report `total_population = 0` for acs5 2012.

**34 property tasks `skipped`** — every county with no adapter. Correct behavior
(`No property adapter for county` fired twice in-window), not a failure.

**Titiler is healthy.** 142 lines, **zero errors**, no memory pressure, no slow
renders. Its only output is 71 repetitions of a benign `rio_tiler` warning
(`Some statistics data in STAC are invalid, they will be ignored`) — cosmetic, and
it is the entire titiler buffer, which is why that buffer only covers 4 minutes.

**Traffic shape.** Requests per day, all time:

```
04-13:3  04-14:2  04-16:5  04-20:5  04-21:1  04-23:30
05-11:1  05-23:13
06-12:7  06-13:6  06-16:5  06-17:1  06-24:1
07-02:1  07-03:1  07-22:3
08-03:35  08-04:1  08-11:9  08-12:6
```

Two spikes. **2026-08-03 (35)** is self-inflicted — it lines up exactly with the
audit-fix deploys v42/v43/v44 (21:28, 22:21, 23:40) and with the repeated
same-parcel requests seen in MEDIUM-3; that is testing, not users. **2026-04-23
(30)** is the only organic-looking spike and is the LinkedIn-spike candidate. I
cannot confirm attribution — the schema stores no referrer, user agent, or client
IP, so traffic source is unanswerable from the database.

---

## 6. Anomalies I wasn't asked about

- **No probing or scanning is visible** — but see §3: `uvicorn.access` is silenced,
  so 404s, path scans, and bot traffic leave no log line at all. Absence of evidence
  only.
- **The only SSH session in the buffer is mine** (`00:04:07Z`,
  `email=ryan.b.herman@gmail.com verified=true`) — expected, noted for completeness.
- **Two API machines, one worker machine live.** The second worker
  (`e7845415f57728`) has been `stopped` since Aug 4. If that is unintentional,
  the worker fleet is at half capacity — which bears on MEDIUM-1.
- **Repeated same-parcel requests** on 2026-08-03 (`ebe38b44` five times,
  `a3628fd4` four times) — consistent with fix-verification, and a case the backfill
  cooldown would now suppress.

---

## 7. What this audit could not see

**Log retention is the dominant blind spot.** `fly logs --no-tail` caps at ~100
lines per machine. The worker — the component that does all imagery, census, and
property work — yielded a **20-minute** window. The API yielded 4h24m only because
it is quiet.

Would log shipping have changed any finding? **Yes, three:**

1. **HIGH-2's new casualty.** `e0cb3db9` lost 8 Landsat years at 00:45Z, ~40 minutes
   before the worker buffer begins. I know *that* it happened from the database but
   have no idea *why* — 429 burst, validation failure, or something else. With
   shipped logs the mechanism would be settled rather than inferred.
2. **The original 2026-08-11 23:28Z incident.** Entirely outside the window. I
   confirmed its damage from the DB and matched STATUS.md's account, but could not
   independently verify the "21 429s in four seconds" claim.
3. **MEDIUM-3 (Adams).** The runs are from June and August 3. Whether those queries
   errored or genuinely returned nothing is exactly what the logs would say.

**What the schema cannot answer, regardless of logs:**

- **Which years failed.** `timeline_request_tasks` has one status and one
  `items_found` per source. There is no per-year record, so a complete-with-gaps task
  is indistinguishable from a complete one without diffing against an expected year
  set. **That is M4, and it is the reason every damage query in this report had to be
  reconstructed from `imagery_snapshots` rather than read off the task table.**
- **Task-level timing.** `timeline_request_tasks` has no `created_at`/`updated_at` —
  only nullable `started_at`/`completed_at`. Task age must come from the parent
  request.
- **Traffic attribution.** No referrer, user agent, or IP stored (§5).
- **Rate-limit hits.** Not logged, access log silenced (§3).
- **Why signing failed.** The event carries `band` and `snapshot_id` but not the
  error (HIGH-3).

---

## 8. Stated assumptions — please challenge these

- **Landsat "healthy = 43"** — derived, and it held up well. `timeline.py:45-79` sets
  `start_year: 1984` with `chunk_by_year`, so 1984–2026 = 43. Empirically **38 of 41
  parcels hit exactly 43/43, spanning 1984–2026**, which is strong corroboration
  rather than an assumption. The brief's "flag anything complete under ~35" would
  have caught only the Denver parcel; I used *any* deviation from 43, which is what
  surfaced the Ocean County casualty at 35.
- **Sentinel-2 "healthy ≈ 30" does not survive contact — I did not use it.** Observed
  distinct-quarter counts run **13 → 35 in a smooth continuum** (median ≈ 18), with no
  bimodality separating "healthy" from "damaged". A flat threshold would flag ~30 of
  41 parcels. Cloud-cover filtering makes the expected count strongly
  location-dependent, so a global threshold is the wrong instrument. Sentinel-2
  damage is **unassessed**, not cleared. Doing it properly needs a per-parcel
  expectation (available scenes vs. selected).
- **Topo has no threshold at all** — counts run 3–9 decades and depend entirely on
  what USGS surveyed for that quad. I only flagged **zero-coverage**: one parcel,
  `5d3a7b3a-…` (Jefferson), has **no topo rows** while its latest task says
  `complete`, `items_found: 0` (request `470f0494-…`, 2026-08-11 22:00:23Z).
- **NAIP** ranges 5–8 scenes (2010–2023), no outliers; not separately assessed.
- **`d6cf2ac8` missing only 2026** is treated as probably-benign, not damage.
- **"Adapter-supported county"** taken from the `county_adapters.py` registry:
  Denver, Adams, DC, Santa Clara/San Jose, NYC.

---

## Appendix A — The damaged-parcel query

No prior heal query existed for this (the repo has
`scripts/requeue_empty_property.py` and `scripts/heal_tract_vintage_gaps.py`, neither
of which covers low-but-nonzero imagery counts), so this was written fresh.

It deliberately reads **`imagery_snapshots`**, not `timeline_request_tasks.items_found`
— see §4 for why the task column cannot be trusted historically.

```sql
-- Landsat: distinct years held per parcel. Healthy = 43 (1984-2026).
SELECT p.id, coalesce(p.county,'?') AS county,
       count(*) AS rows,
       count(DISTINCT extract(year from s.capture_date)) AS yrs,
       min(extract(year from s.capture_date))::int AS y0,
       max(extract(year from s.capture_date))::int AS y1
FROM parcels p
JOIN imagery_snapshots s ON s.parcel_id = p.id AND s.source = 'landsat'
GROUP BY 1,2
ORDER BY yrs ASC;
```

Exact missing years for the candidates:

```sql
WITH yrs AS (SELECT generate_series(1984,2026) AS y),
dmg AS (SELECT unnest(ARRAY[
    '7397388e-9b2f-40af-8c4b-cd92aa2184c5',
    'e0cb3db9-a7d5-4cf5-9c72-9be8f9a968c2',
    'd6cf2ac8-b93b-4c78-add8-bd7ddecc4663']::uuid[]) AS pid)
SELECT d.pid, string_agg(y.y::text, ',' ORDER BY y.y) AS missing_years, count(*) AS n
FROM dmg d CROSS JOIN yrs y
WHERE NOT EXISTS (
  SELECT 1 FROM imagery_snapshots s
  WHERE s.parcel_id = d.pid AND s.source = 'landsat'
    AND extract(year from s.capture_date) = y.y)
GROUP BY 1;
```

**Healing candidate set (recommended, in order):**

| Parcel | Missing | Note |
|---|---|---|
| `7397388e-9b2f-40af-8c4b-cd92aa2184c5` | 20 Landsat years | Known 2026-08-11 incident |
| `e0cb3db9-a7d5-4cf5-9c72-9be8f9a968c2` | 8 Landsat years | **New**, 2026-08-12 00:45Z |
| `2b398698-8235-4e71-b6e1-370e274f1ca6` | acs5 2021, decennial 2020 | Census timeouts, today |
| `177681ef-aa0f-46b8-9453-15a9cc89ef34` | acs5 2018 | Vintage-break residue; survived a re-run |
| `5d3a7b3a-1610-4ac2-95f7-5209de3fd18b` | all topo | Zero rows, task says complete |

**Heal only after the throttle fix is deployed** — otherwise the re-run is exposed to
the same unthrottled signing path that caused the damage.

## Appendix B — Access method

Queries ran read-only over `fly ssh console -a log0s-plotline-api`, executing a
base64-encoded Python payload through the app's own SQLAlchemy engine (`psql` is not
in the image; `Dockerfile.fly` installs only `libpq-dev`). Every session opened with:

```sql
SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;
SET statement_timeout = '60s';
```

No file was written to any production machine; no `UPDATE`, `INSERT`, or `DELETE` was
issued; no config or scale was changed.
