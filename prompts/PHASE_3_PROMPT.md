# Phase 3 — Census Demographic Context

## Context

Phases 1 and 2 are complete. We have:
- Geocoding, parcel storage, and map view (Phase 1)
- Async imagery fetching from NAIP, Landsat, and Sentinel-2 via STAC API (Phase 2)
- A scrollable timeline of aerial/satellite imagery with source filtering and map layer switching

## Phase 3 Goal

Add demographic context to the timeline. When a user views a parcel, show how the *surrounding neighborhood* has changed alongside the imagery — population growth, income shifts, housing age, density changes. This turns the app from "cool satellite photos" into an actual analytical tool that tells a story about a place.

The data source is the US Census Bureau API, pulling both Decennial Census (1990, 2000, 2010, 2020) and American Community Survey (ACS) 5-year estimates (2009–present, annual).

---

## Census Bureau API Primer

**Base URL**: `https://api.census.gov/data`

**API key**: Free, required. Register at https://api.census.gov/key_signup.html. Store as `CENSUS_API_KEY` environment variable. Add to Docker Compose env and pydantic-settings config.

### How the API Works

Every request targets a specific dataset + vintage (year) and asks for variables at a geography level.

```
GET https://api.census.gov/data/{year}/{dataset}?get={variables}&for={geography}&key={key}
```

The response is a 2D array — first row is headers, remaining rows are data:
```json
[
  ["NAME", "B01003_001E", "state", "county", "tract"],
  ["Census Tract 62.02, Denver County, Colorado", "4523", "08", "031", "006202"]
]
```

### Datasets We Care About

| Dataset | Path | Years | Granularity | Best For |
|---------|------|-------|-------------|----------|
| Decennial Census SF1 | `{year}/dec/sf1` | 1990, 2000, 2010 | Block | Total population, housing units, vacancy |
| Decennial Census DHC | `2020/dec/dhc` | 2020 | Block | 2020 equivalent of SF1 |
| ACS 5-Year | `{year}/acs/acs5` | 2009–2023 | Tract | Income, education, commute, housing value |

**Important**: The 1990 and 2000 APIs have slightly different variable names than 2010+. The code needs to handle this mapping.

### Key Variables

#### Population & Housing (Decennial)

| Variable | Description | Available |
|----------|-------------|-----------|
| `P001001` (1990/2000) or `P1_001N` (2010) or `P1_001N` (2020 DHC) | Total population | All years |
| `H001001` (1990/2000) or `H1_001N` (2010/2020) | Total housing units | All years |
| `H003003` (1990/2000) or `H3_003N` (2010/2020) | Vacant housing units | All years |

#### Socioeconomic (ACS 5-Year, tract level)

| Variable | Description |
|----------|-------------|
| `B01003_001E` | Total population |
| `B19013_001E` | Median household income |
| `B25077_001E` | Median home value |
| `B25035_001E` | Median year structure built |
| `B25003_001E` | Total occupied housing units |
| `B25003_002E` | Owner-occupied units |
| `B25003_003E` | Renter-occupied units |
| `B08303_001E` | Total commuters |
| `B08303_013E` | Commuters with 60+ minute commute |
| `B01002_001E` | Median age |
| `B25064_001E` | Median gross rent |

The `E` suffix means "estimate." There's a corresponding `M` suffix for margin of error — fetch both if you want to show confidence intervals, but it's optional for Phase 3.

### Geography: Census Tracts

We're pulling data at the **tract** level, which is the sweet spot — small enough to represent a neighborhood (~4,000 people), large enough that data is reliably available across all years.

From Phase 1, we already store `census_tract_id` on the parcel. The Census Geocoder returns the tract FIPS code. A tract FIPS is structured as: `{state_fips}{county_fips}{tract_code}` — e.g., `08031006202` = Colorado (08), Denver County (031), Tract 006202.

To query the Census API for a tract:
```
GET https://api.census.gov/data/2020/acs/acs5
  ?get=B01003_001E,B19013_001E,B25077_001E
  &for=tract:006202
  &in=state:08%20county:031
  &key={CENSUS_API_KEY}
```

