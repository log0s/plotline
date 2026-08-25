# L8 — the clear-before-resolve fix

2026-08-24. Companion to `05-l8-clear-before-resolve-report.md`, which traced
the defect and left it unfixed by instruction. This report covers the fix, the
scope check that preceded it, and the two runs that show the tests bite.

Frozen record: annotate with dated additions, do not rewrite.

## 1. Scope, measured before editing

The 05 report left one question explicitly open — whether `SearchBar.tsx`
shares the shape. Every component that owns a text input and calls a search
handler was read, and every clear of that input classified:

| Site | What it does to `value` | Shares the defect? |
|---|---|---|
| `SearchInput.tsx:35` `handleSelect` | `setValue("")` before `onSearch` | **yes** |
| `SearchInput.tsx:44` submit, exact-search branch | `setValue("")` before `onSearch` | **yes** |
| `SearchInput.tsx:57` submit, typed branch | `setValue("")` before `onSearch` | **yes** |
| `SearchInput.tsx:112` dropdown exact-search `onMouseDown` | `setValue("")` before `onSearch` | **yes** |
| `SearchBar.tsx:76` `handleSelect` | `setValue(displayName)` — replaces | no |
| `SearchBar.tsx:85,97,164` submit + dropdown | `value` untouched; only `setShowSuggestions(false)` + `clearSuggestions()` | no |
| `SearchBar.tsx:119` `handleChip` | `setValue(address)` — sets | no |

**`SearchBar` never empties its box.** On a rejection the typed address is
already still there and the error renders beneath it. The open question
resolves to *not affected* — no fix, but a test (§4).

Callers of the handler, and what each does with the result:

| Site | Call | Result |
|---|---|---|
| `ParcelInfo.tsx:123` → `SearchInput` | `geocodeMutation.mutate(...)` | discarded, returns `void` |
| `LandingPage.tsx:17` → `SearchBar` | `geocodeMutation.mutate(...)` | discarded, returns `void` |

Neither awaited. Widening `SearchInput`'s `onSearch` to
`void | Promise<unknown>` is therefore honest at both call sites: only
`ParcelInfo` changed, and `SearchBar`'s own prop type was left alone because
nothing there needs the promise.

Two properties were confirmed rather than assumed, because the fix leans on
both:

- **The input is already disabled while pending.** `SearchInput.tsx:96` and
  the Go button at `:199` read `disabled={isLoading}`, and `isLoading` is
  `geocodeMutation.isPending` (`ParcelInfo.tsx:139`). `SearchInput` destructures
  only `{ setQuery, suggestions, clear }` from `useAddressAutocomplete` — it
  never reads that hook's own `isLoading`. So "value kept, box disabled while
  pending, re-enabled on rejection" needed no new code; deferring the clear was
  the whole fix.
- **`clear()` does not touch `showSuggestions`.** It is the hook's own reset
  (`useAddressAutocomplete.ts:22-27`): empties `suggestions`, clears its
  `isLoading`, cancels the debounce timer, bumps `requestIdRef` so an in-flight
  response is dropped. `showSuggestions` is component-local. Leaving `clear()`
  synchronous at submit time therefore keeps the dropdown closed through a
  rejection, which is the settled product decision.

## 2. The fix

`SearchInput.tsx` gains one helper and loses four synchronous clears:

```ts
const clearOnSettle = (result: void | Promise<unknown>) => {
  void Promise.resolve(result).then(
    () => setValue(""),
    () => {},
  );
};
```

Each former `setValue(""); …; onSearch(x)` became
`clear(); setShowSuggestions(false); clearOnSettle(onSearch(x))`. `clear()`
and `setShowSuggestions(false)` stay synchronous — only the box's contents wait
for the settle. `ParcelInfo.handleSearch` returns
`geocodeMutation.mutateAsync(...)` instead of calling `mutate`.

**The empty rejection handler is load-bearing, and its emptiness was checked,
not assumed.** `mutateAsync` rejects where `mutate` did not, so something has
to consume that rejection:

- `useGeocodeMutation` (`hooks/queries.ts:141-158`) defines **`onSuccess` only**
  — no `onError`, so nothing rethrows.
- `throwOnError` and `useErrorBoundary` appear **nowhere** in `frontend/src`.
  Both `QueryClient`s (`main.tsx:8-15`, `test/utils.tsx:7-9`) set
  `defaultOptions.queries` and no `mutations` defaults at all.
