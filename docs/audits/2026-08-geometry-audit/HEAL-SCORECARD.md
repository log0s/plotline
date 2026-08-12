# Geometry Heal — Post-Sweep Scorecard

Observation-only record of the `revalidate` sweep run on **2026-08-12,
03:38:30Z → 03:52:16.9Z** (826 s), scored against the prediction written in
`../2026-08-second-audit/STATUS.md` before the heal ran. Nothing here was
acted on: the sweep was watched, not driven. All production access was log
pulls and `SELECT`s.

Deduped log capture: `/tmp/sweep-capture.log` (1,131 events).

---

## 0. Capture coverage, and what it costs

`fly logs --no-tail` returns at most 100 lines, which on this worker is about
44 s of output — so the prescribed 60 s poll could not have been gap-free. The
capture was switched to a continuous `fly logs` stream (primary) with the polls
kept as a safety net. That was started mid-sweep, so the first third is
poll-sampled only.

| Window | Coverage |
|---|---|
| 03:38:30 → 03:39:25 | **gap** (55 s) |
| 03:39:27 → 03:40:26 | **gap** (59 s) |
| 03:40:33 → 03:44:25 | **gap** (233 s) |
| 03:45:09 → 03:46:01 | **gap** (52 s) |
| 03:47:50 → end | continuous stream |

**≈6.6 min of the 13.8 min sweep has no log coverage — roughly half.** Every
log-derived count below is therefore a *floor*, and the DB carries the load.
Where the two can be reconciled they are, and the reconciliation is stated.

---

## 1. Scorecard

| Category | Predicted | Observed | Source | Verdict |
|---|---|---|---|---|
| Geometry one-for-one replacements | 33 (29 landsat + 4 S2), *on the local dataset* | Not separable in aggregate on prod; **13 of 15 named featured cards replaced at exactly the named years** | DB | see §2 |
| One-for-one, same year group | yes | **yes — landsat exactly conserved**: 2,451 rows = 57 × 43, every parcel exactly 43, zero duplicate year groups | DB | **confirmed** |
| No timeline loses a card | none | **none**; zero parcels below the 43-year CONUS span | DB | **confirmed** |
| Total churn exceeds 33 | yes | 119 landsat + 55 S2 + 5 topo rows written | DB | **confirmed** |
| NAIP gate removes 2023 from both 350 5th Ave parcels | 2 cards | **0** — no NAIP row was created or deleted; the 2023 card still serves `nj_m_4007309_sw` | DB + log | **falsified** |
| Hudson Yards keeps its 2023 card | keeps | **keeps** — its row carries 2 additional tiles (3-tile mosaic), as the audit said | DB | **confirmed** |
| Suppression log lines fire | 2 | **0** captured; 0 rows removed | log + DB | **falsified** |
| Card-count decreases outside suppressions | 0 | **0** | DB | **confirmed** |
| Duplicate-year groups | 0 | **0** landsat/NAIP; **1** S2 (pre-existing, see §4) | DB | confirmed w/ deviation |
| Parcels below expected Landsat span | 0 | **0** (all 57 at 43) | DB | **confirmed** |
| Sweep hygiene | — | 57/57 complete, **0 failed**, 0 skipped as in-flight; 303 tasks complete + 39 `property` skipped (no adapter for county) | DB | clean |

### Replacement volume

| Source | Rows added (DB, exact) | Parcels | Deletions |
|---|---|---|---|
| landsat | 119 | 34 | **119** — derived exactly from conservation (57 × 43 before and after, no dupes) |
| sentinel2 | 55 | 20 | **≥29** (log-observed, ~half coverage); net not derivable — S2 count is not conserved by design |
| usgs_topo | 5 | 1 | — |
| naip | **0** | 0 | 0 |

Log-observed reconciliation events in the covered windows: 22 events / 67
deletions (landsat 14 events / 38; S2 8 events / 29). Consistent with the DB
totals once the ~50 % coverage loss is accounted for — **no log/DB
disagreement.**

### Decomposing the additions

| Source | 2026 capture year (recency, not fix-attributable) | pre-2026 (selection-changing) |
|---|---|---|
| landsat | 15 rows / 15 parcels | **104 rows / 27 parcels** |
| sentinel2 | 15 rows / 15 parcels | **40 rows / 7 parcels** |

The S2 pre-2026 additions concentrate in seven parcels — 13, 10, 8, 6, 3, 1, 1
— which is the relaxed validation fallback (e7d4c6d) doing bulk work, not
geometry.

