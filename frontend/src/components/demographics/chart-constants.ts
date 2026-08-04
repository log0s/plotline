import type { CensusSnapshot } from "../../types";

export const COLORS = {
  population: "#f59e0b",
  owner: "#059669",
  renter: "#7c3aed",
  vacant: "#475569",
  income: "#f59e0b",
  homeValue: "#06b6d4",
  grid: "#1e293b",
  axis: "#64748b",
  reference: "#fbbf24",
  boundary: "#64748b",
};

export const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

// Quieter than the selected-year reference line: this marks a change in what
// the data describes, not where the user is.
export const TRACT_BREAK_LINE = {
  stroke: COLORS.boundary,
  strokeDasharray: "2 3",
  strokeWidth: 1,
};

/**
 * Years at which the parcel's census tract changes, taken from the rows a
 * chart actually plots.
 *
 * Tracts are redrawn every decade, and a split makes the same address's counts
 * fall without anything on the ground changing. Pass the already-filtered
 * series so the returned year is guaranteed to be a category on the axis.
 */
export function findTractBreakYears(snapshots: CensusSnapshot[]): number[] {
  return snapshots
    .filter((s, i) => i > 0 && s.tract_fips !== snapshots[i - 1].tract_fips)
    .map((s) => s.year);
}

export function fmtK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

export function fmtDollar(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}
