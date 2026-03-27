/**
 * API client functions for the geocode and parcels endpoints.
 */
import type {
  AutocompleteSuggestion,
  GeocodeRequest,
  GeocodeResponse,
  ParcelResponse,
} from "../types";

// VITE_API_BASE_URL is empty in local dev (Vite proxy handles routing),
// and set to the full API origin (e.g. https://api.example.com) in production.
const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors — use the status string
    }
    throw new ApiRequestError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

/**
 * Geocode a US address.
 * POST /api/v1/geocode
 */
export async function geocodeAddress(
  request: GeocodeRequest,
): Promise<GeocodeResponse> {
  const response = await fetch(`${BASE_URL}/geocode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<GeocodeResponse>(response);
}

/**
 * Fetch a parcel by UUID.
 * GET /api/v1/parcels/{parcel_id}
 */
export async function getParcel(parcelId: string): Promise<ParcelResponse> {
  const response = await fetch(`${BASE_URL}/parcels/${parcelId}`);
  return handleResponse<ParcelResponse>(response);
}

/**
 * Fetch address autocomplete suggestions.
 * GET /api/v1/geocode/autocomplete?q=...
 */
export async function fetchAutocompleteSuggestions(
  query: string,
): Promise<AutocompleteSuggestion[]> {
  const response = await fetch(
    `${BASE_URL}/geocode/autocomplete?q=${encodeURIComponent(query)}`,
  );
  if (!response.ok) return [];
  return response.json() as Promise<AutocompleteSuggestion[]>;
}

export { ApiRequestError };
