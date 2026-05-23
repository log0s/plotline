import { createBrowserRouter } from "react-router-dom";
import AppShell from "./components/AppShell";
import { RootErrorFallback } from "./components/RootErrorFallback";
import ExplorePage from "./pages/ExplorePage";
import FeaturedRedirectPage from "./pages/FeaturedRedirectPage";
import LandingPage from "./pages/LandingPage";
import NotFoundPage from "./pages/NotFoundPage";

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
