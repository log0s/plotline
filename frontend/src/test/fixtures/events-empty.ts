/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/events
 * Parcel:          45a84ee8-342d-4fe0-b029-f0b2b93db4d8 (1600 Glenarm Pl, Denver CO 80202)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Zero events, supported=true — so the panel's empty branch is reached
 * rather than the unsupported-county banner.
 */
export const eventsEmpty = {
  parcel_id: "45a84ee8-342d-4fe0-b029-f0b2b93db4d8",
  county: "Denver",
  supported: true,
  supported_counties: [
    "Denver County, CO",
    "Adams County, CO",
    "Washington, DC",
    "Santa Clara County, CA",
    "New York County, NY",
  ],
  events: [],
  summary: {
    total_events: 0,
    total_sales: 0,
    total_permits: 0,
    price_history: [],
    appreciation: null,
  },
} as const;
