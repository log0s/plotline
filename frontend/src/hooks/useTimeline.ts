/**
 * Hook that polls the timeline request status and fetches imagery once ready.
 *
 * Lifecycle:
 *   1. Receives a timeline_request_id from the geocode response.
 *   2. Polls GET /timeline-requests/{id} every 2 seconds.
 *   3. When status is "complete", fetches all imagery snapshots.
 *   4. Populates the store with snapshots.
 */
import { useCallback, useEffect, useRef } from "react";
import { getImagery, getTimelineRequest } from "../api/imagery";
import { useAppStore } from "../store";

const POLL_INTERVAL_MS = 2000;

export function useTimeline() {
  const {
    timelineRequestId,
    parcel,
    setTimelineStatus,
    setSnapshots,
  } = useAppStore();

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPollingRef = useRef(false);

  const fetchSnapshots = useCallback(
    async (parcelId: string) => {
      try {
        const data = await getImagery(parcelId);
        setSnapshots(data.snapshots);
      } catch (err) {
        console.error("Failed to fetch imagery snapshots:", err);
      }
    },
    [setSnapshots],
  );

  const poll = useCallback(
    async (requestId: string, parcelId: string) => {
      if (!isPollingRef.current) return;

      try {
        const status = await getTimelineRequest(requestId);

        if (status.status === "complete" || status.status === "failed") {
          isPollingRef.current = false;
          if (status.status === "complete") {
            await fetchSnapshots(parcelId);
          }
          setTimelineStatus(status);
          return;
        }

        setTimelineStatus(status);

        // Continue polling
        pollRef.current = setTimeout(() => {
          void poll(requestId, parcelId);
        }, POLL_INTERVAL_MS);
      } catch (err) {
        console.error("Timeline poll error:", err);
        // Back off on error
        pollRef.current = setTimeout(() => {
          void poll(requestId, parcelId);
        }, POLL_INTERVAL_MS * 3);
      }
    },
    [setTimelineStatus, fetchSnapshots],
  );

  useEffect(() => {
    if (!timelineRequestId || !parcel?.parcel_id) return;

    // Stop any existing poll
    if (pollRef.current) clearTimeout(pollRef.current);
    isPollingRef.current = true;

    void poll(timelineRequestId, parcel.parcel_id);

    return () => {
      isPollingRef.current = false;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [timelineRequestId, parcel?.parcel_id, poll]);

  return null;
}
