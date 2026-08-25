# S2-Year Sweep, Completion — Post-Sweep Scorecard

Scored against the **A1–A7 addendum** of `PREDICTION.md`, written 2026-08-25
after the first sweep truncated and before this one ran. Nothing in that file
was edited.

Sweep run **2026-08-25, 21:46:29Z → 22:31:25Z** against
`37f793129317971b399122858230751be5070a38`.

**The sweep covered all 154 remaining parcels and exited cleanly.** With the
30 from `HEAL-SCORECARD.md`, the fleet of 184 is now swept under year
grouping. Every fleet-wide line the first scorecard had to leave unscored is
scored here.

**Execution exception.** This sweep, like the first, was invoked by a Claude
session rather than by Ryan, under a one-time written exception in the
session prompt, so that log capture could start before the sweep rather than
mid-way through. The exception was bounded by a five-line gate (§0); all five
held. The only production write was the single `revalidate_landsat.py`
invocation; everything else was `SELECT`s and log reads.

Artefacts: before/after DB snapshots (14,148 and 12,547 rows), the continuous
worker log stream (5,170 unique lines), 47 `--no-tail` polls, the script's
own stdout/stderr, and the 154 `created_at` timestamps used to measure the
admission waits.

---

## 0. The gate

| Gate | Required | Observed | Source |
|---|---|---|---|
| Worker image SHA | `37f7931…070a38` | `GH_SHA=37f793129317971b399122858230751be5070a38` on both machines (`e2862966b306d8`, `e7845415f57728`) | `fly image show -a plotline-worker` |
| API health SHA | same | `"sha":"37f793129317971b399122858230751be5070a38"`, built `2026-08-25T21:38:31Z` | `GET /api/v1/health` |
| No in-flight work | 0 `queued`/`processing` | 365 `complete`, 3 `failed`, **0 in flight** | DB, 21:44:34Z |
| Dry-run scope | 154, all six featured, none of the 30 | **154**; 6 of 6 featured present; overlap with the swept 30 = **0** | `--dry-run`, 21:45Z |
| Capture before the sweep | stream started first | stream `21:46:03Z`, sweep `21:46:29Z` — **26 s of margin** | local |

`revalidate_landsat.py` still has **no deployed-SHA gate**; `--require-sha` /
`--skip-deploy-check` remain only in `requeue_parcels.py`. The gate above was
again executed by hand. This is the third heal in a row where the operator,
not the tool, carried the ordering — unchanged from the first scorecard's §0
and repeated here because it is still true.

`--since 2026-08-25T19:09:45Z` was used rather than `--skip-swept-since`:
the SHA that ran the first sweep (`bc1125cd…`) is no longer deployed, which
is exactly the case the `--since` flag was added for.

### Timeline

| Time (UTC) | Event |
|---|---|
| 21:44:34 | In-flight gate read — 0 `queued`/`processing` |
| 21:45:29 | Before-state captured — 14,148 rows (landsat 7,903 / sentinel2 3,965 / naip 1,267 / topo 1,013; 184 parcels) |
| 21:46:03 | Continuous `fly logs -a plotline-worker` stream starts |
| 21:46:11 | 60 s `--no-tail` poller starts |
| 21:46:29 | `revalidate_landsat.py` invoked (once) |
| 21:46:33 | First request created |
| ~21:46:37 | Admission cap reached; the first `Admission refused` follows |
| 22:20:00 | Last request created — enqueue span **2,007.2 s** |
| 22:20:34 | Script process observed exited (last seen alive 22:19:00) |
| 22:31:25 | Last request `complete` (2,692 s of worker time from first enqueue) |
| 22:31:49 | Terminal state confirmed by DB poll — 154/154 `complete`, 0 `failed` |
| 22:32:04 | After-state captured — 12,547 rows |
| 22:34:13 | Capture stopped |

---

## 1. Capture coverage

**No gaps.** The stream started 26 s before the sweep and ran 168 s past the
last completion, so the entire 21:46:29 → 22:31:25 window is continuously
covered. The stream process never died; the watchdog armed to restart it
never fired and `stream_gaps.txt` was never written.

Poll/stream reconciliation over the sweep window, deduplicated:

