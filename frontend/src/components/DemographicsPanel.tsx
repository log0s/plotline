/**
 * DemographicsPanel — census demographic charts and neighborhood snapshot.
 *
 * Renders four visual elements:
 *   1. Population over time (line chart)
 *   2. Housing growth (stacked bar chart)
 *   3. Income & home value (dual-axis line chart)
 *   4. Neighborhood snapshot card (latest ACS data)
 *
 * Charts sync with the imagery timeline via selectedYear (vertical reference line).
 */
import { motion } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAppStore } from "../store";
import type { CensusSnapshot, PricePoint, PropertyEventsResponse } from "../types";

// ── Theme palette ────────────────────────────────────────────────────────────

const COLORS = {
  population: "#f59e0b", // amber-500
  owner: "#059669", // emerald-600
  renter: "#7c3aed", // violet-600
  vacant: "#475569", // slate-600
  income: "#f59e0b", // amber-500
  homeValue: "#06b6d4", // cyan-500
  grid: "#1e293b", // slate-800
  axis: "#64748b", // slate-500
  reference: "#fbbf24", // amber-400
};

const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 4 };

// ── Formatters ───────────────────────────────────────────────────────────────

function fmtK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function fmtDollar(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}

// ── Custom tooltip ───────────────────────────────────────────────────────────

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string | number;
  formatter?: (val: number) => string;
}

