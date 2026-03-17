/**
 * SearchBar — the primary address input on the landing page.
 *
 * Features:
 * - Keyboard submit (Enter key)
 * - Loading spinner while geocoding
 * - Error display
 * - "Try these" example address chips
 */
import { AnimatePresence, motion } from "framer-motion";
import { type FormEvent, useRef, useState } from "react";

interface SearchBarProps {
  onSearch: (address: string) => void;
  isLoading: boolean;
  error: string | null;
}

const EXAMPLE_ADDRESSES = [
  "1600 Pennsylvania Ave NW, Washington, DC",
  "1437 Bannock St, Denver, CO 80202",
  "350 5th Ave, New York, NY 10118",
  "1 Infinite Loop, Cupertino, CA 95014",
];

export function SearchBar({ onSearch, isLoading, error }: SearchBarProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length >= 5) {
      onSearch(trimmed);
    }
  };

  const handleChip = (address: string) => {
    setValue(address);
    onSearch(address);
    inputRef.current?.focus();
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="relative group">
        <div
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
            onChange={(e) => setValue(e.target.value)}
            placeholder="Enter any US address..."
            disabled={isLoading}
            autoFocus
            className={`
              flex-1 bg-transparent text-white placeholder-slate-500
              text-lg outline-none
              disabled:opacity-60
            `}
            aria-label="Address search"
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
        </div>
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
          {EXAMPLE_ADDRESSES.map((addr) => (
            <button
              key={addr}
              onClick={() => handleChip(addr)}
              className={`
                px-3 py-1.5 rounded-full text-xs
                bg-navy-800 border border-navy-600
                text-slate-400 hover:text-amber-400 hover:border-amber-500/50
                transition-all duration-150 cursor-pointer
              `}
            >
              {addr}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
