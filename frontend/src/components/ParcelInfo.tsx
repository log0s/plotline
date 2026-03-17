/**
 * ParcelInfo — sidebar panel displaying geocoded parcel metadata.
 *
 * Shows the normalized address, coordinates, census tract, and
 * a back button to return to the landing page.
 */
import { motion } from "framer-motion";
import type { GeocodeResponse } from "../types";

interface ParcelInfoProps {
  parcel: GeocodeResponse;
  onReset: () => void;
  onSearch: (address: string) => void;
  isLoading: boolean;
}

interface DataRowProps {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}

function DataRow({ label, value, mono = false }: DataRowProps) {
  if (!value) return null;
  return (
    <div className="py-2 border-b border-navy-700/50 last:border-0">
      <p className="data-label uppercase tracking-widest text-xs mb-0.5">{label}</p>
      <p className={`text-sm text-white ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

export function ParcelInfo({ parcel, onReset, onSearch, isLoading }: ParcelInfoProps) {
  return (
    <motion.aside
      initial={{ x: "100%", opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: "100%", opacity: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 35 }}
      className={`
        absolute top-0 right-0 h-full w-80
        bg-navy-900/95 backdrop-blur-md
        border-l border-navy-700/60
        shadow-2xl shadow-black/50
        flex flex-col z-10
        overflow-hidden
      `}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-navy-700/60">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400" />
          <span className="text-sm font-medium text-slate-300">Location found</span>
        </div>
        <button
          onClick={onReset}
          className="text-slate-500 hover:text-white transition-colors p-1 rounded-lg hover:bg-navy-700"
          aria-label="Back to search"
          title="Back to search"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* Address */}
        <div className="mb-6">
          <p className="data-label uppercase tracking-widest mb-2">Address</p>
          <p className="text-white text-base font-medium leading-snug">
            {parcel.normalized_address ?? parcel.address}
          </p>
          {parcel.is_new && (
            <span className="inline-block mt-2 text-xs px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              New entry
            </span>
          )}
        </div>

        {/* Metadata rows */}
        <div className="space-y-0">
          <DataRow
            label="Coordinates"
            value={`${parcel.latitude.toFixed(6)}, ${parcel.longitude.toFixed(6)}`}
            mono
          />
          <DataRow
            label="Census Tract"
            value={parcel.census_tract ?? null}
            mono
          />
          <DataRow
            label="Parcel ID"
            value={parcel.parcel_id}
            mono
          />
        </div>
      </div>

      {/* Search again footer */}
      <div className="px-5 py-4 border-t border-navy-700/60">
        <SearchInput onSearch={onSearch} isLoading={isLoading} />
      </div>
    </motion.aside>
  );
}

// ── Compact inline search for the sidebar footer ─────────────────────────────

interface SearchInputProps {
  onSearch: (address: string) => void;
  isLoading: boolean;
}

function SearchInput({ onSearch, isLoading }: SearchInputProps) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        const addr = (fd.get("address") as string | null)?.trim();
        if (addr && addr.length >= 5) {
          onSearch(addr);
          e.currentTarget.reset();
        }
      }}
      className="flex gap-2"
    >
      <input
        name="address"
        type="text"
        placeholder="Search another address..."
        disabled={isLoading}
        className={`
          flex-1 px-3 py-2 rounded-xl bg-navy-800 border border-navy-600
          text-sm text-white placeholder-slate-500
          focus:outline-none focus:border-amber-500/60
          disabled:opacity-50
        `}
      />
      <button
        type="submit"
        disabled={isLoading}
        className="px-3 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 text-sm font-medium disabled:opacity-50 transition-colors"
      >
        {isLoading ? "..." : "Go"}
      </button>
    </form>
  );
}
