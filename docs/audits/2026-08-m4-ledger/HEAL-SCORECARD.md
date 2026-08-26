# M4 ledger — first production sweep, scorecard

**Written:** 2026-08-26, after the run.
**Authorised:** one full-fleet `scripts/revalidate_landsat.py` run under the
written heal exception. One production write was issued; nothing else.
**Deploy under measurement:** `3a86dd69211c460cee22245d30605941fdd55168`
(`GH_SHA` on both `log0s-plotline-api` machines and both `plotline-worker`
machines; `/api/v1/health` agrees, `built` `2026-08-26T01:29:08Z`).
**Scores:** `PREDICTION.md`, written 2026-08-25 before deploy and unedited.
**Baseline:** `BASELINE.txt` (16,244 rows), `BASELINE-failed.txt` (empty),
`BASELINE-indeterminate.txt` (8 rows).

**Verdict: the sweep ran clean and the prediction holds on every falsifiable
item. Two findings, neither in the ledger: one served NAIP card shows a tile
that does not contain its parcel, and the log capture lost three minutes that
the ledger covered anyway.**

---

## 1. Capture coverage

| Stream | Started | Ended | Lines |
|---|---|---|---|
| `fly logs -a plotline-worker` (tail) | 02:15:49Z | 03:09:18Z | 5,384 |
| `fly logs -a log0s-plotline-api` (tail) | 02:15:49Z | 03:09:18Z | 127 |
| `fly logs -a plotline-worker --no-tail`, 60 s | 02:15:49Z | 03:09:18Z | 4,848 |
| `fly logs -a log0s-plotline-api --no-tail`, 60 s | 02:15:49Z | 03:09:18Z | 4,949 |
| `revalidate_landsat.py` stdout (ssh session) | 02:16:35Z | 02:56:35Z | 1,152 lines, 184 `queued` |

Deduplicated by the structured `timestamp` field, tail and polls together hold
**5,466 distinct worker events**.

**Gap map.** Of the 52 minutes 02:16Z–03:07Z, the worker tail carries lines in
46. Reconciled against the database — `completed_at` truncated to the minute,
184 completions across 48 distinct minutes — three minutes hold completions
and no tail line:

| Minute | Completions | In tail | In 60 s poll |
|---|---|---|---|
| 02:53 | 4 | no | **no** |
| 02:54 | 4 | no | **no** |
| 02:55 | 4 | no | yes (recovered) |

The other three tail-silent minutes (03:05, 03:06, 03:07) are genuine quiet:
the last completion is `03:04:07.532135Z` and the last worker log line is
`03:04:07Z`.

**So: 8 of 184 requests (4.3 %) ran with no log capture at all.** The
consequence is scoped and named in §7 — it is why three of the nine
`suppressed` ledger rows have no matching log line, and it is the one place
this scorecard cannot cross-check the log in both directions.

**Two capture facts that differ from the brief's assumptions.**

1. **The admission-wait lines never reach `fly logs -a log0s-plotline-api`.**
   Zero matches for `admission slot` in either API stream across the whole
   window. The script runs in an `fly ssh console` session, not under the
   machine's main process, so its stdout comes back on the ssh channel and
   nowhere else. Every wait figure in §2 is read from the sweep's own stdout.
2. **Only one worker machine appears in the capture.** All 10,149 worker log
   lines carry `app[e2862966b306d8]`; `e7845415f57728` emits nothing in the
   window. Not investigated — flagged in §13.

---

## 2. Sweep hygiene

```
Done — queued 184 timeline request(s), skipped 0.
exit=0
```

| | |
|---|---|
| Command | `python -u scripts/revalidate_landsat.py --max-wait-minutes 90` |
| Start / end | 02:16:35Z / 02:56:35Z (enqueue), last completion 03:04:07Z |
| Parcels reached | **184 of 184** |
| Skipped | 0 |
| `unreached:` lines | 0 |
| Exit code | **0**, captured |
| Requests created | 184, all `complete`; **zero `failed`, zero non-terminal** |
| Tasks | `census` 184 complete, `landsat` 184, `naip` 184, `sentinel2` 184, `usgs_topo` 184 complete; `property` 31 complete / 153 skipped |

