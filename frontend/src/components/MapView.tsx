/**
 * MapView — MapLibre GL map centered on the geocoded parcel.
 *
 * Uses OpenFreeMap's "liberty" style (no API key required).
 * Drops a custom amber marker at the parcel location.
 */
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { GeocodeResponse } from "../types";

interface MapViewProps {
  parcel: GeocodeResponse;
}

// OpenFreeMap — free, no API key needed
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

export function MapView({ parcel }: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);

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

    mapRef.current = map;

    return () => {
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

    // Remove old marker
    markerRef.current?.remove();

    // Create custom amber marker element
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

    // Fly to new location
    map.flyTo({
      center: [parcel.longitude, parcel.latitude],
      zoom: 15,
      duration: 1400,
      essential: true,
    });
  }, [parcel.latitude, parcel.longitude]);

  return (
    <div
      ref={mapContainerRef}
      className="w-full h-full"
      aria-label="Map view"
    />
  );
}
