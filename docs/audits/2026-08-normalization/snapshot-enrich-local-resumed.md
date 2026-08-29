# Snapshot-scene enrichment — execute

Started 2026-08-29T07:18:14+00:00. Finished 2026-08-29T07:19:44+00:00 (90 s).

Queue at start: **431** rows (`provenance = 'snapshot' AND footprint IS NULL AND source <> 'usgs_topo'`), batch size 200. Excluded from the queue: **143** `usgs_topo` rows — `usgs-historical-topo` is not a Planetary Computer collection, so those scenes have no item to fetch.

Rows fetched: **431**. STAC requests issued: **431**.

## Totals

| Outcome | Rows |
|---|---|
| matched and written | 431 |
| unmatched — item GET 404 | 0 |
| unmatched — item GET 403 | 0 |
| error | 0 |

| Column | Rows |
|---|---|
| `footprint` filled | 431 |
| `bbox` filled (was NULL) | 0 |
| `resolution_m` rewritten | 93 |

Wrote 431 row(s). Queue after this run: **0**.

## `resolution_m` rewrites, by source

| Source | Stored | Item | Rows |
|---|---|---|---|
| naip | 1.0 | 0.3 | 15 |
| naip | 1.0 | 0.5 | 3 |
| naip | 1.0 | 0.6 | 75 |

## Items carrying no `gsd`

| Source | Rows |
|---|---|
| sentinel2 | 213 |

`resolution_m` was left as stored for these rows. `None` is never written over a value.

## Capture-date disagreements

None. Every matched item's `datetime` equals the row's `capture_date`.

## Anomalies

None.

## Findings

Unresolved ids and unexpected resolutions, one line each. Every row named here was left exactly as it was.

None.
