# Step 3 in production — the serving reads cut over

Session of 2026-08-29, 06:10–06:45Z. `STEP3-REPORT.md` §9's two-deploy
sequence, executed: Deploy A puts both read paths in production so the parity
harness can run there, the harness runs read-only against production, and
Deploy B is the cutover itself.

**Outcome. The cutover is deployed and serving.** The production parity run
compared **12,884 rows on each path across 189 parcels, 52,488 comparisons,
and found zero divergences of every class** — including NORM-18's
`resolution_m` population, which is **0** in production as predicted. Every
served id at every smoked surface now resolves in `parcel_scenes` and **not**
in `imagery_snapshots` (141 ids over two parcels, 141/0). The cooling period
for step 4 starts at **2026-08-29T06:41:47.270470Z**.

**Two findings, neither of them parity.** A commit prescribed for deployment
had never had the suite run at that commit and CI's guard rejected it (F1,
NORM-21). And 2 minutes 42 seconds after the cutover deploy, a Landsat tile
request returned **502** — NORM-16's G4 signing storm firing on the request
path for the first time since 2026-08-12, caused by the deploy emptying the
SAS container-token cache, not by the cutover (F2, NORM-22). Both are recorded
below with their evidence.

**Zero production writes by this session.** Every probe set
`default_transaction_read_only = on` and proved it with an `UPDATE … WHERE
false` before reading; both deploys were the owner's pushes.

---

## 1. Gates

### 1a. Deploy A — verified, not pushed

The plan of record (§9 item 1) said deploy `160e7ba`. It is not what is
deployed, and F1 is why.

| Check | Result |
|---|---|
| `origin/main` | `c96dbf8fb9a6ef27a4978a4074da5d159b2c65d7` |
| `160e7ba` ancestor of local head | yes |
| `b1acf9a` ancestor of local head | yes |
| working tree | clean |
| merge shape | `3c2ce01` merges `fix/harness-logging` into `a605d87`; deletion wins, harness absent at head |
| harness at `c96dbf8` | present — `git cat-file -e c96dbf8:scripts/compare_read_paths.py` |
| harness at local head | absent, as F4 of `STEP3-REPORT.md` describes |
| prod health sha | `c96dbf8…`, built `2026-08-29T06:08:28Z` |
| `GH_SHA`, all 4 machines | `c96dbf8…` × 2 api + 2 worker |
| `alembic_version` | `0017` |

The harness's interface was read from the deployed sha rather than assumed:
`main()` takes one optional `--out` and nothing else, and calls
`configure_script_logging()` first — the call CI demanded.

### 1b. Production state — spot re-verified against the prior session's pre-flight

Read 06:14–06:16Z. **Nothing moved between the 05:53Z pre-flight and the run.**

| Quantity | Pre-flight (05:53Z) | This session (06:14Z) |
|---|---|---|
| `scenes` | 6,663 | **6,663** |
| — by provenance | 6,156 snapshot / 505 enriched / 2 selection | **identical** |
| — `provenance = 'mosaic_url'` | 0 | **0** (absent from the group-by) |
| `parcel_scenes` | 12,884 | **12,884** |
| `imagery_snapshots` | 12,884 | **12,884** |
| `parcels` | 189 | **189** |
| `max(selected_at)` | 04:41:26Z | **04:41:26.056Z** |
| `selected_by` non-NULL | 7 | **7** |
| mosaic references / rows | 613 / 576 | **613 / 576** |

`scenes.max(fetched_at)` by provenance corroborates insert-only holding:
`enriched` still **2026-08-27T17:52:36Z**, `snapshot` still
**2026-08-27T19:17:26Z**, and only `selection` carries the sweep's
04:41:26.056Z. No dual-write traffic since step 2's sweep, so the
reconciliation-log check the prompt gated on had no delta to explain.

`parcel_scenes` by source: landsat 8,127 (= 189 × 43, exactly conserved),
sentinel2 2,259, naip 1,305, usgs_topo 1,193. `featured_locations` 6.

