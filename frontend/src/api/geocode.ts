/**
 * API client functions for the geocode and parcels endpoints.
 */
import type { GeocodeRequest, GeocodeResponse, ParcelResponse } from "../types";

const BASE_URL = "/api/v1";

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

export { ApiRequestError };
