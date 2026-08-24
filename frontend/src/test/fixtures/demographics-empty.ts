/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/parcels/{id}/demographics
 * Parcel:          45a84ee8-342d-4fe0-b029-f0b2b93db4d8 (1600 Glenarm Pl, Denver CO 80202)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Captured immediately after geocode, before the census task landed, so
 * snapshots is genuinely empty as the endpoint returns it. Pairs with
 * events-empty to exercise the DemographicsPanel empty branch.
 */
export const demographicsEmpty = {
  parcel_id: "45a84ee8-342d-4fe0-b029-f0b2b93db4d8",
  tract_fips: "08031001706",
  snapshots: [],
  subtitles: [],
  notes:
    "Census tract boundaries may differ across decades. Data shown is for the tract containing this address in each respective year's geography. Dollar values are nominal (not inflation-adjusted).",
} as const;
