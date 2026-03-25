# Phase 4 — Property History Events

## Context

Phases 1–3 are complete. We have:
- Geocoding, parcel storage, and map view (Phase 1)
- Async imagery timeline from NAIP, Landsat, and Sentinel-2 (Phase 2)
- Census demographic charts synced to the imagery timeline (Phase 3)

## Phase 4 Goal

Add the third narrative layer: what has actually *happened* on this specific parcel. Property sales, building permits, zoning changes — the concrete events that explain *why* the land looks different in 2020 than it did in 1995. A user should be able to see "sold for $85,000 in 1998, teardown permit in 2016, new construction permit in 2017, sold for $620,000 in 2019" and connect those events to the satellite imagery showing a small house replaced by a larger one.

The data comes from county open data portals. We're scoping to the Denver metro area (Denver, Adams, Jefferson, Arapahoe counties) because they have strong Socrata-based open data APIs. The architecture should make it straightforward to add more counties later.

---

## Data Sources

All Denver metro county open data portals run on Socrata (or CKAN), which provides a standard REST API called SODA (Socrata Open Data API). No API key required for moderate usage, though a free app token increases rate limits.

### Denver County

| Dataset | Socrata Endpoint | Key Fields |
|---------|-----------------|------------|
| Real Property Sales | `data.denvergov.org` resource `hmrh-5s3x` | `address`, `sale_date`, `sale_price`, `reception_num` |
| Building Permits | `data.denvergov.org` resource `jea5-cqgq` | `address`, `issue_date`, `permit_type`, `project_description`, `valuation` |
| Active Zoning | `data.denvergov.org` resource `gmgx-n2ra` | `zone_district`, geometry | 

### Adams County

| Dataset | Socrata Endpoint | Key Fields |
|---------|-----------------|------------|
| Property Sales | `data.adcogov.org` — search for "sales" | `situs_address`, `sale_date`, `sale_price` |
| Building Permits | `data.adcogov.org` — search for "permits" | `address`, `issue_date`, `type`, `description` |

### Jefferson County

| Dataset | Socrata Endpoint | Key Fields |
|---------|-----------------|------------|
| Property Sales | Check `data.jeffco.us` or Colorado open data | Varies |

### Fallback: Colorado DOLA (Dept of Local Affairs)

If county-specific data is unavailable, the state DOLA portal (`data.colorado.gov`) has statewide property and assessment data, though it's less granular.

**Important**: Socrata dataset resource IDs and field names change over time. Before building, verify each endpoint by visiting the data portal in a browser and checking the API docs tab. The prompt gives you starting points, not guaranteed stable IDs.

---

## Socrata SODA API Primer

All queries follow this pattern:

```
GET https://{domain}/resource/{resource_id}.json
  ?$where=address LIKE '%1600 PENNSYLVANIA%'
  &$order=sale_date DESC
  &$limit=100
```

### Key Query Features

```python
import httpx

SOCRATA_HEADERS = {
    # Optional but increases rate limit from 1000/hr to 10000/hr
    "X-App-Token": "your_app_token_here"
}

async def query_socrata(
    domain: str,
    resource_id: str,
    where: str | None = None,
    order: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query a Socrata dataset."""
    params = {"$limit": limit}
    if where:
        params["$where"] = where
    if order:
        params["$order"] = order

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://{domain}/resource/{resource_id}.json",
            params=params,
            headers=SOCRATA_HEADERS,
        )
        resp.raise_for_status()
        return resp.json()
```

### Address Matching Challenge

This is the hardest part of Phase 4. County records use inconsistent address formats:
- "1600 PENNSYLVANIA AVE" vs "1600 Pennsylvania Avenue" vs "1600 PENNSYLVANIA AV"
- Some include unit numbers, some don't
- Some use directional prefixes ("E 49TH AVE"), some don't

**Strategy — layered matching:**

