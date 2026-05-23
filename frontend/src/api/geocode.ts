import type {
  AutocompleteSuggestion,
  GeocodeRequest,
  GeocodeResponse,
  ParcelResponse,
} from "../types";
import { BASE_URL, apiFetch, handleResponse } from "./client";

export async function geocodeAddress(
  request: GeocodeRequest,
): Promise<GeocodeResponse> {
  const response = await apiFetch(`${BASE_URL}/geocode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<GeocodeResponse>(response);
}

export async function getParcel(
  parcelId: string,
  signal?: AbortSignal,
): Promise<ParcelResponse> {
  const response = await apiFetch(`${BASE_URL}/parcels/${parcelId}`, {
    signal,
  });
  return handleResponse<ParcelResponse>(response);
}

export async function fetchAutocompleteSuggestions(
  query: string,
): Promise<AutocompleteSuggestion[]> {
  try {
    const response = await apiFetch(
      `${BASE_URL}/geocode/autocomplete?q=${encodeURIComponent(query)}`,
    );
    if (!response.ok) return [];
    return response.json() as Promise<AutocompleteSuggestion[]>;
  } catch {
    return [];
  }
}

export { ApiRequestError } from "./client";
