# Titiler Cache Fix — Boundary Baseline

Observation-only record of the first container-token rotation boundary
observed under `30caec4`, on **2026-08-12**. Purpose: score the §5 prediction
in `FINDINGS.md`, and capture the G7 mint-count baseline via the per-mint log
added in `30caec4` (`stac.py:361`).

Nothing here was acted on. All production access was `GET`s against the public
API, `fly logs`, and `fly image show`. No queueing, no heal script, no deploy,
no DB write, no direct call to Planetary Computer's token endpoint — every
mint counted below was triggered server-side by tile browsing, which is the
measurement.

---

## 0. Gate

| Check | Result |
|---|---|
| `GET /api/v1/health` | `sha=30caec4237bf3aef7aad898a1eb7955297b397d3`, built `2026-08-12T19:53:27Z` |
| `fly image show -a log0s-plotline-api` | `GH_SHA=30caec4…` (both machines) |
| `fly image show -a plotline-worker` | `GH_SHA=30caec4…` (both machines) |

Gate passed. The fix (`cf0df2b`) and the mint log (`30caec4`) are both running.
Observation began ~3 min after the deploy.

## 0.1 Capture coverage

Continuous `fly logs` streams for both apps were started at **19:57:2xZ**
(before any boundary), with `fly logs --no-tail` polls every 55 s as the safety
net — the ordering `HEAL-SCORECARD` §0 arrived at the hard way.

| Window | Coverage |
|---|---|
| 19:57:2xZ → 20:49:2xZ | continuous stream, both apps |
| 20:02:09Z → 20:41:04Z | polls, 80 files, in addition to the stream |

**No gaps in the measured window.** The streams are a strict superset of the
polls: of 29 distinct mint lines the polls captured, 0 appear that the stream
missed (`comm -23 poll_mints stream_mints` → empty). The counts below are exact,
not floors. Backlog before 19:56:49Z is pre-deploy and is excluded from all
counts except where explicitly labelled.

One instrumentation failure, with no data cost: a live `Monitor` armed on the
stream emitted no events, because its `cut -c1-200` stage block-buffers even
with `grep --line-buffered` upstream. The files it was reading were complete
throughout; only the live notifications were lost. Recorded so the next
observer does not re-lose it.

---

## 1. The boundary is the Redis TTL, not the token lifetime

§5 anticipates a boundary at the 45-minute token expiry. The observable
rotation boundary is **20 minutes**, not 45.

`?v` is `container_token_expiry()`, which reads the token *cached in Redis*
under `sas-token:{account}/{container}`. That key is written with
`_SAS_CACHE_TTL = 1200` s (`stac.py:174`). So the key vanishes 20 min after its
mint and the next request mints a fresh token — while the token it replaces is
still valid for another ~25 min. The cache key therefore rotates on the
**mint + 20 min** cadence, ~25 min before the credential it names expires.

This makes the fix *more* conservative than §4's argument claims, not less: a
cached Titiler item is discarded roughly 25 minutes before its pinned token
could possibly go stale. It also means rotation events are 2.25× more frequent
than §5 assumed, which is the load term G7 inherits.

Observed cadence, all from the mint log:

| Mint | `se` (token expiry) | Redis key dies | Next mint observed |
|---|---|---|---|
| 19:56:48–49Z | 20:41:48/49Z | 20:16:49Z | 20:17:06Z |
| 20:17:06Z | 21:02:06Z | 20:37:06Z | 20:47:41Z |
| 20:47:41Z | 21:32:40/41Z | 21:07:41Z | — |

The 20:37:06Z expiry produced no mint at 20:37 because no Landsat request
arrived until sweep B at 20:47:38Z. Mints are demand-triggered at the first
request *after* expiry, not scheduled at it — so the boundary is a property of
traffic, not of the clock, and an idle period simply defers it.

---

## 2. The herd

From **20:13:30Z to 20:22:30Z** — ~3 min before the 20:16:49Z boundary through
~5 min after — 18 distinct Landsat snapshots (3 each across all six featured
parcels, so 18 distinct `/stac` cache keys) were browsed in 24 waves, at
concurrency 6 with a 0.3 s per-request stagger and ~20 s between waves.
Realistic browsing load, not a load test.

**432 requests, 432 × 200 OK, 0 non-200.** No client-side error of any kind,
so no bodies with curated messages to record.

