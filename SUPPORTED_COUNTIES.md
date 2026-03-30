# Supported Counties — Property History Data Sources

Plotline fetches property sales and building permit records from county open
data portals. Each county uses a different API: Denver and Adams use ArcGIS
Feature Services, DC uses DCGIS ArcGIS REST services, Santa Clara (San Jose)
uses CKAN, and New York County (Manhattan) uses Socrata.

**Last verified: 2026-03-26**

---

## Denver County

**Portal**: https://opendata-geospatialdenver.hub.arcgis.com

| Dataset | Feature Service URL | Key Fields | Notes |
|---------|-------------------|------------|-------|
| Residential Construction Permits | `services1.arcgis.com/zdB7qR0BtYrg0Xpl/.../ODC_DEV_RESIDENTIALCONSTPERMIT_P/FeatureServer/316` | `ADDRESS`, `ADDRESS_NUMBER`, `ADDRESS_STREETNAME`, `DATE_ISSUED`, `CLASS`, `VALUATION`, `PERMIT_NUM`, `CONTRACTOR_NAME` | `DATE_ISSUED` is epoch-ms. `ADDRESS_NUMBER` is integer. |
| Commercial Construction Permits | `services1.arcgis.com/zdB7qR0BtYrg0Xpl/.../ODC_DEV_COMMERCIALCONSTPERMIT_P/FeatureServer/317` | Same field structure as residential | Separate layer for commercial permits |
| Real Property Sales | *Not available* | — | Socrata dataset `hmrh-5s3x` was retired; no replacement on ArcGIS Hub |

**Address matching**: Query uses `upper(ADDRESS) LIKE '{number} %{street}%'` to
handle directional prefixes (e.g., "1437 N BANNOCK ST").

---

## Adams County

**Portal**: https://data-adcogov.opendata.arcgis.com

| Dataset | Feature Service URL | Key Fields | Notes |
|---------|-------------------|------------|-------|
| Building Permits (Eye On Adams) | `services3.arcgis.com/4PNQOtAivErR7nbT/.../Building_Permits_Eye_On_Adams/FeatureServer/0` | `CombinedAddress`, `HouseNumber`, `StreetName`, `CaseOpened`, `TypeOfWork`, `ClassOfWork`, `Description`, `RecordID_` | `CaseOpened` is epoch-ms. `HouseNumber` is integer. |
| Property Sales | *Not available* | — | Old Socrata domain `data.adcogov.org` is defunct; no public sales API found |

**Address matching**: Query uses `upper(CombinedAddress) LIKE '{number} %{street}%'`.

**Coverage note**: Adams County data only covers unincorporated areas.
Municipalities like Thornton, Westminster, and Northglenn issue their own permits
and do not publish them through the county portal.

---

## District of Columbia

**Portal**: https://opendata.dc.gov (DCGIS ArcGIS REST services)

| Dataset | Service URL | Key Fields | Notes |
|---------|------------|------------|-------|
| Property Sales (ITSPE FACTS) | `maps2.dcgis.dc.gov/.../Property_and_Land_WebMercator/MapServer/56` | `PREMISEADD`, `SALEPRICE`, `SALEDATE` | ArcGIS MapServer layer |
| Building Permits (DCRA) | `maps2.dcgis.dc.gov/.../FEEDS/DCRA/MapServer/{layer}` | `FULL_ADDRESS`, `ISSUE_DATE`, `PERMIT_TYPE_NAME`, `FEES_PAID` | Year-specific layers (2020–2026), queried in parallel |

**Address matching**: Query uses `upper(PREMISEADD) LIKE '%{number} {street}%'`.

---

## Santa Clara County (City of San Jose)

**Portal**: https://data.sanjoseca.gov (CKAN)

| Dataset | CKAN Resource ID | Key Fields | Notes |
|---------|-----------------|------------|-------|
| Building Permits (Active) | `761b7ae8-3be1-4ad6-923d-c7af6404a904` | `ADDRESS`, `ISSUED_DATE`, `DESCRIPTION`, `VALUATION`, `STATUS` | CKAN Datastore API |
| Building Permits (Under Inspection) | `89ccdad9-7309-4826-a5f3-2fcf1fcb20fa` | Same fields | Separate dataset per status |
| Building Permits (Expired) | `df4b8461-0c7a-4d16-b85d-ff7f71c5fed5` | Same fields | |
| Property Sales | *Not available* | — | No public API |

**Address matching**: Filters by `ADDRESS` field using number + street name.

**Coverage note**: This adapter covers City of San Jose addresses only. Other
cities in Santa Clara County (Sunnyvale, Mountain View, Cupertino, etc.) may
have their own portals or no public data.

---

## New York County (Manhattan)

**Portal**: https://data.cityofnewyork.us (Socrata / NYC Open Data)

| Dataset | Socrata Resource ID | Key Fields | Notes |
|---------|-------------------|------------|-------|
| Property Sales (Citywide Rolling Calendar) | `usep-8jbt` | `address`, `sale_price`, `sale_date`, `building_class_category` | Filtered to borough 1 (Manhattan); excludes $0 sales |
| Building Permits (DOB Permit Issuance) | `ipu4-2q9a` | `house__`, `street_name`, `issuance_date`, `job_type`, `permit_type` | Filtered to borough MANHATTAN |

**Address matching**: Uses `upper(address) LIKE '%{number} {street}%'` for
sales; `house__='{number}' AND upper(street_name) LIKE '%{street}%'` for permits.

---

## Adding a New County

To add support for a new county:

1. Find the county's open data portal (ArcGIS Hub, Socrata, or other).
2. Locate building permits and/or property sales datasets.
3. Identify the Feature Service URL and layer ID (or Socrata resource ID).
4. Map the county's field names to our normalized schema.
5. Create a new adapter class in `backend/app/services/county_adapters.py`:
   - Subclass `CountyAdapter`
   - Implement `fetch_sales()` and `fetch_permits()`
   - Map raw field names to `PropertyEventData`
6. Register the adapter in `COUNTY_ADAPTERS` dict.
7. Add the county to this document.
8. Write tests for the new adapter's parsing logic.

### ArcGIS Feature Service Notes

- **Query endpoint**: `{service_url}/query?where=...&outFields=*&f=json&returnGeometry=false`
- **Date fields**: Returned as epoch-milliseconds (divide by 1000 for Unix timestamp).
- **Integer fields**: Don't quote numeric values in WHERE clauses.
- **LIKE queries**: Use `upper(FIELD) LIKE 'VALUE%'` for case-insensitive matching.
- **Result limits**: Default max varies per service (often 1,000–2,000 per request).

### Socrata Notes (for future counties still on Socrata)

- **Field names are case-sensitive** in SoQL queries.
- **Resource IDs change** when datasets are republished.
- **Rate limits**: 1,000 requests/hour without an app token, 10,000/hour with one.
  Set `SOCRATA_APP_TOKEN` in `.env` if needed.
- **Redirects**: Enable `follow_redirects=True` — some portals redirect silently.
