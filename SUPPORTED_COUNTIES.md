# Supported Counties — Property History Data Sources

Plotline fetches property sale and building permit records from county open data
portals. Each county uses a Socrata (SODA) API. Below is the current list of
supported counties, their data portal URLs, dataset resource IDs, and key field
mappings.

**Last verified: 2026-03-25**

---

## Denver County

**Portal**: https://data.denvergov.org

| Dataset | Resource ID | Key Fields | Notes |
|---------|-------------|------------|-------|
| Real Property Sales | `hmrh-5s3x` | `address`, `sale_date`, `sale_price`, `reception_num` | Address field is uppercase |
| Building Permits | `jea5-cqgq` | `address`, `issue_date`, `permit_type`, `project_description`, `valuation`, `permit_num` | `permit_type` values: BLDR, DEMO, ELEC, MECH, PLUM, etc. |

**Address format**: Uppercase, no unit numbers in most records.
Example: `"1600 PENNSYLVANIA AVE"`

---

## Adams County

**Portal**: https://data.adcogov.org

| Dataset | Resource ID | Key Fields | Notes |
|---------|-------------|------------|-------|
| Property Sales | `s3yg-wa5f` | `situs_address`, `sale_date`, `sale_price`, `reception_number` | Address field name differs from Denver |
| Building Permits | `37ih-ctda` | `address`, `issue_date`, `type`, `description`, `valuation`, `permit_number` | `type` instead of `permit_type` |

**Note**: Adams County resource IDs should be verified against the portal before
production use. They may change when datasets are republished.

---

## Adding a New County

To add support for a new county:

1. Find the county's open data portal (typically Socrata-based).
2. Locate the property sales and building permits datasets.
3. Note the resource ID (the `xxxx-xxxx` code in the API URL).
4. Map the county's field names to our normalized schema.
5. Create a new adapter class in `backend/app/services/county_adapters.py`:
   - Subclass `CountyAdapter`
   - Implement `fetch_sales()` and `fetch_permits()`
   - Map raw field names to `PropertyEventData`
6. Register the adapter in `COUNTY_ADAPTERS` dict.
7. Add the county to this document.
8. Write tests for the new adapter's parsing logic.

### Common Socrata Gotchas

- **Field names are case-sensitive** in SoQL queries.
- **Resource IDs change** when datasets are republished.
- **Address formats vary wildly** — always use `upper()` in queries and fuzzy matching on results.
- **Rate limits**: 1,000 requests/hour without an app token, 10,000/hour with one.
  Set `SOCRATA_APP_TOKEN` in `.env` if needed.
- **Date formats**: Usually ISO-8601 (`"2020-01-15T00:00:00.000"`) but can vary.
