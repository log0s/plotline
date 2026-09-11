-- Scoring queries for the 2026-09-11 featured-vetting sweep. Read-only.
--   docker compose exec -T postgres psql -U plotline -d plotline -f - \
--     < docs/audits/2026-09-featured-vetting/queries/scorecard.sql
--
-- The twelve parcels are named by id because six of them are not featured
-- rows (the four candidates, the Marshall alternate, the San Jose proposal)
-- and `featured_locations` is deliberately untouched by this batch.

\pset pager off
\set ON_ERROR_STOP on

CREATE TEMP VIEW v_labels (parcel_id, label) AS
VALUES
  ('c78a1019-5cb5-4a07-9fcd-9b109bb05530'::uuid, '1 rino-art-district'),
  ('5c27245c-5827-430b-ad43-baae66e69335'::uuid, '2 hudson-yards'),
  ('c8ecf010-5096-41c4-86e2-00dccb62248c'::uuid, '3 green-valley-ranch'),
  ('800643ba-a8d2-41c9-92e2-d72d6801eb8b'::uuid, '4 navy-yard'),
  ('14518754-4017-46d3-b950-bc764aea37ad'::uuid, '5 rodanthe'),
  ('70a496c7-3480-4752-b3ad-e0bdc59d8736'::uuid, '6 stapleton'),
  ('3003043d-67f9-432e-8bac-9a01a5e09db0'::uuid, '7 marshall-sagamore'),
  ('537b90df-1758-4848-9151-bb65dd6d9a84'::uuid, '8 marshall-louisville'),
  ('e7fabe0d-555e-4483-bef1-4a14ef2e52bf'::uuid, '9 apple-park'),
  ('9973fa5d-15e5-4453-b8ec-4599087f2aaf'::uuid, '10 wharf'),
  ('f4c63907-ce8b-4c5e-b791-6c43daeb99d4'::uuid, '11 cornell-tech'),
  ('80eb0a69-0880-4c0e-8e1b-c26e08b1ad83'::uuid, '12 silver-creek');

-- The request each parcel's page would serve: latest full-scope one.
CREATE TEMP VIEW v_served AS
SELECT l.label, tr.*
  FROM v_labels l
  JOIN LATERAL (
        SELECT * FROM timeline_requests r
         WHERE r.parcel_id = l.parcel_id AND array_length(r.sources, 1) = 6
         ORDER BY r.created_at DESC LIMIT 1
       ) tr ON TRUE;

\echo '== 1. the served request per parcel'
SELECT label, id AS request, status, origin, created_at, completed_at,
       round(extract(epoch FROM (completed_at - created_at))::numeric, 1) AS secs,
       coalesce(error_message, '') AS err
  FROM v_served ORDER BY label;

\echo '== 2. task rows on the served request'
SELECT s.label, t.source, t.status, t.items_found, t.queries_run, t.queries_failed,
       t.rows_returned, t.rows_matched, t.coverage, left(coalesce(t.error_message,''), 70) AS err
  FROM v_served s JOIN timeline_request_tasks t ON t.timeline_request_id = s.id
 ORDER BY s.label, t.source;

\echo '== 3. served imagery rows per source (parcel_scenes)'
SELECT l.label, ps.source, count(*) AS n,
       string_agg(ps.group_key, ',' ORDER BY ps.group_key) AS groups
  FROM v_labels l JOIN parcel_scenes ps ON ps.parcel_id = l.parcel_id
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 4. census rows per dataset, with tract lineage'
SELECT l.label, cs.dataset,
       string_agg(cs.year::text || '@' || cs.tract_fips, ' ' ORDER BY cs.year) AS year_at_tract
  FROM v_labels l JOIN census_snapshots cs ON cs.parcel_id = l.parcel_id
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 5. property events per parcel'
SELECT l.label, count(pe.id) AS events, min(pe.event_date) AS earliest, max(pe.event_date) AS latest
  FROM v_labels l LEFT JOIN property_events pe ON pe.parcel_id = l.parcel_id
 GROUP BY 1 ORDER BY 1;

\echo '== 6. ledger outcomes on the served request, by source/outcome/reason'
SELECT s.label, ty.source, ty.outcome, coalesce(ty.reason, '') AS reason, count(*) AS n,
       string_agg(ty.group_key, ',' ORDER BY ty.group_key) AS groups
  FROM v_served s
  JOIN timeline_request_tasks t ON t.timeline_request_id = s.id
  JOIN timeline_task_years ty ON ty.task_id = t.id
 GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

\echo '== 7. every non-ok ledger row in full (the M4 surface)'
SELECT s.label, ty.source, ty.group_key, ty.outcome, ty.reason, left(coalesce(ty.detail,''), 90) AS detail
  FROM v_served s
  JOIN timeline_request_tasks t ON t.timeline_request_id = s.id
  JOIN timeline_task_years ty ON ty.task_id = t.id
 WHERE ty.outcome <> 'ok'
 ORDER BY 1, 2, 3;

\echo '== 8. scene provenance and footprint presence for served rows'
SELECT l.label, ps.source, s.provenance, count(*) AS n,
       count(*) FILTER (WHERE s.footprint IS NULL) AS footprint_null
  FROM v_labels l
  JOIN parcel_scenes ps ON ps.parcel_id = l.parcel_id
  JOIN scenes s ON s.id = ps.scene_id
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo '== 9. NAIP capture dates (the pre/post-fire question)'
SELECT l.label, ps.group_key, s.item_id, s.capture_date, s.resolution_m,
       coalesce(array_length(ps.mosaic_scene_ids, 1), 0) AS extra_tiles
  FROM v_labels l
  JOIN parcel_scenes ps ON ps.parcel_id = l.parcel_id AND ps.source = 'naip'
  JOIN scenes s ON s.id = ps.scene_id
 ORDER BY 1, 2;

\echo '== 10. every request created during the sweep window (retry accounting)'
SELECT l.label, tr.id, tr.status, tr.origin, tr.sources, tr.created_at, tr.completed_at
  FROM v_labels l JOIN timeline_requests tr ON tr.parcel_id = l.parcel_id
 WHERE tr.created_at > timestamptz '2026-09-11 22:14:00+00'
 ORDER BY 1, tr.created_at;

\echo '== 11. fleet totals after the sweep'
SELECT
  (SELECT count(*) FROM parcels) AS parcels,
  (SELECT count(*) FROM parcel_scenes) AS parcel_scenes,
  (SELECT count(*) FROM scenes) AS scenes,
  (SELECT count(*) FROM census_snapshots) AS census_snapshots,
  (SELECT count(*) FROM property_events) AS property_events,
  (SELECT count(*) FROM timeline_task_years) AS ledger_rows;
