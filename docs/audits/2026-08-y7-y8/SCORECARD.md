# Y7 + Y8 scorecard — the deploy watch, the observation heal, and the score

Prediction: `PREDICTION.md`. Deploy: `2190e57`/`1367302`/`07db132`, head at run
time. Heal: one census-scoped `requeue_parcels.py --from-ledger --sources
census --include-absent-api` run against production, `--require-sha 07db132`,
`--max-wait-minutes 90`. All commands and queries below ran via `fly ssh
console`, `SELECT`-only except the one heal invocation named in this batch's
prompt as the written exception.

---

## 1. Deploy watch

Worker was **stuck on `70f95d3`** (3 commits behind) when this batch started —
API had already rolled to `07db132` but the worker's CI job had not. No
in-flight deploy (`fly releases -a plotline-worker` showed v64/`70f95d3`
complete 30 min prior). Unstuck by re-running the deploy from GitHub Actions
(operator action, outside this session — `gh` is not available in this
environment). Re-verified after: both apps on `07db132578cab59b5d86da816ed9af55c0c1fff5`
— API `/api/v1/health`, worker `fly image show` `GH_SHA` label agree.

**Deviation from the plan, not from any Y7/Y8 claim:** the plan assumed a
single clean deploy; it needed a manual unstick first. Recorded here because
it is exactly the kind of state a future session would otherwise have to
rediscover from scratch.

---

## 2. Schema and pre-heal state (read 2026-08-27, ~21:45Z)

| | |
|---|---:|
| `alembic_version` | `0013` |
| `timeline_requests.deployed_sha` | present, nullable, no default |
| `census_snapshots.updated_at` | present, `NOT NULL`, default `now()` |
| `timeline_requests` total | 1043 (all pre-migration `deployed_sha IS NULL`) |
| `census_snapshots` total | 1574 (all `updated_at = created_at`, pre-migration backfill) |

**Deviation, noted and not scored:** the prediction's fleet-state table
(written same day, ~hours earlier) read `timeline_requests`=127 and
`census_snapshots`=330. Actual totals were 1043 and 1574. Traffic history
(`created_at` range April–August, hourly buckets showing bursts of dozens to
hundreds of rows, 331 pre-existing `origin='heal'` rows) confirms this is
normal accumulation including the prior heal-3/ops-sweep batches, not a
runaway request loop or a wrong database. Neither Y7 nor Y8's claims depend on
these totals — they're context, not inputs to any falsifier.

