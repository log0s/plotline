# Read-path parity — old vs new

* parcels: **45**
* rows, old path: **3082**
* rows, new path: **3082**
* row/count comparisons: **12560**
* id pairs recorded: **12373** over 3082 distinct old ids and 3082 distinct new ids
* fields compared per row pair: **12** (parcel_id, source, capture_date, stac_item_id, stac_collection, cog_url, additional_cog_urls, thumbnail_url, resolution_m, cloud_cover_pct, bbox, created_at)
* same-date reorderings (not a divergence; see `_compare_rows`): **20**

## Divergences: **12**

| site | parcel | key | field | old | new |
|---|---|---|---|---|---|
| listing | 11111111 | naip/2018 | resolution_m | 0.6 | 1.0 |
| listing | 11111111 | naip/2021 | resolution_m | 0.6 | 1.0 |
| listing | 11111111 | naip/2023 | resolution_m | 0.3 | 1.0 |
| listing[source=naip] | 11111111 | naip/2018 | resolution_m | 0.6 | 1.0 |
| listing[source=naip] | 11111111 | naip/2021 | resolution_m | 0.6 | 1.0 |
| listing[source=naip] | 11111111 | naip/2023 | resolution_m | 0.3 | 1.0 |
| listing[start_date] | 11111111 | naip/2018 | resolution_m | 0.6 | 1.0 |
| listing[start_date] | 11111111 | naip/2021 | resolution_m | 0.6 | 1.0 |
| listing[start_date] | 11111111 | naip/2023 | resolution_m | 0.3 | 1.0 |
| by_id | 11111111 | naip/2018 | resolution_m | 0.6 | 1.0 |
| by_id | 11111111 | naip/2021 | resolution_m | 0.6 | 1.0 |
| by_id | 11111111 | naip/2023 | resolution_m | 0.3 | 1.0 |

### By site

* by_id: 3
* listing: 3
* listing[source=naip]: 3
* listing[start_date]: 3

### By field

* resolution_m: 12

## Item facts the two shapes disagree about

| field | served rows | distinct scenes |
|---|---|---|
| resolution_m | 3 | 3 |
