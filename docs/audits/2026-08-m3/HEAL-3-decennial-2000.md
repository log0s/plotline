# M3 heal 3 — the fleet-wide decennial-2000 sweep (P2), run and scored

One `scripts/requeue_parcels.py` invocation, 2026-08-27, against deployed SHA
`5f3aa7dc374cfaf3f1e12d8257c2dc02fff309ce` on both machines. This is P2 of
`PREDICTION.md`, the last of M3's three acceptance heals, and the first run
large enough to exercise the admission reserve.

**Verdict: every falsifiable clause of the adjusted prediction confirmed,
zero deviations in the scored numbers, one process deviation (log routing),
and one gap recorded rather than fixed.**

---

## 1. The adjusted prediction, with its arithmetic

`PREDICTION.md` P2 as amended by the Y3 addendum (2026-08-26) predicted a
selection of **140 parcels / 140 groups** and a recovery of **64** rows. The
2026-08-27 addendum then said the 64 would erode: every full-scope heal run
under the deployed trim between that count and this sweep removes a parcel
from the population P2 finds, and a sub-64 result is that mechanism rather
than a falsifier.

**Ride-alongs since P2 was written: exactly one.** All three requests created
after the P2 reading (`origin='heal'`, 2026-08-27) are:

| request | parcel | scope | created |
|---|---|---|---|
| `3823fad9` | `e513188c` | `['naip']` | 16:06:16Z (Heal 1) |
| `36caa352` | `6563dedf` | `['landsat','naip']` | 16:37:33Z (Heal 2) |
| `69ec4ac8` | `6563dedf` | full scope | 16:40:17Z (Heal 2, second run) |

Only the third carried a `census` task. It moved `6563dedf`'s
`census_decennial`/`2000` from `absent`/`api_no_data` to `ok` — Crawford's
stored tract is `26039960500`, which **ends `00`**, so the ride-along removed
one parcel from the selection *and* one from the recovery.

**Adjusted prediction, stated before the run:**

| line | arithmetic | adjusted |
|---|---|---:|
| dry-run selection | 140 − 1 ride-along | **139** |
| recovery denominator (selected parcels whose tract ends `00`) | 80 − 1 | **79** |
| recovery | 79 − 16 known-204 tracts (§1.5 list, all 16 still selected) | **63** |
| re-absence | 139 − 63 | **76** |
| max admission depth on a heal | cap 30 − `user_admission_reserve` 5 | **≤ 25** |

---

## 2. Before-state (read 2026-08-27, ~16:45Z, `SELECT` only via `fly ssh`)

| | |
|---|---:|
| parcels | 187 |
| `timeline_requests` | 713 (670 `complete`, 40 `partial`, 3 `failed`) |
| requests in flight | **0** |
| `census_snapshots` `decennial`/`2000` | **48** |
| `imagery_snapshots` | 12,751 — `md5(ids)` `8839c46e66e1da55de74d5b287f1986d` |

Latest ledger, `census_decennial`:

```
1990  absent/api_no_data  187
2000  absent/api_no_data  139
2000  ok                   48
2010  ok                  187
2020  ok                  187
```

Of the 139 `absent` parcels, **79 have a `census_tract_id` ending `00`** and
60 do not. All 16 tracts from `../2026-08-census-decennial/REPORT.md` §1.5
(the ends-`00` tracts that 204 even under the four-character form) were still
in the selected set.

---

## 3. Gate and dry run

1. **Deploy.** `fly image show -a plotline-worker` → `GH_SHA=5f3aa7dc374c…`;
   API `/api/v1/health` → `{"status":"ok","db":"connected","redis":"connected",
   "version":{"sha":"5f3aa7dc374c…","built":"2026-08-27T15:41:35Z"}}`. Both
   machines agree. The script's own gate printed
   `Deploy gate passed — prod is running 5f3aa7dc374c…`.
