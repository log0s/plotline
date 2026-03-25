/**
 * Hook that fetches demographics data once the timeline completes.
 *
 * Watches the timeline status — when it reaches "complete", fires a
 * one-shot fetch for the demographics endpoint. This data doesn't need
 * polling since census data is fetched once and cached.
 */
import { useEffect, useRef } from "react";
import { getDemographics } from "../api/demographics";
import { useAppStore } from "../store";

export function useDemographics() {
  const { parcel, timelineStatus, setDemographics, setDemographicsLoading } =
    useAppStore();
  const fetchedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!parcel?.parcel_id) return;
    if (timelineStatus?.status !== "complete") return;

    // Only fetch once per parcel
    if (fetchedRef.current === parcel.parcel_id) return;
    fetchedRef.current = parcel.parcel_id;

    setDemographicsLoading(true);

    getDemographics(parcel.parcel_id)
      .then((data) => {
        setDemographics(data);
      })
      .catch((err) => {
        console.error("Failed to fetch demographics:", err);
      })
      .finally(() => {
        setDemographicsLoading(false);
      });
  }, [parcel?.parcel_id, timelineStatus?.status, setDemographics, setDemographicsLoading]);
}
