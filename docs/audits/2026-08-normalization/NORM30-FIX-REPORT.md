# NORM-30 — the repo fix and the rule

**2026-08-29. Local only. No production access was used or attempted.**

NORM-30 is the finding that `SET SESSION CHARACTERISTICS AS TRANSACTION READ
ONLY` — and its equivalents, `SET default_transaction_read_only = on` committed,
and psycopg2's `conn.set_session(readonly=True)` — does not make the prober
read-only against Neon's transaction-mode pooler. It makes a *shared production
backend* read-only for whoever borrows it next. It killed this arc's own
authorized write on batch 2 of `enrich_snapshot_scenes.py --execute`
(`SNAPSHOT-ENRICH-PROD-REPORT-3.md` §6b).

The leaked flag was cleared under owner authorization. The **code site** was
left open, and it is why the ADR step-4 cooling reading was deferred rather than
taken: running the instrument would have re-poisoned the pool minutes after the
clear. This session closes the code site and codifies the rule. **The cooling
reading is unblocked pending deploy** — the fix is committed, not running.

Commits: `71eb335` (script + tests), `0c56d5d` (CLAUDE.md), and this report.

---

## 1. The choice: transaction-scoped, not dropped

Requirement 1 offered two ends: drop the `SET` entirely (the script issues only
`SELECT`s, so it is genuinely read-only by construction), or keep a read-only
guarantee in the transaction-scoped form. **Transaction-scoped was chosen.**

`scripts/snapshot_reads.py:69` and `:150-155`:

```python
READ_ONLY_STATEMENT = "SET TRANSACTION READ ONLY"
...
with SessionLocal() as db:
    db.execute(sa_text(READ_ONLY_STATEMENT))
    now = read_counters(db)
    db.rollback()
```

Was, at `snapshot_reads.py:138-139` before the fix:

```python
db.execute(sa_text("SET default_transaction_read_only = on"))
db.commit()
```

Three reasons for keeping a guarantee rather than dropping to convention:

1. **`SET TRANSACTION` provably cannot leak.** It applies to the current
   transaction and is gone at COMMIT — which is the exact instant a
   transaction-mode pooler returns the backend to the shared pool. The failure
   mode NORM-30 describes has no window here. This is the same reasoning
   `app/db.py`'s `check_db_connection` already documents for its `SET LOCAL
   statement_timeout`, so the repo now has one consistent story rather than two.
2. **"SELECT-only by inspection" is a property of today's source.** A future
   edit that adds a write to this script would silently lose the guarantee; the
   guarantee is what a reviewer would otherwise have to re-derive.
3. **It is testable.** A dropped `SET` leaves nothing to assert behaviourally —
   only the absence of a line. Keeping the scoped form lets the test show the
   write actually failing *and* the session clean afterwards, which is the pair
   of facts the finding is about.

The `db.commit()` is also gone. Committing was not incidental to the bug: it is
what pushed the setting past the transaction boundary and onto the pooled
backend. The rollback at the end is retained and is now the only transaction
terminator.

The statement is a **module constant** rather than an inline literal so the
Postgres test executes the real artifact. A test that re-typed the statement
would prove a copy, not the script.

---

## 2. Grep for the shape

Searched the whole repo for `set_session`, `SET SESSION`,
`default_transaction_read_only`, and `SESSION CHARACTERISTICS`.

### 2a. Code sites: one, and it is fixed

| Site | Disposition |
| --- | --- |
| `scripts/snapshot_reads.py:139` | **Fixed** — `71eb335`. |

That is the complete code population. `scripts/compare_read_paths.py`, which
`STATUS.md`'s NORM-1 row records as using `default_transaction_read_only`, **no
longer exists** — it was deleted at the step-3 read cutover, so it is a
historical reference and not a live site. No `app/` module, no test, and no
other script issues a session-level `SET`; the two guards in §3 now assert that
continuously rather than leaving it as a one-time grep.

### 2b. Docs that record the old pattern — frozen, listed here

These are frozen audit records under the "record moves with the code" rule and
are **left unedited**. They are listed because two of them quote *runnable
commands*, and a future session copy-pasting from the record would reintroduce
the defect. **Nothing in this list is a runbook to follow.**

**Copy-paste hazards — quoted as runnable SQL:**

| File:line | What it quotes |
| --- | --- |
| `docs/audits/2026-08-ops-audit/FINDINGS.md:622` | Appendix B "Access method", in a ```sql fence: `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY; SET statement_timeout = '60s';` |
| `docs/audits/2026-08-security-audit/REMEDIATION-1.md:150` | The same two statements inline, citing Appendix B as the method to reuse |

