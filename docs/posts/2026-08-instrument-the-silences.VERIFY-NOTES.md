# Independent verification — `2026-08-instrument-the-silences.md`

Written 2026-09-10 against HEAD `3d15825`. This session did not write the
post. Every verdict below was formed against the primary record: the
documents under `docs/audits/`, the migrations, the code at the cited commits
(`git show <hash>:<path>`), and git history. The drafting session's
`PHASE0-NOTES.md` was read only after every verdict was formed, and is
reconciled in §7. Nothing under `docs/audits/` was edited. No scripts were
run, and no database or production access was used.

Verdict vocabulary: **C** CONFIRMED · **CWN** CONFIRMED-WITH-NOTE ·
**X** CONTRADICTED · **U** UNVERIFIABLE.

---

## 1. `facts_to_verify` — nine entries

| # | Entry (short) | Verdict | Primary source, and the note |
|---|---|---|---|
| 1 | Four occurrences and four heal scripts are two counts; no script is paired to an occurrence | **CWN** | STATUS.md M4 row (line 114) enumerates occurrences (1)–(4). The scheduling note (STATUS.md ~1291-1296) reads "Three production instances from three independent upstreams", names the four scripts, and pairs none. `requeue_empty_property.py` is property-path per `m4-design/INVESTIGATION.md` §5 and `m4-ledger/REPORT.md` §7. **Note:** the entry's own rationale puts occurrence (2) on the SAS signing path. The record does not establish that: `ops-audit/FINDINGS.md` HIGH-2 and its log-shipping section say of (2) "I know *that* it happened … but have no idea *why* — 429 burst, validation failure, or something else." The post states no upstream count, so the body is unaffected. The entry was left unedited (§5). |
| 2 | Racebrook's missing years read `absent`/`api_no_data`; the tract in `detail` is what was diagnostic | **C** | `m4-ledger/HEAL-SCORECARD.md` §11.1, the ten-row table. Single source, and it is the ledger read itself. |
| 3 | ACS5 2023 is the one succeeding year asked under `09170157100` | **C** | `racebrook/REPORT.md` §3 ("Its five surviving census snapshots"), §10 P3 table, §2.3 (`ACS2023_Current` → `09170157100`), and §2.2's rule (ACS 5-year 2022+ uses planning-region codes). Corroborated by HEAL-SCORECARD §11.1. |
| 4 | The two prompt shapes are paraphrase | **CWN** | Grep of `docs/`, `prompts/`, `scripts/`, `backend/` for "resilient to a bad year", "resilient to", "carry an outcome the database", "outcome the database can distinguish": no hits outside `docs/posts/`. **Note:** the first shape has a recorded source closer than the drafter's `PHASE_3_PROMPT.md:140` heading. `prompts/PHASE_3_PROMPT.md:268` reads "If a specific year fails, log the error and continue with other years. Don't fail the whole task over one missing data point.", and `:260` reads "Handle 204/404 gracefully". That is the substance of "resilient to a bad year", and the post's paraphrase is fair to it. |
| 5 | The 63 no-data responses are fleet-wide, from the 2026-08-12 geometry sweep | **CWN** | `geometry-audit/HEAL-SCORECARD.md` §7: "161 ACS5 and 61 decennial saves fired against 63 `Census API: no data for tract` responses". **Notes:** (a) the count is log-derived. §0 of the same file puts ≈6.6 of the 13.8 sweep minutes outside log coverage and calls every log-derived count a floor. (b) "Fleet-wide" means 57 parcels: the sweep was 57/57 (§1), and `CENSUS_TRIAGE.md` confirms production held 57. (c) STATUS.md's M4 row cites this file's §6 for occurrence (4). The content is in §7 (§6 of this report). |
| 6 | Crawford 22/11 is the post's arithmetic over three record counts | **C** | `m3/HEAL-2-crawford.md` Phase 3a item 2: 16 Landsat `ok`, 6 NAIP `ok`, 11 NAIP `absent`/`no_scenes`. The same split was reproduced independently by `ops-batch/SWEEP-SCORECARD.md` §4. |
| 7 | `depth=25` on 236 of 236 lines, and no `origin='user'` request | **CWN** | `m3/HEAL-3-decennial-2000.md` §5.2 for both. **Note:** the second measurement, which STATUS.md's M3 row adds, is the ops-batch scoring sweep. It has its own primary source (`ops-batch/SWEEP-SCORECARD.md` §1: `cap=25 depth=25` on all 814 lines; §8: zero `origin=user` requests). So the "never observed" clause rests on two scorecards, not one. |
| 8 | Adams house-number sample: 4,013 numbers, 741–16610, zero in 9000–13600, four streets | **C** | `property-outcomes/REPORT.md` §5, source 3. The entry already carries the sample caveat that §11 item 3 of the same report states. |
| 9 | Z6's one instance is the only one in a capture that dropped ~3% | **C** | `z6-vintage-lookup/REPORT.md` §1; `ops-batch/SWEEP-SCORECARD.md` §0 and §9.2 (183 task-start lines against 189 requests). |

