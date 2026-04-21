/**
 * ExplorePage — full timeline view for a parcel.
 *
 * Parcel, imagery, and timeline status are fetched via React Query
 * (see src/hooks/queries.ts). A parcel that lands here with no existing
 * imagery triggers a fresh timeline job.
 */
import { AnimatePresence, motion, useMotionValue } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { CompareView } from "../components/CompareView";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { MapView } from "../components/MapView";
import { MobileBottomSheet } from "../components/MobileBottomSheet";
import { ParcelInfo } from "../components/ParcelInfo";
import { Timeline } from "../components/Timeline";
import { useIsMobile } from "../hooks/useMediaQuery";
import {
  useImageryQuery,
  useParcelQuery,
  useTimelineRequestQuery,
  useTriggerTimelineMutation,
} from "../hooks/queries";
import { useAppStore } from "../store";
import type { ImagerySnapshot } from "../types";

export default function ExplorePage() {
  const { parcelId } = useParams<{ parcelId: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const { setSelectedSnapshot, compareMode, selectedEvent } = useAppStore();
  const isMobile = useIsMobile();
  const sheetY = useMotionValue(9999);

  // Timeline request ID is ephemeral (per parcel load). It comes from either:
  //   (a) a fresh geocode navigation: location.state.timelineRequestId
  //   (b) a deep-link trigger when imagery is empty (local state below)
  const navTimelineRequestId =
    (location.state as { timelineRequestId?: string | null } | null)
      ?.timelineRequestId ?? null;
  const [triggeredRequestId, setTriggeredRequestId] = useState<string | null>(
    null,
  );
  const timelineRequestId = navTimelineRequestId ?? triggeredRequestId;

  const parcelQuery = useParcelQuery(parcelId);
  const timelineRequestQuery = useTimelineRequestQuery(timelineRequestId);
  const triggerTimelineMutation = useTriggerTimelineMutation();
  const timelineActive =
    timelineRequestId != null &&
    !timelineRequestQuery.isError &&
    timelineRequestQuery.data?.status !== "complete" &&
    timelineRequestQuery.data?.status !== "failed";
  const imageryQuery = useImageryQuery(parcelId, timelineActive);

  // Deep-link recovery: if parcel exists but has no imagery and no active
  // timeline request, trigger one. Runs at most once per parcelId.
  const triggeredForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!parcelId) return;
    if (triggeredForRef.current === parcelId) return;
    if (timelineRequestId) return;
    if (imageryQuery.isLoading || !imageryQuery.data) return;
    if (imageryQuery.data.length > 0) return;
    triggeredForRef.current = parcelId;
    triggerTimelineMutation.mutate(parcelId, {
      onSuccess: (data) => setTriggeredRequestId(data.timeline_request_id),
    });
  }, [
    parcelId,
    timelineRequestId,
    imageryQuery.isLoading,
    imageryQuery.data,
    triggerTimelineMutation,
  ]);

  // When timeline hits "complete", do one last refetch after a short delay
  // to catch any snapshot rows committed right at the tail of the final task.
  useEffect(() => {
    if (timelineRequestQuery.data?.status !== "complete") return;
    const t = setTimeout(() => void imageryQuery.refetch(), 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineRequestQuery.data?.status]);

  const snapshots = useMemo(() => imageryQuery.data ?? [], [imageryQuery.data]);

  // Auto-select the most recent NAIP snapshot (or most recent overall)
  // the first time snapshots arrive for this parcel.
  const autoSelectedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!parcelId) return;
    if (autoSelectedForRef.current === parcelId) return;
    if (snapshots.length === 0) return;
    autoSelectedForRef.current = parcelId;
    // If a ?snap= deep-link is present, that effect wins.
    if (searchParams.get("snap")) return;
    const latest =
      snapshots.filter((s) => s.source === "naip").at(-1) ??
      snapshots.at(-1) ??
      null;
    if (latest) setSelectedSnapshot(latest);
  }, [parcelId, snapshots, setSelectedSnapshot, searchParams]);

  // Apply ?snap= query param on initial load (deep link support).
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

  // User-driven snapshot selection: updates store AND URL.
  // Auto-select and deep-link paths bypass this and only touch store state,
  // so the URL only reflects explicit user intent.
  const handleSnapshotSelect = useCallback(
    (snap: ImagerySnapshot | null) => {
      setSelectedSnapshot(snap);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (snap) next.set("snap", snap.id);
          else next.delete("snap");
          return next;
        },
        { replace: true },
      );
    },
    [setSelectedSnapshot, setSearchParams],
  );

  // Reset guards + selection state when parcel changes
  useEffect(() => {
    autoSelectedForRef.current = null;
    triggeredForRef.current = null;
    snapParamApplied.current = false;
    useAppStore.getState().setSelectedSnapshot(null);
    useAppStore.getState().setSelectedEvent(null);
  }, [parcelId]);

  const parcel = parcelQuery.data ?? null;
  const loadError = parcelQuery.error;

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <h2 className="text-2xl font-bold text-white mb-4">Parcel not found</h2>
        <p className="text-slate-400 mb-6">{loadError.message}</p>
        <button
          onClick={() => void navigate("/")}
          className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
        >
          Search a different address
        </button>
      </div>
    );
  }

  if (parcelQuery.isLoading || !parcel) {
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
      <div className="relative flex-1 min-h-0 overflow-hidden md:overflow-visible">
        <ErrorBoundary>
          {compareMode ? (
            <CompareView parcel={parcel} />
          ) : (
            <MapView parcel={parcel} sheetY={isMobile ? sheetY : undefined} />
          )}
        </ErrorBoundary>

        <button
          onClick={() => {
            useAppStore.getState().reset();
            void navigate("/");
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

        {!compareMode && !isMobile && (
          <AnimatePresence>
            <ParcelInfo
              key={parcel.parcel_id}
              parcel={parcel}
              timelineRequestId={timelineRequestId}
              timelineStatus={timelineRequestQuery.data ?? null}
              snapshots={snapshots}
              imageryLoading={
                imageryQuery.isLoading ||
                (timelineRequestQuery.data?.status === "complete" &&
                  imageryQuery.isFetching)
              }
            />
          </AnimatePresence>
        )}

        {!compareMode && isMobile && (
          <MobileBottomSheet expandTrigger={selectedEvent} y={sheetY} resetKey={parcel.parcel_id}>
            <ParcelInfo
              key={parcel.parcel_id}
              parcel={parcel}
              timelineRequestId={timelineRequestId}
              timelineStatus={timelineRequestQuery.data ?? null}
              snapshots={snapshots}
              imageryLoading={
                imageryQuery.isLoading ||
                (timelineRequestQuery.data?.status === "complete" &&
                  imageryQuery.isFetching)
              }
            />
          </MobileBottomSheet>
        )}
      </div>

      <div className="border-t border-navy-700/60">
        <Timeline
          parcelId={parcel.parcel_id}
          snapshots={snapshots}
          timelineRequestId={timelineRequestId}
          timelineStatus={timelineRequestQuery.data ?? null}
          imageryLoading={
            imageryQuery.isLoading ||
            (timelineRequestQuery.data?.status === "complete" &&
              imageryQuery.isFetching)
          }
          onSnapshotSelect={handleSnapshotSelect}
        />
      </div>
    </motion.div>
  );
}
