# Edit pass — `2026-08-migration-lock.md`, 2026-08-26

Report for the edit pass against the primary record (GATE-STOP.md and its two
addenda, `dd99cee`, `edc13db`, `alembic/env.py` at `edc13db`, STATUS.md's
M10/X1/X2/X3 rows, and the two sweep prompts). Item numbers are the prompt's.
Body is 1,798 words, three H2s, no bullets, US spelling.

## 1. Cite the gate line

**Record:** `SWEEP-PROMPT-1.md` Phase 1 line 2: "`alembic_version` on prod
reads `0011`. `timeline_task_years` exists, has the expected columns,
constraints, and indexes, and holds zero rows. Otherwise stop — a non-empty
ledger before the sweep means something already ran."

**Changed:** the opening now quotes the line (eliding the
columns/constraints/indexes clause with an ellipsis), and the "what caught it"
section quotes the trailing rationale clause verbatim and attributes it to
`SWEEP-PROMPT-1.md` Phase 1 line 2. The "my reading" hedge is gone from
`facts_to_verify`.

**Difference noted:** GATE-STOP.md §1's gate table condenses the same line to
"`alembic_version` = `0011`; `timeline_task_years` exists, empty" and drops
the rationale clause entirely. The prompt is the source; the table is a
paraphrase. Recorded in `facts_to_verify`.

## 2. The 00:52Z boots and the deploy SHA

**Record:** GATE-STOP.md §1.1 has both apps at
`GH_SHA=ce307e352bfcbf0b81be9f444b4dc25fdecad24e` with health agreeing, and
the second addendum labels the 00:52Z pair "Boot A, `ce307e35…`, ~00:52Z
(pre-fix code)". `SWEEP-PROMPT-1.md` is written against the same SHA.
Confirmed.

**Changed:** the SHA is named (short form) at the log block, and again where
the post states what that deploy shipped against a missing table.

## 3. X2 stated

**Record:** GATE-STOP.md §5 — `timeline.py:1374`, `:1383`,
`imagery.py:287-288`, `year_ledger.py:195-217`, `timeline.py:1577-1601`; §9
bounds the "no requests" evidence to *created* requests, with 0 `queued` / 0
`processing` closing the in-flight gap.

**Changed:** one paragraph added at the end of the mechanism section with
those citations, the `UndefinedTable` → `failed` chain, §9's bound stated as a
bound ("nothing arrived, not that nothing could have"), and the sweep's 184
requests as what would have exercised it.

## 4. The two-direction reproduction

**Record:** GATE-STOP.md §4.1 (real `alembic upgrade head` at `0010` prints
the production transcript, `alembic current` stays `0010`) and §4.2 (the same
structure with alembic's own `MigrationContext`: DDL persists with the lock
statement removed, discarded with it present).

**Changed:** both directions summarized in one sentence citing §4.1 and §4.2,
placed where the post claims the DDL actually ran.

## 5. The lock "working" — contradiction fixed

**Record:** `825d69b7e46618` logs `Migrations complete.` at 00:52:28Z;
`48e0de9a713918` logs `Running database migrations...` at 00:52:40Z. The two
boots never overlapped, so nothing was ever contended.

**Changed:** the draft said the 00:52Z pair showed the lock "working exactly
as designed and serializing two boots." That is removed. The post now says the
second boot re-ran the upgrade because the version bump had been rolled back,
and states explicitly that the boots did not overlap. "The outcome M10 wanted"
is reserved for 01:29Z — and even there the post says only that the second
boot found committed state and did nothing, because no log line shows it
waiting on the lock (at 01:29Z the first machine's head check is 01:29:41Z and
the second pulls its image at 01:29:51Z). GATE-STOP.md §10 anomaly 1 and the
X1/M10 rows read this as the lock serializing; that disagreement is recorded
in `facts_to_verify`.

## 6. Unflagged numbers

- **"Seven minutes"** — kept. GATE-STOP.md §1.3 gives the capture clock as
  `2026-08-26 00:59:39 UTC`; the deploy's migration lines run 00:52:22Z to
  00:52:45Z. Both timestamps are now in the sentence.
- **"Eighteen seconds"** — kept, and the post now says which lines it spans:
  the two `Running upgrade` lines (00:52:27Z, 00:52:45Z). The twelve-second
  gap between the first machine's `Migrations complete.` and the second's
  `Running database migrations...` is stated alongside it.
- **"Three weeks"** — kept as prose in one place; the precise figure is
  twenty-two days (see item 10).
- **"Six lines"** — wrong and removed. The block is `env.py:96-109` at
  `ce307e35`, fourteen lines, which is what the post now says. STATUS.md's X1
  row cites the same range.
- **"NullPool"** — confirmed at `edc13db`: `engine_from_config(...,
  poolclass=pool.NullPool)` at `env.py:138`, and `_verify_at_head`'s docstring
  says why it matters. Kept.

