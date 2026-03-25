/**
 * Timeline — horizontal scrollable imagery timeline with interleaved property events.
 *
 * Renders thumbnail cards for each imagery snapshot AND property event cards,
 * sorted chronologically. Clicking a card selects it and updates the map
 * imagery layer.
 *
 * Source filter toggles let users show/hide imagery sources and event types.
 * Keyboard arrow keys navigate between snapshots.
 */
import { AnimatePresence, motion } from "framer-motion";
import {
  DollarSign,
  Hammer,
  Trash2,
  Wrench,
  Zap,
  Pipette,
  FileText,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "../store";
import type {
  ImagerySnapshot,
  ImagerySource,
  PropertyEvent,
  PropertyEventType,
} from "../types";

// ── Source badge colours ───────────────────────────────────────────────────────

const SOURCE_COLORS: Record<ImagerySource, string> = {
  naip: "bg-emerald-600 text-emerald-100",
  landsat: "bg-blue-700 text-blue-100",
  sentinel2: "bg-violet-700 text-violet-100",
};

const SOURCE_LABELS: Record<ImagerySource, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
};

// ── Event type config ─────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const EVENT_TYPE_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ComponentType<any> }
> = {
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

// ── Unified timeline item type ───────────────────────────────────────────────

type TimelineItem =
  | { kind: "imagery"; data: ImagerySnapshot; dateStr: string }
  | { kind: "event"; data: PropertyEvent; dateStr: string };

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDate(isoDate: string): string {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function progressLabel(
  tasks: { source: string; status: string; items_found: number }[],
): string {
  const done = tasks.filter((t) => t.status === "complete");
  const processing = tasks.find((t) => t.status === "processing");
  const parts: string[] = done.map(
    (t) => `${SOURCE_LABELS[t.source as ImagerySource] ?? t.source} (${t.items_found})`,
  );
  if (processing) {
    parts.push(
      `Loading ${SOURCE_LABELS[processing.source as ImagerySource] ?? processing.source}...`,
    );
  }
  return parts.join(" · ");
}

function formatPrice(price: number): string {
  if (price >= 1_000_000) return `$${(price / 1_000_000).toFixed(1)}M`;
  if (price >= 1_000) return `$${(price / 1_000).toFixed(0)}K`;
  return `$${price}`;
}

// ── Event filter categories ──────────────────────────────────────────────────

type EventFilterKey = "sales" | "building_permits" | "other_permits";

const EVENT_FILTER_TYPES: Record<EventFilterKey, PropertyEventType[]> = {
  sales: ["sale"],
  building_permits: ["permit_building", "permit_demolition"],
  other_permits: [
    "permit_electrical",
    "permit_mechanical",
    "permit_plumbing",
    "permit_other",
    "zoning_change",
    "assessment",
  ],
};

const EVENT_FILTER_LABELS: Record<EventFilterKey, string> = {
  sales: "Sales",
  building_permits: "Permits",
  other_permits: "Other",
};

// ── Component ──────────────────────────────────────────────────────────────────

export function Timeline() {
  const {
    snapshots,
    selectedSnapshot,
    timelineStatus,
    propertyEvents,
    setSelectedSnapshot,
  } = useAppStore();

  const [activeFilters, setActiveFilters] = useState<Set<ImagerySource>>(
    new Set(["naip", "landsat", "sentinel2"]),
  );

  const [activeEventFilters, setActiveEventFilters] = useState<Set<EventFilterKey>>(
    new Set(["sales", "building_permits"]),
  );

  const [selectedEvent, setSelectedEvent] = useState<PropertyEvent | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Build unified timeline
  const visibleEventTypes = new Set<PropertyEventType>();
  for (const key of activeEventFilters) {
    for (const t of EVENT_FILTER_TYPES[key]) {
      visibleEventTypes.add(t);
    }
  }

  const items: TimelineItem[] = [];

  // Add visible imagery snapshots
  for (const snap of snapshots) {
    if (!activeFilters.has(snap.source as ImagerySource)) continue;
    items.push({ kind: "imagery", data: snap, dateStr: snap.capture_date });
  }

  // Add visible property events
  if (propertyEvents?.events) {
    for (const evt of propertyEvents.events) {
      if (!visibleEventTypes.has(evt.event_type)) continue;
      if (evt.event_date) {
        items.push({ kind: "event", data: evt, dateStr: evt.event_date });
      }
    }
  }

  // Sort chronologically
  items.sort((a, b) => a.dateStr.localeCompare(b.dateStr));

  // Imagery-only items for keyboard nav
  const visibleSnapshots = items
    .filter((i): i is TimelineItem & { kind: "imagery" } => i.kind === "imagery")
    .map((i) => i.data);

  // Keyboard navigation (imagery only)
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!visibleSnapshots.length) return;
      const idx = selectedSnapshot
        ? visibleSnapshots.findIndex((s) => s.id === selectedSnapshot.id)
        : -1;

      if (e.key === "ArrowRight") {
        const next = visibleSnapshots[Math.min(idx + 1, visibleSnapshots.length - 1)];
        if (next) setSelectedSnapshot(next);
        e.preventDefault();
      } else if (e.key === "ArrowLeft") {
        const prev = visibleSnapshots[Math.max(idx - 1, 0)];
        if (prev) setSelectedSnapshot(prev);
        e.preventDefault();
      }
    },
    [visibleSnapshots, selectedSnapshot, setSelectedSnapshot],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // Scroll selected card into view
  useEffect(() => {
    if (!selectedSnapshot || !scrollContainerRef.current) return;
    const el = scrollContainerRef.current.querySelector(
      `[data-snapshot-id="${selectedSnapshot.id}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [selectedSnapshot]);

  const toggleFilter = (source: ImagerySource) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(source)) {
        if (next.size > 1) next.delete(source);
      } else {
        next.add(source);
      }
      return next;
    });
  };

  const toggleEventFilter = (key: EventFilterKey) => {
    setActiveEventFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const isProcessing =
    timelineStatus?.status === "queued" ||
    timelineStatus?.status === "processing";

  const isEmpty = !isProcessing && snapshots.length === 0;

  const hasEvents = (propertyEvents?.events?.length ?? 0) > 0;

  return (
    <div className="flex flex-col bg-navy-950/95 border-t border-navy-700/60 select-none">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-navy-800/60">
        {/* Status / progress text */}
        <div className="flex items-center gap-2 min-w-0">
          {isProcessing && (
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          )}
          <span className="text-xs text-slate-400 truncate">
            {isProcessing
              ? timelineStatus?.tasks?.length
                ? progressLabel(timelineStatus.tasks)
                : "Searching for historical imagery\u2026"
              : `${items.length} item${items.length !== 1 ? "s" : ""}`}
          </span>
        </div>

        {/* Filter toggles */}
        <div className="flex items-center gap-1.5 shrink-0 ml-3">
          {/* Imagery source toggles */}
          {snapshots.length > 0 &&
            (["naip", "landsat", "sentinel2"] as ImagerySource[]).map((src) => {
              const hasItems = snapshots.some((s) => s.source === src);
              if (!hasItems) return null;
              const active = activeFilters.has(src);
              return (
                <button
                  key={src}
                  onClick={() => toggleFilter(src)}
                  className={`px-2 py-0.5 rounded text-[10px] font-medium transition-opacity ${
                    active ? SOURCE_COLORS[src] : "bg-navy-800 text-slate-500"
                  }`}
                  title={`${active ? "Hide" : "Show"} ${SOURCE_LABELS[src]}`}
                >
                  {SOURCE_LABELS[src]}
                </button>
              );
            })}

          {/* Event filter toggles */}
          {hasEvents && (
            <>
              <span className="w-px h-4 bg-navy-700/60 mx-1" />
              {(Object.keys(EVENT_FILTER_LABELS) as EventFilterKey[]).map((key) => {
                const active = activeEventFilters.has(key);
                return (
                  <button
                    key={key}
                    onClick={() => toggleEventFilter(key)}
                    className={`px-2 py-0.5 rounded text-[10px] font-medium transition-opacity ${
                      active
                        ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                        : "bg-navy-800 text-slate-500"
                    }`}
                    title={`${active ? "Hide" : "Show"} ${EVENT_FILTER_LABELS[key]}`}
                  >
                    {EVENT_FILTER_LABELS[key]}
                  </button>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* Scrollable timeline strip */}
      <div
        ref={scrollContainerRef}
        className="flex items-end gap-3 px-4 py-3 overflow-x-auto scrollbar-thin scrollbar-thumb-navy-700 scrollbar-track-transparent"
        style={{ minHeight: "96px" }}
      >
        {isEmpty && (
          <div className="flex items-center justify-center w-full py-4 text-xs text-slate-500 text-center px-8">
            No historical imagery found for this location.
            <br />
            This can happen for very rural areas or outside the continental US.
          </div>
        )}

        {isProcessing && snapshots.length === 0 && (
          <div className="flex items-center gap-3 py-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="w-16 h-16 rounded-md bg-navy-800 animate-pulse shrink-0"
                style={{ animationDelay: `${i * 100}ms` }}
              />
            ))}
          </div>
        )}

        <AnimatePresence initial={false}>
          {items.map((item) =>
            item.kind === "imagery" ? (
              <SnapshotCard
                key={`img-${item.data.id}`}
                snapshot={item.data}
                isSelected={selectedSnapshot?.id === item.data.id}
                onSelect={setSelectedSnapshot}
              />
            ) : (
              <EventCard
                key={`evt-${item.data.id}`}
                event={item.data}
                isSelected={selectedEvent?.id === item.data.id}
                onSelect={setSelectedEvent}
              />
            ),
          )}
        </AnimatePresence>
      </div>

      {/* Event detail popover */}
      <AnimatePresence>
        {selectedEvent && (
          <EventDetailPopover
            event={selectedEvent}
            onClose={() => setSelectedEvent(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Snapshot card ─────────────────────────────────────────────────────────────

interface SnapshotCardProps {
  snapshot: ImagerySnapshot;
  isSelected: boolean;
  onSelect: (snap: ImagerySnapshot) => void;
}

function SnapshotCard({ snapshot, isSelected, onSelect }: SnapshotCardProps) {
  const [imgError, setImgError] = useState(false);
  const source = snapshot.source as ImagerySource;

  return (
    <motion.button
      data-snapshot-id={snapshot.id}
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.2 }}
      onClick={() => onSelect(snapshot)}
      className={`relative flex flex-col items-center gap-1 shrink-0 group focus:outline-none`}
      title={`${SOURCE_LABELS[source]} \u00b7 ${snapshot.capture_date}${
        snapshot.cloud_cover_pct != null
          ? ` \u00b7 ${snapshot.cloud_cover_pct.toFixed(0)}% cloud`
          : ""
      }`}
    >
      {/* Thumbnail */}
      <div
        className={`relative w-16 h-16 rounded-md overflow-hidden transition-all duration-150 ${
          isSelected
            ? "ring-2 ring-amber-400 ring-offset-1 ring-offset-navy-950"
            : "ring-1 ring-navy-700 group-hover:ring-navy-500"
        }`}
      >
        {snapshot.thumbnail_url && !imgError ? (
          <img
            src={snapshot.thumbnail_url}
            alt={`${source} ${snapshot.capture_date}`}
            className="w-full h-full object-cover"
            loading="lazy"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-full h-full bg-navy-800 flex items-center justify-center">
            <span className="text-[9px] text-slate-500 font-mono leading-tight text-center px-1">
              {snapshot.capture_date.slice(0, 4)}
            </span>
          </div>
        )}

        {/* Selected overlay */}
        {isSelected && (
          <div className="absolute inset-0 bg-amber-400/10 pointer-events-none" />
        )}
      </div>

      {/* Source badge */}
      <span
        className={`px-1.5 py-0.5 rounded text-[9px] font-medium leading-none ${SOURCE_COLORS[source]}`}
      >
        {SOURCE_LABELS[source]}
      </span>

      {/* Date label */}
      <span className="text-[9px] font-mono text-slate-500 leading-none">
        {formatDate(snapshot.capture_date)}
      </span>
    </motion.button>
  );
}

// ── Event card ────────────────────────────────────────────────────────────────

interface EventCardProps {
  event: PropertyEvent;
  isSelected: boolean;
  onSelect: (event: PropertyEvent) => void;
}

function EventCard({ event, isSelected, onSelect }: EventCardProps) {
  const config = EVENT_TYPE_CONFIG[event.event_type] ?? EVENT_TYPE_CONFIG.permit_other;
  const Icon = config.icon;

  return (
    <motion.button
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.2 }}
      onClick={() => onSelect(event)}
      className="relative flex flex-col items-center gap-1 shrink-0 group focus:outline-none"
      title={event.description ?? config.label}
    >
      {/* Icon card */}
      <div
        className={`relative w-16 h-16 rounded-md overflow-hidden transition-all duration-150 flex flex-col items-center justify-center gap-1 ${
          isSelected
            ? "ring-2 ring-amber-400 ring-offset-1 ring-offset-navy-950 bg-navy-800"
            : "ring-1 ring-navy-700 group-hover:ring-navy-500 bg-navy-850"
        }`}
        style={{ backgroundColor: isSelected ? undefined : "rgb(20 27 45)" }}
      >
        <Icon size={18} className="text-slate-300" />
        {event.event_type === "sale" && event.sale_price ? (
          <span className="text-[9px] font-mono font-bold text-amber-400 leading-none">
            {formatPrice(event.sale_price)}
          </span>
        ) : (
          <span className="text-[8px] text-slate-500 leading-none text-center px-0.5">
            {config.label}
          </span>
        )}
      </div>

      {/* Event type badge */}
      <span
        className={`px-1.5 py-0.5 rounded text-[9px] font-medium leading-none ${config.color}`}
      >
        {config.label}
      </span>

      {/* Date label */}
      <span className="text-[9px] font-mono text-slate-500 leading-none">
        {event.event_date ? formatDate(event.event_date) : "No date"}
      </span>
    </motion.button>
  );
}

// ── Event detail popover ──────────────────────────────────────────────────────

function EventDetailPopover({
  event,
  onClose,
}: {
  event: PropertyEvent;
  onClose: () => void;
}) {
  const config = EVENT_TYPE_CONFIG[event.event_type] ?? EVENT_TYPE_CONFIG.permit_other;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.15 }}
      className="mx-4 mb-2 rounded-lg bg-navy-900/95 border border-navy-700/60 px-4 py-3 shadow-xl backdrop-blur-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-1.5 rounded-md ${config.color}`}>
            <Icon size={14} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {event.description ?? config.label}
            </p>
            <p className="text-[11px] text-slate-400">
              {event.event_date ? new Date(event.event_date + "T00:00:00").toLocaleDateString(
                "en-US",
                { year: "numeric", month: "long", day: "numeric" },
              ) : "Date unknown"}
              {" \u00b7 "}
              {event.source.replace("_", " ")}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-navy-800 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
        >
          <X size={14} />
        </button>
      </div>

      {/* Detail fields */}
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        {event.sale_price != null && event.sale_price > 0 && (
          <div>
            <span className="text-slate-500">Sale Price</span>
            <p className="text-amber-400 font-mono font-medium">
              ${event.sale_price.toLocaleString()}
            </p>
          </div>
        )}
        {event.permit_type && (
          <div>
            <span className="text-slate-500">Permit Type</span>
            <p className="text-slate-300">{event.permit_type}</p>
          </div>
        )}
        {event.permit_valuation != null && event.permit_valuation > 0 && (
          <div>
            <span className="text-slate-500">Valuation</span>
            <p className="text-slate-300 font-mono">
              ${event.permit_valuation.toLocaleString()}
            </p>
          </div>
        )}
        {event.permit_description && (
          <div className="col-span-2">
            <span className="text-slate-500">Description</span>
            <p className="text-slate-300">{event.permit_description}</p>
          </div>
        )}
      </div>
    </motion.div>
  );
}
