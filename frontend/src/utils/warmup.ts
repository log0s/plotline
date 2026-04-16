/**
 * Fire-and-forget requests to wake up fly.io services that auto-stop when idle.
 * Called at module level in main.tsx so the machines are booting before the user
 * interacts with anything.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function warmupServices(): void {
  fetch(`${BASE_URL}/api/v1/health`).catch(() => {});
  fetch(`${BASE_URL}/api/v1/imagery/tiles/healthz`).catch(() => {});
}
