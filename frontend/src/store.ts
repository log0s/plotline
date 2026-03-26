/**
 * Global application state via Zustand.
 *
 * Tracks the active parcel, timeline fetch status, and the
 * imagery snapshots available for display. Navigation is handled
 * by React Router — no view state here.
 */
import { create } from "zustand";
import type {
  AppState,
  DemographicsResponse,
  GeocodeResponse,
  ImagerySnapshot,
  PropertyEventsResponse,
  TimelineRequest,
} from "./types";

export const useAppStore = create<AppState>((set) => ({
  parcel: null,
  isLoading: false,
  error: null,

  // Timeline
  timelineRequestId: null,
  timelineStatus: null,
  snapshots: [],
  selectedSnapshot: null,

  // Demographics
  demographics: null,
  demographicsLoading: false,

  // Property events
  propertyEvents: null,
  propertyEventsLoading: false,

  selectedYear: null,

  // Compare mode
  compareMode: false,
  compareSnapshots: [null, null],

  setParcel: (parcel: GeocodeResponse) =>
    set({
      parcel,
      error: null,
      isLoading: false,
      timelineRequestId: parcel.timeline_request_id,
      // Reset timeline + demographics + events state when a new parcel is loaded
      timelineStatus: null,
      snapshots: [],
      selectedSnapshot: null,
      demographics: null,
      demographicsLoading: false,
      propertyEvents: null,
      propertyEventsLoading: false,
      selectedYear: null,
      compareMode: false,
      compareSnapshots: [null, null],
    }),

  setLoading: (isLoading: boolean) => set({ isLoading }),

  setError: (error: string | null) => set({ error, isLoading: false }),

  setTimelineStatus: (timelineStatus: TimelineRequest | null) =>
    set({ timelineStatus }),

  setSnapshots: (snapshots: ImagerySnapshot[]) => {
    set((state) => ({
      snapshots,
      // Auto-select the most recent NAIP image on first load; fall back to most recent overall
      selectedSnapshot:
        state.selectedSnapshot === null && snapshots.length > 0
          ? (snapshots.filter((s) => s.source === "naip").at(-1) ??
            snapshots.at(-1) ??
            null)
          : state.selectedSnapshot,
    }));
  },

  setSelectedSnapshot: (selectedSnapshot: ImagerySnapshot | null) =>
    set({
      selectedSnapshot,
      // Sync the year focus for demographics highlighting
      selectedYear: selectedSnapshot
        ? parseInt(selectedSnapshot.capture_date.slice(0, 4), 10)
        : null,
    }),

  setDemographics: (demographics: DemographicsResponse | null) =>
    set({ demographics }),

  setDemographicsLoading: (demographicsLoading: boolean) =>
    set({ demographicsLoading }),

  setPropertyEvents: (propertyEvents: PropertyEventsResponse | null) =>
    set({ propertyEvents }),

  setPropertyEventsLoading: (propertyEventsLoading: boolean) =>
    set({ propertyEventsLoading }),

  setCompareMode: (compareMode: boolean) =>
    set((state) => ({
      compareMode,
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
      parcel: null,
      isLoading: false,
      error: null,
      timelineRequestId: null,
      timelineStatus: null,
      snapshots: [],
      selectedSnapshot: null,
      demographics: null,
      demographicsLoading: false,
      propertyEvents: null,
      propertyEventsLoading: false,
      selectedYear: null,
      compareMode: false,
      compareSnapshots: [null, null],
    }),
}));
