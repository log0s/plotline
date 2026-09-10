---
status: draft
candidate_titles:
  - "Complete, with permanent gaps"
  - "Instrument the silences"
  - "What `complete` was hiding"
  - "Every silence looked like the same silence"
  - "Absent, wearing a timeout's clothes"
pull_quote: "A system that can only report success will report success."
facts_to_verify:
  - "The four occurrences and the four heal scripts are two separate counts and the post states them as two. The draft also called the four occurrences independent upstreams; that clause is removed, because STATUS.md's M4 row puts occurrences (1) and (2) on the Planetary Computer SAS signing path and (3) and (4) on api.census.gov — two distinct upstreams, not four (the row's own summary sentence says three, counting only (1)-(3)). No upstream count is stated in the post. STATUS.md's M4 row records four production occurrences; the scheduling note that names revalidate_landsat.py, requeue_empty_property.py, heal_tract_vintage_gaps.py and requeue_parcels.py as the recurring chore was written when the count stood at three, and requeue_empty_property.py is a property-path script. Nothing pairs a script to an occurrence, and the post does not."
  - "Racebrook's five missing years read `absent`/`api_no_data` in the ledger, not a distinct outcome. What made them diagnostic is the tract carried in `detail` — 09170157100 on every failing year, 09009157100 on every succeeding year but one. The post says the detail is what answered the question, and the outcome vocabulary alone would not have."
  - "ACS5 2023 is the one succeeding year not asked under 09009157100: it carries 09170157100, the post-2022 planning-region key. `docs/audits/2026-08-racebrook/REPORT.md` §3 (Blast radius — 'Its five surviving census snapshots') and §10 (the requeue addendum's P3 ledger table) both record it, as does §2.3's live geocoder matrix (`ACS2023_Current` → `09170157100`). That makes the exception the confirming case for the diagnosis rather than an anomaly — the one vintage in the set actually published under the new geography is the one the new-geography key succeeds against. The post names the key and says so."
  - "The two prompt shapes near the end are paraphrase, not quotation. Grep over docs/, prompts/, scripts/ and backend/ finds neither string in any recorded prompt or brief, so the post states them without quotation marks as the shape of a request rather than its text."
  - "The 63 `Census API: no data for tract` responses are a fleet-wide count from the 2026-08-12 geometry sweep (HEAL-SCORECARD.md §7), not Racebrook's own. The post attributes them to the sweep."
  - "Crawford's split — 22 recovered, 11 real absence — is the sum of two lines in HEAL-2-crawford.md §3a (16 Landsat `ok` plus 6 NAIP `ok`, against 11 NAIP `absent`/`no_scenes`). The arithmetic is the post's; the three counts are the record's."
  - "The admission reserve's `depth=25` on 236 of 236 lines rests on HEAL-3 §5.2 alone. So does the statement that no `origin='user'` request arrived; STATUS.md's M3 row adds a second heal with the same result, which is why the post says the reserve has never been observed doing the thing it exists for."
  - "The Adams house-number sample (4,013 numbers, 741–16610, zero in 9000–13600) rests on a single reading taken 2026-08-27 for that batch (property-outcomes REPORT.md §5). It is a sample of four streets, not the whole layer."
  - "Z6's one production instance is the only one in the capture, and the capture dropped roughly 3% of the worker stream that sweep. `not exercised` and `exercised once` are both consistent with the evidence for the retry sites; `fired once` is not a floor the record establishes for Z6 either, only what was seen."
---
# Complete, with permanent gaps

In August a sweep ran across Plotline's parcel fleet and one address came back
wrong in a way nothing in the system could name. Parcel `2f1b332e` — Racebrook
Road, Orange, Connecticut — held five census years where its neighbors held
seven to nine, and it had just been re-run in full. Its task ended `complete`.
No failure was recorded, and the sweep logged 63 `Census API: no data for
tract` responses fleet-wide that are, at the row level, identical to a tract
that has no data for a year. Connecticut replaced its counties with planning
regions for data tabulated from 2022, which makes genuine absence entirely
plausible — the point, not a mitigating detail.

The audit row that recorded it said so plainly: nothing could say whether
those years re-failed or were never published, and no heal script could be
written until something could. The parcel was unknowable by design — not by a
design anyone chose, but by a run of small, locally sensible decisions that
each converted an upstream failure into a smaller success.

There were four of them, in four different places. A census task that lost
some of its years still ended `complete`, because a year the API has no data
for returns `{}` and is skipped without incrementing the failure counter, so
the task's own all-failed arithmetic cannot see it. A county API outage was
recorded as a completed property fetch with zero records. An address outside
an adapter's real jurisdiction was indistinguishable from an address the
county simply has nothing on. And a tract lookup that failed transiently fell
back to the parcel's stored tract, wrote the census row under it, and recorded
the year `ok`. Each is defensible alone. Together they meant the database
could not distinguish "this parcel has no history" from "this integration has
been broken for a month." My development notes have a name for the fix:
instrument the silences.

