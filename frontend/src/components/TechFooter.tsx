/**
 * TechFooter — tech stack and data sources bar at bottom of landing page.
 */

const techStack: { name: string; url: string }[] = [
  { name: "PostGIS", url: "https://postgis.net/" },
  { name: "FastAPI", url: "https://fastapi.tiangolo.com/" },
  { name: "React", url: "https://react.dev/" },
  { name: "MapLibre", url: "https://maplibre.org/" },
  { name: "Celery", url: "https://docs.celeryq.dev/" },
];
const dataSources: { name: string; url: string }[] = [
  { name: "USGS / Landsat", url: "https://www.usgs.gov/landsat-missions" },
  { name: "NAIP", url: "https://naip-usdaonline.hub.arcgis.com/" },
  { name: "Sentinel-2", url: "https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-2" },
  { name: "Census Bureau", url: "https://www.census.gov/data.html" },
  { name: "County Records", url: "https://data.gov" },
];

export function TechFooter() {
  return (
    <footer className="w-full border-t border-navy-800/60 mt-auto">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500">
          <div className="flex items-center gap-1.5 flex-wrap justify-center">
            <span className="text-slate-600 mr-1">Built with</span>
            {techStack.map((tech, i) => (
              <span key={tech.name}>
                <a href={tech.url} target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-amber-400 transition-colors">{tech.name}</a>
                {i < techStack.length - 1 && (
                  <span className="text-navy-700 mx-1">·</span>
                )}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap justify-center">
            <span className="text-slate-600 mr-1">Data from</span>
            {dataSources.map((src, i) => (
              <span key={src.name}>
                <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-amber-400 transition-colors">{src.name}</a>
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
