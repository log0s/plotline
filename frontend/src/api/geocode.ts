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
    throw new ApiRequestError(response.status, await extractErrorDetail(response));
  }
  return response.json() as Promise<T>;
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : JSON.stringify(d),
          )
          .join("; ");
      }
      return JSON.stringify(detail);
    }
  } catch {
    // fall through
  }
  return `HTTP ${response.status}`;
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

export { ApiRequestError };
