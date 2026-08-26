import type { TimelineRequest } from "../types";

type Status = TimelineRequest["status"] | undefined;

/**
 * The run finished and there is a timeline to show.
 *
 * "partial" means every source finished, at least one failed and at least one
 * did not — a Crawford County parcel serving Landsat and topo while NAIP and
 * Sentinel-2 both timed out. The timeline renders; it just has a hole in it.
 * Every place that used to ask `status === "complete"` before enabling a
 * dependent query or unblocking a refetch means this, not "complete".
 */
export function isTimelineDelivered(status: Status): boolean {
  return status === "complete" || status === "partial";
}

/** The run reached a terminal state — nothing more will change. */
export function isTimelineTerminal(status: Status): boolean {
  return isTimelineDelivered(status) || status === "failed";
}
