/**
 * LandingPage — hero section with search bar, featured locations,
 * how-it-works explainer, and tech stack footer.
 */
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { FeaturedCards } from "../components/FeaturedCards";
import { HowItWorks } from "../components/HowItWorks";
import { SearchBar } from "../components/SearchBar";
import { TechFooter } from "../components/TechFooter";
import { useGeocodeMutation } from "../hooks/queries";

export default function LandingPage() {
  const geocodeMutation = useGeocodeMutation();
  const navigate = useNavigate();

  const handleSearch = (address: string, coords?: { lat: number; lon: number }) => {
    geocodeMutation.mutate({ address, navigate, ...coords });
  };

  const isLoading = geocodeMutation.isPending;
  const error = geocodeMutation.error?.message ?? null;

  return (
    <motion.div
      key="landing"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col items-center min-h-screen"
    >
      {/* Hero section */}
      <div className="flex flex-col items-center justify-center flex-1 w-full px-4 py-20">
        {/* Brand header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.5 }}
          className="text-center mb-10"
        >
          <h1 className="text-5xl sm:text-6xl font-bold tracking-tight text-white mb-4">
            See how any place has changed.
          </h1>
          <p className="text-slate-400 text-lg max-w-lg mx-auto leading-relaxed">
            Enter any US address and explore decades of aerial imagery,
            property history, and demographic shifts.
          </p>
        </motion.div>

        {/* Search */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.5 }}
          className="w-full"
        >
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            error={error}
            variant="hero"
          />
        </motion.div>
      </div>

      {/* Featured locations */}
      <FeaturedCards />

      {/* How it works */}
      <HowItWorks />

      {/* Tech footer */}
      <TechFooter />
    </motion.div>
  );
}
