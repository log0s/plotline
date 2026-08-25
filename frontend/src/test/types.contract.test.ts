/**
 * Contract test: every captured fixture must match its frontend type exactly.
 *
 * This file's value is in what `tsc` says about it, not in what Vitest
 * reports at runtime. `npm test` runs Vitest, which strips types without
 * checking them — so this file passing under Vitest proves nothing on its
 * own. The gate is `npm run typecheck` (`tsc --noEmit`), which the repo
 * already runs as part of `npm run build`. The one runtime assertion below
 * exists so `npm test` doesn't report an empty suite.
 *
 * Plain assignment is NOT enough here. TypeScript's excess-property check
 * only fires on object literals, and these fixtures are imported consts —
 * `const x: T = fixture` silently accepts a fixture carrying fields `T`
 * never declared. That is exactly the drift b4c3a2b found by hand. So each
 * fixture gets two independent checks:
 *
 *   assignable<T>(mut(fixture))  → missing field, wrong type, wrong nullability
 *   const _: NoExtra<...> = yes  → field present in the payload, absent from T
 *
 * To confirm the gate still bites, edit a type in src/types/index.ts:
 * deleting a field a fixture carries raises "EXTRA KEYS IN FIXTURE" on the
 * matching _e binding; adding a field no fixture carries raises TS2741 on
 * the matching _a binding, or TS2322 on the container when the field sits
 * on a nested element type (ImagerySnapshot, FeaturedLocation).
 */
import { describe, expect, it } from "vitest";
import type {
  DemographicsResponse,
  FeaturedLocation,
  GeocodeResponse,
  ImageryListResponse,
  PropertyEventsResponse,
  TimelineRequest,
} from "../types";
import { demographicsAdams } from "./fixtures/demographics-adams";
import { demographicsInflight } from "./fixtures/demographics-inflight";
import { demographicsStapleton } from "./fixtures/demographics-stapleton";
import { eventsAdamsZero } from "./fixtures/events-adams-zero";
import { eventsInflight } from "./fixtures/events-inflight";
import { eventsStapleton } from "./fixtures/events-stapleton";
import { featuredList } from "./fixtures/featured-list";
import { geocodeStapleton } from "./fixtures/geocode-stapleton";
import { imageryStapleton } from "./fixtures/imagery-stapleton";
import { timelineInflight } from "./fixtures/timeline-inflight";
import { timelinePropertyCompleteZero } from "./fixtures/timeline-property-complete-zero";
import { timelinePropertyFailed } from "./fixtures/timeline-property-failed";

/**
 * Strip `as const` readonly modifiers. Homomorphic, so tuples stay tuples —
 * ImagerySnapshot.bbox is a 4-tuple and must not decay to number[].
 */
type Mutable<T> = T extends object
  ? { -readonly [K in keyof T]: Mutable<T[K]> }
  : T;

/** Keys the payload carries that the type does not declare, walked recursively. */
type ExtraKeys<F, T> = F extends readonly (infer FE)[]
  ? T extends readonly (infer TE)[]
    ? ExtraKeys<FE, TE>
    : never
  : F extends object
    ? T extends object
      ?
          | Exclude<keyof F, keyof T>
          | {
              [K in Extract<keyof F, keyof T>]: ExtraKeys<F[K], T[K]>;
            }[Extract<keyof F, keyof T>]
      : never
    : never;

type NoExtra<F, T> = [ExtraKeys<F, T>] extends [never]
  ? true
  : ["EXTRA KEYS IN FIXTURE:", ExtraKeys<F, T>];

/** Identity at runtime; the cast is what `tsc` checks. */
const mut = <T>(v: T) => v as Mutable<T>;
const yes = true as const;

/* ── missing field / wrong type / wrong nullability ─────────────────────── */

const _a1: DemographicsResponse = mut(demographicsAdams);
const _a2: DemographicsResponse = mut(demographicsInflight);
const _a3: DemographicsResponse = mut(demographicsStapleton);
const _a4: PropertyEventsResponse = mut(eventsAdamsZero);
const _a5: PropertyEventsResponse = mut(eventsInflight);
const _a6: PropertyEventsResponse = mut(eventsStapleton);
const _a7: GeocodeResponse = mut(geocodeStapleton);
const _a8: TimelineRequest = mut(timelineInflight);
const _a9: TimelineRequest = mut(timelinePropertyCompleteZero);
const _a10: TimelineRequest = mut(timelinePropertyFailed);
const _a11: ImageryListResponse = mut(imageryStapleton);
const _a12: { locations: FeaturedLocation[] } = mut(featuredList);

/* ── field in the payload that the type does not declare ────────────────── */

const _e1: NoExtra<typeof demographicsAdams, DemographicsResponse> = yes;
const _e2: NoExtra<typeof demographicsInflight, DemographicsResponse> = yes;
const _e3: NoExtra<typeof demographicsStapleton, DemographicsResponse> = yes;
const _e4: NoExtra<typeof eventsAdamsZero, PropertyEventsResponse> = yes;
const _e5: NoExtra<typeof eventsInflight, PropertyEventsResponse> = yes;
const _e6: NoExtra<typeof eventsStapleton, PropertyEventsResponse> = yes;
const _e7: NoExtra<typeof geocodeStapleton, GeocodeResponse> = yes;
const _e8: NoExtra<typeof timelineInflight, TimelineRequest> = yes;
const _e9: NoExtra<typeof timelinePropertyCompleteZero, TimelineRequest> = yes;
const _e10: NoExtra<typeof timelinePropertyFailed, TimelineRequest> = yes;
const _e11: NoExtra<typeof imageryStapleton, ImageryListResponse> = yes;
const _e12: NoExtra<typeof featuredList, { locations: FeaturedLocation[] }> =
  yes;

describe("API type contract", () => {
  it("is enforced by tsc, not by this assertion", () => {
    // Referencing the bindings keeps noUnusedLocals honest about them.
    expect(
      [
        _a1,
        _a2,
        _a3,
        _a4,
        _a5,
        _a6,
        _a7,
        _a8,
        _a9,
        _a10,
        _a11,
        _a12,
        _e1,
        _e2,
        _e3,
        _e4,
        _e5,
        _e6,
        _e7,
        _e8,
        _e9,
        _e10,
        _e11,
        _e12,
      ].length,
    ).toBe(24);
  });
});
