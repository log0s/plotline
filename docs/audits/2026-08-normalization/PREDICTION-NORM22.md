# Prediction — NORM-22 startup mint, scored at the next production deploy

Written 2026-08-29, branch `norm22-startup-mint`, before any production
observation of this fix. **This session made no production reads or writes**
(the branch prompt forbids production access of any kind); the observable
below is scored by a **later session**, at the next production deploy that
carries this branch's commits — plausibly step 4's deploy. That session must
score this file rather than edit it, per the audit norms: append a dated
"Scored" section, do not alter the prediction.

## What is being predicted

The fix (`schedule_startup_mint()`, wired into `app/main.py`'s lifespan)
mints all three known `(account, container)` pairs into the Redis-backed
cache `_container_token` reads, in the background, before the app takes
traffic. If it works, the specific 502 STEP3-PROD-REPORT.md §5/F2 observed —
a Landsat tile 502 in the first minutes after a deploy, caused by a cold
container-token re-mint hitting the request path's 2.0 s `SIGN_WAIT_REQUEST`
budget against a PC 429's 18–19 s advised wait — should not recur in that
window.

**Scope, carried from the branch prompt into this prediction verbatim: this
closes the deploy-triggered instance of the class, not the class.** A
sustained 429 storm arriving mid-traffic (not at boot) still hits the same
2.0 s wall — that is O1 act two / G4 territory, untouched by this fix. A
clean deploy window proves nothing about that case, and no later session may
cite this prediction's confirmation as evidence the request path survives a
429 storm.

**A second scope note, from this session's own investigation
(`NORM22-REPORT.md` §1).** F2 and NORM-22 attribute the 502 to a deploy
emptying an "in-process" cache; the code shows the cache is Redis-backed and
unaffected by an API/worker deploy (Redis is a separate Fly app). The more
defensible mechanism is idle-period token TTL expiry (~45 min) that a
deploy's own post-deploy traffic is likely to trip first, in a low-traffic
app. **This prediction does not depend on which mechanism is right** — the
startup mint guarantees a warm token exists before post-deploy traffic
regardless of why the previous one went cold — but a later session should
read this before concluding "confirmed" means "the deploy-emptying theory
was correct." It means "the observable window was clean," which is true
under either mechanism.

## The observable

**N = 10 minutes** from the deploy's health-check-passing timestamp (the
same anchor STEP3-PROD-REPORT.md §5 used: machine restart, not traffic
start). Ten minutes covers the ~7-second window the one observed incident
took to self-clear by more than 80×, with margin for a slower PC response
under real load.

Within that window, on every API machine (`fly logs -a log0s-plotline-api`,
scoped to the deploy timestamp):

