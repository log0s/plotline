/**
 * CompareView — dual synchronized MapLibre maps with a draggable swipe divider
 * for before/after imagery comparison.
 *
 * Architecture: both maps are full-width, stacked on top of each other.
 * The right map (B) is clipped with clip-path so only the portion to
 * the right of the divider is visible, revealing map A underneath on the left.
 */
import maplibregl from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { applyImageryLayer } from "../utils/applyImageryLayer";
import { useAppStore } from "../store";
import type { GeocodeResponse, ImagerySnapshot } from "../types";

interface CompareViewProps {
  parcel: GeocodeResponse;
}

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const SOURCE_LABELS: Record<string, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
};

function formatDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export function CompareView({ parcel }: CompareViewProps) {
  const { compareSnapshots, setCompareMode } = useAppStore();
  const [snapA, snapB] = compareSnapshots;

  const containerRef = useRef<HTMLDivElement>(null);
  const leftMapRef = useRef<maplibregl.Map | null>(null);
  const rightMapRef = useRef<maplibregl.Map | null>(null);
  const leftContainerRef = useRef<HTMLDivElement>(null);
  const rightContainerRef = useRef<HTMLDivElement>(null);
  const leftReadyRef = useRef(false);
  const rightReadyRef = useRef(false);
  const syncingRef = useRef(false);

  const [dividerPos, setDividerPos] = useState(50); // percentage
  const isDraggingRef = useRef(false);

  // Exit on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCompareMode(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [setCompareMode]);

  // Sync cameras between maps
  const syncMaps = useCallback(
    (source: maplibregl.Map, target: maplibregl.Map) => {
      if (syncingRef.current) return;
      syncingRef.current = true;
      target.jumpTo({
        center: source.getCenter(),
        zoom: source.getZoom(),
        bearing: source.getBearing(),
        pitch: source.getPitch(),
      });
      syncingRef.current = false;
    },
    [],
  );

  // Initialize both maps — both are full-size, stacked
  useEffect(() => {
    if (!leftContainerRef.current || !rightContainerRef.current) return;

    const center: [number, number] = [parcel.longitude, parcel.latitude];

    const leftMap = new maplibregl.Map({
      container: leftContainerRef.current,
      style: MAP_STYLE,
      center,
      zoom: 15,
      attributionControl: false,
    });

    const rightMap = new maplibregl.Map({
      container: rightContainerRef.current,
      style: MAP_STYLE,
      center,
      zoom: 15,
      attributionControl: true,
    });

    rightMap.addControl(new maplibregl.NavigationControl(), "top-right");

    leftMap.on("load", () => {
      leftReadyRef.current = true;
    });
    rightMap.on("load", () => {
      rightReadyRef.current = true;
    });

    // Sync cameras
    leftMap.on("move", () => syncMaps(leftMap, rightMap));
    rightMap.on("move", () => syncMaps(rightMap, leftMap));

    leftMapRef.current = leftMap;
    rightMapRef.current = rightMap;

    return () => {
      leftReadyRef.current = false;
      rightReadyRef.current = false;
      leftMap.remove();
      rightMap.remove();
      leftMapRef.current = null;
      rightMapRef.current = null;
    };
  }, [parcel.latitude, parcel.longitude, syncMaps]);

  // Apply imagery to left map (snapshot A)
  useApplySnapshot(leftMapRef, leftReadyRef, snapA, parcel);

  // Apply imagery to right map (snapshot B)
  useApplySnapshot(rightMapRef, rightReadyRef, snapB, parcel);

  // Draggable divider handlers
  const handleDragStart = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
  }, []);

  useEffect(() => {
    const handleDrag = (e: MouseEvent | TouchEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const clientX = "touches" in e ? e.touches[0].clientX : e.clientX;
      const pct = ((clientX - rect.left) / rect.width) * 100;
      setDividerPos(Math.max(5, Math.min(95, pct)));
    };

    const handleDragEnd = () => {
      isDraggingRef.current = false;
    };

    document.addEventListener("mousemove", handleDrag);
    document.addEventListener("mouseup", handleDragEnd);
    document.addEventListener("touchmove", handleDrag);
    document.addEventListener("touchend", handleDragEnd);

    return () => {
      document.removeEventListener("mousemove", handleDrag);
      document.removeEventListener("mouseup", handleDragEnd);
      document.removeEventListener("touchmove", handleDrag);
      document.removeEventListener("touchend", handleDragEnd);
    };
  }, []);

  return (
    <div ref={containerRef} className="relative w-full h-full select-none">
      {/* Map A (left / underneath) — full size */}
      <div ref={leftContainerRef} className="absolute inset-0" />

      {/* Map B (right / on top) — full size, clipped to show only right of divider */}
      <div
        className="absolute inset-0"
        style={{ clipPath: `inset(0 0 0 ${dividerPos}%)` }}
      >
        <div ref={rightContainerRef} className="w-full h-full" />
      </div>

      {/* Draggable divider */}
      <div
        className="absolute top-0 bottom-0 z-20 cursor-col-resize"
        style={{ left: `${dividerPos}%`, transform: "translateX(-50%)", width: "40px" }}
        onMouseDown={handleDragStart}
        onTouchStart={handleDragStart}
      >
        {/* Visible divider line */}
        <div className="absolute left-1/2 -translate-x-1/2 top-0 bottom-0 w-1 bg-amber-400/80" />
        {/* Drag handle */}
        <div className="absolute top-1/2 left-1/2 -translate-y-1/2 -translate-x-1/2 w-8 h-8 rounded-full bg-navy-900/90 border-2 border-amber-400 flex items-center justify-center shadow-lg">
          <svg className="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l-3 3 3 3M16 9l3 3-3 3" />
          </svg>
        </div>
      </div>

      {/* Labels */}
      {snapA && (
        <div className="absolute top-3 left-3 z-10">
          <SnapshotLabel snapshot={snapA} side="A" />
        </div>
      )}
      {snapB && (
        <div className="absolute top-3 right-3 z-10">
          <SnapshotLabel snapshot={snapB} side="B" />
        </div>
      )}

      {/* Exit button */}
      <button
        onClick={() => setCompareMode(false)}
        className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 px-4 py-2 rounded-xl bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-sm text-white hover:border-amber-500/40 transition-colors"
      >
        Exit Compare
      </button>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function SnapshotLabel({
  snapshot,
  side,
}: {
  snapshot: ImagerySnapshot;
  side: "A" | "B";
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-xs">
      <span className="text-amber-400 font-bold">{side}</span>
      <span className="text-slate-300 font-mono">
        {SOURCE_LABELS[snapshot.source] ?? snapshot.source}
      </span>
      <span className="text-slate-500">·</span>
      <span className="text-slate-300">{formatDate(snapshot.capture_date)}</span>
    </div>
  );
}

/**
 * Hook to apply a snapshot to a map ref, handling the load-ready timing.
 */
function useApplySnapshot(
  mapRef: React.RefObject<maplibregl.Map | null>,
  readyRef: React.RefObject<boolean>,
  snapshot: ImagerySnapshot | null,
  parcel: GeocodeResponse,
) {
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!readyRef.current) {
        const onLoad = () => {
          apply();
          map.off("load", onLoad);
        };
        map.on("load", onLoad);
        return;
      }
      applyImageryLayer(map, snapshot, {
        lat: parcel.latitude,
        lng: parcel.longitude,
      });
    };

    apply();
  }, [mapRef, readyRef, snapshot, parcel.latitude, parcel.longitude]);
}
