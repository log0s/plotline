# Phase 5 — Polish & Presentation

## Context

Phases 1–4 are complete. We have a fully functional application:
- Geocoding and map view (Phase 1)
- Historical imagery timeline from NAIP, Landsat, Sentinel-2 (Phase 2)
- Census demographic charts synced to the timeline (Phase 3)
- Property sales and permit events interleaved on the timeline (Phase 4)

## Phase 5 Goal

This phase is about turning a working app into a *portfolio piece*. No new data sources or major features — instead, focus on the details that make someone stop scrolling on your GitHub profile, click the demo link, and remember it. That means: a polished landing page, shareable URLs, before/after image comparison, featured example locations, a hero README, and Docker-based one-command setup that actually works.

---

## 1. Landing Page Redesign

The Phase 1 landing page was functional. Now make it memorable.

### Layout

```
┌──────────────────────────────────────────────────────┐
│  [logo/wordmark]                        [GitHub ↗]   │
│                                                      │
│                                                      │
│          See how any place has changed.               │
│                                                      │
│     ┌──────────────────────────────────────────┐     │
│     │  🔍  Enter a US address...                │     │
│     └──────────────────────────────────────────┘     │
│                                                      │
│     Try:  [Commerce City, CO]  [Denver, CO]          │
│           [Outer Banks, NC]    [Your address]        │
│                                                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │  Featured   │  │  Featured   │  │  Featured   │  │
│  │  Location 1 │  │  Location 2 │  │  Location 3 │  │
│  │  before →   │  │  before →   │  │  before →   │  │
│  │  after      │  │  after      │  │  after      │  │
│  │             │  │             │  │             │  │
│  │  Brief      │  │  Brief      │  │  Brief      │  │
│  │  story      │  │  story      │  │  story      │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│  How it works:                                       │
│  1. Enter any US address                             │
│  2. We search decades of satellite imagery           │
│  3. See the full story of your location              │
│                                                      │
├──────────────────────────────────────────────────────┤
│  Built with PostGIS · FastAPI · React · MapLibre     │
│  Data from USGS · Census Bureau · County Records     │
│  [View on GitHub ↗]                                  │
└──────────────────────────────────────────────────────┘
```

### Design Details

- **Hero section**: Dark background, large text, the search bar is the obvious call to action. No stock imagery, no decorative illustrations — the app itself is the visual.
- **Featured locations**: Pre-computed examples (see section 3 below). Each card shows a small before/after thumbnail pair, the location name, a one-line story ("Farmland to subdivision in 20 years"), and is clickable to jump straight to the full timeline.
- **How it works**: Three steps, dead simple. Use subtle icons (Lucide), not numbered circles.
- **Footer tech stack bar**: Lists the technologies and data sources. This is for hiring managers who scroll to the bottom — it says "I know what I'm doing" without being a résumé.
- **Animations**: Subtle. The search bar should feel snappy (slight scale on focus). Featured cards fade in on scroll with Framer Motion. Nothing should bounce, wiggle, or draw attention to itself.

### Search Experience

- As the user types, show a subtle loading state after they stop typing for 500ms (debounce)
- On submit, animate a transition from the landing page to the map view — the search bar should visually move from center-screen to the top nav bar, and the map should expand from the center point. Use Framer Motion's `layout` animation or a shared layout transition.
- If geocoding fails, show an inline error below the search bar: "We couldn't find that address. Try including the city and state." Don't use a toast or modal.

---

## 2. Before/After Image Comparison

Add a side-by-side (or swipe) comparison view for any two imagery snapshots.

### Implementation

Use a slider/swipe comparison component. The user drags a divider left and right to reveal the "before" image underneath the "after" image. This is a well-known UX pattern (see: Mapbox Compare, juxtapose.js, leaflet-side-by-side).

**For MapLibre**: Use `maplibre-gl-compare` — it's a plugin that renders two synchronized MapLibre maps side by side with a draggable divider. Each map shows a different imagery layer.

```
npm install maplibre-gl-compare
```

**If maplibre-gl-compare isn't compatible with your MapLibre version**, build a simpler version:
- Render two MapLibre instances side by side
- Sync their camera (center, zoom, bearing, pitch) via `moveend` events
- Use a CSS `clip-path` or `overflow: hidden` on the right map, controlled by a draggable divider
- This is actually not that much code and gives you full control over styling

### UX Flow