1. **The mint log lines are present at boot, once per container, per
   machine.** Grep: `"SAS startup mint succeeded"` — expect exactly 3 lines
   (or fewer, each backed by a matching `"SAS startup mint failed"` line for
   any that didn't recover; see clause 3). Grep for the container labels
   specifically: `container=naipeuwest/naip`,
   `container=sentinel2l2a01/sentinel2-l2`,
   `container=landsateuwest/landsat-c2`.
2. **Zero cold-cache 502s.** Grep: `"Titiler returned 500"` cross-referenced
   against a `502` response in the same window — none should trace back to
   `"SAS signing failed; retry exceeds wait budget, giving up"` fired within
   60 s of that machine's `"Plotline API starting"` line.
3. **Zero re-mint 429s in the startup window.** Grep:
   `"SAS signing failed; retry exceeds wait budget, giving up"` with
   `wait_s` in the 18–19 s range (PC's advised wait for this endpoint) — none
   should appear within N minutes of a `"Plotline API starting"` line on the
   same machine. A 429 *outside* that window (ordinary mid-traffic
   throttling) is not a falsification of this prediction — see the O1/G4
   scope note above.

## What would falsify it

- A `"SAS startup mint succeeded"` line missing for any of the three
  containers on any API machine, with no corresponding
  `"SAS startup mint failed"` line either — the mint didn't run at all
  (wiring broken, e.g. `schedule_startup_mint()` not reached, or
  `_startup_mint_tasks` garbage-collected before running).
- Any cold-cache 502 (clause 2) inside the N-minute window — the fix ran
  but didn't close the gap it was built for.
- A container name mismatch: a mint log line naming a container that never
  appears in a real signed URL (would mean `STARTUP_MINT_CONTAINERS` in
  `stac.py` names the wrong container and pre-warms a cache key the request
  path never reads).

## What would not falsify it (deviations, not failures)

- A `"SAS startup mint failed"` line for any container, provided no cold
  502 for that container followed within the window — this is the
  documented degrade-to-today's-behaviour path, not a bug.
- A 429 or a 502 *outside* the N-minute post-deploy window — mid-traffic
  storms are out of scope (see above).
- The worker's logs showing no mint-at-startup lines at all — by design
  (`NORM22-REPORT.md` §3), the worker was not given this fix; its 60 s
  batch budget already absorbs a re-mint.

---

## Observed — production, 2026-08-29 deploy of `174892cc`

*(Appended by the snapshot-enrich production session. Everything above this
line is as committed in `dd6d881` and has not been edited.)*

**Verdict: confirmed, on all three clauses, with full window coverage — and
the window contained the failure mode's own trigger rather than merely being
quiet.**

### The deploy this scores

`GET /api/v1/health` → `{"sha":"174892cc8164d4df7a915db279b4c77f569e1921",
"built":"2026-08-29T17:41:26Z"}`. That sha contains `06f8f59` by way of the
merge `0f193be` (`git merge-base --is-ancestor 0f193be 174892cc` exits 0), and
`GH_SHA=174892cc…` on 4 of 4 machines of both apps. **This is the "next
production deploy" this prediction defers to.**

Anchor per the prediction's own rule (machine restart, not traffic start):

| machine | `Plotline API starting` | window N = 10 min ends |
|---|---|---|
| `825d69b7e46618` | 17:41:59.371Z | 17:51:59Z |
| `48e0de9a713918` | 17:42:17.957Z | 17:52:17Z |

**Coverage is complete, not a floor.** `fly logs -a log0s-plotline-api
--no-tail` returns a capped 100-line page; on this low-traffic app that page
spans 07:54:34Z → the buffer head continuously, so it contains every line both
machines emitted in both windows. The buffer was proved live rather than
assumed: a probe `ssh` at 17:54:09Z appeared in the next capture, establishing
that the empty span 17:47:16Z → 17:54:09Z is *no lines emitted*, not *lines
not yet retrieved*. Capture committed unedited: `norm22-deploy-window.txt`.

### Clause 1 — the mint lines are present, once per container, per machine

**6 of 6 `"SAS startup mint succeeded"` lines, 0 `"SAS startup mint failed"`.**

| machine | naipeuwest/naip | sentinel2l2a01/sentinel2-l2 | landsateuwest/landsat-c2 |
|---|---|---|---|
| `825d69b7e46618` | 17:42:00.254Z | 17:42:00.007Z | 17:42:10.139Z |
| `48e0de9a713918` | 17:42:18.587Z | 17:42:19.034Z | 17:42:18.845Z |

Each is preceded by its own `"SAS container token minted container=…"` line,
so the mint reached the cache and did not merely log. **No container-name
mismatch:** the three labels are exactly the three the request path reads, and
`sentinel2l2a01/sentinel2-l2` carries no stray trailing `a` (STATUS.md
NORM-22's own correction, confirmed against a second production reading).

Every mint completed **before** its machine's window: the last one landed
17:42:19.034Z, 11.1 s after `48e0de9a713918`'s `Application startup complete`.

### Clause 2 — zero cold-cache 502s, and the clause is not vacuous

**0 occurrences of `"Titiler returned 500"`, `"Band signing failed"`, or any
502 in either window.**

A quiet window on a low-traffic app would prove nothing, so **the request path
was exercised inside the window on purpose**: a Landsat tile —
`GET /api/v1/imagery/cc8292b9-eafb-4509-a306-055084b04542/tiles/8/47/102`
(scene `LC09_L2SP_037037_20260817_02_T1`) — at **17:47:22Z, 5 min 23 s after
`825d69b7e46618` booted**, returned **HTTP 200, 76,732 bytes, 4.18 s**. That
is the same route, the same source and the same signing path that produced the
502 at 06:39:42Z on 2026-08-29 (STEP3-PROD-REPORT.md §5/F2), inside the window
that incident was inside. **It served.**

### Clause 3 — zero re-mint 429s in the startup window, and the stronger reading

**0 occurrences of `"SAS signing failed; retry exceeds wait budget, giving
up"` anywhere in either window.**

The finding worth more than the zero: **`825d69b7e46618` met the 429 anyway,
and the fix absorbed it.** At 17:41:59.793Z — 0.42 s after
`Application startup complete` — the startup mint for `landsateuwest/landsat-c2`
drew `429 Too Many Requests` on `…/sas/v1/token/landsateuwest/landsat-c2`,
backed off `wait_s=8.43`, drew a second 429 at 17:42:08.840Z, backed off
`wait_s=1.11`, and minted at 17:42:10.111Z with `ms=10563`.

**Ten and a half seconds of throttled signing, on the exact container and the
exact endpoint of the original incident, resolved with no user-visible
effect.** It resolved because a startup mint spends `SIGN_WAIT_BATCH` (60 s),
not the request path's `SIGN_WAIT_REQUEST` (2.0 s): 10.56 s fits comfortably
in the first budget and exceeds the second by 5×. **Pre-fix, that same 429
arriving on the first Landsat tile request after this deploy is the 502.** The
window did not merely avoid the failure mode; it contained the trigger and
converted it into a 10-second boot delay nobody could observe.

`48e0de9a713918`, minting 19 s later, met no 429 at all — consistent with the
first machine's mint having already paid the throttle.

### Falsifiers, checked one by one

| Falsifier | Observed |
|---|---|
| A mint line missing for any container on any machine, with no matching failure line | **none** — 6 of 6 succeeded |
| Any cold-cache 502 inside N | **none**, and a real Landsat tile inside N returned 200 |
| A container name mismatch | **none** — all three labels match the request path's keys |

### Scope, restated so this confirmation is not over-read

Per this prediction's own terms and the branch prompt's: **this scores the
deploy-triggered instance of the class, not the class.** The 429 absorbed here
arrived *at boot*, where the 60 s budget applies. A sustained 429 storm
arriving mid-traffic still meets the request path's 2.0 s wall — O1 act two /
G4 territory, untouched by this fix and untouched by this observation. Nothing
here is evidence about that case.

And per the prediction's second scope note: "confirmed" means **the observable
window was clean**, which is true under either candidate mechanism (a deploy
emptying the cache, or idle-period TTL expiry). This session did not
discriminate between them and did not try to.
