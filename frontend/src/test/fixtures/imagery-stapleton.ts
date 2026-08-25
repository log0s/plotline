/**
 * REAL captured API payload — SAS query strings redacted, see below.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/imagery
 * Parcel:          70a496c7-3480-4752-b3ad-e0bdc59d8736 (8340 Northfield Blvd, Denver CO 80238 — Stapleton/Central Park)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: b4c3a2bd8b0fa1e620395d894fd7cfb641cefda9
 *
 * 70 snapshots: 43 landsat, 7 naip, 13 sentinel2, 7 usgs_topo. Exercises every member of the
 * ImagerySource union in one payload.
 *
 * REDACTION — the ONLY hand-edit, applied mechanically:
 * 20 cog_url values carried live Azure SAS tokens (naip and
 * sentinel2 blobs are signed at response time; landsat and usgs_topo are
 * public and unsigned). Everything up to and including the "?" is verbatim;
 * the query string is replaced with the literal "<SAS-REDACTED>". Tokens
 * were read-only (sp=rl) delegated SAS for Planetary Computer's public
 * containers with a ~25h expiry, so nothing of value was removed — but a
 * signature parameter does not belong in git history. cog_url is `string`
 * on both sides, so the redaction cannot affect what this fixture measures.
 *
 * Note additional_cog_urls is null on all 70 snapshots: this parcel has no
 * multi-tile NAIP mosaic, so the mosaic branch of ImagerySnapshot is
 * declared here but not exercised.
 */