### 1c. Deploy B — verified after the owner's push

| Check | Result |
|---|---|
| `origin/main` | `18ddb8e83e3fb90307bec6bf70bd480978ab19d7` |
| `b1acf9a` ancestor of deployed sha | **yes** (`git merge-base --is-ancestor`) |
| `3c2ce01`, `c96dbf8` ancestors | yes |
| prod health sha | `18ddb8e…`, built `2026-08-29T06:37:11Z` |
| `GH_SHA`, all 4 machines | `18ddb8e…` × 2 api + 2 worker |
| machine versions | api v81 (06:37:36Z, 06:37:54Z), worker v72 (06:37:41Z, 06:37:52Z) |

The push carried this session's three record commits along with the cutover,
which is why the deployed sha is `18ddb8e` and not `3c2ce01`. They are
documentation only; `b1acf9a` is the code being deployed and its ancestry is
what the gate checked.

## 2. The parity run

```
fly ssh console -a log0s-plotline-api --machine 825d69b7e46618 -C \
  "sh -c 'cd /app; setsid nohup python scripts/compare_read_paths.py \
     --out /tmp/parity-prod.md > /tmp/parity-prod.log 2>&1 < /dev/null &'"
```

Launched 06:17Z at deployed sha `c96dbf8`, detached so a killed ssh client
could neither take the output nor be mistaken for an abort (NORM-8 / F5);
completed 06:32Z, ~15 minutes. Retrieved byte-for-byte by `fly ssh sftp get`
(583 bytes) and committed unedited as `parity-prod.md`.

The script's read-only guarantee is its own (`SET
default_transaction_read_only = on`, **committed** so it covers the
transactions that follow), and this session verified the same property
independently on every probe it ran.

**Result: 0 divergences.** 189 parcels · 12,884 rows on each path · 52,488
comparisons · 51,725 id pairs over 12,884 distinct old ids and 12,884 distinct
new ids · 12 fields per pair · 76 same-date reorderings · **"Item facts the
two shapes disagree about: None."**

## 3. Prediction scorecard

Committed as `6934770` **before** the run and never edited; scored in
`18ddb8e`. Full table in `PREDICTION-STEP3.md`.

**13 of 13 scorable quantities confirmed. 1 unobservable. No divergence of any
class, no unpredicted class.**

| | Predicted | Observed |
|---|---|---|
| parcels | 189 | **189** |
| rows old / new | 12,884 / 12,884 | **12,884 / 12,884** |
| id pairs | 51,725 | **51,725** |
| comparisons | 52,488 | **52,488** |
| distinct old / new ids | 12,884 / 12,884 | **12,884 / 12,884** |
| divergences | 0 | **0** |
| NORM-18 `resolution_m` population | 0 | **0** |
| `row_order` | 0 | **0** |
| same-date reorderings | nonzero, no point estimate | **76** |
| exit code | 0 | **not observed** |

**PP4 is the result worth keeping.** 51,725 id pairs was derived from the
harness's control flow before any production run — 3 × 12,884 for `listing`,
`listing[source=…]` and `by_id`, plus 12,884 + 189 for the two date windows,
on the stated prediction that **exactly one row per parcel shares that
parcel's midpoint capture date**. It landed exactly. The fragile assumption
held over all 189 parcels even though 76 same-date reorderings prove same-date
pairs are common elsewhere in the data.

**PP14 is scored unobserved rather than confirmed**, and the distinction is
the point. The `setsid nohup` launch that protects a long production run from
a killed ssh client also discards the process's exit status. The script
returns 1 if and only if `report.divergences` is non-empty and the capture
says 0, so the exit code was 0 — but that is an inference from the code and
the artifact, not a reading of `$?`. **Rule for the next detached production
run:** append `; echo $? > /tmp/<name>.rc` to the launched command, so the
status survives the client that started it.

**What this run establishes that the local one could not.** The local scoring
was of a prediction written with the answer already in hand
(`PREDICTION-STEP3.md` §0). This one was not: the harness had never been run
against production, and every structural and volumetric claim was derived
rather than remembered. The one exception is disclosed in the prediction's own
§P0 — PP12's zero reproduces a direct 12,884-pair measurement taken in the
pre-flight, so it confirms that two routes to that number agree, not a
forecast.

## 4. Post-cutover smoke

All read-only GETs against `https://log0s-plotline-api.fly.dev/api/v1`, plus
read-only DB probes.

