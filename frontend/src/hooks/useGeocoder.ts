/**
 * Custom hook wrapping the geocode API call.
 * Uses React Query's useMutation for loading / error state management.
 */
import { useMutation } from "@tanstack/react-query";
import type { NavigateFunction } from "react-router-dom";
import { geocodeAddress } from "../api/geocode";
import { useAppStore } from "../store";
import type { GeocodeResponse } from "../types";

export function useGeocoder() {
  const { setParcel, setLoading, setError } = useAppStore();

  const mutation = useMutation<
    GeocodeResponse,
    Error,
    { address: string; lat?: number; lon?: number; navigate: NavigateFunction }
  >({
    mutationFn: ({ address, lat, lon }) => geocodeAddress({ address, lat, lon }),
    onMutate: () => {
      setLoading(true);
      setError(null);
    },
    onSuccess: (data, { navigate }) => {
      setParcel(data);
      navigate(`/explore/${data.parcel_id}`);
    },
    onError: (error: Error) => {
      setError(error.message);
      setLoading(false);
    },
  });

  return {
    geocode: (address: string, navigate: NavigateFunction, coords?: { lat: number; lon: number }) =>
      mutation.mutate({ address, navigate, ...coords }),
    isLoading: mutation.isPending,
    error: mutation.error?.message ?? null,
  };
}
