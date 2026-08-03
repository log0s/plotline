# Supported Counties — Property History Data Sources

Plotline fetches property sales and building permit records from county open
data portals. Each county uses a different API: Denver and Adams use ArcGIS
Feature Services, DC uses DCGIS ArcGIS REST services (MapServer layers), Santa
Clara (San Jose) uses CKAN, and New York County (Manhattan) uses Socrata.

Everything below is derived from the shipped adapter code
(`backend/app/services/county_adapters.py` plus the `arcgis.py`, `ckan.py`,
and `socrata.py` clients). Field lists show what the parsers actually read,
not everything the upstream dataset offers. If this document and the code
disagree, the code wins — re-verify here whenever an adapter changes.

**Last verified: 2026-08-03**

---

## How queries and matching work (all counties)

- The timeline task reduces the parcel address to a street number plus the
  first street-name word, skipping a directional prefix
  ("1600 Pennsylvania Ave NW" → `1600` + `PENNSYLVANIA`) —
  `address_normalizer.extract_search_terms`.
- Adapters run deliberately broad queries with those two terms. Every record
  that comes back is fuzzy-matched against the full parcel address — exact
  street-number match plus ≥0.7 street-name token overlap
  (`address_normalizer.is_address_match`) — before it is saved. The LIKE
  patterns below only need to be broad enough; precision comes from this
  post-filter. Records with no situs address bypass the filter.
