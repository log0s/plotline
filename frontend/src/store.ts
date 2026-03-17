/**
 * Global application state via Zustand.
 *
 * Keeps it minimal for Phase 1: tracks the current view (landing vs. map)
 * and the active parcel result.
 */
import { create } from "zustand";
import type { AppState, GeocodeResponse } from "./types";

export const useAppStore = create<AppState>((set) => ({
  view: "landing",
  parcel: null,
  isLoading: false,
  error: null,

  setParcel: (parcel: GeocodeResponse) =>
    set({ parcel, view: "map", error: null, isLoading: false }),

  setLoading: (isLoading: boolean) => set({ isLoading }),

  setError: (error: string | null) =>
    set({ error, isLoading: false }),

  reset: () =>
    set({
      view: "landing",
      parcel: null,
      isLoading: false,
      error: null,
    }),
}));
