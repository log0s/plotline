/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/featured
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: b4c3a2bd8b0fa1e620395d894fd7cfb641cefda9
 *
 * 6 locations, the full seeded set. No SAS tokens: preview_image_url
 * is a path served by our own API, not a signed blob URL.
 *
 * Every nullable field on FeaturedLocation (key_stat, description,
 * earliest_snapshot_id, latest_snapshot_id, preview_image_url) is non-null
 * on all 6 rows here, so this fixture pins the field names and types
 * but does not exercise the null branches.
 */
export const featuredList = {
  locations: [
    {
      id: "fbc3ebaa-ed66-4f80-bb7e-e95f082e4678",
      parcel_id: "70a496c7-3480-4752-b3ad-e0bdc59d8736",
      name: "Stapleton / Central Park",
      subtitle:
        "Denver's closed airport became the largest urban redevelopment in US history",
      slug: "stapleton-central-park",
      key_stat: "Former airport site, 4,700-acre master-planned community",
      description:
        "Denver's Stapleton International Airport closed in 1995 and was replaced by one of the most ambitious urban redevelopment projects in the country. NAIP imagery from 2003 shows demolition; by 2023, it's a dense neighborhood.",
      latitude: 39.78518536945,
      longitude: -104.891391524528,
      earliest_snapshot_id: "ea7337a5-c1d3-4803-9fbe-b5f064a30c31",
      latest_snapshot_id: "910f993e-7296-4b3a-b5b6-f9aedd996c8a",
      preview_image_url: "/static/featured/stapleton-central-park.jpg",
    },
    {
      id: "3565c2ae-eac2-4068-bbea-17c530e1ba85",
      parcel_id: "c78a1019-5cb5-4a07-9fcd-9b109bb05530",
      name: "RiNo Art District",
      subtitle:
        "An industrial corridor transformed into Denver's trendiest neighborhood",
      slug: "rino-art-district",
      key_stat: "Denver's fastest-appreciating neighborhood, 2014-2020",
      description:
        "River North was an industrial corridor of rail yards and warehouses. Starting around 2014, it transformed into Denver's trendiest neighborhood with art galleries, breweries, and new construction.",
      latitude: 39.762785604353,
      longitude: -104.983456008989,
      earliest_snapshot_id: "d2f3155a-d246-4a43-9c89-6b91706cef57",
      latest_snapshot_id: "213e1423-0fb3-46ed-a9db-e657663c89d8",
      preview_image_url: "/static/featured/rino-art-district.jpg",
    },
    {
      id: "70632db1-2e31-4884-bfed-adeb10e5df56",
      parcel_id: "c8ecf010-5096-41c4-86e2-00dccb62248c",
      name: "Green Valley Ranch",
      subtitle:
        "Open prairie east of Denver exploded into a planned community in 15 years",
      slug: "green-valley-ranch",
      key_stat: "Population grew thousands of percent since 2000",
      description:
        "The area east of Denver near E-470 was open prairie and farmland in the early 2000s. NAIP imagery shows the rapid development of subdivisions, schools, and commercial centers that now house tens of thousands.",
      latitude: 39.783839038444,
      longitude: -104.781622326767,
      earliest_snapshot_id: "1eff3efc-1f6b-4361-b981-bb42fc34ae5f",
      latest_snapshot_id: "9880c914-9595-43cf-af64-1993c2b026ea",
      preview_image_url: "/static/featured/green-valley-ranch.jpg",
    },
    {
      id: "c9ea816c-48e0-4e00-a4b5-db379de7ec12",
      parcel_id: "800643ba-a8d2-41c9-92e2-d72d6801eb8b",
      name: "Navy Yard / Capitol Riverfront",
      subtitle:
        "A Navy shipyard on the Anacostia became DC's fastest-growing neighborhood",
      slug: "navy-yard-capitol-riverfront",
      key_stat:
        "From Navy shipyard to one of DC's densest neighborhoods since 2008",
      description:
        "Washington's Capitol Riverfront south of the US Capitol was a Navy shipyard and industrial waterfront for two centuries. After Nationals Park opened in 2008, residential towers, offices, and mixed-use developments filled in along the Anacostia River, making it one of DC's fastest-growing neighborhoods.",
      latitude: 38.874832843351,
      longitude: -77.000502957426,
      earliest_snapshot_id: "39c0b3fc-3278-4f74-9fff-ae525190f278",
      latest_snapshot_id: "9efc1b64-eee5-44ee-a55e-bbeb23a7454f",
      preview_image_url: "/static/featured/navy-yard-capitol-riverfront.jpg",
    },
    {
      id: "a987be49-3ed1-4045-88e2-c50996e2ffb0",
      parcel_id: "14518754-4017-46d3-b950-bc764aea37ad",
      name: "Rodanthe, Outer Banks",
      subtitle:
        "Decades of coastal erosion reshaped the Outer Banks barrier islands",
      slug: "rodanthe-outer-banks",
      key_stat: "Shoreline retreated over 200 ft since 1984",
      description:
        "Rodanthe sits on one of the narrowest stretches of the Outer Banks. Comparing Landsat imagery from the 1980s to recent NAIP shows the shoreline migrating westward, houses lost to the surf, and NC-12 repeatedly relocated as the barrier island rolls over itself.",
      latitude: 35.584688434752,
      longitude: -75.464804480551,
      earliest_snapshot_id: "6e12a29b-1cab-418d-9615-b440d6f74d11",
      latest_snapshot_id: "3cda9007-7191-4f2b-a4eb-4e6baf7767e7",
      preview_image_url: "/static/featured/rodanthe-outer-banks.jpg",
    },
    {
      id: "6a5d0053-3dea-4255-ad1c-342d67cea8d5",
      parcel_id: "5c27245c-5827-430b-ad43-baae66e69335",
      name: "Hudson Yards",
      subtitle:
        "Open rail yards on Manhattan's West Side became a supertower megaproject",
      slug: "hudson-yards",
      key_stat: "$25B+ built on a deck over active Penn Station rail yards",
      description:
        "The Hudson Yards site on Manhattan's far west side spent decades as an open rail yard serving Penn Station. Landsat imagery from the 1990s shows bare tracks; by the 2010s, a platform deck was constructed over the active rails and a cluster of supertall towers rose above it in the largest private real-estate development in US history.",
      latitude: 40.753895530647,
      longitude: -73.999734922343,
      earliest_snapshot_id: "3b942549-aca3-4c0b-8554-86bc66e71b4a",
      latest_snapshot_id: "aac70486-9026-4512-b3fe-204bf4a77ffb",
      preview_image_url: "/static/featured/hudson-yards.jpg",
    },
  ],
} as const;
