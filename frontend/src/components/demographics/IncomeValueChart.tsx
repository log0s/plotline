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
import { CHART_MARGIN, COLORS, fmtDollar } from "./chart-constants";
import { ChartTooltip, SectionHeader } from "./chart-utils";

interface IncomeValueChartProps {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
  compact?: boolean;
}

export function IncomeValueChart({
  snapshots,
  selectedYear,
  subtitle,
  compact,
}: IncomeValueChartProps) {
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
      <p className="text-[9px] text-slate-500 mb-1">
        Nominal dollars (not inflation-adjusted)
      </p>
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
            width={compact ? 0 : 48}
            hide={compact}
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
