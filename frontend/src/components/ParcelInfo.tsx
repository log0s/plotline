import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { SOURCE_LABELS } from "../constants";
import { DemographicsPanel } from "./DemographicsPanel";
import { EventDetail } from "./EventDetail";
import { SearchInput } from "./SearchInput";
import { useGeocodeMutation } from "../hooks/queries";
import { useIsMobile } from "../hooks/useMediaQuery";
import { useAppStore } from "../store";
import type {
  GeocodeResponse,
  ImagerySnapshot,
  TimelineRequest,
} from "../types";

function TaskRow({
  task,
}: {
  task: { source: string; status: string; items_found: number };
}) {
  const label = SOURCE_LABELS[task.source] ?? task.source;
  const isDone = task.status === "complete";
  const isProcessing = task.status === "processing";
  const isFailed = task.status === "failed";
  const isSkipped = task.status === "skipped";

  const indicator = isDone ? (
    <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
  ) : isProcessing ? (
    <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
  ) : isFailed ? (
    <span className="inline-block w-2 h-2 rounded-full bg-red-400 shrink-0" />
  ) : (
    <span className="inline-block w-2 h-2 rounded-full bg-slate-600 shrink-0" />
  );

  const statusText = isDone
    ? `${task.items_found} item${task.items_found !== 1 ? "s" : ""}`
    : isProcessing
      ? "loading…"
      : isFailed
        ? "failed"
        : isSkipped
          ? "skipped"
          : "queued";

  return (
    <li className="flex items-center justify-between gap-2 text-xs">
      <span className="flex items-center gap-2 min-w-0">
        {indicator}
        <span className="text-slate-300 truncate">{label}</span>
      </span>
      <span className="text-slate-500 font-mono shrink-0">{statusText}</span>
    </li>
  );
}

interface ParcelInfoProps {
  parcel: GeocodeResponse;
  timelineRequestId: string | null;
  timelineStatus: TimelineRequest | null;
  snapshots: ImagerySnapshot[];
  imageryLoading: boolean;
}

interface DataRowProps {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}

function DataRow({ label, value, mono = false }: DataRowProps) {
  if (!value) return null;
  return (
    <div className="py-2 border-b border-navy-700/50 last:border-0">
      <p className="data-label uppercase tracking-widest text-xs mb-0.5">
        {label}
      </p>
      <p className={`text-sm text-white ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

export function ParcelInfo({
  parcel,
  timelineRequestId,
  timelineStatus,
  snapshots,
  imageryLoading,
}: ParcelInfoProps) {
  const navigate = useNavigate();
  const geocodeMutation = useGeocodeMutation();
  const selectedEvent = useAppStore((s) => s.selectedEvent);
  const setSelectedEvent = useAppStore((s) => s.setSelectedEvent);

  const isTimelineProcessing =
    imageryLoading ||
    timelineStatus?.status === "queued" ||
    timelineStatus?.status === "processing" ||
    (timelineRequestId != null && timelineStatus == null);

  const handleReset = () => {
    useAppStore.getState().reset();
    void navigate("/");
  };

  const handleSearch = (
    address: string,
    coords?: { lat: number; lon: number },
  ) => {
    geocodeMutation.mutate({ address, navigate, ...coords });
  };

  const isLoading = geocodeMutation.isPending;
  const error = geocodeMutation.error?.message ?? null;
  const isMobile = useIsMobile();

  return (
    <motion.aside
      initial={isMobile ? { opacity: 0 } : { x: "100%", opacity: 0 }}
      animate={isMobile ? { opacity: 1 } : { x: 0, opacity: 1 }}
      exit={isMobile ? { opacity: 0 } : { x: "100%", opacity: 0 }}
      transition={
        isMobile
          ? { duration: 0.2 }
          : { type: "spring", stiffness: 300, damping: 35 }
      }
      className={
        isMobile
          ? "w-full"
          : `absolute top-0 right-0 h-full w-80 bg-navy-900/95 backdrop-blur-md border-l border-navy-700/60 shadow-2xl shadow-black/50 flex flex-col z-10 overflow-hidden`
      }
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-navy-700/60">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400" />
          <span className="text-sm font-medium text-slate-300">
            Location found
          </span>
        </div>
        <button
          onClick={handleReset}
          className="text-slate-500 hover:text-white transition-colors p-1 rounded-lg hover:bg-navy-700"
          aria-label="Back to search"
          title="Back to search"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Selected event detail — top on mobile for visibility */}
      {isMobile && (
        <AnimatePresence>
          {selectedEvent && (
            <div className="px-5 border-b border-navy-700/60">
              <EventDetail
                event={selectedEvent}
                onClose={() => setSelectedEvent(null)}
              />
            </div>
          )}
        </AnimatePresence>
      )}

      {/* Content */}
      <div
        className={isMobile ? "px-5 py-4" : "flex-1 overflow-y-auto px-5 py-4"}
      >
        {/* Address */}
        <div className="mb-6">
          <p className="data-label uppercase tracking-widest mb-2">Address</p>
          <p className="text-white text-base font-medium leading-snug">
            {parcel.normalized_address ?? parcel.address}
          </p>
          {parcel.is_new && (
            <span className="inline-block mt-2 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              New entry
            </span>
          )}
        </div>

        {/* Metadata rows */}
        <div className="space-y-0">
          <DataRow
            label="Coordinates"
            value={`${parcel.latitude.toFixed(6)}, ${parcel.longitude.toFixed(6)}`}
            mono
          />
          <DataRow
            label="Census Tract"
            value={parcel.census_tract ?? null}
            mono
          />
          <DataRow label="Parcel ID" value={parcel.parcel_id} mono />
        </div>

        {/* Timeline status */}
        <div className="mt-6">
          <p className="data-label uppercase tracking-widest text-xs mb-2">
            Timeline
          </p>
          {isTimelineProcessing ? (
            timelineStatus?.tasks?.length ? (
              <ul className="flex flex-col gap-1">
                {timelineStatus.tasks.map((t) => (
                  <TaskRow key={t.source} task={t} />
                ))}
              </ul>
            ) : (
              <div className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
                <span className="text-xs text-slate-400">
                  Searching for historical imagery&hellip;
                </span>
              </div>
            )
          ) : (
            <p className="text-sm text-white">
              {snapshots.length} item{snapshots.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>

        {/* Demographics */}
        <div className="mt-6 -mx-5">
          <DemographicsPanel
            parcelId={parcel.parcel_id}
            enabled={
              timelineStatus?.status === "complete" ||
              (timelineRequestId == null && snapshots.length > 0)
            }
            compact={isMobile}
          />
        </div>
      </div>

      {/* Selected event detail — bottom on desktop */}
      {!isMobile && (
        <AnimatePresence>
          {selectedEvent && (
            <div className="px-5 border-t border-navy-700/60">
              <EventDetail
                event={selectedEvent}
                onClose={() => setSelectedEvent(null)}
              />
            </div>
          )}
        </AnimatePresence>
      )}

      {/* Search again footer */}
      <div className="px-5 py-4 border-t border-navy-700/60">
        <SearchInput
          onSearch={handleSearch}
          isLoading={isLoading}
          error={error}
          onClearError={() => geocodeMutation.reset()}
        />
      </div>
    </motion.aside>
  );
}
