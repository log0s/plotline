import { fmtK } from "./chart-constants";

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string | number;
  formatter?: (val: number) => string;
}

export function ChartTooltip({ active, payload, label, formatter = fmtK }: TooltipProps) {
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

export function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
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