### Tract Boundary Changes Over Time

**This is a real gotcha.** Census tract boundaries change between decades. A tract that existed in 1990 may have been split into three tracts by 2020 as the area grew. For Phase 3, we'll handle this simply:

- For each decade, query the tract that contains the parcel point *in that decade's geography*
- Use the Census Geocoder's vintage parameter to find which tract the point falls in for older decades
- Alternatively, use the NHGIS crosswalk files — but that's overkill for now

The simplest approach: just query the current tract ID for ACS data (which always uses the most recent tract boundaries), and accept that decennial data for older decades might be slightly misaligned. Note this limitation in the UI with a small tooltip. Perfecting cross-decade tract normalization is a rabbit hole — don't go down it in Phase 3.

---

## New Database Table

```sql
CREATE TABLE census_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    tract_fips TEXT NOT NULL,          -- full FIPS: state + county + tract
    dataset TEXT NOT NULL CHECK (dataset IN ('decennial', 'acs5')),
    year INTEGER NOT NULL,
    -- Demographics
    total_population INTEGER,
    median_household_income INTEGER,   -- in nominal dollars for that year
    median_home_value INTEGER,         -- in nominal dollars for that year
    median_year_built INTEGER,         -- e.g. 1978
    total_housing_units INTEGER,
    occupied_housing_units INTEGER,
    owner_occupied_units INTEGER,
    renter_occupied_units INTEGER,
    vacancy_rate DOUBLE PRECISION,     -- computed: vacant / total
    median_age DOUBLE PRECISION,
    median_gross_rent INTEGER,
    -- Raw response for anything we want to pull out later
    raw_data JSONB,
    -- Dedup
    UNIQUE (parcel_id, dataset, year),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_census_parcel_year ON census_snapshots (parcel_id, year);
```

**Design note**: Columns are nullable because not every variable is available in every dataset/year. Decennial data won't have income or home value; ACS won't go back further than 2009. The `raw_data` JSONB column stores the full API response so we can extract additional variables later without re-fetching.

---

## Census Fetch Service

Create a `services/census.py` module:

```python
class CensusFetcher:
    """Client for the US Census Bureau API."""

    BASE_URL = "https://api.census.gov/data"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)

    async def fetch_acs5(
        self, year: int, state_fips: str, county_fips: str, tract_code: str
    ) -> dict:
        """Fetch ACS 5-year estimates for a tract."""
        variables = [
            "B01003_001E",  # population
            "B19013_001E",  # median income
            "B25077_001E",  # median home value
            "B25035_001E",  # median year built
            "B25003_001E",  # occupied units
            "B25003_002E",  # owner occupied
            "B25003_003E",  # renter occupied
            "B01002_001E",  # median age
            "B25064_001E",  # median rent
        ]
        resp = await self.client.get(
            f"{self.BASE_URL}/{year}/acs/acs5",
            params={
                "get": ",".join(variables),
                "for": f"tract:{tract_code}",
                "in": f"state:{state_fips} county:{county_fips}",
                "key": self.api_key,
            },
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def fetch_decennial(
        self, year: int, state_fips: str, county_fips: str, tract_code: str
    ) -> dict:
        """Fetch decennial census data for a tract."""
        # Variable names differ by decade — map them
        if year == 2020:
            dataset = "dec/dhc"
            vars = {"P1_001N": "population", "H1_001N": "housing_units"}
        elif year == 2010:
            dataset = "dec/sf1"
            vars = {"P001001": "population", "H001001": "housing_units"}
        else:  # 2000, 1990
            dataset = "dec/sf1"
            vars = {"P001001": "population", "H001001": "housing_units"}

        resp = await self.client.get(
            f"{self.BASE_URL}/{year}/{dataset}",
            params={
                "get": ",".join(vars.keys()),
                "for": f"tract:{tract_code}",
                "in": f"state:{state_fips} county:{county_fips}",
                "key": self.api_key,
            },
        )
        resp.raise_for_status()
        raw = self._parse_response(resp.json())
        # Normalize to consistent field names
        return {vars[k]: v for k, v in raw.items() if k in vars}

    def _parse_response(self, data: list[list[str]]) -> dict:
        """Convert Census API's header+rows format to a dict."""
        if len(data) < 2:
            return {}
        headers = data[0]
        values = data[1]
        return {
            h: self._to_number(v)
            for h, v in zip(headers, values)
            if h not in ("state", "county", "tract")
        }

    @staticmethod
    def _to_number(val: str) -> int | float | None:
        """Census API returns numbers as strings. -666666666 means 'not available'."""
        if val is None or val == "" or val == "-666666666":
            return None
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return None
```