2. **In flight.** Zero requests outside `{complete, partial, failed}`.
3. **Dry run**, `--from-ledger --sources census_decennial --include-absent-api
   --dry-run`: `Ledger selected 139 group(s) across 139 parcel(s).`
   Mechanically counted from the captured output: **139** `would re-queue`
   lines, **0** whose scope is not exactly `[census]`, **139** group lines, all
   `census_decennial 2000 absent/api_no_data`. One group per parcel; no parcel
   carried a second source, so the stop condition did not fire.
   **Selection confirmed at 139 — the adjusted number, through the script
   itself.** This is what the Y3 addendum said only a real dry run against
   deployed M3 code could establish; it now reads the same way through
   `requeue_parcels.py` as it did through hand-written SQL.

`census_decennial`/`1990` did **not** appear in the selection — `is_stale`
excluding the 187 stale rows is observed here, not merely unit-tested.

---

## 4. The run

```
python scripts/requeue_parcels.py --require-sha 5f3aa7d --from-ledger \
    --sources census_decennial --include-absent-api --max-wait-minutes 90
```

`Done — queued 139 timeline request(s), skipped 0.` **Exit code 0.** Zero
unreached. Enqueue window 16:50:52.6Z → 17:04:24.6Z (13.5 min); last request
reached terminal at 17:08:04Z. The 139 parcels enqueued are byte-identical to
the 139 the dry run listed.

---

## 5. Scorecard

### 5.1 Hygiene — confirmed

| check | observed |
|---|---|
| requests created | **139**, across 139 distinct parcels (= dry-run count) |
| `origin` | `heal` ×139 |
| `sources` | `['census']` ×139 |
| task rows per request | **exactly 1** on all 139 (`census`, all `complete`) |
| request status | `complete` ×139 |
| `error_message` | null on all 139 |
| unreached | **0** |
| exit code | **0** |

Fleet requests went 670 → 809 `complete`; `partial` 40 and `failed` 3
unchanged.

### 5.2 Admission reserve — confirmed

**Max `depth` observed on any heal admission: 25.** All 236 admission log
lines read `cap=25`; every `Admission refused` line reads
`hard_cap=30 origin=heal reason=queue_full`. The depth series is degenerate
and is summarised rather than listed: `depth=25` on 236 of 236 lines, no
other value ever recorded. The heal ceiling held at 25 for the whole run and
five slots stayed reserved.

| | |
|---|---:|
| admission refusals | 84 |
| wait episodes | 84 |
| `Waiting for an admission slot` poll lines | 152 |
| total time waiting | 782.9 s (13.0 min) |
| longest single wait | 15.6 s |
| median wait | 10.3 s |

**No `origin='user'` request arrived during the run.** All 139 requests
created in the window 16:50:52Z–17:08:30Z are `origin='heal'`; zero non-heal
requests exist in that window. So the claim P2 itself flagged as untestable —
that a user request still gets in at heal depth 25 — remains untested by
observation. What is now measured is the ceiling, not the reserve's effect on
user traffic.

### 5.3 Recovery — confirmed exactly

**`census_snapshots` `decennial`/`2000`: 48 → 111. 63 rows gained.**
Adjusted prediction: 63. The ledger agrees: `census_decennial`/`2000` latest
outcomes are now `ok` 111 / `absent`+`api_no_data` 76, and this run's own
tasks wrote `2000 ok ×63` and `2000 absent/api_no_data ×76`.

**Every one of the 63 gained rows has a tract ending `00`. Zero exceptions.**
That was the stated finding condition — a gained row on a tract not ending
`00` would mean the trim fired where it should not have, or that the model of
why those years were absent is wrong. Neither happened.

`median_household_income` is null on all 63; median income is an ACS variable
the decennial config never requests, so this is the config, not a loss.

Independently, this also confirms a prediction made in STATUS.md's copy entry
on 2026-08-26: *"the decennial floor in production is 2000 for 111 parcels…
once the fix is deployed and swept."* Observed: **111.** (Its companion "and
2010 for the other 75" was written at a 186-parcel fleet; the fleet is now
187, so the complement is 76.)

