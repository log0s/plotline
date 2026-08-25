# Frontend test harness and schema-drift pass — 2026-08-24

Four reports, produced in order over one day. They are **frozen records**:
copied verbatim from the working reports, never edited. Annotate with dated
additions if they need correction; do not rewrite them.

The living ledger for everything here is
[`../2026-08-second-audit/STATUS.md`](../2026-08-second-audit/STATUS.md). These
documents are the working detail behind rows and notes in it — read STATUS.md
first for what is true now, and come here for how it was established.

## Commits

| Commit | Subject |
|---|---|
| `1a8bb3c` | `test(frontend): add Vitest + Testing Library harness` |
| `7a273fd` | `test(frontend): cover H1, M11 and the autocomplete debounce` |
| `b4c3a2b` | `fix(test): correct a fixture pairing that never existed, record the harness` |
| `6629db1` | `fix(frontend): close the measured schema drift, lock it with a test` |
| *(this commit)* | creates this directory; adds the `/featured` placeholder entry to STATUS.md |

All four verified as ancestors of HEAD at the time this was written. This
commit cannot cite its own hash; find it with
`git log --diff-filter=A -- docs/audits/2026-08-frontend-tests/README.md`.

`256ed32` (2026-08-03, "treat a county-portal outage as a failed property
task") is referenced throughout as the M11 fix the tests were written against.
It predates this pass.

## The reports

| File | Covers |
|---|---|
| [`01-harness-report.md`](01-harness-report.md) | Choosing and standing up the harness; capturing the first fixtures from the local stack; the initial eight tests and their revert-and-confirm results against pre-`256ed32` code. Commits `1a8bb3c`, `7a273fd`. |
| [`02-fixture-ledger-timestamp-report.md`](02-fixture-ledger-timestamp-report.md) | Three items: a captured fixture that turned out to describe a state that never existed and its correction; the STATUS.md ledger entries; and a code read of every writer of `timeline_request_tasks.status`/`error_message` against an anomalous row. Commit `b4c3a2b`. |
| [`03-schema-drift-phase1-report.md`](03-schema-drift-phase1-report.md) | Measure-only pass: every fixture assigned to its frontend type under `tsc`, every Pydantic response schema diffed against its TypeScript counterpart, the reconciliation of the two, and a fix-policy recommendation. No code changed. |
| [`04-schema-drift-phase2-report.md`](04-schema-drift-phase2-report.md) | The fix, the contract test and its delete-and-confirm outcomes, two new captured fixtures, measured coverage, and an assessment of whether the codebase would survive a switch to `openapi-typescript`. Commit `6629db1`. |

Reports 01 and 02 are plain ASCII; 03 and 04 are UTF-8. All four were checked
for CP437 artefacts when copied here — zero found.

## What landed in STATUS.md

All in [`../2026-08-second-audit/STATUS.md`](../2026-08-second-audit/STATUS.md).

Under **Notes for future readers** (from `b4c3a2b`, revised by `6629db1`):

- the harness note and its blocking condition
- the corrected fixture pairing, and the rule against hand-editing fixtures
- the intentionally-failing H1 test (`it.fails`) and what a pass would mean
- the Recharts text-measurement span trap
- the measured schema-drift size and the fix
- the no-backend-finding result
- which endpoints the contract test locks and which four it does not
- why optional-vs-required is invisible to that test, with `supported_counties`
  as the worked example
- why the check needs two mechanisms rather than plain assignment
- the two `PropertyEventType` members no backend path produces
- the SAS redaction in `imagery-stapleton.ts`, reconciled against the
  never-hand-edit rule

Under **To investigate**:

- the anomalous task row whose error message predates its own timestamps
  (from `02-…`)
- `/featured` failure rendering as a healthy landing page (added by this
  commit; M11's shape on the flagship page, unfixed by instruction)
