import { warmupSnapshot } from "../api/imagery";

// Long enough that scrubbing past a snapshot doesn't warm it, short enough
// that the warmup still lands before the first tiles finish requesting.
const WARMUP_DELAY_MS = 250;

const warmed = new Set<string>();

/**
 * Warm a snapshot's COG once the selection has settled on it.
 *
 * Scrubbing the timeline changes the selection several times a second. Firing
 * a warmup per hop spends the endpoint's per-IP budget on snapshots the user
 * passed through, and the one they stop on — the only one that matters — is
 * the call that gets rate limited. Delaying the call and remembering what has
 * already been warmed keeps a session to roughly one warmup per snapshot the
 * user actually views.
 *
 * Returns a cancel function; call it when the selection moves on.
 */
export function scheduleWarmup(snapshotId: string): () => void {
  if (warmed.has(snapshotId)) return () => {};

  const timer = window.setTimeout(() => {
    warmed.add(snapshotId);
    void warmupSnapshot(snapshotId).then((ok) => {
      // Refused or failed — forget it so a later selection can retry.
      if (!ok) warmed.delete(snapshotId);
    });
  }, WARMUP_DELAY_MS);

  return () => window.clearTimeout(timer);
}