1. On the timeline, user selects two snapshots (add a "Compare" mode toggle button)
2. When two are selected, transition the map into split-view comparison mode
3. The divider is draggable, and both maps stay synchronized
4. Labels on each side show the date and source
5. An "Exit comparison" button returns to the normal single-map view
6. Keyboard shortcut: `Escape` exits comparison mode

### Thumbnail Comparison on the Timeline

Also add a simpler inline comparison: when hovering over a timeline thumbnail, show a small tooltip with the earliest available image alongside it. This doesn't require the full split-map — just two thumbnail images side by side in a tooltip. Quick, lightweight, and immediately communicates change.

---

## 3. Featured Example Locations

Pre-compute and cache timelines for 3–4 carefully chosen locations. These serve two purposes: they make the landing page visually compelling, and they let someone evaluate the app without entering their own address.

### Suggested Locations

Choose locations that tell a dramatic visual story:

**1. Suburban Sprawl**
- Area near E-470 / Green Valley Ranch in Denver metro
- Story: "Prairie to planned community in 15 years"
- NAIP imagery from 2003 vs 2023 should show empty grassland → dense subdivision
- Census data should show massive population growth

**2. Urban Redevelopment**
- RiNo (River North Art District) in Denver
- Story: "Industrial warehouses to breweries and condos"
- Permits should show demolition + new construction clustering around 2014–2020
- Home values should show dramatic appreciation

**3. Environmental Change**
- Pick an area near a Colorado reservoir that's had visible water level changes, or an area affected by wildfire (e.g., near the Marshall Fire area in Louisville/Superior — 2021)
- Story: visible landscape change driven by environmental events
- Landsat shows the change most clearly at this scale

**4. (Optional) Agricultural to Airport**
- Area near Denver International Airport
- Story: "Farmland to one of the largest airports in the world"
- Landsat from 1984 vs present is dramatic
- This one is iconic and immediately recognizable

### Implementation

- Create a `seed_featured.py` script that runs the full timeline pipeline for each featured location
- Store the results in the database with a `featured` flag on the parcel (add a `is_featured BOOLEAN DEFAULT FALSE` column to `parcels`, or create a separate `featured_locations` table with display metadata)
- The landing page loads featured locations from a dedicated API endpoint
- Featured location cards show: location name, one-line story, earliest thumbnail, most recent thumbnail, key stat (e.g., "Population: 200 → 12,000")

```
GET /api/v1/featured
  Response: [
    {
      "parcel_id": "uuid",
      "name": "Green Valley Ranch",
      "subtitle": "Prairie to planned community in 15 years",
      "earliest_thumbnail": "url",
      "latest_thumbnail": "url",
      "key_stat": "Population grew 4,200% since 1990",
      "slug": "green-valley-ranch"
    },
    ...
  ]
```

---

## 4. Shareable URLs

Every parcel view should have a clean, shareable URL that someone can paste into Slack or a README and it works.

### URL Structure

```
/                              → Landing page
/explore/{parcel_id}           → Full timeline view for a parcel
/explore/{parcel_id}?snap=uuid → Timeline view with a specific snapshot selected
/compare/{parcel_id}?a=uuid&b=uuid → Comparison view between two snapshots
/featured/{slug}               → Featured location (redirects to /explore/{parcel_id})
```

### Implementation

- Use React Router for client-side routing
- On the `/explore/{parcel_id}` route:
  - If the parcel exists and has a completed timeline, render the full view immediately
  - If the parcel exists but the timeline is still processing, show a loading state with progressive results
  - If the parcel doesn't exist, show a 404 with a search bar to try a different address
- The `?snap=uuid` query parameter auto-selects that snapshot on the timeline and loads its imagery on the map
- Update the URL as the user interacts (selecting snapshots, entering comparison mode) using `history.replaceState` — don't create new history entries for every click

### Open Graph / Social Preview

When someone pastes a URL into Slack, Twitter, or iMessage, it should show a rich preview. Add meta tags:

```html
<meta property="og:title" content="Parcel History — 8000 E 49th Ave, Denver CO" />
<meta property="og:description" content="See how this location changed from 1985 to 2024" />
<meta property="og:image" content="{latest_thumbnail_url}" />
<meta property="og:type" content="website" />
```

For a single-page React app, these need to be set server-side. Options:
1. **Simple**: Add a lightweight server-side route (in FastAPI) that serves the HTML shell with correct meta tags for `/explore/{parcel_id}` URLs. The React app hydrates on top.
2. **Simpler**: Use `react-helmet-async` and accept that only crawlers/bots that execute JavaScript will see the meta tags (this covers Slack and Twitter but not all platforms).
3. **Simplest**: Don't worry about it for Phase 5. A nice-to-have, not a must-have.