- Permit types normalize to `permit_building`, `permit_demolition`,
  `permit_electrical`, `permit_mechanical`, `permit_plumbing`, or
  `permit_other` (`classify_permit`; "RENEWAL" short-circuits to other so it
  doesn't match "NEW"). Sales are `sale`. Events dedupe on
  `(parcel_id, source, source_record_id)` at upsert.
- Every upstream query is individually wrapped: a failing portal logs a
  warning and contributes zero events; it never fails the timeline.
- **Row caps, no pagination**: every query fetches a single page (caps noted
  per county below). No client paginates — anything past the cap is silently
  dropped. ArcGIS and Socrata queries order by date descending, so their caps
  keep the most recent records; San Jose's CKAN query has no ordering, so its
  cap keeps an arbitrary subset.

---

## Denver County

**Portal**: https://opendata-geospatialdenver.hub.arcgis.com

| Dataset | Feature Service URL | Fields Read | Notes |
|---------|-------------------|------------|-------|
| Residential Construction Permits | `services1.arcgis.com/zdB7qR0BtYrg0Xpl/.../ODC_DEV_RESIDENTIALCONSTPERMIT_P/FeatureServer/316` | `ADDRESS`, `DATE_ISSUED`, `CLASS`, `VALUATION`, `PERMIT_NUM`, `CONTRACTOR_NAME` | `DATE_ISSUED` is epoch-ms. `CLASS` is the permit type; `PERMIT_NUM` is the record id. Ordered `DATE_ISSUED DESC`, max 100 rows/layer. |
| Commercial Construction Permits | `services1.arcgis.com/zdB7qR0BtYrg0Xpl/.../ODC_DEV_COMMERCIALCONSTPERMIT_P/FeatureServer/317` | Same fields | Queried in parallel with residential. |
| Property Sales | *Not available* | — | `fetch_sales()` is a permanent `return []` stub. *History: Socrata dataset `hmrh-5s3x` on data.denvergov.org was retired when Denver moved to ArcGIS Hub (~2025); no replacement exists on the Hub.* |

**Address matching**: `upper(ADDRESS) LIKE '{number} %{street}%'` — the
wildcard between number and street absorbs directional prefixes
(e.g., "1437 N BANNOCK ST").

---

## Adams County

**Portal**: https://data-adcogov.opendata.arcgis.com

| Dataset | Feature Service URL | Fields Read | Notes |
|---------|-------------------|------------|-------|
| Building Permits (Eye On Adams) | `services3.arcgis.com/4PNQOtAivErR7nbT/.../Building_Permits_Eye_On_Adams/FeatureServer/0` | `CombinedAddress`, `CaseOpened`, `TypeOfWork`, `ClassOfWork`, `Description`, `RecordID_` | `CaseOpened` is epoch-ms and is the event date (there is no issue-date field). Permit type is `TypeOfWork`, falling back to `ClassOfWork`. Record id is `RecordID_` (trailing underscore). No valuation column is read — Adams permit events never carry a valuation. Ordered `CaseOpened DESC`, max 100 rows. |
| Property Sales | *Not available* | — | `fetch_sales()` is a permanent `return []` stub. *History: the old Socrata domain `data.adcogov.org` is defunct; no public sales API was found after the ArcGIS Hub migration.* |

**Address matching**: `upper(CombinedAddress) LIKE '{number} %{street}%'`.

**Coverage note**: Adams County data only covers unincorporated areas.
Municipalities like Thornton, Westminster, and Northglenn issue their own
permits and do not publish them through the county portal.

---

## District of Columbia

**Portal**: https://opendata.dc.gov (DCGIS ArcGIS REST services)

| Dataset | Service URL | Fields Read | Notes |
|---------|------------|------------|-------|
| Property Sales (ITSPE FACTS) | `maps2.dcgis.dc.gov/.../DCGIS_DATA/Property_and_Land_WebMercator/MapServer/56` | `SSL`, `PROPERTY_ADDRESS`, `LAST_SALE_PRICE`, `LAST_SALE_DATE`, `DEED_DATE`, `LAND_USE_DESCRIPTION` | Assessment table holding each property's **last** sale only, so DC yields at most one sale event per matching record — not a full sales history. Rows without `LAST_SALE_PRICE` are dropped. Dates are epoch-ms; `DEED_DATE` is the fallback date. Record id is `SSL`. Max 20 rows. (`APPRAISED_VALUE_CURRENT_TOTAL` is also fetched but only retained in `raw_data`.) |
| Building Permits (DCRA) | `maps2.dcgis.dc.gov/.../FEEDS/DCRA/MapServer/{layer}` | `FULL_ADDRESS`, `ISSUE_DATE`, `PERMIT_TYPE_NAME`, `PERMIT_SUBTYPE_NAME`, `DESC_OF_WORK`, `FEES_PAID`, `PERMIT_ID` | Year-specific layers queried in parallel; layer ids are not contiguous: 2→2020, 3→2021, 14→2022, 15→2023, 16→2024, 17→2025, 18→2026. `ISSUE_DATE` is epoch-ms. `FEES_PAID` is stored as the event's valuation. Record id is `PERMIT_ID`. Ordered `ISSUE_DATE DESC`, max 50 rows/layer. |

**Address matching**: `upper(PROPERTY_ADDRESS) LIKE '{number} %{street}%'` for
sales; the same pattern on `FULL_ADDRESS` for permits. The pattern is anchored
at the start deliberately — an earlier leading-wildcard version also matched
"1100 X" when searching for "100 X".

---

## Santa Clara County (City of San Jose)

**Portal**: https://data.sanjoseca.gov (CKAN)

| Dataset | CKAN Resource ID | Fields Read | Notes |
|---------|-----------------|------------|-------|
| Building Permits (Active) | `761b7ae8-3be1-4ad6-923d-c7af6404a904` | `gx_location`, `ISSUEDATE`, `WORKDESCRIPTION`, `FOLDERDESC`, `FOLDERNAME`, `PERMITVALUATION`, `CONTRACTOR`, `FOLDERNUMBER` | `ISSUEDATE` format is "3/8/2026 12:00:00 AM" (M/D/YYYY, ISO fallback). Permit type is `WORKDESCRIPTION`, falling back to `FOLDERDESC`. Record id is `FOLDERNUMBER`. Max 100 rows/resource, unordered. |
| Building Permits (Under Inspection) | `89ccdad9-7309-4826-a5f3-2fcf1fcb20fa` | Same fields | Separate dataset per permit status. No status field is read — a permit's status is implied by which resource returned it. |
| Building Permits (Expired) | `df4b8461-0c7a-4d16-b85d-ff7f71c5fed5` | Same fields | All three resources are queried in parallel. |
| Property Sales | *Not available* | — | `fetch_sales()` is a permanent `return []` stub — no public sales API. |

**Address matching**: CKAN Datastore full-text search with
`q="{number} {street}"` (full-text across all columns — CKAN has no per-field
LIKE), then a client-side filter: the first token of `gx_location` must equal
the street number and the street name must appear in the string. Plain
substring matching would let "12" match "512 S 1ST ST".

**Coverage note**: This adapter covers City of San Jose addresses only. Other
cities in Santa Clara County (Sunnyvale, Mountain View, Cupertino, etc.) may
have their own portals or no public data.

---

## New York County (Manhattan)

**Portal**: https://data.cityofnewyork.us (Socrata / NYC Open Data)

| Dataset | Socrata Resource ID | Fields Read | Notes |
|---------|-------------------|------------|-------|
| Property Sales (Citywide Annualized Calendar) | `w2pb-icbu` | `address`, `sale_price`, `sale_date`, `neighborhood`, `building_class_category`, `block`, `lot` | Sales history back to 2016. Filtered to borough 1 (Manhattan); excludes $0 sales. Ordered `sale_date DESC`, max 200 rows. |
| Property Sales (Citywide Rolling Calendar) | `usep-8jbt` | Same fields | Trailing ~12 months — the only source for the current year. Queried in parallel with the annualized dataset; overlapping rows dedupe via the `{block}-{lot}-{sale_date}` record id. |
| Building Permits (DOB Permit Issuance) | `ipu4-2q9a` | `house__`, `street_name`, `issuance_date`, `job_type`, `permit_type`, `owner_s_business_name`, `filing_status`, `job__` | Filtered to borough MANHATTAN. `job_type` codes map to labels (NB→New Building, A1→Major Alteration, A2/A3→Minor Alteration, DM→Demolition); `permit_type` is the fallback label. `issuance_date` is MM/DD/YYYY or ISO. Record id is `job__`. Ordered `issuance_date DESC`, max 100 rows. |

**Address matching**:
`borough='1' AND upper(address) LIKE '%{number} {street}%' AND sale_price > 0`
for sales;
`borough='MANHATTAN' AND house__='{number}' AND upper(street_name) LIKE '%{street}%'`
for permits.

**App token**: `SOCRATA_APP_TOKEN` (optional, via `.env`) is sent as
`X-App-Token` for higher rate limits. NYC is the only Socrata adapter, so the
token affects nothing else.

---

## Known coverage gaps

- Only the five jurisdictions above have adapters. For any other county —
  Clark County, NV (Las Vegas) is a notable large one — the property task is
  skipped with "Property data not yet available for {county} County".
- Sales data exists only for DC (last sale per property) and NYC. Denver,
  Adams, and San Jose are permits-only; their `fetch_sales()` stubs
  permanently return `[]`.
- Adams County covers unincorporated areas only — Thornton, Westminster, and
  Northglenn permits are not in the county portal. San Jose is the only
  covered city in Santa Clara County.
- All row caps above are single-request limits; no client paginates.

---

## Adding a New County

To add support for a new county:

1. Find the county's open data portal (ArcGIS Hub, Socrata, CKAN, or other).
2. Locate building permits and/or property sales datasets.
3. Identify the Feature Service URL and layer ID (or Socrata/CKAN resource ID).
4. Map the county's field names to our normalized schema.
5. Create a new adapter class in `backend/app/services/county_adapters.py`:
   - Subclass `CountyAdapter`
   - Implement `fetch_sales()` and `fetch_permits()` (a permanent
     `return []` stub is fine where a source doesn't exist)
   - Query through the shared clients: `arcgis.query_feature_service`,
     `socrata.query_socrata`, or `ckan.query_ckan_datastore`
   - Map raw field names to `PropertyEventData`, and set `situs_address` so
     the fuzzy post-filter can reject near-miss records
6. Register the adapter in the `COUNTY_ADAPTERS` dict. Lookup keys are
   lowercase with any trailing " county" stripped — "New York County"
   resolves to "new york".
7. Add the county to this document.
8. Write tests for the new adapter's parsing logic.

### ArcGIS Feature Service Notes

- **Query endpoint**: `{service_url}/query?where=...&outFields=*&f=json&returnGeometry=false`
- **Date fields**: Returned as epoch-milliseconds (divide by 1000 for Unix timestamp).
- **Integer fields**: Don't quote numeric values in WHERE clauses.
- **Result limits**: Upstream defaults vary per service (often 1,000–2,000
  per request), but our client always sends `resultRecordCount` (default 100)
  and fetches a single page.
- Non-200 responses and `error` objects in the JSON raise `ArcGISError`;
  adapters catch per-layer and return `[]`.

### Socrata Notes

- **Field names are case-sensitive** in SoQL queries.
- **Resource IDs change** when datasets are republished. *(History: this is
  how Denver's `hmrh-5s3x` and Adams's data.adcogov.org portal died —
  both migrated to ArcGIS Hub and the Socrata resources vanished.)*
- **404 means empty, not error**: the client treats HTTP 404 as "dataset
  deleted" and returns `[]` with a warning — a retired resource quietly
  yields zero events rather than failing the timeline.
- **Rate limits**: 1,000 requests/hour without an app token, 10,000/hour with
  one. Set `SOCRATA_APP_TOKEN` in `.env` if needed.
- **Redirects**: some portals redirect silently. *(History: this bit us
  early on; all three clients now hardwire `follow_redirects=True`.)*

### CKAN Notes

- **Endpoint**: `https://{domain}/api/3/action/datastore_search`.
- **`q` is full-text across all columns** — there is no per-field LIKE. Do
  exact filtering client-side (see San Jose) or via the `filters` param
  (exact-match only; currently unused).
- Responses carry a `success` flag; failures raise `CKANError`.
- `limit` defaults to 100; `offset` exists but nothing paginates.
