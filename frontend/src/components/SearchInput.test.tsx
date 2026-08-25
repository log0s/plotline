import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ParcelInfo } from "./ParcelInfo";
import { renderWithProviders } from "../test/utils";
import { handleResponse } from "../api/client";
import { geocodeStapleton } from "../test/fixtures/geocode-stapleton";
import { geocodeError422 } from "../test/fixtures/geocode-error-422";
import { geocodeError502 } from "../test/fixtures/geocode-error-502";
import { demographicsAdams } from "../test/fixtures/demographics-adams";
import { eventsAdamsZero } from "../test/fixtures/events-adams-zero";
import { geocodeAddress, fetchAutocompleteSuggestions } from "../api/geocode";
import { getDemographics } from "../api/demographics";
import { getPropertyEvents } from "../api/events";
import type { GeocodeResponse, TimelineRequest } from "../types";

// Mocked at the module boundary, not inside the hooks: useGeocodeMutation
// (queries.ts) and useAddressAutocomplete both import from ../api/geocode, so
// the component under test is wired exactly as it is in production.
vi.mock("../api/geocode", () => ({
  geocodeAddress: vi.fn(),
  getParcel: vi.fn(),
  fetchAutocompleteSuggestions: vi.fn(),
}));
vi.mock("../api/demographics", () => ({ getDemographics: vi.fn() }));
vi.mock("../api/events", () => ({ getPropertyEvents: vi.fn() }));

const ADDRESS = "8340 Northfield Blvd, Denver, CO 80238";
const AUTOCOMPLETE_DEBOUNCE_MS = 150;

/**
 * fireEvent inside act(), plus a microtask flush so React commits before the
 * next assertion. A bare `act(async () => {...})` with a synchronous body
 * trips @typescript-eslint/require-await.
 */
