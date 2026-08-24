/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/events
 * Parcel:          9a839723-94c5-406f-99c9-424af22a4885 (1201 16th St, Denver CO 80202)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Empty for the same reason as demographics-inflight: the property task
 * had not run yet. supported=true, so the panel reaches its empty branch.
 */
export const eventsInflight = {
  parcel_id: "9a839723-94c5-406f-99c9-424af22a4885",
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
