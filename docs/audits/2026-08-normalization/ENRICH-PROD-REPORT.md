# STAC enrichment against production — the run that did not happen

Session of 2026-08-28, 21:20–21:30 UTC. The plan was: verify the deploy,
measure, dry-run, predict, execute once detached, score, record.

**Outcome: a STOP at item 3. The dry run reported 6 `error` outcomes, so the
execute was not run. Production is byte-for-byte unchanged — the only
authorized write never happened.** All 505 `provenance = 'mosaic_url'` rows
still carry candidate ids and NULL footprints; NORM-7 stands in production in
full.

The errors are **not** a property of the six rows. Every one of the six
searches succeeds when replayed at a low request rate, and each returns the
item that matches the row (F6 below). The cause is the request rate the run
itself generates: **the Planetary Computer `/search` endpoint answers 403 —
not 429 — when it throttles, and `403` is not in the script's retryable set**
(`scripts/enrich_synthesized_scenes.py:119`). At local scale (145 requests)
the throttle never engaged; at production scale (~814 requests in 28 s) it
engaged 6 times. That is a script defect against production scale, which this
session's constraints make a stop-and-report, not an in-session fix.

Captures committed with this report:

* `enrich-prod-dryrun.md` — the script's own report, written on the machine to
  `/tmp/enrich-prod-dryrun.md` and retrieved by `fly ssh sftp get`.
* `enrich-prod-dryrun-stdout.txt` — the detached run's full stdout, including
  the structlog summary line.

Both are markdown/text rather than the `.txt`/`.json` names the prompt
sketched: `--report` writes markdown, and the script has no JSON output mode
(`render_report`, `enrich_synthesized_scenes.py:634`). Names follow the local
run's convention (`enrich-local-dryrun.md`).

Everything against production was read-only. Every DB probe opened its own
connection and called `conn.set_session(readonly=True)`. No write, no sweep,
no heal, no requeue, no deploy, no code change.

---

## 1. Deploy gates — all four pass

| Gate | Evidence | Result |
|---|---|---|
| a. API sha | `GET https://log0s-plotline-api.fly.dev/api/v1/health` at 21:20:02Z → `{"sha":"99e33f2853ca3be20b4001de097b092c919a0100","built":"2026-08-28T20:04:45Z"}`. `git merge-base --is-ancestor 99e33f2 99e33f2853ca…` exits 0 | pass — the deployed sha **is** `99e33f2` |
| b. Image labels | `fly image show -a log0s-plotline-api` (machines `825d69b7e46618`, `48e0de9a713918`) and `-a plotline-worker` (`e2862966b306d8`, `e7845415f57728`): all four carry `GH_SHA=99e33f2853ca3be20b4001de097b092c919a0100` | pass — both apps on the health sha |
| c. Migration head | `SELECT version_num FROM alembic_version` → `0016`, read 21:20:33Z | pass |
| d. The constraint actually admits `'enriched'` | `pg_get_constraintdef` for `ck_scenes_provenance` on `scenes`: `CHECK ((provenance = ANY (ARRAY['snapshot'::text, 'mosaic_url'::text, 'enriched'::text])))` | pass |

On (c): the revision id was read from the migration file, not inferred from
the filename — `alembic/versions/0016_scenes_provenance_enriched.py:46`
declares `revision: str = "0016"`, so prefix and revision id coincide here.

On (d): queried rather than assumed, because "the migration ran" and "the
migration applied its intent" are different claims. The deployed CHECK carries
the third value.

## 2. Pre-run measurement, read-only, 21:20:55–21:20:57Z

| Measurement | Value | Expected |
|---|---|---|
| `scenes` by provenance | `mosaic_url` **505**, `snapshot` **6156**, `enriched` **0** (absent) | exactly as predicted — no drift |
| `scenes` total | 6661 | |
| `parcel_scenes` total | **12884** | merge-accounting baseline |
| `parcel_scenes` carrying a mosaic / total mosaic references | **576 / 613** | |
| queue by source/collection | naip/naip 505 | all NAIP, as step 1 left it |
| queue rows with no referencing parcel | 0 | every row has a bbox to search with |
| queue `footprint` / `bbox` / `resolution_m` non-NULL | 0 / 0 / 0 | untouched since step 1 |
| `imagery_snapshots` rows / distinct items | 12884 / 6156 | unchanged from 17:03:37Z on 2026-08-28 |
| newest `imagery_snapshots.created_at` | 2026-08-27T19:41:01.190156Z | unchanged since step 1's reading |
| newest `timeline_task_years.created_at` | 2026-08-27T22:00:44.961932Z | unchanged |
| dangling `mosaic_scene_ids` references | 0 | |

**No drift.** The three provenance counts are exactly the numbers step 1 left
behind, so the STOP condition on unexplained writes did not fire.

The two structural merge queries from `PREDICTION-ENRICH.md` §3, re-run
against production as §6 requires:

