/**
 * REAL captured API payload — do not hand-edit.
 *
 * Source endpoint: GET /api/v1/timeline-requests/{id}
 * Parcel:          e032a469-d6c9-49d6-927e-e26779cea3a6 (request 7090d5ad-d252-44ea-8010-3ddfb32592e3, Adams County)
 * Captured:        2026-08-24 from the local dev stack (docker compose)
 * Backend git SHA: 31677c7f60dc25016e44ac2ebd3df786e407deab
 *
 * M11 counterpart: property status=complete with items_found=0 — the
 * 'genuinely no records' state that must render differently from failed.
 */
export const timelinePropertyCompleteZero = {
  id: "7090d5ad-d252-44ea-8010-3ddfb32592e3",
  parcel_id: "e032a469-d6c9-49d6-927e-e26779cea3a6",
  status: "complete",
  created_at: "2026-03-26T22:44:17.403309Z",
  completed_at: "2026-03-26T22:44:29.855570Z",
  error_message: null,
  tasks: [
    {
      source: "census",
      status: "complete",
      items_found: 9,
      started_at: "2026-03-26T22:44:20.357577Z",
      completed_at: "2026-03-26T22:44:29.554048Z",
      error_message: null,
    },
    {
      source: "landsat",
      status: "complete",
      items_found: 3,
      started_at: "2026-03-26T22:44:18.085458Z",
      completed_at: "2026-03-26T22:44:19.221722Z",
      error_message: null,
    },
    {
      source: "naip",
      status: "complete",
      items_found: 7,
      started_at: "2026-03-26T22:44:17.524730Z",
      completed_at: "2026-03-26T22:44:18.081442Z",
      error_message: null,
    },
    {
      source: "property",
      status: "complete",
      items_found: 0,
      started_at: "2026-03-26T22:44:29.557109Z",
      completed_at: "2026-03-26T22:44:29.851707Z",
      error_message: null,
    },
    {
      source: "sentinel2",
      status: "complete",
      items_found: 3,
      started_at: "2026-03-26T22:44:19.225600Z",
      completed_at: "2026-03-26T22:44:20.354716Z",
      error_message: null,
    },
  ],
} as const;
