# Footprint revalidation — execute

Started 2026-08-29T20:36:43+00:00. Finished 2026-08-29T20:36:45+00:00 (2 s).

Queue at start: **2** rows (`footprint IS NOT NULL AND NOT ST_IsValid(footprint) AND source <> :excluded`, with `:excluded` = `'usgs_topo'`), batch size 200. NORM-31's sweep: every row whose stored footprint fails `ST_IsValid`, of any provenance, refetched and rewritten through `normalize_footprint`. Footprint only — no `bbox` and no `resolution_m` is written in this mode.

Rows fetched: **2**. STAC requests issued: **2**.

## Totals

| Outcome | Rows |
|---|---|
| matched and written | 2 |
| unmatched — item GET 404 | 0 |
| unmatched — item GET 403 | 0 |
| error | 0 |

| Column | Rows |
|---|---|
| `footprint` rewritten | 2 |
| `bbox` filled (was NULL) | 0 |
| `resolution_m` rewritten | 0 |

Wrote 2 row(s). Queue after this run: **0**.

## `resolution_m` rewrites, by source

None: every fetched item agreed with the value already stored.

## Items carrying no `gsd`

| Source | Rows |
|---|---|
| sentinel2 | 2 |

`resolution_m` was left as stored for these rows. `None` is never written over a value.

## Capture-date disagreements

None. Every matched item's `datetime` equals the row's `capture_date`.

## Anomalies

None.

## Footprint invariants, after the run

All three must be `0`. The third is NORM-31's addition: every prediction in this arc asked the first two and none asked whether the polygon was *valid*, which is how two self-intersecting rows passed three layers of checks.

| Check | Rows |
|---|---|
| footprint not `POLYGON` | 0 |
| footprint equal to its own bbox | 0 |
| footprint fails `ST_IsValid` | 0 |

Query: `SELECT count(*) FILTER (WHERE GeometryType(footprint) <> 'POLYGON') AS not_polygon, count(*) FILTER (WHERE NOT ST_IsValid(footprint)) AS invalid, count(*) FILTER (WHERE ST_Equals(footprint, ST_Envelope(footprint))) AS equals_bbox FROM scenes WHERE footprint IS NOT NULL`

## Findings

Unresolved ids and unexpected resolutions, one line each. Every row named here was left exactly as it was.

None.
