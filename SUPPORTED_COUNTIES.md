# Supported Counties — Property History Data Sources

Plotline fetches building permit records from county open data portals. Both
Denver and Adams County migrated from Socrata to ArcGIS Hub in ~2025, so the
adapters now use ArcGIS Feature Service REST APIs. Property sales data is no
longer available via public API for either county.

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
