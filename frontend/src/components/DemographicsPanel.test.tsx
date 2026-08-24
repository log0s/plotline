import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DemographicsPanel } from "./DemographicsPanel";
import { renderWithProviders } from "../test/utils";
import { demographicsAdams } from "../test/fixtures/demographics-adams";
import { eventsAdamsZero } from "../test/fixtures/events-adams-zero";
import { demographicsInflight } from "../test/fixtures/demographics-inflight";
import { eventsInflight } from "../test/fixtures/events-inflight";
import { timelinePropertyCompleteZero } from "../test/fixtures/timeline-property-complete-zero";
import { timelinePropertyFailed } from "../test/fixtures/timeline-property-failed";
import { timelineInflight } from "../test/fixtures/timeline-inflight";
import { getDemographics } from "../api/demographics";
import { getPropertyEvents } from "../api/events";

vi.mock("../api/demographics", () => ({ getDemographics: vi.fn() }));
vi.mock("../api/events", () => ({ getPropertyEvents: vi.fn() }));

/** Pull a source's real status out of a captured timeline-request payload,
 * rather than typing the status literal into the test. */
function statusOf(
  timeline: { tasks: readonly { source: string; status: string }[] },
  source: string,
): "queued" | "processing" | "complete" | "failed" | "skipped" {
  const task = timeline.tasks.find((t) => t.source === source);
  if (!task) throw new Error(`fixture has no ${source} task`);
  return task.status as ReturnType<typeof statusOf>;
}

const ADAMS_PARCEL = "e032a469-d6c9-49d6-927e-e26779cea3a6";
const INFLIGHT_PARCEL = "9a839723-94c5-406f-99c9-424af22a4885";

// M11 regression — Resolved (256ed32). A property source that FAILED must be
// called out; one that COMPLETED having found nothing must not be. The Adams
// County parcel is the real complete-with-zero case: 9 census snapshots, zero
// property events, property task complete at 0 items — payloads and task rows
// all from the same run.
describe("DemographicsPanel property source states", () => {
  beforeEach(() => {
    vi.mocked(getDemographics).mockResolvedValue(demographicsAdams as never);
    vi.mocked(getPropertyEvents).mockResolvedValue(eventsAdamsZero as never);
  });

  it("does not flag the property source when it completed with zero events", async () => {
    renderWithProviders(
      <DemographicsPanel
        parcelId={ADAMS_PARCEL}
        enabled
        censusStatus={statusOf(timelinePropertyCompleteZero, "census")}
        propertyStatus={statusOf(timelinePropertyCompleteZero, "property")}
      />,
    );

    // The notes paragraph renders only in the populated body, so it is the
    // marker that the panel settled with data rather than into an empty state.
    await waitFor(() =>
      expect(
        screen.getByText(/census tract boundaries may differ/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/property records unavailable/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/we’ll retry/i)).not.toBeInTheDocument();
  });

  // The failed status is read from a real request that genuinely failed
  // (Stapleton's 377e9f11, "All Denver County property queries failed").
  // No Adams request ever failed, so the status necessarily comes from the
  // parcel that produced one.
  it("flags the property source when it failed", async () => {
    renderWithProviders(
      <DemographicsPanel
        parcelId={ADAMS_PARCEL}
        enabled
        censusStatus={statusOf(timelinePropertyFailed, "census")}
        propertyStatus={statusOf(timelinePropertyFailed, "property")}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/property records unavailable/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/we’ll retry on your next visit/i),
    ).toBeInTheDocument();
  });
});

// The third M11 state: nothing has run yet. Empty payloads here mean "not
// fetched", not "nothing to find", and the panel must say so rather than
// render an authoritative-sounding empty result.
describe("DemographicsPanel in-flight state", () => {
  beforeEach(() => {
    vi.mocked(getDemographics).mockResolvedValue(demographicsInflight as never);
    vi.mocked(getPropertyEvents).mockResolvedValue(eventsInflight as never);
  });

  it("says data is still coming while the tasks are queued", async () => {
    renderWithProviders(
      <DemographicsPanel
        parcelId={INFLIGHT_PARCEL}
        enabled
        censusStatus={statusOf(timelineInflight, "census")}
        propertyStatus={statusOf(timelineInflight, "property")}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/data will appear once the timeline finishes/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/no census or property records found/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/couldn’t load/i)).not.toBeInTheDocument();
  });
});