## 7. Scope of "the window the bug was live"

**Record:** GATE-STOP.md §9 and the second addendum — deploy boundary
`2026-08-26T00:52Z`, casualty check `01:36Z`, zero `timeline_requests` created
in between, 0 `queued`, 0 `processing`.

**Changed:** "the entire window the bug was live" is now "between the 00:52Z
deploy and the 01:36Z check, which spans the whole interval in which the
recorder ran without its table."

## 8. The release-command rationale

**Record:** `dd99cee`'s message: "Not release_command: the worker is a separate
Fly app deployed by a parallel CI job, so a release command on the API alone
would not close the window it appears to close." Attribution confirmed.

**Changed:** the post now says the commit message is where that reasoning is,
rather than asserting it unsourced.

## 9. `Running upgrade` is not evidence

**Record:** GATE-STOP.md §3 step 4 says alembic "logs `Running upgrade 0010 ->
0011` because it genuinely ran it," which overstates what the log line proves —
alembic prints it before executing the step.

**Changed:** the post says the line is *not* the evidence, and points at the
reproduction (§4.2's lock-removed direction) as what shows the DDL executing.

## 10. Dates normalized to UTC

**Record:** every log timestamp is UTC; every commit is authored `-0600`.
`dd99cee` = 2026-08-03T17:56:19-06:00 = **2026-08-04T00:56Z**. The gate's
capture clock is 2026-08-26T00:59:39Z.

**Changed:** one parenthetical in the opening states the convention. `dd99cee`
now "landed on 4 August," and the interval is **twenty-two days**, not 23.
STATUS.md's M10 re-mark says 23 days because it differences the local calendar
dates; that is recorded in `facts_to_verify` rather than silently followed.

## 11. 488 vs 525 — reconciled, and the record is wrong

**Record:** GATE-STOP.md §6 and STATUS.md's X3 row both say "the 488-test
suite that ships with `0011`." `edc13db`'s message and GATE-STOP.md §13 say 3
added, 525 passing, from 522. `REPORT.md` §6 says "**522 passed, 0 failed**
… up from 488 at `fa3ea89`."

**Measured:** `pytest --collect-only -q` in a throwaway worktree at
`ce307e35` (the SHA that shipped `0011` to production) collects **522**; at
`HEAD` (`edc13db` plus docs commits) it collects **525**. So 488 is the
pre-ledger count at `fa3ea89`, and §6 and X3 carry it forward by mistake.

**Changed:** the post says 522 passed on the commit that shipped `0011`, and
525 after `edc13db`. **Not fixed:** STATUS.md's X3 row still says 488. That is
a live error in the living ledger, and this batch was scoped to the post and
the two prompts, so it is reported here rather than edited. GATE-STOP.md §6 is
frozen and would take a dated annotation, not an edit.

## 12. Which sweep prompt

**Changed:** every reference is `SWEEP-PROMPT-1.md` by name — the opening, the
gate-line quote, and the provenance paragraph's "a sweep prompt whose job was
to say what would make me stop." `SWEEP-PROMPT-2` is not cited in the body at
all: a clause naming it as the re-issue was written and then cut to hold the
word budget, and since nothing in the post depends on it, it stayed cut.

## 13. Spelling

"authorisation" → "authorization", "behaviour" → "behavior". No other British
forms found.

## Updated `facts_to_verify`

1. **Test count — resolved, and the record is wrong.** 488 is the pre-ledger
   count at `fa3ea89`; the suite is 522 at `ce307e35` and 525 at `edc13db`.
   STATUS.md's X3 row needs a correction annotation this batch did not make.
2. **`env.py` line ranges — resolved against the file at `edc13db`.**
   GATE-STOP.md §12 is right (`_verify_at_head` at `:56-95`, the transaction
   block at `:141-191`); the X1 row and the commit message are both slightly
   off. The post cites only `env.py:96-109` (pre-fix, at `ce307e35`).
3. **Twenty-two days, not 23** — UTC vs local commit dates; STATUS.md's M10
   re-mark uses the local difference.
4. **The 00:52Z boots never overlapped**, so nothing was contended.
   GATE-STOP.md §10 anomaly 1 reads it as the lock failing to serialize.
   Worth reconciling with §10 before publishing.
5. **No log line proves either boot ever waited on the lock**, including at
   01:29Z. The post claims the outcome, not an observed wait; GATE-STOP.md's
   addendum and the X1 row both describe it as serialization.
6. **That no production request was lost** rests on zero `timeline_requests`
   *created* between 00:52Z and 01:36Z, plus 0 `queued` / 0 `processing`;
   GATE-STOP.md §9 states the bound.
7. **The gate quote** elides one clause with an ellipsis; GATE-STOP.md §1's
   table paraphrases the same line and drops the rationale.
8. **SQLAlchemy version** — §3 says production 2.0.49, §15 says the local
   reproduction ran 2.0.50. The post names neither.