1. **Normalize the geocoded address**: uppercase, strip unit/apt numbers, standardize suffixes (AVE→AV, STREET→ST, BOULEVARD→BLVD, DRIVE→DR), strip trailing directionals
2. **Query broadly**: use SoQL `LIKE` with the street number + first word of street name: `$where=upper(address) LIKE '1600 PENNSYLVANIA%'`
3. **Filter results client-side**: apply fuzzy matching (Levenshtein distance or token set ratio) on the returned results to pick the correct records
4. **Accept imperfection**: some parcels won't match. This is a portfolio project, not a title company — log the miss and move on.

Build a `services/address_normalizer.py` utility:

```python
import re

SUFFIX_MAP = {
    "AVENUE": "AVE", "STREET": "ST", "BOULEVARD": "BLVD",
    "DRIVE": "DR", "ROAD": "RD", "LANE": "LN", "COURT": "CT",
    "PLACE": "PL", "CIRCLE": "CIR", "TERRACE": "TER",
    "PARKWAY": "PKWY", "WAY": "WAY", "TRAIL": "TRL",
}

def normalize_address(address: str) -> str:
    """Normalize an address for fuzzy matching against county records."""
    addr = address.upper().strip()
    # Remove unit/apt/suite
    addr = re.sub(r'\s*(APT|UNIT|STE|SUITE|#)\s*\S+', '', addr)
    # Standardize suffixes
    for long, short in SUFFIX_MAP.items():
        addr = re.sub(rf'\b{long}\b', short, addr)
    # Remove extra whitespace
    addr = re.sub(r'\s+', ' ', addr)
    return addr

def extract_search_terms(address: str) -> tuple[str, str]:
    """Extract street number and street name start for LIKE query."""
    normalized = normalize_address(address)
    parts = normalized.split()
    if len(parts) >= 2:
        return parts[0], parts[1]  # e.g. ("1600", "PENNSYLVANIA")
    return parts[0], ""
```

---

## New Database Table

```sql
CREATE TABLE property_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'sale', 'permit_building', 'permit_demolition', 'permit_electrical',
        'permit_mechanical', 'permit_plumbing', 'permit_other',
        'zoning_change', 'assessment'
    )),
    event_date DATE,                  -- nullable: some records lack dates
    -- Sale-specific
    sale_price INTEGER,               -- null for non-sale events
    -- Permit-specific
    permit_type TEXT,                  -- raw permit type from source
    permit_description TEXT,           -- project description
    permit_valuation INTEGER,         -- estimated project cost
    -- General
    description TEXT,                 -- human-readable summary
    source TEXT NOT NULL,             -- e.g. "denver_sales", "denver_permits"
    source_record_id TEXT,            -- original record ID from the county
    raw_data JSONB,                   -- full original record
    -- Dedup
    UNIQUE (parcel_id, source, source_record_id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_property_events_parcel_date ON property_events (parcel_id, event_date);
CREATE INDEX idx_property_events_type ON property_events (parcel_id, event_type);
```

**Design notes:**
- `event_type` is normalized across counties. Raw permit types vary wildly ("BLDR" vs "Building" vs "B-NEW CONSTRUCTION"), so we normalize into a small enum and keep the raw value in `permit_type`.
- `source_record_id` is whatever ID the county uses (reception number, permit number, etc.) — this powers deduplication.
- `raw_data JSONB` stores the full Socrata response row so we can re-extract fields later without re-fetching.

---

## County Data Adapters

Build an adapter pattern so each county's quirks are isolated. This is important architectural signal for a portfolio project — it shows you know how to handle messy real-world integrations cleanly.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PropertyEvent:
    """Normalized property event from any county source."""
    event_type: str
    event_date: date | None
    sale_price: int | None
    permit_type: str | None
    permit_description: str | None
    permit_valuation: int | None
    description: str
    source: str
    source_record_id: str
    raw_data: dict

class CountyAdapter(ABC):
    """Base class for county open data adapters."""

    @abstractmethod
    async def fetch_sales(self, street_number: str, street_name: str) -> list[PropertyEvent]:
        ...

    @abstractmethod
    async def fetch_permits(self, street_number: str, street_name: str) -> list[PropertyEvent]:
        ...