Before-state capture (full row-level, per user instruction — HEAL-3 §5's
4-field content checksum computed per-row rather than as a group aggregate,
so this run's diff can be exact instead of interim):
- `logs/before-census_snapshots.csv` — all 1574 rows: id, parcel_id, dataset,
  year, tract_fips, created_at, updated_at, `md5(total_population|
  median_household_income|median_home_value|total_housing_units)`.
- `logs/before-ledger-census_decennial-absent.log`,
  `logs/before-ledger-census_acs5-absent.log` — full absent set via
  `ledger_gaps.py --outcome absent --all`.

---

## 3. Dry run 1 (pre-heal)

```
requeue_parcels.py --from-ledger --sources census --include-absent-api \
    --dry-run --require-sha 07db132
```

`Deploy gate passed — prod is running 07db132…`. **Ledger selected 127
group(s) across 78 parcel(s).** Log: `logs/dryrun-1-pre-heal.log`.

**Unit note (not a deviation):** the prediction's Claim 2 says "127 groups";
the run-time expectation is **78 requests** (one per parcel, each carrying
that parcel's absent groups as tasks) — confirmed by the dry run's own second
line. Hygiene below is scored against 78; the Y7 falsifier is scored against
127 groups. Both are the same selection, counted at two different
granularities, per the user's instruction before the run.

**Y7 Claim 2 — confirmed exactly.** 127 matches the prediction's stated
number precisely (itself a same-day re-read that had already deviated from
HEAL-3's older 76 — see `PREDICTION.md`'s own deviation note).

---

## 4. The run

```
requeue_parcels.py --from-ledger --sources census --include-absent-api \
    --require-sha 07db132 --max-wait-minutes 90
```

`Done — queued 78 timeline request(s), skipped 0.` **Exit code 0.** Log:
`logs/heal-run.log`, 345 lines. Admission gating visible throughout:
`cap=25 depth=25 hard_cap=30`, refuse/wait/retry cycling as heal 3 showed.
Polled to terminal after enqueue completed: all 78 requests reached
`complete` (0 `partial`, 0 `failed`) within a few minutes of the last
enqueue.

---

## 5. Score

### 5.1 Hygiene — confirmed

| check | result |
|---|---|
| request count | 78 / 78 expected |
| `origin` | `heal` × 78 |
| `status` | `complete` × 78 |
| `sources` | `['census']` × 78 |
| `deployed_sha` | `07db132578cab59b5d86da816ed9af55c0c1fff5` × 78, 0 mismatched |

**Y7 Claim 1 — confirmed.** Every new request's `deployed_sha` equals the
health SHA at creation time; zero exceptions.

### 5.2 Y7 falsifier — confirmed exactly

Second dry run, identical command:

```
Ledger selected 0 group(s) across 0 parcel(s).
Nothing to do.
```

Log: `logs/dryrun-2-post-heal.log`. **Y7 Claim 3 confirmed exactly — zero
groups selected**, no exceptions to list.

`ledger_gaps.py --outcome absent --all` re-read for both sources
(`logs/after-ledger-census_decennial-absent.log`,
`logs/after-ledger-census_acs5-absent.log`): all 78 `census_decennial`/`2000`
groups and all 49 `census_acs5`/`2009` groups now carry `same` in the `same_sha`
column — 127 of 127, zero unmarked.

### 5.3 Rows gained — none

`census_decennial` absent triples: 265 before, 265 after (1990's 187 stale +
2000's 78, unchanged in both counts). `census_acs5` absent triples: 49 before,
49 after. **Zero ride-along rows this run** — unlike heal 3's 28 unpredicted
`acs5`/2009 recoveries, this run recovered nothing and lost nothing. Every
group that was absent before the heal is absent after it, now under the new
SHA.

### 5.4 Y8 — `updated_at` — confirmed, zero leakage

Full before/after diff, `before-census_snapshots.csv` vs
`after-census_snapshots.csv` (1574 rows each, 0 created, 0 removed):

| | count |
|---|---:|
| rows with `updated_at` moved | 575 |
| — content checksum changed (real value change) | **0** |
| — content checksum identical (idempotent upsert, Claim 6) | **575** |
| checksum changed but `updated_at` unchanged (falsifier) | **0** |

**Y8 Claim 5 — confirmed, exactly on scope.** The 575 touched rows are
precisely `{2010, 2020} × decennial` and `{2009, 2012, 2015, 2018, 2021,
2023} × acs5` for the 78 healed parcels — 78 × 7 = 546 plus 29 pre-existing
`acs5`/2009 rows among those parcels (the other 20 of the 49 `acs5`/2009
absent groups had no snapshot row to touch), 546 + 29 = 575. The touched-row
parcel set is **exactly** the 78 healed parcels — zero rows moved outside
that set, zero rows inside that set left untouched. This is the same
census-task-covers-all-vintages shape HEAL-3 §5.5 documented ("by design, not
scope leakage"), now provable exactly instead of by checksum spot-check,
because `updated_at` exists.

**Y8 Claim 6 — confirmed.** All 575 moved rows kept identical checksums —
the idempotent-upsert-bumps-`updated_at` behavior is pinned, not a bug, and
this is the first production observation of it at full row-level resolution
rather than the interim group-aggregate method.

**Zero recovery, zero regression.** No `census_decennial`/2000 or
`census_acs5`/2009 row was created for any of the 78 parcels — every one of
those groups is still `absent/api_no_data` after the run (§5.3). Y8 doesn't
claim recovery; it claims `updated_at` tracks what the upsert touches, which
holds regardless of whether the touch changed anything.

### 5.5 Isolation — confirmed, by mechanism not by count

No imagery baseline was captured before the heal (out of scope of the
before-state this batch's prompt asked for — census rows and the census
ledger only). Isolation is instead proven by joining this run's own requests
to their tasks directly, which is a stronger check than an aggregate
before/after diff would have been (it isolates this run's effect from
concurrent unrelated traffic, of which §2's deviation note shows there is
a fair amount):

```sql
SELECT count(*) FROM timeline_request_tasks t
JOIN timeline_requests r ON r.id = t.timeline_request_id
WHERE r.origin = 'heal' AND r.deployed_sha = '07db132…' AND t.source != 'census'
```

→ **0**. Every task row this run's 78 requests created is a `census` task;
none reached the imagery fetch path at all — the same
`reconcile_source_snapshots`-unreachable mechanism HEAL-3 §5.5 established.

Zero non-census ledger rows from this run's tasks (§5.3, §5.4 — only
`census_decennial` and `census_acs5` groups moved). Admission held at
`cap=25`/`hard_cap=30` throughout (`logs/heal-run.log`).

### 5.6 Failures — none

Zero `failed`, zero `partial`, zero unreached, exit code 0.

---

## 6. Anomalies and deviations

1. **Worker deploy was stuck** before this batch started (§1) — not a code
   defect, a CI/ops gap. Worth a note for whoever owns the deploy pipeline:
   a partial multi-service deploy (API rolled, worker didn't) produced no
   alert this session could see.
2. **Fleet-total deviation** (§2) — large but explained, not a Y7/Y8 defect.
3. **Zero ride-along** (§5.3) — the interesting asymmetry against heal 3 is
   that this run recovered nothing. That's a fact about the Census API's
   current behavior for these specific vintages/tracts, not about Y7 or Y8;
   worth flagging for whoever next asks "is decennial-2000/acs5-2009 worth
   retrying again" — the answer right now is "not until something upstream
   changes," and Y7 is precisely the mechanism that now stops that question
   from costing an API call every time it's asked.

---

## 7. Verdict

**Y7 and Y8 both fully confirmed in production, zero deviation from either
claim.** All six claims in `PREDICTION.md` hold exactly: Claims 1–4 (Y7) and
5–6 (Y8). No falsifier fired. Isolation held. The batch's own predicted units
(78 requests vs. 127 groups) were called out in advance and did not need to
be reconciled after the fact.
