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

/**
 * Ask the API to pre-warm Titiler's cache for a snapshot.
 *
 * Best-effort: resolves false when the call is refused (rate limited) or
 * fails, so the caller can let a later selection try again. Nothing is
 * surfaced to the user — a cold cache only costs a slower first tile.
 */
export async function warmupSnapshot(snapshotId: string): Promise<boolean> {
  try {
    const response = await apiFetch(
      `${BASE_URL}/imagery/${snapshotId}/warmup`,
      {
        method: "POST",
      },
    );
    return response.ok;
  } catch {
    return false;
  }
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