function ChartTooltip({ active, payload, label, formatter = fmtK }: TooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg bg-navy-900/95 border border-navy-700/60 px-3 py-2 text-xs shadow-lg">
      <p className="text-slate-400 mb-1 font-mono">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full inline-block"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-slate-300">{entry.name}:</span>
          <span className="text-white font-medium">{formatter(entry.value)}</span>
        </p>
      ))}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-2">
      <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
        {title}
      </h3>
      {subtitle && (
        <p className="text-[11px] text-amber-400/80 mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

// ── 1. Population Line Chart ─────────────────────────────────────────────────

function PopulationChart({
  snapshots,
  selectedYear,
  subtitle,
}: {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
}) {
  const data = snapshots
    .filter((s) => s.total_population != null)
    .map((s) => ({ year: s.year, population: s.total_population }));

  if (data.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0 }}
    >
      <SectionHeader title="Population" subtitle={subtitle} />
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
          <XAxis
            dataKey="year"
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickFormatter={fmtK}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip content={<ChartTooltip />} />
          {selectedYear && (
            <ReferenceLine
              x={selectedYear}
              stroke={COLORS.reference}
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
          )}
          <Line
            type="monotone"
            dataKey="population"
            stroke={COLORS.population}
            strokeWidth={2}
            dot={{ r: 3, fill: COLORS.population }}
            activeDot={{ r: 5 }}
            name="Population"
          />
        </LineChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── 2. Housing Stacked Bar Chart ─────────────────────────────────────────────

function HousingChart({
  snapshots,
  selectedYear,
  subtitle,
}: {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
}) {
  const data = snapshots
    .filter(
      (s) =>
        s.total_housing_units != null &&
        (s.owner_occupied_units != null || s.renter_occupied_units != null),
    )
    .map((s) => {
      const owner = s.owner_occupied_units ?? 0;
      const renter = s.renter_occupied_units ?? 0;
      const occupied = s.occupied_housing_units ?? owner + renter;
      const total = s.total_housing_units ?? occupied;
      const vacant = Math.max(0, total - occupied);
      return { year: s.year, Owner: owner, Renter: renter, Vacant: vacant };
    });

  if (data.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
    >
      <SectionHeader title="Housing" subtitle={subtitle} />
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
          <XAxis
            dataKey="year"
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickFormatter={fmtK}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip content={<ChartTooltip />} />
          {selectedYear && (
            <ReferenceLine
              x={selectedYear}
              stroke={COLORS.reference}
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
          )}
          <Bar dataKey="Owner" stackId="a" fill={COLORS.owner} name="Owner" radius={[0, 0, 0, 0]} />
          <Bar dataKey="Renter" stackId="a" fill={COLORS.renter} name="Renter" />
          <Bar dataKey="Vacant" stackId="a" fill={COLORS.vacant} name="Vacant" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── 3. Income & Home Value Dual-Axis Line Chart ──────────────────────────────

function IncomeValueChart({
  snapshots,
  selectedYear,
  subtitle,
}: {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
}) {
  const data = snapshots
    .filter(
      (s) =>
        s.dataset === "acs5" &&
        (s.median_household_income != null || s.median_home_value != null),
    )
    .map((s) => ({
      year: s.year,
      income: s.median_household_income,
      homeValue: s.median_home_value,
    }));

  if (data.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
    >
      <SectionHeader title="Income & Home Value" subtitle={subtitle} />
      <p className="text-[9px] text-slate-500 mb-1">Nominal dollars (not inflation-adjusted)</p>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={CHART_MARGIN}>
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
          <XAxis
            dataKey="year"
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickFormatter={fmtDollar}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 10, fill: COLORS.axis }}
            tickFormatter={fmtDollar}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip content={<ChartTooltip formatter={fmtDollar} />} />
          {selectedYear && (
            <ReferenceLine
              x={selectedYear}
              yAxisId="left"
              stroke={COLORS.reference}
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
          )}
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="income"
            stroke={COLORS.income}
            strokeWidth={2}
            dot={{ r: 3, fill: COLORS.income }}
            name="Median Income"
            connectNulls
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="homeValue"
            stroke={COLORS.homeValue}
            strokeWidth={2}
            dot={{ r: 3, fill: COLORS.homeValue }}
            name="Median Home Value"
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── 4. Neighborhood Snapshot Card ────────────────────────────────────────────

function SnapshotCard({ snapshots }: { snapshots: CensusSnapshot[] }) {
  // Find latest ACS snapshot
  const latest = [...snapshots]
    .filter((s) => s.dataset === "acs5")
    .pop();

  if (!latest) return null;

  const ownerPct =
    latest.owner_occupied_units && latest.occupied_housing_units
      ? Math.round(
          (latest.owner_occupied_units / latest.occupied_housing_units) * 100,
        )
      : null;

  const items: { label: string; value: string }[] = [];

  if (latest.median_age != null)
    items.push({ label: "Median age", value: latest.median_age.toFixed(1) });

  if (latest.median_gross_rent != null)
    items.push({
      label: "Median rent",
      value: `$${latest.median_gross_rent.toLocaleString()}`,
    });

  if (latest.median_year_built != null)
    items.push({
      label: "Typical home built",
      value: String(latest.median_year_built),
    });

  if (latest.median_household_income != null)
    items.push({
      label: "Median income",
      value: `$${latest.median_household_income.toLocaleString()}`,
    });

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.3 }}
      className="rounded-lg bg-navy-800/60 border border-navy-700/40 p-3"
    >
      <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
        Neighborhood Snapshot
        <span className="text-[10px] text-slate-500 font-normal ml-2">
          {latest.year} ACS
        </span>
      </h3>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {items.map((item) => (
          <div key={item.label}>
            <p className="text-[10px] text-slate-500">{item.label}</p>
            <p className="text-sm font-mono text-amber-400">{item.value}</p>
          </div>
        ))}
      </div>

      {/* Owner vs renter bar */}
      {ownerPct != null && (
        <div className="mt-3">
          <div className="flex justify-between text-[10px] text-slate-500 mb-1">
            <span>Owner {ownerPct}%</span>
            <span>Renter {100 - ownerPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-navy-700 overflow-hidden flex">
            <div
              className="h-full rounded-l-full"
              style={{ width: `${ownerPct}%`, backgroundColor: COLORS.owner }}
            />
            <div
              className="h-full rounded-r-full"
              style={{
                width: `${100 - ownerPct}%`,
                backgroundColor: COLORS.renter,
              }}
            />
          </div>
        </div>
      )}
    </motion.div>
  );
}

// ── 5. Price History Chart (from property events) ────────────────────────

function PriceHistoryChart({
  propertyEvents,
  selectedYear,
}: {
  propertyEvents: PropertyEventsResponse;
  selectedYear: number | null;
}) {
  const { summary } = propertyEvents;
  if (summary.price_history.length === 0) return null;

  const data = summary.price_history.map((p: PricePoint) => ({
    year: parseInt(p.date.slice(0, 4), 10),
    price: p.price,
    label: new Date(p.date + "T00:00:00").toLocaleDateString("en-US", {
      month: "short",
      year: "numeric",
    }),
  }));

  const singlePoint = data.length === 1;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.35 }}
    >
      <SectionHeader
        title="Sale Price History"
        subtitle={summary.appreciation ?? undefined}
      />
      <ResponsiveContainer width="100%" height={140}>
        {singlePoint ? (
          <ScatterChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis
              dataKey="year"
              tick={{ fontSize: 10, fill: COLORS.axis }}
              tickLine={false}
              axisLine={false}
              type="number"
              domain={["dataMin - 2", "dataMax + 2"]}
            />
            <YAxis
              dataKey="price"
              tick={{ fontSize: 10, fill: COLORS.axis }}
              tickFormatter={fmtDollar}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip content={<ChartTooltip formatter={fmtDollar} />} />
            <Scatter
              dataKey="price"
              fill={COLORS.income}
              name="Sale Price"
            />
          </ScatterChart>
        ) : (
          <LineChart data={data} margin={CHART_MARGIN}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis
              dataKey="year"
              tick={{ fontSize: 10, fill: COLORS.axis }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: COLORS.axis }}
              tickFormatter={fmtDollar}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip content={<ChartTooltip formatter={fmtDollar} />} />
            {selectedYear && (
              <ReferenceLine
                x={selectedYear}
                stroke={COLORS.reference}
                strokeDasharray="4 4"
                strokeWidth={1.5}
              />
            )}
            <Line
              type="monotone"
              dataKey="price"
              stroke={COLORS.income}
              strokeWidth={2}
              dot={{ r: 4, fill: COLORS.income }}
              activeDot={{ r: 6 }}
              name="Sale Price"
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── Unsupported County Empty State ───────────────────────────────────────

function UnsupportedCountyBanner({ county }: { county: string | null }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-lg bg-navy-800/40 border border-navy-700/40 p-3"
    >
      <p className="text-[11px] text-slate-400 leading-relaxed">
        Property records not yet available for{" "}
        <span className="text-slate-300 font-medium">{county ?? "this"} County</span>.
        Currently supported: Denver, Adams counties.
      </p>
    </motion.div>
  );
}

// ── Main panel ───────────────────────────────────────────────────────────────

export function DemographicsPanel() {
  const { demographics, demographicsLoading, selectedYear, propertyEvents } = useAppStore();

  // Loading state
  if (demographicsLoading) {
    return (
      <div className="flex flex-col gap-3 p-4 animate-pulse">
        <div className="h-3 w-32 bg-navy-800 rounded" />
        <div className="h-32 bg-navy-800/50 rounded-lg" />
        <div className="h-32 bg-navy-800/50 rounded-lg" />
      </div>
    );
  }

  // No data yet — but may still have property events
  const hasDemo = demographics && demographics.snapshots.length > 0;
  const hasPropertyData = propertyEvents && propertyEvents.events.length > 0;
  const showUnsupported = propertyEvents && !propertyEvents.supported;

  if (!hasDemo && !hasPropertyData && !showUnsupported) {
    return (
      <div className="flex items-center justify-center p-6 text-center">
        <p className="text-xs text-slate-500">
          No census or property data available yet.
          <br />
          Data will appear once the timeline finishes processing.
        </p>
      </div>
    );
  }

  const snapshots = demographics?.snapshots ?? [];
  const subtitles = demographics?.subtitles ?? [];
  const notes = demographics?.notes;

  // Find subtitles for each chart
  const popSubtitle = subtitles.find((s) => s.toLowerCase().includes("population"));
  const valueSubtitle = subtitles.find((s) => s.toLowerCase().includes("home value"));
  const ownerSubtitle = subtitles.find((s) => s.toLowerCase().includes("owner"));

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto scrollbar-thin scrollbar-thumb-navy-700 scrollbar-track-transparent">
      {/* Subtitles banner */}
      {subtitles.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-wrap gap-2"
        >
          {subtitles.slice(0, 3).map((s) => (
            <span
              key={s}
              className="text-[10px] text-amber-400/70 bg-amber-400/5 border border-amber-400/10 rounded-full px-2.5 py-0.5"
            >
              {s}
            </span>
          ))}
        </motion.div>
      )}

      {/* Price history chart (property events) */}
      {hasPropertyData && propertyEvents && (
        <PriceHistoryChart
          propertyEvents={propertyEvents}
          selectedYear={selectedYear}
        />
      )}

      {/* Unsupported county empty state */}
      {showUnsupported && !hasPropertyData && (
        <UnsupportedCountyBanner county={propertyEvents?.county ?? null} />
      )}

      {hasDemo && (
        <>
          <PopulationChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={popSubtitle}
          />

          <HousingChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={ownerSubtitle}
          />

          <IncomeValueChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={valueSubtitle}
          />

          <SnapshotCard snapshots={snapshots} />
        </>
      )}

      {/* Tract caveat */}
      {notes && (
        <p className="text-[9px] text-slate-600 leading-relaxed mt-1">{notes}</p>
      )}
    </div>
  );
}
