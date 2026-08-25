Done. Two commits, 8 tests, all gates green.

## Phase 1 findings

No frontend test tooling of any kind (frontend/package.json:10-17,29-45); Vite 5.3 + React 18.3 + TS 5.4 -> Vitest; the only MapLibre-touching files are CompareView.tsx:11,14, MapView.tsx:16,19, utils/applyImageryLayer.ts:9 -- none of the four targets; and zero captured fixtures existed anywhere in the repo, so I brought up the local stack.

## Fixtures

All real captures from `docker compose` against the live Census API and Denver/Adams county portals, each with a provenance header. Two were lucky finds in the persisted dev volume:

- timeline-property-failed.ts -- a genuine Denver portal outage recorded as `property: failed`, error "All Denver County property queries failed" -- the exact message 256ed32 introduced.
- timeline-property-complete-zero.ts -- Adams County parcel, `property: complete, items_found: 0`.

For the empty-payload pair I geocoded a fresh address (1600 Glenarm Pl) and captured demographics/events before the census task landed, since no parcel in the DB has zero census snapshots -- the header records that capture timing.

## Test results

| Test | Result | Revert-and-confirm |
|---|---|---|
| HousingChart -- ACS years plot | pass | -- |
| HousingChart -- decennial years plot (it.fails, H1) | fails as expected | -- |
| DemographicsPanel -- complete+zero -> no-records state | pass | fails pre-256ed32 |
| DemographicsPanel -- property failed -> retry state | pass | fails pre-256ed32 |
| ParcelInfo -- failed source surfaces issue row | pass | fails pre-256ed32 |
| ParcelInfo -- complete+zero shows no issue row | pass | still passes pre-fix |
| useAddressAutocomplete -- 5 keystrokes -> 1 fetch | pass | -- |
| useAddressAutocomplete -- below min length -> 0 fetches | pass | -- |

Revert procedure: `git show 256ed32 -- frontend/` -> `git apply -R` -> run -> `git apply` to restore; component diff verified empty afterward. 3 of 4 M11 assertions fail against pre-fix code. The fourth still passes because pre-fix the zero case also rendered nothing -- it's a guard against a future over-correction, not a discriminator on its own. Worth knowing before anyone reads it as proof.

## Fixture/type disagreement (1, not fixed)

backend/app/schemas/imagery.py:23-24 declares started_at and completed_at on the task schema and the API returns both. frontend/src/types/index.ts:64-69 (TimelineRequestTask) declares neither. Found by assigning the raw payloads to their types under tsc -- 10 excess-property errors. The frontend type is a silent subset of the contract; harmless today, but it means those fields can't be used without a type edit, and nothing flags the drift.

## MapLibre mock

None needed. Two smaller mocks were required: vi.mock('recharts') replacing only ResponsiveContainer (jsdom parents are always 0x0), and ResizeObserver/matchMedia stubs in setup.

## Follow-ups

- L8 second half -- the clear-before-resolve race (SearchInput.tsx:35,44,57,112). Needs a SearchInput render test with a deferred geocode promise; deferred per brief.
- Recharts parks a hidden measurement span on document.body -- it survives cleanup() and produces phantom getByText matches for the last-measured string. Cost me a debugging cycle; any future chart test should scope queries to `container`. Noted in HousingChart.test.tsx.
- Task timestamps may not describe the recorded outcome. The failed-property row's error_message can only have been written by 256ed32 (2026-08-03), yet its started_at/completed_at read 2026-03-26 and the parent request's updated_at reads 2026-05-23. Most likely a backfill updated status/error in place without refreshing the timestamps. I did not verify this in the backend code -- it's local dev data and outside this pass's scope, but if the same path runs in prod, those timestamps lie.
- CI job is non-blocking twice over: continue-on-error: true AND absent from every deploy job's needs (verified by parsing the YAML).

## Draft STATUS.md lines -- "Notes for future readers" (not applied, per brief)

- **A frontend test harness exists as of 1a8bb3c (2026-08-24).** Vitest +
  Testing Library + jsdom, run with `npm test` in `frontend/`. CI runs it via
  the `test-frontend` job, deliberately non-blocking (`continue-on-error`, and
  no deploy job depends on it). Fixtures under `frontend/src/test/fixtures/`
  are real captured API payloads with provenance headers, not objects built
  from the TypeScript types -- see DEVELOPMENT.md on what hand-built input cost
  the backend suite.
- **One frontend test is expected to fail, on purpose.**
  `HousingChart.test.tsx` asserts via `it.fails` that a decennial year with a
  housing unit total appears in the chart. It does not, which is H1's open
  decennial half. The captured Stapleton fixture shows the real shape: 2010
  and 2020 carry `total_housing_units` (1,773 and 2,642) with a null tenure
  split. When H1 is fixed the assertion starts passing and `it.fails` reports
  it as a failure -- that is the signal to delete `.fails`, not to weaken the
  assertion.
- **`TimelineRequestTask` (frontend) omits `started_at` and `completed_at`,**
  which `backend/app/schemas/imagery.py:23-24` declares and the API returns.
  Unfixed as of 7a273fd; found while type-checking fixtures against the types.

One note on the record: per CLAUDE.md a change isn't complete until STATUS.md reflects it, but the brief says not to edit it. I followed the brief -- STATUS.md is currently stale with respect to both commits, and the drafts above are what it needs.