export const imageryStapleton = {
  parcel_id: "70a496c7-3480-4752-b3ad-e0bdc59d8736",
  snapshots: [
    {
      id: "ea7337a5-c1d3-4803-9fbe-b5f064a30c31",
      source: "usgs_topo",
      capture_date: "1890-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_East%20Denver_402931_1890_125000_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.5, -104.5, 40.0],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "604ea84ad34eb12031203797",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "98ef1972-3f58-4ffe-b1e9-6a38cf46002c",
      source: "usgs_topo",
      capture_date: "1938-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Derby_232799_1938_24000_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.75, -104.875, 39.875],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a37fae4b00f54eb3df529",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "497dafb9-2393-41b8-b645-92fe60545909",
      source: "usgs_topo",
      capture_date: "1940-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Derby_402536_1940_31680_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.75, -104.875, 39.875],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a502ee4b00f54eb4093a2",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "42b32000-67e6-48a2-a2c6-cc06ddab0367",
      source: "usgs_topo",
      capture_date: "1950-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Derby_232802_1950_24000_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.75, -104.875, 39.875],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a37fae4b00f54eb3df52e",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "ca44303d-1763-4e02-b98c-1b40e01c166e",
      source: "usgs_topo",
      capture_date: "1965-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Commerce%20City_232616_1965_24000_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.75, -104.875, 39.875],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a3797e4b00f54eb3ded3f",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "21bdba0e-03e5-44fe-b0d3-493e42b16c6c",
      source: "usgs_topo",
      capture_date: "1972-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Long%20Branch_233644_1972_24000_geo.tif",
      additional_cog_urls: null,
      bbox: [-104.875, 39.75, -104.75, 39.875],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a3ab7e4b00f54eb3e3c96",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "5a749b2c-ed99-4b48-9b3a-ed5ed69d1a8b",
      source: "usgs_topo",
      capture_date: "1981-01-01",
      cog_url:
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/CO/CO_Denver%20East_403027_1981_100000_geo.tif",
      additional_cog_urls: null,
      bbox: [-105.0, 39.5, -104.0, 40.0],
      thumbnail_url: null,
      resolution_m: null,
      cloud_cover_pct: null,
      stac_item_id: "5a8a2690e4b00f54eb3c25d3",
      stac_collection: "usgs-historical-topo",
    },
    {
      id: "c9a7604e-06c7-4099-91a4-d74c266193a3",
      source: "landsat",
      capture_date: "1984-06-22",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19840622_02_T1",
      additional_cog_urls: null,
      bbox: [-105.64036406, 39.35854492, -102.83151094, 41.29510508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19840622_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19840622_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "3adbec2b-edf7-4dfd-808f-71f4939eff73",
      source: "landsat",
      capture_date: "1985-10-15",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19851015_02_T1",
      additional_cog_urls: null,
      bbox: [-105.67263408, 39.36457492, -102.86722093, 41.29762508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19851015_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19851015_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "3b2cbd72-ea88-4e4a-951d-3f70185c7cde",
      source: "landsat",
      capture_date: "1986-08-15",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19860815_02_T1",
      additional_cog_urls: null,
      bbox: [-105.71207408, 39.36525492, -102.90651092, 41.30008508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19860815_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19860815_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "686aa7f7-23e2-4d93-945d-e254a4f19bd2",
      source: "landsat",
      capture_date: "1987-10-21",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19871021_02_T1",
      additional_cog_urls: null,
      bbox: [-105.56497401, 39.33816492, -102.74974099, 41.27928508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19871021_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19871021_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "26b1f042-f31d-4bc8-9a11-9e38a5ccf13c",
      source: "landsat",
      capture_date: "1988-10-23",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19881023_02_T1",
      additional_cog_urls: null,
      bbox: [-105.63672403, 39.34761492, -102.82453095, 41.28972508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19881023_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19881023_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "1e112fc9-1a60-4299-90c2-0240eb34cabd",
      source: "landsat",
      capture_date: "1989-10-10",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19891010_02_T1",
      additional_cog_urls: null,
      bbox: [-105.73005407, 39.36279492, -102.92066091, 41.30538508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19891010_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19891010_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "837e4934-a9d5-4ef8-8c27-a9e794550e4d",
      source: "landsat",
      capture_date: "1990-10-29",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19901029_02_T1",
      additional_cog_urls: null,
      bbox: [-105.70499407, 39.36236492, -102.8955109, 41.30823508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19901029_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19901029_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "6a664508-5fd7-441c-9bde-0ab93b95fe6f",
      source: "landsat",
      capture_date: "1991-10-16",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19911016_02_T1",
      additional_cog_urls: null,
      bbox: [-105.70132404, 39.35143492, -102.88861092, 41.30015508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19911016_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19911016_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "77a0cb29-f76e-4e98-be47-585b1ab555b8",
      source: "landsat",
      capture_date: "1992-12-21",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19921221_02_T1",
      additional_cog_urls: null,
      bbox: [-105.65830403, 39.34541492, -102.85290093, 41.29770508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19921221_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19921221_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "694273c4-8cbc-43f3-8551-ec1961ca7b3b",
      source: "landsat",
      capture_date: "1993-10-21",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19931021_02_T2",
      additional_cog_urls: null,
      bbox: [-105.64749401, 39.33951492, -102.82444095, 41.29236508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19931021_02_T2&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19931021_02_T2",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "ea7c9f96-c88c-4b00-8934-528dbbb054cb",
      source: "landsat",
      capture_date: "1994-09-06",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19940906_02_T1",
      additional_cog_urls: null,
      bbox: [-105.70502406, 39.35948492, -102.88468089, 41.31094508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19940906_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19940906_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "63179d8e-3402-4ee1-8d49-2ae8c587875e",
      source: "landsat",
      capture_date: "1995-11-03",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_034032_19951103_02_T1",
      additional_cog_urls: null,
      bbox: [-107.23823399, 39.33029496, -104.4000909, 41.31153504],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_034032_19951103_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_034032_19951103_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "04eb98ea-46fd-4459-ace6-943073bc68e3",
      source: "landsat",
      capture_date: "1996-08-17",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_034032_19960817_02_T1",
      additional_cog_urls: null,
      bbox: [-107.08699392, 39.30321495, -104.24272097, 41.28358505],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_034032_19960817_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_034032_19960817_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "f5b27646-dcb6-4e25-a2c7-302e490e8c82",
      source: "landsat",
      capture_date: "1997-10-16",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19971016_02_T1",
      additional_cog_urls: null,
      bbox: [-105.56500397, 39.31925492, -102.74965098, 41.28198508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19971016_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19971016_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "0ebbf170-ecd8-4834-b254-1b3d35371c8f",
      source: "landsat",
      capture_date: "1998-09-17",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19980917_02_T1",
      additional_cog_urls: null,
      bbox: [-105.62249401, 39.33642492, -102.80269093, 41.30060508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19980917_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19980917_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "6d846bf3-9a7e-4201-932b-d3bf1c799158",
      source: "landsat",
      capture_date: "1999-11-23",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_19991123_02_T1",
      additional_cog_urls: null,
      bbox: [-105.63348407, 39.36369492, -102.81620086, 41.32486508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_19991123_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_19991123_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "8dadaf6c-cd22-47e2-bd82-3d7254d23393",
      source: "landsat",
      capture_date: "2000-11-25",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20001125_02_T1",
      additional_cog_urls: null,
      bbox: [-105.672664, 39.33461492, -102.85281092, 41.30032508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20001125_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20001125_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "3c4692cf-0f16-478d-9c9a-4d42021b5196",
      source: "landsat",
      capture_date: "2001-11-28",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20011128_02_T1",
      additional_cog_urls: null,
      bbox: [-105.70505404, 39.34873492, -102.88818089, 41.31364508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20011128_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20011128_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "6e099d1a-5cac-49d0-b4f0-aa1036897bb1",
      source: "landsat",
      capture_date: "2002-10-21",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_034032_20021021_02_T1",
      additional_cog_urls: null,
      bbox: [-107.29203402, 39.34011496, -104.42516089, 41.31436504],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_034032_20021021_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 1.0,
      stac_item_id: "LT05_L2SP_034032_20021021_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "0b88c66e-13fa-4d71-ab02-f56faf6f2bcd",
      source: "landsat",
      capture_date: "2003-10-17",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20031017_02_T1",
      additional_cog_urls: null,
      bbox: [-105.65108403, 39.34465492, -102.81013095, 41.29234508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20031017_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20031017_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "5995cc89-5803-46b7-aa98-52e66a234ac7",
      source: "landsat",
      capture_date: "2004-09-17",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20040917_02_T1",
      additional_cog_urls: null,
      bbox: [-105.61881402, 39.34144492, -102.78158096, 41.28981508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20040917_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20040917_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "25b2520f-f0c3-49b8-bae2-fa8e55b93249",
      source: "landsat",
      capture_date: "2005-11-23",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20051123_02_T1",
      additional_cog_urls: null,
      bbox: [-105.59375403, 39.34375492, -102.76002095, 41.29265508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20051123_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20051123_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "6a418cb3-a1ae-4681-8778-b38c323db25f",
      source: "landsat",
      capture_date: "2006-12-03",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_034032_20061203_02_T1",
      additional_cog_urls: null,
      bbox: [-107.30654403, 39.34524496, -104.43945088, 41.31984504],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_034032_20061203_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_034032_20061203_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "ffa0a220-eeb2-417f-9ff7-38b6fa1b93a2",
      source: "landsat",
      capture_date: "2007-09-26",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20070926_02_T1",
      additional_cog_urls: null,
      bbox: [-105.67613402, 39.34208492, -102.81737095, 41.28949508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20070926_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20070926_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "19279af7-0c06-401a-9d22-3c7dfc38308f",
      source: "landsat",
      capture_date: "2008-10-30",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20081030_02_T1",
      additional_cog_urls: null,
      bbox: [-105.76943406, 39.36015492, -102.92433091, 41.30242508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20081030_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20081030_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "fc08819f-df2b-4643-bc94-1ccdb73c4561",
      source: "landsat",
      capture_date: "2009-11-18",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20091118_02_T1",
      additional_cog_urls: null,
      bbox: [-105.66894401, 39.33912492, -102.80315096, 41.28683508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20091118_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20091118_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "2f42257c-03c9-40be-9f1e-83f114f77882",
      source: "landsat",
      capture_date: "2010-11-05",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20101105_02_T1",
      additional_cog_urls: null,
      bbox: [-105.69407403, 39.34485492, -102.82086095, 41.29209508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20101105_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20101105_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "09550290-ea60-418f-82e0-f689e623dd4a",
      source: "naip",
      capture_date: "2011-07-23",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2011/co_100cm_2011/39104/m_3910409_se_13_1_20110723.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.941114, 39.747196, -104.871316, 39.815297],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_1_20110723_20110901&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_1_20110723_20110901",
      stac_collection: "naip",
    },
    {
      id: "88f593eb-7dd6-48cd-9077-1f151a7aa793",
      source: "landsat",
      capture_date: "2011-10-23",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LT05_L2SP_033032_20111023_02_T1",
      additional_cog_urls: null,
      bbox: [-105.68693403, 39.34736492, -102.81003094, 41.29483508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LT05_L2SP_033032_20111023_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LT05_L2SP_033032_20111023_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "8a0a7adb-9599-4c6a-a229-8b0f05209a78",
      source: "landsat",
      capture_date: "2012-10-08",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LE07_L2SP_034032_20121008_02_T1",
      additional_cog_urls: null,
      bbox: [-107.24907402, 39.34090496, -104.32122089, 41.31380504],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LE07_L2SP_034032_20121008_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LE07_L2SP_034032_20121008_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "525b68dd-12cb-4d0c-a0ad-88e3b8b8320e",
      source: "naip",
      capture_date: "2013-07-16",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2013/co_100cm_2013/39104/m_3910409_se_13_1_20130716.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.941067, 39.747232, -104.871363, 39.815261],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_1_20130716_20130917&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_1_20130716_20130917",
      stac_collection: "naip",
    },
    {
      id: "6f78a057-3046-40db-8aab-4e865afe75f8",
      source: "landsat",
      capture_date: "2013-09-26",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033032_20130926_02_T1",
      additional_cog_urls: null,
      bbox: [-105.5982038, 39.25331492, -102.83563069, 41.38720508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033032_20130926_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.01,
      stac_item_id: "LC08_L2SP_033032_20130926_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "84b3585d-f15f-4aa5-90b5-18e2c9cc6566",
      source: "landsat",
      capture_date: "2014-11-16",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033033_20141116_02_T1",
      additional_cog_urls: null,
      bbox: [-106.0350904, 37.82810489, -103.32707446, 39.95445511],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033033_20141116_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.06,
      stac_item_id: "LC08_L2SP_033033_20141116_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "58dccaf5-5075-4714-b636-978332534557",
      source: "sentinel2",
      capture_date: "2015-08-21",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2015/08/21/S2A_MSIL2A_20150821T180236_N0212_R141_T13TEE_20210412T001908.SAFE/GRANULE/L2A_T13TEE_A000853_20150821T180238/IMG_DATA/R10m/T13TEE_20150821T180236_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [
        -104.95142268372466, 39.65791787541492, -103.9949801564664,
        40.648649039388,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20150821T180236_R141_T13TEE_20210412T001908&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.104538,
      stac_item_id: "S2A_MSIL2A_20150821T180236_R141_T13TEE_20210412T001908",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "9cee050e-a9c2-4d6d-bfa1-072118e162ac",
      source: "naip",
      capture_date: "2015-09-10",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2015/co_100cm_2015/39104/m_3910409_se_13_1_20150910.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.941289, 39.747133, -104.871245, 39.815396],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_1_20150910_20151102&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_1_20150910_20151102",
      stac_collection: "naip",
    },
    {
      id: "8d596e32-142b-41ae-95ce-601071d506b8",
      source: "landsat",
      capture_date: "2015-11-03",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033032_20151103_02_T1",
      additional_cog_urls: null,
      bbox: [-105.6053838, 39.25344492, -102.84280069, 41.38717508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033032_20151103_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.04,
      stac_item_id: "LC08_L2SP_033032_20151103_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "4409d384-22d1-4882-87ae-16b00fba0180",
      source: "sentinel2",
      capture_date: "2015-12-16",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2015/12/16/S2A_MSIL2A_20151216T175252_N0300_R098_T13TEE_20210526T043020.SAFE/GRANULE/L2A_T13TEE_A002526_20151216T175254/IMG_DATA/R10m/T13TEE_20151216T175252_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.00023656, 39.65455731, -103.70165934, 40.65085652],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20151216T175252_R098_T13TEE_20210526T043020&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.001751,
      stac_item_id: "S2A_MSIL2A_20151216T175252_R098_T13TEE_20210526T043020",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "31f4d350-93bb-4e02-9854-549e006125da",
      source: "landsat",
      capture_date: "2016-10-20",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033033_20161020_02_T1",
      additional_cog_urls: null,
      bbox: [-106.0386004, 37.82814489, -103.33058446, 39.95442511],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033033_20161020_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.02,
      stac_item_id: "LC08_L2SP_033033_20161020_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "8a23136c-3963-4d9b-afb0-e16650d5ba58",
      source: "sentinel2",
      capture_date: "2016-11-10",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2016/11/10/S2A_MSIL2A_20161110T175252_N0212_R098_T13TEE_20210414T034820.SAFE/GRANULE/L2A_T13TEE_A007245_20161110T175253/IMG_DATA/R10m/T13TEE_20161110T175252_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [
        -105.00023438069769, 39.6545573069827, -103.71751759315202,
        40.01715582389984,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20161110T175252_R098_T13TEE_20210414T034820&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.088098,
      stac_item_id: "S2A_MSIL2A_20161110T175252_R098_T13TEE_20210414T034820",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "e66efd2a-60c0-424b-a153-6912b27be5a5",
      source: "naip",
      capture_date: "2017-09-02",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2017/co_100cm_2017/39104/m_3910409_se_13_1_20170902.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.941242, 39.747133, -104.871199, 39.815378],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_1_20170902_20171017&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_1_20170902_20171017",
      stac_collection: "naip",
    },
    {
      id: "ad6d1790-00f4-4ceb-9e77-bb5495d9a551",
      source: "landsat",
      capture_date: "2017-09-21",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033033_20170921_02_T1",
      additional_cog_urls: null,
      bbox: [-106.0245504, 37.82796489, -103.31653446, 39.95454511],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033033_20170921_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LC08_L2SP_033033_20170921_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "e3369c54-9a5b-4297-ab61-bec480700fb2",
      source: "sentinel2",
      capture_date: "2017-11-30",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2017/11/30/S2B_MSIL2A_20171130T174659_N0212_R098_T13TEE_20201014T231309.SAFE/GRANULE/L2A_T13TEE_A003842_20171130T174655/IMG_DATA/R10m/T13TEE_20171130T174659_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [
        -105.0002365638915, 39.6545573069827, -103.70165933840751,
        40.650856515774606,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2B_MSIL2A_20171130T174659_R098_T13TEE_20201014T231309&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.100305,
      stac_item_id: "S2B_MSIL2A_20171130T174659_R098_T13TEE_20201014T231309",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "119194ae-64de-4d32-8933-cd53a205b37b",
      source: "landsat",
      capture_date: "2018-09-15",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_034032_20180915_02_T1",
      additional_cog_urls: null,
      bbox: [-107.16591377, 39.24248495, -104.37418066, 41.39787505],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_034032_20180915_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.03,
      stac_item_id: "LC08_L2SP_034032_20180915_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "24f1d300-1a9e-4407-9e1a-066c3bc8193d",
      source: "sentinel2",
      capture_date: "2018-12-18",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2018/12/18/S2B_MSIL2A_20181218T175739_N0212_R141_T13TEE_20201008T111706.SAFE/GRANULE/L2A_T13TEE_A009319_20181218T175738/IMG_DATA/R10m/T13TEE_20181218T175739_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.000244, 39.6579798298449, -103.98859, 40.650856515774606],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2B_MSIL2A_20181218T175739_R141_T13TEE_20201008T111706&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.109537,
      stac_item_id: "S2B_MSIL2A_20181218T175739_R141_T13TEE_20201008T111706",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "fa3b8f57-20aa-4030-a109-b9acf54d8890",
      source: "naip",
      capture_date: "2019-08-03",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2019/co_60cm_2019/39104/m_3910409_se_13_060_20190803.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.939934, 39.748144, -104.872509, 39.814369],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_060_20190803_20191121&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_060_20190803_20191121",
      stac_collection: "naip",
    },
    {
      id: "b3b456b7-a400-46e4-b7e4-08d708d2a9d7",
      source: "landsat",
      capture_date: "2019-10-13",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033033_20191013_02_T1",
      additional_cog_urls: null,
      bbox: [-106.0315804, 37.82805489, -103.32356446, 39.95448511],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033033_20191013_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.04,
      stac_item_id: "LC08_L2SP_033033_20191013_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "f085dedb-5018-48f9-adfe-6a67a2d6b29a",
      source: "sentinel2",
      capture_date: "2019-11-18",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2019/11/18/S2A_MSIL2A_20191118T175631_N0212_R141_T13TEE_20201003T174115.SAFE/GRANULE/L2A_T13TEE_A023018_20191118T175629/IMG_DATA/R10m/T13TEE_20191118T175631_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.000244, 39.65805102591974, -104.00105, 40.650856515774606],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20191118T175631_R141_T13TEE_20201003T174115&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.090079,
      stac_item_id: "S2A_MSIL2A_20191118T175631_R141_T13TEE_20201003T174115",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "b655cd11-80cc-4c21-8188-efff975a609f",
      source: "landsat",
      capture_date: "2020-09-29",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033033_20200929_02_T1",
      additional_cog_urls: null,
      bbox: [-106.0315804, 37.82805489, -103.32356446, 39.95448511],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033033_20200929_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.01,
      stac_item_id: "LC08_L2SP_033033_20200929_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "11d6e27d-1290-41fb-acbe-cb7c197eafa0",
      source: "sentinel2",
      capture_date: "2020-11-27",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2020/11/27/S2B_MSIL2A_20201127T175709_N0212_R141_T13TEE_20201128T162535.SAFE/GRANULE/L2A_T13TEE_A019472_20201127T175823/IMG_DATA/R10m/T13TEE_20201127T175709_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [
        -105.0002365638915, 39.65801382178425, -103.99556772969079,
        40.650856515774606,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2B_MSIL2A_20201127T175709_R141_T13TEE_20201128T162535&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.618522,
      stac_item_id: "S2B_MSIL2A_20201127T175709_R141_T13TEE_20201128T162535",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "ae9dbf82-a858-4e21-b9e4-aa2581ef2cd8",
      source: "naip",
      capture_date: "2021-07-28",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2021/co_060cm_2021/39104/09/m_3910409_se_13_060_20210728.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.939934, 39.748144, -104.872509, 39.814369],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_060_20210728&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_060_20210728",
      stac_collection: "naip",
    },
    {
      id: "d395de29-1f9e-44dd-af0b-3340b0cb476f",
      source: "landsat",
      capture_date: "2021-11-07",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_L2SP_033033_20211107_02_T1",
      additional_cog_urls: null,
      bbox: [-105.6698504, 37.82854488, -102.99012447, 39.95714512],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC09_L2SP_033033_20211107_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.1,
      stac_item_id: "LC09_L2SP_033033_20211107_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "49087f18-9f25-4aa0-aa4e-ac72ff19d1da",
      source: "sentinel2",
      capture_date: "2021-12-02",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2021/12/02/S2B_MSIL2A_20211202T175719_N0300_R141_T13TEE_20211203T065332.SAFE/GRANULE/L2A_T13TEE_A024763_20211202T180003/IMG_DATA/R10m/T13TEE_20211202T175719_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.000244, 39.65802413, -103.99594, 40.65085652],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2B_MSIL2A_20211202T175719_R141_T13TEE_20211203T065332&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.179785,
      stac_item_id: "S2B_MSIL2A_20211202T175719_R141_T13TEE_20211203T065332",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "d47b6636-6c81-42d7-9e87-86d1ee8da611",
      source: "sentinel2",
      capture_date: "2022-11-22",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/DE/2022/11/22/S2A_MSIL2A_20221122T175641_N0400_R141_T13TDE_20221123T050707.SAFE/GRANULE/L2A_T13TDE_A038748_20221122T175828/IMG_DATA/R10m/T13TDE_20221122T175641_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-106.18317, 39.6557526, -104.88455, 40.6507988],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20221122T175641_R141_T13TDE_20221123T050707&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.015899,
      stac_item_id: "S2A_MSIL2A_20221122T175641_R141_T13TDE_20221123T050707",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "f7641778-5627-4ef9-a5f5-7f530550ccc6",
      source: "landsat",
      capture_date: "2022-11-30",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_L2SP_033032_20221130_02_T1",
      additional_cog_urls: null,
      bbox: [-105.60894381, 39.25620492, -102.84648069, 41.38445508],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC09_L2SP_033032_20221130_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.05,
      stac_item_id: "LC09_L2SP_033032_20221130_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "d5ae0ebe-a860-4e8f-aa9f-ec036e97fbb2",
      source: "naip",
      capture_date: "2023-09-25",
      cog_url:
        "https://naipeuwest.blob.core.windows.net/naip/v002/co/2023/co_030cm_2023/39104/m_3910409_se_13_030_20230925_20240104.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-104.941059, 39.747242, -104.871375, 39.815256],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=naip&item=co_m_3910409_se_13_030_20230925_20240104&assets=image&asset_bidx=image%7C1%2C2%2C3&format=png&max_size=128",
      resolution_m: 1.0,
      cloud_cover_pct: null,
      stac_item_id: "co_m_3910409_se_13_030_20230925_20240104",
      stac_collection: "naip",
    },
    {
      id: "e6773a67-b16f-4676-8b39-21d038debd73",
      source: "landsat",
      capture_date: "2023-10-16",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_L2SP_033033_20231016_02_T1",
      additional_cog_urls: null,
      bbox: [
        -106.06669040220638, 37.83117489028675, -103.35515446380039,
        39.95416510971325,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC09_L2SP_033033_20231016_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.01,
      stac_item_id: "LC09_L2SP_033033_20231016_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "7a00e4c3-3094-4bed-a613-235a68dcb284",
      source: "sentinel2",
      capture_date: "2023-12-17",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/DE/2023/12/17/S2A_MSIL2A_20231217T175741_N0510_R141_T13TDE_20231220T075806.SAFE/GRANULE/L2A_T13TDE_A044325_20231217T175740/IMG_DATA/R10m/T13TDE_20231217T175741_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-106.1831726, 39.6557526, -104.8845569, 40.6507988],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2A_MSIL2A_20231217T175741_R141_T13TDE_20231220T075806&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.002362,
      stac_item_id: "S2A_MSIL2A_20231217T175741_R141_T13TDE_20231220T075806",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "c866f191-6f69-4ced-94e3-0c3f7b2255c3",
      source: "landsat",
      capture_date: "2024-10-02",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_L2SP_033033_20241002_02_T1",
      additional_cog_urls: null,
      bbox: [
        -106.04562040201917, 37.83094488993814, -103.33760446401124,
        39.954365110061865,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC09_L2SP_033033_20241002_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.0,
      stac_item_id: "LC09_L2SP_033033_20241002_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "17cf1351-8648-4baa-ae27-094eba6ce166",
      source: "sentinel2",
      capture_date: "2024-12-06",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2024/12/06/S2B_MSIL2A_20241206T175639_N0511_R141_T13TEE_20241206T211053.SAFE/GRANULE/L2A_T13TEE_A040493_20241206T180051/IMG_DATA/R10m/T13TEE_20241206T175639_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.0002366, 39.6580283, -103.9970918, 40.6508565],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2B_MSIL2A_20241206T175639_R141_T13TEE_20241206T211053&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.00252,
      stac_item_id: "S2B_MSIL2A_20241206T175639_R141_T13TEE_20241206T211053",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "d62efd23-fbd7-4e77-b584-4d336f6437d6",
      source: "landsat",
      capture_date: "2025-09-27",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC08_L2SP_033032_20250927_02_T1",
      additional_cog_urls: null,
      bbox: [
        -105.6161438012832, 39.253564917906395, -102.84997068722838,
        41.38711508209361,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC08_L2SP_033032_20250927_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.04,
      stac_item_id: "LC08_L2SP_033032_20250927_02_T1",
      stac_collection: "landsat-c2-l2",
    },
    {
      id: "7333303c-0b4b-4cf7-9e50-dcde8e4be4a4",
      source: "sentinel2",
      capture_date: "2025-11-13",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2025/11/13/S2C_MSIL2A_20251113T174611_N0511_R098_T13TEE_20251113T204309.SAFE/GRANULE/L2A_T13TEE_A006217_20251113T174800/IMG_DATA/R10m/T13TEE_20251113T174611_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.0002366, 39.6545573, -103.7016593, 40.6508565],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2C_MSIL2A_20251113T174611_R098_T13TEE_20251113T204309&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.00069,
      stac_item_id: "S2C_MSIL2A_20251113T174611_R098_T13TEE_20251113T204309",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "473ec009-e337-43fc-8b55-c3ebaca57612",
      source: "sentinel2",
      capture_date: "2026-07-11",
      cog_url:
        "https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/13/T/EE/2026/07/11/S2C_MSIL2A_20260711T173901_N0512_R098_T13TEE_20260711T223155.SAFE/GRANULE/L2A_T13TEE_A009649_20260711T174522/IMG_DATA/R10m/T13TEE_20260711T173901_TCI_10m.tif?<SAS-REDACTED>",
      additional_cog_urls: null,
      bbox: [-105.0002366, 39.6545573, -103.7016593, 40.6508565],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=sentinel-2-l2a&item=S2C_MSIL2A_20260711T173901_R098_T13TEE_20260711T223155&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png&max_size=128",
      resolution_m: 10.0,
      cloud_cover_pct: 0.000206,
      stac_item_id: "S2C_MSIL2A_20260711T173901_R098_T13TEE_20260711T223155",
      stac_collection: "sentinel-2-l2a",
    },
    {
      id: "910f993e-7296-4b3a-b5b6-f9aedd996c8a",
      source: "landsat",
      capture_date: "2026-07-20",
      cog_url:
        "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2/items/LC09_L2SP_033032_20260720_02_T1",
      additional_cog_urls: null,
      bbox: [
        -105.62332380159364, 39.25375491798286, -102.86073068686449,
        41.38707508201714,
      ],
      thumbnail_url:
        "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png?collection=landsat-c2-l2&item=LC09_L2SP_033032_20260720_02_T1&assets=red&assets=green&assets=blue&color_formula=gamma+RGB+2.7%2C+saturation+1.5%2C+sigmoidal+RGB+15+0.55&format=png&max_size=128",
      resolution_m: 30.0,
      cloud_cover_pct: 0.12,
      stac_item_id: "LC09_L2SP_033032_20260720_02_T1",
      stac_collection: "landsat-c2-l2",
    },
  ],
} as const;