**Tally: 5 C, 4 CWN, 0 X, 0 U.**

---

## 2. Body claims

### 2a. Numeric claims

Numbers marked *(post)* are the post's own sums or illustrations. Their inputs
are confirmed from the record.

| # | Fragment | Number | Source | Verdict |
|---|---|---|---|---|
| B1 | "held five census years" | 5 | STATUS M4 (4); geometry HEAL-SCORECARD §7 | C |
| B2 | "where its neighbors held seven to nine" | 7–9 | same | C |
| B3 | "the sweep logged 63 `Census API: no data for tract` responses fleet-wide" | 63 | geometry HEAL-SCORECARD §7 | CWN: log-derived floor with ~half the sweep uncovered (§0); the fleet was 57 parcels |
| B4 | "planning regions for data tabulated from 2022" | 2022 | racebrook REPORT §2.2 | C |
| B5 | "There were four of them, in four different places" | 4 *(post)* | the post's enumeration; each item is recorded: FINDINGS H4, STATUS M4, the Adams row / property REPORT §1, Z6 REPORT | C |
| B6 | "'this parcel has no history' from 'this integration has been broken for a month'" | a month | DEVELOPMENT.md:66 | CWN: DEVELOPMENT.md reads "this parcel has no permits" and "the integration has been broken for a month". The inner quotes mark two states rather than cite a source, but they are near-quotes with one word changed |
| B7 | "four production occurrences" | 4 | STATUS M4 row | C |
| B8 | the four scripts "all exist because…" | 4 | STATUS scheduling note ~1294 | CWN: `heal_tract_vintage_gaps.py` was deleted in `b7c9cbb` (2026-08-26), and STATUS annotates it "historical". The sentence reports what the ledger records, and the ledger says "exist" |
| B9 | "one is on the property path entirely" | 1 | INVESTIGATION §5; m4-ledger REPORT §7 | C |
| B10 | "inspects seven things, none per-year" | 7 | INVESTIGATION §4 table | C |
| B11 | "three of the six sources — Landsat, Sentinel-2 and NAIP — have no trigger" | 3 / 6 | INVESTIGATION §4; six sources per §1.2's CHECK | C |
| B12 | "no query that reads inside a JSON document anywhere in the repository" | 0 | INVESTIGATION §9 | CWN: the grep covered `backend/app`, `backend/alembic` and `scripts`, not tests or frontend. The finding's own wording is "in SQL, anywhere" |
| B13 | "One of the two JSON-typed columns … is `json`" | 1 of 2 | INVESTIGATION §9 | C |
| B14 | "Five outcomes" | 5 | migration `0011` CHECK (m4-ledger REPORT §1); `year_ledger.py@ef2d0a2` `OUTCOMES` | C |
| B15 | "each with a machine reason" | — | `year_ledger.py@ef2d0a2`: `REASONS[ok]` is empty and `_validate` raises "'ok' takes no reason"; HEAL-SCORECARD §3 says "Every non-`ok` row carries a machine reason" | **X, edited** (§5) |
| B16 | "wired at all seven per-year sites" | 7 | STATUS M4; m4-ledger REPORT §4; INVESTIGATION §3 | C |
| B17 | "reached 184 of 184 parcels, exit 0" | 184 | m4-ledger HEAL-SCORECARD §2 | C |
| B18 | "wrote 16,244 ledger rows" | 16,244 | HEAL-SCORECARD §3 and header | C |
| B19 | "a prediction of 16,100 ± 300 written before deploy and never edited" | 16,100 ± 300 | m4-ledger PREDICTION §2 P2; git | CWN: `8ad20e6` is 2026-08-26T00:43:57Z, before the 00:51:55Z build. `adce829` later appended P7–P11 (81 insertions, no deletions to that file), so P2's text was never edited, but the file was |
| B20 | "zero `failed` rows fleet-wide" | 0 | HEAL-SCORECARD §7 | C |
| B21 | "1,154 decade rows over 183 parcels instead of roughly 989 over 157" | 1,154 / 183 / ≈989 / 157 | HEAL-SCORECARD §3; PREDICTION §2, §8 | C |
| B22 | "decennial 1990 was `absent` on all 184 parcels" | 184 | HEAL-SCORECARD §11 | C |
| B23 | "decennial 2000 on 137" | 137 | same | C |
| B24 | "ACS5 2009 on 75" | 75 | same | C |
| B25 | "silently `complete` for months" | months | the `if data:` skip enters in `7e5df04` (2026-03-25); HEAL-SCORECARD §11 | C |
| B26 | "All ten of its census groups … five of the ten read `absent`/`api_no_data`" | 10 / 5 | HEAL-SCORECARD §11.1 | C |
| B27 | "every succeeding year but one … the exception, ACS5 2023" | 1 | HEAL-SCORECARD §11.1; racebrook §2.2 rule; `ACS5_YEARS` | C |
| B28 | "`4ce1822`, gives every `(dataset, year)` pair its own geography vintage" | every | `census.py@4ce1822` `_GEOGRAPHY_VINTAGES` has 8 entries for 10 pairs; racebrook REPORT §5: "Decennial 1990 and 2000 stay unmapped"; STATUS M4: "Every year the geocoder can serve" | **X, edited** (§5) |
| B29 | "one invocation … exit 0, complete in 38 seconds" | 1 / 38 s | racebrook REPORT §10 | C |
| B30 | "`census_snapshots` 5 → 8 … at exactly the predicted figures" | 5 → 8 | §10 P1; PREDICTION P1 (2757 / 2453 / 2604) | C |
| B31 | "the five pre-existing rows unchanged, and all 68 imagery rows byte-identical by id" | 5 / 68 | §10 P1, P4 | C |
| B32 | "Three of the five came back. Two did not" | 3 / 2 | §10; PREDICTION P2 | C |
| B33 | "lists 1,798 datasets and `dec/*` appears at vintages 2000, 2010 and 2020 only" | 1,798 | census-decennial REPORT §2 | C |
| B34 | "186 by the time the fleet was re-measured" | 186 | §1.1, §2 | C |
| B35 | "four characters when there is none and six when there is" | 4 / 6 | §0, §1.4 | CWN: measured over 3,088 tracts in 8 counties; §9 marks the Bureau's naming of the convention UNVERIFIED |
| B36 | "all 47 parcels reading `ok` … all 80 whose tract does read `absent`" | 47 / 80 | §1.2 | CWN: 59 more `absent` tracts do not end in `00` and are real-suffix absences. "Decennial 2000's failure is a tract width" holds for 80 of 139 (STATUS M4: "a tract width, on 80 of the 139") |
| B37 | "a dead endpoint spent months in the ledger" | months | The ledger was first populated 2026-08-26 02:16Z (STATUS M4; HEAL-SCORECARD header), and `e6afa9b` is the same day. The months were the pre-ledger `if data:` skip | **X, edited** (§5). The sentence mirrors census-decennial REPORT §0 item 3, which carries the same error (§6) |
| B38 | "Grepping for that shape across every other outbound client found one more instance — Socrata's" | 1 | census-decennial REPORT §4 found Socrata only. But STATUS **N4** records Photon (`api/geocode.py:77-82`: `RequestError`/`HTTPStatusError` → `[]`) as the same shape, and `ops-batch/REPORT.md` §4's grep found it again. It is still open | **X, flagged** (§5) |
| B39 | "fixed two batches later in `2c3f468`" | 2 | The record calls the work between these commits batches: "the copy batch" (`722219e`, census-decennial REPORT §3, §10), the M3 batch (m3 REPORT), then the "Retry/ops batch" (`2c3f468`). That makes the ops batch the third, or the fourth if the test-network-guard pass counts | **X, flagged** (§5) |
| B40 | "Three heals were predicted and scored" | 3 | STATUS M3 row; HEAL-1/2/3 | C |
| B41 | "One delete, citing the outcome; the eight surviving rows untouched" | 1 / 8 | HEAL-1 Phase 3 items 3 and 5 | C |
| B42 | "Crawford County, Michigan, whose 33 groups all read `failed`/`read_timeout`" | 33 | HEAL-2 Phase 1 item 3; tract `26039960500` (HEAL-3 §1), state 26 | C |
| B43 | "22 came back `ok` — 16 Landsat years and 6 NAIP — and 11 came back `absent`" | 22 *(post)* / 16 / 6 / 11 | HEAL-2 Phase 3a item 2 | C |
| B44 | "Eleven of the thirty-three were genuine absence" | 11 / 33 | HEAL-2 addendum | C |
| B45 | "139 parcels selected through the script itself, 139 requests, exit 0" | 139 | HEAL-3 §3, §4, §5.1 | C |
| B46 | "`decennial` 2000 going 48 → 111 — exactly 63 rows, every one on a tract ending `00`, with 76 … absent" | 48 / 111 / 63 / 76 | HEAL-3 §5.3, §5.4 | C |
| B47 | "measured for the first time … depth of 25 on all 236 admission lines" | 25 / 236 | HEAL-3 §5.2; m3 REPORT UNVERIFIED item 6 | C |
| B48 | "no user request having arrived in that window or the larger sweep after it" | 0 | HEAL-3 §5.2; ops SWEEP-SCORECARD §8 | C |
| B49 | "Five commits widened the retry policies on SAS signing, the Census API and ArcGIS" | 5 | SWEEP-SCORECARD §10: "Every retry site shipped in `70437e6`, `8a86fad` and `533bc3b`". `git show --stat`: `2c3f468` is the Socrata 404 raise and `6daf621` is a test-only topo allowlist pin | **X, edited** (§5) |
| B50 | "enqueued 189 requests" | 189 | SWEEP-SCORECARD §1 | C |
| B51 | "met not one attempt at a status any of them retries" | 0 | SWEEP-SCORECARD §0 | CWN: log-derived with ~3% of the stream dropped. The ledger rules out exhausted retries only, and §0 says so |
| B52 | "It fired once in the captured window — one connection error against a Lower Manhattan parcel" | 1 | Z6 REPORT §1 (2 Broadway, `36061000900`); SWEEP-SCORECARD §9.1 | C |
| B53 | "the same reflex in three places at once" | 3 | property REPORT header: "Three defects, one shape" | C |
| B54 | "the District of Columbia could lose seven of its eight queries and end `complete`" | 7 *(post)* / 8 | property REPORT §1 (DC = 1 sales + 7 permit layers); `all_queries_failed` at `48b7fd8^` `county_adapters.py:127-128` | C |
| B55 | "Adams … with exactly one query" | 1 | property REPORT §1 | C |
| B56 | "Migration 0014" | 0014 | `backend/alembic/versions/0014_property_task_outcomes.py` (`1f7e398`) adds `partial`, the four counts and `coverage` | C |
| B57 | "Adams' deny-list is seven mailing cities" | 7 | property REPORT §5 | C |
| B58 | "4,013 house numbers across four streets spanning 741 to 16610, with zero … in the band" | 4,013 / 4 / 741 / 16610 | property REPORT §5 | CWN: a sample of four streets; REPORT §11 item 3 notes that only Thornton is confirmed from two directions |
| B59 | "the Adams parcel came back `skipped`, `not_covered`, `items_found` NULL" | NULL | property SCORECARD P-1 | C |

