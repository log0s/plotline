/**
 * FeaturedCards — grid of pre-computed example locations on the landing page.
 * Fetches from the /api/v1/featured endpoint; falls back to static placeholders
 * if the API returns nothing (e.g. before seeding).
 */
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { MapPin } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { getFeaturedLocations } from "../api/featured";
import type { FeaturedLocation } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

const PLACEHOLDER_CARDS: FeaturedLocation[] = [
  {
    id: "placeholder-1",
    parcel_id: "",
    name: "Stapleton / Central Park",
    subtitle: "Denver's closed airport became the largest urban redevelopment in US history",
    slug: "stapleton-central-park",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
  {
    id: "placeholder-2",
    parcel_id: "",
    name: "RiNo Art District",
    subtitle: "An industrial corridor transformed into Denver's trendiest neighborhood",
    slug: "rino-art-district",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
  {
    id: "placeholder-3",
    parcel_id: "",
    name: "Green Valley Ranch",
    subtitle: "Open prairie east of Denver exploded into a planned community in 15 years",
    slug: "green-valley-ranch",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
  {
    id: "placeholder-4",
    parcel_id: "",
    name: "Navy Yard / Capitol Riverfront",
    subtitle: "A Navy shipyard on the Anacostia became DC's fastest-growing neighborhood",
    slug: "navy-yard-capitol-riverfront",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
  {
    id: "placeholder-5",
    parcel_id: "",
    name: "Rodanthe, Outer Banks",
    subtitle: "Decades of coastal erosion reshaped the Outer Banks barrier islands",
    slug: "rodanthe-outer-banks",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
  {
    id: "placeholder-6",
    parcel_id: "",
    name: "Hudson Yards",
    subtitle: "Open rail yards on Manhattan's West Side became a supertower megaproject",
    slug: "hudson-yards",
    key_stat: null,
    description: null,
    latitude: 0,
    longitude: 0,
    earliest_snapshot_id: null,
    latest_snapshot_id: null,
    preview_image_url: null,
  },
];

export function FeaturedCards() {
  const { data: apiLocations } = useQuery({
    queryKey: ["featured"],
    queryFn: getFeaturedLocations,
    staleTime: 10 * 60 * 1000,
  });

  useEffect(() => {
    if (!apiLocations) return;
    for (const loc of apiLocations) {
      if (loc.preview_image_url) {
        const url = loc.preview_image_url.startsWith("http")
          ? loc.preview_image_url
          : `${API_BASE}${loc.preview_image_url}`;
        const img = new Image();
        img.src = url;
      }
    }
  }, [apiLocations]);

  const locations =
    apiLocations && apiLocations.length > 0 ? apiLocations : PLACEHOLDER_CARDS;

  return (
    <section className="w-full max-w-4xl mx-auto px-4 py-12">
      <h2 className="text-sm font-medium uppercase tracking-widest text-slate-500 text-center mb-8">
        Featured locations
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {locations.map((card, i) => {
          const href = `/featured/${card.slug}`;

          const previewUrl = card.preview_image_url
            ? card.preview_image_url.startsWith("http")
              ? card.preview_image_url
              : `${API_BASE}${card.preview_image_url}`
            : null;

          return (
            <motion.div
              key={card.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.1, duration: 0.4 }}
            >
              <Link
                to={href}
                className="h-full flex flex-col group rounded-2xl bg-navy-800/60 border border-navy-700/50 hover:border-amber-500/30 transition-all duration-200 overflow-hidden"
              >
                {/* Thumbnail area */}
                <div className="h-36 bg-navy-800 flex items-center justify-center overflow-hidden">
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt={card.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <MapPin className="w-8 h-8 text-navy-600" />
                  )}
                </div>
                <div className="p-4">
                  <h3 className="text-white font-medium mb-1 group-hover:text-amber-400 transition-colors">
                    {card.name}
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed mb-2 line-clamp-2">
                    {card.subtitle}
                  </p>
                  {card.key_stat && (
                    <p className="text-[10px] text-amber-400/70 font-mono">
                      {card.key_stat}
                    </p>
                  )}
                </div>
              </Link>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