- The only mutation `onError` in the app is `ExplorePage.tsx:79`, a different
  mutation (`useTriggerTimelineMutation`), and it swallows into local state.

So the catch in `clearOnSettle` is the single consumer of that rejection, and
the error still reaches the user by the path it always did — the mutation's
`error`, passed down as the `error` prop and rendered under the input. That
reasoning is in a comment at the site.

## 3. Delete-the-fix, both runs

Targeted at the fix itself: `clearOnSettle`'s body replaced with a synchronous
`setValue("")`, everything else (including `mutateAsync`) left in place.

| Run | Result |
|---|---|
| Fix present | **5 passed** |
| Fix deleted | **3 failed, 2 passed**, plus 2 unhandled rejections |

The three that fail are exactly (a) pending, (b) 502, (c) 422; the two that
survive are the success-path and empty-string-autocomplete guards, which is
what they are for. The two unhandled rejections are the second half of the
result: with the deferred clear gone, `mutateAsync`'s rejection has no
consumer. That is direct evidence for the comment in §2.

The `SearchBar` guard was checked the same way — inserting a `setValue("")`
into `SearchBar.tsx`'s submit path turns both of its tests red, and removing it
turns them green again. A guard that cannot fail is not a guard.

## 4. Tests

`SearchInput.test.tsx`: the three `it.fails` markers are gone and the tests are
ordinary guards. (b) and (c) gained one assertion each —
`expect(input.disabled).toBe(false)` — because "the value survived" is only
half the requirement; a box that keeps its text but stays disabled is still a
dead end for the user. The assertion is meaningful precisely because of the
`isPending`-only wiring established in §1.

`SearchBar.test.tsx` is new: two cases over the captured 502 and 422 bodies,
rendering `LandingPage` so `SearchBar` runs through the real
`useGeocodeMutation` and the real `useAddressAutocomplete`, with the API
modules mocked at their boundary exactly as `SearchInput.test.tsx` does it. It
asserts the typed address survives a rejection and the input re-enables. It
pins a *non*-defect: its job is to make the §1 answer fail loudly if someone
later "tidies" `SearchBar` into clearing its box.

`HousingChart.test.tsx`'s H1 marker was not touched.

Suite: **17 passed** (15 before this pass), `tsc --noEmit` clean, `eslint`
clean at `--max-warnings 0`, prettier clean.

## 5. Two things this pass changed that were not code

- **`test/setup.ts` gained an `IntersectionObserver` stub.** Rendering
  `LandingPage` mounts framer-motion's `whileInView` on `HowItWorks` and
  `FeaturedCards`, which constructs one on a layout effect; jsdom has none, and
  the render threw. The stub never fires, so those sections stay at their
  initial variant — the elements are in the DOM either way, which is all the
  queries need. Same shape as the existing `ResizeObserver` stub and for the
  same reason.
- **`deploy.yml`'s comment said four `it.fails` tests; there is now one.** The
  05 report flagged that comment as stale once, and the commit before this one
  corrected it to "four". This commit corrects it to "one" and says why. The
  count in a CI comment is exactly the kind of prose that drifts if it is not
  edited alongside the thing it counts.

## 6. What this pass did not do

- **The autocomplete half of L8 is untouched.** `useAddressAutocomplete.ts:12`
  is still a 150ms debounce against the 60/min/IP limit, and a 429 is still
  swallowed into `[]` with no degraded-state signal. L8 is therefore
  **Partially resolved**, not Resolved — the remainder is a real open finding,
  not an accept. It is also a policy-risk item and not only a robustness one:
  komoot's published posture for Photon is throttle-then-ban for heavy users,
  and by INVENTORY N4 a throttled or banned Photon is indistinguishable in our
  UI from an address with no matches — so the failure mode is silent on both
  ends. (The brief cited `docs/claude_SOURCE-LANDSCAPE-2026-08.md` §5.5 for the
  komoot posture. That file is not in this checkout and never has been; the
  security audit's REMEDIATION-1 recorded the same phantom path as a deviation
  on 2026-08-22. The claim is carried unsourced rather than linked to a path
  that does not resolve.)
- **The 429, 503 and client-timeout paths remain undistinguished from 422/502
  in the UI**, as §10 of the 05 report noted. Still an observation, still not
  filed.
- **The Pages deploy gate remains deferred** to its own pass, exactly as
  described in §9 of the 05 report. `test-frontend` is blocking as a PR signal
  and gates no deploy.