---

## 5. Developer Experience Polish

### Docker Compose — One Command Setup

The existing Docker Compose from Phase 1 should already work, but verify and tighten:

- `docker compose up` should bring up *everything* — no manual migration step, no separate frontend build
- Add a `depends_on` with health checks so the API doesn't start before PostGIS is ready
- The API container should run Alembic migrations on startup (entrypoint script)
- The frontend dev server should proxy API requests to the backend (already configured in Vite, but verify)
- Add a `docker-compose.prod.yml` override that builds the React app and serves it via nginx — shows you know the difference between dev and prod setups

### .env.example

```env
# Required
CENSUS_API_KEY=your_key_here

# Optional — defaults work for local Docker setup
DATABASE_URL=postgresql+asyncpg://parcel:parcel@db:5432/parcelhistory
REDIS_URL=redis://redis:6379/0
MAPTILER_KEY=optional_for_nicer_basemap
SOCRATA_APP_TOKEN=optional_increases_rate_limit

# Feature flags
ENABLE_TITILER=false
```

### Makefile

Clean up and finalize:

```makefile
.PHONY: up down migrate seed test lint featured

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python scripts/seed.py

featured:
	docker compose exec api python scripts/seed_featured.py

test:
	docker compose exec api pytest -v
	# frontend tests if any exist

lint:
	docker compose exec api ruff check .
	cd frontend && npm run lint

format:
	docker compose exec api ruff format .
	cd frontend && npm run format

clean:
	docker compose down -v --remove-orphans
```

---

## 6. Error States & Edge Cases

Go through the app and make sure every error state is handled with a designed UI, not a blank screen or console error:

### Geocoding Failures
- Invalid address → inline error below search bar
- Census Geocoder API down → "We're having trouble reaching the geocoding service. Try again in a moment." with a retry button
- Address outside the US → "We currently only support US addresses."

### Imagery Gaps
- No imagery found → "No historical imagery available for this location" with context (rural areas, non-CONUS)
- Imagery loading timeout → show whatever loaded with a "Some imagery sources timed out. Showing partial results." banner
- Thumbnail load failure → placeholder card with date/source badge, no broken image icon

### Census Data Gaps
- Tract not found in older decades → show available years, note the gap
- Census API rate limited → retry with backoff, show partial results if some years succeeded

### Property Data
- Unsupported county → designed empty state (already built in Phase 4)
- No records found for a supported county → "No property records found at this address in [County] records. This may be a recently built property or the address format may not match county records."
- Socrata API down → skip gracefully, show imagery and census data without property events

### General
- WebGL not supported (old browser) → show a clear message rather than a blank map
- Mobile viewport → the app should be usable on mobile, even if the experience is simplified. Test the timeline horizontal scroll on touch devices.
- Slow connection → all async data loads should show skeleton/shimmer states, not spinners

---

## 7. Performance Quick Wins

Don't over-optimize, but hit the obvious things:

- **Lazy load thumbnails**: Use `loading="lazy"` on timeline thumbnail images or use an Intersection Observer. A timeline with 30+ thumbnails shouldn't load them all at once.
- **API response caching**: Add `Cache-Control` headers to the imagery and demographics endpoints. Once a timeline is complete, the data is static — cache it for hours.
- **Database query optimization**: Make sure the imagery listing query uses the `(parcel_id, capture_date)` index. Run `EXPLAIN ANALYZE` on the main queries and fix any sequential scans.
- **Bundle size**: Check `npm run build` output. If the bundle is over 500KB gzipped, look for obvious culprits (did Framer Motion or Recharts bring in too much?). Tree-shaking should handle most of it.

---

## What "Done" Looks Like for Phase 5

- [ ] Landing page redesigned with hero section, search bar, featured locations, and tech footer
- [ ] Search-to-map transition is smooth and polished
- [ ] Before/after image comparison works with draggable divider
- [ ] 3–4 featured locations pre-seeded with compelling before/after stories
- [ ] Shareable URLs work — copy a URL, open in new tab, see the same view
- [ ] `docker compose up` brings up the entire stack with no manual steps
- [ ] .env.example exists with clear documentation
- [ ] All error states show designed UI rather than blank screens or raw errors
- [ ] Mobile viewport is usable (doesn't need to be perfect, just not broken)
- [ ] Lighthouse performance score > 80 on the landing page
- [ ] No console errors or warnings in normal usage
