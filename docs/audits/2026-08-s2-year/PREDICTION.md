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
