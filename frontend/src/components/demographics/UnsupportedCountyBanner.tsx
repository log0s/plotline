import { motion } from "framer-motion";

interface UnsupportedCountyBannerProps {
  county: string | null;
  supportedCounties?: string[];
}

function formatList(names: string[]): string {
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join("; ")}; and ${names[names.length - 1]}`;
}

export function UnsupportedCountyBanner({
  county,
  supportedCounties,
}: UnsupportedCountyBannerProps) {
  const supported = supportedCounties?.length
    ? ` Currently supported: ${formatList(supportedCounties)}.`
    : "";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-lg bg-navy-800/40 border border-navy-700/40 p-3"
    >
      <p className="text-[11px] text-slate-400 leading-relaxed">
        Property records not yet available for{" "}
        <span className="text-slate-300 font-medium">
          {county ?? "this"} County
        </span>
        .{supported}
      </p>
    </motion.div>
  );
}
