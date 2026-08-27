import { motion } from "framer-motion";

interface NotCoveredBannerProps {
  /** The task's own error_message, which names the county and the city. Falls
   * back to a generic line if the task carried none. */
  message: string | null;
}

/** The county has an adapter, but it isn't the authority for this address —
 * Adams County's permit layer covers unincorporated Adams, and Thornton keeps
 * its own records.
 *
 * Deliberately the same quiet treatment as UnsupportedCountyBanner: this is
 * "we did not ask", which is neither "we asked and there is nothing" (zero
 * records) nor "we asked and it broke" (an error). Rendering it as either is
 * the defect this component exists to prevent. */
export function NotCoveredBanner({ message }: NotCoveredBannerProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="rounded-lg bg-navy-800/40 border border-navy-700/40 p-3"
    >
      <p className="text-[11px] text-slate-400 leading-relaxed">
        {message ??
          "Property records for this address are kept by its city, not the county."}
      </p>
    </motion.div>
  );
}