| Surface | Result |
|---|---|
| `/featured` | **200**, 6 locations, each with `earliest_snapshot_id` / `latest_snapshot_id` |
| `/featured/stapleton-central-park` | **200** |
| `/parcels/1a67b7ae…/imagery` (Stapleton) | **200**, 69 rows |
| `/parcels/dc493cc5…/imagery` (Navy Yard) | **200**, 72 rows |
| `/imagery/c36e2ec7…/tiles/14/3418/6215` (NAIP) | **200**, 27,055 bytes `image/jpeg` |
| `/imagery/631cff38…/tiles/14/3418/6215` (Landsat) | **502**, then **200** on retry — F2 |

**The id space moved, measured.** All **141** served ids from the two listings
were probed against both tables:

| Parcel | served ids | resolve in `parcel_scenes` | resolve in `imagery_snapshots` |
|---|---|---|---|
| Stapleton `1a67b7ae` | 69 | **69** | **0** |
| Navy Yard `dc493cc5` | 72 | **72** | **0** |

That is NORM-19 observed rather than asserted, and it is also the cutover's
delete-the-fix evidence at the serving surface: not one id the API hands out
is resolvable in the old table.

`/featured`'s bounds agree with the listings: Stapleton's
`earliest_snapshot_id` `691bb19e-032c-46d8-8a12-8a9f9d3fd314` is the first row
of its listing (`usgs_topo`, 1890-01-01), and both ids are in the 69 probed.

**The mosaic reconstruction is exact.** Navy Yard is a NAIP-mosaic parcel;
`additional_cog_urls` cardinality was cross-checked against
`cardinality(mosaic_scene_ids)` row by row:

* rows carrying `mosaic_scene_ids` in the database: **10**
* served rows carrying `additional_cog_urls`: **10**
* cardinality mismatches: **0**
* served rows with no matching database row: **0**

So §2d's Python-side reconstruction resolves every reference, drops none, and
invents none, on live data.

**The `/stac` callback was exercised end to end** — the Landsat tile request
reached Titiler, which called back to `/imagery/{id}/stac` with the **new**
id, and the retry returned a 200 PNG. The callback resolves the new id space.

## 5. The 502, classified — F2

The prompt's gate is "5xx on any surface is STOP-and-report", and this is the
report. **The cause is upstream and pre-existing; the cutover is not
implicated.** The log timeline is unambiguous:

```
06:37:44Z  Plotline API starting            (machine 825d69b7…, Deploy B)
06:38:02Z  Plotline API starting            (machine 48e0de9a…)
06:39:02Z  SAS container token minted       sentinel2l2a01/sentinel2-l2a
06:39:03Z  SAS container token minted       naipeuwest/naip          → NAIP tile 200
06:39:42Z  SAS signing failed; retry exceeds wait budget, giving up
             429 Too Many Requests  …/sas/v1/token/landsateuwest/landsat-c2
             wait_s 19.0, spent_s 0.24, budget_s 2.0
06:39:42Z  Landsat SAS token expiry unavailable; falling back to a time bucket
06:39:44Z  SAS signing failed; retry exceeds wait budget, giving up   (429, wait_s 18.0)
06:39:44Z  Band signing failed after retries   bands [red, green, blue]
06:39:44Z  Titiler returned 500 for snapshot 631cff38…
06:39:51Z  SAS container token minted       landsateuwest/landsat-c2   ← succeeds 7 s later
~06:41Z    same id, same z/x/y  → 200, PNG
```

