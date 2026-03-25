/**
 * API client for demographics endpoints.
 */
import type { DemographicsResponse } from "../types";

const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

export async function getDemographics(
  parcelId: string,
): Promise<DemographicsResponse> {
  const resp = await fetch(`${BASE_URL}/parcels/${parcelId}/demographics`);
  if (!resp.ok) {
    throw new Error(`Demographics fetch failed: ${resp.status}`);
  }
  return resp.json();
}