<details>
<summary>The 63 gained rows</summary>

| tract_fips | parcel | `total_population` (2000) |
|---|---|---:|
| `06001401700` | `8da97ba5` | 1878 |
| `06001422100` | `d4146486` | 2630 |
| `06057000900` | `fa12be75` | 3782 |
| `06067000400` | `6b015022` | 3909 |
| `06073001400` | `3cca4341` | 3283 |
| `06081604900` | `f54492d9` | 3244 |
| `06085511200` | `7f8bd819` | 4666 |
| `08031002000` | `39fc3efc` | 619 |
| `08031002000` | `71d85fbd` | 619 |
| `08069002700` | `a66fd724` | 5104 |
| `08077000200` | `b7da4a3a` | 2221 |
| `08077000700` | `5b4c9b60` | 4326 |
| `12087970900` | `67624825` | 2058 |
| `12099002600` | `24ec8466` | 414 |
| `13121002500` | `8f881da5` | 1981 |
| `13121003900` | `bb41c52d` | 2426 |
| `13313000700` | `fccb0598` | 3670 |
| `17031320400` | `d33bc6ab` | 575 |
| `17161021100` | `8170fba4` | 3582 |
| `17201000600` | `a38b1d05` | 4256 |
| `19113001500` | `af35715a` | 2997 |
| `24510010500` | `2003d090` | 1897 |
| `25005632100` | `5f87f80c` | 6242 |
| `25017356300` | `58e18c18` | 5031 |
| `26021001300` | `f0e0806e` | 2003 |
| `26089970100` | `e195a200` | 2101 |
| `26125131500` | `e2cd29b0` | 3961 |
| `27053110900` | `b4160286` | 3647 |
| `27123032000` | `826709c8` | 2856 |
| `31055002500` | `dba7f0bd` | 2580 |
| `31105954500` | `bb42acfe` | 4089 |
| `33015051000` | `1a473e7c` | 3792 |
| `33015058000` | `d9ad0fc1` | 3701 |
| `34023001100` | `b60771b7` | 4397 |
| `34023006500` | `d159235d` | 6451 |
| `34029713100` | `caf73bab` | 7018 |
| `34029713600` | `e0cb3db9` | 3773 |
| `36047019500` | `b35356f6` | 3821 |
| `36059409000` | `5b868158` | 5953 |
| `36061000900` | `64a47cd8` | 1111 |
| `36061001300` | `1074e64b` | 1525 |
| `36061003100` | `09f35468` | 1726 |
| `36061007600` | `e513188c` | 2493 |
| `36063021100` | `b0ca9bbc` | 2179 |
| `36081071100` | `dc5c75c8` | 4420 |
| `36081073900` | `64949192` | 4994 |
| `36111952300` | `f207e9a4` | 1711 |
| `39103405000` | `71d8ea55` | 3928 |
| `41039004600` | `733e7ef5` | 2721 |
| `41039005000` | `8ca13666` | 5099 |
| `41041951100` | `a2716ed5` | 1661 |
| `41041951200` | `8dcdf498` | 1736 |
| `41065970200` | `34efa7ae` | 2885 |
| `42101007900` | `cad84768` | 4777 |
| `47065001800` | `1754635c` | 3331 |
| `48453000700` | `7d3e5258` | 1469 |
| `49035101800` | `f3d65109` | 3313 |
| `50007000100` | `1445b762` | 4651 |
| `51013101300` | `590f63b0` | 5820 |
| `51760020900` | `100c2b8f` | 2949 |
| `53007960700` | `177681ef` | 2734 |
| `53073001000` | `56677086` | 6918 |
| `53075000700` | `b4838b92` | 3684 |

</details>

### 5.4 Re-absence — confirmed

**76 parcels re-recorded `absent`/`api_no_data` for `decennial`/`2000`.**
Adjusted prediction: 76. They split exactly along the predicted line:

