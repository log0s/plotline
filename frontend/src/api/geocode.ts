import type {
  AutocompleteSuggestion,
  GeocodeRequest,
  GeocodeResponse,
  ParcelResponse,
} from "../types";
import { BASE_URL, handleResponse } from "./client";

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
export async function getParcel(
  parcelId: string,
  signal?: AbortSignal,
): Promise<ParcelResponse> {
  const response = await fetch(`${BASE_URL}/parcels/${parcelId}`, { signal });
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

export { ApiRequestError } from "./client";
