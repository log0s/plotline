/**
 * SearchBar — address input used on both the landing page (hero variant)
 * and explore page (compact variant in top nav).
 *
 * Features:
 * - Autocomplete suggestions from Nominatim via debounced API calls
 * - Keyboard navigation (arrow keys, Enter, Escape) through suggestions
 * - Loading spinner while geocoding
 * - Error display
 * - "Try these" example address chips (hero variant only)
 */
import { AnimatePresence, motion } from "framer-motion";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useAddressAutocomplete } from "../hooks/useAddressAutocomplete";

interface SearchBarProps {
  onSearch: (address: string, coords?: { lat: number; lon: number }) => void;
  isLoading: boolean;
  error: string | null;
  variant?: "hero" | "compact";
}

const EXAMPLE_ADDRESSES: { address: string; lat: number; lon: number }[] = [
  { address: "1600 Pennsylvania Ave NW, Washington, DC", lat: 38.8977, lon: -77.0365 },
  { address: "1437 Bannock St, Denver, CO 80202", lat: 39.7392, lon: -104.9876 },
  { address: "350 5th Ave, New York, NY 10118", lat: 40.7484, lon: -73.9856 },
  { address: "1 Infinite Loop, Cupertino, CA 95014", lat: 37.3318, lon: -122.0312 },
];