The only task-level error messages are 153 `property` rows reading `Property
data not yet available for <county>` — the documented no-adapter path, not a
failure, and outside the ledger (property has no period key).

### 2.1 Admission waits — the production verification of `b537953`

**`depth` and `cap` appeared in the log. Yes.** First captured line, verbatim:

```
2026-08-26T02:16:49.226244Z [info     ] Waiting for an admission slot  [app.services.admission] cap=30 depth=30 poll_seconds=5.0 wait_remaining_s=5389.9
```

This is the first time the fields `d6b21b3` added and `b05458b` / `b537953`
connected have been seen against a real sweep. Every figure below is parsed
from those lines, not reconstructed from `created_at`:

| | |
|---|---|
| Wait episodes (`Admission refused` → next `Created new timeline request`) | **135** |
| Poll lines (`Waiting for an admission slot`) | **460** |
| Distinct `depth` values | `{30}` |
| Distinct `cap` values | `{30}` |
| Total time waiting | **2,342.4 s** |
| Enqueue span (first→last `Created new timeline request`) | 2,379.0 s |
| Wait fraction | **98.5 %** |
| Mean / median | 17.4 s / 15.3 s |
| Longest / shortest | **30.5 s** / 5.2 s |
| Polls per episode | min 1, median 3, max 6 |
| Budget consumed | `wait_remaining_s` never fell below ~3,010 of 5,400 |

135 refusals, 135 waits, 135 slots opened, 184 parcels reached. The brief
predicted ~150 waits; 135 is the measurement.

**Verdict: confirmed.** G9's outstanding item — "verified under CI and under a
local shell, and never once against a real sweep" — is closed, along with the
exit-code method gap: `exit=0` was captured, not inferred.

---

## 3. Ledger population — P1, P2

**16,244 rows.** Prediction P2: 16,100 ± 300. **Confirmed.**

| ledger `source` | rows | groups/parcel predicted | groups/parcel observed |
|---|---|---|---|
| `landsat` | 7,912 | 43 | 43 on all 184 |
| `sentinel2` | 2,208 | 12 | 12 on all 184 |
| `naip` | 3,128 | 17 | 17 on all 184 |
| `census_decennial` | 736 | 4 | 4 on all 184 |
| `census_acs5` | 1,104 | 6 | 6 on all 184 |
| `usgs_topo` | 1,156 | variable | 1–10, median 6 |

**P1: confirmed exactly.** The query for any parcel whose fixed-source counts
differ from 43 / 12 / 17 / 4 / 6 returns **zero rows**. Rows per parcel run
83–92, median 88 — 82 fixed plus that parcel's topo rows, with no exceptions:

```
83:1  84:2  85:11  86:16  87:31  88:35  89:40  90:28  91:15  92:5
```

184 × 82 = 15,088; 15,088 + 1,156 = 16,244. The arithmetic closes to the row.

**Deviation inside P2: the topo split.** Predicted ≈ 989 decade rows over 157
parcels plus 27 whole-source `*` rows. Observed **1,154 decade rows over 183
parcels plus 2 `*` rows**. The total stays inside the ±300 band, but the shape
is different, and PREDICTION §8 said why it might be: the ledger counts decades
*in the TNM response*, while the historical 6.3/parcel average counts decades
that produced a *snapshot*. The "27 parcels hold no topo" figure was a fact
about snapshots; only **one** parcel's TNM search returned nothing this run.

### Outcome distribution

| source | ok | absent | suppressed | indeterminate | failed |
|---|---|---|---|---|---|
| `landsat` | 7,912 | — | — | — | — |
| `sentinel2` | 2,199 | 9 | — | — | — |
| `naip` | 1,272 | 1,840 | 9 | 7 | — |
| `usgs_topo` | 1,154 | 1 | — | 1 | — |
| `census_decennial` | 414 | 322 | — | — | — |
| `census_acs5` | 1,028 | 76 | — | — | — |
| **total** | **13,979** | **2,248** | **9** | **8** | **0** |