| Query | Production |
|---|---|
| candidate ids prefix-overlapping another `scenes` row's `item_id`, same collection | **0** |
| a non-queue `scenes` row sharing a queue row's tile **filename** under a different URL | **0** |
| queue rows whose `cog_url` is also held by another `scenes` row | **0** |
| distinct `cog_url` within the queue | 505 of 505 |

So 0 merges was the production expectation too, on the same structural
grounds — and the dry run planned exactly 0.

Two counts taken rather than scaled, per §6:

* `_h_` resolution-spelling class: **22** rows (local had 2).
* candidates already carrying a trailing publication date
  (`item_id ~ '_[0-9]{8}_[0-9]{8}$'`): **55** rows (local had 12).

## 3. Dry run

Started detached per NORM-8 / F5, so the ssh client's timeout could not orphan
it:

```
fly ssh console -a log0s-plotline-api -C \
  "sh -c 'cd /app && nohup python scripts/enrich_synthesized_scenes.py \
     --report /tmp/enrich-prod-dryrun.md > /tmp/enrich-prod-dryrun-stdout.txt 2>&1 & echo started pid $!'"
```

pid 656 on machine `825d69b7e46618`, started 21:21:14Z, finished 21:21:42Z —
**28 seconds**. Polled read-only (`ls`, `/proc/656`) rather than re-run; both
files were then retrieved with `fly ssh sftp get --machine 825d69b7e46618`.
(The first `sftp get` without `--machine` landed on the other machine and
reported "file does not exist" — the report lives on the machine that wrote
it, and `fly` picks a machine per invocation.)

| Outcome | Rows |
|---|---|
| already-exact | **196** |
| id-corrected | **303** |
| merged | **0** |
| unmatched | **0** |
| error | **6** |
| would enrich in place | 499 |
| queue after | 6 |

Capture-date disagreements: **0**. Anomalies section: absent. Requests:
505 item GETs + 309 searches ≈ **814**, against the ~850 §6 predicted.

The split is 38.8% exact / 60.0% corrected, against F1's 31.7% / 65.4% — both
inside the §6 bands (already-exact band 60–260, actual 196; id-corrected band
230–430, actual 303).

**Every single non-exact row 404'd on the item endpoint** (309 of 309). Not
one row returned a 200 naming a different item, and not one returned 403.

## 4. Why the run stopped here

Item 3 of the session's prompt: *"If the dry run itself reports errors beyond
the expected unmatched remainder: STOP, commit, report."* And
`PREDICTION-ENRICH.md` §7, committed before any of this: *"Any `error`
outcome: a transport failure surviving four attempts with Retry-After backoff
is an unhealthy endpoint, and the honest response is to stop and report rather
than to run the remainder against it."*

Six errors, none of them an unmatched row. The gate fired. The execute
command was never issued, and no prediction was appended to
`PREDICTION-ENRICH.md`: rule 4 asks for a prediction before a run, and the run
this session was authorized for did not take place. The production prediction
belongs to the session that runs it, after the defect below is fixed.

## 5. F6 — Planetary Computer throttles `/search` with 403, and the script does not retry 403

**New. Script defect, exposed only at production scale. Open — it blocks the
production enrichment run.**

The six error rows, all with the same detail shape:

```
| `pa_m_4007563_ne_18_1_20130605`   | error | item GET 404; HTTPStatusError: Client error '403 Forbidden' for url '…/api/stac/v1/search'
| `pa_m_4007563_se_18_1_20170612`   | error | …
| `sc_m_3508254_ne_17_1_20110430`   | error | …
| `sc_m_3508254_ne_17_1_20150424`   | error | …
| `tn_m_3508959_se_16_060_20180804` | error | …
| `tx_m_3009743_nw_14_1_20141014`   | error | …
```

**The rows are fine; the rate was not.** Each of the six searches was replayed
from inside the machine a few minutes after the run — same collection, same
`point_to_bbox(parcel, 1500 m)`, same year window, issued sequentially with a
2-second gap — and all six returned **200**, each containing the item the row
needs:

| Row | Replay | Item returned |
|---|---|---|
| `sc_m_3508254_ne_17_1_20110430` | 200, 2 features | `sc_m_3508254_ne_17_1_20110430_20110705` |
| `sc_m_3508254_ne_17_1_20150424` | 200, 2 features | `sc_m_3508254_ne_17_1_20150424_20150714` |
| `pa_m_4007563_ne_18_1_20130605` | 200, 4 features | `pa_m_4007563_ne_18_1_20130605_20130729` |
| `pa_m_4007563_se_18_1_20170612` | 200, 4 features | `pa_m_4007563_se_18_1_20170612_20171207` |
| `tx_m_3009743_nw_14_1_20141014` | 200, 4 features | `tx_m_3009743_nw_14_1_20141014_20141201` |
| `tn_m_3508959_se_16_060_20180804` | 200, 4 features | `tn_m_3508959_se_16_060_20180804_20190131` |

