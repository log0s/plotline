/**
 * MapView — MapLibre GL map centered on the geocoded parcel.
 *
 * Phase 2 additions:
 *   - Imagery layer: when a snapshot is selected in the Timeline, it's displayed
 *     as a raster layer with a crossfade transition.
 *   - Info chip: shows the selected imagery source, date, and resolution.
 */
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { GeocodeResponse, ImagerySnapshot } from "../types";
import { useAppStore } from "../store";

interface MapViewProps {
  parcel: GeocodeResponse;
}

// OpenFreeMap — free, no API key needed
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const SOURCE_LABELS: Record<string, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
};

const IMAGERY_SOURCE_ID = "plotline-imagery";
const IMAGERY_LAYER_ID = "plotline-imagery-layer";

export function MapView({ parcel }: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const mapReadyRef = useRef(false);

  const { selectedSnapshot } = useAppStore();
  const [infoChip, setInfoChip] = useState<ImagerySnapshot | null>(null);

  // Initialise map on mount
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      attributionControl: true,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    map.on("load", () => {
      mapReadyRef.current = true;
    });

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

    const applySnapshot = (snap: ImagerySnapshot | null) => {
      if (!mapReadyRef.current) {
        // Wait for map to finish loading, then retry
        const onLoad = () => {
          applySnapshot(snap);
          map.off("load", onLoad);
        };
        map.on("load", onLoad);
        return;
      }

      // Remove existing layer + source
      if (map.getLayer(IMAGERY_LAYER_ID)) map.removeLayer(IMAGERY_LAYER_ID);
      if (map.getSource(IMAGERY_SOURCE_ID)) map.removeSource(IMAGERY_SOURCE_ID);

      if (!snap) {
        setInfoChip(null);
        return;
      }

      if (snap.id) {
        // Tile proxy endpoint — signing happens server-side per request,
        // so SAS tokens never expire in the browser's tile URL template.
        const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
        const tileUrl = `${apiBase}/api/v1/imagery/${snap.id}/tiles/{z}/{x}/{y}`;
        map.addSource(IMAGERY_SOURCE_ID, {
          type: "raster",
          tiles: [tileUrl],
          tileSize: 256,
        });
      } else if (snap.thumbnail_url) {
        // Fallback: static preview image overlay centered on the parcel
        const offset = 0.003; // ~300m
        const lat = parcel.latitude;
        const lng = parcel.longitude;
        map.addSource(IMAGERY_SOURCE_ID, {
          type: "image",
          url: snap.thumbnail_url,
          coordinates: [
            [lng - offset, lat + offset],
            [lng + offset, lat + offset],
            [lng + offset, lat - offset],
            [lng - offset, lat - offset],
          ],
        });
      } else {
        setInfoChip(null);
        return;
      }

      // Insert above water/landcover but below roads, buildings, and labels.
      // "aeroway_fill" is the first layer after all landcover/water fills in
      // the OpenFreeMap liberty style, so imagery renders on top of the base
      // map but underneath transport and label layers.
      const beforeLayer = map.getLayer("boundary_3") ? "boundary_3"
        : map.getLayer("building") ? "building"
        : undefined;

      map.addLayer(
        {
          id: IMAGERY_LAYER_ID,
          type: "raster",
          source: IMAGERY_SOURCE_ID,
          paint: { "raster-opacity": 0, "raster-opacity-transition": { duration: 600 } },
        },
        beforeLayer,
      );

      // Fade in
      requestAnimationFrame(() => {
        if (map.getLayer(IMAGERY_LAYER_ID)) {
          map.setPaintProperty(IMAGERY_LAYER_ID, "raster-opacity", 0.85);
        }
      });

      setInfoChip(snap);
    };

    applySnapshot(selectedSnapshot);
  }, [selectedSnapshot, parcel.latitude, parcel.longitude]);

  return (
    <div className="relative w-full h-full">
      <div
        ref={mapContainerRef}
        className="w-full h-full"
        aria-label="Map view"
      />

      {/* Imagery info chip */}
      {infoChip && (
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
      )}
    </div>
  );
}