Reasons, complete: `api_no_data` 398, `no_scenes` 1,841, `all_cloud_filtered`
9, `naip_no_point_coverage` 9, NAIP item cap 7, TNM row cap 1. Every non-`ok`
row carries a machine reason; none is null.

---

## 4. The falsifier — P6a

**Zero.** `ok` ledger rows from this sweep whose `(parcel_id, source,
group_key)` has no matching served snapshot: **0 for imagery, 0 for census.**
The atomicity argument in PREDICTION §6 stands.

The `ok` set is not merely consistent with the served set — for three sources
it *is* the served set, row for row:

| source | `ok` groups | served snapshot rows |
|---|---|---|
| `landsat` | 7,912 | 7,912 |
| `sentinel2` | 2,199 | 2,199 |
| `naip` | 1,272 | 1,273 |
| `usgs_topo` | 1,154 | 1,163 |
| `census_decennial` | 414 | 414 |
| `census_acs5` | 1,028 | 1,028 |

The two differences are accounted for exactly in §5.

---

## 5. The inverse — P6b, and the brief's stricter form

**P6b as written (snapshots created inside the sweep window): zero, and the
population is empty** — the sweep created no snapshot rows at all (§10), so
P6b is confirmed but vacuous.

The brief asked the stricter, unscoped question: *every* served snapshot row
whose group has no `ok` ledger row from this sweep. That is **10 rows, all on
one parcel, `e513188c`**:

| rows | source | ledger says |
|---|---|---|
| 9 | `usgs_topo` (1889, 1891, 1900, 1935, 1940, 1955, 1966, 1984, 1995) | `absent` / `no_scenes` on the `*` row; no decade rows at all |
| 1 | `naip` 2023 (`nj_m_4007309_sw_18_030_20230820_20231019`) | `suppressed` / `naip_no_point_coverage` |

Census: **zero** in this direction too.

The nine topo rows are the case PREDICTION §6 carved out deliberately — TNM
returned nothing for this parcel this run, and reconciliation leaves absent
groups alone, so rows a previous run landed stay served. Correct behaviour,
now visible for the first time.

**The NAIP row is a finding.** See §13.1.

---

## 6. `absent`, its reasons, and the empty-chunk probe

| source | reason | count |
|---|---|---|
| `naip` | `no_scenes` | 1,840 |
| `census_decennial` | `api_no_data` | 322 |
| `census_acs5` | `api_no_data` | 76 |
| `sentinel2` | `all_cloud_filtered` | 9 |
| `usgs_topo` | `no_scenes` | 1 |

### 6.1 The O6 nine — P3

Sentinel-2 2015 fleet-wide: **175 `ok`, 9 `absent`/`all_cloud_filtered`, and
nothing else.** The nine are exactly the nine `LOGGING-FIX.md` §2 named:

```
177681ef  absent  all_cloud_filtered      e4a9bed5  absent  all_cloud_filtered
1f0c42aa  absent  all_cloud_filtered      eab6adf5  absent  all_cloud_filtered
34efa7ae  absent  all_cloud_filtered      fa12be75  absent  all_cloud_filtered
39286f1d  absent  all_cloud_filtered
7fb423de  absent  all_cloud_filtered      ad00ac68  absent  all_cloud_filtered
```

**P3: confirmed, and tighter than predicted.** The prediction allowed more
than nine; the answer is exactly nine, with zero `no_scenes` — which was the
stated falsifier for the probe. The set of S2-2015 non-`ok` parcels and the set
of O6 nine are the same set.

### 6.2 Probe firings

`_classify_empty_chunk` fires once per empty cloud-filtered chunk, on the two
sources carrying a `query` (`landsat`, `sentinel2`). Landsat recorded **zero**
non-`ok` years fleet-wide, so it produced no empty chunks and no probes.
Sentinel-2 produced **9**. **Total probe queries this sweep: 9**, all
resolving to `all_cloud_filtered`, **zero** `no_scenes`, **zero**
`cloud-probe failed`. Against PREDICTION §3's budget ("a handful of requests
per run, not a second pass") — confirmed.

**Method deviation, recorded not worked around:** the brief asked for the
probe count "from the log". There is no log line at the probe site —
`_classify_empty_chunk` calls `_search_stac_with_retry` directly and neither
logs on success. The count above is derived from the ledger, which records one
row per probe outcome and is exact; it is not a log measurement. If a future
run needs the probe counted independently of the ledger, the line has to be
added first.