| | Lines |
|---|---|
| Unique lines seen by the 47 `--no-tail` polls | 4,223 |
| Unique lines seen by the stream | 5,170 |
| **Poll lines absent from the stream** | **0** |
| Stream lines absent from the polls | 947 |

The stream is again a strict superset. The 947-line difference is the
poller's 100-line buffer cap losing data between polls.

Independent log/DB reconciliation: the **163** `Replaced superseded imagery
snapshots` events in-window sum to **1,827 deletions (1,818 sentinel2 + 9
landsat)**, which is exactly the DB-measured deletion count on both sources.
Log and DB agree to the row.

A second independent check: the stream carries exactly **154** in-window
`STAC search complete` events with `source: sentinel2` — one per parcel, none
missing, none duplicated. (Two further such events sit in the stream at
19:16Z; they are `fly logs`' start-up backfill from the *first* sweep, not
this one, and are excluded from every count here.)

**Coverage caveat, stated because it is a real limit.** The worker was
streamed. The API and Titiler were read only from their 100-line `--no-tail`
buffers (§10). The API buffer spans 18:59:40 → 22:33:49 and so covers the
window; Titiler's newest line predates the window by nearly 21 hours, which
is itself the finding.

---

## 2. Sweep hygiene — **A7 confirmed on its falsifiers; its observability expectation unmet**

| Quantity | Value | Source |
|---|---|---|
| Parcels reached | **154 of 154** | script stdout, DB |
| `queued` lines printed | 154 | script stdout |
| `skipped` | **0** | script stdout |
| `unreached:` lines | **0** | script stderr |
| Tracebacks from the script | **0** | script stderr |
| Requests created | 154, on 154 distinct parcels | DB |
| Terminal status | **154 `complete`, 0 `failed`** | DB |

Final line: `Done — queued 154 timeline request(s), skipped 0.`

**Exit code: not captured, inferred 0.** The invocation ran under `nohup` and
its exit status was not collected. Zero is inferred from the output — the
`Done —` line printed, no `unreached:` line and no traceback followed, and
the only `sys.exit(1)` reachable past that point is the `if unreached:`
branch. That inference is sound but it is not a measurement, and A7 names the
exit code explicitly. **This is a gap in the session's method, not in the
script**, and it is recorded rather than papered over.

### Admission waits — the first production exercise of `wait_for_admission_slot`

| Quantity | Value | Source |
|---|---|---|
| `Admission refused` warnings | **112** | script stderr |
| Inter-arrival gaps ≥ 1 s (i.e. waits) | **112** | DB `created_at` |
| Sub-second gaps (slot already free) | 41 | DB `created_at` |
| Total time waiting | **1,994.9 s** | DB `created_at` |
| Enqueue span | 2,007.2 s | DB `created_at` |
| **Share of enqueue wall time spent waiting** | **99.4 %** | derived |
| Mean wait | 17.8 s | derived |
| Median wait | 15.5 s | derived |
| Longest single wait | **50.7 s** | derived |

A7 predicted the sweep "should spend most of its wall time waiting". It spent
99.4 % of it waiting, and the refusal count and the wait count agree exactly
at 112 — one refusal, one wait, no wait that failed to open a slot and no
refusal that was not waited out. `wait_for_admission_slot` did in production
precisely what `d6b21b3` was written to make it do.

