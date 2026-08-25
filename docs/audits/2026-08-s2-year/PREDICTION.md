# Prediction — Sentinel-2 moves from quarter grouping to year grouping

**Written:** 2026-08-25, *before* the change is deployed and before any sweep.
**Code under prediction:** `6489018` (selector, validator period, and
`selection_scope`). HEAD before the change: `17dc9be`. Committed, not
deployed as of 2026-08-25.
**Scored by:** the next full re-queue sweep, run by Ryan.

Nothing in this file may be edited after the sweep runs. The observed result
goes in a scorecard next to it, with a verdict per line.

---

## Inputs this rests on

| input | value | source |
|---|---|---|
| Parcels in production | 184 | prompt / `../2026-08-m4-design/INVESTIGATION.md` §7 |
| S2 rows per parcel, production | 23.8 | prompt — **UNVERIFIED here**, no prod DB access this session |
| Implied production S2 rows | ~4,379 | 184 × 23.8, arithmetic on the above |
| Sample used for the per-parcel numbers | 5 featured parcels, read live via the public API 2026-08-25 | `REPORT.md` §2 |
| Sample S2 rows per parcel | 23.6 (118 / 5) | measured; within 1% of the fleet figure, so the sample is representative *on this statistic* |

The sample's per-parcel predictions below are replays of the **real production
search** (bbox = `point_to_bbox(lat, lng, 1500)`, `datetime` = the calendar
year, `max_items=20`, `query={"eo:cloud_cover": {"lt": 40}}`, then
`filter_items_containing_point`) against live Planetary Computer STAC on
2026-08-25, with the new selector applied. They are not extrapolations.

They omit one production step: `validate_sentinel_selection` HEAD-checks the
picked granule's `visual` asset and swaps in the next-best of the same year if
it 404s. The replay did not sign or HEAD anything. A failed HEAD changes
*which* scene a year holds, never how many. So the counts below are firm and
the individual `pick_date`s are the modal case, not a guarantee.

---

## P1 — Rows per parcel after the sweep

**Formula: one row per calendar year from 2015 through the current year —
`current_year − 2014`, i.e. 12 rows in 2026.**

Falsifiable form: after the sweep, `SELECT parcel_id, count(*) FROM
imagery_snapshots WHERE source='sentinel2' GROUP BY 1` returns **no parcel
above 12**, and no parcel holds two rows with the same
`extract(year FROM capture_date)`.

A parcel **below** 12 is not a falsification — it is the measurement this
change exists to enable (see P6). A parcel **above** 12 falsifies P1 and means
either a year's search failed (leaving its old rows untouched, which is
reconciliation working as designed) or the scope and the selector disagree.

## P2 — The five sampled parcels, exactly

Replayed 2026-08-25. `delete` = rows reconciliation removes; `add` = rows the
new pick inserts that no row currently carries; `final` = rows after.

| parcel | now | keep | add | delete | final |
|---|---|---|---|---|---|
| Rodanthe / Outer Banks | 34 | 12 | 0 | 22 | 12 |
| Green Valley Ranch | 22 | 11 | 1 | 11 | 12 |
| Stapleton / Central Park | 16 | 11 | 1 | 5 | 12 |
| Navy Yard / Capitol Riverfront | 23 | 12 | 0 | 11 | 12 |
| Hudson Yards | 23 | 11 | 1 | 12 | 12 |
| **total** | **118** | **57** | **3** | **61** | **60** |

All five reach exactly 12: every year 2015–2026 returned at least one scene
containing the point on every one of them.

All three additions are **2026** — the open year, where scenes have landed
since each parcel was last swept. No addition falls in a closed year on any
sampled parcel.

## P3 — Fleet-wide churn

Point estimates, with the band that would still count as confirmed:

| quantity | point estimate | confirmed if within |
|---|---|---|
| S2 rows deleted | **~2,170** | 1,900 – 2,400 |
| S2 rows added | **~110** | 0 – 200 |
| S2 rows after the sweep | **~2,210** (184 × 12) | 2,050 – 2,300 |

