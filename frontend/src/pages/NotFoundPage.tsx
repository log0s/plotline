/**
 * NotFoundPage — branded 404 page with search bar to try a different address.
 */
import { motion } from "framer-motion";
import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col items-center justify-center min-h-screen px-4"
    >
      <h1 className="text-7xl font-bold text-white mb-2">
        4<span className="text-amber-400">0</span>4
      </h1>
      <p className="text-slate-400 text-lg mb-2">
        This page doesn't exist.
      </p>
      <p className="text-sm text-slate-500 mb-8 text-center max-w-sm">
        The URL may be incorrect, or the parcel you're looking for may not be in our database yet.
      </p>
      <Link
        to="/"
        className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
      >
        Search an address
      </Link>
    </motion.div>
  );
}
