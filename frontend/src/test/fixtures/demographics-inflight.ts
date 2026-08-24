/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/demographics
 * Parcel:          9a839723-94c5-406f-99c9-424af22a4885 (1201 16th St, Denver CO 80202)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Empty because the census task had not run yet — NOT because the tract
 * has no data. See timeline-inflight.ts for the task states at this instant.
 */
export const demographicsInflight = {
  parcel_id: "9a839723-94c5-406f-99c9-424af22a4885",
  tract_fips: "08031001704",
  snapshots: [],
  subtitles: [],
  notes:
    "Census tract boundaries may differ across decades. Data shown is for the tract containing this address in each respective year's geography. Dollar values are nominal (not inflation-adjusted).",
} as const;
