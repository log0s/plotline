/**
 * MapView — MapLibre GL map centered on the geocoded parcel.
 *
 * When a snapshot is selected in the Timeline, it's displayed
 * as a raster layer with a crossfade transition via the shared
 * applyImageryLayer utility.
 */
import { motion, useMotionValue, useTransform, type MotionValue } from "framer-motion";
import { LocateFixed } from "lucide-react";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { applyImageryLayer } from "../utils/applyImageryLayer";
import { useAppStore } from "../store";
import type { GeocodeResponse, ImagerySnapshot } from "../types";

interface MapViewProps {
  parcel: GeocodeResponse;
  sheetY?: MotionValue<number>;
}

// OpenFreeMap — free, no API key needed
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const SOURCE_LABELS: Record<string, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
};

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
    const obs = new ResizeObserver(([e]) => setContainerH(e.contentRect.height));
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  if (!webglSupported) {
    return (
      <div className="relative w-full h-full flex items-center justify-center bg-navy-900">
        <div className="text-center px-6 max-w-md">
          <h3 className="text-lg font-bold text-white mb-2">WebGL not supported</h3>
          <p className="text-sm text-slate-400">
            Your browser doesn't support WebGL, which is required to display
            the interactive map. Please try a modern browser like Chrome, Firefox,
            or Edge.
          </p>
        </div>
      </div>
    );
  }

  // Initialise map on mount
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      attributionControl: false,
    });

    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

    map.addControl(new maplibregl.NavigationControl(), "top-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    map.on("load", () => {
      mapReadyRef.current = true;
      setMapError(false);
    });

    map.on("error", () => setMapError(true));

    mapRef.current = map;

    return () => {
      mapReadyRef.current = false;
      markerRef.current?.remove();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only runs once on mount

  // Update marker whenever parcel changes
  useEffect(() => {
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
  }, [parcel.latitude, parcel.longitude]);

  // Apply selected imagery snapshot as a raster layer
  useEffect(() => {
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

      applyImageryLayer(map, snap, {
        lat: parcel.latitude,
        lng: parcel.longitude,
      });
      setInfoChip(snap);

      // Landsat/Sentinel look bad when zoomed in too close
      const isLowRes =
        snap?.source === "landsat" || snap?.source === "sentinel2";
      if (isLowRes && map.getZoom() >= 14) {
        map.easeTo({ zoom: 13, duration: 600 });
      }
    };

    apply(selectedSnapshot);
  }, [selectedSnapshot, parcel.latitude, parcel.longitude]);

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
      {infoChip && (sheetY ? (
        <motion.div
          className="absolute left-1/2 -translate-x-1/2 z-10 pointer-events-none"
          style={{ bottom: chipBottom }}
        >
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-xs font-mono text-slate-300">
            <span className="text-amber-400 font-semibold">
              {SOURCE_LABELS[infoChip.source] ?? infoChip.source}
            </span>
            <span>·</span>
            <span>{infoChip.capture_date}</span>
            {infoChip.resolution_m != null && (
              <>
                <span>·</span>
                <span>{infoChip.resolution_m}m res</span>
              </>
            )}
          </div>
        </motion.div>
      ) : (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 text-xs font-mono text-slate-300">
            <span className="text-amber-400 font-semibold">
              {SOURCE_LABELS[infoChip.source] ?? infoChip.source}
            </span>
            <span>·</span>
            <span>{infoChip.capture_date}</span>
            {infoChip.resolution_m != null && (
              <>
                <span>·</span>
                <span>{infoChip.resolution_m}m res</span>
              </>
            )}
          </div>
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
