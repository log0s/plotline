-- Local-database state snapshot, run before and after the vetting sweep.
-- Read-only. Post-0019 schema: imagery lives in scenes + parcel_scenes.
--   docker compose exec -T postgres psql -U plotline -d plotline -f - \
--     < docs/audits/2026-09-featured-vetting/queries/state_snapshot.sql

\pset pager off
\echo '== snapshot taken at'
SELECT now() AT TIME ZONE 'UTC' AS utc;

\echo '== fleet totals'
SELECT
  (SELECT count(*) FROM parcels) AS parcels,
  (SELECT count(*) FROM parcel_scenes) AS parcel_scenes,
  (SELECT count(*) FROM scenes) AS scenes,
  (SELECT count(*) FROM census_snapshots) AS census_snapshots,
  (SELECT count(*) FROM property_events) AS property_events,
  (SELECT count(*) FROM timeline_requests) AS timeline_requests,
  (SELECT count(*) FROM timeline_request_tasks) AS tasks,
  (SELECT count(*) FROM timeline_task_years) AS ledger_rows;

\echo '== per-parcel imagery counts (parcels created 2026-09-11 or featured)'
SELECT coalesce(f.slug, left(p.id::text, 8)) AS label, ps.source, count(*) AS n,
       min(ps.group_key) AS lo, max(ps.group_key) AS hi
  FROM parcels p
  JOIN parcel_scenes ps ON ps.parcel_id = p.id
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
 WHERE f.slug IS NOT NULL OR p.created_at >= date '2026-09-11'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== per-parcel census rows'
SELECT coalesce(f.slug, left(p.id::text, 8)) AS label, cs.dataset,
       string_agg(cs.year::text, ',' ORDER BY cs.year) AS years,
       string_agg(DISTINCT cs.tract_fips, ',') AS tracts
  FROM parcels p
  JOIN census_snapshots cs ON cs.parcel_id = p.id
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
 WHERE f.slug IS NOT NULL OR p.created_at >= date '2026-09-11'
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== per-parcel property events'
SELECT coalesce(f.slug, left(p.id::text, 8)) AS label, count(pe.id) AS events
  FROM parcels p
  LEFT JOIN property_events pe ON pe.parcel_id = p.id
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
 WHERE f.slug IS NOT NULL OR p.created_at >= date '2026-09-11'
 GROUP BY 1 ORDER BY 1;

\echo '== latest full-scope request per parcel, with task rows'
SELECT coalesce(f.slug, left(p.id::text, 8)) AS label, tr.id AS request, tr.status,
       tr.origin, tr.created_at, t.source, t.status AS task_status, t.items_found,
       t.queries_run, t.queries_failed, t.rows_returned, t.rows_matched, t.coverage,
       left(coalesce(t.error_message, ''), 60) AS err
  FROM parcels p
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
  JOIN LATERAL (
        SELECT * FROM timeline_requests r
         WHERE r.parcel_id = p.id AND array_length(r.sources, 1) = 6
         ORDER BY r.created_at DESC LIMIT 1
       ) tr ON TRUE
  JOIN timeline_request_tasks t ON t.timeline_request_id = tr.id
 WHERE f.slug IS NOT NULL OR p.created_at >= date '2026-09-11'
 ORDER BY 1, t.source;

\echo '== ledger outcomes on that latest full-scope request'
SELECT coalesce(f.slug, left(p.id::text, 8)) AS label, ty.source, ty.outcome,
       coalesce(ty.reason, '') AS reason, count(*) AS n,
       string_agg(ty.group_key, ',' ORDER BY ty.group_key) AS groups
  FROM parcels p
  LEFT JOIN featured_locations f ON f.parcel_id = p.id
  JOIN LATERAL (
        SELECT * FROM timeline_requests r
         WHERE r.parcel_id = p.id AND array_length(r.sources, 1) = 6
         ORDER BY r.created_at DESC LIMIT 1
       ) tr ON TRUE
  JOIN timeline_request_tasks t ON t.timeline_request_id = tr.id
  JOIN timeline_task_years ty ON ty.task_id = t.id
 WHERE f.slug IS NOT NULL OR p.created_at >= date '2026-09-11'
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;
