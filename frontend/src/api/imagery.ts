import type {
  ImageryListResponse,
  ImagerySource,
  TimelineRequest,
} from "../types";
import { BASE_URL, apiFetch, handleResponse } from "./client";

export async function triggerTimeline(
  parcelId: string,
  signal?: AbortSignal,
): Promise<{ timeline_request_id: string }> {
  const response = await apiFetch(`${BASE_URL}/parcels/${parcelId}/timeline`, {
    method: "POST",
    signal,
  });
  return handleResponse<{ timeline_request_id: string }>(response);
}

export async function getTimelineRequest(
  requestId: string,
): Promise<TimelineRequest> {
  const response = await apiFetch(`${BASE_URL}/timeline-requests/${requestId}`);
  return handleResponse<TimelineRequest>(response);
}

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
  const response = await apiFetch(url, { signal: options?.signal });
  return handleResponse<ImageryListResponse>(response);
}

export { ApiRequestError } from "./client";
