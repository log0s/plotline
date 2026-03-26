/**
 * FeaturedRedirectPage — /featured/:slug route handler.
 * Fetches the featured location by slug and redirects to /explore/:parcelId.
 */
import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { getFeaturedBySlug } from "../api/featured";

export default function FeaturedRedirectPage() {
  const { slug } = useParams<{ slug: string }>();
  const [parcelId, setParcelId] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!slug) return;
    getFeaturedBySlug(slug).then((data) => {
      if (data) {
        setParcelId(data.parcel_id);
      } else {
        setNotFound(true);
      }
    });
  }, [slug]);

  if (notFound) return <Navigate to="/" replace />;
  if (parcelId) return <Navigate to={`/explore/${parcelId}`} replace />;

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