class DenverAdapter(CountyAdapter):
    DOMAIN = "data.denvergov.org"
    SALES_RESOURCE = "hmrh-5s3x"      # verify this is current
    PERMITS_RESOURCE = "jea5-cqgq"    # verify this is current

    async def fetch_sales(self, street_number: str, street_name: str) -> list[PropertyEvent]:
        where = f"upper(address) LIKE '{street_number} {street_name}%'"
        rows = await query_socrata(self.DOMAIN, self.SALES_RESOURCE, where=where)
        return [self._parse_sale(row) for row in rows]

    def _parse_sale(self, row: dict) -> PropertyEvent:
        return PropertyEvent(
            event_type="sale",
            event_date=parse_date(row.get("sale_date")),
            sale_price=safe_int(row.get("sale_price")),
            permit_type=None,
            permit_description=None,
            permit_valuation=None,
            description=self._format_sale_description(row),
            source="denver_sales",
            source_record_id=row.get("reception_num", row.get("id", "")),
            raw_data=row,
        )

    def _format_sale_description(self, row: dict) -> str:
        price = safe_int(row.get("sale_price"))
        if price and price > 0:
            return f"Sold for ${price:,}"
        return "Property sale recorded (price not disclosed)"

    async def fetch_permits(self, street_number: str, street_name: str) -> list[PropertyEvent]:
        where = f"upper(address) LIKE '{street_number} {street_name}%'"
        rows = await query_socrata(self.DOMAIN, self.PERMITS_RESOURCE, where=where)
        return [self._parse_permit(row) for row in rows]

    def _parse_permit(self, row: dict) -> PropertyEvent:
        return PropertyEvent(
            event_type=self._classify_permit(row.get("permit_type", "")),
            event_date=parse_date(row.get("issue_date")),
            sale_price=None,
            permit_type=row.get("permit_type"),
            permit_description=row.get("project_description"),
            permit_valuation=safe_int(row.get("valuation")),
            description=self._format_permit_description(row),
            source="denver_permits",
            source_record_id=row.get("permit_num", row.get("id", "")),
            raw_data=row,
        )

    def _classify_permit(self, raw_type: str) -> str:
        raw = raw_type.upper()
        if "DEMO" in raw:
            return "permit_demolition"
        if "ELEC" in raw:
            return "permit_electrical"
        if "MECH" in raw:
            return "permit_mechanical"
        if "PLUM" in raw:
            return "permit_plumbing"
        if any(k in raw for k in ("BUILD", "BLDR", "NEW", "ADDITION", "REMODEL")):
            return "permit_building"
        return "permit_other"

    def _format_permit_description(self, row: dict) -> str:
        parts = []
        ptype = row.get("permit_type", "Permit")
        parts.append(ptype)
        desc = row.get("project_description")
        if desc:
            # Truncate long descriptions
            parts.append(f"— {desc[:120]}")
        val = safe_int(row.get("valuation"))
        if val and val > 0:
            parts.append(f"(${val:,} valuation)")
        return " ".join(parts)


class AdamsCountyAdapter(CountyAdapter):
    """Adapter for Adams County open data. Verify endpoints before building."""
    DOMAIN = "data.adcogov.org"
    # TODO: verify resource IDs from the data portal
    ...


# Registry for selecting the right adapter
COUNTY_ADAPTERS: dict[str, CountyAdapter] = {
    "denver": DenverAdapter(),
    # "adams": AdamsCountyAdapter(),
    # "jefferson": JeffersonAdapter(),
}

def get_adapter_for_county(county: str) -> CountyAdapter | None:
    """Return the appropriate adapter, or None if the county isn't supported."""
    normalized = county.lower().replace(" county", "").strip()
    return COUNTY_ADAPTERS.get(normalized)