**Three things rule the cutover out.** The snapshot id resolved — the request
got as far as signing bands *for that row*, which requires the `/stac`
callback to have found it in `parcel_scenes`. The failure's stack ends in
`app/services/stac.py:429` on `httpx` raising PC's 429, in code this batch did
not touch. And the same id at the same tile coordinate returned 200 on retry.

**The mechanism, which is worth more than the incident.** The SAS
container-token cache is per-process and in-memory. **A deploy empties it**,
so the first request per `(account, container)` after any deploy must mint a
fresh token, and the request path's `SIGN_WAIT_REQUEST` budget is **2.0 s**
against a PC-advised retry wait of 18–19 s — it cannot absorb a 429 on that
mint and gives up immediately. NAIP and Sentinel-2 minted cleanly at
06:39:02–03; `landsateuwest` drew a transient 429 that cleared within 7
seconds.

**This is NORM-16 firing.** That row recorded that the G4 storm did not recur
during the 2026-08-29 fleet sweep and warned in its own words that **"a future
sweep must not cite it as evidence the request path is safe."** The warning
was vindicated 2 minutes 42 seconds after the cutover deploy, on the request
path, by a single cold-cache tile request. NORM-16 moves from *not observed
since 2026-08-12* to **observed on the request path, 2026-08-29**.

**Scope, honestly.** One 502, on one Landsat tile, on a cold process, cleared
by a retry 7 seconds later, with no user traffic in the window. It is not an
incident. It is a reproducible consequence of deploying, it will happen on
every deploy, and it was invisible until something requested a Landsat tile
promptly after one.

## 6. The deploy-window log read, and its limit

Retained window **06:24:34Z – 06:41:09Z**, which brackets Deploy B (06:37) and
every request this session made.