Each returned id is the row's candidate id plus a publication date — the
`id-corrected` shape, so all six are expected to enrich normally once the
request survives.

**The mechanism.** `_RETRYABLE_STATUSES` is `{429, 500, 502, 503, 504}`
(`enrich_synthesized_scenes.py:119`). A 403 is deliberately *not* retryable
there, and for the **item** endpoint that is right: the geometry audit
established a per-item 403 that means "PC will not serve this item", and
retrying it four times would be four wasted requests. The `search` path
inherits the same rule through `_request`, and then `search` calls
`resp.raise_for_status()` (`:338`), which turns the 403 into an
`HTTPStatusError` that `resolve_row`'s handler records as `error` (`:416`).
So a throttle response on the search endpoint is treated as a permanent
refusal of a specific item.

Two facts say it is a throttle and not a refusal: the replay above, and the
rate — 814 requests in 28 seconds is ~29 req/s sustained, at concurrency 6
with no inter-request delay. The local run issued 145 requests and saw zero
403s of any kind.

**Not fixed here.** The session's constraints make a script bug found against
production data a stop-and-report. The shape of the fix, for whoever takes it:
a 403 from `/search` is retryable and a 403 from the item endpoint is not, so
the two paths need different retryable sets rather than one shared constant —
and the run should carry a small inter-request delay or a lower concurrency so
it does not provoke the limiter in the first place. Whatever is chosen, the
`error` outcome must stay an `error`: converting a throttled search into
"unmatched" would be exactly the "complete with zero vs failed" collapse the
engineering norms forbid.

## 6. The two never-exercised branches are still never-exercised

The local run left two branches untested, and the production dry run — which
resolves every row exactly as an execute would, since dry run and execute
share `apply_resolutions` — did not reach either:

* **403-on-item-GET falls through to search.** Zero item-GET 403s across 505
  requests (`grep -c 'item GET 403'` → 0). Every non-exact row 404'd. The
  branch has now gone 593 rows (88 local + 505 production) without being
  entered. The geometry audit's six forbidden items remain outside this queue.
* **Collision-merge.** 0 merges planned, on the same structural grounds
  production's own queries confirmed in §2. `_merge_scene` has still never
  run outside its tests.

Both remain predictions rather than observations. The 403 this session did
find is a *different* 403 — on the search endpoint, at the run level, not the
item level (F6).

## 7. One refinement to F1, free from the dry run

`_h_` in a tile filename does **not** always mean the catalogued id spells the
resolution differently. Of the 22 `_h_` rows in the production queue, **17 are
`id-corrected`** to a `_.6_` or `_.5_` id (the F1 shape), but **5 are
`already-exact`** — `mi_m_4408418_sw_16_h_20160809`,
`mi_m_4408631_nw_16_h_20160722`, `mi_m_4508560_nw_16_h_20160725`,
`mo_m_4009441_ne_15_h_20160615`, `vt_m_4407330_se_18_h_20160804`. PC
catalogues those state-years with the literal `_h_`. F1's "neither" class is
therefore state-year-scoped, not a property of the `_h_` spelling itself.

This is an observation from a dry run, not a write; the local prediction's
"exactly 2 `_h_`, both id-corrected" was a local count and is untouched.

## 8. State left behind

Nothing changed in production.

* `scenes`: 6661 rows — 6156 `snapshot`, 505 `mosaic_url`, **0 `enriched`**.
* `parcel_scenes`: 12884 rows, 576 carrying 613 mosaic references, 0 dangling.
* Migration 0016 is deployed and its widened CHECK is live; **no row uses the
  new value**, which is exactly what 0016's docstring said would be true until
  the enrichment script writes one.
* On machine `825d69b7e46618`: `/tmp/enrich-prod-dryrun.md` and
  `/tmp/enrich-prod-dryrun-stdout.txt`, both retrieved and committed here.
  Nothing else was created; pid 656 exited on its own.
* No process is still running. `/proc/656` was gone before the files were
  fetched.

## 9. What the next session needs

1. Fix F6 in `scripts/enrich_synthesized_scenes.py` — split the retryable
   statuses by endpoint, and pace the run. Test that a 403 from `/search`
   retries and a 403 from the item endpoint still falls straight through to
   the search (delete-the-fix: the test must fail with the change removed).
2. Re-run the dry run against production and expect 505 → 499 enriched + 6,
   now resolving; a clean dry run is the precondition, not the goal.
3. Write the production prediction into `PREDICTION-ENRICH.md` and commit it
   **before** the execute. The dry run in this report is the strongest input
   it has: 196 / 303 / 0 / 0 is what an unthrottled run should produce, plus
   the six now-resolvable rows.
4. Execute once, detached, per NORM-8.

Step 2 stays blocked on NORM-7 in production either way.
