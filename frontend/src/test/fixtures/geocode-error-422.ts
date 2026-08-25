/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: POST /api/v1/geocode
 * Request body:    {"address":"zzzz nonexistent street qqqq, nowhere, XX 00000"}
 * Status:          422
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 3c60133c003af66ee07fa536ffa8380fb0b30735
 * Method:          unmodified stack; a nonsense address the Census Geocoder
 *                  cannot match (geocode.py AddressNotFoundError branch).
 *
 * `message` is what api/client.ts's extractErrorDetail() lifts out of this
 * body and hands to ApiRequestError — the string the UI actually renders.
 */
export const geocodeError422 = {
  status: 422,
  body: {
    detail:
      "Could not match this address. Please check the spelling and include city and state.",
  },
  message:
    "Could not match this address. Please check the spelling and include city and state.",
} as const;
