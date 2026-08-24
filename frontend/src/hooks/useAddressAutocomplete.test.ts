import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAddressAutocomplete } from "./useAddressAutocomplete";
import { fetchAutocompleteSuggestions } from "../api/geocode";

vi.mock("../api/geocode", () => ({
  fetchAutocompleteSuggestions: vi.fn(),
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(fetchAutocompleteSuggestions).mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

// L8 (Open) — useAddressAutocomplete.ts:12 debounces at 150ms. This pins the
// debounce itself: a burst of keystrokes must collapse to one request. The
// other half of L8 — SearchInput clearing the input before the geocode
// resolves — is not covered here; see the follow-ups in the report.
describe("useAddressAutocomplete", () => {
  it("issues one request for a burst of keystrokes inside the debounce window", async () => {
    const { result } = renderHook(() => useAddressAutocomplete());

    const keystrokes = ["834", "8340", "8340 ", "8340 N", "8340 No"];
    for (const value of keystrokes) {
      act(() => {
        result.current.setQuery(value);
        vi.advanceTimersByTime(20);
      });
    }

    expect(fetchAutocompleteSuggestions).not.toHaveBeenCalled();

    // async so the fetch's own state updates settle inside act()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });

    expect(fetchAutocompleteSuggestions).toHaveBeenCalledTimes(1);
    expect(fetchAutocompleteSuggestions).toHaveBeenCalledWith("8340 No");
  });

  it("does not fire below the minimum query length", () => {
    const { result } = renderHook(() => useAddressAutocomplete());

    act(() => {
      result.current.setQuery("83");
      vi.advanceTimersByTime(500);
    });

    expect(fetchAutocompleteSuggestions).not.toHaveBeenCalled();
  });
});