The boundary is unmistakable in the latency, and only in the latency:

| Wave | Time | Median ms | p90 | Max |
|---|---|---|---|---|
| 7 | 20:16:25Z | 494 | 1339 | 1444 |
| 8 | 20:16:48Z | 506 | 1380 | 1672 |
| **9** | **20:17:12Z** | **2138** | **2904** | **3325** |
| 10 | 20:17:31Z | 1300 | 1878 | 2372 |
| 11 | 20:17:53Z | 915 | 1964 | 2371 |
| 12 | 20:18:13Z | 568 | 1580 | 2265 |

Wave 8 was the last wave before the Redis key died; wave 9 was the first after.
Median tile latency rose **4.2×** (506 → 2138 ms) for exactly one wave, decayed
across waves 10–11, and was back at baseline by wave 12 (~60 s after the
boundary). Wave 1 shows the same shape (2188 ms) for the unrelated reason that
Titiler's item LRU was cold for those 18 keys on first browse.

That spike is the whole cost of the fix, made visible: every key rotates at
once, every item is refetched once, and the refetch is one container-token
round-trip plus local derivations — §4.1's model, holding in production.

---

## 3. Counts at the boundary (20:17:06Z ±5 min)

| Quantity | Count | Detail |
|---|---|---|
| **M** — "SAS container token minted" (landsat) | **6** | all at 20:17:06Z, all `se=2026-08-12T21:02:06Z`, `ms` = 673, 670, 670, 679, 828, 830 |
| **K** — exhausted-backoff / signing-failure lines | **0** | no `"backoff exceeds wait budget"` in window |
| "SAS rate-limited; backing off" | **0** | — |
| Titiler 500s (log-side) | **0** | no `Titiler request failed`, no `logger.error` from `app.api.v1.imagery` |
| API 502s (client-side) | **0** | of 432 herd requests |
| "SAS token expiry unavailable" fallbacks | **0** | as expected; no `?v=t…` bucket form was ever live |
| Worker mints during browsing | **0** | `plotline-worker` logged 0 mint lines for the entire session |

All 6 mints came from a single API machine (`48e0de9a713918`). The `825d69b7…`
machine minted nothing at this boundary.

**The no-single-flight signature of §4.2, confirmed in production.** Six
concurrent misses each minted their own token in the same second, all six
returning tokens that expire at the identical `se`. The mint latency (670–830
ms) is the window: any request arriving inside that ~0.8 s finds no cached
token and mints its own. The winner's `setex` closes the window, which is why 6
concurrent mints — not 18, and not the 54 that 18 snapshots × 3 bands could
have produced — served an 18-key rotation.

The same signature is visible twice more, at boundaries not driven by the herd:

| Boundary | Landsat mints | `ms` range | Notes |
|---|---|---|---|
| 19:56:48–49Z | 3 | 197–640 | one `/stac` callback, one mint per band signing |
| **20:17:06Z** | **6** | **670–830** | the herd; 18 keys rotating together |
| 20:47:41Z | 2 | 246–669 | sweep B's first request |

The 19:56 case is the sharpest: a **single** `/stac` callback signing three
bands produced three mints, because the three band signings race each other
inside one request. Fan-out is per concurrent signing, not per request.

Non-Landsat containers show the same behaviour and set the scale G7 should
expect: at 19:56:31–32Z, `sentinel2l2a01/sentinel2-l2` minted **13** tokens and
`naipeuwest/naip` minted **8**, within ~1.5 s of each other. Landsat is not
special here; it is simply the container this investigation instrumented.

---

## 4. Rotation check (§5 item 2)

