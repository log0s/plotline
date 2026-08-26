import { act, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ParcelInfo } from "./ParcelInfo";
import { renderWithProviders } from "../test/utils";
import { geocodeStapleton } from "../test/fixtures/geocode-stapleton";
import { timelinePropertyFailed } from "../test/fixtures/timeline-property-failed";
import { timelinePropertyCompleteZero } from "../test/fixtures/timeline-property-complete-zero";
import { demographicsAdams } from "../test/fixtures/demographics-adams";
import { eventsAdamsZero } from "../test/fixtures/events-adams-zero";
import { getDemographics } from "../api/demographics";
import { getPropertyEvents } from "../api/events";
import type { GeocodeResponse, TimelineRequest } from "../types";

vi.mock("../api/demographics", () => ({ getDemographics: vi.fn() }));
vi.mock("../api/events", () => ({ getPropertyEvents: vi.fn() }));

beforeEach(() => {
  vi.mocked(getDemographics).mockResolvedValue(demographicsAdams as never);
  vi.mocked(getPropertyEvents).mockResolvedValue(eventsAdamsZero as never);
});

const parcel = geocodeStapleton as unknown as GeocodeResponse;

async function renderPanel(timeline: unknown) {
  const result = renderWithProviders(
    <ParcelInfo
      parcel={parcel}
      timelineRequestId={null}
      timelineStatus={timeline as TimelineRequest}
      snapshots={[]}
      imageryLoading={false}
    />,
  );
  // ParcelInfo mounts DemographicsPanel, whose two queries resolve on a later
  // tick. Flush them before asserting so the panel is in its settled state.
  await act(async () => {});
  return result;
}

// M11 regression — Resolved (256ed32). A source that failed must stay visible
// after the run finishes; a source that completed with nothing to report must
// not be dressed up as a failure.
describe("ParcelInfo property task states", () => {
  it("surfaces a failed property source after the timeline completes", async () => {
    await renderPanel(timelinePropertyFailed);

    expect(
      screen.getByText(/property data unavailable — we'll retry/i),
    ).toBeInTheDocument();
  });

  it("shows no issue row when the property source completed with zero items", async () => {
    await renderPanel(timelinePropertyCompleteZero);

    expect(
      screen.queryByText(/property data unavailable/i),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/retry on your next visit/i),
    ).not.toBeInTheDocument();
  });
});

// M3: 'partial' is terminal and serving. Crawford County 6563dedf finished
// with naip and sentinel2 failed and four sources fine; the panel must show
// those two as unavailable and must NOT put "Timeline failed" over the rest.
describe("ParcelInfo partial timeline", () => {
  const partial = {
    ...timelinePropertyFailed,
    status: "partial",
    error_message: null,
  };

  it("does not render a partial timeline as failed", async () => {
    await renderPanel(partial);

    expect(screen.queryByText(/timeline failed/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/property data unavailable — we'll retry/i),
    ).toBeInTheDocument();
  });

  it("enables demographics for a partial timeline", async () => {
    await renderPanel(partial);

    expect(getDemographics).toHaveBeenCalled();
  });
});
