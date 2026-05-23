import { motion } from "framer-motion";
import {
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
import type { PricePoint, PropertyEventsResponse } from "../../types";
import { CHART_MARGIN, COLORS, fmtDollar } from "./chart-constants";
import { ChartTooltip, SectionHeader } from "./chart-utils";

interface PriceHistoryChartProps {
  propertyEvents: PropertyEventsResponse;
  selectedYear: number | null;
}

export function PriceHistoryChart({ propertyEvents, selectedYear }: PriceHistoryChartProps) {
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
