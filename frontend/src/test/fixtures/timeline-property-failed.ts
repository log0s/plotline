/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/timeline-requests/{id}
 * Parcel:          70a496c7-3480-4752-b3ad-e0bdc59d8736 (request 377e9f11-efb0-416b-94f3-7ce1ea11e125)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * M11 evidence: a genuine Denver portal outage recorded as property
 * status=failed with the error message 256ed32 introduced. Note the task
 * started_at/completed_at predate that commit — see the report.
 */
export const timelinePropertyFailed = {
  id: "377e9f11-efb0-416b-94f3-7ce1ea11e125",
  parcel_id: "70a496c7-3480-4752-b3ad-e0bdc59d8736",
  status: "complete",
  created_at: "2026-03-26T22:29:42.061715Z",
  completed_at: "2026-03-26T22:30:00.079531Z",
  error_message: null,
  tasks: [
    {
      source: "census",
      status: "complete",
      items_found: 3,
      started_at: "2026-03-26T22:29:48.862970Z",
      completed_at: "2026-03-26T22:29:59.599783Z",
      error_message: null,
    },
    {
      source: "landsat",
      status: "complete",
      items_found: 2,
      started_at: "2026-03-26T22:29:46.963695Z",
      completed_at: "2026-03-26T22:29:47.837219Z",
      error_message: null,
    },
    {
      source: "naip",
      status: "complete",
      items_found: 7,
      started_at: "2026-03-26T22:29:46.227120Z",
      completed_at: "2026-03-26T22:29:46.960347Z",
      error_message: null,
    },
    {
      source: "property",
      status: "failed",
      items_found: 0,
      started_at: "2026-03-26T22:29:59.612078Z",
      completed_at: "2026-03-26T22:30:00.076421Z",
      error_message: "All Denver County property queries failed",
    },
    {
      source: "sentinel2",
      status: "complete",
      items_found: 3,
      started_at: "2026-03-26T22:29:47.840892Z",
      completed_at: "2026-03-26T22:29:48.859956Z",
      error_message: null,
    },
  ],
} as const;
