/**
 * Shared utility for applying an imagery snapshot as a raster layer on a MapLibre map.
 * Used by both MapView (single map) and CompareView (dual maps).
 */
import type maplibregl from "maplibre-gl";
import type { ImagerySnapshot } from "../types";

const DEFAULT_SOURCE_ID = "plotline-imagery";
const DEFAULT_LAYER_ID = "plotline-imagery-layer";

interface ApplyImageryOptions {
  sourceId?: string;
  layerId?: string;
  opacity?: number;
}

export function applyImageryLayer(
  map: maplibregl.Map,
  snapshot: ImagerySnapshot | null,
  parcelCoords: { lat: number; lng: number },
  opts?: ApplyImageryOptions,
): void {
  const sourceId = opts?.sourceId ?? DEFAULT_SOURCE_ID;
  const layerId = opts?.layerId ?? DEFAULT_LAYER_ID;
  const targetOpacity = opts?.opacity ?? 0.85;

  // Remove existing layer + source
  if (map.getLayer(layerId)) map.removeLayer(layerId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);

  if (!snapshot) return;

  if (snapshot.id) {
    // Tile proxy endpoint — signing happens server-side per request
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
    const tileUrl = `${apiBase}/api/v1/imagery/${snapshot.id}/tiles/{z}/{x}/{y}`;
    map.addSource(sourceId, {
      type: "raster",
      tiles: [tileUrl],
      tileSize: 256,
    });
  } else if (snapshot.thumbnail_url) {
    // Fallback: static preview image overlay centered on the parcel
    const offset = 0.003; // ~300m
    const { lat, lng } = parcelCoords;
    map.addSource(sourceId, {
      type: "image",
      url: snapshot.thumbnail_url,
      coordinates: [
        [lng - offset, lat + offset],
        [lng + offset, lat + offset],
        [lng + offset, lat - offset],
        [lng - offset, lat - offset],
      ],
    });
  } else {
    return;
  }

  // Insert above water/landcover but below roads, buildings, and labels
  const beforeLayer = map.getLayer("boundary_3")
    ? "boundary_3"
    : map.getLayer("building")
      ? "building"
      : undefined;

  map.addLayer(
    {
      id: layerId,
      type: "raster",
      source: sourceId,
      paint: {
        "raster-opacity": 0,
      },
    },
    beforeLayer,
  );
  map.setPaintProperty(layerId, "raster-opacity-transition", { duration: 600 });

  // Fade in
  requestAnimationFrame(() => {
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, "raster-opacity", targetOpacity);
    }
  });
}
