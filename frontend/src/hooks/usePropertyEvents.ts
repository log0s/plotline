/**
 * Hook that fetches property events once the timeline completes.
 *
 * Watches the timeline status — when it reaches "complete", fires a
 * one-shot fetch for the property events endpoint.
 */
import { useEffect, useRef } from "react";
import { getPropertyEvents } from "../api/events";
import { useAppStore } from "../store";

export function usePropertyEvents() {
  const parcelId = useAppStore((s) => s.parcel?.parcel_id ?? null);
  const timelineStatus = useAppStore((s) => s.timelineStatus?.status ?? null);
  const fetchedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!parcelId || timelineStatus !== "complete") return;
    if (fetchedRef.current === parcelId) return;
    fetchedRef.current = parcelId;

    useAppStore.getState().setPropertyEventsLoading(true);

    getPropertyEvents(parcelId)
      .then((data) => {
        useAppStore.getState().setPropertyEvents(data);
      })
      .catch((err) => {
        console.error("Failed to fetch property events:", err);
      })
      .finally(() => {
        useAppStore.getState().setPropertyEventsLoading(false);
      });
  }, [parcelId, timelineStatus]);
}
