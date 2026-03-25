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
  timeline_request_id: string | null;
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

// ── Imagery / Timeline types ───────────────────────────────────────────────────

export type ImagerySource = "naip" | "landsat" | "sentinel2";

export interface ImagerySnapshot {
  id: string;
  source: ImagerySource;
  capture_date: string; // ISO date string "YYYY-MM-DD"
  cog_url: string;
  thumbnail_url: string | null;
  resolution_m: number | null;
  cloud_cover_pct: number | null;
  stac_item_id: string;
  stac_collection: string;
}

export interface TimelineRequestTask {
  source: string;
  status: "queued" | "processing" | "complete" | "failed" | "skipped";
  items_found: number;
  error_message: string | null;
}

export interface TimelineRequest {
  id: string;
  parcel_id: string | null;
  status: "queued" | "processing" | "complete" | "failed";
  tasks: TimelineRequestTask[];
  completed_at: string | null;
}

export interface ImageryListResponse {
  parcel_id: string;
  snapshots: ImagerySnapshot[];
}

// ── Demographics / Census types ───────────────────────────────────────────────

export interface CensusSnapshot {
  year: number;
  dataset: "decennial" | "acs5";
  total_population: number | null;
  median_household_income: number | null;
  median_home_value: number | null;
  median_year_built: number | null;
  total_housing_units: number | null;
  occupied_housing_units: number | null;
  owner_occupied_units: number | null;
  renter_occupied_units: number | null;
  vacancy_rate: number | null;
  median_age: number | null;
  median_gross_rent: number | null;
}

export interface DemographicsResponse {
  parcel_id: string;
  tract_fips: string | null;
  snapshots: CensusSnapshot[];
  subtitles: string[];
  notes: string;
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

  // Timeline state
  timelineRequestId: string | null;
  timelineStatus: TimelineRequest | null;
  snapshots: ImagerySnapshot[];
  selectedSnapshot: ImagerySnapshot | null;

  // Demographics state
  demographics: DemographicsResponse | null;
  demographicsLoading: boolean;

  // The year the user is "focused" on (from clicking an imagery snapshot)
  selectedYear: number | null;

  // Actions
  setParcel: (parcel: GeocodeResponse) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setTimelineStatus: (status: TimelineRequest | null) => void;
  setSnapshots: (snapshots: ImagerySnapshot[]) => void;
  setSelectedSnapshot: (snapshot: ImagerySnapshot | null) => void;
  setDemographics: (data: DemographicsResponse | null) => void;
  setDemographicsLoading: (loading: boolean) => void;
  reset: () => void;
}
