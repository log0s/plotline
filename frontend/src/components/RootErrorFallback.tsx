import { Link, useRouteError } from "react-router-dom";

export function RootErrorFallback() {
  const error = useRouteError();
  const message =
    error instanceof Error ? error.message : "An unexpected error occurred";

  return (
    <div className="relative w-full min-h-screen bg-navy-950 flex flex-col items-center justify-center px-4">
      <h2 className="text-2xl font-bold text-white mb-2">Something broke</h2>
      <p className="text-sm text-slate-400 mb-6 text-center max-w-md">
        {message}
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
