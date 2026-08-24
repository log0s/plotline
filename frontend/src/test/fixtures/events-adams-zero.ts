/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/events
 * Parcel:          e032a469-d6c9-49d6-927e-e26779cea3a6 (Adams County, CO)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Zero events with supported=true — the authoritative 'no records here'
 * answer, not an outage. The parcel's property task completed at 0 items;
 * see timeline-property-complete-zero.ts for that same run's task rows.
 */
export const eventsAdamsZero = {
  parcel_id: "e032a469-d6c9-49d6-927e-e26779cea3a6",
  county: "Adams",
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
