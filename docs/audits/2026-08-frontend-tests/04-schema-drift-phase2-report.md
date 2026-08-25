# Phase 2 — Fix, contract test, and coverage

Commit: **6629db1** — `fix(frontend): close the measured schema drift, lock it with a test`
5 files changed, 1436 insertions(+), 8 deletions(-). Not pushed.

Verified green before commit: `tsc --noEmit` clean, `npm test` 10/10 across 5 files,
`npm run lint` clean.

---

## 1. What changed, per type

### `TimelineRequestTask` (`frontend/src/types/index.ts`)

Added, in the position the Pydantic schema declares them:

```ts
started_at: string | null;
completed_at: string | null;
```

`string | null`, not `?`. Justification, as recorded in STATUS.md: `grep -rn
"exclude_none\|exclude_unset\|exclude_defaults" app/api/ app/main.py` returns
zero hits, and FastAPI's default is `response_model_exclude_none=False`, so the
key is always serialized and the value may be null. `timeline-inflight.ts`
confirms it empirically — present-and-null on all six tasks.

### `PropertyEventsResponse` (`frontend/src/types/index.ts`)

```diff
-  supported_counties?: string[];
+  supported_counties: string[];
```

`api/v1/events.py:92` always populates it from
`get_supported_county_display_names()`. **No call-site change was needed.** The
single reader, `DemographicsPanel.tsx:190`, is
`propertyEvents?.supported_counties`, which is `string[] | undefined` either
way, and `UnsupportedCountyBanner`'s own prop is independently optional.

### Not changed, deliberately

