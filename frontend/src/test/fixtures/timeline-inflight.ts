/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/timeline-requests/{id}
 * Parcel:          9a839723-94c5-406f-99c9-424af22a4885 (1201 16th St, Denver CO 80202)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * Request status=processing with every task still queued. Captured in the
 * same instant as demographics-inflight and events-inflight, so the three
 * together are one real moment rather than a splice.
 */
export const timelineInflight = {
  id: "6744e17b-8383-4b60-a950-9d1dbbb5135e",
  parcel_id: "9a839723-94c5-406f-99c9-424af22a4885",
  status: "processing",
  created_at: "2026-08-24T22:46:07.013593Z",
  completed_at: null,
  error_message: null,
  tasks: [
    {
      source: "census",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
    {
      source: "landsat",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
    {
      source: "naip",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
    {
      source: "property",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
    {
      source: "sentinel2",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
    {
      source: "usgs_topo",
      status: "queued",
      items_found: 0,
      started_at: null,
      completed_at: null,
      error_message: null,
    },
  ],
} as const;
