/**
 * API client for property events endpoints.
 */
import type { PropertyEventsResponse } from "../types";

const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

export async function getPropertyEvents(
  parcelId: string,
): Promise<PropertyEventsResponse> {
  const resp = await fetch(`${BASE_URL}/parcels/${parcelId}/events`);
  if (!resp.ok) {
    throw new Error(`Property events fetch failed: ${resp.status}`);
  }
  return resp.json();
}
