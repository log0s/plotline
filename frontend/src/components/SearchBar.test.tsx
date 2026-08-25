import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LandingPage from "../pages/LandingPage";
import { renderWithProviders } from "../test/utils";
import { handleResponse } from "../api/client";
import { geocodeError422 } from "../test/fixtures/geocode-error-422";
import { geocodeError502 } from "../test/fixtures/geocode-error-502";
import { featuredList } from "../test/fixtures/featured-list";
import { geocodeAddress, fetchAutocompleteSuggestions } from "../api/geocode";
import { getFeaturedLocations } from "../api/featured";
import type { GeocodeResponse } from "../types";

// Mocked at the module boundary, exactly as SearchInput.test.tsx does it, so
// SearchBar is wired through the real useGeocodeMutation and the real
// useAddressAutocomplete.
vi.mock("../api/geocode", () => ({
  geocodeAddress: vi.fn(),
  getParcel: vi.fn(),
  fetchAutocompleteSuggestions: vi.fn(),
}));
vi.mock("../api/featured", () => ({
  getFeaturedLocations: vi.fn(),
  getFeaturedBySlug: vi.fn(),
}));

const ADDRESS = "8340 Northfield Blvd, Denver, CO 80238";

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

/** The error api/client.ts really builds from a captured error body. */
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

beforeEach(() => {
  vi.mocked(fetchAutocompleteSuggestions).mockResolvedValue([]);
  vi.mocked(getFeaturedLocations).mockResolvedValue(
    featuredList.locations as never,
  );
});

async function renderLanding() {
  const view = renderWithProviders(<LandingPage />);
  await actAsync();
  const input: HTMLInputElement = screen.getByPlaceholderText(
    "Enter any US address...",
  );
  return { ...view, input, form: input.closest("form") as HTMLFormElement };
}

// L8 companion guard. SearchBar was examined alongside SearchInput and found
// NOT to share the clear-before-resolve shape: it calls setValue(displayName)
// or leaves `value` alone, and never setValue(""). That answer is worth a test
// rather than only a sentence in the audit — this pins it, so a future edit
// that "tidies" SearchBar into clearing the box fails here instead of shipping
// L8 again on the landing page.
describe("SearchBar geocode race (L8 companion)", () => {
  it.each([
    ["502 upstream failure", geocodeError502],
    ["422 no-match", geocodeError422],
  ])(
    "keeps the typed address and re-enables the input on a %s",
    async (_label, fixture) => {
      const pending = deferred<GeocodeResponse>();
      vi.mocked(geocodeAddress).mockReturnValue(pending.promise);

      const { input, form } = await renderLanding();
      await actAsync(() => {
        fireEvent.change(input, { target: { value: ADDRESS } });
      });
      await actAsync(() => {
        fireEvent.submit(form);
      });

      expect(geocodeAddress).toHaveBeenCalledTimes(1);
      expect(input.value).toBe(ADDRESS);

      // Built before entering act(): Response.json() settles over several
      // microtasks, and awaiting it inside act() lets act() exit before React
      // has processed the rejection.
      const apiError = await capturedApiError(fixture);
      await actAsync(() => {
        pending.reject(apiError);
      });

      await screen.findByText(fixture.message);
      expect(input.value).toBe(ADDRESS);
      expect(input.disabled).toBe(false);
    },
  );
});
