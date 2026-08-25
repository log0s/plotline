# Frontend test harness and schema-drift pass — 2026-08-24

Six reports. The first four were produced in order over one day; the fifth
(L8's trace) and sixth (L8's fix) followed. They are **frozen records**: copied
verbatim from the working reports, never edited. Annotate with dated additions if they need correction;
do not rewrite them.

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
| `3c60133` | `docs: archive the frontend-test pass, record the /featured fallback` — created this directory; added the `/featured` placeholder entry to STATUS.md |
| `07b55e0` | `test(frontend): pin the L8 clear-before-resolve race` — added report `05-…`, `SearchInput.test.tsx`, two captured error fixtures |
| `1e2fb99` | `ci(frontend): make test-frontend blocking as a PR signal` |
| *(this commit)* | `fix(frontend): clear the search box only after the geocode settles` — adds report `06-…`, `SearchBar.test.tsx`; fixes L8's clear-before-resolve half |

All seven earlier commits verified as ancestors of HEAD at the time each line
was written. A commit cannot cite its own hash; find this one with
`git log --diff-filter=A -- docs/audits/2026-08-frontend-tests/06-l8-fix-report.md`.

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
| [`05-l8-clear-before-resolve-report.md`](05-l8-clear-before-resolve-report.md) | L8's second half: the traced submit→settle sequence, why the clear fires no empty-string autocomplete, the three user-visible outcomes, two captured error bodies (422 and a genuine 502), five tests of which three are `it.fails`, the discarded fix sketch, and the two options for making the frontend suite actually gate a Cloudflare Pages deploy. L8 remains Open at the time of writing; annotated afterwards where `06-…` answered its two open items. |
| [`06-l8-fix-report.md`](06-l8-fix-report.md) | L8's fix: the scope check that answered whether `SearchBar` shares the shape (it does not), the deferred clear and why its rejection handler is empty, delete-the-fix runs for both components, the three `.fails` markers converted to guards, and the jsdom `IntersectionObserver` stub the landing-page render needed. L8 becomes Partially resolved — the autocomplete half stays open. |

Reports 01 and 02 are plain ASCII; 03, 04, 05 and 06 are UTF-8. All were checked
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
- `/featured` failure rendering as a healthy landing page (added by `3c60133`;
  M11's shape on the flagship page, unfixed by instruction)

From `05-…` (`07b55e0`), under the **L8** row and the harness note:

- L8 stays Open, with regression tests in place and expected to fail until fixed
- that a gating CI will block L8's *own* fix until the `.fails` markers are
  removed, and that this is intended
- the two options for making the frontend suite gate a Pages deploy, and why
  blocking `test-frontend` in `deploy.yml` alone constrains nothing

From `06-…` (this commit), under the **L8** row, the harness note and the
gating note:

- L8 moves to Partially resolved: the clear-before-resolve half is fixed, the
  autocomplete half (150ms debounce, swallowed 429) is still open
- `SearchBar` is **not affected, guarded by test** — the question `05-…` left
  open, now answered in code rather than prose
- the harness is 17 tests, and only one `it.fails` remains (H1's decennial half)
- the gating note's prediction recorded as **confirmed**, with the
  delete-the-fix numbers that show the three tests bite on the real defect
