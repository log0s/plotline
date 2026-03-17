/**
 * App — root component.
 *
 * Manages the two top-level views:
 *   "landing" — centered search bar, project intro
 *   "map"     — full-viewport map + imagery timeline at bottom + parcel sidebar
 *
 * Phase 2: adds Timeline component and useTimeline polling hook.
 */
import { AnimatePresence, motion } from "framer-motion";
import { ParcelInfo } from "./components/ParcelInfo";
import { SearchBar } from "./components/SearchBar";
import { MapView } from "./components/MapView";
import { Timeline } from "./components/Timeline";
import { useGeocoder } from "./hooks/useGeocoder";
import { useTimeline } from "./hooks/useTimeline";
import { useAppStore } from "./store";

export default function App() {
  const { view, parcel, error, isLoading, reset } = useAppStore();
  const { geocode } = useGeocoder();

  // Start polling as soon as we have a timeline_request_id
  useTimeline();

  return (
    <div className="relative w-full h-full min-h-screen bg-navy-950 overflow-hidden">
      <AnimatePresence mode="wait">
        {view === "landing" && (
          <motion.div
            key="landing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.35 }}
            className="flex flex-col items-center justify-center min-h-screen px-4 py-12"
          >
            {/* Brand header */}
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.5 }}
              className="text-center mb-12"
            >
              <h1 className="text-5xl font-bold tracking-tight text-white mb-3">
                Plot<span className="text-amber-400">line</span>
              </h1>
              <p className="text-slate-400 text-lg max-w-md mx-auto leading-relaxed">
                Enter any US address and explore how that location has changed
                across decades of aerial imagery, property history, and
                demographic data.
              </p>
            </motion.div>

            {/* Search */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.5 }}
              className="w-full"
            >
              <SearchBar
                onSearch={geocode}
                isLoading={isLoading}
                error={error}
              />
            </motion.div>

            {/* Footer tagline */}
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 }}
              className="mt-16 text-xs text-navy-600 text-center"
            >
              Powered by US Census Geocoder · NAIP · Landsat · Sentinel-2 · OpenFreeMap
            </motion.p>
          </motion.div>
        )}

        {view === "map" && parcel && (
          <motion.div
            key="map"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4 }}
            className="relative w-full h-screen flex flex-col"
          >
            {/* Map takes all remaining space above the timeline */}
            <div className="relative flex-1 min-h-0">
              <MapView parcel={parcel} />

              {/* Top-left brand chip */}
              <button
                onClick={reset}
                className="absolute top-4 left-4 z-10 flex items-center gap-2 px-3 py-2 rounded-xl bg-navy-900/90 backdrop-blur-sm border border-navy-700/60 hover:border-amber-500/40 transition-colors"
                title="Back to search"
              >
                <svg
                  className="w-4 h-4 text-amber-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
                <span className="text-sm font-semibold text-white">
                  Plot<span className="text-amber-400">line</span>
                </span>
              </button>

              {/* Parcel info sidebar */}
              <AnimatePresence>
                <ParcelInfo
                  key={parcel.parcel_id}
                  parcel={parcel}
                  onReset={reset}
                  onSearch={geocode}
                  isLoading={isLoading}
                />
              </AnimatePresence>
            </div>

            {/* Timeline strip — always visible at bottom */}
            <Timeline />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