### Years to Fetch

For a given parcel, fetch:
- **Decennial**: 1990, 2000, 2010, 2020
- **ACS 5-Year**: 2009, 2012, 2015, 2018, 2021, 2023 (every ~3 years to avoid redundancy — ACS is rolling 5-year, so consecutive years overlap heavily)

This gives ~10 data points spanning 1990–2023, which is enough to show clear trends without hammering the API.

---

## Celery Task Integration

Add a `census` source to the existing `fetch_imagery_timeline` task (or create a separate `fetch_census_data` task — your call on task granularity).

```python
@celery_app.task(bind=True, max_retries=3)
def fetch_census_data(self, timeline_request_id: str):
    """
    1. Load the parcel and extract tract FIPS components
       (state_fips, county_fips, tract_code from the stored census_tract_id)
    2. Update the timeline_request_task for 'census' to 'processing'
    3. For each target year:
       a. Call the appropriate Census API (decennial or ACS)
       b. Insert into census_snapshots (ON CONFLICT skip for idempotency)
       c. Handle 204/404 gracefully — some tracts don't exist in older decades
    4. Update task status to 'complete' with items_found count
    """
```

**Error handling specifics:**
- The Census API returns HTTP 204 (no content) when a tract doesn't exist in a given vintage. This is expected for older decades — log it and move on.
- The API has rate limits (~500 requests/day without key, much higher with key). We're making ~10 requests per parcel, so this won't be an issue for a portfolio project, but add a small delay (0.5s) between requests to be a good citizen.
- If a specific year fails, log the error and continue with other years. Don't fail the whole task over one missing data point.

---

## New API Endpoints

```
GET /api/v1/parcels/{parcel_id}/demographics
  Returns all census snapshots for a parcel, sorted by year ascending.
  Response: {
    "parcel_id": "uuid",
    "tract_fips": "08031006202",
    "snapshots": [
      {
        "year": 1990,
        "dataset": "decennial",
        "total_population": 2841,
        "median_household_income": null,
        "median_home_value": null,
        "total_housing_units": 1205,
        "vacancy_rate": 0.04
      },
      {
        "year": 2009,
        "dataset": "acs5",
        "total_population": 4523,
        "median_household_income": 52340,
        "median_home_value": 215000,
        "total_housing_units": 1876,
        "vacancy_rate": 0.06,
        "median_age": 34.2,
        "owner_occupied_units": 1102,
        "renter_occupied_units": 662,
        "median_gross_rent": 1150,
        "median_year_built": 1978
      },
      ...
    ],
    "notes": "Census tract boundaries may differ across decades. Data shown is for the tract containing this address in each respective year's geography."
  }
```

---

## Frontend Changes

### Demographics Panel

Add a collapsible panel below (or beside) the imagery timeline. When census data is loaded, show a set of small, clean charts that tell the neighborhood story at a glance.

#### Charts to Build (use Recharts or a lightweight charting library)

**1. Population Over Time** — Line chart
- X-axis: year (1990–2023)
- Y-axis: total population
- Single line, data points marked
- This is the headline number — "this tract went from 2,800 to 12,000 people"

**2. Housing Growth** — Stacked bar chart
- X-axis: year
- Y-axis: housing units
- Stacked bars: owner-occupied (one color), renter-occupied (another), vacant (gray)
- Shows the ownership vs rental shift over time

