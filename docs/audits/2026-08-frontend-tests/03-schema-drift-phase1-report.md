# Phase 1 — Measured drift

## Method note (matters for reading the table)

Plain assignment does **not** trigger TypeScript's excess-property check — that only fires on object literals, and the fixtures are imported consts. So I ran two independent checks per fixture:

- **Assignability** via `declare function mut<T>(v: T): Mutable<T>` (recursively strips the `as const` readonly modifiers) → catches missing fields, type mismatch, nullability mismatch.
- **Excess** via a recursive `ExtraKeys<F, T>` conditional type that walks arrays and nested objects and resolves to the union of keys the fixture has and the type doesn't → catches extra fields.

Both directions were proven live: injecting `probe_missing: string` into `DemographicsResponse` produced three `TS2741` errors and removing it cleared them, while the six real errors stayed put.

## 1. Fixture → type, under `tsc`

| Fixture | Assigned to | Field | Error class |
|---|---|---|---|
| `timeline-inflight.ts` | `TimelineRequest` → `.tasks[]` : `TimelineRequestTask` | `started_at` | extra field |
| `timeline-inflight.ts` | ″ | `completed_at` | extra field |
| `timeline-property-complete-zero.ts` | ″ | `started_at` | extra field |
| `timeline-property-complete-zero.ts` | ″ | `completed_at` | extra field |
| `timeline-property-failed.ts` | ″ | `started_at` | extra field |
| `timeline-property-failed.ts` | ″ | `completed_at` | extra field |
| `demographics-adams.ts` | `DemographicsResponse` | — | clean |
| `demographics-inflight.ts` | `DemographicsResponse` | — | clean |
| `demographics-stapleton.ts` | `DemographicsResponse` | — | clean |
| `events-adams-zero.ts` | `PropertyEventsResponse` | — | clean |
| `events-inflight.ts` | `PropertyEventsResponse` | — | clean |
| `events-stapleton.ts` | `PropertyEventsResponse` | — | clean |
| `geocode-stapleton.ts` | `GeocodeResponse` | — | clean |

**6 errors, all one field pair on one nested type.** Zero missing-field, zero type-mismatch, zero nullability errors across all 10 fixtures.

## 2. Schema diff — every Pydantic response schema vs its frontend counterpart

19 backend `BaseModel` classes, 16 frontend interfaces. 16 pairs matched by name.

**Field-name drift — the entire list:**

| Backend schema | Frontend type | Backend-only | Frontend-only |
|---|---|---|---|
| `TimelineRequestTaskResponse` | `TimelineRequestTask` | `started_at: datetime \| None`, `completed_at: datetime \| None` | — |
| *(all 15 other pairs)* | | none | none |

**Frontend-only fields, whole codebase: zero.** That makes step 4 vacuous — there is nothing to grep for and nothing to remove.

**Optionality mismatch (1):**

| Field | Backend | Frontend |
|---|---|---|
| `PropertyEventsResponse.supported_counties` | `list[str]` — **required**, always populated by `get_supported_county_display_names()` | `supported_counties?: string[]` — **optional** |

**Renamed-in-transit fields: none.** Both sides are snake_case end to end. The one rename in the codebase is local and deliberate: `parcelResponseToGeocodeShape` (`hooks/queries.ts:38-56`) maps `id`→`parcel_id` and `census_tract_id`→`census_tract` to reshape `ParcelResponse` into `GeocodeResponse` for cache priming. That's an adapter, not drift.

**Unpaired schemas:**

| Backend, no named frontend interface | Handled how |
|---|---|
| `TriggerTimelineResponse` | inline `{ timeline_request_id: string }` — `api/imagery.ts:187,192`. Structurally correct. |
| `FeaturedListResponse` | inline `{ locations: FeaturedLocation[] }` — `api/featured.ts:121`. Structurally correct. |
| `VersionInfo`, `HealthResponse` | frontend never calls `/health`. No counterpart needed. |

Frontend with no backend counterpart: `AppState` only — Zustand UI state, by design.

**Type-level narrowings** (backend declares `str`, frontend declares a hand union). Not field drift, but the same failure mode, so I checked each against what the backend can actually emit:

