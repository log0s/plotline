import { createBrowserRouter, Link, useRouteError } from "react-router-dom";
import AppShell from "./components/AppShell";
import ExplorePage from "./pages/ExplorePage";
import FeaturedRedirectPage from "./pages/FeaturedRedirectPage";
import LandingPage from "./pages/LandingPage";
import NotFoundPage from "./pages/NotFoundPage";

function RootErrorFallback() {
  const error = useRouteError();
  const message =
    error instanceof Error ? error.message : "An unexpected error occurred";

  return (
    <div className="relative w-full min-h-screen bg-navy-950 flex flex-col items-center justify-center px-4">
      <h2 className="text-2xl font-bold text-white mb-2">Something broke</h2>
      <p className="text-sm text-slate-400 mb-6 text-center max-w-md">{message}</p>
      <Link
        to="/"
        className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
      >
        Back to search
      </Link>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RootErrorFallback />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/explore/:parcelId", element: <ExplorePage /> },
      { path: "/featured/:slug", element: <FeaturedRedirectPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
