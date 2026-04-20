/**
 * React Query hooks for all server data.
 *
 * Keys:
 *   ["parcel", parcelId]          → GeocodeResponse-shaped parcel metadata
 *   ["timelineRequest", requestId] → TimelineRequest (polled while in progress)
 *   ["imagery", parcelId]         → ImagerySnapshot[]
 *   ["demographics", parcelId]    → DemographicsResponse
 *   ["propertyEvents", parcelId]  → PropertyEventsResponse
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { NavigateFunction } from "react-router-dom";
import { getDemographics } from "../api/demographics";
import { getPropertyEvents } from "../api/events";
import { geocodeAddress, getParcel } from "../api/geocode";
import { getImagery, getTimelineRequest, triggerTimeline } from "../api/imagery";
import type {
  DemographicsResponse,
  GeocodeResponse,
  ImagerySnapshot,
  PropertyEventsResponse,
  TimelineRequest,
} from "../types";

const POLL_INTERVAL_MS = 2000;

function parcelResponseToGeocodeShape(data: {
  id: string;
  address: string;
  normalized_address: string | null;
  latitude: number;
  longitude: number;
  census_tract_id: string | null;
}): GeocodeResponse {
  return {
    parcel_id: data.id,
    address: data.address,
    normalized_address: data.normalized_address,
    latitude: data.latitude,
    longitude: data.longitude,
    census_tract: data.census_tract_id,
    is_new: false,
    timeline_request_id: null,
  };
}

export function useParcelQuery(parcelId: string | undefined) {
  return useQuery<GeocodeResponse>({
    queryKey: ["parcel", parcelId],
    enabled: !!parcelId,
    queryFn: async ({ signal }) => {
      const data = await getParcel(parcelId as string, signal);
      return parcelResponseToGeocodeShape(data);
    },
  });
}

export function useImageryQuery(
  parcelId: string | undefined,
  timelineActive = false,
) {
  return useQuery<ImagerySnapshot[]>({
    queryKey: ["imagery", parcelId],
    enabled: !!parcelId,
    queryFn: async ({ signal }) => {
      const data = await getImagery(parcelId as string, { signal });
      return data.snapshots;
    },
    refetchInterval: (query) =>
      query.state.status === "error" ? false : timelineActive ? 3000 : false,
    retry: 3,
  });
}

function isTimelineTerminal(status: TimelineRequest["status"] | undefined) {
  return status === "complete" || status === "failed";
}

export function useTimelineRequestQuery(requestId: string | null | undefined) {
  return useQuery<TimelineRequest>({
    queryKey: ["timelineRequest", requestId],
    enabled: !!requestId,
    queryFn: () => getTimelineRequest(requestId as string),
    refetchInterval: (query) => {
      if (query.state.status === "error") return false;
      if (isTimelineTerminal(query.state.data?.status)) return false;
      return POLL_INTERVAL_MS;
    },
    retry: 3,
    retryDelay: (n) => Math.min(6000, 2000 * 2 ** n),
  });
}

export function useDemographicsQuery(
  parcelId: string | undefined,
  enabled: boolean,
) {
  return useQuery<DemographicsResponse>({
    queryKey: ["demographics", parcelId],
    enabled: enabled && !!parcelId,
    queryFn: () => getDemographics(parcelId as string),
  });
}

export function usePropertyEventsQuery(
  parcelId: string | undefined,
  enabled: boolean,
) {
  return useQuery<PropertyEventsResponse>({
    queryKey: ["propertyEvents", parcelId],
    enabled: enabled && !!parcelId,
    queryFn: () => getPropertyEvents(parcelId as string),
  });
}

interface GeocodeVars {
  address: string;
  lat?: number;
  lon?: number;
  navigate: NavigateFunction;
}

export function useGeocodeMutation() {
  const queryClient = useQueryClient();

  return useMutation<GeocodeResponse, Error, GeocodeVars>({
    mutationFn: ({ address, lat, lon }) => geocodeAddress({ address, lat, lon }),
    onSuccess: (data, { navigate }) => {
      // Prime the parcel cache so ExplorePage doesn't refetch it immediately.
      queryClient.setQueryData<GeocodeResponse>(["parcel", data.parcel_id], {
        ...data,
        timeline_request_id: null,
      });
      void navigate(`/explore/${data.parcel_id}`, {
        state: { timelineRequestId: data.timeline_request_id },
      });
    },
  });
}

export function useTriggerTimelineMutation() {
  return useMutation<{ timeline_request_id: string }, Error, string>({
    mutationFn: (parcelId) => triggerTimeline(parcelId),
  });
}