export function SearchBar({
  onSearch,
  isLoading,
  error,
  variant = "hero",
}: SearchBarProps) {
  const [value, setValue] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isCompact = variant === "compact";

  const { suggestions, setQuery, clear: clearSuggestions } = useAddressAutocomplete();

  // Sync autocomplete query with input value
  const handleChange = (text: string) => {
    setValue(text);
    setQuery(text);
    setHighlightIndex(-1);
    setShowSuggestions(true);
  };

  const handleSelect = (displayName: string, lat: number, lon: number) => {
    setValue(displayName);
    setShowSuggestions(false);
    clearSuggestions();
    onSearch(displayName, { lat, lon });
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (highlightIndex >= 0 && highlightIndex < suggestions.length) {
      const s = suggestions[highlightIndex];
      handleSelect(s.display_name, s.lat, s.lon);
      return;
    }
    const trimmed = value.trim();
    if (trimmed.length >= 5) {
      setShowSuggestions(false);
      clearSuggestions();
      onSearch(trimmed);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showSuggestions || suggestions.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((prev) =>
        prev < suggestions.length - 1 ? prev + 1 : 0,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((prev) =>
        prev > 0 ? prev - 1 : suggestions.length - 1,
      );
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
      setHighlightIndex(-1);
    }
  };

  const handleChip = (address: string, lat: number, lon: number) => {
    setValue(address);
    clearSuggestions();
    onSearch(address, { lat, lon });
    inputRef.current?.focus();
  };

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Hide suggestions when geocoding starts
  useEffect(() => {
    if (isLoading) setShowSuggestions(false);
  }, [isLoading]);

  const suggestionDropdown = showSuggestions && suggestions.length > 0 && (
    <div
      ref={dropdownRef}
      className={`
        absolute left-0 right-0 z-50 mt-1
        bg-navy-800 border border-navy-600 rounded-xl
        shadow-2xl shadow-black/40 overflow-hidden
      `}
    >
      {suggestions.map((s, i) => {
        // Show the first line (street/name) bolder, rest dimmer
        const parts = s.display_name.split(", ");
        const primary = parts[0];
        const secondary = parts.slice(1).join(", ");
        return (
          <button
            key={`${s.lat}-${s.lon}-${i}`}
            type="button"
            onMouseDown={(e) => {
              e.preventDefault(); // prevent input blur
              handleSelect(s.display_name, s.lat, s.lon);
            }}
            onMouseEnter={() => setHighlightIndex(i)}
            className={`
              w-full text-left px-4 py-2.5 flex items-start gap-3
              transition-colors duration-75
              ${i === highlightIndex ? "bg-navy-700" : "hover:bg-navy-700/50"}
              ${i > 0 ? "border-t border-navy-700/40" : ""}
            `}
          >
            <svg
              className="w-4 h-4 text-slate-500 mt-0.5 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M17.657 16.657L13.414 20.9a2 2 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
            <div className="min-w-0">
              <span className="text-sm text-white block truncate">
                {primary}
              </span>
              {secondary && (
                <span className="text-xs text-slate-400 block truncate">
                  {secondary}
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );

  if (isCompact) {
    return (
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <div className="relative">
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-navy-800 border border-navy-700/60 focus-within:border-amber-500/60 transition-colors">
            <svg
              className="w-4 h-4 text-slate-500 flex-shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
              />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={value}
              onChange={(e) => handleChange(e.target.value)}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              onKeyDown={handleKeyDown}
              placeholder="Search address..."
              disabled={isLoading}
              autoComplete="off"
              className="bg-transparent text-white placeholder-slate-500 text-sm outline-none w-48 lg:w-64 disabled:opacity-60"
              aria-label="Address search"
              role="combobox"
              aria-expanded={showSuggestions && suggestions.length > 0}
              aria-autocomplete="list"
            />
          </div>
          {suggestionDropdown}
        </div>
        {isLoading && (
          <svg className="animate-spin w-4 h-4 text-amber-400" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
        )}
      </form>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="relative group">
        <motion.div
          whileFocusWithin={{ scale: 1.01 }}
          transition={{ duration: 0.15 }}
          className={`
            flex items-center gap-3 px-5 py-4 rounded-2xl
            bg-navy-800 border
            transition-all duration-200
            ${error ? "border-red-500/60" : "border-navy-600 group-focus-within:border-amber-500/60"}
            shadow-xl shadow-black/30
          `}
        >
          {/* Search icon */}
          <svg
            className={`w-5 h-5 flex-shrink-0 transition-colors ${
              error ? "text-red-400" : "text-slate-500 group-focus-within:text-amber-400"
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
            />
          </svg>

          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => handleChange(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onKeyDown={handleKeyDown}
            placeholder="Enter any US address..."
            disabled={isLoading}
            autoFocus
            autoComplete="off"
            className={`
              flex-1 bg-transparent text-white placeholder-slate-500
              text-lg outline-none
              disabled:opacity-60
            `}
            aria-label="Address search"
            role="combobox"
            aria-expanded={showSuggestions && suggestions.length > 0}
            aria-autocomplete="list"
          />

          {/* Submit button or spinner */}
          {isLoading ? (
            <div className="w-8 h-8 flex items-center justify-center">
              <svg
                className="animate-spin w-5 h-5 text-amber-400"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v8z"
                />
              </svg>
            </div>
          ) : (
            <button
              type="submit"
              disabled={value.trim().length < 5}
              className={`
                px-4 py-2 rounded-xl text-sm font-medium
                transition-all duration-150
                ${
                  value.trim().length >= 5
                    ? "bg-amber-500 hover:bg-amber-400 text-navy-950 cursor-pointer"
                    : "bg-navy-700 text-slate-500 cursor-not-allowed"
                }
              `}
              aria-label="Search"
            >
              Search
            </button>
          )}
        </motion.div>

        {/* Autocomplete dropdown */}
        {suggestionDropdown}
      </form>

      {/* Error message */}
      <AnimatePresence>
        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="mt-3 text-sm text-red-400 text-center"
          >
            {error}
          </motion.p>
        )}
      </AnimatePresence>

      {/* Example chips */}
      {!isLoading && (
        <div className="mt-5 flex flex-wrap gap-2 justify-center">
          <span className="text-xs text-slate-500 w-full text-center mb-1">
            Try these
          </span>
          {EXAMPLE_ADDRESSES.map((ex) => (
            <button
              key={ex.address}
              onClick={() => handleChip(ex.address, ex.lat, ex.lon)}
              className={`
                px-3 py-1.5 rounded-full text-xs
                bg-navy-800 border border-navy-600
                text-slate-400 hover:text-amber-400 hover:border-amber-500/50
                transition-all duration-150 cursor-pointer
              `}
            >
              {ex.address}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
