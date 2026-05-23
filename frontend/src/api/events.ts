import type { PropertyEventsResponse } from "../types";
import { BASE_URL, apiFetch, handleResponse } from "./client";

export async function getPropertyEvents(
  parcelId: string,
): Promise<PropertyEventsResponse> {
  const resp = await apiFetch(`${BASE_URL}/parcels/${parcelId}/events`);
  return handleResponse<PropertyEventsResponse>(resp);
}
