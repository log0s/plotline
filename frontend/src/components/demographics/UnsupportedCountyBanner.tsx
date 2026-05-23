import { motion } from "framer-motion";

interface UnsupportedCountyBannerProps {
  county: string | null;
}

export function UnsupportedCountyBanner({
  county,
}: UnsupportedCountyBannerProps) {
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
        . Currently supported: Denver, Adams counties.
      </p>
    </motion.div>
  );
}