**Tally: 59 claims. 44 C, 9 CWN, 6 X (4 edited, 2 flagged), 0 U.**

### 2b. Non-numeric factual claims

Deviation from item 2: these are not numbers. They are factual claims that
the premise ("every claim traces") covers, so they are checked the same way.

| # | Claim | Source | Verdict |
|---|---|---|---|
| N1 | "a gate line written to catch a ledger that already held rows caught the opposite failure instead, because a table that does not exist also fails a check that it is empty" | `m4-ledger/SWEEP-PROMPT-1.md` Phase 1 line 2: "`alembic_version` on prod reads `0011`. `timeline_task_years` exists, has the expected columns, constraints, and indexes, and holds zero rows." `GATE-STOP.md` §1: "FAIL — version is `0010`; the table does not exist." The line checked version and existence explicitly and failed on them. It did not catch the failure through its emptiness clause. The "written to catch a ledger that already held rows" half is defensible, because it is the line's own rationale sentence | **X, flagged** (§5) |
| N2 | The census skip returns `{}`, increments nothing, and the all-failed check cannot see it | `timeline.py@07b55e0` census loops | C |
| N3 | A county API outage was recorded as a completed property fetch with zero records | FINDINGS.md H4 heading | C |
| N4 | Rollup counts lived only in a log line, and `items_found` was the lifetime total; aggregation counted only `failed` | `timeline.py@48b7fd8^` :1340-1397; `imagery.py@48b7fd8^` `aggregate_request_status` | C |
| N5 | `lookup_tract_at_vintage` "retried timeouts only and raised on everything else"; the caller caught every geocoder error and fell back | `geocoder.py@4275908^` (`except httpx.TimeoutException` retries; `HTTPStatusError`/`RequestError` raise); `timeline.py@4275908^` `_VintageTracts.tract_for` | C |
| N6 | "Racebrook is the standing counterexample" | Z6 REPORT §1 names "Denver 41.11" as the counterexample. Racebrook qualifies on `racebrook/REPORT.md` §1.2 and §2.3: its stored tract differs from its vintage tract on six of ten years | CWN: well supported, but by a different document than the Z6 report |
| N7 | "four production occurrences of the first of those silences — years dropped under a `complete` task" | STATUS M4 | CWN: the preceding paragraph describes the first silence in its census form, while occurrences (1)–(2) are Landsat. The appositive carries the correct scope. It was an owner-directed edit per PHASE0-NOTES, batch 2 |
| N8 | "All of this was agent-built from my prompts" | Model trailers on every named commit: `7e5df04`, `4544f10`, `b5a306a`, `256ed32`, `0814d7e`, `ef2d0a2`, `a6c7800`, `48b7fd8`, `eee8a9e`, `4275908`, and the five PREDICTION-creating commits (`8ad20e6`, `4330833`, `ea0f640`, `1a9854f`, `7ac08a3`) | CWN: agent authorship is recorded. "From my prompts" is the author's own testimony |
| N9 | "the model version is not what changed between them" | Trailers: the census skip `7e5df04` and the property path with the Adams adapter `4544f10` are **Claude Opus 4.6 (1M context)**. The vintage fallback `b5a306a` and the H4 all-failed rule `256ed32` are Opus 5. The instruments are Opus 5 (`4275908` is Sonnet 5) | **X, flagged** (§5) |
| N10 | "Every one of these paths was already logging something, and several were logging success" | INVESTIGATION §3f (the census 404 is logged INFO inside the client, and nothing at the loop); ops SWEEP-SCORECARD §5 ("Property history fetch complete items_saved: 0"); Z6 §1 warning | CWN: the census path logged only inside the client, without a parcel |
| N11 | Unknowable → answered → healed arc; "no crosswalk table and no Connecticut special case" | racebrook REPORT §0, §2.3, §5 | C |