The status ledger records four production occurrences of the first of those
silences — years dropped under a `complete` task. Separately, it records the
argument for doing something: `revalidate_landsat.py`,
`requeue_empty_property.py`, `heal_tract_vintage_gaps.py` and
`requeue_parcels.py` all exist because a task cannot say which years it failed
to fetch. Two counts, not one — no script is
paired to an occurrence, and one is on the property path entirely. The
recurring chore was the argument.

## Where the outcomes live

The design question was where a per-year outcome should sit: a JSONB column on
the existing task row, or a row per attempted year. It was answered against
what the backfill path needs to read rather than what is cheapest to write.
`maybe_refetch_for_backfill` inspects seven things, none per-year, and three
of the six sources — Landsat, Sentinel-2 and NAIP — have no trigger at all.
Whatever shape the outcomes took, the query would be a set query across
parcels and runs, not a document read.

The second argument was about the harness, and it is the sharper one. A grep
across the backend, the migrations and the scripts for JSON operators and
containment returns no query that reads inside a JSON document anywhere in the
repository. One of the two JSON-typed columns in the schema is `json` rather
than `jsonb`, so even "we already use JSONB" is only half true as precedent.
And the test suite runs on SQLite, which has neither `jsonb_each` nor GIN —
every JSONB query the design would need is unavailable in the test database. A
per-year table is ordinary rows and B-trees and runs identically on both
dialects. The investigation called that a fact about the harness rather than
about Postgres, which is the correct place to put it.

So: `timeline_task_years`, one row per attempted group, shipped in `0814d7e`
and `ef2d0a2`. Five outcomes — `ok`, `failed`, `absent`, `suppressed`,
`indeterminate` — each with a machine reason, wired at all seven per-year
sites. Two things it deliberately does not do. Task status semantics are
unchanged: a task with failed years still ends `complete`, and the ledger is
the record, not the enforcement. And it starts at deploy carrying no history,
because no backfill is possible for outcomes never written down — a parcel's
absence from the gap report means "not yet swept," not "healthy."

The first sweep did not run: a gate line written to catch a ledger that
already held rows caught the opposite failure instead, because a table that
does not exist also fails a check that it is empty — which is the first post's
subject. Once the migration runner was fixed, one `revalidate_landsat.py`
invocation reached 184 of 184 parcels, exit 0, and wrote 16,244 ledger rows
against a prediction of 16,100 ± 300 written before deploy and never edited.
Every falsifiable clause held, with zero `failed` rows fleet-wide. The one
deviation — a topo split of 1,154 decade rows over 183 parcels instead of
roughly 989 over 157 — was flagged as unverifiable in the prediction's own
text, for the reason it deviated.

## What the ledger said

The first thing it said was that decennial 1990 was `absent` on all 184
parcels, decennial 2000 on 137, and ACS5 2009 on 75 — the first measurement
ever taken of the `if data:` skip. All of it had been silently `complete` for
months.

The second thing it said was about Racebrook. All ten of its census groups
recorded an outcome, and each carried in `detail` the tract it had actually
asked about. Every failing year was asked under `09170157100`; every
succeeding year but one was asked under `09009157100` — the exception, ACS5
2023, is the only vintage in the set published under the post-2022
planning-region geography, and it succeeded under `09170157100`. The
vocabulary alone would not have settled anything — five of the ten read
`absent`/`api_no_data`, effectively what they had been saying all along. What
settled it was the key in the detail column. Not a re-failure: we had been
asking with the post-2022 planning-region geography for vintages published
under the pre-2022 county one.

The fix, `4ce1822`, gives every `(dataset, year)` pair its own geography
vintage. No crosswalk table and no Connecticut special case was needed — the
Census geocoder already draws the boundary where the data API draws it. The
requeue was predicted first and scored after: one invocation gated on the
deployed SHA, exit 0, complete in 38 seconds, `census_snapshots` 5 → 8 with
ACS5 2009, ACS5 2021 and decennial 2020 arriving at exactly the predicted
figures, the five pre-existing rows unchanged, and all 68 imagery rows
byte-identical by id. Three of the five came back. Two did not, and the
prediction said which two before the run.

Those two became fleet-wide findings rather than a footnote. Decennial 1990
does not exist on `api.census.gov` at all: the discovery endpoint lists 1,798
datasets and `dec/*` appears at vintages 2000, 2010 and 2020 only. Every one
of those `absent` rows — 186 by the time the fleet was re-measured — was a 404
wearing an absence label. Decennial 2000's failure is a tract width:
`2000/dec/sf1` addresses a tract by its basic code plus a real suffix, four
characters when there is none and six when there is, and our six-character
form 204s on every no-suffix tract. The split in the ledger is perfect — all
47 parcels reading `ok` have a tract that does not end in `00`, and all 80
whose tract does read `absent`. Both are fixed in `e6afa9b`, with the
mechanism underneath: `_request` mapped 404 to `None` to `{}` to `absent`,
which is how a dead endpoint spent months in the ledger as "the tract has no
data." A 4xx or 5xx now raises and lands as `failed`/`http_<status>`. Grepping
for that shape across every other outbound client found one more instance —
Socrata's 404 returning an empty list on the property path — fixed two batches
later in `2c3f468`.

