/**
 * Timeline — horizontal scrollable imagery timeline.
 *
 * Renders thumbnail cards for each imagery snapshot, sorted chronologically.
 * Clicking a card selects it and updates the map imagery layer.
 * Source filter toggles let users show/hide NAIP, Landsat, and Sentinel-2.
 * Keyboard arrow keys navigate between snapshots.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "../store";
import type { ImagerySnapshot, ImagerySource } from "../types";

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

// ── Component ──────────────────────────────────────────────────────────────────

export function Timeline() {
  const {
    snapshots,
    selectedSnapshot,
    timelineStatus,
    setSelectedSnapshot,
  } = useAppStore();

  const [activeFilters, setActiveFilters] = useState<Set<ImagerySource>>(
    new Set(["naip", "landsat", "sentinel2"]),
  );

  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Filter snapshots by active source toggles
  const visible = snapshots.filter((s) =>
    activeFilters.has(s.source as ImagerySource),
  );

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!visible.length) return;
      const idx = selectedSnapshot
        ? visible.findIndex((s) => s.id === selectedSnapshot.id)
        : -1;

      if (e.key === "ArrowRight") {
        const next = visible[Math.min(idx + 1, visible.length - 1)];
        if (next) setSelectedSnapshot(next);
        e.preventDefault();
      } else if (e.key === "ArrowLeft") {
        const prev = visible[Math.max(idx - 1, 0)];
        if (prev) setSelectedSnapshot(prev);
        e.preventDefault();
      }
    },
    [visible, selectedSnapshot, setSelectedSnapshot],
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
        // Don't allow deselecting all filters
        if (next.size > 1) next.delete(source);
      } else {
        next.add(source);
      }
      return next;
    });
  };

  const isProcessing =
    timelineStatus?.status === "queued" ||
    timelineStatus?.status === "processing";

  const isEmpty = !isProcessing && snapshots.length === 0;

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
                : "Searching for historical imagery…"
              : `${visible.length} scene${visible.length !== 1 ? "s" : ""}`}
          </span>
        </div>

        {/* Source filter toggles */}
        {snapshots.length > 0 && (
          <div className="flex items-center gap-1.5 shrink-0 ml-3">
            {(["naip", "landsat", "sentinel2"] as ImagerySource[]).map((src) => {
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
          </div>
        )}
      </div>

      {/* Scrollable thumbnail strip */}
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
          {visible.map((snap) => (
            <SnapshotCard
              key={snap.id}
              snapshot={snap}
              isSelected={selectedSnapshot?.id === snap.id}
              onSelect={setSelectedSnapshot}
            />
          ))}
        </AnimatePresence>
      </div>
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
      title={`${SOURCE_LABELS[source]} · ${snapshot.capture_date}${
        snapshot.cloud_cover_pct != null
          ? ` · ${snapshot.cloud_cover_pct.toFixed(0)}% cloud`
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
