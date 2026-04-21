import type { DemographicsResponse } from "../types";
import { BASE_URL, handleResponse } from "./client";

export async function getDemographics(
  parcelId: string,
): Promise<DemographicsResponse> {
  const resp = await fetch(`${BASE_URL}/parcels/${parcelId}/demographics`);
  return handleResponse<DemographicsResponse>(resp);
}