**A7's observability clause is falsified, and the reason is a defect worth
naming.** A7 predicted "the log should carry repeated `Waiting for an
admission slot` at `depth=30, cap=30`". It carries **none**.
`configure_logging()` is called only in `app/main.py:24` and
`app/tasks/celery_app.py:70`; no script calls it. So a script's root logger
has no handler, Python's last-resort handler takes over, and that handler
emits **WARNING and above only, to stderr, as a bare message with no
structured fields and no timestamp**. `Admission refused` (a warning) came
through stripped to two words; `Waiting for an admission slot` (INFO) was
discarded entirely. Every wait number in the table above had to be
reconstructed from DB timestamps because the log the fix was instrumented
with does not reach the operator. Filed as anomaly §11.1.

---

## 3. S2 conservation — **A1 confirmed on both falsifiable clauses**

A1's falsification conditions are "any parcel above 12, or any parcel holding
two rows in one calendar year". Neither occurred.

| Measure | These 154 | Source |
|---|---|---|
| Parcels **above** 12 | **0** | DB |
| Parcels holding two rows in one calendar year | **0** | DB |
| Parcels at exactly 12 | **145 of 154** | DB |
| Parcels at 11 | 9 | DB |
| min / median / max | **11 / 12 / 12** | DB |
| Total S2 rows | **1,839** | DB |

Fleet-wide after the sweep: **2,199 S2 rows across 184 parcels; 175 at
exactly 12; zero duplicate calendar years anywhere.** A1's point estimate was
2,208 (184 × 12). The 9-row shortfall is exactly the 9 parcels at 11.

### The nine at 11, and why — from capture

All nine are missing **2015** and only 2015. All nine held **no 2015 row
before the sweep either**, so nothing was deleted to produce this; the year
was already absent and stayed absent.

The capture says why it stayed absent: there were **zero** `STAC year chunk
failed after retries; skipping` events in the entire window, and the nine
parcels' S2 searches are logged as `selected_groups: 11, selected_items: 11`
against `raw_count` values in the normal range. Planetary Computer returned
no 2015 scene for these footprints; the pipeline did not fail to ask.

| Parcel | Location | Lat |
|---|---|---|
| `e4a9bed5` | Citrus Heights, Sacramento Co., CA | 38.69 |
| `fa12be75` | North San Juan, Nevada Co., CA | 39.37 |
| `1f0c42aa` | Elberta, Benzie Co., MI | 44.63 |
| `eab6adf5` | Durham, Washington Co., OR | 45.40 |
| `ad00ac68` | SE 41st Ave, Multnomah Co., OR | 45.48 |
| `7fb423de` | SE Franklin, Multnomah Co., OR | 45.50 |
| `39286f1d` | NE 23rd Ave, Multnomah Co., OR | 45.56 |
| `34efa7ae` | The Dalles, Wasco Co., OR | 45.60 |
| `177681ef` | Chelan Co., WA | 47.48 |

Eight of nine are Pacific Northwest or Northern California; the ninth is
Michigan lakeshore. All are northern-tier (38.7 – 47.5° N). Sentinel-2A
launched 2015-06-23 and its 2015 acquisition plan was not global, so a
northern-tier western-US footprint plausibly has no 2015 scene at all. That
reading is consistent with everything measured here and is **not** established
by it — no 2015 archive query was run against PC to confirm the absence is
upstream rather than in the search parameters. Recorded as the leading
explanation, unverified.

### A5 — the deficit measurement: **soft half confirmed, named population falsified**

A5 predicted "most land at 12, and the below-12 population — if any — is
`bd70afa6` and the coastal / boundary-adjacent parcels P6 named." Most did
land at 12 — 145 of 154, and A1's `12 − actual` deficit is zero on all of
them. The naming is wrong in both directions: **`bd70afa6` is not in the
below-12 population** — it went 5 → 12 and is now at the fleet norm (§5) —
and the nine that are below 12 are not the coastal/boundary set P6 named but
a northern-tier cluster, only one of which (`1f0c42aa`, Lake Michigan shore)
is coastal in any sense. The deficit that remains fleet-wide is **9 rows,
all of them the year 2015 on those nine parcels.**

---

## 4. Deletion wave, measured — **A2 confirmed on both bands**

| Quantity | Predicted | Band | Observed | Verdict |
|---|---|---|---|---|
| S2 rows deleted | ~1,788 | 1,700 – 1,900 | **1,818** | **confirmed** |
| S2 rows added | ~31 | 10 – 80 | **52** | **confirmed** |
| S2 rows after, these 154 | 1,848 | exact | **1,839** | −9 |

The identity holds exactly: `3,605 − 1,818 + 52 = 1,839`. The 9-row miss on
the "exact" line is the nine parcels at 11 from §3, and A2's exactness was
conditional on A1 ("1,848, exact, if A1 holds") — A1 held on its falsifiable
clauses but landed nine short of its point estimate, and A2 inherits exactly
that.

A2's methodological argument is vindicated. The brief's rate-based figure was
~2,170; the identity gave ~1,788; the measurement is **1,818**. The identity
was right and the rate was not.

### Deletions split by year

| | Rows |
|---|---|
| Closed years (≤ 2025) | **1,589** |
| Open year (2026) | 229 |
| **Total** | **1,818** |

### Additions split by cause

| Cause | Rows |
|---|---|
| Open-year re-pick (2026, a 2026 row already existed) | **42** |
| First-fetch backfill on `bd70afa6` (2015–2023, one per year, no prior row) | **9** |
| Genuine closed-year selection change | **1** |
| **Total** | **52** |

**Zero** of the 42 open-year additions landed on a parcel that had no 2026
row — every one is a re-pick, i.e. recency, not new coverage. The single
selection-changing addition is `f54492d9`, 2024: it took **2024-11-04 at
0.0078 %** where the year previously held three rows whose best was
2024-09-30 at 0.0171 %. That is the selector doing what it is meant to do —
one row per year, minimised on cloud.

---

## 5. Collateral — **A3 confirmed; A4 confirmed on topo, falsified in letter on NAIP**

Fleet-wide source totals, before → after:

| Source | Before | After | Deleted | Added |
|---|---|---|---|---|
| sentinel2 | 3,965 | 2,199 | 1,818 | 52 |
| landsat | 7,903 | **7,912** | **9** | 18 |
| naip | 1,267 | **1,273** | **0** | 6 |
| usgs_topo | 1,013 | **1,163** | **0** | 150 |

Total rows 14,148 → 12,547, a net −1,601, which reconciles: −1,766 + 9 + 6 +
150.

### A3 — Landsat: conserved, open-year swaps only. **Confirmed.**

**All 154 parcels hold exactly 43 Landsat rows afterwards** — min, median and
max are all 43. **Zero deletions in any closed year.** All 9 deletions are
one-for-one replacements inside 2026:

| Parcel | Deleted | Cloud % | Added | Cloud % | Cloud |
|---|---|---|---|---|---|
| `1cc54096` | 2026-01-10 `LC09_L2SP_040037_20260110_02_T1` | 0.06 | 2026-04-08 `LC08_L2SP_040037_20260408_02_T1` | 0.27 | worse |
| `24ec8466` | 2026-03-24 `LC08_L2SP_015042_20260324_02_T1` | 0.10 | 2026-04-25 `LC08_L2SP_015041_20260425_02_T1` | 5.05 | worse |
| `2b398698` | 2026-07-08 `LC08_L2SP_037037_20260708_02_T1` | 0.00 | 2026-08-17 `LC09_L2SP_037037_20260817_02_T1` | 0.00 | equal |
| `5b4c9b60` | 2026-05-14 `LC08_L2SP_036033_20260514_02_T1` | 0.29 | 2026-07-02 `LC09_L2SP_035033_20260702_02_T1` | 1.20 | worse |
| `67624825` | 2026-01-03 `LC08_L2SP_015043_20260103_02_T1` | 0.62 | 2026-02-12 `LC09_L2SP_015043_20260212_02_T1` | 1.04 | worse |
| `6dc460b8` | 2026-05-14 `LC08_L2SP_036033_20260514_02_T1` | 0.29 | 2026-07-02 `LC09_L2SP_035033_20260702_02_T1` | 1.20 | worse |
| `b7da4a3a` | 2026-05-14 `LC08_L2SP_036033_20260514_02_T1` | 0.29 | 2026-07-02 `LC09_L2SP_035033_20260702_02_T1` | 1.20 | worse |
| `dceca4b9` | 2026-01-10 `LC09_L2SP_040037_20260110_02_T1` | 0.06 | 2026-04-08 `LC08_L2SP_040037_20260408_02_T1` | 0.27 | worse |
| `fe065e2d` | 2026-04-08 `LC09_L2SP_016033_20260408_02_T1` | 0.00 | 2026-06-03 `LC08_L2SP_016033_20260603_02_T1` | 0.15 | worse |

**The first sweep's pattern holds and strengthens: 8 of 9 swaps trade down on
cloud, 1 is equal, none improve.** Across both sweeps that is 10 of 11
Landsat open-year swaps landing on a cloudier scene than the row they
replaced. Flagged in §11.4, not investigated. Three of the nine also cross to
an adjacent WRS-2 path (`015042→015041`, and `036033→035033` on three
parcels), so the replacement is not always the same footprint.

**`bd70afa6` — A3's named unknown — gained, decisively.** A3 predicted it
would not lose rows and declined to predict whether it would gain. It gained
on three sources at once:

| Source | Before | After |
|---|---|---|
| landsat | **34** | **43** |
| sentinel2 | **5** | **12** |
| naip | **0** | **6** |
| usgs_topo | 7 | 7 |

Its 9 new Landsat rows are 1984–1992, one per year, filling exactly the span
it was missing. Its 9 closed-year S2 additions are 2015–2023, one per year.
**Its missing years were transient search failures, not real absences** —
that is the informative outcome A3 said either answer would be, and it lands
on the recoverable side. It is now at the fleet norm on every source.

### A4 — topo: **confirmed, and stronger than predicted**

| | Value |
|---|---|
| Parcels holding zero topo before | **23** |
| Of those, parcels that gained rows | **23 of 23** |
| Rows added | **150** |
| Topo rows deleted, fleet-wide | **0** |
| Topo rows added to any parcel that already had some | **0** |

A4 predicted additions onto "some subset" of the 23 and allowed that a parcel
with no covering quad would gain nothing. Every one of the 23 gained, 3 to 9
rows each. Nothing was deleted and nothing landed outside the 23. The
prediction's falsification conditions — a topo row on a parcel that already
had one, or any topo deletion — did not occur.

### A4 — NAIP: **falsified in letter, upheld in substance**

A4 called NAIP "exactly 0 rows created and 0 deleted… the cleanest zero
available". Observed: **0 deleted, 6 created.**

**All 6 additions are on `bd70afa6`**, the single parcel of the 154 that held
zero NAIP rows — a fact A4's own inputs table records ("Parcels among them
holding zero `naip` rows: 1") and its NAIP line then did not account for.
The rows are Washington quads spanning 2011–2023. This is the identical shape
as the topo backfill: additions only, onto a source that was empty for that
parcel, with zero deletions anywhere.

So the letter of the zero is falsified by six rows on one parcel, and the
claim it was written to test — that the S2-year change leaked outside S2 — is
not supported. Nothing was deleted from NAIP or topo on any parcel; Landsat
is conserved parcel-by-parcel at 43 with swaps confined to the open year; the
only non-S2 movement fleet-wide is additive first-fetch backfill.

---

## 6. G2 — Rodanthe: **P5 / A6 confirmed exactly**

Rodanthe (`cf46ed63`) was swept. **34 S2 rows → 12.**

2015, predicted to keep only the 1.01 % October granule:

| | Capture | Cloud % | Item |
|---|---|---|---|
| before | 2015-07-26 | **25.037** | `S2A_MSIL2A_20150726T160236_R054_T18SVE_20210411T162645` |
| before | 2015-10-21 | 1.007 | `S2A_MSIL2A_20151021T155022_R011_T18SVE_20210412T184030` |
| **after** | **2015-10-21** | **1.007** | `S2A_MSIL2A_20151021T155022_R011_T18SVE_20210412T184030` |

The 25.04 % granule is gone; `S2A…20151021…` survives. **Exactly as
predicted, item id included.**

2017 collapsed from four rows (02-12, 05-03, 09-20, 12-14) to one:
**2017-02-12** at 0.038 %, the lowest-cloud member of the four. The featured
card that was wrong is now right.

## 7. G3 — Green Valley Ranch: **P5 / A6 confirmed exactly**

GVR (`2a4ca7b9`) was swept. **22 S2 rows → 12.** 2026 held four rows and now
holds **one**:

| | Capture | Cloud % |
|---|---|---|
| before | 2026-03-08 | 0.0516 |
| before | 2026-03-26 | 3.2867 |
| before | 2026-06-29 | 0.1039 |
| before | 2026-07-11 | 0.0002 |
| **after** | **2026-08-20** | **0.0002** |

Surviving item: `S2C_MSIL2A_20260820T173901_R098_T13TEE_20260820T223509`.
P5 named **2026-08-20 at 0.00 %** as the pick and called it an insert. Both
are correct — the date is exact, the cloud rounds to 0.00 %, and the row is
new. The first scorecard's "weak corroboration" from a neighbouring parcel in
the same Denver tile is now a direct confirmation.

---

## 8. Featured pages — **A6 confirmed on all six**

All six featured parcels were swept. **All six end at exactly 12 S2 cards,
from the 16, 16, 22, 23, 34 and 23 A6 named. No featured timeline shows a
duplicate calendar year.**

| Featured parcel | S2 cards before | after | Years whose pick changed |
|---|---|---|---|
| Stapleton / Central Park | 16 | **12** | 2015, 2025, 2026 |
| RiNo Art District | 16 | **12** | 2015, 2025, 2026 |
| Green Valley Ranch | 22 | **12** | 2015, 2016, 2019, 2021, 2025, 2026 |
| Navy Yard / Capitol Riverfront | 23 | **12** | 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2025, 2026 |
| Hudson Yards | 23 | **12** | 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2025, 2026 |
| Rodanthe, Outer Banks | 34 | **12** | all 12 |

Served item per year, after:

| Year | Stapleton | RiNo | GVR | Navy Yard | Hudson Yards | Rodanthe |
|---|---|---|---|---|---|---|
| 2015 | 12-16 | 12-16 | 12-16 | 11-16 | 09-24 | 10-21 |
| 2016 | 11-10 | 11-30 | 11-10 | 11-17 | 10-18 | 04-18 |
| 2017 | 11-30 | 12-20 | 11-30 | 10-18 | 10-18 | 02-12 |
| 2018 | 12-18 | 12-18 | 10-19 | 10-23 | 11-07 | 10-05 |
| 2019 | 11-18 | 12-03 | 11-18 | 10-28 | 11-02 | 09-25 |
| 2020 | 11-27 | 12-22 | 11-04 | 11-29 | 11-08 | 11-03 |
| 2021 | 12-02 | 12-27 | 10-05 | 11-09 | 10-19 | 12-23 |
| 2022 | 11-22 | 12-17 | 10-18 | 10-22 | 11-26 | 12-18 |
| 2023 | 12-17 | 12-17 | 11-17 | 11-16 | 11-16 | 11-08 |
| 2024 | 12-06 | 12-06 | 10-14 | 10-11 | 10-18 | 10-28 |
| 2025 | 11-13 | 12-28 | 11-13 | 10-16 | 10-06 | 10-20 |
| 2026 | 08-20 | 08-20 | 08-20 | 05-31 | 08-12 | 03-19 |

**The user-visible half of this change has now shipped to every featured
page.** The first scorecard's closing line on this section — "the
user-visible half of this change has not shipped to any featured page" — is
no longer true, and this is the batch that makes it false.

The table also makes §9's finding visible without any statistics: of the 66
closed-year featured cards, **64 are September–December** — the two
exceptions are both Rodanthe (2016-04-18, 2017-02-12).

---

## 9. Cap-truncation signature, fleet-wide — measurement for G8, no conclusion

Month of capture of surviving S2 rows, all **184** parcels, before (3,965
rows) and after (2,199 rows):

| Month | Before | After |
|---|---|---|
| Jan | 18 | 5 |
| Feb | 75 | 26 |
| Mar | 82 | 9 |
| Apr | 91 | 18 |
| May | 128 | 33 |
| Jun | 268 | 27 |
| Jul | 275 | 120 |
| Aug | 297 | 150 |
| Sep | 816 | 265 |
| Oct | 784 | 606 |
| Nov | 679 | 571 |
| Dec | 452 | 369 |

| Quarter | Before | After |
|---|---|---|
| Q1 | 175 (4.4 %) | 40 (1.8 %) |
| Q2 | 487 (12.3 %) | 78 (3.5 %) |
| Q3 | 1,388 (35.0 %) | 535 (24.3 %) |
| Q4 | **1,915 (48.3 %)** | **1,546 (70.3 %)** |

The first sweep measured 42.1 % → 70.0 % Q4 on 30 parcels. The fleet of 184
gives 48.3 % → **70.3 %**. The post-sweep Q4 share reproduces to within
0.3 points on a population five times larger and drawn from different
geography, which is a much stronger constraint on the mechanism than the
30-parcel figure was. **70 % of every S2 card Plotline now serves is an
October–December scene, and 1.8 % is a Q1 scene.** G8's unfixed 20-item cap
is the standing explanation. Measurement only; no conclusion drawn here.

---

## 10. Signing behaviour

| Signal | Count in window | Source |
|---|---|---|
| `SAS rate-limited; backoff exceeds wait budget, giving up` | **0** | worker stream |
| `Band signing failed after retries` | **0** | worker stream |
| `SAS container token minted` | **8** (4 sentinel2, 4 landsat) | worker stream |
| `STAC year chunk failed after retries; skipping` | **0** | worker stream |
| STAC 403s of any kind | **0** | worker stream |
| Titiler 5xx | **0** | `fly logs -a plotline-titiler --no-tail` |
| Request-path overlap | **none** | API + Titiler logs |

The eight SAS mints are spread across the window (21:46:43 → 22:18:10) —
four Sentinel-2, four Landsat — consistent with token expiry over a 45-minute
run and nothing more.

**Zero STAC 403s.** The first sweep saw two, on Landsat 2016 and 2017, and
lost no rows to them. This run saw none at all, and correspondingly zero
`STAC year chunk failed` events across 154 parcels × 4 sources. No rows were
lost to upstream refusal anywhere in this sweep.

**The request path was idle again, and the zeros mean the same limited
thing.** Titiler emitted no log lines during the window — its `--no-tail`
buffer's newest line is `01:47:01Z`, the *same* line the first scorecard
recorded nearly 21 hours earlier, meaning Titiler has emitted nothing at all
in between. The API's 14 in-window lines are this session's own SSH
connections and nothing else. So G4's pattern — batch-path signing load
starving the request path — again had no opportunity to appear. **These zeros
are evidence of an idle request path, not evidence that the pattern is
fixed**, and two sweeps have now failed to test it for the same reason.

---

## 11. Anomalies

Flagged, not investigated.

1. **Scripts run without logging configured, so the admission-wait
   instrumentation never reaches the operator.** `configure_logging()` is
   called only from `app/main.py:24` and `app/tasks/celery_app.py:70`.
   `revalidate_landsat.py` — and by inspection `requeue_parcels.py`,
   `seed.py` and the heal scripts — call neither, so their root logger has
   no handler and Python's last-resort handler emits WARNING-and-above only,
   to stderr, stripped of every structured field. The 112 `Admission refused`
   lines arrived as the bare two-word message; the 112 matching `Waiting for
   an admission slot` INFO lines, with the `depth`/`cap`/`wait_remaining_s`
   fields `d6b21b3` added precisely so an operator could watch a wait, were
   discarded. Every wait figure in §2 was reconstructed from DB timestamps
   instead. **The fix is instrumented; the instrument is not connected.**
2. **The script's exit code was not captured** (§2). A method gap in this
   session, not a defect in the script — but it means A7's exit-code clause
   is inferred rather than measured, and a future sweep should collect the
   status.
3. **Nine parcels sit at 11 S2 rows, all missing 2015, all northern-tier**
   (§3). No STAC failure explains it and none of them held a 2015 row before.
   The Sentinel-2A 2015 ramp-up reading is unverified — no archive query was
   run against PC to confirm the absence is upstream.
4. **Eight of nine Landsat open-year swaps traded down on cloud cover; one
   was equal; none improved** (§5). Across both sweeps: 10 of 11. Three of
   the nine also crossed to an adjacent WRS-2 path.
5. **150 topo rows and 6 NAIP rows appeared on parcels that held none of
   that source** (§5). As in the first sweep, whether those parcels ever had
   a successful fetch on that source before is not recoverable from the
   record.
6. **One `USGS topo fetch failed`** — `500` from `tnmaccess.nationalmap.gov`
   at 22:16:18Z, on a parcel that already held topo rows. It kept them; no
   rows were lost. **Two `Vintage tract lookup failed, using stored tract`**
   — `502` from the Census geocoder at 22:20:44Z and 22:21:03Z, both falling
   back to the stored tract as designed. Four `… row cap — results are
   truncated` warnings (Socrata ×4, TNM ×2, ArcGIS ×1) and one `STAC search
   hit its item cap` (NAIP, cap 50). All three task-level failures are the
   M4 shape again: a per-source failure inside a task that reported
   `complete`.
7. **`revalidate_landsat.py` still has no deployed-SHA gate** (§0). Third
   heal running, third time the operator carried the ordering by hand.

---

## Verdict

**The sweep completed, the fleet is consistent, and every prediction the
completion run could reach is confirmed — A1, A2, A3, A6 and A7 on their
falsifiable clauses, A4 on topo and falsified only by six backfill rows on
the one parcel its own inputs table flagged; A5's named population is wrong
in both directions; and the instrument `d6b21b3` added to watch its own fix
was never connected to a handler.**