---

## 7. `failed` — P4

**Zero `failed` rows fleet-wide.** `ledger_gaps.py --outcome failed` prints
`No ledger rows match.` (`BASELINE-failed.txt`).

P4 predicted 0–10, topo-dominated. **Confirmed, at the floor.**

**Cross-check against the log, both directions.**

*Ledger → log:* vacuous. No `failed` row exists.

*Log → ledger:* across all 5,466 deduplicated worker events, warnings and
errors are:

| event | count | ledger consequence |
|---|---|---|
| `DC permits query failed` | 9 | none — `property`, no period key |
| `Suppressing imagery year with no covering tile` | 6 | `naip` `suppressed` |
| `Socrata query hit its row cap` | 4 | none — property adapter |
| `STAC search hit its item cap` | 1 (`source: naip`) | 7 `naip` `indeterminate` |
| `TNM query hit its row cap` | 1 | 1 `usgs_topo` `indeterminate` |
| `ArcGIS query hit its row cap` | 1 | none — property adapter |

Zero `Band signing failed after retries`, zero `SAS rate-limited … giving up`,
zero `STAC year chunk failed after retries`, zero `USGS topo fetch failed`,
zero `httpx.ReadTimeout`. No upstream incident occurred in the window, and the
ledger says the same.

**The one reconciliation failure, and it is the capture's, not the ledger's.**
The ledger holds **9** `suppressed` rows; the log holds **6** suppression
lines. The three unlogged rows are `8d9ee137` / 2012, 2014, 2016. That
request ran **02:47:22Z → 02:55:12Z** — its suppression lines were emitted
inside the 02:53–02:55 capture hole from §1. The ledger recorded what the log
capture lost, which is the first time this batch's instrument has demonstrated
its own reason for existing.

---

## 8. `indeterminate` — P5

**8 rows. Zero with the `no outcome` reason. Zero `cloud-probe failed`.**
P5 predicted under 20 with zero `no outcome`. **Confirmed.**

| parcel | source | group | reason |
|---|---|---|---|
| `fe065e2d` | `naip` | 2010, 2019, 2020, 2022, 2024, 2025, 2026 | NAIP search hit its item cap |
| `9c35ceb0` | `usgs_topo` | `*` | TNM response hit its row cap |

Both sites match the ones `REPORT.md` listed, and both agree with the log to
the event: one `STAC search hit its item cap` warning at 02:44:48Z
(`source: naip`) for `fe065e2d`'s single whole-range NAIP search, which fans
out to one `indeterminate` row per absent year in that search — 7 of them —
and one `TNM query hit its row cap` warning at 02:25:02Z for `9c35ceb0`.

The two sites PREDICTION §5 expected to read zero — the probe failing, and a
group reaching the end of `_search_and_persist_source` with no verdict — both
read **zero**. The residual `no outcome` pass firing would have been a new
defect; it did not fire.

---

## 9. Topo `*` rows

**Two `*` rows**, both explained:

| parcel | outcome | reason | decade rows under it |
|---|---|---|---|
| `9c35ceb0` | `indeterminate` | TNM row cap | present |
| `e513188c` | `absent` | `no_scenes` | **none** |

`e513188c` is the only parcel in the fleet with zero topo decade rows, and it
carries a `*` row — the shape PREDICTION §1 called correct. The defect shape
it named (82 + 0 rows and *no* `*` row) does not occur.

**Per-decade rows against served topo rows:** `ok` decade rows with no served
snapshot for that decade: **0**. Served topo decades with no `ok` row this
sweep: **9**, every one on `e513188c` (§5). 1,163 served − 9 = 1,154 = the
`ok` count. The two records reconcile exactly.

---

## 10. Snapshot churn

**Zero.** Not "minimal" — zero.

The before-state (02:15:22Z) and after-state (03:07Z) captures of every
`imagery_snapshots` row — `(parcel_id, source, capture_date, stac_item_id,
created_at)`, 12,547 rows — are **identical**: 0 rows only in before, 0 rows
only in after. Same for `census_snapshots` (1,442 rows).

