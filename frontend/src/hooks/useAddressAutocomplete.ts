/**
 * Hook for debounced address autocomplete suggestions via Photon.
 *
 * Returns suggestions after the user pauses typing for 150ms.
 * Cancels in-flight requests when the query changes.
 * Keeps stale results visible while loading new ones for snappier UX.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAutocompleteSuggestions } from "../api/geocode";
import type { AutocompleteSuggestion } from "../types";

const DEBOUNCE_MS = 150;
const MIN_QUERY_LENGTH = 3;

export function useAddressAutocomplete() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<AutocompleteSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);

  const clear = useCallback(() => {
    setSuggestions([]);
    setIsLoading(false);
    if (timerRef.current) clearTimeout(timerRef.current);
    requestIdRef.current++;
  }, []);

  useEffect(() => {
    if (query.length < MIN_QUERY_LENGTH) {
      clear();
      return;
    }

    if (timerRef.current) clearTimeout(timerRef.current);

    // Show loading immediately while keeping previous results visible
    setIsLoading(true);

    timerRef.current = setTimeout(async () => {
      const thisRequestId = ++requestIdRef.current;

      try {
        const results = await fetchAutocompleteSuggestions(query);
        // Only update if this is still the latest request
        if (thisRequestId === requestIdRef.current) {
          setSuggestions(results);
          setIsLoading(false);
        }
      } catch {
        if (thisRequestId === requestIdRef.current) {
          setIsLoading(false);
        }
      }
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query, clear]);

  return { query, setQuery, suggestions, isLoading, clear };
}
