# Snapshot-scene enrichment — execute

Started 2026-08-29T07:15:34+00:00. **Incomplete — this report was written after a batch, not at the end.**

Queue at start: **1031** rows (`provenance = 'snapshot' AND footprint IS NULL AND source <> 'usgs_topo'`), batch size 200. Excluded from the queue: **143** `usgs_topo` rows — `usgs-historical-topo` is not a Planetary Computer collection, so those scenes have no item to fetch.

Rows fetched: **600**. STAC requests issued: **600**.

## Totals

| Outcome | Rows |
|---|---|
| matched and written | 600 |
| unmatched — item GET 404 | 0 |
| unmatched — item GET 403 | 0 |
| error | 0 |

| Column | Rows |
|---|---|
| `footprint` filled | 600 |
| `bbox` filled (was NULL) | 0 |
| `resolution_m` rewritten | 0 |

Wrote 600 row(s). Queue after this run: **431**.

## `resolution_m` rewrites, by source

None: every fetched item agreed with the value already stored.

## Items carrying no `gsd`

None.

## Capture-date disagreements

None. Every matched item's `datetime` equals the row's `capture_date`.

## Anomalies

None.

## Findings

Unresolved ids and unexpected resolutions, one line each. Every row named here was left exactly as it was.

None.
