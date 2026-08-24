/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: POST /api/v1/geocode
 * Parcel:          70a496c7-3480-4752-b3ad-e0bdc59d8736 (8340 Northfield Blvd, Denver CO 80238)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * The parcel prop ParcelInfo receives on the Explore page.
 */
export const geocodeStapleton = {
  parcel_id: "70a496c7-3480-4752-b3ad-e0bdc59d8736",
  address: "8340 Northfield Blvd, Denver, CO 80238",
  normalized_address: "8340 NORTHFIELD BLVD, DENVER, CO, 80238",
  latitude: 39.78518536945,
  longitude: -104.891391524528,
  census_tract: "08031004111",
  is_new: false,
  timeline_request_id: "39ba6213-71c1-4532-92b9-d72ccf2390cc",
} as const;