**3. Income & Home Value** — Dual-axis line chart (ACS years only, 2009+)
- Left axis: median household income
- Right axis: median home value
- Two lines, clearly labeled
- Add a note: "Nominal dollars (not inflation-adjusted)"

**4. Neighborhood Snapshot Card** — Not a chart, just a styled info card showing the *most recent* ACS data:
- Median age
- Median rent
- Median year structures built (this is surprisingly evocative — "the typical home here was built in 1962")
- Owner vs renter percentage as a simple donut or progress bar

#### Chart Design Guidelines

- Match the existing dark theme from Phase 1
- Use the accent color palette (earthy tones) for data series
- Keep charts small — these are glanceable summaries, not analytical dashboards
- No chart junk: no 3D, no excessive gridlines, no decorative elements
- Subtle animation on load (Framer Motion fade + slide up, staggered per chart)
- Each chart should have a plain-English subtitle that interprets the data: "Population grew 340% since 1990" or "Shifted from 70% owner-occupied to 55% since 2009"
- Generate these subtitle strings on the backend in the API response — compute the deltas server-side so the frontend just renders them

#### Responsive Layout

```
Desktop (≥1024px):
┌────────────────────────────────────────────────┐
│                    MAP VIEW                     │
├─────────────────────┬──────────────────────────┤
│   Imagery Timeline  │   Demographics Panel     │
│   (horizontal       │   (vertical stack of     │
│    scroll)          │    charts)               │
└─────────────────────┴──────────────────────────┘

Mobile (<1024px):
┌──────────────────────┐
│      MAP VIEW        │
├──────────────────────┤
│  Imagery Timeline    │
│  (horizontal scroll) │
├──────────────────────┤
│  Demographics Panel  │
│  (stacked charts)    │
└──────────────────────┘
```

### Timeline Integration

Sync the imagery timeline with the demographics panel. When a user clicks a 2005 NAIP image, subtly highlight the nearest census data point on the charts (a vertical reference line or a pulsing dot on the population line chart). This visual connection between "what the land looked like" and "who lived there" is what makes the app feel cohesive rather than being two disconnected data views.

---

## Testing

### Backend Tests
- Census API client: mock responses for each dataset type (decennial 2020, ACS 2023, decennial 2000 with different variable names)
- Handle the -666666666 "not available" sentinel value correctly
- Handle 204/404 responses for non-existent tracts gracefully
- FIPS parsing: verify correct splitting of tract_fips into state, county, tract components
- Demographics endpoint: verify sorting and computed fields (vacancy_rate, subtitle strings)
- Idempotency: run the census fetch task twice, verify no duplicate snapshots

### Manual Testing Checklist
- **Rapidly growing area** (e.g., "5000 E 56th Ave, Commerce City CO") — should show dramatic population + housing growth
- **Stable established neighborhood** (e.g., "1500 Pearl St, Denver CO") — relatively flat population, rising income/values
- **Rural area** (e.g., somewhere in eastern Colorado) — small numbers, possible tract boundary issues in older decades
- **New development** (e.g., near Green Valley Ranch, Denver) — tract may not exist in 1990, should handle gracefully

---

## What "Done" Looks Like for Phase 3

- [ ] Census API key configured in environment and Docker Compose
- [ ] Census fetch runs as part of the timeline build (or as a parallel task)
- [ ] Frontend shows progressive loading: "Census data loading..." then charts appear
- [ ] All four chart types render with real data
- [ ] Charts have interpretive subtitles generated server-side
- [ ] Selecting an imagery snapshot highlights the corresponding era on the demographic charts
- [ ] Neighborhood snapshot card shows latest ACS data
- [ ] Graceful handling of missing data (null values, non-existent tracts in older decades)
- [ ] Tract boundary caveat noted in the UI
- [ ] At least 4 backend tests covering Census API parsing and edge cases
- [ ] No regressions to Phase 1 or Phase 2 functionality
