-- Featured-location copy fix: NAIP year claims (2026-08-13)
--
-- Why: the Stapleton and Green Valley Ranch blurbs claimed "NAIP imagery from
-- 2003". The Planetary Computer NAIP collection starts 2010-01-01 (STATUS.md
-- T5), and both parcels' actual NAIP coverage locally is 2011-2023 biennial.
-- README.md and scripts/seed_featured.py now carry corrected wording; the rows
-- already in production keep the old text until this runs.
--
-- Run order: STEP 1 (read-only) first and confirm the coverage matches the
-- years asserted in STEP 2's text. If production's parcels for these slugs
-- have different NAIP years than 2011-2023, STOP and adjust the wording --
-- the years below were verified against the LOCAL database only.
--
-- Not run from here. Owner-executed.

-- ---------------------------------------------------------------------------
-- STEP 1 -- read-only: current descriptions + the coverage they must match.
-- ---------------------------------------------------------------------------

SELECT slug, name, description
FROM featured_locations
WHERE slug IN ('stapleton-central-park', 'green-valley-ranch')
ORDER BY display_order;

SELECT f.slug,
       i.source,
       min(extract(year FROM i.capture_date))::int AS first_year,
       max(extract(year FROM i.capture_date))::int AS last_year,
       count(*)                                    AS rows
FROM featured_locations f
JOIN imagery_snapshots i ON i.parcel_id = f.parcel_id
WHERE f.slug IN ('stapleton-central-park', 'green-valley-ranch')
GROUP BY 1, 2
ORDER BY 1, 2;

-- ---------------------------------------------------------------------------
-- STEP 2 -- apply the corrected copy. Keyed on slug (UNIQUE on
-- featured_locations; see app/models/parcels.py). Wrapped so both rows move
-- together or neither does.
-- ---------------------------------------------------------------------------

BEGIN;

UPDATE featured_locations
SET description = 'Denver''s Stapleton International Airport closed in 1995 and was replaced by one of the most ambitious urban redevelopment projects in the country. Annual Landsat imagery starts in 1984, a decade before the airport closed; NAIP aerials cover 2011–2023 across the 4,700-acre site, and USGS topo sheets reach back to 1890.'
WHERE slug = 'stapleton-central-park';

UPDATE featured_locations
SET description = 'The area east of Denver near E-470 was open prairie and farmland in the early 2000s. Annual Landsat imagery reaches back to 1984 and NAIP aerials cover 2011–2023, alongside four decades of Census data on the population growth.'
WHERE slug = 'green-valley-ranch';

-- Expect: UPDATE 1, UPDATE 1. Anything else means the slug set drifted --
-- ROLLBACK and investigate before committing.

COMMIT;
