/**
 * API client functions for imagery timeline endpoints.
 */
import type {
  ImageryListResponse,
  ImagerySource,
  TimelineRequest,
} from "../types";

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
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new ApiRequestError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

/**
 * Trigger a new imagery timeline fetch for a parcel.
 * POST /api/v1/parcels/{parcel_id}/timeline
 */
export async function triggerTimeline(
  parcelId: string,
): Promise<{ timeline_request_id: string }> {
  const response = await fetch(`${BASE_URL}/parcels/${parcelId}/timeline`, {
    method: "POST",
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
  },
): Promise<ImageryListResponse> {
  const params = new URLSearchParams();
  if (options?.source) params.set("source", options.source);
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);

  const query = params.toString();
  const url = `${BASE_URL}/parcels/${parcelId}/imagery${query ? `?${query}` : ""}`;
  const response = await fetch(url);
  return handleResponse<ImageryListResponse>(response);
}

export { ApiRequestError };