async function actAsync(fn: () => void = () => {}) {
  await act(async () => {
    fn();
    await Promise.resolve();
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * The error the real api/client.ts builds from a captured error body — the
 * fixtures hold the bodies the API actually returned, and handleResponse turns
 * them into the ApiRequestError React Query stores. Nothing here is hand-built.
 */
async function capturedApiError(fixture: {
  status: number;
  body: { detail: string };
}): Promise<unknown> {
  const response = new Response(JSON.stringify(fixture.body), {
    status: fixture.status,
    headers: { "Content-Type": "application/json" },
  });
  try {
    await handleResponse<never>(response);
  } catch (error) {
    return error;
  }
  throw new Error("fixture did not produce an error response");
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="pathname">{location.pathname}</div>;
}

beforeEach(() => {
  vi.mocked(getDemographics).mockResolvedValue(demographicsAdams as never);
  vi.mocked(getPropertyEvents).mockResolvedValue(eventsAdamsZero as never);
  vi.mocked(fetchAutocompleteSuggestions).mockResolvedValue([]);
});

async function renderPanel() {
  const view = renderWithProviders(
    <>
      <ParcelInfo
        parcel={geocodeStapleton as unknown as GeocodeResponse}
        timelineRequestId={null}
        timelineStatus={null as unknown as TimelineRequest}
        snapshots={[]}
        imageryLoading={false}
      />
      <LocationProbe />
    </>,
  );
  // ParcelInfo mounts DemographicsPanel, whose two queries resolve on a later
  // tick. Flush them before asserting so the panel is in its settled state.
  await actAsync();
  const input: HTMLInputElement = screen.getByPlaceholderText(
    "Search another address...",
  );
  return { ...view, input, form: input.closest("form") as HTMLFormElement };
}

async function typeAddress(input: HTMLInputElement) {
  await actAsync(() => {
    fireEvent.change(input, { target: { value: ADDRESS } });
  });
}

/** Let the autocomplete debounce elapse and its fetch settle. */
async function flushDebounce() {
  await act(async () => {
    await new Promise((resolve) =>
      setTimeout(resolve, AUTOCOMPLETE_DEBOUNCE_MS + 50),
    );
  });
}

// L8 (Resolved), clear-before-resolve half — SearchInput used to call
// setValue("") synchronously before onSearch, so the typed address was gone
// before the geocode settled. The clear now runs in clearOnSettle, behind the
// promise ParcelInfo returns from mutateAsync. (a)-(c) assert the fixed
// behaviour; (d) and (e) guard it against over-correcting.
describe("SearchInput geocode race (L8)", () => {
  it("keeps the typed address while the geocode is pending", async () => {
    const pending = deferred<GeocodeResponse>();
    vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

    const { input, form } = await renderPanel();
    await typeAddress(input);
    await actAsync(() => {
      fireEvent.submit(form);
    });

    expect(geocodeAddress).toHaveBeenCalledTimes(1);
    expect(input.value).toBe(ADDRESS);

    await actAsync(() => {
      pending.resolve(geocodeStapleton as unknown as GeocodeResponse);
    });
  });

  it("keeps the typed address and shows the error when the geocode rejects", async () => {
    const pending = deferred<GeocodeResponse>();
    vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

    const { input, form } = await renderPanel();
    await typeAddress(input);
    await actAsync(() => {
      fireEvent.submit(form);
    });

    // Built before entering act(): Response.json() settles over several
    // microtasks, and awaiting it inside act() lets act() exit before React
    // has processed the rejection.
    const apiError = await capturedApiError(geocodeError502);
    await actAsync(() => {
      pending.reject(apiError);
    });

    // findByText polls: React Query commits the mutation error over an
    // indeterminate number of ticks, and a single act() flush is not
    // enough to catch it reliably.
    await screen.findByText(geocodeError502.message);
    expect(input.value).toBe(ADDRESS);
    // The box must be usable again, not just populated: `disabled` is driven
    // solely by the mutation's isPending (SearchInput takes no isLoading from
    // the autocomplete hook), so a rejection re-enables it for a retry.
    expect(input.disabled).toBe(false);
  });

  // Same assertion against the other error the API really returns. 422 is the
  // worse case for L8: "check the spelling" against an empty box.
  it("keeps the typed address when the geocode rejects with a 422 no-match", async () => {
    const pending = deferred<GeocodeResponse>();
    vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

    const { input, form } = await renderPanel();
    await typeAddress(input);
    await actAsync(() => {
      fireEvent.submit(form);
    });

    // Built before entering act(): Response.json() settles over several
    // microtasks, and awaiting it inside act() lets act() exit before React
    // has processed the rejection.
    const apiError = await capturedApiError(geocodeError422);
    await actAsync(() => {
      pending.reject(apiError);
    });

    // findByText polls: React Query commits the mutation error over an
    // indeterminate number of ticks, and a single act() flush is not
    // enough to catch it reliably.
    await screen.findByText(geocodeError422.message);
    expect(input.value).toBe(ADDRESS);
    // The box must be usable again, not just populated: `disabled` is driven
    // solely by the mutation's isPending (SearchInput takes no isLoading from
    // the autocomplete hook), so a rejection re-enables it for a retry.
    expect(input.disabled).toBe(false);
  });

  // Guard, passes today: whatever L8's fix does, success must still clear the
  // box and navigate to the new parcel.
  it("clears the input and navigates once the geocode resolves", async () => {
    const pending = deferred<GeocodeResponse>();
    vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

    const { input, form } = await renderPanel();
    await typeAddress(input);
    await actAsync(() => {
      fireEvent.submit(form);
    });

    await actAsync(() => {
      pending.resolve(geocodeStapleton as unknown as GeocodeResponse);
    });

    await waitFor(() =>
      expect(screen.getByTestId("pathname")).toHaveTextContent(
        `/explore/${geocodeStapleton.parcel_id}`,
      ),
    );
    expect(input.value).toBe("");
    expect(screen.queryByText(geocodeError502.message)).not.toBeInTheDocument();
  });

  // Guard, passes today: setValue("") does not call setQuery, so clearing the
  // box cannot re-enter the autocomplete effect with an empty query. This is
  // the half of L8 that is *not* broken, pinned so a fix that also resets the
  // hook's query cannot silently introduce a fetch for "".
  it("does not fire an autocomplete request for the empty string on submit", async () => {
    const pending = deferred<GeocodeResponse>();
    vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

    const { input, form } = await renderPanel();
    await typeAddress(input);
    await flushDebounce();

    expect(fetchAutocompleteSuggestions).toHaveBeenCalledTimes(1);
    expect(fetchAutocompleteSuggestions).toHaveBeenCalledWith(ADDRESS);

    await actAsync(() => {
      fireEvent.submit(form);
    });
    await flushDebounce();

    expect(fetchAutocompleteSuggestions).toHaveBeenCalledTimes(1);
    expect(fetchAutocompleteSuggestions).not.toHaveBeenCalledWith("");

    await actAsync(() => {
      pending.resolve(geocodeStapleton as unknown as GeocodeResponse);
    });
  });
});