| Frontend | Union | Backend producers | Verdict |
|---|---|---|---|
| `ImagerySnapshot.source` | naip / landsat / sentinel2 / usgs_topo | `_SOURCES` (3) + `usgs_topo` hardcoded | exact |
| `TimelineRequestTask.status` | queued / processing / complete / failed / skipped | all 5 emitted by `_set_task_status` | exact |
| `TimelineRequest.status` | queued / processing / complete / failed | all 4 | exact |
| `CensusSnapshot.dataset` | decennial / acs5 | both | exact |
| `PropertyEvent.event_type` | 9 members | 7 — `classify_permit`'s 6 + `"sale"` | **over-wide**: `zoning_change`, `assessment` have no producer |
| `ImagerySnapshot.bbox` | `[number,number,number,number]` | `list[float]` | narrowed, structurally safe |

No union is too *narrow* — no value the backend emits is unrepresentable. The two dead `PropertyEventType` members are read (`constants.ts:70,75`; `Timeline.tsx:87-88` filter groups), so they are not dead code, just unreachable branches.

## 3. Reconciliation

**Confirmed by fixture:** `started_at` / `completed_at` — 3 of 3 timeline fixtures.

**Fixture-covered but `tsc`-invisible (1):** `supported_counties`. All three events fixtures carry the field, but an optional property accepts a present value, so no error fires. The fixtures *had* the evidence and the type system could not surface it. This is the drift the harness was structurally blind to.

**Schema-only — no fixture covers the endpoint (7 of 12 endpoints):** `GET /parcels/{id}` (`ParcelResponse`), `GET /parcels/{id}/imagery` (`ImageryListResponse`, `ImagerySnapshot`), `GET /featured`, `GET /featured/{slug}` (`FeaturedLocation`), `GET /geocode/autocomplete` (`AutocompleteSuggestion`), `POST /parcels/{id}/timeline`, `GET /health`. By field count the two largest uncovered types are `ImagerySnapshot` (11) and `FeaturedLocation` (12) — together 23 of the ~102 frontend-declared fields sit behind no fixture at all.

**Backend finding: none.** Every fixture's key set equals its backend schema's key set exactly — top level and nested, in both directions, all 10 fixtures. The API returns precisely what its own contract declares. No field escapes the schema.

## 4. Frontend-only fields

Zero exist. Nothing to grep, nothing to remove.

## 5. Size of the drift, and recommendation

**Two fields, one type, one endpoint — plus one optionality slip.** Out of 16 type pairs and ~102 declared fields, that is a 2% field-level miss rate and a single 1-field optionality error. The `TimelineRequestTask` instance found in `b4c3a2b` was not the tip of a pattern; it was very nearly the whole of it.

That said, the honest reading is narrower than "the codebase is fine": **the measurement only had teeth on 5 of 12 endpoints.** The clean result for `ImagerySnapshot` and `FeaturedLocation` comes from the hand schema diff, not from a fixture, and the hand diff is exactly the process that produced the drift in the first place.

**Recommended fix policy — the stated policy (step 6) as written, with three specifics:**

1. **`started_at` / `completed_at` → `string | null`, not `?`.** Pydantic declares `datetime | None = None`; there is no `exclude_none`, `exclude_unset`, or `exclude_defaults` anywhere in `app/api/` or `app/main.py` (grepped — zero hits), and FastAPI's default is `response_model_exclude_none=False`. The key is always present; the value may be null. `timeline-inflight.ts` confirms it: present-and-null on all six tasks.
2. **`supported_counties` → required `string[]`.** Backend declares it required and always populates it. The single use site (`DemographicsPanel.tsx:190`) reads `propertyEvents?.supported_counties`, which stays `string[] | undefined` either way, and `UnsupportedCountyBanner`'s own prop is independently optional — so this tightens the type with no call-site change.
3. **Leave the two `PropertyEventType` members.** They are union members rather than fields, they are referenced in `constants.ts` and `Timeline.tsx`, and pruning them is a product decision about future event types, not a drift fix. It belongs in STATUS.md as a recorded observation, not in this diff.

I'd also flag for the record — not for this pass — that the real exposure is the 7 fixture-less endpoints, and that the contract test in step 8 will lock in only what fixtures exist to lock in.

**Phase 2 is not started.**
