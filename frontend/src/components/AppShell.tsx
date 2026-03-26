/**
 * AppShell — root layout wrapper for all routes.
 * Renders the Outlet with AnimatePresence for page transitions.
 */
import { AnimatePresence } from "framer-motion";
import { Outlet, useLocation } from "react-router-dom";

export default function AppShell() {
  const location = useLocation();

  return (
    <div className="relative w-full h-full min-h-screen bg-navy-950 overflow-hidden">
      <AnimatePresence mode="wait">
        <Outlet key={location.pathname} />
      </AnimatePresence>
    </div>
  );
}
