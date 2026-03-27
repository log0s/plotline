/**
 * Hook that polls the timeline request status and fetches imagery once ready.
 *
 * Lifecycle:
 *   1. If timeline_request_id is present, polls GET /timeline-requests/{id}
 *      every 2 seconds until complete, then fetches imagery.
 *   2. If timeline_request_id is null but a parcel is loaded (existing parcel
 *      with pre-built imagery), fetches imagery directly and marks the
 *      timeline as complete.
 */
import { useCallback, useEffect, useRef } from "react";
import { getImagery, getTimelineRequest } from "../api/imagery";
import { useAppStore } from "../store";

const POLL_INTERVAL_MS = 2000;

export function useTimeline() {
  const {
    timelineRequestId,
    parcel,
    timelineStatus,
    snapshots,
    setTimelineStatus,
    setSnapshots,
  } = useAppStore();

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPollingRef = useRef(false);
  const directFetchedRef = useRef<string | null>(null);

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

  // Poll when we have a timeline request ID
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

  // Fallback: when parcel is loaded but there's no timeline request ID
  // (e.g., backend returned null), fetch existing imagery directly.
  useEffect(() => {
    if (timelineRequestId) return; // polling handles this case
    if (!parcel?.parcel_id) return;
    if (timelineStatus != null) return; // already have status
    if (snapshots.length > 0) return; // already have imagery
    if (directFetchedRef.current === parcel.parcel_id) return;
    directFetchedRef.current = parcel.parcel_id;

    void (async () => {
      await fetchSnapshots(parcel.parcel_id);
      setTimelineStatus({
        id: "",
        parcel_id: parcel.parcel_id,
        status: "complete",
        tasks: [],
        completed_at: null,
      });
    })();
  }, [timelineRequestId, parcel?.parcel_id, timelineStatus, snapshots.length, fetchSnapshots, setTimelineStatus]);

  // Reset the direct-fetch guard when the parcel changes
  useEffect(() => {
    directFetchedRef.current = null;
  }, [parcel?.parcel_id]);

  return null;
}
