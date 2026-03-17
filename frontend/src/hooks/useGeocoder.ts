/**
 * Custom hook wrapping the geocode API call.
 * Uses React Query's useMutation for loading / error state management.
 */
import { useMutation } from "@tanstack/react-query";
import { geocodeAddress } from "../api/geocode";
import { useAppStore } from "../store";
import type { GeocodeResponse } from "../types";

export function useGeocoder() {
  const { setParcel, setLoading, setError } = useAppStore();

  const mutation = useMutation<GeocodeResponse, Error, string>({
    mutationFn: (address: string) => geocodeAddress({ address }),
    onMutate: () => {
      setLoading(true);
      setError(null);
    },
    onSuccess: (data) => {
      setParcel(data);
    },
    onError: (error: Error) => {
      setError(error.message);
      setLoading(false);
    },
  });

  return {
    geocode: (address: string) => mutation.mutate(address),
    isLoading: mutation.isPending,
    error: mutation.error?.message ?? null,
  };
}
