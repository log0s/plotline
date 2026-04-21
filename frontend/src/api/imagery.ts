import type {
  ImageryListResponse,
  ImagerySource,
  TimelineRequest,
} from "../types";
import { BASE_URL, handleResponse } from "./client";

/**
 * Trigger a new imagery timeline fetch for a parcel.
 * POST /api/v1/parcels/{parcel_id}/timeline
 */
export async function triggerTimeline(
  parcelId: string,
  signal?: AbortSignal,
): Promise<{ timeline_request_id: string }> {
  const response = await fetch(`${BASE_URL}/parcels/${parcelId}/timeline`, {
    method: "POST",
    signal,
  });
  return handleResponse<{ timeline_request_id: string }>(response);
}

/**
 * Poll the status of a timeline request.
 * GET /api/v1/timeline-requests/{request_id}
 */
export async function getTimelineRequest(
  requestId: string,
): Promise<TimelineRequest> {
  const response = await fetch(`${BASE_URL}/timeline-requests/${requestId}`);
  return handleResponse<TimelineRequest>(response);
}

/**
 * Fetch all imagery snapshots for a parcel.
 * GET /api/v1/parcels/{parcel_id}/imagery
 */
export async function getImagery(
  parcelId: string,
  options?: {
    source?: ImagerySource;
    startDate?: string;
    endDate?: string;
    signal?: AbortSignal;
  },
): Promise<ImageryListResponse> {
  const params = new URLSearchParams();
  if (options?.source) params.set("source", options.source);
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);

  const query = params.toString();
  const url = `${BASE_URL}/parcels/${parcelId}/imagery${query ? `?${query}` : ""}`;
  const response = await fetch(url, { signal: options?.signal });
  return handleResponse<ImageryListResponse>(response);
}

export { ApiRequestError } from "./client";