| source | before | after | created in window |
|---|---|---|---|
| `landsat` | 7,912 | 7,912 | 0 |
| `naip` | 1,273 | 1,273 | 0 |
| `sentinel2` | 2,199 | 2,199 | 0 |
| `usgs_topo` | 1,163 | 1,163 | 0 |

The newest `created_at` in the table is `2026-08-25 22:30:26Z`, before this
sweep started. No closed-group change, because no change at all: the fleet was
already swept under the S2-year code on 2026-08-25, so this run re-selected the
same items and reconciliation had nothing to do. The prediction expected
"minimal and open-year only"; zero satisfies it, and it makes §4's row-for-row
agreement a statement about a stable population rather than a moving one.

---

## 11. Census

**Zero census rows gained. No parcel's census year set changed.** 1,028 `acs5`
and 414 `decennial` before and after; newest `created_at` `2026-08-25
01:43:22Z`.

What is new is the *record of what was asked*, which has never existed before:

| dataset | year | ok | absent (`api_no_data`) |
|---|---|---|---|
| `census_decennial` | 1990 | 0 | **184** |
| | 2000 | 47 | 137 |
| | 2010 | 184 | 0 |
| | 2020 | 183 | **1** |
| `census_acs5` | 2009 | 109 | 75 |
| | 2012 | 184 | 0 |
| | 2015 | 184 | 0 |
| | 2018 | 184 | 0 |
| | 2021 | 183 | **1** |
| | 2023 | 184 | 0 |

This is the first measurement of the `if data:` skip PREDICTION §8 said had
never been instrumented. Decennial 1990 is absent for **every parcel in the
fleet** — the API returns nothing for it at tract level, uniformly. Decennial
2000 and ACS5 2009 are absent for a large minority. None of this was visible
before today; all of it was silently `complete`.

### 11.1 `2f1b332e` — Racebrook Road, Orange, Connecticut

The parcel M4 occurrence (4) was scheduled on. It holds 5 census rows against
7–9 for its peers, and nothing in the system could say whether the missing
years re-failed or were never published. **The ledger now says.** Every one of
its ten census groups recorded an outcome, with the tract it asked about in
`detail`:

| source | group | outcome | detail |
|---|---|---|---|
| `census_acs5` | 2009 | `absent` / `api_no_data` | empty response for tract **09170**157100 |
| `census_acs5` | 2012 | `ok` | tract **09009**157100 |
| `census_acs5` | 2015 | `ok` | tract **09009**157100 |
| `census_acs5` | 2018 | `ok` | tract **09009**157100 |
| `census_acs5` | 2021 | `absent` / `api_no_data` | empty response for tract **09170**157100 |
| `census_acs5` | 2023 | `ok` | tract **09170**157100 |
| `census_decennial` | 1990 | `absent` / `api_no_data` | empty response for tract **09170**157100 |
| `census_decennial` | 2000 | `absent` / `api_no_data` | empty response for tract **09170**157100 |
| `census_decennial` | 2010 | `ok` | tract **09009**157100 |
| `census_decennial` | 2020 | `absent` / `api_no_data` | empty response for tract **09170**157100 |

**The answer is: not a re-failure. The API returned an empty response for the
tract we asked about, every time.** And the pattern in the `detail` column is
the shape of the question that replaces it: every failing year was asked under
`09170157100` (Greater New Haven Planning Region, the post-2022 Connecticut
geography) and every succeeding year but one was asked under `09009157100`
(New Haven County, the pre-2022 geography). ACS5 2023 succeeds under `09170`;
ACS5 2021 and decennial 2020 fail under it.

Fleet-wide, `2f1b332e` is the **only** parcel in 184 that misses decennial 2020,
and the **only** one that misses ACS5 2021. Its 1990/2000 absences are the
fleet-wide pattern above and carry no parcel-specific signal.

Whether asking `09170` for a 2020/2021 vintage is the right question is a new
investigation, not this scorecard's — flagged in §13.3. What is settled is that
M4 occurrence (4)'s stated blocker is gone: the years are recorded, with
reasons and with the tract, and a heal can now be targeted at them.