Arithmetic: `deletions ≈ 184 × (23.8 − 12) = 2,171`; `additions ≈ 184 × 0.6`,
the sampled rate of 3 additions across 5 parcels.

The additions band is deliberately wide where the deletions band is not.
Deletions follow from the row counts, which are known. Additions depend on how
long ago each parcel was last swept, which is not — a parcel swept last week
gains nothing in 2026, one swept in March gains one.

**This is the single most likely line to be falsified**, and the reason is
stated in advance: 23.8 is the fleet mean, and the fleet contains parcels
whose S2 task failed or partially failed. Those hold fewer than 23.8 rows and
delete fewer. If deletions come in **under** 1,900, the first thing to check
is not this prediction but how many parcels have fewer than 12 S2 years
available — i.e. P6.

## P4 — Landsat, NAIP and topo churn is exactly zero

**Falsifiable claim: the sweep deletes 0 and adds 0 rows for `source` in
(`landsat`, `naip`, `usgs_topo`) beyond what an unchanged-code sweep would do
— which for a re-run over an already-swept parcel is 0.**

The basis: this change touches three sites, all three S2-only — the
`sentinel2` entry's `selection_scope` in `_SOURCES`, `select_sentinel_items`,
and the `period` lambda in `validate_sentinel_selection`. `SELECTION_SCOPES`
keeps its `"quarter"` entry, so no other source's bucket function moved.
Landsat's `"year"`, NAIP's `"year"` and topo's hardcoded `"decade"` are
byte-identical to `17dc9be`.

Any non-zero Landsat/NAIP/topo churn falsifies this and means the change
leaked outside S2 — the most serious outcome available here, and worth
stopping the sweep for.

## P5 — The two named defects

**G2 (Rodanthe `sentinel2` 2015, the 25.04% non-covering granule).**
Predicted **resolved by deletion, not by re-selection**. Under year grouping
2015 is one group holding both the 25.04% granule (2015-07-26) and its 1.01%
covering sibling (2015-10-21). Lowest cloud wins, so the sibling is selected —
it is already a row, so it is kept, not re-inserted — and 2015-07-26 falls in
a selected group without being in `keep`, so reconciliation deletes it.
After the sweep, Rodanthe holds exactly one 2015 row, dated **2015-10-21**,
and the featured card that was wrong is right. Falsified if any 2015 row
remains besides that one, or if the card still shows July 2015.

**G3 (Green Valley Ranch, duplicate 2026-Q1 rows).** Predicted **resolved**.
GVR's four 2026 rows — 2026-03-08, 2026-03-26 (the duplicate pair),
2026-06-29, 2026-07-11 — all fall in one group. The replay picks
**2026-08-20** (0.00% cloud), which is not currently a row, so 2026 resolves
to one insert and four deletes. Falsified if GVR holds more than one 2026 row
after the sweep.

Note the shape of the fix: G3 was unreachable before because 2026-Q1 was
never *in* a selection, and reconciliation deliberately leaves absent groups
alone. Year grouping does not change that rule — it makes the group reachable.

**Second-order prediction, offered because it is the mechanism and not the
symptom:** across the whole fleet the sweep leaves **zero** parcels holding
two S2 rows in one calendar year. G3 was described as "the only duplicate
group ever produced"; if others exist, this sweep clears them too, and the
count of rows deleted in excess of P3's band is where they will show up.

## P6 — What O6 can measure afterwards, and what it will find

O6 (S2 health unassessable — no expected count) is not fixed by this change;
it is made *answerable*. The expected count becomes `current_year − 2014` per
parcel, and the deficit `12 − actual` becomes a per-parcel damage figure.

**Prediction for that measurement, once run: most parcels sit at exactly 12,
and the parcels below 12 are concentrated in the same coastal / boundary-
adjacent population that failed at Rodanthe and Hudson Yards, plus any parcel
whose S2 task failed during a sweep.** Deliberately soft — it is a shape, not
a number, and it is written here so the eventual measurement can contradict
it.

