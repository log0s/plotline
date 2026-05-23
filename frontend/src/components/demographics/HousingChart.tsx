import { motion } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CensusSnapshot } from "../../types";
import { CHART_MARGIN, COLORS, fmtK } from "./chart-constants";
import { ChartTooltip, SectionHeader } from "./chart-utils";

interface HousingChartProps {
  snapshots: CensusSnapshot[];
  selectedYear: number | null;
  subtitle?: string;
}

export function HousingChart({
  snapshots,
  selectedYear,
  subtitle,
}: HousingChartProps) {
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
          <Bar
            dataKey="Owner"
            stackId="a"
            fill={COLORS.owner}
            name="Owner"
            radius={[0, 0, 0, 0]}
          />
          <Bar
            dataKey="Renter"
            stackId="a"
            fill={COLORS.renter}
            name="Renter"
          />
          <Bar
            dataKey="Vacant"
            stackId="a"
            fill={COLORS.vacant}
            name="Vacant"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
