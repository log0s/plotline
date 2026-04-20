/**
 * CompareView — dual synchronized MapLibre maps with a draggable swipe divider
 * for before/after imagery comparison.
 *
 * Architecture: both maps are full-width, stacked on top of each other.
 * The right map (B) is clipped with clip-path so only the portion to
 * the right of the divider is visible, revealing map A underneath on the left.
 */
import { LocateFixed } from "lucide-react";
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
      attributionControl: {},
    });

    leftMap.addControl(new maplibregl.NavigationControl(), "bottom-left");

    const rightMap = new maplibregl.Map({
      container: rightContainerRef.current,
      style: MAP_STYLE,
      center,
      zoom: 15,
      attributionControl: false,
    });

    leftMap.on("load", () => {
      leftReadyRef.current = true;
    });
    rightMap.on("load", () => {
      rightReadyRef.current = true;
    });

    // Sync cameras
    leftMap.on("move", () => syncMaps(leftMap, rightMap));
    rightMap.on("move", () => syncMaps(rightMap, leftMap));

    // Add marker to both maps so it's visible on both sides of the divider
    for (const map of [leftMap, rightMap]) {
      const el = document.createElement("div");
      el.className = "plotline-marker";
      el.innerHTML = `
        <div style="
          width: 20px;
          height: 20px;
          background: #f59e0b;
          border: 3px solid #fff;
          border-radius: 50% 50% 50% 0;
          transform: rotate(-45deg);
          box-shadow: 0 2px 8px rgba(0,0,0,0.4);
          pointer-events: none;
        "></div>
      `;
      new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat(center)
        .addTo(map);
    }

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

  const handleRecenter = useCallback(() => {
    // Fly the left map; the sync handler mirrors camera onto the right map.
    leftMapRef.current?.flyTo({
      center: [parcel.longitude, parcel.latitude],
      bearing: 0,
      pitch: 0,
      duration: 800,
      essential: true,
    });
  }, [parcel.latitude, parcel.longitude]);

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
      setDividerPos(Math.max(0, Math.min(100, pct)));
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
    <div ref={containerRef} className="relative w-full h-full select-none overflow-hidden">
      {/* Map A (left / underneath) — full size */}
      <div ref={leftContainerRef} className="absolute inset-0" />

      {/* Map B (right / on top) — full size, clipped to show only right of divider */}
      <div
        className="absolute inset-0"
        style={{ clipPath: `inset(0 0 0 ${dividerPos}%)` }}
      >
        <div ref={rightContainerRef} className="w-full h-full" />
      </div>

      {/* Divider line (visual only, no pointer events) */}
      <div
        className="absolute top-0 bottom-0 z-[5] pointer-events-none"
        style={{ left: `${dividerPos}%`, transform: "translateX(-50%)", width: "4px" }}
      >
        <div className="w-1 h-full bg-amber-400/80 mx-auto" />
      </div>

      {/* Drag handle (centered on divider) */}
      <div
        className="absolute z-[5] cursor-col-resize"
        style={{
          left: `${dividerPos}%`,
          top: "50%",
          transform: "translate(-50%, -50%)",
          width: "40px",
          height: "40px",
        }}
        onMouseDown={handleDragStart}
        onTouchStart={handleDragStart}
      >
        <div className="w-8 h-8 mx-auto mt-1 rounded-full bg-navy-900/90 border-2 border-amber-400 flex items-center justify-center shadow-lg">
          <svg className="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l-3 3 3 3M16 9l3 3-3 3" />
          </svg>
        </div>
      </div>

      {/* Labels */}
      {snapA && (
        <div className="absolute top-14 left-3 z-30">
          <SnapshotLabel snapshot={snapA} side="A" />
        </div>
      )}
      {snapB && (
        <div className="absolute top-14 right-3 z-30">
          <SnapshotLabel snapshot={snapB} side="B" />
        </div>
      )}

      {/* Recenter button */}
      <button
        type="button"
        onClick={handleRecenter}
        title="Recenter on searched address"
        aria-label="Recenter on searched address"
        className="absolute top-4 right-4 z-30 p-2 rounded-xl bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-slate-200 hover:border-amber-500/40 hover:text-amber-400 transition-colors"
      >
        <LocateFixed className="w-4 h-4" aria-hidden="true" />
      </button>

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

      // Landsat/Sentinel look bad when zoomed in too close — matches MapView
      const isLowRes =
        snapshot?.source === "landsat" || snapshot?.source === "sentinel2";
      if (isLowRes && map.getZoom() >= 14) {
        map.easeTo({ zoom: 13, duration: 600 });
      }
    };

    apply();
  }, [mapRef, readyRef, snapshot, parcel.latitude, parcel.longitude]);
}