```

### Adapter Selection

When the Celery task runs, it uses the parcel's `county` field (stored during geocoding) to pick the right adapter. If no adapter exists for that county, the task marks the `property` timeline_request_task as `skipped` with a message like "Property data not yet available for El Paso County" — don't fail, just skip gracefully.

---

## Celery Task

```python
@celery_app.task(bind=True, max_retries=3)
def fetch_property_history(self, timeline_request_id: str):
    """
    1. Load parcel, determine county
    2. Get the appropriate CountyAdapter (or skip if unsupported)
    3. Extract street number + street name from the normalized address
    4. Fetch sales and permits in parallel (asyncio.gather)
    5. Apply fuzzy address matching to filter false positives
    6. Insert into property_events (ON CONFLICT skip)
    7. Update timeline_request_task status
    """
```

**Fuzzy matching detail:**
After fetching results from Socrata, compare each result's address to the parcel's normalized address. Use a simple token-based approach — you don't need a full fuzzy matching library:

```python
def is_address_match(parcel_address: str, record_address: str, threshold: float = 0.85) -> bool:
    """Check if a record's address matches the parcel address."""
    a = set(normalize_address(parcel_address).split())
    b = set(normalize_address(record_address).split())
    if not a or not b:
        return False
    intersection = a & b
    # Jaccard-like similarity
    return len(intersection) / max(len(a), len(b)) >= threshold
```

This is intentionally simple. It catches "1600 PENNSYLVANIA AVE" matching "1600 PENNSYLVANIA AV UNIT 3" while filtering out "1600 PENN ST" (different street). For a portfolio project, this is plenty. You could swap in `thefuzz` (formerly `fuzzywuzzy`) if you want something more robust.

---

## New API Endpoints

```
GET /api/v1/parcels/{parcel_id}/events
  Returns all property events for a parcel, sorted by event_date ascending.
  Supports query params:
    ?type=sale — filter by event type
    ?type=permit_building,permit_demolition — multiple types (comma-separated)
    ?start_date=2000-01-01&end_date=2024-12-31
  Response: {
    "parcel_id": "uuid",
    "county": "Denver",
    "supported": true,   # false if no adapter exists for this county
    "events": [
      {
        "id": "uuid",
        "event_type": "sale",
        "event_date": "1998-04-15",
        "description": "Sold for $85,000",
        "sale_price": 85000,
        "permit_type": null,
        "permit_description": null,
        "permit_valuation": null,
        "source": "denver_sales"
      },
      {
        "id": "uuid",
        "event_type": "permit_demolition",
        "event_date": "2016-09-22",
        "description": "DEMO — Demolition of single family residence ($12,000 valuation)",
        "sale_price": null,
        "permit_type": "DEMO",
        "permit_description": "Demolition of single family residence",
        "permit_valuation": 12000,
        "source": "denver_permits"
      },
      ...
    ],
    "summary": {
      "total_events": 8,
      "total_sales": 3,
      "total_permits": 5,
      "price_history": [
        { "date": "1998-04-15", "price": 85000 },
        { "date": "2012-08-03", "price": 195000 },
        { "date": "2019-11-14", "price": 620000 }
      ],
      "appreciation": "629% since first recorded sale"
    }
  }
```

The `summary` object is computed server-side. The `price_history` array and `appreciation` string give the frontend what it needs for the price chart and headline stat without doing math client-side.

---

## Frontend Changes

### Events on the Timeline

Property events should appear *on the existing imagery timeline*, interleaved with the imagery snapshots. This is what ties everything together — the user sees:

```
1998            2005          2016         2017          2019         2023
┌──────┐     ┌──────┐     ┌────────┐   ┌────────┐   ┌──────────┐  ┌──────┐
│NAIP  │     │NAIP  │     │ SOLD   │   │ PERMIT │   │  SOLD    │  │NAIP  │
│aerial│     │aerial│     │$195,000│   │New Bld │   │ $620,000 │  │aerial│
└──────┘     └──────┘     └────────┘   └────────┘   └──────────┘  └──────┘
 Landsat      NAIP                      Demo+Build    Sale          NAIP
                          Sale