| Check | Result |
|---|---|
| old read function signatures (`get_imagery_snapshots`, `get_snapshot_by_id`, `count_imagery_snapshots`, `_snapshot_ids_for_parcels`) | **0 occurrences of any** |
| `imagery_snapshots_read` events | **0** — the reconciler has not run since the deploy |
| error-level events | **2**, both the F2 chain (`Band signing failed after retries`, `Titiler returned 500`), same `snapshot_id` |
| warning-level events | **1**, the same chain's Landsat expiry fallback |
| 404s on old ids (NORM-19's predicted tail) | **not observable — see below** |

**The limit, stated rather than glossed.** `fly logs --no-tail` returned 100
lines and the API emits no per-request access line to it, so there is no
`status_code` field to tally. **NORM-19's predicted brief tail of 404s on old
ids is therefore unobserved, not absent** — and there was no browser holding a
pre-deploy page in this window anyway, so the population was very likely
genuinely zero. Both statements are weaker than "no 404s occurred" and neither
should be written up as that. What *is* measurable, and is the claim that
matters, is §4's 141/0: no id the API now hands out lives in the old table.

## 7. Cooling period t0 — step 4's clock starts here

`scripts/snapshot_reads.py --out /tmp/reads-t0.json`, read-only, on machine
`825d69b7e46618`. Retrieved and committed as `reads-t0.json` so the closing
reading has a baseline that does not live on an ephemeral `/tmp`.

**t0 = `2026-08-29T06:41:47.270470Z`**, `stats_reset: null`.

| `imagery_snapshots` | value |
|---|---|
| `seq_scan` | **3,929** |
| `idx_scan` | **158,669** |
| `seq_tup_read` | 30,399,861 |
| `idx_tup_fetch` | 1,238,541 |
| `n_live_tup` | 12,884 |

`parcel_scenes`: seq_scan 123, idx_scan 57,448, n_live_tup 12,884.
`scenes`: seq_scan 145, idx_scan 137,121, n_live_tup 6,663.

**The 05:53:44Z reading is the pre-cutover reference, not t0**, and the delta
between them corroborates the harness rather than measuring the cooling
period: 3,900 → 3,929 `seq_scan` (+29) and 143,517 → 158,669 `idx_scan`
(+15,152) across the parity run, which fetched all 12,884 rows individually on
the old path plus every listing and count. That is the shape a 12,884-row
by-id sweep should leave.

**The expected legitimate reader set from t0 onward is exactly one:**
`reconcile_source_snapshots.existing_rows`, the sixth site in
`STEP1-REPORT.md` §7 that deliberately did not move, instrumented by the
`imagery_snapshots_read` structlog event. Nothing else in the codebase reads
the table; no serving path does.

**No timeline request ran during this session, so the instrumented event is
recorded as unobserved, not absent.** The counters and the log are the two
halves of step 4's measurement (`STEP3-REPORT.md` §5) and both need a
closing reading: the counters say how many accesses happened, the log says how
many were the reconciler, and the difference is the population step 4 is
looking for.

## 8. Findings

### F1 — a commit prescribed for deployment had never had the suite run at that commit

**New. Resolved before Deploy A; process rule below. NORM-21.**

`STEP3-REPORT.md` §9 item 1 prescribed deploying `160e7ba`. CI rejected it:
`tests/test_script_logging.py`, a guard requiring every script to call
`configure_script_logging()`, failed at that commit because
`scripts/compare_read_paths.py` did not. The guard had only ever run at head,
where the cutover had already **deleted** the harness — so the one commit in
the arc where the script existed *and* the guard applied was never tested, and
the plan of record named exactly that commit as the thing to deploy.

The fix commit `c96dbf8` is `160e7ba` plus the logging call, with the guard
test run at that commit before pushing, and it is what Deploy A actually
deployed. Nothing about the harness's behaviour changed: the interface read
back out of `c96dbf8` is the same single `--out`, and the run produced the
report `160e7ba` would have.

**The process rule, which is the durable part.** *Any commit prescribed for
deployment gets the suite run at that commit, not only at head.* A plan that
names a historical sha for deployment is naming a state no CI run has ever
covered, and a green suite at head says nothing about it — especially in an
arc like this one, where a later commit deletes a file the earlier commit
introduced. Writing "deploy `X`" into a report is a claim that `X` is
deployable, and this batch demonstrates that the claim can be false while
every visible signal is green.

### F2 — the G4 signing storm fired on the request path, and a deploy is what arms it

**New. Open, unfixed. NORM-22, and it upgrades NORM-16.** §5 has the full
timeline and classification.

`SIGN_WAIT_REQUEST` is 2.0 s and PC's 429 advises an 18–19 s wait, so the
request path cannot absorb a throttled token mint. The in-memory SAS
container-token cache is emptied by every deploy, so **every deploy creates a
window in which the first request per `(account, container)` must mint a token
under that unabsorbable budget**. The window is short — 7 seconds here — and
invisible unless something requests a tile inside it, which is why NORM-16
could record a clean 189-parcel sweep and still be right that nothing was
fixed.

**Not fixed here, and this session cannot fix it** — it is a write to the
request path's retry policy, outside step 3's scope, and any remedy trades a
user-visible 502 against a user-visible delay. Candidates, in order of
durability: (a) mint container tokens at startup for the four known
`(account, container)` pairs, so the cold-cache window closes before the
machine takes traffic; (b) let the request path serve a stale-but-unexpired
cached token across a deploy by persisting the cache in Redis, which is where
`stac:{id}` already lives; (c) raise `SIGN_WAIT_REQUEST` past PC's advised
wait, which converts a fast 502 into a slow tile and is the worst of the
three. The decision belongs with whoever owns NORM-16.

**Later: 2026-08-29, branch `norm22-startup-mint` (not yet merged).** Two
factual corrections to this finding's mechanism, made reading `stac.py` on
this batch's head rather than re-deriving from the incident alone. **The
container-token cache is not in-process — it is Redis-backed**
(`_cached_container_token` / `_mint_container_token`, keyed
`sas-token:{account}/{container}`), and has been since `e8c857c` and
`2168124` (2026-08-12), both ancestors of the deployed incident sha
`c96dbf8`. Candidate (b) above, "persisting the cache in Redis," was already
built at incident time; it did not prevent the 502. Since Redis is a
separate Fly app from `log0s-plotline-api`, an API/worker deploy does not
restart or flush it, so "a deploy empties the cache" cannot be the literal
mechanism. The more defensible read: PC container tokens live ~45 min
(margin-adjusted TTL, `_container_token_ttl`), this is a low-traffic app, and
the deploy's own post-deploy smoke/health traffic is often the first request
in a container's idle window — so a deploy *correlates* with the re-mint
trip without *causing* it via cache emptying. **Second correction: there are
three known `(account, container)` pairs, not four** — `naipeuwest/naip`,
`sentinel2l2a01/sentinel2-l2`, `landsateuwest/landsat-c2` — matching the
three mint lines this finding's own timeline shows, and cross-checked
against `BOUNDARY-BASELINE.md` and `STATUS.md`'s G7 row. That timeline's
`sentinel2l2a01/sentinel2-l2a` also has a stray trailing "a" against every
other production reading of that container. Neither correction changes the
remedy: a startup mint into the same Redis-backed cache still closes the
observed window, because it guarantees a warm token exists before the
post-deploy request that would otherwise trip it, regardless of which idle
period produced the cold entry. Full reasoning and evidence:
`NORM22-REPORT.md`.

### F3 — a detached run's exit code does not survive the client that launched it

**New. Minor, and fixed by one line next time.** §3's PP14. `setsid nohup …
&` is the correct shape for a production run that must outlive its ssh client
(NORM-8), and it discards `$?`. Appending `; echo $? > /tmp/<name>.rc` costs
nothing and turns an inference into a reading.

## 9. Deviations from the prompt

1. **Deploy A deployed `c96dbf8`, not the prescribed `160e7ba`.** F1. The
   substitution happened outside any session, before this one started, and
   this session verified rather than chose it.
2. **The owner's push #2 carried three of this session's record commits**, so
   the deployed sha is `18ddb8e` rather than `3c2ce01`. The gate checked
   `b1acf9a`'s ancestry in the deployed sha, which is the property that
   matters; the extra commits are documentation.
3. **A 5xx was observed on a smoked surface**, which is a STOP-and-report
   condition. It is reported in §5 and F2 rather than waved through, and it is
   classified as upstream and pre-existing on three independent grounds. **No
   remedial action was taken and none is recommended by this session** — F2's
   options are the owner's call.
4. **The deploy-window 404 check could not be performed** as specified, for
   want of per-request logging and log retention. §6 states the limit instead
   of substituting a weaker check silently.

## 10. State left behind

* **Production serves from `parcel_scenes` joined to `scenes`.** Deployed sha
  `18ddb8e83e3fb90307bec6bf70bd480978ab19d7`, built 06:37:11Z, on all four
  machines of both apps. Rollback is redeploying the previous sha.
* **`imagery_snapshots` is unchanged and still dual-written**, 12,884 rows.
  Its only remaining reader in the codebase is
  `reconcile_source_snapshots.existing_rows`, which step 4 owns.
* **The cooling period is running**, t0 `2026-08-29T06:41:47.270470Z`, baseline
  committed as `reads-t0.json`. Both instruments are named in §7 and both need
  a closing reading before step 4 drops anything.
* **NORM-18 is open at population 0.** Measured, not argued. The class opens
  the first time a NAIP selection is rewritten against a `scenes` row written
  before the NORM-9 fix.
* **NORM-22 is open and unfixed**, and will recur on the next deploy.
* **This session wrote nothing to production.** Every probe proved
  `default_transaction_read_only` before reading; both deploys were owner
  pushes.
* **The record commits in this batch are not pushed.** They ride on the
  owner's next push; production already has everything it needs.

**Next scheduled work, before step 4:** the snapshot-enrichment heal —
NORM-18's item-fact refresh, NORM-13's `scenes` arm, and NORM-7's footprint
backlog, as one pass. See STATUS.md's Scheduled section.
