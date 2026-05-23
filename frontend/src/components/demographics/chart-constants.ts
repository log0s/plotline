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
};

export const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

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