| class | count | tract ends `00`? |
|---|---:|---|
| tract carries a real suffix that did not exist in 2000 | **60** | no |
| tract ends `00` but `2000/dec/sf1` 204s under the four-character form too | **16** | yes |

The 16 are precisely `../2026-08-census-decennial/REPORT.md` §1.5's list, each
now confirmed a second time from production rather than from a live probe:
`08031015300`, `09170157100`, `11001980000` (×3 parcels), `17031839100`,
`17031980000`, `26019000500`, `26061000800`, `29147470400`, `34023009300`
(×2), `36121970700`, `48453032600`, `53035940000`, `55079187300`. Racebrook
(`09170157100`) stays absent and was the only parcel STATUS.md expected to.

**All 76 are permanent absences, and the ledger has no way to say so.**
`absent`/`api_no_data` is the same row a pre-trim parcel got; nothing
distinguishes "the API has no data for this tract, ever" from "the request
was wrong and has since been fixed". The retry policy therefore still treats
all 76 as retryable-behind-a-flag, and **the next
`--from-ledger --sources census_decennial --include-absent-api` run selects
all 76 again**, spending ~9 Census API calls and ~4.5 s of inter-year sleep
per parcel to re-record the identical row.

This is Y3's sibling, not Y3. Y3 was a group *current code no longer
attempts* (`1990`), closed by `is_stale` + `attempted_group_keys`. This is a
group current code **does** attempt, correctly, whose answer will not change.
`is_stale` cannot reach it. Recorded in STATUS.md as a new row; **not fixed
in this batch.**

### 5.5 Isolation — confirmed

| check | before | after | verdict |
|---|---|---|---|
| `imagery_snapshots` count | 12,751 | 12,751 | unchanged |
| `imagery_snapshots` `md5(ids)` | `8839c46e…986d` | `8839c46e…986d` | **identical** |
| by source | 8040 / 1293 / 2235 / 1183 | 8040 / 1293 / 2235 / 1183 | unchanged |
| `decennial` 2010 rows, `md5(ids)` | 187, `b2b0969f…da86` | 187, `b2b0969f…da86` | identical |
| `decennial` 2020 rows, `md5(ids)` | 187, `85ebc901…6413` | 187, `85ebc901…6413` | identical |

**Zero imagery rows created or deleted fleet-wide**, by id set, not merely by
count. A census-only scope creates no imagery task row, so
`reconcile_source_snapshots` was never reachable.

**Zero ledger rows for any non-census source from this run's tasks.** Every
row the 139 tasks wrote:

```
census_acs5       2009  absent/api_no_data   47
census_acs5       2009  ok                   92
census_acs5       2012/2015/2018/2021/2023  ok  139 each
census_decennial  2000  absent/api_no_data   76
census_decennial  2000  ok                   63
census_decennial  2010  ok                  139
census_decennial  2020  ok                  139
```

Only `census_acs5` and `census_decennial`. No `landsat`, `naip`, `sentinel2`,
`usgs_topo`.

**One honest limit on the 2010/2020 claim.** The census task covers all of
`DECENNIAL_YEARS`, so 2010 and 2020 *were* re-fetched and re-upserted on all
139 parcels — that is by design, not scope leakage. What is proved is that no
2010/2020 row was added, removed or replaced: the id-set md5s are identical
and zero rows in those years have a `created_at` after 16:50Z. What is **not**
proved is value-identity, because the before-state captured id checksums only
and `census_snapshots` has no `updated_at`. A content checksum is recorded
here so the next run can diff against it:
`decennial` 2010 → `584fa0ed05386a0ad610d3e46a938d0f`,
2020 → `21d3aa8a47dc7a74e9138e656cb1240d`
(over `total_population|median_household_income|median_home_value|total_housing_units`,
ordered by id).