```

**Event cards on the timeline:**
- Visually distinct from imagery thumbnails — use a different card style (no image, icon-based)
- Icon per event type: 🏷️ sale (or a price tag icon), 🔨 building permit, 🏗️ demolition permit, ⚡ electrical, etc. (use Lucide icons, not emoji)
- Sale cards prominently show the price
- Permit cards show the permit type and a truncated description
- Clicking an event card shows full details in a popover or the sidebar — full description, valuation, source link, raw data toggle for the curious

### Price History Chart

Add to the demographics panel (or as its own section):

**Sale Price Over Time** — Line/scatter chart
- X-axis: date
- Y-axis: sale price ($)
- Data points for each sale, connected by line
- Headline stat: total appreciation percentage
- If only one sale exists, show it as a single point with no trend line

This chart is powerful next to the median home value chart from Phase 3 — it shows how *this specific property* tracked against the *neighborhood median*.

### Event Filter Toggles

Add filter toggles to the timeline control bar:
- Sales (on by default)
- Building permits (on by default)
- Other permits (off by default — electrical/plumbing permits add noise)

### Unsupported County State

If the parcel is in a county without an adapter:
- Show a tasteful empty state in the events section: "Property records not yet available for [County Name]. Currently supported: Denver, Adams, Jefferson counties."
- Don't hide the section entirely — the empty state communicates that the feature exists and coverage is expanding
- The imagery timeline and demographics should still work fine

---

## Socrata Endpoint Verification

**Critical step before building**: Socrata resource IDs and field names change when datasets are updated or republished. Before Claude Code starts writing adapters:

1. Visit each data portal URL in a browser
2. Search for the relevant dataset
3. Click "API" or "API Docs" to get the current resource ID and field names
4. Update the adapter code accordingly

Build this verification step into the task — if the Socrata endpoint returns a 404 or the expected fields are missing, log a clear error and mark the source as failed rather than crashing.

Add a `SUPPORTED_COUNTIES.md` doc that lists each county, its data portal URL, the dataset resource IDs, and when they were last verified. This helps future contributors (and future you) keep the integrations current.

---

## Testing

### Backend Tests
- Address normalizer: test with a variety of Denver-style addresses, verify correct normalization and search term extraction
- Fuzzy address matching: test true matches, near misses, and false positives
- DenverAdapter: mock Socrata responses, verify correct parsing of sales and permits
- Permit classification: test the raw permit type → normalized event_type mapping with real Denver permit type strings
- Event deduplication: insert the same events twice, verify no duplicates
- Price history computation: verify appreciation calculation with multiple sales
- Unsupported county handling: verify graceful skip behavior

### Manual Testing Checklist
- **Property with rich history** (e.g., an older Denver home that's been sold multiple times) — should show sales, possibly permits
- **New construction** (e.g., a recently built home in Stapleton/Central Park) — should show building permits and recent sale
- **Commercial property** (e.g., something on Colfax Ave) — may have different permit patterns
- **Address outside Denver metro** (e.g., Colorado Springs) — should show unsupported county state, no crash
- **Address with unit number** (e.g., a condo) — test that address normalization strips the unit for matching

---

## What "Done" Looks Like for Phase 4

- [ ] Denver county adapter fetches real sales and permit data from Socrata
- [ ] At least one additional county adapter exists (Adams or Jefferson), even if data is sparse
- [ ] Address normalization and fuzzy matching produce reasonable results
- [ ] Property events appear on the imagery timeline, interleaved chronologically
- [ ] Event cards are visually distinct from imagery thumbnails with appropriate icons
- [ ] Clicking an event shows full details
- [ ] Price history chart renders in the demographics panel
- [ ] Appreciation summary computed and displayed
- [ ] Event filter toggles work
- [ ] Unsupported county shows graceful empty state
- [ ] `SUPPORTED_COUNTIES.md` documents data sources and field mappings
- [ ] At least 5 backend tests covering adapters, address matching, and edge cases
- [ ] No regressions to Phases 1–3
