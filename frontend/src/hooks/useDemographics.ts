/**
 * Hook that fetches demographics data once the timeline completes.
 *
 * Watches the timeline status — when it reaches "complete", fires a
 * one-shot fetch for the demographics endpoint.
 */
import { useEffect, useRef } from "react";
import { getDemographics } from "../api/demographics";
import { useAppStore } from "../store";

export function useDemographics() {
  const parcelId = useAppStore((s) => s.parcel?.parcel_id ?? null);
  const timelineStatus = useAppStore((s) => s.timelineStatus?.status ?? null);
  const fetchedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!parcelId || timelineStatus !== "complete") return;
    if (fetchedRef.current === parcelId) return;
    fetchedRef.current = parcelId;

    useAppStore.getState().setDemographicsLoading(true);

    getDemographics(parcelId)
      .then((data) => {
        useAppStore.getState().setDemographics(data);
      })
      .catch((err) => {
        console.error("Failed to fetch demographics:", err);
      })
      .finally(() => {
        useAppStore.getState().setDemographicsLoading(false);
      });
  }, [parcelId, timelineStatus]);
}
