/**
 * Shared utility for applying an imagery snapshot as a raster layer on a MapLibre map.
 * Used by both MapView (single map) and CompareView (dual maps).
 *
 * When the snapshot has additional_cog_urls (NAIP mosaic components), one
 * raster source+layer is added per COG, stacked in order so later tiles
 * cover any transparent pixels in the primary tile.
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

function collectManagedIds(
  map: maplibregl.Map,
  baseSource: string,
  baseLayer: string,
): {
  layers: string[];
  sources: string[];
} {
  const style = map.getStyle();
  const layers: string[] = [];
  const sources: string[] = [];
  for (const layer of style?.layers ?? []) {
    if (layer.id === baseLayer || layer.id.startsWith(`${baseLayer}-cog-`)) {
      layers.push(layer.id);
    }
  }
  for (const srcId of Object.keys(style?.sources ?? {})) {
    if (srcId === baseSource || srcId.startsWith(`${baseSource}-cog-`)) {
      sources.push(srcId);
    }
  }
  return { layers, sources };
}

export function applyImageryLayer(
  map: maplibregl.Map,
  snapshot: ImagerySnapshot | null,
  opts?: ApplyImageryOptions,
): void {
  const sourceId = opts?.sourceId ?? DEFAULT_SOURCE_ID;
  const layerId = opts?.layerId ?? DEFAULT_LAYER_ID;
  const targetOpacity = opts?.opacity ?? 0.85;

  // Remove existing primary + any mosaic component layers/sources
  const managed = collectManagedIds(map, sourceId, layerId);
  for (const id of managed.layers) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  for (const id of managed.sources) {
    if (map.getSource(id)) map.removeSource(id);
  }

  if (!snapshot) return;

  const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

  // Build the list of source/layer entries — primary first, then one per
  // additional_cog_url. The primary source gets the snapshot bbox as
  // bounds so MapLibre doesn't request tiles outside the imagery extent;
  // mosaic components cover different extents, so they stay unbounded.
  const entries: {
    src: string;
    layer: string;
    tileUrl: string;
    bounds?: [number, number, number, number];
  }[] = [
    {
      src: sourceId,
      layer: layerId,
      tileUrl: `${apiBase}/api/v1/imagery/${snapshot.id}/tiles/{z}/{x}/{y}`,
      bounds:
        snapshot.bbox && snapshot.bbox.length === 4 ? snapshot.bbox : undefined,
    },
  ];
  const extras = snapshot.additional_cog_urls ?? [];
  extras.forEach((_url, idx) => {
    // cog=1 → additional_cog_urls[0], cog=2 → additional_cog_urls[1], etc.
    const cogIndex = idx + 1;
    entries.push({
      src: `${sourceId}-cog-${cogIndex}`,
      layer: `${layerId}-cog-${cogIndex}`,
      tileUrl: `${apiBase}/api/v1/imagery/${snapshot.id}/tiles/{z}/{x}/{y}?cog=${cogIndex}`,
    });
  });

  // Insert above water/landcover but below roads, buildings, and labels
  const beforeLayer = map.getLayer("boundary_3")
    ? "boundary_3"
    : map.getLayer("building")
      ? "building"
      : undefined;

  for (const entry of entries) {
    map.addSource(entry.src, {
      type: "raster",
      tiles: [entry.tileUrl],
      tileSize: 256,
      ...(entry.bounds ? { bounds: entry.bounds } : {}),
    });
    map.addLayer(
      {
        id: entry.layer,
        type: "raster",
        source: entry.src,
        paint: { "raster-opacity": 0 },
      },
      beforeLayer,
    );
    map.setPaintProperty(entry.layer, "raster-opacity-transition", {
      duration: 600,
    });
  }

  // Fade all entries in together
  requestAnimationFrame(() => {
    for (const entry of entries) {
      if (map.getLayer(entry.layer)) {
        map.setPaintProperty(entry.layer, "raster-opacity", targetOpacity);
      }
    }
  });
}
