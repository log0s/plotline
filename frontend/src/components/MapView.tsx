/**
 * MapView — MapLibre GL map centered on the geocoded parcel.
 *
 * When a snapshot is selected in the Timeline, it's displayed
 * as a raster layer with a crossfade transition via the shared
 * applyImageryLayer utility.
 */
import { useEffect, useRef, useState } from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  type MotionValue,
} from "framer-motion";
import { Info, LocateFixed } from "lucide-react";
import maplibregl from "maplibre-gl";
import { SOURCE_LABELS } from "../constants";
import { useAppStore } from "../store";
import { applyImageryLayer } from "../utils/applyImageryLayer";
import type { GeocodeResponse, ImagerySnapshot } from "../types";

interface MapViewProps {
  parcel: GeocodeResponse;
  sheetY?: MotionValue<number>;
}

// OpenFreeMap — free, no API key needed
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

function isWebGLSupported(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function MapView({ parcel, sheetY }: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const mapReadyRef = useRef(false);

  const { selectedSnapshot } = useAppStore();
  const [infoChip, setInfoChip] = useState<ImagerySnapshot | null>(null);
  const [topoTooltip, setTopoTooltip] = useState(false);
  const [webglSupported] = useState(isWebGLSupported);
  const [mapError, setMapError] = useState(false);
  const [containerH, setContainerH] = useState(0);
  const fallbackY = useMotionValue(9999);
  const sheetH = Math.min(containerH * 0.85, Math.max(0, containerH - 60));
  const chipBottom = useTransform(
    sheetY ?? fallbackY,
    (v: number) => sheetH - v + 12,
  );

  useEffect(() => {
    const el = mapContainerRef.current?.parentElement;
    if (!el) return;
    const obs = new ResizeObserver(([e]) =>
      setContainerH(e.contentRect.height),
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (!webglSupported || !mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left",
    );

    map.addControl(new maplibregl.NavigationControl(), "top-left");
    map.addControl(
      new maplibregl.ScaleControl({ unit: "imperial" }),
      "bottom-left",
    );

    map.on("load", () => {
      mapReadyRef.current = true;
      setMapError(false);
    });

    map.on("error", () => setMapError(true));
    // Clear the warning once the map settles again — tile errors are often
    // transient, and a sticky banner outlives the problem.
    map.on("idle", () => setMapError((prev) => (prev ? false : prev)));

    mapRef.current = map;

    return () => {
      mapReadyRef.current = false;
      markerRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- map init runs once; deps would remount the GL context
  }, [webglSupported]);

  useEffect(() => {
    if (!webglSupported) return;
    const map = mapRef.current;
    if (!map) return;

    markerRef.current?.remove();

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
        cursor: pointer;
      "></div>
    `;

    const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
      .setLngLat([parcel.longitude, parcel.latitude])
      .addTo(map);

    markerRef.current = marker;

    map.flyTo({
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      duration: 1400,
      essential: true,
    });
  }, [webglSupported, parcel.latitude, parcel.longitude]);

  useEffect(() => {
    if (!webglSupported) return;
    const map = mapRef.current;
    if (!map) return;

    const apply = (snap: ImagerySnapshot | null) => {
      if (!mapReadyRef.current) {
        const onLoad = () => {
          apply(snap);
          map.off("load", onLoad);
        };
        map.on("load", onLoad);
        return;
      }

      if (snap) {
        const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
        fetch(`${apiBase}/api/v1/imagery/${snap.id}/warmup`, {
          method: "POST",
        }).catch(() => {});
      }

      applyImageryLayer(map, snap);
      setInfoChip(snap);
      setTopoTooltip(false);

      const isLowRes =
        snap?.source === "landsat" || snap?.source === "sentinel2";
      if (isLowRes && map.getZoom() >= 14) {
        map.easeTo({ zoom: 13, duration: 600 });
      }
    };

    apply(selectedSnapshot);
  }, [webglSupported, selectedSnapshot, parcel.latitude, parcel.longitude]);

  if (!webglSupported) {
    return (
      <div className="relative w-full h-full flex items-center justify-center bg-navy-900">
        <div className="text-center px-6 max-w-md">
          <h3 className="text-lg font-bold text-white mb-2">
            WebGL not supported
          </h3>
          <p className="text-sm text-slate-400">
            Your browser doesn't support WebGL, which is required to display the
            interactive map. Please try a modern browser like Chrome, Firefox,
            or Edge.
          </p>
        </div>
      </div>
    );
  }

  const handleRecenter = () => {
    mapRef.current?.flyTo({
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      bearing: 0,
      pitch: 0,
      duration: 800,
      essential: true,
    });
  };

  return (
    <div className="relative w-full h-full">
      <div
        ref={mapContainerRef}
        className="w-full h-full"
        aria-label="Map view"
      />

      <button
        type="button"
        onClick={handleRecenter}
        title="Recenter on searched address"
        aria-label="Recenter on searched address"
        className="absolute top-4 right-4 md:right-[21rem] z-10 p-2 rounded-xl bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-slate-200 hover:border-amber-500/40 hover:text-amber-400 transition-colors"
      >
        <LocateFixed className="w-4 h-4" aria-hidden="true" />
      </button>

      {/* Imagery info chip */}
      {infoChip &&
        (sheetY ? (
          <motion.div
            className="absolute left-1/2 -translate-x-1/2 md:left-[calc(50%-10rem)] z-10"
            style={{ bottom: chipBottom }}
          >
            <InfoChip
              chip={infoChip}
              topoTooltip={topoTooltip}
              setTopoTooltip={setTopoTooltip}
            />
          </motion.div>
        ) : (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 md:left-[calc(50%-10rem)] z-10">
            <InfoChip
              chip={infoChip}
              topoTooltip={topoTooltip}
              setTopoTooltip={setTopoTooltip}
            />
          </div>
        ))}

      {mapError && (
        <div className="absolute bottom-2 right-2 z-10 flex items-center gap-1.5 px-2 py-1 rounded-lg bg-navy-900/90 border border-amber-500/30 text-[10px] text-amber-400">
          Some tiles failed to load
        </div>
      )}
    </div>
  );
}

function InfoChip({
  chip,
  topoTooltip,
  setTopoTooltip,
}: {
  chip: ImagerySnapshot;
  topoTooltip: boolean;
  setTopoTooltip: (v: boolean) => void;
}) {
  const isTopo = chip.source === "usgs_topo";
  const year = chip.capture_date.slice(0, 4);

  return (
    <div className="relative pointer-events-auto">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-xs font-mono text-slate-300">
        <span className="text-amber-400 font-semibold">
          {isTopo
            ? "USGS Topographic Map"
            : (SOURCE_LABELS[chip.source] ?? chip.source)}
        </span>
        <span>·</span>
        <span>{isTopo ? year : chip.capture_date}</span>
        {isTopo && (
          <>
            <span>·</span>
            <span className="text-slate-400">Not a photograph</span>
            <button
              onClick={() => setTopoTooltip(!topoTooltip)}
              className="text-slate-400 hover:text-slate-200 transition-colors"
              aria-label="About this map"
            >
              <Info size={12} />
            </button>
          </>
        )}
        {!isTopo && chip.resolution_m != null && (
          <>
            <span>·</span>
            <span>{chip.resolution_m}m res</span>
          </>
        )}
      </div>
      {isTopo && topoTooltip && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 px-3 py-2 rounded-lg bg-navy-900/95 backdrop-blur-sm border border-navy-700/60 text-xs text-slate-300 leading-relaxed">
          This is a scanned USGS topographic map, not a photograph. It shows
          terrain, roads, and land use as surveyed by cartographers at the time.
          Features include contour lines (brown), vegetation (green), water
          (blue), and man-made structures (black).
        </div>
      )}
    </div>
  );
}