**One year is not like the others and should not be scored as damage:**
Sentinel-2A returned no usable scene over any sampled parcel before
**2015-07-26** (Rodanthe; Denver's first is 2015-08-11). 2015 Q1 and Q2 are
pre-mission everywhere — the only genuinely scene-absent quarters in the whole
gate measurement. A 2015 row will exist, drawn from H2, so the formula holds;
but a parcel missing *only* 2015 is a boundary case, not a gap.

## P7 — Capture dates skew late in the year, and that is not a regression

`capture_date` is preserved unchanged on every row, so the card still shows
the month. Predicted: **the selected month clusters hard in Q4** — of the 60
predicted final rows on the sample, the replay puts 51 in Q4, 5 in Q3, and 4
in H1.

The skew **sharpens** rather than appears: the same five parcels' 118 current
rows are already 95/118 Q3–Q4, and collapsing four quarters to one
lowest-cloud pick concentrates that further, because the cap makes December
the densest end of every candidate pool.

The cause is the 20-item-per-year cap, not the year key: PC returns
newest-first, so a saturated parcel-year's pool *starts* at late December and
runs backwards to roughly September or October. Year grouping neither causes
this nor cures it. Recorded so that "the S2 cards are all autumn" is read
afterwards as a known pre-existing property with a named cause — and so that
a later fix to the cap (see the report's follow-up register) has a before
number to be scored against.

Falsified if the post-sweep month distribution is *not* at least as
Q4-weighted as the pre-sweep one.

---

# ADDENDUM 2026-08-25 — the completion sweep, calibrated from the 30

Written after `HEAL-SCORECARD.md` and after `d6b21b3`, and **before the
completion sweep runs**. The original prediction above is untouched; this
is a second, separately scorable prediction for the 154 parcels the
2026-08-25 sweep never reached. Nothing here may be edited after that
sweep runs.

The 30 that ran are not a re-test — P1 was confirmed exactly on them. What
follows is calibrated *from* those 30, against the measured pre-sweep state
of the remaining 154, read from the after-state snapshot at
**2026-08-25T19:17:30Z**.

## Inputs, all DB-measured

| input | value |
|---|---|
| Parcels not reached | **154** |
| S2 rows they currently hold | **3,605** (mean 23.4; min 5, median 23, max 39) |
| Parcels among them holding a duplicate calendar year | **154 of 154** |
| Landsat rows they hold | 6,613 — **153 at exactly 43**, one (`bd70afa6`) at 34 |
| Parcels among them holding **zero** `usgs_topo` rows | **23** |
| Parcels among them holding **zero** `naip` rows | 1 |
| Measured on the 30 | 423 S2 deletions, 6 additions, 100 % landing at 12 |

## A1 — Every parcel lands at 12, and the fleet ends at 2,208

`current_year − 2014` = 12, one row per calendar year 2015–2026, zero
duplicate years, on all 154. Fleet-wide afterwards: **184 × 12 = 2,208**
S2 rows.

Falsified by any parcel above 12, or any parcel holding two rows in one
calendar year. A parcel **below** 12 is the P6 measurement, not a
falsification — see A5.

## A2 — S2 churn: ~1,788 deleted, ~31 added

| quantity | point estimate | confirmed if within |
|---|---|---|
| S2 rows deleted | **~1,788** | 1,700 – 1,900 |
| S2 rows added | **~31** | 10 – 80 |
| S2 rows after, these 154 | **1,848** (exact, if A1 holds) | 1,848 |

Arithmetic, and it is an identity rather than a rate: `deletions =
3,605 − 1,848 + additions`. Additions are taken at the measured rate from
the 30 — 6/30 = 0.2 per parcel — giving `154 × 0.2 ≈ 31` and deletions
`1,757 + 31 = 1,788`.

**Deviation from the brief, stated because it changes the number.** The
prompt calibrated deletions as `154 × (423/30) ≈ 2,170`. That applies the
swept 30's deletion *rate* to a population with a different starting
count: those 30 averaged **25.9** S2 rows each, the remaining 154 average
**23.4**. The rate is not transferable; the identity is. ~2,170 was P3's
estimate for all **184** parcels, and 423 of it has already been spent —
`2,174 − 423 ≈ 1,751` reaches the same place from the other direction.

The additions band is wide for the same reason P3's was: additions depend
on how long ago each parcel was last swept, and the 154 were last touched
across a range of dates.

## A3 — Landsat conserved at 43, open-year swaps only

153 of the 154 hold exactly 43 Landsat rows and are predicted to hold
exactly 43 afterwards. Any deletion in a **closed** year (≤ 2025) falsifies
this and means the change leaked outside S2 — the serious outcome P4 was
written to catch. One-for-one replacements inside 2026 are expected and do
not falsify it: two occurred on the 30, both trading down on cloud cover.

**`bd70afa6` is the exception and the one to watch.** It holds 34 Landsat
rows and 5 S2 rows — the fleet minimum on both. It is predicted **not to
lose** rows. Whether it *gains* is genuinely unknown and either outcome is
informative: if its missing years were transient search failures they will
fill, and if they are real absences they will not. No prediction is made
either way, deliberately.

## A4 — NAIP zero, topo backfill confined to the 23

**NAIP: exactly 0 rows created and 0 deleted.** This was confirmed exactly
on the 30 and is the cleanest zero available.

**Topo: additions only, and only onto parcels that hold none.** Exactly
**23** of the 154 currently hold zero `usgs_topo` rows; the sweep is
predicted to add rows to some subset of those 23 and to **no parcel
outside them**, and to delete zero topo rows fleet-wide. On the 30, all 31
topo additions landed on the 4 parcels that held zero.

Falsified by a topo row appearing on any parcel that already had one, or
by any topo deletion. If fewer than 23 gain rows that is not a
falsification — a parcel with no covering quad gains nothing.

## A5 — What the deficit measurement will find

P6 is answerable per parcel as `12 − actual`. On the 30 the deficit was
**zero everywhere**. The prediction for the 154, deliberately soft: **most
land at 12, and the below-12 population — if any — is `bd70afa6` and the
coastal / boundary-adjacent parcels P6 named.** Recorded so the eventual
measurement can contradict it.

## A6 — Carried over unchanged, now scorable

These are the original P5 and the featured-page expectations, restated
without amendment because the completion sweep is the first run that
reaches the parcels they name:

- **G2 / Rodanthe (`cf46ed63`).** Exactly one 2015 S2 row afterwards,
  dated **2015-10-21** (1.01 % cloud); the 25.04 % `S2A…20150726…` granule
  deleted. Its 34 rows collapse to 12; 2017's four rows collapse to one.
  Falsified if any other 2015 row survives or the card still shows July
  2015.
- **G3 / Green Valley Ranch (`2a4ca7b9`).** Exactly one 2026 row, P5's
  pick being **2026-08-20** at 0.00 % — an insert. Its four 2026 rows
  (03-08, 03-26, 06-29, 07-11) all go. Falsified by more than one 2026 row
  afterwards.
- **All six featured parcels** end at exactly 12 S2 cards, from 16, 16,
  22, 23, 34 and 23 today, with no duplicate calendar year on any of them.
  This is the user-visible half of the change and none of it has shipped.

## A7 — The sweep completes, and says so

New, because it is what `d6b21b3` exists to make true: **the run reaches
all 154 parcels and exits 0.** `AdmissionRefused` is expected — the cap is
30, the worker drains ~2 parcels per 27 s, so the sweep should spend most
of its wall time waiting — and the log should carry repeated `Waiting for
an admission slot` at `depth=30, cap=30`. At the 2026-08-25 drain rate,
154 parcels is roughly 35 minutes, inside the 60-minute default.

Falsified by a non-zero exit, by any `unreached:` line, or by a
traceback. If the wait budget is exhausted, the run is expected to name
every parcel it did not reach and exit 1 — which is a *pass* for the
script and a deferral for the sweep, and the two should not be scored as
one thing.
