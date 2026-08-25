# L8 clear-before-resolve — regression tests written before the fix

2026-08-24. Working detail behind the L8 row and the harness note in
[`../2026-08-second-audit/STATUS.md`](../2026-08-second-audit/STATUS.md).
Frozen record: annotate with dated additions, do not rewrite.

Scope: the second half of second-audit finding **L8**. The debounce half
(`useAddressAutocomplete.ts:12`) already had a hook test from `7a273fd`. This
pass covers the clear-before-resolve half at
`SearchInput.tsx:35,44,57,112`. **L8 was not fixed here** — the tests are
written against the target behaviour and are expected to fail until it is.

---

## 1. The finding is not stale

STATUS.md's line numbers date from 2026-08-03. The last commit touching
`SearchInput.tsx` is `62fd34d` (2026-06-16, "preserve house number when
selecting autocomplete suggestion"), which predates them. Lines 35, 44, 57 and
112 in the working tree still hold exactly the four `setValue("")` calls the
finding cites. Nothing has moved.

## 2. Phase 1 — the sequence from submit to settle

| # | Site | What happens |
|---|---|---|
| 1 | `SearchInput.tsx:79` | `<form onSubmit={handleSubmit}>` |
| 2 | `SearchInput.tsx:42` | `e.preventDefault()` |
| 3a | `:43–49` | **Branch A** — exact-search row highlighted: `setValue("")` **`:44`** → `clear()` `:45` → `setShowSuggestions(false)` `:46` → `onSearch(typedTrimmed)` `:47` |
| 3b | `:50–55` → `:32` | **Branch B** — a suggestion highlighted → `handleSelect`: reads `value.trim()` `:33`, picks the address `:34`, `setValue("")` **`:35`**, `setShowSuggestions(false)` `:36`, `clear()` `:37`, `onSearch(address, {lat, lon})` `:38` |
| 3c | `:56–61` | **Branch C** — plain typed text ≥ 5 chars: `setValue("")` **`:57`** → `clear()` `:58` → `setShowSuggestions(false)` `:59` → `onSearch(typedTrimmed)` `:60` |
| 3d | `:110–116` | Mouse path on the exact-search button — the same four calls as Branch A, `setValue("")` at **`:112`** |
| 4 | `ParcelInfo.tsx:123–128` | `onSearch` is `handleSearch`, which calls `geocodeMutation.mutate({address, navigate, ...coords})` `:127`. `mutate` is fire-and-forget: it returns `void`, never throws, and is never awaited |
| 5 | `queries.ts:144–146` | mutationFn → `geocodeAddress()` → `api/geocode.ts:12` `apiFetch` POST `/api/v1/geocode` |
| 6 | `client.ts:38–46` | on `!response.ok`, throws `ApiRequestError(status, detail)`; `detail` is lifted from the JSON body by `extractErrorDetail` `:15–36` |
| 7 (ok) | `queries.ts:147–156` | `onSuccess` primes the `["parcel", id]` cache and calls `navigate("/explore/:id")` |
| 8 (err) | `ParcelInfo.tsx:137–138` | `isLoading = isPending`; `error = geocodeMutation.error?.message ?? null`, both passed down as props |
| 9 (err) | `SearchInput.tsx:102, 206–215` | red border on the input; the message in the `AnimatePresence` paragraph |

**The race, precisely.** In all four branches `setValue("")` runs
*synchronously before* `onSearch`, in the same React batch that starts the
request. No path restores `value`. SearchInput never holds the promise — it
receives only `isLoading` and `error` as props — so as currently designed there
is nowhere for it to put the text back.

## 3. What the clear does to the autocomplete hook

**It fires no request for the empty string, and it aborts nothing.**

- `setQuery` is called only from `onChange` (`SearchInput.tsx:87`). `setValue("")`
  does not touch the hook's `query`, so the effect at
  `useAddressAutocomplete.ts:29` does not re-run. There is no fetch for `""`.
- `clear()` (`:22–27`) empties `suggestions`, clears the pending debounce timer,
  and increments `requestIdRef`. An in-flight suggestion response is therefore
  **discarded on arrival, not aborted** — `fetchAutocompleteSuggestions`
  (`api/geocode.ts:30`) takes no `AbortSignal`, so the HTTP request still
  completes.

**Where the self-DoS half meets the race half.** The hook's `query` is left
holding the old address while the box reads empty. Recovery from a failed
geocode therefore requires retyping the whole address, which replays the full
debounced keystroke burst — one Photon-backed autocomplete request per 150 ms
pause, for an address the user had already typed once. The self-DoS is the
*recovery cost* of the race, not an independent defect.

## 4. What the user sees today

| Case | Branch | Rendered |
|---|---|---|
| **(a) 3 s, succeeds** | `queries.ts:147` | Input empty and `disabled` (`SearchInput.tsx:96`) for the full 3 s, button reads `"..."` (`:202`), then navigation. The typed address is gone for the whole window; a user who spots a typo mid-flight has nothing to correct. |
| **(b) 502** | `geocode.py:241–245` | `"The Census Geocoder API is currently unavailable. Please try again later."` — red border plus red paragraph. Input empty. |
| **(c) 422 no match** | `geocode.py:246–251` | `"Could not match this address. Please check the spelling and include city and state."` — identical rendering. Input empty. |

**(b) and (c) are not distinguished by the UI.** `ApiRequestError` carries
`status` (`client.ts:6`) but no frontend code reads it; both reach the same
`:102` / `:206` render through `error?.message`. The same is true of 429 and
503, and of the 30 s client timeout (`client.ts:91`, `"Request timed out"`).
The only difference between the three is the sentence. Case (c) is the worst of
them: the message says "check the spelling" against a box with nothing in it.

## 5. Fixtures — both error bodies are real captures

Both were produced from the local `docker compose` stack at backend SHA
`3c60133c003af66ee07fa536ffa8380fb0b30735`, on 2026-08-24. Neither body is
hand-built, and the fixture headers record the method.

- **`geocode-error-422.ts`** — unmodified stack, `POST /api/v1/geocode` with
  `{"address":"zzzz nonexistent street qqqq, nowhere, XX 00000"}`. Returns 422
  with the `AddressNotFoundError` detail.
- **`geocode-error-502.ts`** — a real 502 *was* producible locally. The API
  container was restarted with a compose override setting
  `CENSUS_GEOCODER_URL=http://127.0.0.1:9/geocoder/geographies/onelineaddress`
  (a closed port; the setting is `config.py:57`, so pydantic-settings picks it
  up from the environment). `httpx` raises `ConnectError`, `geocoder.py` maps it
  to `GeocoderUnavailableError`, and the route returns 502. The override was
  removed and the API restored to stock config immediately after the capture.

  **Correction to the task framing:** the 502 is the **Census** geocoder, not
  Photon. Photon backs autocomplete only (`geocode.py:69`) and returns `[]` on
  any failure (`:78–80`); it can never produce a 502 on this route. Stopping
  Photon would have produced nothing.

Each fixture stores `status`, the captured `body`, and the `message` string
that `client.ts`'s `extractErrorDetail` lifts out of that body — the string the
UI actually renders. The tests do not use `message` as an input: they feed the
captured `body` through the real `handleResponse` to construct the very
`ApiRequestError` production would construct.

## 6. Mock surface

```ts
vi.mock("../api/geocode", () => ({
  geocodeAddress: vi.fn(),           // deferred: test controls resolve/reject
  getParcel: vi.fn(),                // unused here; queries.ts imports it
  fetchAutocompleteSuggestions: vi.fn(),
}));
vi.mock("../api/demographics", () => ({ getDemographics: vi.fn() }));
vi.mock("../api/events", () => ({ getPropertyEvents: vi.fn() }));
```

Mocked at the module boundary, never inside a hook. Both `useGeocodeMutation`
(via `queries.ts:15`) and `useAddressAutocomplete` (via `:9`) import from
`../api/geocode`, so replacing that one module controls the whole path while
leaving React Query, the hooks and the components untouched.

**What is rendered: the real `ParcelInfo`, by decision.** `SearchInput` takes
`onSearch`/`isLoading`/`error` as props and never touches the API module
itself, so a test could only reach the geocode by supplying its own wiring. A
local harness duplicating `ParcelInfo.tsx:106,123–128,137–138` would have made
for a tidier file but would have guarded a *copy* of the wiring; the race lives
in the seam between the component and the mutation, which is exactly what a
copy would not exercise. `ParcelInfo` is therefore rendered whole, alongside a
three-line `LocationProbe` that surfaces `useLocation().pathname` so the
success case can assert navigation. The demographics and events mocks are
inherited from `ParcelInfo.test.tsx`'s established pattern.

## 7. Tests and results

`frontend/src/components/SearchInput.test.tsx`, five tests.

| # | Test | Expected | Observed |
|---|---|---|---|
| a | `it.fails` — keeps the typed address while the geocode is pending | fail (L8) | **fails as expected.** Input reads `""` at the assertion |
| b | `it.fails` — keeps the typed address and shows the error when the geocode rejects (**502**) | fail (L8) | **fails as expected.** Error paragraph renders; input reads `""` |
| c | `it.fails` — keeps the typed address when the geocode rejects with a **422** no-match | fail (L8) | **fails as expected.** Same shape as (b) |
| d | `it` — clears the input and navigates once the geocode resolves | pass | **passes.** Input `""`, pathname `/explore/70a496c7-…`, no error |
| e | `it` — does not fire an autocomplete request for the empty string on submit | pass | **passes.** Exactly one call, with the typed address; never `""` |

Test (b) covers the 502 and (c) the 422 separately rather than the single
rejection test the task specified, because a real 502 body was capturable —
and because (c) is the case where the empty box contradicts its own error
message.

Test (e) is a passing guard, as Phase 1 predicted. Its value is directional:
the obvious wrong fix for L8 is to also reset the hook's `query`, which would
re-enter the effect with `""`; this test fails the moment that happens.

Full suite after this pass: **15 tests, 6 files, all green.** `npm run lint`
clean, `npx tsc --noEmit` clean, `prettier --check` clean.

### Two harness notes worth keeping

**Build the API error *before* entering `act()`.** The first version did
`pending.reject(await capturedApiError(fx))` inside the `act` callback.
`Response.json()` settles over several microtasks, so `act` could exit before
React had processed the rejection — the suite failed intermittently, and which
of the two rejection tests failed varied run to run. Construct the error first,
then reject inside `act`.

**Poll for a mutation error; a single `act` flush is not enough.** Even with
the ordering fixed, `expect(screen.getByText(...))` immediately after the
rejection was flaky. React Query commits mutation error state over an
indeterminate number of ticks. `await screen.findByText(...)` (and `waitFor`
for the navigation assertion) made it deterministic — five consecutive clean
runs before and after the fix sketch.

**`act(async () => { ...sync... })` trips `@typescript-eslint/require-await`.**
`ParcelInfo.test.tsx` gets away with `await act(async () => {})` only because
the rule ignores empty function bodies. Non-empty synchronous bodies are
errors, so this file routes every one through a single `actAsync(fn)` helper
whose body genuinely awaits a microtask.

## 8. The fix sketch, and its discard

The minimal shape that makes (a), (b) and (c) pass is to give `SearchInput` a
settled signal to clear on. Sketched locally: widen the prop to
`onSearch: (address, coords?) => void | Promise<unknown>`; in `ParcelInfo`,
have `handleSearch` `return geocodeMutation.mutateAsync({...})` instead of
calling `mutate`; and in each of the four clear sites, drop the eager
`setValue("")`/`clear()` and instead do
`void Promise.resolve(onSearch(...)).then(() => { setValue(""); clear(); }, () => {})`
— keeping `setShowSuggestions(false)` eager, since the dropdown should close on
submit regardless of outcome. The rejection handler is required, not optional:
`mutateAsync` rejects, and without it every failed geocode becomes an unhandled
rejection. Under this sketch all three `it.fails` tests reported *"Expect test
to fail"* — the flip — on three consecutive runs, while (d) and (e) continued to
pass, which is the evidence that (d) and (e) genuinely constrain the fix rather
than merely coexisting with it. Open questions the sketch does not settle and
the fix pass must: whether the input should stay `disabled` while pending (it
currently does, so the retained text would be visible but uneditable, which may
be worse than useless), whether a rejection should also restore the suggestion
dropdown, and whether `SearchBar.tsx` on the landing page has the same
structure and so belongs in the same change.

The sketch was reverted with `git checkout --` on both files. `git diff` is
empty; `git status --porcelain` shows only the three added files (the test and
the two fixtures) plus this pass's documentation.

## 9. CI: making the frontend tests actually gate a Pages deploy

**Reported, not implemented.** STATUS.md's harness note says `test-frontend`
becomes blocking when this test lands or on 2026-09-30, and correctly observes
that blocking it in `deploy.yml` constrains nothing: `deploy.yml:138–139` says
the frontend auto-deploys through the Cloudflare Pages GitHub integration,
which watches the repository directly and never reads a GitHub Actions result.
Removing `continue-on-error` (`:83`) and adding `test-frontend` to a `needs:`
list changes what a red run *looks like*; it does not stop a single byte from
reaching production.

There are two ways to close that, and they are not equivalent.

**Option 1 — run the tests inside the Pages build command.** Change the Pages
project's build command from `npm run build` to something like
`npm ci && npm test && npm run build`. Cheapest possible change, entirely in
the Cloudflare dashboard, no workflow edits; a failing test fails the Pages
build and the previous deployment stays live. What it costs: the gate now lives
in dashboard configuration rather than in the repository, so it is invisible to
anyone reading the repo and is not code-reviewed when it changes; every
preview build gets slower by the suite's runtime plus a second `npm ci`; and
Pages build minutes are consumed by test runs. It also duplicates the
`test-frontend` job rather than replacing it — you would keep both, one for
signal and one for enforcement, and they can drift.

**Option 2 — move the Pages deploy into GitHub Actions behind the job.**
Disconnect the Pages GitHub integration, add a `deploy-frontend` job with
`needs: [changes, test-frontend]` and an `if:` on the frontend path filter, and
publish with `wrangler pages deploy` (or `cloudflare/pages-action`) using a
`CLOUDFLARE_API_TOKEN` secret. The gate then lives in the repository, is
reviewed like any other code, and reuses the filter and dispatch escape hatch
already built at `:6–14` and `:30–54`. What it costs: a real migration. Preview
deployments for branches and PRs stop happening automatically and must be
re-created as workflow steps if they are wanted; a new API token with Pages
edit scope enters the secret store; and the failure mode inverts — today a
broken Actions run still ships a frontend, whereas afterwards a broken workflow
means no frontend deploy at all, which is the point but is also a new way to be
stuck. Note the `needs:` chain would need `test-frontend` to keep running on
`workflow_dispatch` for the force-deploy path to work.

**Recommendation: Option 2**, on the repo's own stated principle that the
record moves with the code — a gate that lives in a dashboard is exactly the
kind of prose-about-code that drifts. Option 1 is a reasonable stopgap if the
migration cannot be scheduled before 2026-09-30.

**Do the `it.fails` tests interact badly with a gating run? No — confirmed by
measurement, not by reading.** Vitest counts an `it.fails` test whose body
throws as a **pass**: the run above reports `Tests 5 passed (5)` and exits `0`
with three `it.fails` tests in the file. That is what makes them safe to gate
on. The hazard runs the other way, and it is the point of writing them: when
L8 is fixed, those tests report *"Expect test to fail"*, the run exits non-zero,
and a gating CI **blocks the fix's own deploy** until whoever fixed it removes
the `.fails`. That is intended — it is the mechanism that stops a fix from
landing without the test being converted into a real regression guard — but it
must be written down, because a fixer who does not know it will read a red CI
on a correct fix as a broken test. It is now in the STATUS.md L8 row.

## 10. What this pass did not do

- **L8 is not fixed.** By instruction. The row stays Open.

  **Later (2026-08-24, `06-l8-fix-report.md`):** fixed, clear-before-resolve
  half only. The sketch in §8 was followed with one deviation — `clear()` on
  the autocomplete hook stays synchronous at submit time; only `setValue("")`
  moved behind the promise. The autocomplete half of L8 (the 150ms debounce,
  the swallowed 429) is still open.
- **`SearchBar.tsx`** (the landing-page search) was not examined for the same
  pattern. It is a different component with its own submit path; whether it
  shares the defect is unverified and is not claimed either way here.

  **Later (2026-08-24, `06-l8-fix-report.md`):** examined. It does **not**
  share the defect — it sets `value` to the selected address (`:76`) or leaves
  it untouched (`:85,:97,:164`) and never calls `setValue("")`. No fix was
  needed; `SearchBar.test.tsx` now guards it so the answer is a test rather
  than a sentence.
- **The 429, 503 and client-timeout paths** are undistinguished from 422/502 in
  the UI (§4). That is an observation from this trace, not a finding this pass
  was scoped to fix or to file.
- **`deploy.yml:73–78` is now stale and was left alone.** Its comment says the
  suite "deliberately contains one test expected to fail (H1's decennial half,
  via `it.fails`)"; there are now four. Section 3 of this pass's brief was
  report-only on CI, so the workflow file was not touched. The STATUS.md note
  was corrected instead; the comment should be fixed by whoever next edits
  `deploy.yml`.

  **Later (2026-08-24, the commit adding this annotation):** done. The comment
  was replaced and `continue-on-error` removed, making `test-frontend` blocking
  as a visible PR signal. It still gates no deploy and was deliberately not
  added to any deploy job's `needs` — the Pages gate described in §9 as
  Option 2 remains deferred to its own pass. Measured in that commit:
  `npm test` exits 0 with the four `it.fails` tests present, 1 with an ordinary
  assertion broken.
