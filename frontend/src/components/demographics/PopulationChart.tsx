import { motion } from "framer-motion";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CensusSnapshot } from "../../types";
import { CHART_MARGIN, COLORS, fmtK } from "./chart-constants";
import { ChartTooltip, SectionHeader } from "./chart-utils";

interface PopulationChartProps {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
}

export function PopulationChart({ snapshots, selectedYear, subtitle }: PopulationChartProps) {
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
