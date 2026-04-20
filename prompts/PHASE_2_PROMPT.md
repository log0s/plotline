# Phase 2 — Imagery Timeline

## Context

Phase 1 is complete. We have a working full-stack app with:
- PostgreSQL + PostGIS database with `parcels` and `timeline_requests` tables
- FastAPI backend with a geocode endpoint that calls the US Census Geocoder
- Celery + Redis wired up (worker running but no real tasks yet)
- React + TypeScript frontend with a landing page, search bar, and MapLibre map view
- Docker Compose running everything locally
- A user can enter an address, geocode it, and see it on a map

## Phase 2 Goal

When a user geocodes an address, kick off an async job that searches for all available aerial/satellite imagery at that location across multiple decades. Store the results and render them as a scrollable visual timeline on the frontend. This is the core "wow factor" feature — the user sees their location change over time through real imagery.

---

## New Database Tables

Add these via a new Alembic migration. Do not modify the existing migration file.

```sql
-- Imagery snapshots found for a parcel
CREATE TABLE imagery_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('naip', 'landsat', 'sentinel2')),
    capture_date DATE NOT NULL,
    -- STAC item metadata
    stac_item_id TEXT NOT NULL,
    stac_collection TEXT NOT NULL,
    -- Bounding box of the image (not the parcel — the full scene/tile)
    bbox GEOMETRY(POLYGON, 4326),
    -- URL to the Cloud-Optimized GeoTIFF asset
    cog_url TEXT NOT NULL,
    -- Thumbnail: we generate this by requesting a small image from Titiler
    thumbnail_url TEXT,
    -- Metadata
    resolution_m DOUBLE PRECISION,
    cloud_cover_pct DOUBLE PRECISION,
    -- Prevent duplicates
    UNIQUE (parcel_id, stac_item_id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_imagery_parcel_date ON imagery_snapshots (parcel_id, capture_date);
CREATE INDEX idx_imagery_bbox ON imagery_snapshots USING GIST (bbox);

-- Track individual data source fetch status within a timeline request
CREATE TABLE timeline_request_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timeline_request_id UUID NOT NULL REFERENCES timeline_requests(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('naip', 'landsat', 'sentinel2', 'census', 'property')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'complete', 'failed', 'skipped')),
    items_found INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX idx_trt_request ON timeline_request_tasks (timeline_request_id);
```

The `timeline_request_tasks` table lets us track each data source independently. This way the frontend can show progressive results — "NAIP imagery loaded (12 snapshots), Landsat loading..." — rather than waiting for everything to finish.

---

## STAC API Integration

All imagery comes from the Microsoft Planetary Computer STAC API. No API key required.

**Base URL**: `https://planetarycomputer.microsoft.com/api/stac/v1`

### How STAC Search Works

```python
import httpx

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"

async def search_stac(
    collection: str,
    bbox: tuple[float, float, float, float],  # (west, south, east, north)
    datetime_range: str,  # e.g. "2003-01-01/2024-12-31"
    max_items: int = 50,
    query: dict | None = None,  # additional property filters
) -> list[dict]:
    """Search a STAC collection for items intersecting a bounding box."""
    async with httpx.AsyncClient(timeout=30) as client:
        items = []
        payload = {
            "collections": [collection],
            "bbox": list(bbox),
            "datetime": datetime_range,
            "limit": min(max_items, 100),  # API max per page is 100
        }
        if query:
            payload["query"] = query

        resp = await client.post(f"{STAC_API}/search", json=payload)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("features", []))

        # Handle pagination if needed
        while len(items) < max_items:
            next_link = next(
                (l for l in data.get("links", []) if l["rel"] == "next"),
                None
            )
            if not next_link:
                break
            resp = await client.get(next_link["href"])
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("features", []))

        return items[:max_items]
```

### Collections to Search

