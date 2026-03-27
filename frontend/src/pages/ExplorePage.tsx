/**
 * ExplorePage — full timeline view for a parcel.
 *
 * Loads parcel data from the API if not already in the store (deep link support).
 * Reads ?snap= query param to pre-select a snapshot.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getParcel } from "../api/geocode";
import { getImagery, triggerTimeline } from "../api/imagery";
import { CompareView } from "../components/CompareView";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { MapView } from "../components/MapView";
import { ParcelInfo } from "../components/ParcelInfo";
import { Timeline } from "../components/Timeline";
import { useDemographics } from "../hooks/useDemographics";
import { usePropertyEvents } from "../hooks/usePropertyEvents";
import { useTimeline } from "../hooks/useTimeline";
import { useAppStore } from "../store";

export default function ExplorePage() {
  const { parcelId } = useParams<{ parcelId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const {
    parcel,
    setParcel,
    setSnapshots,
    setTimelineStatus,
    snapshots,
    selectedSnapshot,
    setSelectedSnapshot,
    compareMode,
  } = useAppStore();
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deepLinkLoading, setDeepLinkLoading] = useState(false);

  // Start data polling/fetching hooks
  useTimeline();
  useDemographics();
  usePropertyEvents();

  // Deep link: load parcel from API if not in store
  useEffect(() => {
    if (!parcelId) return;

    // Already have this parcel loaded
    if (parcel && parcel.parcel_id === parcelId) return;

    let cancelled = false;
    setDeepLinkLoading(true);
    setLoadError(null);

    getParcel(parcelId)
      .then(async (data) => {
        if (cancelled) return;
        // Convert ParcelResponse to GeocodeResponse shape for the store
        const geocodeShape = {
          parcel_id: data.id,
          address: data.address,
          normalized_address: data.normalized_address,
          latitude: data.latitude,
          longitude: data.longitude,
          census_tract: data.census_tract_id,
          is_new: false,
          timeline_request_id: null as string | null,
        };

        // Try to load existing imagery first
        try {
          const imagery = await getImagery(data.id);
          if (!cancelled) {
            if (imagery.snapshots.length > 0) {
              setParcel(geocodeShape);
              setSnapshots(imagery.snapshots);
              // Mark timeline as complete so demographics/events hooks fire
              setTimelineStatus({
                id: "",
                parcel_id: data.id,
                status: "complete",
                tasks: [],
                completed_at: null,
              });
            } else {
              // No existing imagery — trigger a new timeline fetch
              const { timeline_request_id } = await triggerTimeline(data.id);
              geocodeShape.timeline_request_id = timeline_request_id;
              if (!cancelled) setParcel(geocodeShape);
            }
          }
        } catch {
          // Imagery fetch failed — just set parcel, trigger timeline
          if (!cancelled) {
            try {
              const { timeline_request_id } = await triggerTimeline(data.id);
              geocodeShape.timeline_request_id = timeline_request_id;
            } catch { /* proceed without timeline */ }
            if (!cancelled) setParcel(geocodeShape);
          }
        }

        if (!cancelled) setDeepLinkLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setDeepLinkLoading(false);
        setLoadError(err.message ?? "Parcel not found");
      });

    return () => {
      cancelled = true;
    };
  }, [parcelId, parcel, setParcel, setSnapshots, setTimelineStatus]);

  // Apply ?snap= query param on initial load (deep link support).
  // Only runs when snapshots first arrive, not on every URL change.
  const snapParamApplied = useRef(false);
  useEffect(() => {
    if (snapParamApplied.current || snapshots.length === 0) return;
    const snapId = searchParams.get("snap");
    if (!snapId) return;

    const match = snapshots.find((s) => s.id === snapId);
    if (match) {
      setSelectedSnapshot(match);
      snapParamApplied.current = true;
    }
  }, [snapshots]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync URL when snapshot changes (user clicks in timeline)
  useEffect(() => {
    if (!selectedSnapshot) return;
    setSearchParams({ snap: selectedSnapshot.id }, { replace: true });
  }, [selectedSnapshot]); // eslint-disable-line react-hooks/exhaustive-deps

  // Error state — parcel not found
  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <h2 className="text-2xl font-bold text-white mb-4">Parcel not found</h2>
        <p className="text-slate-400 mb-6">{loadError}</p>
        <button
          onClick={() => navigate("/")}
          className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
        >
          Search a different address
        </button>
      </div>
    );
  }

  // Deep link loading state
  if (deepLinkLoading || !parcel) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="flex items-center gap-3 text-slate-400">
          <svg className="animate-spin w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          <span>Loading parcel...</span>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      key="map"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="relative w-full h-screen flex flex-col"
    >
      {/* Map takes all remaining space above the timeline */}
      <div className="relative flex-1 min-h-0">
        <ErrorBoundary>
          {compareMode ? (
            <CompareView parcel={parcel} />
          ) : (
            <MapView parcel={parcel} />
          )}
        </ErrorBoundary>

        {/* Top-left brand chip */}
        <button
          onClick={() => {
            useAppStore.getState().reset();
            navigate("/");
          }}
          className="absolute top-4 left-4 z-10 flex items-center gap-2 px-3 py-2 rounded-xl bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 hover:border-amber-500/40 transition-colors"
          title="Back to search"
        >
          <svg
            className="w-4 h-4 text-amber-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          <span className="text-sm font-semibold text-white">
            Plot<span className="text-amber-400">line</span>
          </span>
        </button>

        {/* Parcel info sidebar (hidden in compare mode) */}
        {!compareMode && (
          <AnimatePresence>
            <ParcelInfo key={parcel.parcel_id} parcel={parcel} />
          </AnimatePresence>
        )}
      </div>

      {/* Timeline strip */}
      <div className="border-t border-navy-700/60">
        <Timeline />
      </div>
    </motion.div>
  );
}