**Tally: 11 claims. 5 C, 4 CWN, 2 X (both flagged), 0 U.**

---

## 3. Commit hashes

Frontmatter cites no hashes. In the body, every hash is an ancestor of HEAD
(`git merge-base --is-ancestor <h> HEAD` exits 0 for all six).

| Hash | `git show --stat` | Sentence's attribution | Verdict |
|---|---|---|---|
| `0814d7e` | migration `0011`, `models/parcels.py`, `conftest.py` | ledger table shipped | C |
| `ef2d0a2` | `year_ledger.py`, `timeline.py`, `stac.py`, `usgs_topo.py`, `imagery.py`, `ledger_gaps.py`, tests | the seven sites wired | C |
| `4ce1822` | `census.py` (vintage map), `test_timeline.py`, racebrook REPORT | per-pair geography vintage | C for the files. The sentence's "every pair" overreach is B28, edited |
| `e6afa9b` | `census.py`, `year_ledger.py`, `timeline.py`, tests | 1990 dropped, 2000 width, 404 → `failed`/`http_<status>` | C |
| `2c3f468` | `socrata.py`, `test_county_adapters.py` | Socrata 404 fix | C |
| `4275908` | `geocoder.py`, `timeline.py`, tests | Z6 fix | C |

Also checked because B49 depends on them: `70437e6` (`stac.py` SAS retry),
`8a86fad` (`census.py` retry), `533bc3b` (`arcgis.py` 429 retry), and
`6daf621` (test-only, `test_imagery.py`, topo allowlist pin).

