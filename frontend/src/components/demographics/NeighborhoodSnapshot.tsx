import { motion } from "framer-motion";
import type { CensusSnapshot } from "../../types";
import { COLORS } from "./chart-constants";

interface NeighborhoodSnapshotProps {
  snapshots: CensusSnapshot[];
}

export function NeighborhoodSnapshot({ snapshots }: NeighborhoodSnapshotProps) {
  const latest = [...snapshots].filter((s) => s.dataset === "acs5").pop();

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
