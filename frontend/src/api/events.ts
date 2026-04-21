import type { PropertyEventsResponse } from "../types";
import { BASE_URL, handleResponse } from "./client";

export async function getPropertyEvents(
  parcelId: string,
): Promise<PropertyEventsResponse> {
  const resp = await fetch(`${BASE_URL}/parcels/${parcelId}/events`);
  return handleResponse<PropertyEventsResponse>(resp);
}