---

## 4. Sources paragraph

All eight directories exist under `docs/audits/`, and so does
`2026-08-second-audit/STATUS.md`. **The ordering claim is true.** The body
walks m4-design ("Where the outcomes live"), then m4-ledger (gate stop, first
sweep, the ledger's first readings), then racebrook, census-decennial, m3
(backfill path, retry table, three heals), ops-batch, z6-vintage-lookup, and
property-outcomes, in that order.

**Note, not a contradiction:** the opening paragraph's 63-response count and
the occurrence-(4) framing rest on `2026-08-geometry-audit/HEAL-SCORECARD.md`
§7, which the paragraph does not list. It fits first in the order if added.
The paragraph was left unchanged, because adding a source is not a minimal
correction of a false claim.

---

## 5. Edits and flags

### Edits made (CONTRADICTED, one defensible reading)

| # | Line | Before | After | Basis |
|---|---|---|---|---|
| E1 (B15) | 84-85 | "`indeterminate` — each with a machine reason, wired at all seven per-year sites." | "`indeterminate` — every one but `ok` with a machine reason, wired at all seven per-year sites." | `year_ledger.py@ef2d0a2` rejects any reason on `ok`; HEAL-SCORECARD §3: "Every non-`ok` row carries a machine reason" |
| E2 (B28) | 121-122 | "gives every `(dataset, year)` pair its own geography vintage." | "gives every `(dataset, year)` pair the geocoder can serve its own geography vintage." | `census.py@4ce1822` (8 of 10); racebrook REPORT §5; STATUS M4's own phrase |
| E3 (B37) | 142 | "which is how a dead endpoint spent months in the ledger as "the tract has no data."" | "which is how a dead endpoint spent months as "the tract has no data."" | The ledger was populated the same day the fix landed (2026-08-26). The months were the pre-ledger skip, logged as "no data for tract" (INVESTIGATION §3f). The narrowest true reading deletes three words |
| E4 (B49) | 173 | "Five commits widened the retry policies" | "Three commits widened the retry policies" | SWEEP-SCORECARD §10; `git show --stat` on all five |

E1 and E2 pushed lines past the file's 78-column wrap, so those two
paragraphs (lines 82-89 and 121-129) were re-wrapped. `git diff
--word-diff` shows no word changes beyond the four above. `status` is untouched. No `[NEEDS]` markers were inserted,
because no claim was UNVERIFIABLE.

### Flagged, text left as written (CONTRADICTED, correction needs a judgment call)

1. **N9, line 215, "the model version is not what changed between them."**
   This is the strongest flag. The trailers contradict it for two of the
   silences: the census skip (`7e5df04`) and the original property path
   (`4544f10`) were written by Claude Opus 4.6 (1M context), and the
   instruments by Opus 5. It holds for the vintage fallback (`b5a306a`) and
   the H4 rule (`256ed32`), which are both Opus 5. The sentence carries the
   closing section's argument, so how to restate it is the author's call.
   DEVELOPMENT.md:49 makes a narrower claim ("the review stance seems to
   matter a lot more than the model version") and :51 records that stamping
   was inconsistent before mid-August.
2. **B38, line 144, "found one more instance."** STATUS N4 (Photon,
   `api/geocode.py:77-82`) is the same shape, and it is still open. The post's
   own thesis would take it in. Whether to name it, or to narrow "every other
   outbound client" to the clients the census-decennial grep covered, is an
   authorial choice.
3. **N1, line 91, the gate-line mechanism.** The line checked the version and
   the table's existence explicitly. A restatement means choosing how much of
   the first post's framing to keep. That framing is also one of the first
   post's candidate titles ("A gate written for the opposite failure").
4. **B39, line 145, "two batches later."** By the record's own use of
   "batch", the ops batch is the third or fourth after `e6afa9b`. "The next
   day" (2026-08-26 → 2026-08-27) is exact, but choosing that wording is a
   rewrite.

### Not edited, by choice

The frontmatter entry 1's claim that occurrence (2) is on the SAS signing
path is unsupported (§1). I left it alone because the frontmatter is the
drafting session's verification record. This file supersedes it. Rewriting
the entry would blur which session concluded what.

---

## 6. The record itself: flagged, not fixed

`docs/audits/` is read-only for this session. By the repo's norm 3, each
of these belongs in STATUS.md, and none could be entered from here.

1. **`census-decennial/REPORT.md` §0 item 3:** "a dead endpoint spent months
   in the ledger". The ledger was first populated 2026-08-26 02:16Z, the same
   day as the report. The months were pre-ledger.
2. **`census-decennial/REPORT.md` §4:** "Every other outbound client was
   checked." The table omits Photon (`api/geocode.py:77-82`), which STATUS N4
   already recorded as the same shape. `ops-batch/REPORT.md` §4 later found it.
3. **`ops-batch/SWEEP-SCORECARD.md` §9.1:** says `lookup_tract_at_vintage`
   "issues a bare `client.get` with no attempt loop". At `4275908^` it has an
   attempt loop that retries `httpx.TimeoutException`. `z6-vintage-lookup/REPORT.md`
   §1 has it right.
4. **STATUS.md M4 row:** cites `geometry-audit/HEAL-SCORECARD.md` §6 as the
   evidence for occurrence (4). The content is §7.
5. **STATUS.md M4 row and scheduling note:** "three independent upstreams"
   counts (1)–(3). (1) and (2) are both Landsat year loss, and
   `ops-audit/FINDINGS.md` says (2)'s mechanism is unknown, so "independent"
   is not established.
6. **`z6-vintage-lookup/REPORT.md` §1:** "Denver 41.11 (`4ce1822`)". The
   Denver 41.07 → 41.11 case is `b5a306a`'s. `4ce1822` only updated its test
   (racebrook REPORT §6). This is a citation looseness, not a wrong fact.

---

## 7. Reconciliation with `PHASE0-NOTES.md`

Read after every verdict above was formed.

- **Beat 4 (gate stop), SUPPORTED there, X here (N1).** The notes cite
  GATE-STOP §1's result but not SWEEP-PROMPT-1's wording of line 2, which is
  where the mechanism clause fails.
- **Beat 7 (ops batch), SUPPORTED there, X here (B49).** The notes do not
  test "five commits" against which commits carried retries.
- **Beat 5 (census defects), SUPPORTED there, X here on two sentences (B37,
  B38).** The notes verify the 1,798 / 47 / 80 figures, which hold. They do
  not check "months in the ledger" against the ledger's start date, or the
  grep's scope against N4.
- **Beat 5 / `4ce1822` (B28).** Not examined in the notes.
- **The closing section (N9)** is not among the notes' beats. Nothing in
  the notes checks it.
- **Z6 counterexample (N6).** The notes call Racebrook "a genuine
  relationship in the record". It is, via racebrook §1.2, but the Z6 report
  names Denver 41.11.
- **Item 5 of edit batch 2 (paraphrase).** The notes' nearest hit is
  `PHASE_3_PROMPT.md:140`. Lines 260 and 268 of the same file are closer in
  substance (§1, entry 4).
- **Edit batch 2, item 2 (two upstreams).** The notes place (2) on the
  signing path. The ops audit says its mechanism is unknown (§1, entry 1).
- **Everything else agrees.** All nine beats' numeric figures that the notes
  cite match the record as read here.

---

## 8. Recommendation

**Not yet ready for the publish decision. It is close.** Four sentences
were corrected in place, and each correction is a narrowing, not a new
claim. Four flagged sentences need the owner. Three of them can each be
settled in one line:

1. **N9 is the one that matters.** The closing section's argument rests on
   "the model version is not what changed", and the trailers show it did
   change for the census skip and the original property path. Restate it
   narrowly (for example, around the vintage fallback and the H4 rule, both
   Opus 5), or cut the clause.
2. **B38:** decide whether Photon (N4, still open) enters the sentence.
3. **N1:** decide how to phrase the gate line's mechanism.
4. **B39:** a count to fix or drop.

Optional: add `2026-08-geometry-audit/` to the Sources paragraph.

Once those are decided, every remaining claim in the post traces to a file
or a commit, and the draft meets its own premise.

---

## Edit batch 2026-09-10 (post-verification)

Written 2026-09-10 against HEAD `3ca91ed`. The owner decided all four §5
flags and the §4 note; this batch executes those decisions. Every edit
traces to a flag or finding above, to `m4-ledger/GATE-STOP.md`, to
DEVELOPMENT.md, or to a cited commit. The post's `status` is untouched.
Body word count (everything after the frontmatter, the method that
reproduces the 2,209 and 2,245 of earlier commits): **2,249 → 2,302**.

The four record-level findings in §6 items 1, 3, 4 and 5, plus the Photon
note for §6 item 2, are entered in STATUS.md in the commit that follows
this one. This file cannot carry its own commit hash.

### Item 1 — N9, the model-version claim (narrowed, one paragraph)

**Before:** "The same tooling that wrote the silences wrote the
instruments; the model version is not what changed between them. What
changed was what I asked for."

**After, the paragraph in full:**

> All of this was agent-built from my prompts — the census skip, the property
> rollup and the vintage fallback, and equally the ledger, the retry policy, the
> coverage gate and every prediction they were scored against. The same tooling
> that wrote the silences wrote the instruments, but the model version moved
> between them, and I can't isolate it from everything else that moved. What I
> can point to is narrower. The vintage fallback and the property path's
> all-failed rule were written by the same model that later built the ledger and
> the coverage gate, and that model instrumented the all-failed rule itself;
> only the fallback's fix came from another. In those two, what changed was what
> I asked for. A prompt asking for a census fetch that is resilient to a bad year
> produces a skip. A prompt asking that every attempted year carry an outcome
> the database can distinguish, and that the expected result be written down
> before the run, produces a table, a vocabulary, and a scorecard allowed to
> come back `not exercised`.

**Trailers relied on** (`git log -1 --format='%(trailers:key=Co-Authored-By)'`):

| Role | Commit | Trailer |
|---|---|---|
| Census skip | `7e5df04` | Claude Opus 4.6 (1M context) |
| Original property path | `4544f10` | Claude Opus 4.6 (1M context) |
| Vintage fallback | `b5a306a` | Claude Opus 5 |
| H4 all-failed rule | `256ed32` | Claude Opus 5 |
| Ledger | `0814d7e`, `ef2d0a2` | Claude Opus 5 |
| Coverage gate | `eee8a9e` | Claude Opus 5 |
| All-failed rule instrumented (`partial`, counts) | `48b7fd8`, `1f7e398` | Claude Opus 5 |
| Vintage fallback fixed (Z6) | `4275908` | Claude Sonnet 5 |

`b5a306a`'s message is where the fallback enters: "a missing tract or a
geocoder outage falls back to the stored tract". DEVELOPMENT.md's
attribution note records that about a third of commits carried no trailer
as of the audit and that stamping was consistent only from about mid-August.
All ten commits above carry one.

**Deviation from the instruction.** The instruction named both the vintage
fallback and the all-failed rule as "written and later instrumented by the
same model". That holds for the all-failed rule (`256ed32` → `48b7fd8`,
`1f7e398`, all Opus 5). It does not hold for the fallback: its fix,
`4275908`, is Sonnet 5, and the ledger did not instrument it — Z6 REPORT §1
records that the row and the ledger "carry no trace that the tract came from
a fallback". The paragraph therefore says both were written by the model
that later built the ledger and the coverage gate (true for both), says that
model instrumented the all-failed rule (true), and says the fallback's fix
came from another model.

**Observation, not edited.** The next sentence's example, "a census fetch
that is resilient to a bad year produces a skip", illustrates with the
census skip, which is one of the two cases where the model did change
(`7e5df04`, Opus 4.6). The sentence is about prompt shape, not model, so it
is not false. A skeptical reader may still notice it sits next to the
narrowed claim.

### Item 2 — B38, line 144 (Photon enters)

**Before:** "Grepping for that shape across every other outbound client
found one more instance — Socrata's 404 returning an empty list on the
property path — fixed two batches later in `2c3f468`."

**After:** "Grepping for that shape across every other outbound client
found two more instances: Socrata's 404 returning an empty list on the
property path, fixed in a later batch in `2c3f468`, and Photon's errors
returning an empty address-suggestion list, which is still open."

Basis: STATUS.md N4 (`api/geocode.py:77-82`, `RequestError` and
`HTTPStatusError` → `return []`, "LOW — Open"); `ops-batch/REPORT.md` §4's
grep found it again.

### Item 3 — N1, line 91, the gate clause

**Case applied: the framing is dropped.** `GATE-STOP.md` does not state
that gate line 2's purpose was guarding against a ledger that already held
rows. The line that decided it is §1's table row, `GATE-STOP.md:30`:

```
| 2 | `alembic_version` = `0011`; `timeline_task_years` exists, empty | **FAIL** — version is `0010`; the table does not exist |
```

The rest of GATE-STOP.md (§1.2's evidence, §7) states no purpose for the
line either. The purpose sentence exists only in the brief,
`SWEEP-PROMPT-1.md:25`: "Otherwise stop — a non-empty ledger before the
sweep means something already ran." The instruction's test was GATE-STOP.md,
so the framing went.

**Before:** "The first sweep did not run: a gate line written to catch a
ledger that already held rows caught the opposite failure instead, because a
table that does not exist also fails a check that it is empty — which is the
first post's subject."

**After:** "The first sweep did not run: the pre-sweep gate checked
`alembic_version` and the ledger table's existence, and found `0010` and no
table — which is the first post's subject."

The cross-reference "— which is the first post's subject." is unchanged.
The rest of the paragraph was re-wrapped to 78 columns; no other words
changed.

### Item 4 — B39, line 145

**Before:** "fixed two batches later in `2c3f468`"
**After:** "fixed in a later batch in `2c3f468`"

Carried inside item 2's sentence.

### Item 5 — Sources paragraph (§4 note)

**Before:** "`2026-08-m4-design/`, `2026-08-m4-ledger/`, …"
**After:** "`2026-08-geometry-audit/`, `2026-08-m4-design/`,
`2026-08-m4-ledger/`, …"

Placed first. The opening paragraph's 63 no-data responses come from
`geometry-audit/HEAL-SCORECARD.md` §7, and the opening is the first thing
the post walks, so "in the order this post walks them" stays true.

### Item 6 — frontmatter `facts_to_verify`, entry 1

**Before (the changed span):** "that clause is removed, because STATUS.md's
M4 row puts occurrences (1) and (2) on the Planetary Computer SAS signing
path and (3) and (4) on api.census.gov — two distinct upstreams, not four
(the row's own summary sentence says three, counting only (1)-(3))."

**After:** "that clause is removed. STATUS.md's M4 row attributes occurrence
(1) to Planetary Computer SAS signing 429s and records (3) and (4) against
api.census.gov; occurrence (2) was a Landsat loss whose cause
ops-audit/FINDINGS.md leaves unestablished (it records that it happened,
not why)."

The "summary sentence says three" parenthetical also went: the next commit
rewrites that STATUS.md sentence, and the entry would otherwise cite text
that no longer exists. The rest of the entry is unchanged. §5's "Not edited,
by choice" paragraph above stands as a record of what the verification
session decided. This entry is now the owner's decision, executed.

### Follow-up, 2026-09-10 (after `633bb88` and `5a93e10`)

The owner accepted item 1's departure (the vintage fallback is not a
same-model case) and noted that the paragraph still counted it. The owner
also accepted `SWEEP-PROMPT-1.md:25` as the record of the gate's purpose:
it is the brief that commissioned the gate, and it lives under
`docs/audits/`. Body word count: **2,302 → 2,328**.

#### Item 1, revised — the fallback leaves the same-model claim

**Before (as of `633bb88`):** "What I can point to is narrower. The vintage
fallback and the property path's all-failed rule were written by the same
model that later built the ledger and the coverage gate, and that model
instrumented the all-failed rule itself; only the fallback's fix came from
another. In those two, what changed was what I asked for. A prompt asking
for a census fetch …"

**After, the paragraph in full:**

> All of this was agent-built from my prompts — the census skip, the property
> rollup and the vintage fallback, and equally the ledger, the retry policy, the
> coverage gate and every prediction they were scored against. The same tooling
> that wrote the silences wrote the instruments, but the model version moved
> between them, and I can't isolate it from everything else that moved. What I
> can point to is narrower: the property path's all-failed rule was written by
> the same model that later built the ledger and the coverage gate, and that
> model instrumented the rule itself. There, what changed was what I asked for.
> The shape of the ask shows even where the model also changed. A prompt asking
> for a census fetch that is resilient to a bad year produces a skip. A prompt
> asking that every attempted year carry an outcome the database can
> distinguish, and that the expected result be written down before the run,
> produces a table, a vocabulary, and a scorecard allowed to come back
> `not exercised`.

The owner's suggested text was used verbatim. Checked against the item 1
trailer table: `256ed32` (the all-failed rule, 2026-08-03) is Opus 5. The
ledger (`0814d7e`, `ef2d0a2`, 2026-08-25) and the coverage gate (`eee8a9e`,
2026-08-27) are Opus 5 and come later. The rule was instrumented by
`48b7fd8` and `1f7e398`, both Opus 5. The added clause, "even where the
model also changed", is what now sits before the census example: the
census skip `7e5df04` is Opus 4.6 and the ledger is Opus 5. That closes
item 1's "Observation, not edited" above.

#### Item 3, revised — the framing returns, with the recorded mechanism

**Sources:** the gate's purpose comes from `SWEEP-PROMPT-1.md:25` ("holds
zero rows. Otherwise stop — a non-empty ledger before the sweep means
something already ran."). The mechanism comes from `GATE-STOP.md:30`
("FAIL — version is `0010`; the table does not exist").

**Before (as of `633bb88`):** "The first sweep did not run: the pre-sweep
gate checked `alembic_version` and the ledger table's existence, and found
`0010` and no table — which is the first post's subject."

**After:** "The first sweep did not run, and the gate line that stopped it
was written for the opposite failure: a ledger that already held rows, since
rows before the sweep mean something already ran. It checked the migration
version and the table's existence first, and found `0010` and no table —
which is the first post's subject."

"First" follows the line's own order in `SWEEP-PROMPT-1.md:25` (version,
then existence, then zero rows) and GATE-STOP.md §1.2's evidence. That
evidence reads `alembic_version` and then hits `UndefinedTable` before
emptiness is ever reached. The cross-reference "— which is the first post's
subject." is unchanged. The paragraph was re-wrapped to 78 columns.
