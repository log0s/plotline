/**
 * FeaturedRedirectPage — /featured/:slug route handler.
 * Fetches the featured location by slug and redirects to /explore/:parcelId.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";
import { getFeaturedBySlug } from "../api/featured";

export default function FeaturedRedirectPage() {
  const { slug } = useParams<{ slug: string }>();

  const { data, error, isLoading } = useQuery({
    queryKey: ["featuredBySlug", slug],
    queryFn: () => getFeaturedBySlug(slug as string),
    enabled: !!slug,
    staleTime: 10 * 60 * 1000,
  });

  if (data?.parcel_id) {
    return <Navigate to={`/explore/${data.parcel_id}`} replace />;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <h2 className="text-2xl font-bold text-white mb-2">
          Couldn&apos;t load featured location
        </h2>
        <p className="text-sm text-slate-400 mb-6 text-center max-w-sm">
          {error instanceof Error ? error.message : "Network error"}
        </p>
        <Link
          to="/"
          className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
        >
          Back to search
        </Link>
      </div>
    );
  }

  if (!isLoading && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <h2 className="text-2xl font-bold text-white mb-2">
          Featured location not found
        </h2>
        <p className="text-sm text-slate-400 mb-6 text-center max-w-sm">
          The location &quot;{slug}&quot; hasn&apos;t been seeded yet. Run{" "}
          <code className="text-amber-400 bg-navy-800 px-1.5 py-0.5 rounded text-xs">
            make featured
          </code>{" "}
          to populate featured locations.
        </p>
        <Link
          to="/"
          className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-navy-950 font-medium transition-colors"
        >
          Search an address instead
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="flex items-center gap-3 text-slate-400">
        <svg className="animate-spin w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
        </svg>
        <span>Loading featured location...</span>
      </div>
    </div>
  );
}