### 11.2 The rest of `2f1b332e`

`landsat` 43 `ok`; `sentinel2` 12 `ok`; `naip` 6 `ok` / 11 `absent`;
`usgs_topo` 7 `ok`. No `failed`, no `indeterminate`.

---

## 12. Baseline

`BASELINE.txt` — `ledger_gaps.py --all`, 16,244 rows, captured 03:07Z at
database clock `2026-08-26 03:06:48 UTC` under SHA `3a86dd69…`, header line
carrying both. `BASELINE-failed.txt` (`--outcome failed`, no rows) and
`BASELINE-indeterminate.txt` (`--outcome indeterminate`, 8 rows) captured
separately; `--outcome` is supported and forces listing.

Every later sweep diffs against these.

---

## 13. Anomalies — flagged, not investigated

### 13.1 A served NAIP card shows a tile that does not contain its parcel

`e513188c` serves `imagery_snapshots` row `nj_m_4007309_sw_18_030_20230820_
20231019` for NAIP 2023 (created `2026-05-23`). This sweep's ledger records
that same group as `suppressed` / `naip_no_point_coverage`, detail *"selected
tiles do not contain the parcel: nj_m_4007309_sw_18_030_20230820_20231019,
nj_m_4007424_ne_18_030_20230820_2023…"* — the same item id.

The point-coverage gate (`14b59af`) refuses to *write* such a row; it does not
remove one already written, and reconciliation leaves suppressed groups alone
by the same rule that protects absent ones. So the parcel's 2023 NAIP card is
still being served from a tile the gate has now positively identified as not
containing the parcel. **This is user-visible and it is the only instance in
the fleet** — the other 8 `suppressed` rows (`1754635c` ×5, `8d9ee137` ×3) have
no served snapshot for their groups.

### 13.2 One worker machine produced every log line

All 10,149 captured worker lines carry `app[e2862966b306d8]`. `e7845415f57728`
is `started` per `fly image show` and emitted nothing in 53 minutes while 184
requests drained. Whether it consumed no tasks or its logs did not reach `fly
logs` is unresolved.

### 13.3 Racebrook's tract vintage

§11.1: the failing years are asked under `09170157100`, the succeeding ones
under `09009157100`, and ACS5 2023 succeeds under `09170`. Connecticut's
2022 county-to-planning-region change is the obvious mechanism and
`scripts/heal_tract_vintage_gaps.py` already exists for that shape. Not
investigated here.

### 13.4 A three-minute capture hole

§1. 8 of 184 requests ran unlogged. Not a production defect — a method one, and
the reason §7's log-to-ledger direction carries a caveat. `fly logs` tail plus
60 s `--no-tail` polls did not achieve full coverage; the polls recovered one
of the three minutes.

---

## 14. Deviations from the brief

1. **`python -u`, not `python`.** The brief named `python
   scripts/revalidate_landsat.py --max-wait-minutes 90`. Run through an `fly
   ssh console -C` pipe, Python block-buffers stdout, and the wait lines the
   brief requires be read "from the log line, not reconstructed" would have
   arrived in 4 KB bursts or been lost on the buffer at exit. `-u` changes
   buffering only. The invocation was otherwise exact, and run once.
2. **Probe count derived from the ledger, not the log.** §6.2. There is no log
   line at the probe site to count.
3. **The falsifier computed in both scopings.** §5 reports the brief's
   unscoped form (10 rows) alongside PREDICTION P6b's `created_at`-scoped form
   (0 rows, empty population). The prediction's scoping is the one under score;
   the brief's is the one that found `e513188c`.

## 15. UNVERIFIED

- **That a second sweep adds another 16,244 rows** (PREDICTION §2's claim about
  per-run row accumulation). One sweep has run; nothing here tests it.
- **Whether `e7845415f57728` processed any task.** §13.2 — not investigated.
- **Whether 09170 is the correct tract to ask for 2020/2021 vintages.** §13.3.
- **The 8 unlogged requests.** Their ledger rows are present and consistent;
  their worker log lines are gone and cannot be recovered — `fly logs` retains
  no buffer that far back by the time the gap was identified.