Note that **both also set `statement_timeout` at session level**, which is the
same leak class as the read-only flag and was not part of NORM-30's original
scope: a leaked 60-second timeout on a shared backend would truncate unrelated
production queries. `SET LOCAL` is the correct form and is what `app/db.py`
already uses. No live code has this defect — it exists only in these two
records — but the CLAUDE.md rule in §4 is written to cover `SET` of **any** GUC
rather than the read-only flag alone, for exactly this reason.

**Historical narrative — describe what a past session did, not what to do:**

| File | Lines |
| --- | --- |
| `docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT-3.md` | 14, 112, 300, 307, 454, 463 (the finding's own write-up) |
| `docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT-2.md` | 15, 112, 467 |
| `docs/audits/2026-08-normalization/SNAPSHOT-ENRICH-PROD-REPORT.md` | 254 |
| `docs/audits/2026-08-normalization/STEP3-PROD-REPORT.md` | 25, 109, 445 |
| `docs/audits/2026-08-normalization/STEP3-REPORT.md` | 197 |
| `docs/audits/2026-08-normalization/STEP2-PROD-REPORT.md` | 23 |
| `docs/audits/2026-08-normalization/STEP1-PROD-REPORT.md` | 19 |
| `docs/audits/2026-08-normalization/ENRICH-PROD-REPORT.md` | 35 |
| `docs/audits/2026-08-normalization/ENRICH-PROD-REPORT-2.md` | 17 |
| `docs/audits/2026-08-normalization/PREDICTION-SNAPSHOT-ENRICH.md` | 518, 1174 |
| `docs/audits/2026-08-normalization/PREDICTION-STEP2-PROD.md` | 39 |
| `docs/audits/2026-08-normalization/PREDICTION-STEP1.md` | 248 |
| `docs/audits/2026-08-security-audit/FINDINGS.md` | 240 |
| `docs/audits/2026-08-second-audit/STATUS.md` | 671, 700 (NORM-1 and NORM-30 rows) |

`STEP3-REPORT.md:197` deserves one word of care: it says the comparison harness
"sets `default_transaction_read_only = on`" and calls it "read-only, and
provably". That claim was **correct about the harness and false about the
backend** — it is the sentence NORM-30 inverts. The harness is deleted, so
there is nothing to fix; the row above exists so nobody reads it as a pattern to
copy.

There is **no runbook file in the repo** that prescribes the pattern. The
prescription lived in session prompts, which is why the fix for that half is
CLAUDE.md and not an edit to a doc.

---

## 3. Tests

`backend/tests/test_pooler_safe_reads.py`, four tests. The property has two
halves and neither implies the other.

**Textual (three tests, run everywhere).** No script and no `app/` module issues
a session-level `SET`. A grep-shaped assertion is legitimate here and is the
same class as `test_script_logging.py`'s root-handler guard: the property *is*
textual — which statement the source sends — and a behavioural version would
need a transaction pooler in the test rig to observe the leak at all, which the
local stack does not have.

The regex admits `SET LOCAL`, `SET TRANSACTION` and `SET CONSTRAINTS`, and its
bare-GUC branch is anchored to an opening quote so it means "this SQL string
*starts with* SET". **Unanchored it fired on every `UPDATE … SET col = :v` in
the repo** — four scripts and two services — which is how it first ran here; the
anchor is commented at the site so the next person does not loosen it back.
`test_the_regex_would_catch_the_statement_that_caused_norm30` pins that with a
fixture containing all three original forms plus the two allowed ones, asserting
exactly three catches, so a regex that quietly stops matching fails rather than
passes vacuously.

**Behavioural (one test, needs Postgres).** Against a real server, on **one
connection**, so the second half observes leakage rather than a fresh session
that never carried the flag:

* inside the transaction: `transaction_read_only` is `on`, and a `CREATE TEMP
  TABLE` raises `read-only transaction`;
* in the next transaction on that same connection: `transaction_read_only` and
  `default_transaction_read_only` are both `off`, and the write succeeds.

SQLite cannot express either half. Per NORM-29 the limit is stated rather than
faked: the test skips without `TEST_POSTGRES_URL`, and
`test_the_postgres_half_is_not_silently_skipped` **fails rather than skips**
when `CI` is set, matching `test_migrations_postgres.py`'s guard. CI sets the
variable for the whole backend test step (`.github/workflows/deploy.yml:171`),
so the behavioural half runs there.

**What this test still cannot see.** The local stack connects to Postgres
directly. It proves the *scoping* — the setting does not survive the transaction
— which is the property that makes the leak impossible. It does not reproduce
the pooler hand-off itself, so it would not catch a leak arriving by some other
mechanism. That is a real gap and is why the textual guard is not redundant.

**Delete-the-fix, performed.** Restoring the original two lines —
`READ_ONLY_STATEMENT = "SET default_transaction_read_only = on"` plus the
`db.commit()` — makes **two** tests fail:

* `test_no_script_issues_a_session_level_set` — the statement is caught;
* `test_transaction_read_only_blocks_a_write_and_does_not_survive_the_transaction`
  — `SHOW transaction_read_only` reads `off` inside the transaction, because
  `default_transaction_read_only` governs *subsequent* transactions, not the
  current one. The mutation therefore fails on the first assertion; the
  session-cleanliness assertion two lines later would catch it as well.

The mutation was applied and reverted; `scripts/snapshot_reads.py` is back to
`71eb335`'s content, verified by re-running the suite green.

**Suite: 750 passed / 3 skipped** (`docker compose exec -T api`, with
`TEST_POSTGRES_URL` set — 749 before this batch). `ruff check`, `ruff format
--check` and `mypy` clean over `app/` and `tests/`.

---

## 4. The rule

`CLAUDE.md`, production access, immediately after the SHA-pinning rule:

> Production connections go through a transaction-mode pooler, so **session-level
> `SET` of any kind is forbidden** — `SET SESSION …`, `SET <guc>` outside a
> transaction, a committed `SET`, or psycopg2's `set_session()`. The setting
> outlives the connection's lease and lands on a shared backend, where it applies
> to unrelated clients: a read-only probe done this way made production read-only
> and killed an authorized write mid-run (NORM-30). Read-only intent is expressed
> **per transaction** — `BEGIN READ ONLY` / `SET TRANSACTION READ ONLY` as the
> transaction's first statement, or `SET LOCAL` for other GUCs — and the
> `UPDATE … WHERE false` proof runs *inside that same transaction*, where it
> proves the thing that is actually scoped.

Two deliberate widenings beyond the finding as written. It covers **any GUC**,
not the read-only flag, because §2b found `statement_timeout` set the same way
in the same quoted method. And it relocates the `UPDATE … WHERE false` probe
rather than banning it: the probe was never wrong, it was in the wrong scope —
it proved a property of a transaction that had already ended. Inside the
read-only transaction it proves exactly what it claims.

---

## 5. One discrepancy with this session's prompt

The prompt asked STATUS.md to record the production pool "verified clean
19:59:16Z (cite the report)". **That timestamp does not appear in any committed
artifact.** `SNAPSHOT-ENRICH-PROD-REPORT-3.md` records the clear at 19:29Z and
three verifications: 0 of 8 read-only from both apps at **19:30:49Z** and
**19:30:57Z** (§7), and the post-run probe's own session state at **19:52:27Z**
reading `default_ro: off` (§6d). This session has no production access and
cannot take a fourth reading. The STATUS.md row therefore cites the three
timestamps that are in the record, and 19:59:16Z is not asserted anywhere.

---

## 6. State after this batch

* `scripts/snapshot_reads.py` — **fixed**, `71eb335`. Committed, **not
  deployed**; a mitigation that is not running is not mitigating.
* Code population — **complete**, one site, guarded against regrowth.
* CLAUDE.md — **rule codified**, `0c56d5d`.
* Frozen docs — **listed, unedited**; two carry copy-paste hazards, named in §2b.
* Step-4 cooling reading — **unblocked pending deploy.** It needs the fixed
  script on the machine. Until the deploy, running
  `scripts/snapshot_reads.py` in production still executes the old committed
  session GUC and would re-poison the pool.
