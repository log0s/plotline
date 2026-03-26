/**
 * Application router — defines all routes for Plotline.
 */
import { createBrowserRouter } from "react-router-dom";
import AppShell from "./components/AppShell";
import ExplorePage from "./pages/ExplorePage";
import FeaturedRedirectPage from "./pages/FeaturedRedirectPage";
import LandingPage from "./pages/LandingPage";
import NotFoundPage from "./pages/NotFoundPage";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/explore/:parcelId", element: <ExplorePage /> },
      { path: "/featured/:slug", element: <FeaturedRedirectPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
