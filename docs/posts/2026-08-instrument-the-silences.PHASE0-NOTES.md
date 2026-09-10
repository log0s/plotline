# Phase 0 verification and structural report — `2026-08-instrument-the-silences.md`

Written 2026-09-09, before and alongside the draft. Every beat in the prompt
was checked against its cited documents; verdicts below. Body is 2,209 words,
three H2s, no bullets, no numbered lists, no `[NEEDS]` markers, US spelling,
wrapped at 78 columns.

## Verdict table — all nine beats

| # | Beat | Verdict | Note |
|---|---|---|---|
| 1 | M4 diagnosed — four production occurrences, four hand-written heal scripts, Racebrook unknowable by design | **SUPPORTED-WITH-CORRECTION** | Both counts are in the record but they are two counts, not one. STATUS.md's M4 row enumerates four occurrences: 21 SAS 429s costing 20 Landsat years (2026-08-11); Ocean County NJ losing 8 Landsat years (2026-08-12); four `httpx.ReadTimeout`s costing a Maricopa parcel acs5 2021 + decennial 2020 (2026-08-12); and Racebrook (2026-08-12, from the geometry sweep). The "recurring chore" note naming `revalidate_landsat.py`, `requeue_empty_property.py`, `heal_tract_vintage_gaps.py` and `requeue_parcels.py` was written when the count stood at **three** and does not pair scripts to occurrences; `requeue_empty_property.py` is a property-path script and `heal_tract_vintage_gaps.py` was later deleted in `b7c9cbb`. The draft states both counts and explicitly says they are not paired. Racebrook's unknowability is verbatim in geometry HEAL-SCORECARD.md §7 and CENSUS_TRIAGE.md's closure of the phantom net-loss reading. |
| 2 | Design decision — per-year table vs JSONB, decided on what backfill reads and on the SQLite suite | **SUPPORTED** | INVESTIGATION.md §4 (what `maybe_refetch_for_backfill` inspects: seven items, none per-year; Landsat/Sentinel-2/NAIP have no trigger at all; the topo probe tests row absence only) and §9 (no query reads inside a JSON document anywhere in the repo; `census_snapshots.raw_data` is `json` not `jsonb`; SQLite has neither `jsonb_each` nor GIN). §9's own words: "a fact about the harness, not about Postgres." |
| 3 | Ledger built and swept — every attempted group records an outcome; 16,244 rows; predictions held; Racebrook answered with the wrong tract key | **SUPPORTED-WITH-CORRECTION** | HEAL-SCORECARD.md §3 (16,244 vs P2's 16,100 ± 300), §7 (zero `failed` fleet-wide), §11.1. Correction: Racebrook's five missing years read `absent`/`api_no_data` — the same outcome they would have carried anyway. What answered the question is the **tract in `detail`**: `09170157100` on every failing year, `09009157100` on every succeeding year but one. The draft says the vocabulary alone would not have settled it and that the detail column did. The single P2 deviation (topo split 1,154/183 + 2 `*` rows against ≈989/157 + 27) was flagged UNVERIFIED in PREDICTION §8 before the run; the draft keeps it. |
| 4 | Gate stop — a gate written for the opposite failure caught it | **SUPPORTED** | GATE-STOP.md §1: gate 2 read `alembic_version` `0010` and no `timeline_task_years`. One clause in the draft, cross-referencing the first post and nothing more. |
| 5 | Racebrook healed through the ledger; two fleet-wide census defects exposed | **SUPPORTED** | racebrook/REPORT.md §0 (three of five recovered, two are separate defects) and §10 (requeue scored: exit 0, 38s, `census_snapshots` 5 → 8, all three figures matching, 68 imagery rows byte-identical by id). census-decennial/REPORT.md §0/§1.2/§2: 1990 has no `dec/*` dataset at that vintage (discovery endpoint, 1,798 datasets, `dec/*` at 2000/2010/2020 only); 2000's split is 47 `ok` all not ending `00` against 80 `absent` all ending `00`, no exceptions. |
| 6 | M3 — backfill reads the ledger; three scored heals | **SUPPORTED** | m3/REPORT.md §6-§8 (`services/ledger.py`, `RETRY_POLICY` keyed on `(outcome, reason)` with `("absent", None)` deliberately missing so a new reason logs a policy gap). HEAL-1: one delete citing `suppressed`, eight surviving rows byte-identical by id, confirmed zero deviations. HEAL-2 Crawford MI: 16 Landsat `ok` + 6 NAIP `ok` + 11 NAIP `absent`/`no_scenes`; the 22/11 split is the post's arithmetic over the record's three counts. HEAL-3: 139 parcels/139 requests/exit 0; `decennial` 2000 48 → 111 = 63 rows, all on tracts ending `00`; 76 re-absent; `depth=25` on 236 of 236 admission lines. |
| 7 | Ops batch — retry alignment, scored honestly as "not exercised" | **SUPPORTED** | SWEEP-SCORECARD.md §0 (zero attempts hit a retried status on any of the three clients; corroborated by zero `failed` ledger rows) and §10 ("A quiet sweep is not confirmation, and this document declines to read it as one"). Compressed to five sentences per the prompt. |
| 8 | Z6 — failed vintage lookup substituted a plausible tract and recorded `ok`; fired once; stable tract by luck | **SUPPORTED** | z6-vintage-lookup/REPORT.md §1: one `httpx.ConnectError` at 18:55:14Z 2026-08-27, parcel `64a47cd8` (2 Broadway, NY), stored tract `36061000900`; all nine of its census rows carry that tract and a live re-lookup at every geocoder-mapped vintage returns it. "That is luck, not a property of the mechanism." Fixed in `4275908`. |
| 9 | Property — Z3/Z4/coverage: partial tasks, returned-vs-matched, Adams as a jurisdiction gap | **SUPPORTED** | property-outcomes/REPORT.md §1 (H4's all-failed rule; DC's 8 queries; "Adams passed this test only by arithmetic"), §3 (`rows_returned`/`rows_matched` existed only in a log line; `items_found` was the parcel's persisted lifetime total), §4 (`partial` at task and request level; `aggregate_request_status` counted only `failed`), §5 (Adams deny-list; 4,013 house numbers, 741–16610, zero in 9000–13600). SCORECARD.md §2 confirms the Adams task row on every field. |

Every commit hash cited in the post — `0814d7e`, `ef2d0a2`, `4ce1822`,
`e6afa9b`, `2c3f468`, `4275908` — was verified with `git merge-base
--is-ancestor` against HEAD.

## The Z6 vs `386f3e3` disambiguation

They are adjacent silences and different defects, and the post touches only
one of them.

**Z6** (`4275908`) is a *failed lookup that substituted*.
`lookup_tract_at_vintage` retried `httpx.TimeoutException` only;
`_VintageTracts.tract_for` caught every `GeocoderError` unconditionally and
fell back to the parcel's stored tract, which was then written into the census
row and recorded as `ok` in the ledger with no trace of the fallback.

**`386f3e3`** is a *successful re-resolution whose label did not move*. The
census upsert's `DO UPDATE SET` refreshed eleven demographic columns and
`raw_data` but not `tract_fips`, so a re-run resolving a different ancestor
tract would overwrite the numbers while keeping the old tract's label
(CENSUS_TRIAGE.md §4). No lookup failed; nothing was substituted.

**Call:** the thesis paragraph's "a tract lookup that failed transiently fell
back to the parcel's stored tract, wrote the census row under it, and recorded
the year `ok`" is worded for **Z6**, which is the only one of the two that is
a failed lookup. `386f3e3` is not mentioned in the post at all — the mislabel
is a provenance defect rather than a silence, and folding it in would have
blurred the distinction the beat exists to draw.

## Structural choices

**Opened on Racebrook**, as the prompt suggested. It earns the opening because
it is the only artifact that carries the whole arc on its own: unknowable at
beat 1, first answered at beat 3, healed at beat 5. Starting there lets the
thesis arrive as a generalization from something concrete rather than as an
assertion the rest of the post has to defend. It also gives the piece a return
— the Z6 paragraph closes on Racebrook as the standing counterexample to a
lucky fallback, which is a genuine relationship in the record, not a framing
device.

**The prediction/scorecard discipline is named once and not made the frame**,
per the prompt. It appears as verbs — predicted first and scored after, written
before deploy and never edited, flagged as unverifiable before the run — and
gets one explicit sentence in the closing paragraph. The silences are the spine.

**Beat 7 is five sentences**, the compression the prompt allowed. Its verdict
(`not exercised`) is kept verbatim because it is the sharpest evidence that the
scoring discipline is real: it is the one place the record declines to claim a
win it could have claimed.

**The gate stop is one clause**, per the ban on restating the first post's
mechanics. It is present as texture — the sweep that did not run — and nothing
about advisory locks or transaction semantics appears.

**Nothing was tidied.** The `not exercised` verdict, the topo-split deviation,
the admission reserve that has never been observed doing its job, and the eight
of 184 requests that ran with no log capture are all in or adjacent to the
text as written.

## Deviations from spec

1. **Deliverables are in YAML frontmatter at the top, not at the bottom.** The
   prompt asks for the bottom "matching the first post's convention for
   placement," but `2026-08-migration-lock.md` puts `status`,
   `candidate_titles`, `pull_quote` and `facts_to_verify` in frontmatter at the
   top and ends with a plain Sources paragraph. Following the letter would have
   made the two posts inconsistent, which is the stated purpose of the
   instruction; a YAML block at the end is also not frontmatter and would not
   parse. Same four keys, same order, same file position as the first post.
   Trivially movable if the literal placement was wanted.

2. **This report is a companion file rather than a comment block in the post.**
   The prompt offered either. `2026-08-migration-lock.EDIT-NOTES.md` is the
   precedent, and a 1,500-word HTML comment inside a 2,200-word post would
   dominate the file. No existing file was modified.

3. **Word count landed at 2,209**, inside the 1,500–2,200 band's upper edge
   after four trim passes. Two things were cut for budget that were otherwise
   worth keeping: the Denver/Brighton exclusions from Adams' deny-list (they
   are mailing cities for unincorporated pockets the layer *does* cover, which
   is why the list is derived rather than assumed), and the ACS5 2009 ride-along
   in `4ce1822`'s blast radius.

4. **Two numbers in the draft were corrected during writing.** An early draft
   said the reflex accumulated over "four years"; DEVELOPMENT.md dates the
   project at four and a half months, so it now reads "a run of small, locally
   sensible decisions." And the 184-parcel sweep count and the 186-parcel
   decennial re-measurement are both used, with the fleet's growth stated in
   the sentence rather than left as an apparent inconsistency.

## `facts_to_verify` in the post

Seven entries, covering the two SUPPORTED-WITH-CORRECTION beats (the
occurrence/script counts; Racebrook's `absent` outcome versus its diagnostic
`detail`) and five claims resting on a single document: the 63 no-data
responses, Crawford's 22/11 arithmetic, the admission reserve's `depth=25` and
never-observed reserve, the Adams house-number sample, and the bound on Z6's
one observed firing given the sweep's ~3% log-capture loss.

---

## Edit batch 2026-09-10

Owner read-through of `fab4047`. Verify-then-execute: item 1 was a record check
gating item 3. Only the post and this file changed; nothing under
`docs/audits/` was touched.

### Item 1 — VERIFY the ACS5 2023 tract key (confirmed)

The key is **`09170157100`**, the post-2022 planning-region key. Owner's
expectation held.

Citations, all in `../audits/2026-08-racebrook/REPORT.md`:

- §3 *Blast radius*, table "Its five surviving census snapshots" — `acs5 |
  2023 | 09170157100`, against `09009157100` for acs5 2012/2015/2018 and
  decennial 2010.
- §10 *Requeue and score, 2026-08-26 (addendum)*, the P3 ledger table —
  `census_acs5 | 2023 | ok | tract 09170157100`, the only `ok` row of the ten
  not carrying `09009157100`.
- §2.3, the live geocoder matrix — `ACS2023_Current` → `09170157100`,
  `ACS2021_Current` → `09009157100`; the boundary the data API draws.

Corroborated outside the racebrook directory by
`../audits/2026-08-m4-ledger/HEAL-SCORECARD.md` §11.1 ("ACS5 2023 succeeds
under `09170`") and by the row-level ledger export
`../audits/2026-08-y7-y8/logs/after-census_snapshots.csv:564`.

This makes the exception the confirming case rather than an anomaly: ACS5 2023
is the one vintage in the set actually published under the new geography, so
the new-geography key is the *right* key for it. **Item 3 was written.**

### Item 2 — DROP the upstream count (done)

`from four independent upstreams` removed; no upstream count returns to the
post in any form.

**Distinct upstreams across the four occurrences: two.** STATUS.md's M4 row
puts (1) — the 2026-08-11 burst of 21 SAS signing 429s, 20 Landsat years lost
— and (2) — 2026-08-12 00:45Z, Ocean County NJ, 8 Landsat years on
pre-throttle production — on the Planetary Computer signing path, and (3) —
four `httpx.ReadTimeout`s, Maricopa's acs5 2021 and decennial 2020 — and (4) —
Racebrook, empty responses for tract `09170157100` — on `api.census.gov`.

Note the row's own summary sentence reads "Observed in production three times,
from three independent upstreams", written when the count stood at three and
counting (1)-(3). Either reading falsifies four; the draft's number had no
support at any point in the row's history. The audit file is not edited — this
is recorded here and in `facts_to_verify`.

### Item 5 — the quoted prompts (paraphrase case)

Neither string is verbatim in the record. `grep -rn` over `docs/`, `prompts/`,
`scripts/` and `backend/` for "resilient to a bad year", "attempted year an
outcome", "outcome the database" and "write down what you expect" returns only
the post's own lines 210-211. `prompts/` (ORIGINAL, PHASE_2-5) and every
`PROMPT.md`/`SWEEP-PROMPT-*.md` under `docs/audits/` were searched directly;
the nearest hit is `prompts/PHASE_3_PROMPT.md:140` "## Census Fetch Service",
which is a section heading, not the request.

Both are therefore rephrased as paraphrase with the quotation marks removed —
"A prompt asking for a census fetch that is resilient to a bad year produces a
skip. A prompt asking that every attempted year carry an outcome the database
can distinguish, and that the expected result be written down before the run,
produces …". The contrast the passage rests on is unchanged; what is gone is
the claim that these are recorded prompt text.

### Diff summary

| item | change |
|---|---|
| 1 | verification only — no edit |
| 2 | line 48: `, from four independent upstreams` dropped |
| 3 | line 107: exception clause added, naming ACS5 2023 and `09170157100` as the only vintage published under the new geography |
| 4 | line 48: "four production occurrences of that shape" → "of the first of those silences — years dropped under a `complete` task" |
| 5 | lines 209-213: both prompts de-quoted and rephrased as request shapes |
| 6 | H1 → `Complete, with permanent gaps`; `candidate_titles` replaced with the five given, in order |
| 7 | `pull_quote` → "A system that can only report success will report success." |
| 8 | `facts_to_verify`: first entry amended with the two-upstream finding and the removal; new entries for the ACS5 2023 key and for the paraphrased prompts (7 → 9) |
| 9 | this section |

Body word count 2,209 → **2,245** (+36). Ceiling is soft and the item 3 clause
was authorised to cost words; no compensating trim was made. Reflowed
paragraphs at lines 48-56 and 109-119 to the file's ~76-column wrap — no words
changed by the reflow.

Final H1: **Complete, with permanent gaps**. Final pull quote: **A system that
can only report success will report success.**

### Deviation

Item 4's suggested wording was "the first of those silences" alone. The
occurrences include Landsat year loss (occurrences 1 and 2) while the first
silence as the preceding paragraph states it is the census `{}` skip
specifically, so the appositive "— years dropped under a `complete` task" was
added to name the shape the four actually share. One edit, both fours
disambiguated, no restructuring.