Then the half that acts on it. `maybe_refetch_for_backfill` gained a path that
selects retryable groups from the ledger, folds them onto the sources that
would re-run them, and dispatches one scoped request. The retry policy is a
table keyed on `(outcome, reason)` with the outcome-wide fallback deliberately
missing for `absent`, so a new absence reason added without a decision
announces itself as a policy gap rather than being swept into "no."

Three heals were predicted and scored. The first deleted a served NAIP card on
the ledger's authority: parcel `e513188c` was serving a 2023 image built from
a tile that does not contain the parcel, and the same run's ledger recorded
that group `suppressed`/`naip_no_point_coverage` on that item id. One delete,
citing the outcome; the eight surviving rows untouched. The second was
Crawford County, Michigan, whose 33 groups all read `failed`/`read_timeout`.
Re-attempted, 22 came back `ok` — 16 Landsat years and 6 NAIP — and 11 came
back `absent`/`no_scenes`. Eleven of the thirty-three were genuine absence
wearing a timeout's clothes, and the ledger is what told them apart; before
per-year persistence that task was just `failed`, with nothing to say which
years were worth a retry. The third was the fleet-wide decennial-2000 sweep:
139 parcels selected through the script itself, 139 requests, exit 0, and
`decennial` 2000 going 48 → 111 — exactly 63 rows, every one on a tract ending
`00`, with 76 correctly re-recorded as absent. The admission reserve was
measured for the first time and held at a depth of 25 on all 236 admission
lines — and is still unobserved doing the thing it exists for, no user request
having arrived in that window or the larger sweep after it.

That larger sweep is worth one honest sentence. Five commits widened the retry
policies on SAS signing, the Census API and ArcGIS; the sweep scoring them
enqueued 189 requests and met not one attempt at a status any of them retries.
The verdict is `not exercised`, written into the prediction before the run and
not upgraded after. A quiet sweep is not confirmation.

## The same reflex, elsewhere

The sweep that found nothing did find one thing, on the client that batch had
not widened. `lookup_tract_at_vintage` retried timeouts only and raised on
everything else; its caller caught every geocoder error unconditionally, fell
back to the parcel's stored tract, and handed that tract to the fetch loop,
which wrote the census row and recorded the year `ok`. Neither carried a trace
that the tract came from a fallback. It fired once in the captured window —
one connection error against a Lower Manhattan parcel — and the fallback
happened to be right, because that tract has not moved under any vintage the
geocoder serves. That is luck, not a property of the mechanism, and Racebrook
is the standing counterexample. Fixed in `4275908`.

The property path had the same reflex in three places at once, and it took a
schema migration to give them states. A task was `failed` only if every query
failed, so the District of Columbia could lose seven of its eight queries and
end `complete`, thinner; Adams County passed that test only by arithmetic,
since with exactly one query "one failed" and "all failed" are the same
sentence. The matched and returned row counts both existed at the rollup and
went into a log line and nowhere else, while the number the task stored was
the parcel's persisted lifetime total. And an address in a municipality the
adapter's data source does not cover produced a genuine-looking `complete`
with zero records. Migration 0014 gave the task row `partial`, both row
counts, and a coverage state; the request aggregation had to change too, since
it counted only `failed` and would have dropped a `partial` task into the
complete bucket one level up. Adams' deny-list is seven mailing cities,
derived from the layer's own contents: 4,013 house numbers across four streets
spanning 741 to 16610, with zero anywhere in the band that is Thornton,
Northglenn and Federal Heights. The gap is the jurisdiction. And a missing
city never denies: the gate may turn a real answer into "we did not ask" only
when it knows something. On the scoring run the Adams parcel came back
`skipped`, `not_covered`, `items_found` NULL.

All of this was agent-built from my prompts — the census skip, the property
rollup and the vintage fallback, and equally the ledger, the retry policy, the
coverage gate and every prediction they were scored against. The same tooling
that wrote the silences wrote the instruments; the model version is not what
changed between them. What changed was what I asked for. A prompt asking for a
census fetch that is resilient to a bad year produces a skip. A prompt asking
that every attempted year carry an outcome the database can distinguish, and
that the expected result be written down before the run, produces a table, a
vocabulary, and a scorecard allowed to come back `not exercised`.

The thing I would take from this is that a silence is not a missing log line.
Every one of these paths was already logging something, and several were
logging success. The fix is a state the database can distinguish — a row
saying which year, under which key, with which reason — and the discipline of
writing down what you expect it to say before you look. A system that can only
report success will report success.

Sources, all under `docs/audits/` and in the order this post walks them:
`2026-08-m4-design/`, `2026-08-m4-ledger/`, `2026-08-racebrook/`,
`2026-08-census-decennial/`, `2026-08-m3/`, `2026-08-ops-batch/`,
`2026-08-z6-vintage-lookup/` and `2026-08-property-outcomes/`. Every finding's
current state is in `2026-08-second-audit/STATUS.md`.