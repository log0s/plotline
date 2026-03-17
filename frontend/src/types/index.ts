/**
 * Shared TypeScript types for the Plotline frontend.
 * These mirror the Pydantic schemas on the backend.
 */

// ── API Request / Response types ──────────────────────────────────────────────

export interface GeocodeRequest {
  address: string;
}

export interface GeocodeResponse {
  parcel_id: string;
  address: string;
  normalized_address: string | null;
  latitude: number;
  longitude: number;
  census_tract: string | null;
  is_new: boolean;
}

export interface ParcelResponse {
  id: string;
  address: string;
  normalized_address: string | null;
  latitude: number;
  longitude: number;
  census_tract_id: string | null;
  county: string | null;
  state_fips: string | null;
  created_at: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  db: "connected" | "error";
  redis: "connected" | "error";
  version: string;
}

// ── API Error shape ───────────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  status: number;
}

// ── Application state ─────────────────────────────────────────────────────────

export type AppView = "landing" | "map";

export interface AppState {
  view: AppView;
  parcel: GeocodeResponse | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  setParcel: (parcel: GeocodeResponse) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}
