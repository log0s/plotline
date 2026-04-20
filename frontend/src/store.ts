/**
 * Zustand store for UI-interaction state only.
 *
 * Server data (parcel, timeline, snapshots, demographics, events) lives in
 * React Query — see src/hooks/queries.ts. This store tracks what the user
 * has *selected* in the UI: the focused imagery snapshot, focused event,
 * year, and compare-mode state.
 */
import { create } from "zustand";
import type { AppState, ImagerySnapshot } from "./types";

export const useAppStore = create<AppState>((set) => ({
  selectedSnapshot: null,
  selectedEvent: null,
  selectedYear: null,
  compareMode: false,
  compareSnapshots: [null, null],

  setSelectedSnapshot: (selectedSnapshot: ImagerySnapshot | null) =>
    set({
      selectedSnapshot,
      selectedYear: selectedSnapshot
        ? parseInt(selectedSnapshot.capture_date.slice(0, 4), 10)
        : null,
    }),

  setSelectedEvent: (selectedEvent) => set({ selectedEvent }),

  setCompareMode: (compareMode: boolean) =>
    set((state) => ({
      compareMode,
      selectedSnapshot: compareMode ? null : state.selectedSnapshot,
      selectedEvent: compareMode ? null : state.selectedEvent,
      compareSnapshots: compareMode ? state.compareSnapshots : [null, null],
    })),

  setCompareSnapshot: (index: 0 | 1, snapshot: ImagerySnapshot | null) =>
    set((state) => {
      const updated: [ImagerySnapshot | null, ImagerySnapshot | null] = [
        ...state.compareSnapshots,
      ];
      updated[index] = snapshot;
      return { compareSnapshots: updated };
    }),

  reset: () =>
    set({
      selectedSnapshot: null,
      selectedEvent: null,
      selectedYear: null,
      compareMode: false,
      compareSnapshots: [null, null],
    }),
}));