---

## 2. Geometry attribution — the featured parcels decide it

The aggregate cannot be split into geometry-class versus fallback-upgrade
churn on production, because the audit measured a **different database** (see
§5). On the featured parcels, where the audit named exact years, the split is
unambiguous:

| Featured location | Audit-named years | Replaced by sweep | Hit | Extra |
|---|---|---|---|---|
| RiNo Art District | landsat 1987, 1988, 2007, 2008, 2010, 2011 | same six + 2026 | **6/6** | 2026 |
| Hudson Yards | landsat 2013, 2016, 2017, 2019, 2020 | same five + 2026 | **5/5** | 2026 |
| Green Valley Ranch | landsat 2006, 2012 | same two + 2026 | **2/2** | 2026 |
| Rodanthe, Outer Banks | sentinel2 2015, 2017 | 2017 only | **1/2** | — |
| Navy Yard / Capitol Riverfront | — (clean) | **nothing** | — | — |
| Stapleton / Central Park | — (clean) | 2026 only | — | 2026 |

**The only extra year on any featured parcel is 2026** — the current year,
whose best scene moves as new acquisitions land. And the two parcels the audit
called clean came back clean: Navy Yard was touched not at all. That is about
as clean a control as this kind of observation offers, and it is the strongest
evidence that the pre-2026 replacements are the fix acting, not churn.

### Featured before/after

| Parcel | Landsat before → after | Total rows after | Sweep-written |
|---|---|---|---|
| RiNo Art District | 43 → 43 | 73 | 7 |
| Hudson Yards | 43 → 43 | 84 | 7 |
| Green Valley Ranch | 43 → 43 | 79 | 3 |
| Rodanthe, Outer Banks | 43 → 43 | 86 | 3 |
| Navy Yard / Capitol Riverfront | 43 → 43 | 83 | 0 |
| Stapleton / Central Park | 43 → 43 | 73 | 2 |

Landsat "before" is derived, not remembered: the count is conserved and there
are no duplicate groups, so before = after = 43.

---

## 3. The NAIP suppression did not fire, and the reason is structural

Zero NAIP rows were created or deleted. `350 5th Ave` still serves
`nj_m_4007309_sw_18_030_20230820_20231019` for 2023 — the New Jersey quad the
audit condemned — with `created_at` still 2026-05-23.

The two safety rules compose into a hole. 14b59af drops an uncovered year from
`selected_groups`; `reconcile_source_snapshots` then sees that group as
*absent*, and its docstring is explicit that absent groups are never deleted,
because absence usually means a failed search rather than a retired scene.

**So the gate is prospective only.** It prevents a wrong year from being
written, but on every parcel that already has one — which is exactly the
population the audit identified — the wrong card survives. The predicted
"removes exactly one card from each of the two 350 5th Ave parcels" could not
have happened on a re-run, only on a first fetch.

Not investigated further, per the brief. Flagged for its own pass.

---

## 4. Anomaly categories

Each is reported, none is fixed.

1. **NAIP suppression is prospective-only** (§3). Two known wrong cards remain
   on production. Highest-value item here.
2. **Rodanthe sentinel2 2015 Q3 was not healed.** The row is still
   `S2A_MSIL2A_20150726T160236_R054_T18SVE_20210411T162645`, 25.04 % cloud,
   the granule Appendix A lists as non-covering. Its Q4 sibling (1.01 %) is a
   different quarter group, so the quarter-scoped selector never had to choose
   between them. 1 of the 15 featured cards remains wrong.
3. **One duplicate S2 quarter group.** Green Valley Ranch has two 2026-Q1 rows
   (2026-03-08 and 2026-03-26), created 2026-06-12 and 2026-06-17 — **before
   this sweep**, and not created by it. The sweep's selection did not include
   2026-Q1, so the absent-group rule left it alone. Pre-existing, and
   structurally not healable by re-running.
4. **Signing storm on the request path during and just after the sweep.**
   41 × `SAS rate-limited; backoff exceeds wait budget, giving up`, 17 ×
   `Band signing failed after retries`, and 115 Titiler 500s across 5
   snapshots (03:39–03:40 and 03:55). This is the O1 act-two mismatch running
   in the opposite direction: the batch path's signing load exhausts PC's
   limit while the request path's 2 s `SIGN_WAIT_REQUEST` budget gives up
   immediately. A user browsing during a sweep gets 500s.
