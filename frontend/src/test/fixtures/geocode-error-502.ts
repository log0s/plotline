/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: POST /api/v1/geocode
 * Request body:    {"address":"8340 Northfield Blvd, Denver, CO 80238"}
 * Status:          502
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 3c60133c003af66ee07fa536ffa8380fb0b30735
 * Method:          the API container restarted with a compose override setting
 *                  CENSUS_GEOCODER_URL=http://127.0.0.1:9/... (a closed port),
 *                  so httpx raises ConnectError and geocoder.py maps it to
 *                  GeocoderUnavailableError -> 502. Note this is the *Census*
 *                  geocoder, not Photon: Photon backs autocomplete only and
 *                  returns [] on failure, never a 502.
 *
 * `message` is what api/client.ts's extractErrorDetail() lifts out of this
 * body and hands to ApiRequestError — the string the UI actually renders.
 */
export const geocodeError502 = {
  status: 502,
  body: {
    detail:
      "The Census Geocoder API is currently unavailable. Please try again later.",
  },
  message:
    "The Census Geocoder API is currently unavailable. Please try again later.",
} as const;
