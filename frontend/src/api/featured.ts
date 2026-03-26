/**
 * API client for featured locations.
 */
import type { FeaturedLocation } from "../types";

const BASE_URL = `${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1`;

export async function getFeaturedLocations(): Promise<FeaturedLocation[]> {
  const response = await fetch(`${BASE_URL}/featured`);
  if (!response.ok) return [];
  const data = (await response.json()) as { locations: FeaturedLocation[] };
  return data.locations;
}

export async function getFeaturedBySlug(
  slug: string,
): Promise<FeaturedLocation | null> {
  const response = await fetch(`${BASE_URL}/featured/${encodeURIComponent(slug)}`);
  if (!response.ok) return null;
  return response.json() as Promise<FeaturedLocation>;
}
