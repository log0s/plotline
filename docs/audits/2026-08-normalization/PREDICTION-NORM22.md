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