`?v` is not observable client-side — the browser only ever sees
`/api/v1/imagery/{id}/tiles/{z}/{x}/{y}`, and `api_internal_url` is a Flycast
address. The `se` on the signed band hrefs in `GET /imagery/{id}/stac` is the
same value from the same Redis key that `container_token_expiry()` reads for
`?v`, so it is the faithful read-only proxy. Same snapshot
(`cf46ed63…`'s 1984 Landsat item) throughout:

| Sample | `se` on band hrefs |
|---|---|
| 19:56:47Z (before boundary) | `2026-08-12T20:41:48Z` and `…49Z` |
| 20:02:51Z (before boundary) | `2026-08-12T20:41:49Z` |
| 20:31:00Z (after boundary) | `2026-08-12T21:02:06Z` |

- Two samples inside one token's life → **same** value. ✅
- Samples spanning the boundary → **different** values. ✅
- The post-boundary value **equals the `se` on the boundary's mint lines**
  (`21:02:06Z`). ✅
- No `?v=t…` fallback form, and 0 "expiry unavailable" warnings — the
  Redis/signer path was healthy throughout. ✅

`Cache-Control: private, max-age=900` was present on every `/stac` response, as
`cf0df2b` intends.

One detail worth keeping: at 19:56:48–49Z the three bands of a single item came
back carrying **two different tokens** (`se=…48Z` on green, `…49Z` on red and
blue) — the three racing mints of §3, visible in the response body itself. The
tokens are interchangeable in every way that matters (same container, same
grant, expiries 1 s apart), so this is a curiosity, not a defect. But it means
`?v` and the hrefs it versions can disagree by one mint generation for the
lifetime of the per-URL signed-URL cache. The race is still one-directional, as
§4 argues: the item can only ever receive a token at least as fresh as the one
`?v` names.

---

## 5. §5 verdict

Scored against `FINDINGS.md` §5's own criteria and its own protocol: two full
sweeps of 43 years × 6 featured parcels = **258 snapshots**, ≥45 min apart, the
second after the boundary traffic. Concurrency 6, staggered.

| Sweep | Window | Result |
|---|---|---|
| **A** | 19:58:25Z → 20:00:22Z | **258/258 200 OK**, 0 non-200 |
| **B** | 20:47:38Z → 20:49:24Z | **258/258 200 OK**, 0 non-200 |

Gap between sweep starts: **49.2 min** — one full token lifetime, satisfying
§5's requirement.

| §5 prediction | Verdict |
|---|---|
| 1. Expired-`se` Titiler 500s cease within one token lifetime of deploy | **CONFIRMED** |
| 2. `?v` observed rotating across a token boundary; stable within one | **CONFIRMED** |
| 3. Unfixed production would re-poison (control) | **NOT INDEPENDENTLY TESTABLE** — see below |

**Item 1 — confirmed, and the control §5 demands is satisfied.** §5 is explicit
that a clean sweep sooner than 45 min after a browse proves nothing, because
cache churn alone produces one. Sweep B is not that sweep. Sweep A browsed all
258 snapshots at 19:58Z, seeding Titiler's item LRU while the live token was
`se=2026-08-12T20:41:49Z`. Under the *unfixed* code those 258 entries would
have been keyed on a constant URL, would have survived in the LRU untouched
(258 entries, `maxsize=512`, no expiry), and every one of them would have been
serving a token expired since 20:41:49Z by the time sweep B ran at 20:47:38Z.
That is precisely the 04:17Z failure, reproduced by construction. Sweep B found
**0 failures in 258**. Combined with 432 clean herd requests straddling a live
rotation and 0 Titiler errors in the logs across the whole session, item 1 is
confirmed on the strongest evidence the read-only protocol admits.

**Item 3 — not independently testable, by construction.** It is a counterfactual
about unfixed code, and unfixed code is no longer running. Its evidentiary role
is served by the sweep A → sweep B pairing above, which is the same experiment
run against the fix. Recorded as untestable rather than passed, because scoring
a prediction on evidence it did not ask for is how records drift.

### What §5 did not anticipate

1. **The boundary cadence is 20 min, not 45** (§1). §5's sampling advice —
   "more than 45 min apart yields two different values" — is true but not tight;
   samples 21 min apart also differ. Anyone re-running this should not conclude
   the fallback bucket is live merely because `?v` changed sooner than expected.
2. **Rotation is demand-triggered, not clock-triggered.** No traffic, no mint;
   the 20:37:06Z expiry passed unremarked and the mint landed at 20:47:41Z with
   sweep B's first request. A rotation "boundary" cannot be scheduled for
   observation without also generating the traffic that causes it.
3. **The mint fan-out is per concurrent band signing, not per request.** One
   `/stac` callback produced 3 mints at 19:56. §4.2 frames the risk as
   concurrent *misses*; the sharper statement is that a single request is
   already concurrent with itself.
4. **The cost of the fix is a one-wave latency spike, not errors** (§2). 4.2×
   median for ~20 s, fully decayed within ~60 s, zero failures. This is the
   number to watch if the rotation ever does turn harmful.
5. **Landsat is not the largest herd.** Sentinel-2 minted 13 and NAIP 8 in a
   single cold window, against Landsat's 6. G7's scope is `_container_token`,
   not the Landsat path that led us to it.

---

## 6. G7 handoff

The 6-mint figure is a **baseline, not a ceiling**. It was measured on 18 keys
at concurrency 6 from one client against a 2-machine API; the bound is the mint
latency (~0.8 s) times the arrival rate, so a real herd — six timelines opened
at once, 43 keys each, across both machines — would mint more. The 13 observed
on `sentinel2-l2` in one cold window is the better indication of the scale
available. Nothing here rate-limited: `K=0`, and the only 429 backoff lines in
the capture are pre-deploy backlog from 18:45Z.

BASELINE: 6 minted + 0 exhausted at boundary 2026-08-12T20:17:06Z; worker mints: none; ms range: 670–830

---

# Addendum, 2026-08-12 — the post-fix boundary

The same observation, repeated against `b2019e4` (`2168124` + `e8c857c`
deployed), scoring the four-clause prediction in `FINDINGS.md`'s
2026-08-12 addendum. Nothing above is edited; §1–§6 stand as the record of the
unfixed behaviour.

Observation only. All production access was `GET`s against the public API,
`fly logs`, and `fly image show`. No queueing, no heal script, no deploy, no DB
write, no direct call to Planetary Computer's token endpoint — every mint
counted below was triggered server-side by tile browsing.

## A0. Gate

| Check | Result |
|---|---|
| `GET /api/v1/health` | `sha=b2019e483b5913890f4e242e2b3f0687cc19b52c`, built `2026-08-12T21:13:32Z` |
| `fly image show -a log0s-plotline-api` | `GH_SHA=b2019e4…` (`825d69b7e46618`, `48e0de9a713918`) |
| `fly image show -a plotline-worker` | `GH_SHA=b2019e4…` (`e2862966b306d8`, `e7845415f57728`) |

Gate passed on both apps, both machines.

## A0.1 Capture coverage

Four independent captures, all started before the boundary:

| Capture | Span |
|---|---|
| `fly logs` streams, both apps | 21:28:00Z → 22:11:00Z |
| `fly logs` streams under a pty, both apps | 21:52:53Z → 22:11:00Z |
| `--no-tail` polls @55 s, both apps | 21:28:13Z → 22:10:51Z (45 files/app) |
| `--no-tail` polls @25 s, both apps | 21:53:14Z → 22:10:59Z (41 files/app) |

**No gaps in the measured window.** The boundary window (22:04:12Z ±5 min =
21:59:12Z–22:09:12Z) sits entirely inside every capture, and **all four
independently contain both** 22:04:12Z mint lines. The counts below are exact,
not floors.

One instrumentation scare, recorded so the next observer does not repeat it:
the plain `fly logs` streams wrote nothing for 25 minutes, which read as the
block-buffering failure `HEAL-SCORECARD` §0 warns about. Duplicate pty-backed
streams were started at 21:52:53Z on that suspicion. The suspicion was wrong —
this API emits **no log lines at all during normal tile serving**; between
21:24:12Z and 22:04:12Z the only lines of any kind, from any capture, are the
mints themselves. The plain streams were quiet, not stuck, and hold both
boundary mints. Silence in this log is not evidence of a dead stream, and the
mint line is the only heartbeat available.

## A1. Boundary location, and the cadence claim

The landsat-c2 token in force at the start of observation was minted at
**21:24:12Z** with `se=2026-08-12T22:09:12Z`. Under `e8c857c` its Redis key
dies at `se − 300 s` = **22:04:12Z**, and that is where the boundary was
planned and where it landed — to the second.

| | Mint | `se` | Key dies | Next mint |
|---|---|---|---|---|
| Pre-fix (§1) | 20:17:06Z | 21:02:06Z | 20:37:06Z (mint + 20:00) | 20:47:41Z (deferred) |
| **Post-fix** | **21:24:12Z** | **22:09:12Z** | **22:04:12Z (mint + 40:00)** | **22:04:12Z** |

Consecutive landsat-c2 mints fell **exactly 40 min 0 s apart** (21:24:12Z →
22:04:12Z), against 20 min under the fixed TTL. The keepalive (one tile request
every ~2 min, 20 requests, all 200) held demand continuous across the whole
interval, so this is the demand-saturated cadence, not a deferred one — the
distinction §1 had to make for the 20:37:06Z expiry does not arise here.

## A2. The herd

From **22:01:12Z to 22:09:24Z** — ~3 min before the 22:04:12Z boundary through
~5 min after — the same 18 distinct Landsat snapshots (3 each across all six
featured parcels) were browsed at concurrency 6 with a 0.3 s per-request
stagger and 20 s between waves.

**288 requests, 288 × 200 OK, 0 non-200.** No client-side error of any kind, so
no bodies to record.

Protocol deviation from §2, stated because it bears on the decay reading: 16
waves at ~28 s spacing here, against §2's 24 waves at ~21 s. Concurrency,
stagger and URL set are identical; the wider spacing is per-request `curl`
subprocess overhead in this run's harness. Wave *counts* either side of the
boundary are therefore the like-for-like comparison, and wall-clock decay reads
~33% long against §2 for that reason alone.

| Wave | Time | Median ms | p90 | Max |
|---|---|---|---|---|
| 1 | 22:02:18Z | 1736 | 3226 | 4387 |
| 2 | 22:02:47Z | 1372 | 2691 | 3173 |
| 3 | 22:03:15Z | 1335 | 1829 | 1923 |
| 4 | 22:03:43Z | 455 | 1577 | 1700 |
| **5** | **22:04:11Z** | **1960** | **2630** | **3318** |
| 6 | 22:04:41Z | 1530 | 2024 | 2734 |
| 7 | 22:05:09Z | 1383 | 1915 | 2472 |
| 8 | 22:05:36Z | 1236 | 1622 | 1887 |
| 9 | 22:06:04Z | 367 | 1526 | 1663 |
| 10 | 22:06:32Z | 348 | 1387 | 1563 |
| 11 | 22:07:00Z | 369 | 1441 | 1869 |
| 12 | 22:07:28Z | 455 | 1481 | 1859 |
| 13 | 22:07:56Z | 504 | 1773 | 2699 |
| 14 | 22:08:22Z | 450 | 1471 | 2914 |
| 15 | 22:08:50Z | 424 | 1422 | 1529 |
| 16 | 22:09:18Z | 448 | 1390 | 1634 |

Wave 4 was the last wave before the key died; wave 5 straddles it. Median rose
**4.3×** (455 → 1960 ms) for exactly one wave, then decayed monotonically
across waves 6–8 and was back at baseline by wave 9.

Waves 1–3 are the cold-LRU shape §2 saw in its wave 1, stretched over three
waves because this run's keepalive touched only one of the 18 keys every 2 min
and so left most of the item cache cold. Their decay (1736 → 1372 → 1335 → 455)
is nearly identical in shape to the post-boundary decay (1960 → 1530 → 1383 →
1236 → 367), which is what §4.1's model predicts: a rotation *is* a cold LRU for
every key at once, so the two curves should coincide. They do.

## A3. Counts at the boundary (22:04:12Z ±5 min)

| Quantity | Count | Detail |
|---|---|---|
| **M** — "SAS container token minted" (landsat-c2) | **2** | both at 22:04:12Z, both `se=2026-08-12T22:49:12Z`; one per machine — `48e0de9a713918` `ms=238`, `825d69b7e46618` `ms=657` |
| Mints per (machine, container) | **1** | max group size, both groups |
| **K** — exhausted-backoff / signing-failure lines | **0** | no `backoff exceeds wait budget`, no `Band signing failed after retries` |
| "SAS rate-limited; backing off" | **0** | — |
| Titiler 500s (log-side) | **0** | no `Titiler request failed`; zero `error` or `warning` level lines in the window from any capture |
| API 502s (client-side) | **0** | of 288 herd requests + 20 keepalive requests |
| "SAS token expiry unavailable" | **0** | the 120 s fallback bucket never ran |
| Worker mints | **0** | `plotline-worker` logged 0 mint lines for the entire session |

**The single-flight signature, in production.** §3's six concurrent mints
returning the identical `se` from one machine are gone: an 18-key rotation now
costs one mint per machine. Both machines participated, which is the accepted
per-process bound `2168124` documents, not a miss.

The cold-start window at 21:23–21:24Z, captured incidentally before the herd,
is the sharper comparison because §3's largest herds were also cold starts:

| Container | Cold-start mints, pre-fix (§3) | Cold-start mints, post-fix (21:23–21:24Z) |
|---|---|---|
| `sentinel2l2a01/sentinel2-l2` | 13 | **1** |
| `naipeuwest/naip` | 8 | **1** |
| `landsateuwest/landsat-c2` | 6 | **2** (1 per machine) |

Both non-Landsat containers reached their own key-death moment inside the
capture (`se=22:08:25Z`, so keys died at 22:03:25Z) and minted **nothing**,
because no sentinel2 or NAIP request arrived — the herd and keepalive are
Landsat-only. Their post-fix boundary is therefore *not* exercised by this run;
the 1-and-1 above are cold-start mints, not boundary mints. Recorded as
unexercised rather than passed.

## A4. Rotation check

Same snapshot as §4 (`cf46ed63…`'s 1984 Landsat item, `4eb53b4e…`), read from
the `se` on the signed band hrefs:

| Sample | `se` on band hrefs | `Cache-Control` |
|---|---|---|
| 21:28:20Z (before boundary) | `2026-08-12T22:09:12Z` | `private, max-age=900` |
| 21:52:06Z (before boundary) | `2026-08-12T22:09:12Z` | `private, max-age=724` |
| 22:07:35Z (after boundary) | `2026-08-12T22:49:12Z` | `private, max-age=900` |

- Two samples inside one token's life → **same** value. ✅
- Samples spanning the boundary → **different** values. ✅
- Post-boundary value **equals the `se` on the boundary mint lines**
  (`22:49:12Z`). ✅
- No `?v=t…` fallback form, 0 expiry-unavailable warnings. ✅

The middle sample is the cadence claim tested directly: **23 min 46 s** after
the first, and unchanged. Under the fixed 1200 s TTL that key would have died
at 21:44:12Z and this sample would have carried a different `se` — §5's "what
§5 did not anticipate" item 1, now inverted by `e8c857c`.

§4's curiosity is also gone: all three bands returned the **identical** `se` in
all three samples, where §4 recorded one `/stac` callback producing tokens 1 s
apart on green vs red/blue. That is `2168124` coalescing the intra-request band
race the seam was placed below, visible in the response body.

## A5. Verdict

| Prediction clause | Verdict |
|---|---|
| 1. ≤1 mint per boundary, per process, per container | **CONFIRMED** — 2 landsat-c2 mints at 22:04:12Z, max group size 1 per (machine, container). Cold-start comparison: sentinel2-l2 13 → 1, naip 8 → 1. |
| 2. `K` stays 0 | **CONFIRMED** — K = 0, no 429 backoff lines, 0 error/warning lines, 0 non-200 of 308 client requests. |
| 3. Latency spike unchanged in shape | **CONFIRMED on magnitude, DEVIATION on decay** — 4.3× vs the predicted ~4.2×, one wave, as predicted; decay took 113 s (4 waves) against §2's ~60 s (3 waves). See below. |
| 4. Cadence moves ~20 min → ~40 | **CONFIRMED** — consecutive landsat-c2 mints exactly 40 min 0 s apart, under continuous demand; `se` samples 23 min 46 s apart agree. |

**Clause 3, the deviation.** The magnitude clause is the load-bearing one and it
held almost exactly: 4.3× against a predicted 4.2×, for exactly one wave. The
decay clause did not: 113 s to return to baseline against §2's ~60 s. Recorded
as a deviation and not as a pass, though two things argue it is measurement and
not regression. This run's waves are ~28 s apart against §2's ~21 s, so the
same *three*-wave decay would already read ~84 s; and the observed decay is
four waves, one more than §2's three. The residual is consistent with this
run's colder item cache — waves 1–3 show the same four-wave shape from a cold
start with no rotation involved at all. What it is *not* consistent with is
mints dominating: mint latency fell from 670–830 ms to 238/657 ms and the count
fell from 6 to 2, so if mints had been the dominant term the spike would have
shrunk. It did not, which is the prediction's own stated reasoning holding.

No clause was falsified. Refresh-ahead stays rejected on its own terms: the
reopening evidence `FINDINGS.md` names — `K` > 0 or 429s at a boundary after
both fixes are deployed — did not appear.

POST-FIX: 2 minted (1 per machine) + 0 exhausted at boundary 2026-08-12T22:04:12Z; worker mints: none; ms: 238, 657; cadence 40 min 0 s; spike 4.3× one wave, decayed in 113 s
