/**
 * ParcelInfo — sidebar panel displaying geocoded parcel metadata.
 *
 * Shows the normalized address, coordinates, census tract, and
 * a search-again input. Uses React Router for navigation.
 */
import { AnimatePresence, motion } from "framer-motion";
import {
  DollarSign,
  FileText,
  Hammer,
  Pipette,
  Trash2,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DemographicsPanel } from "./DemographicsPanel";
import { useAddressAutocomplete } from "../hooks/useAddressAutocomplete";
import { useGeocoder } from "../hooks/useGeocoder";
import { useAppStore } from "../store";
import type { GeocodeResponse, PropertyEvent } from "../types";

const SOURCE_LABELS: Record<string, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
};

function progressLabel(
  tasks: { source: string; status: string; items_found: number }[],
): string {
  const done = tasks.filter((t) => t.status === "complete");
  const processing = tasks.find((t) => t.status === "processing");
  const parts: string[] = done.map(
    (t) => `${SOURCE_LABELS[t.source] ?? t.source} (${t.items_found})`,
  );
  if (processing) {
    parts.push(`Loading ${SOURCE_LABELS[processing.source] ?? processing.source}...`);
  }
  return parts.join(" · ");
}

interface ParcelInfoProps {
  parcel: GeocodeResponse;
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
      <p className="data-label uppercase tracking-widest text-xs mb-0.5">{label}</p>
      <p className={`text-sm text-white ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const EVENT_TYPE_CONFIG: Record<string, { label: string; color: string; icon: React.ComponentType<any> }> = {
  sale: { label: "Sale", color: "bg-amber-500 text-amber-50", icon: DollarSign },
  permit_building: { label: "Building", color: "bg-orange-600 text-orange-50", icon: Hammer },
  permit_demolition: { label: "Demolition", color: "bg-red-600 text-red-50", icon: Trash2 },
  permit_electrical: { label: "Electrical", color: "bg-yellow-600 text-yellow-50", icon: Zap },
  permit_mechanical: { label: "Mechanical", color: "bg-slate-600 text-slate-50", icon: Wrench },
  permit_plumbing: { label: "Plumbing", color: "bg-sky-600 text-sky-50", icon: Pipette },
  permit_other: { label: "Permit", color: "bg-slate-600 text-slate-50", icon: FileText },
  zoning_change: { label: "Zoning", color: "bg-purple-600 text-purple-50", icon: FileText },
  assessment: { label: "Assessment", color: "bg-teal-600 text-teal-50", icon: FileText },
};

export function ParcelInfo({ parcel }: ParcelInfoProps) {
  const navigate = useNavigate();
  const { geocode } = useGeocoder();
  const isLoading = useAppStore((s) => s.isLoading);
  const selectedEvent = useAppStore((s) => s.selectedEvent);
  const setSelectedEvent = useAppStore((s) => s.setSelectedEvent);
  const timelineRequestId = useAppStore((s) => s.timelineRequestId);
  const timelineStatus = useAppStore((s) => s.timelineStatus);
  const snapshots = useAppStore((s) => s.snapshots);

  const isTimelineProcessing =
    timelineStatus?.status === "queued" ||
    timelineStatus?.status === "processing" ||
    (timelineRequestId != null && timelineStatus == null);

  const handleReset = () => {
    useAppStore.getState().reset();
    navigate("/");
  };

  const handleSearch = (address: string, coords?: { lat: number; lon: number }) => {
    geocode(address, navigate, coords);
  };

  return (
    <motion.aside
      initial={{ x: "100%", opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: "100%", opacity: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 35 }}
      className={`
        absolute top-0 right-0 h-full w-80
        bg-navy-900/95 backdrop-blur-md
        border-l border-navy-700/60
        shadow-2xl shadow-black/50
        flex flex-col z-10
        overflow-hidden
      `}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-navy-700/60">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400" />
          <span className="text-sm font-medium text-slate-300">Location found</span>
        </div>
        <button
          onClick={handleReset}
          className="text-slate-500 hover:text-white transition-colors p-1 rounded-lg hover:bg-navy-700"
          aria-label="Back to search"
          title="Back to search"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
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
          <DataRow
            label="Parcel ID"
            value={parcel.parcel_id}
            mono
          />
        </div>

        {/* Timeline status */}
        <div className="mt-6">
          <p className="data-label uppercase tracking-widest text-xs mb-2">Timeline</p>
          {isTimelineProcessing ? (
            <div className="flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
              <span className="text-xs text-slate-400">
                {timelineStatus?.tasks?.length
                  ? progressLabel(timelineStatus.tasks)
                  : "Searching for historical imagery\u2026"}
              </span>
            </div>
          ) : (
            <p className="text-sm text-white">
              {snapshots.length} item{snapshots.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>

        {/* Demographics */}
        <div className="mt-6 -mx-5">
          <DemographicsPanel />
        </div>
      </div>

      {/* Selected event detail */}
      <AnimatePresence>
        {selectedEvent && (
          <div className="px-5 border-t border-navy-700/60">
            <EventDetail event={selectedEvent} onClose={() => setSelectedEvent(null)} />
          </div>
        )}
      </AnimatePresence>

      {/* Search again footer */}
      <div className="px-5 py-4 border-t border-navy-700/60">
        <SearchInput onSearch={handleSearch} isLoading={isLoading} />
      </div>
    </motion.aside>
  );
}

// ── Compact inline search for the sidebar footer ─────────────────────────────

interface SearchInputProps {
  onSearch: (address: string, coords?: { lat: number; lon: number }) => void;
  isLoading: boolean;
}

function EventDetail({ event, onClose }: { event: PropertyEvent; onClose: () => void }) {
  const config = EVENT_TYPE_CONFIG[event.event_type] ?? EVENT_TYPE_CONFIG.permit_other;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      className="overflow-hidden"
    >
      <div className="mt-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded-md ${config.color}`}>
              <Icon size={14} />
            </div>
            <p className="data-label uppercase tracking-widest text-xs">
              {config.label}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-navy-700 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-0">
          {(event.description ?? null) && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">Description</p>
              <p className="text-sm text-white">{event.description}</p>
            </div>
          )}
          <div className="py-2 border-b border-navy-700/50">
            <p className="data-label uppercase tracking-widest text-xs mb-0.5">Date</p>
            <p className="text-sm text-white font-mono">
              {event.event_date
                ? new Date(event.event_date + "T00:00:00").toLocaleDateString("en-US", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })
                : "Unknown"}
            </p>
          </div>
          {event.sale_price != null && event.sale_price > 0 && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">Sale Price</p>
              <p className="text-sm text-amber-400 font-mono font-medium">
                ${event.sale_price.toLocaleString()}
              </p>
            </div>
          )}
          {event.permit_type && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">Permit Type</p>
              <p className="text-sm text-white">{event.permit_type}</p>
            </div>
          )}
          {event.permit_valuation != null && event.permit_valuation > 0 && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">Valuation</p>
              <p className="text-sm text-white font-mono">
                ${event.permit_valuation.toLocaleString()}
              </p>
            </div>
          )}
          {event.permit_description && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">Details</p>
              <p className="text-sm text-slate-300">{event.permit_description}</p>
            </div>
          )}
          <div className="py-2">
            <p className="data-label uppercase tracking-widest text-xs mb-0.5">Source</p>
            <p className="text-sm text-slate-300">{event.source.replace("_", " ")}</p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function SearchInput({ onSearch, isLoading }: SearchInputProps) {
  const { setQuery, suggestions, clear } = useAddressAutocomplete();
  const [value, setValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSelect = (displayName: string, lat: number, lon: number) => {
    setValue("");
    setShowSuggestions(false);
    clear();
    onSearch(displayName, { lat, lon });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (highlightIndex >= 0 && highlightIndex < suggestions.length) {
      const s = suggestions[highlightIndex];
      handleSelect(s.display_name, s.lat, s.lon);
      return;
    }
    const addr = value.trim();
    if (addr.length >= 5) {
      setValue("");
      clear();
      setShowSuggestions(false);
      onSearch(addr);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative flex gap-2">
      <div className="relative flex-1">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setQuery(e.target.value);
            setShowSuggestions(true);
            setHighlightIndex(-1);
          }}
          onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder="Search another address..."
          disabled={isLoading}
          className={`
            w-full px-3 py-2 rounded-xl bg-navy-800 border border-navy-600
            text-sm text-white placeholder-slate-500
            focus:outline-none focus:border-amber-500/60
            disabled:opacity-50
          `}
        />
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute left-0 right-0 bottom-full mb-1 z-50 bg-navy-800 border border-navy-600 rounded-xl shadow-2xl shadow-black/40 overflow-hidden">
            {suggestions.map((s, i) => {
              const parts = s.display_name.split(", ");
              const primary = parts[0];
              const secondary = parts.slice(1).join(", ");
              return (
                <button
                  key={`${s.lat}-${s.lon}-${i}`}
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleSelect(s.display_name, s.lat, s.lon);
                  }}
                  onMouseEnter={() => setHighlightIndex(i)}
                  className={`
                    w-full text-left px-3 py-2 flex items-start gap-2
                    transition-colors duration-75
                    ${i === highlightIndex ? "bg-navy-700" : "hover:bg-navy-700/50"}
                    ${i > 0 ? "border-t border-navy-700/40" : ""}
                  `}
                >
                  <svg
                    className="w-3.5 h-3.5 text-slate-500 mt-0.5 shrink-0"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a2 2 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <div className="min-w-0">
                    <span className="text-xs text-white block truncate">{primary}</span>
                    {secondary && (
                      <span className="text-[11px] text-slate-400 block truncate">{secondary}</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <button
        type="submit"
        disabled={isLoading}
        className="px-3 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 text-sm font-medium disabled:opacity-50 transition-colors shrink-0"
      >
        {isLoading ? "..." : "Go"}
      </button>
    </form>
  );
}