5. **At least one Titiler 500 is an expired SAS token, not rate limiting.**
   The 03:34 failures carry `se=2026-08-12T00:00:52Z` in the URL — expired
   three hours earlier. Distinct cause, same symptom.
6. **An ArcGIS query hit its row cap.** DC property layer, cap 20,
   `upper(PROPERTY_ADDRESS) LIKE '1300 %4%'`, 03:48:33Z. This is the evidence
   the counties reconciliation item 13 was explicitly waiting for.

---

## 5. Loudly: the prediction and the sweep are about different databases

The audit's 33 pairs carry parcel ids (`c78a1019`, `5c27245c`, `d2a82e6b`, …)
that **do not exist in production**. FINDINGS.md says so in passing — "local
database (41 parcels)" — but the consequence was not carried into the
prediction: production has 57 parcels with entirely different UUIDs.

Two concrete distortions this introduces:

- The local set has **two** `350 5th Ave` parcels and a separate
  `4800 Telluride St` row duplicating Green Valley Ranch's failures.
  Production has one of each. Deduplicated and mapped by address, the 33 pairs
  correspond to **24** production rows, of which **2** (Erie CO) have no
  production parcel at all — so **22** was the realistic prod-side target, not
  33.
- Production contains parcels the audit never assessed, so some of the 104
  pre-2026 landsat replacements may be geometry-class failures that were never
  counted.

**"33" was never a prod-side prediction, and scoring it as one would be a
category error.** Appendix A's stac_item_ids could not be checked directly for
that reason; the year-level test in §2 is the substitute, and it is strong.

Separately, the brief that commissioned this scorecard predicted "two
suppressions: Hudson Yards 2023 NAIP and Jersey City 2011". Both halves are
wrong against the record: STATUS.md states Hudson Yards **keeps** its 2023 card
and calls the contrary expectation out by name, and "Jersey City" appears
nowhere in any audit document. The suppression pair was always the two
350 5th Ave parcels.

---

## 6. O5's damaged parcels — healed, but not by this sweep

Both are at the full 43-year span. Neither took a single row from this sweep:
they were healed by a `requeue_parcels.py` run at **03:32:22Z**, six minutes
earlier.

| Parcel | Address | Landsat now | Rows from this sweep | Healed by |
|---|---|---|---|---|
| `7397388e` | 3890 W 44th | 43 | 0 | runs at 23:00Z and 03:00Z |
| `e0cb3db9` | 141 rainbow drive brick | 43 | 0 | runs at 01:00Z and 03:00Z |

Worth stating plainly because the sweep would otherwise look like the cause.
The ordering the `--require-sha` gate exists to enforce did hold — the
throttle was deployed before either re-run, and neither re-rolled the dice.

---

## 7. Census ride-along, and M4

- **3 census rows gained across 2 parcels** during the sweep — the transient-gap
  opportunistic heals. Small, as expected.
- 161 ACS5 and 61 decennial saves fired against 63
  `Census API: no data for tract` responses, which are the silent
  `if data:` skips M4 describes — they increment nothing.
- **One parcel still shows census year gaps after its sweep run**:
  `Racebrook Road, Orange, Connecticut` (2f1b332e), holding 5 years —
  decennial 2010 and ACS5 2012, 2015, 2018, 2023 — against 7–9 for its peers.

That parcel is M4 occurrence data, and it demonstrates M4's actual sharpness
better than a timeout would: **nothing in the system can say whether those
years re-failed or were never available.** No failure was recorded, the task
ended `complete`, and the 404s look identical to genuine absence. Connecticut's
2022 county-to-planning-region change makes genuine absence plausible — which
is the point. M4's per-year persistence is what would tell the two apart.

---

## Verdict

**Confirmed with noted deviation on the geometry half; falsified on the NAIP
half.**

The geometry fix did what it was predicted to do and did it cleanly: one-for-one
within the year group, no card lost, no duplicate accreted, clean parcels left
untouched, and 13 of the 15 named featured cards replaced at exactly the named
years. The deviations are Rodanthe 2015 Q3 (quarter-scoping, unhealed) and the
fact that the count "33" was measured against a database the sweep never
touched.

The NAIP prediction is falsified outright, and usefully so: the gate is
prospective and the absent-group rule protects the very rows it was meant to
remove. That is a composition bug between two individually correct rules, and
it would not have been visible without running the heal and looking.
