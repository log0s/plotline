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
