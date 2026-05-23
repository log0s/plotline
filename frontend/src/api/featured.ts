import type { FeaturedLocation } from "../types";
import { BASE_URL, apiFetch, handleResponse } from "./client";

export async function getFeaturedLocations(): Promise<FeaturedLocation[]> {
  const response = await apiFetch(`${BASE_URL}/featured`);
  const data = await handleResponse<{ locations: FeaturedLocation[] }>(
    response,
  );
  return data.locations;
}

export async function getFeaturedBySlug(
  slug: string,
): Promise<FeaturedLocation> {
  const response = await apiFetch(
    `${BASE_URL}/featured/${encodeURIComponent(slug)}`,
  );
  return handleResponse<FeaturedLocation>(response);
}