`PropertyEventType`'s `zoning_change` and `assessment` — no backend producer
(`classify_permit` at `county_adapters.py:861` emits six `permit_*` values; the
adapters emit `"sale"` directly; seven against the union's nine). Both are
*read* at `constants.ts:70,75` and `Timeline.tsx:87-88`, so they are
unreachable branches, not dead code. Recorded in STATUS.md as an observation.

Nothing was widened to `any` or `unknown`. No fixture needed it.

---

## 2. The two new fixtures — drift they surfaced: **none**

Captured from the local stack (which was not running; I started `postgres`,
`redis`, `api` via docker compose — it is **still up**, `docker compose down`
when you're done with it). Backend git SHA recorded in both headers is
`b4c3a2bd8b0fa1e620395d894fd7cfb641cefda9`, the actual HEAD at capture, not the
`31677c7` the older fixtures carry.

| Fixture | Endpoint | Content | Drift |
|---|---|---|---|
| `imagery-stapleton.ts` | `GET /parcels/70a496c7…/imagery` | 70 snapshots — 43 landsat, 13 sentinel2, 7 naip, 7 usgs_topo | none |
| `featured-list.ts` | `GET /featured` | 6 locations, the full seeded set | none |

Both matched their frontend types on the first `tsc` run, and both matched their
Pydantic schemas key-for-key in both directions. Specifically confirmed:

- All 70 `bbox` values are exactly 4 elements — the
  `[number, number, number, number]` narrowing holds against real data.
- `source` values are exactly `{landsat, naip, sentinel2, usgs_topo}` — the
  `ImagerySource` union is exact, not merely wide enough.
- Nulls land only where expected: `resolution_m`, `thumbnail_url` and
  `cloud_cover_pct` are null only for `usgs_topo` (and `cloud_cover_pct` for
  `naip`), which is what those sources genuinely lack.

**Two gaps in what these fixtures exercise, both recorded in their headers and
in STATUS.md:** `additional_cog_urls` is null on all 70 rows, so the NAIP mosaic
branch is declared but unexercised; and every nullable field on
`FeaturedLocation` (`key_stat`, `description`, `earliest_snapshot_id`,
`latest_snapshot_id`, `preview_image_url`) is non-null on all 6 rows, so the
null branches are pinned by type but not by evidence.

### The SAS redaction

Per your call. 20 of the 70 snapshots (`naip`, `sentinel2`) had `cog_url` values
signed at response time with Azure SAS tokens. Applied mechanically by pattern —
every URL containing `sig=` had its entire query string replaced with the
literal `<SAS-REDACTED>`; everything through the `?` is verbatim. Hosts touched:
`naipeuwest.blob.core.windows.net`, `sentinel2l2a01.blob.core.windows.net`.
`landsat` (a public STAC item link) and `usgs_topo` (public S3) were unsigned and
are untouched, as are all thumbnail URLs (PC data-API render URLs, which sign
themselves server-side and carry no signature parameter).

Verified: **0** occurrences of `sig=` remain in the file. The one that briefly
survived was in my own header prose explaining the redaction — reworded.

STATUS.md reconciles this against the "never hand-edit a captured fixture" rule
that sits three bullets above it, since leaving that contradiction unremarked is
exactly the drift this whole pass is about. The distinction drawn: the edit is
uniform, applied by pattern rather than to individual values, and declared in
the fixture's own header. A per-value edit would not be acceptable on the same
reasoning.

---

## 3. Contract test — `frontend/src/test/types.contract.test.ts`

**Which harness:** `tsc --noEmit`, i.e. `npm run typecheck`, which
`npm run build` already runs. *Not* `npm test`. Vitest strips types without
checking them, so the suite passing proves nothing about the contract — this is
stated at the top of the file so nobody mistakes a green `npm test` for a green
contract. `vitest typecheck` was not used: it needs `test.typecheck` config the
harness doesn't have, and it would put the gate somewhere `npm run build`
doesn't already look. There is one trivial runtime assertion so `npm test`
doesn't report an empty suite.

**Mechanism**, as you specified — both, not plain assignment:

- `Mutable<T>` — homomorphic, so it strips `as const` readonly modifiers while
  *preserving tuple arity*. This matters: the naive `readonly (infer E)[] →
  Mutable<E>[]` form decays `bbox` to `number[]` and silently stops checking
  the 4-tuple.
- `ExtraKeys<F, T>` — recursive walker through objects and arrays, resolving to
  the union of keys the payload carries that the type doesn't declare.
  `NoExtra<F, T>` turns a non-empty result into
  `["EXTRA KEYS IN FIXTURE:", …]`, so the failure message names the fields.

12 fixtures × 2 checks = 24 bindings.

### Delete-and-confirm, both directions

Both run against the **new** fixtures, to prove the new coverage is live rather
than re-proving the mechanism on fixtures Phase 1 already exercised.

Line numbers below are against the **committed** file (both were re-run after
prettier reformatted it, so they're current, not stale from an earlier draft).

**Direction 1 — remove a field a fixture carries.** Deleted
`stac_collection: string` from `ImagerySnapshot`:

```
src/test/types.contract.test.ts(106,7): error TS2322: Type 'boolean' is not
assignable to type '["EXTRA KEYS IN FIXTURE:", "stac_collection"]'.
```

Line 106 is `_e11`, the `imageryStapleton` excess check. Restored → clean.

**Direction 2 — add a field no fixture carries.** Added `epsg: number` to
`ImagerySnapshot`:

```
src/test/types.contract.test.ts(91,7): error TS2322: Type '{ parcel_id:
"70a496c7-…"; snapshots: [{ id: "ea7337a5-…"; source: "usgs_topo"; … }] }' is not
assignable to type 'ImageryListResponse'.
```

Line 91 is `_a11`, the `imageryStapleton` assignability check. Restored → clean;
`git diff --stat` reports no change against the commit.

A third run, adding `region: string` to `FeaturedLocation`, is worth reporting
for what it revealed rather than as a separate confirmation: it produced five
`TS2741`s from `FeaturedCards.tsx`'s six hand-built placeholder objects *before*
reaching the contract test. Those placeholders are themselves object literals
typed as `FeaturedLocation`, so they already act as an incidental (partial)
guard on that one type — and they will make any future `FeaturedLocation` field
addition noisy in a way the other types aren't. The contract test's own error
was there too, just further down the output.

**One correction to my Phase 1 wording:** the error class for direction 2 is
`TS2741` only when the added field is on a *top-level* response type (as with
`DemographicsResponse.probe_missing` in Phase 1). When it sits on a nested
element type — `ImagerySnapshot`, `FeaturedLocation` — TypeScript reports
`TS2322` on the container and names the incompatible element type. The gate
fires either way; the code differs. The file's header comment now says this
accurately rather than promising TS2741 unconditionally.

---

## 4. Measured coverage — what the test locks, and what it doesn't

Written into STATUS.md in these terms.

**Locked (6 endpoints):** `POST /geocode`, `GET /parcels/{id}/demographics`,
`GET /parcels/{id}/events`, `GET /timeline-requests/{id}`,
`GET /parcels/{id}/imagery`, `GET /featured` — and through the last two, the
`ImagerySnapshot` and `FeaturedLocation` element types.

**Not locked (4):** `GET /parcels/{id}` (`ParcelResponse`),
`GET /geocode/autocomplete` (`AutocompleteSuggestion`),
`POST /parcels/{id}/timeline` (`TriggerTimelineResponse`, matched only by an
inline literal in `api/imagery.ts`), and `GET /health` (`HealthResponse`,
`VersionInfo` — the frontend never calls it). These are held only by the hand
diff, which is the same process that produced the drift in the first place.

**And the blind spot that isn't about coverage at all:** an optional-vs-required
mismatch is invisible to this test by construction. `supported_counties` is the
worked example, and it's in STATUS.md as such — all three events fixtures
carried the field, the type declared it `?`, and an optional property accepts a
present value, so `tsc` said nothing. The evidence sat in the fixtures the whole
time. Only the hand diff against the Pydantic schema found it. **A green
contract test means no missing, extra, or mistyped field. It does not mean the
optionality is right.**

---

## 5. Step 9 — would this codebase survive `openapi-typescript`?

The switch would erase both of the blind spots above outright, and that is a
stronger argument than the drift count suggests. Generated types cover *every*
path in `/openapi.json` whether or not anyone captured a fixture for it, which
retires the four uncovered endpoints without further work; and because
`openapi-typescript` reads each schema's `required` array, optionality stops
being a human judgment call — the `supported_counties` class of error becomes
unrepresentable rather than merely untested. Against that, the cost is
concentrated and countable: **15 hand-authored API interfaces plus 2 union
aliases**, of which **six carry narrowings the generator would flatten**, since
the backend declares all of them as bare `str` / `list[float]` with no `Literal`
or `Enum` — `ImagerySource` (4 members, 8 use sites), `PropertyEventType` (9
members, 8 use sites), `TimelineRequestTask.status` (5), `TimelineRequest.status`
(4), `CensusSnapshot.dataset` (2), and `ImagerySnapshot.bbox`'s 4-tuple. The
sharpest loss is exhaustiveness: `SOURCE_COLORS: Record<ImagerySource, string>`
and `EVENT_TYPE_CONFIG` (`Timeline.tsx:31`, `constants.ts`) are compile-time
exhaustive today and would degrade to `Record<string, …>`, so adding a seventh
imagery source would stop being a type error and start being a missing color at
runtime. The `bbox` tuple is the cheapest loss — `applyImageryLayer.ts:82`
already re-checks `snapshot.bbox.length === 4` at runtime, so the tuple type is
belt-and-braces there. The honest conclusion is that this is not
generated-versus-hand-written but *both*: generate the field-level types, keep
the six unions in a small hand-authored overlay that intersects or re-declares
them, and the drift class disappears while the exhaustiveness checks survive.
The alternative worth pricing first is fixing it at the source — `Literal` types
on the six Pydantic fields would put the unions in `/openapi.json` and make the
overlay unnecessary, which is a backend change and therefore out of scope here.

---

## 6. Record

STATUS.md's "Notes for future readers" replaces the b4c3a2b drift note with
seven bullets: the measured size and the fix; the no-backend-finding result; the
locked/unlocked endpoint list; the optional-vs-required blindness with
`supported_counties` as the example; why the check needs two mechanisms; the two
producer-less `PropertyEventType` members; and the SAS redaction reconciled
against the never-hand-edit rule.

Nothing in the batch leaves a STATUS.md claim false as far as I can tell. Two
things I did **not** touch and am flagging rather than leaving silent:

- The finding at STATUS.md ~line 618 about task
  `39e83483` carrying an error message its own timestamps predate is a separate
  provenance question, unaffected by this batch. `timeline-property-failed.ts`
  is the fixture built from that request, and its header already points at it.
- The `M7 ORM/schema drift` row (line 66) is a *backend* ORM-vs-migration drift
  and shares only the word "drift" with this pass. Untouched.
