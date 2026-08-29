# Read-path parity — old vs new

* parcels: **189**
* rows, old path: **12884**
* rows, new path: **12884**
* row/count comparisons: **52488**
* id pairs recorded: **51725** over 12884 distinct old ids and 12884 distinct new ids
* fields compared per row pair: **12** (parcel_id, source, capture_date, stac_item_id, stac_collection, cog_url, additional_cog_urls, thumbnail_url, resolution_m, cloud_cover_pct, bbox, created_at)
* same-date reorderings (not a divergence; see `_compare_rows`): **76**

## Divergences: **0**

None.

## Item facts the two shapes disagree about

None.
