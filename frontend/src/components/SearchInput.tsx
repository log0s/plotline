import { AnimatePresence, motion } from "framer-motion";
import { useRef, useState } from "react";
import { useAddressAutocomplete } from "../hooks/useAddressAutocomplete";

interface SearchInputProps {
  onSearch: (address: string, coords?: { lat: number; lon: number }) => void;
  isLoading: boolean;
  error: string | null;
  onClearError: () => void;
}

export function SearchInput({
  onSearch,
  isLoading,
  error,
  onClearError,
}: SearchInputProps) {
  const { setQuery, suggestions, clear } = useAddressAutocomplete();
  const [value, setValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSelect = (displayName: string, lat: number, lon: number) => {
    setValue("");
    setShowSuggestions(false);
    clear();
    onSearch(displayName, { lat, lon });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (highlightIndex >= 0 && highlightIndex < suggestions.length) {
      const s = suggestions[highlightIndex];
      handleSelect(s.display_name, s.lat, s.lon);
      return;
    }
    const addr = value.trim();
    if (addr.length >= 5) {
      setValue("");
      clear();
      setShowSuggestions(false);
      onSearch(addr);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  return (
    <div>
      <form onSubmit={handleSubmit} className="relative flex gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setQuery(e.target.value);
              setShowSuggestions(true);
              setHighlightIndex(-1);
              if (error) onClearError();
            }}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            onKeyDown={handleKeyDown}
            placeholder="Search another address..."
            disabled={isLoading}
            className={`
            w-full px-3 py-2 rounded-xl bg-navy-800 border
            text-sm text-white placeholder-slate-500
            focus:outline-none focus:border-amber-500/60
            disabled:opacity-50
            ${error ? "border-red-500/60" : "border-navy-600"}
          `}
          />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute left-0 right-0 bottom-full mb-1 z-50 bg-navy-800 border border-navy-600 rounded-xl shadow-2xl shadow-black/40 overflow-hidden">
              {suggestions.map((s, i) => {
                const parts = s.display_name.split(", ");
                const primary = parts[0];
                const secondary = parts.slice(1).join(", ");
                return (
                  <button
                    key={`${s.lat}-${s.lon}-${i}`}
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      handleSelect(s.display_name, s.lat, s.lon);
                    }}
                    onMouseEnter={() => setHighlightIndex(i)}
                    className={`
                    w-full text-left px-3 py-2 flex items-start gap-2
                    transition-colors duration-75
                    ${i === highlightIndex ? "bg-navy-700" : "hover:bg-navy-700/50"}
                    ${i > 0 ? "border-t border-navy-700/40" : ""}
                  `}
                  >
                    <svg
                      className="w-3.5 h-3.5 text-slate-500 mt-0.5 shrink-0"
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
                      <span className="text-xs text-white block truncate">
                        {primary}
                      </span>
                      {secondary && (
                        <span className="text-[11px] text-slate-400 block truncate">
                          {secondary}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <button
          type="submit"
          disabled={isLoading}
          className="px-3 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 text-sm font-medium disabled:opacity-50 transition-colors shrink-0"
        >
          {isLoading ? "..." : "Go"}
        </button>
      </form>
      <AnimatePresence>
        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="mt-2 text-xs text-red-400"
          >
            {error}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
