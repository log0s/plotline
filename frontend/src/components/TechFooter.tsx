/**
 * TechFooter — tech stack and data sources bar at bottom of landing page.
 */

const techStack = ["PostGIS", "FastAPI", "React", "MapLibre", "Celery"];
const dataSources = ["USGS / Landsat", "NAIP", "Sentinel-2", "Census Bureau", "County Records"];

export function TechFooter() {
  return (
    <footer className="w-full border-t border-navy-800/60 mt-auto">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500">
          <div className="flex items-center gap-1.5 flex-wrap justify-center">
            <span className="text-slate-600 mr-1">Built with</span>
            {techStack.map((tech, i) => (
              <span key={tech}>
                <span className="text-slate-400">{tech}</span>
                {i < techStack.length - 1 && (
                  <span className="text-navy-700 mx-1">·</span>
                )}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap justify-center">
            <span className="text-slate-600 mr-1">Data from</span>
            {dataSources.map((src, i) => (
              <span key={src}>
                <span className="text-slate-400">{src}</span>
                {i < dataSources.length - 1 && (
                  <span className="text-navy-700 mx-1">·</span>
                )}
              </span>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
