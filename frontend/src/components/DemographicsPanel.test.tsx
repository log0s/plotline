import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DemographicsPanel } from "./DemographicsPanel";
import { renderWithProviders } from "../test/utils";
import { demographicsEmpty } from "../test/fixtures/demographics-empty";
import { eventsEmpty } from "../test/fixtures/events-empty";
import { getDemographics } from "../api/demographics";
import { getPropertyEvents } from "../api/events";

vi.mock("../api/demographics", () => ({ getDemographics: vi.fn() }));
vi.mock("../api/events", () => ({ getPropertyEvents: vi.fn() }));

// Both sources come back genuinely empty. What distinguishes the two states
// below is only the task status the timeline reported.
beforeEach(() => {
  vi.mocked(getDemographics).mockResolvedValue(demographicsEmpty as never);
  vi.mocked(getPropertyEvents).mockResolvedValue(eventsEmpty as never);
});

// M11 regression — Resolved (256ed32). "Complete with zero rows" and "failed"
// must not render the same way: the first is an authoritative answer, the
// second is a portal outage the user should expect us to retry.
describe("DemographicsPanel empty state", () => {
  it("renders the no-records state when the sources completed with zero rows", async () => {
    renderWithProviders(
      <DemographicsPanel
        parcelId="45a84ee8-342d-4fe0-b029-f0b2b93db4d8"
        enabled
        censusStatus="complete"
        propertyStatus="complete"
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/no census or property records found/i),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/couldn’t load/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/we’ll retry/i)).not.toBeInTheDocument();
  });

  it("renders the retry state when the property source failed", async () => {
    renderWithProviders(
      <DemographicsPanel
        parcelId="45a84ee8-342d-4fe0-b029-f0b2b93db4d8"
        enabled
        censusStatus="complete"
        propertyStatus="failed"
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/couldn’t load property records/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/we’ll retry on your next visit/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/no census or property records found/i),
    ).not.toBeInTheDocument();
  });
});