#### NAIP (Best visual quality, ~1m resolution)
- **Collection**: `naip`
- **Date range**: 2003–present (varies by state, typically every 2–3 years)
- **Key asset**: `image` — this is a 4-band (RGBIR) COG
- **Notes**: No cloud cover metadata (it's aerial, so flights happen on clear days). This is the most visually compelling source — you can see individual buildings, cars, trees.

```python
naip_items = await search_stac(
    collection="naip",
    bbox=parcel_bbox,
    datetime_range="2003-01-01/2025-12-31",
    max_items=30,
)
# COG URL: item["assets"]["image"]["href"]
```

#### Landsat (Longest history, 30m resolution)
- **Collection**: `landsat-c2-l2` (Collection 2, Level 2 — surface reflectance)
- **Date range**: 1984–present
- **Key assets**: Individual bands. For a natural color composite, use `red`, `green`, `blue`. For display, use the `rendered_preview` asset if available.
- **Cloud filter**: Use `eo:cloud_cover` property to filter. Keep items under 20% cloud cover.
- **Notes**: 30m resolution means you won't see buildings, but you'll clearly see land use changes — farmland to suburb, forest to clearcut, lake level changes.

```python
landsat_items = await search_stac(
    collection="landsat-c2-l2",
    bbox=parcel_bbox,
    datetime_range="1984-01-01/2025-12-31",
    max_items=50,
    query={"eo:cloud_cover": {"lt": 20}},
)
# Rendered preview: item["assets"].get("rendered_preview", {}).get("href")
# Or individual bands: item["assets"]["red"]["href"], etc.
```

#### Sentinel-2 (Recent years, 10m resolution)
- **Collection**: `sentinel-2-l2a`
- **Date range**: 2015–present
- **Key asset**: `rendered_preview` for quick display, or `B04` (red), `B03` (green), `B02` (blue) for raw bands
- **Cloud filter**: `eo:cloud_cover` < 20

```python
sentinel_items = await search_stac(
    collection="sentinel-2-l2a",
    bbox=parcel_bbox,
    datetime_range="2015-01-01/2025-12-31",
    max_items=30,
    query={"eo:cloud_cover": {"lt": 20}},
)
```

### Generating a Bounding Box from a Parcel Point

The geocoded point is just a lat/lng. We need a bounding box to search imagery. Create a small buffer around the point:

```python
from shapely.geometry import Point
from shapely.ops import transform
import pyproj

def point_to_bbox(lat: float, lng: float, buffer_m: float = 500) -> tuple[float, float, float, float]:
    """Create a bounding box around a point. Returns (west, south, east, north)."""
    # Project to a meter-based CRS, buffer, project back
    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS(f"EPSG:{get_utm_epsg(lng, lat)}")

    project_to_utm = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
    project_to_wgs = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True).transform

    point_utm = transform(project_to_utm, Point(lng, lat))
    buffer_utm = point_utm.buffer(buffer_m)
    buffer_wgs = transform(project_to_wgs, buffer_utm)

    return buffer_wgs.bounds  # (minx, miny, maxx, maxy) = (west, south, east, north)

def get_utm_epsg(lng: float, lat: float) -> int:
    """Get the UTM zone EPSG code for a given lat/lng."""
    zone = int((lng + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone
```

---

## Thumbnail Generation

We need thumbnails for the timeline UI. Two approaches — use whichever is more practical:

### Option A: Titiler (Preferred)
If Titiler is running as a service, request a small PNG tile crop:

```
GET http://titiler:8000/cog/preview?url={cog_url}&width=400&height=400&rescale=0,255
```

Store the resulting image in a local `/thumbnails` directory (mounted as a Docker volume) and save the local path in `imagery_snapshots.thumbnail_url`.

### Option B: STAC Rendered Preview
Many STAC items include a `rendered_preview` or `thumbnail` asset. Use this directly as the thumbnail URL — no processing needed. Check:

```python
thumbnail_url = (
    item["assets"].get("rendered_preview", {}).get("href")
    or item["assets"].get("thumbnail", {}).get("href")
)
```

For NAIP, you'll need to generate thumbnails (Option A) since NAIP items don't consistently have preview assets. For Landsat and Sentinel-2, `rendered_preview` is usually available.

### Signing Planetary Computer URLs
Planetary Computer COG URLs require signing for direct access. Use their token endpoint:

```python
import httpx

async def sign_planetary_computer_url(url: str) -> str:
    """Sign a Planetary Computer asset URL for access."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://planetarycomputer.microsoft.com/api/sas/v1/sign",
            params={"href": url},
        )
        resp.raise_for_status()
        return resp.json()["href"]
```

Call this before serving any COG URL to the frontend or to Titiler.

---

## Celery Tasks

### Task: `fetch_imagery_timeline`

This is the main orchestrator task. It runs when a user geocodes an address (or explicitly requests a timeline refresh).

```python
# Pseudocode — implement with proper error handling, logging, retries

@celery_app.task(bind=True, max_retries=3)
def fetch_imagery_timeline(self, timeline_request_id: str):
    """
    1. Load the timeline_request and its associated parcel
    2. Compute bounding box from parcel point
    3. Create timeline_request_tasks rows for each source
    4. For each source (naip, landsat, sentinel2):
       a. Update task status to 'processing'
       b. Search STAC API
       c. For each item found:
          - Extract metadata (date, cloud cover, resolution, COG URL)
          - Generate or fetch thumbnail URL
          - Insert into imagery_snapshots (skip duplicates via ON CONFLICT)
       d. Update task status to 'complete' with items_found count
    5. Update timeline_request status to 'complete'
    """
```

**Important behaviors:**
- Each source should be fetched independently so one failure doesn't block the others. If Sentinel-2 search fails, NAIP and Landsat results should still be available.
- Use database-level deduplication (the UNIQUE constraint on `parcel_id, stac_item_id`) so re-running the task is idempotent.
- For NAIP, prefer one image per year (pick the one closest to mid-summer for best vegetation visibility). NAIP often has multiple items per year for the same area — don't store all of them or the timeline gets noisy.
- For Landsat, aim for roughly one image per year. Pick the lowest cloud cover item within each calendar year.
- For Sentinel-2, one per quarter is plenty for the timeline view.
- Log the total wall time for each source search. This data is interesting for DEVELOPMENT.md.

### Triggering the Task

Modify the existing `POST /api/v1/geocode` endpoint (or create a new endpoint) to automatically kick off the imagery fetch after geocoding:

```python
# After inserting/finding the parcel:
timeline_request = create_timeline_request(parcel_id=parcel.id)
fetch_imagery_timeline.delay(str(timeline_request.id))
# Return the timeline_request_id to the frontend so it can poll
```

---

## New API Endpoints

```
POST /api/v1/parcels/{parcel_id}/timeline
  Triggers a new timeline fetch for an existing parcel.
  Creates a timeline_request, kicks off the Celery task.
  Response: { "timeline_request_id": "uuid" }

GET /api/v1/timeline-requests/{request_id}
  Returns the timeline request status including per-source task status.
  Response: {
    "id": "uuid",
    "status": "processing",
    "tasks": [
      { "source": "naip", "status": "complete", "items_found": 12 },
      { "source": "landsat", "status": "processing", "items_found": 0 },
      { "source": "sentinel2", "status": "queued", "items_found": 0 }
    ]
  }

GET /api/v1/parcels/{parcel_id}/imagery
  Returns all imagery snapshots for a parcel, sorted by capture_date ascending.
  Supports query params for filtering:
    ?source=naip — filter to a single source
    ?start_date=1990-01-01&end_date=2024-12-31 — date range
  Response: {
    "parcel_id": "uuid",
    "snapshots": [
      {
        "id": "uuid",
        "source": "landsat",
        "capture_date": "1985-06-15",
        "cog_url": "https://...",  # signed URL
        "thumbnail_url": "https://...",
        "resolution_m": 30.0,
        "cloud_cover_pct": 8.2
      },
      ...
    ]
  }

GET /api/v1/tiles/{z}/{x}/{y}
  (Optional — only if running Titiler as a sidecar service)
  Proxy to Titiler for serving COG tiles to MapLibre.
  Query param: ?url={signed_cog_url}
```

**URL Signing**: The `/imagery` endpoint must sign all COG URLs before returning them. Planetary Computer SAS tokens are time-limited, so sign them at response time, not at ingest time.

---

## Frontend Changes

### Polling for Timeline Status

After geocoding, the frontend receives a `timeline_request_id`. Poll the status endpoint every 2 seconds until all tasks are complete (or use SSE/WebSocket if you want to be fancy, but polling is fine for Phase 2).

Show a subtle loading state on the map view:
- "Searching for historical imagery..."
- As each source completes, update: "Found 12 NAIP images (1984–2023) • Loading Landsat..."
- When all sources are done, transition to the timeline view

### Timeline Component

This is the centerpiece UI. Build a vertical scrollable timeline on the right side (or bottom, your call) of the map view:

```
┌─────────────────────────────────────────────────┐
│                                                   │
│                   MAP VIEW                        │
│          (showing current imagery layer)          │
│                                                   │
├─────────────────────────────────────────────────┤
│  ← 1985      1995      2005      2015    2024 →  │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐         │
│  │thumb │  │thumb │  │thumb │  │thumb │  ...     │
│  │ nail │  │ nail │  │ nail │  │ nail │         │
│  └──────┘  └──────┘  └──────┘  └──────┘         │
│  Landsat   NAIP      NAIP      Sentinel          │
│  Jun 1985  Jul 2005  Aug 2015  Mar 2024          │
└─────────────────────────────────────────────────┘
```

**Behaviors:**
- Thumbnails are arranged chronologically left-to-right
- Each thumbnail is labeled with the source (color-coded badge) and date
- Clicking a thumbnail loads that imagery layer on the map
- The currently selected snapshot is highlighted
- Source filter toggles (NAIP / Landsat / Sentinel-2) let users show/hide sources
- Smooth scroll with Framer Motion, keyboard arrow key navigation
- On first load, auto-select the most recent NAIP image (best visual quality)

### Map Imagery Layer

When a user selects a snapshot from the timeline:

1. Take the signed COG URL
2. If using Titiler: add it as a raster tile source in MapLibre, pointed at Titiler's tile endpoint
3. If not using Titiler: use the `rendered_preview` URL as a static image overlay
4. Crossfade transition between the previous and new imagery layer (MapLibre supports layer opacity animation)
5. Show a small info chip on the map: "NAIP • August 12, 2015 • 1m resolution"

### Fallback for Slow/Missing Imagery

- If no imagery is found for a parcel, show a helpful empty state: "No historical imagery available for this location. This can happen for very rural areas or locations outside the continental US."
- If thumbnails fail to load, show a placeholder with the date and source badge — don't break the timeline layout.

---

## Titiler Setup (Optional but Recommended)

Add Titiler as a service in Docker Compose:

```yaml
titiler:
  image: ghcr.io/developmentseed/titiler:latest
  ports:
    - "8001:8000"
  environment:
    - WORKERS_PER_CORE=1
    - MAX_WORKERS=2
```

This gives you a local tile server that can dynamically render COGs. The frontend can request tiles at any zoom level without downloading entire GeoTIFFs.

If Titiler adds too much complexity for Phase 2, skip it and use the STAC rendered preview URLs directly. You can always add it later. The important thing is that the timeline works.

---

## Testing

### Backend Tests
- STAC search client: mock the Planetary Computer API responses, verify correct parsing of items
- Bounding box generation: test with known coordinates, verify the buffer math
- Celery task: mock STAC searches, verify imagery_snapshots are inserted correctly
- Deduplication: run the same task twice, verify no duplicate snapshots
- API endpoints: test the imagery listing with filtering and sorting
- URL signing: mock the signing endpoint, verify URLs are signed at response time

### Manual Testing Checklist
Use these addresses to verify the timeline works across different scenarios:
- **Denver suburb** (e.g., "8000 E 49th Ave, Denver CO") — should show clear farmland-to-suburb transition in NAIP
- **Rural Colorado** (e.g., "40.5, -105.5 area") — should have Landsat but sparse NAIP
- **Coastal change** (e.g., somewhere on the Outer Banks, NC) — shoreline erosion visible in Landsat
- **Major development** (e.g., near DIA airport) — dramatic change from prairie to airport infrastructure

---

## What "Done" Looks Like for Phase 2

- [ ] User geocodes an address and imagery search starts automatically
- [ ] Frontend shows real-time progress as each source completes
- [ ] Timeline renders with thumbnails, source badges, and dates
- [ ] Clicking a thumbnail changes the imagery layer on the map with a smooth transition
- [ ] Source filter toggles work
- [ ] Second visit to the same parcel loads cached imagery instantly (no re-fetch)
- [ ] Empty state handled gracefully
- [ ] At least 4 backend tests covering STAC integration and task logic
- [ ] No regressions to Phase 1 functionality