**Ride-along, predicted as unpredicted.** P2 §6 declined to make any claim
about `census_acs5` and said any movement there would be a ride-along that
can only add rows. Observed: `acs5`/`2009` went `absent` 75 → 47 fleet-wide
and `census_snapshots` `acs5`/`2009` went 112 → 140 — **28 rows gained**. No
other `acs5` year moved. Consistent with the acs5-2009 vintage-resolution
behaviour recorded in `../2026-08-racebrook/REPORT.md`; not scored here,
because no prediction was made.

Rows created after 16:50Z, all datasets and years: `decennial`/2000 = 63,
`acs5`/2009 = 28. Nothing else.

### 5.6 Current-request rule (§2.2 trigger-6 guard) — confirmed

`_find_reusable_request` called read-only against production for the first
three healed parcels:

| parcel | current request | scope | this run's heal request |
|---|---|---|---|
| `09f35468` | `916eec5c` (2026-08-26 08:04:56Z) | full six-source | `1c2d9a99` `['census']` |
| `100c2b8f` | `11464582` (2026-08-26 02:43:20Z) | full six-source | `708f38bd` `['census']` |
| `1074e64b` | `80f3fbfd` (2026-08-26 02:40:20Z) | full six-source | `eaf7ec65` `['census']` |

In all three the current request is the older full-scope one and **is not**
the scoped heal, even though the heal is newer and `complete`. The
`full_scope_clause` filter is doing what it was added for: had the census-only
request become current, `maybe_refetch_for_backfill` would see a request with
no `usgs_topo` task row and re-dispatch the whole pipeline on every page view
forever.

Observed through the service function rather than the HTTP endpoint on
purpose: `POST /timeline` is the only route that exposes it, and it is a
write. `GET /timeline-requests/{id}` reads a request by id and cannot answer
"which request is current".

### 5.7 Failures — none

**Zero `failed` ledger rows from this run**, so zero `failed/http_*` rows —
the reason split from `e6afa9b` had nothing to record, which is the correct
outcome for a run in which every Census call either answered or legitimately
204'd. Nothing to quote.

Fleet-wide, the only latest-`failed` group is the pre-existing
`landsat`/`read_timeout` ×1, unchanged by this run. No `error_message` on any
of the 139 requests. The captured `fly logs` for both apps contain no error,
traceback or exception attributable to the run.

---

## 6. Anomalies and deviations (flagged, not fixed)

1. **Neither `fly logs` stream carried the script's admission-wait lines.**
   The gate expected the API stream to carry them. It did not: the script runs
   as `fly ssh console -C`, whose stdout goes to the ssh session, not to the
   app's log stream — `grep -ci admission` is **0** on both `api.log` and
   `worker.log`. Every admission number in §5.2 comes from the captured
   invocation output instead, which is the same text. A process deviation with
   no effect on the evidence, recorded so the next run's gate expects the right
   source.
2. **`census_decennial`/`1990` is still 187 `absent`/`api_no_data`** and will
   stay so permanently. Confirmed unchanged and correctly not selected. This
   is Y3 working as designed, not a defect — but it is the same shape as §5.4:
   two distinct permanent classes now sit in the ledger under the one
   `absent`/`api_no_data` vocabulary, one excluded by `is_stale` and one not.
3. **The 16-tract exception list is now verified twice** and can drop its
   UNVERIFIED marker on the recovery arithmetic: it was probed live
   2026-08-26, and this run re-recorded `absent` on exactly those 16 and no
   others. The recovery count landing on 63 rather than above it is the
   evidence.

---

## 7. Verdict

**P2 confirmed, zero deviation.** 139 selected, 63 recovered, 76 re-absent,
max heal admission depth 25, zero imagery churn, zero non-census ledger rows,
zero failures, exit 0 — every adjusted number hit exactly, and the one number
that moved from the original prediction (64 → 63) moved for the reason the
2026-08-27 addendum wrote down in advance. The decennial-2000 tract-width
defect is healed fleet-wide. One new gap — permanent absences the ledger
cannot mark as permanent — enters STATUS.md unfixed.
