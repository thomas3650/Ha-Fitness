/** The two images an exercise has in the media proxy (spec §4). */
export type ImageKind = "gif" | "thumbnail";

/** The part of Home Assistant's `hass` object the images use. */
export interface ImageHass {
  fetchWithAuth(path: string, init?: RequestInit): Promise<Response>;
}

// One object URL per exercise and kind for the page (spec §5.2). It holds the promise, so calls
// that overlap fetch once.
const cache = new Map<string, Promise<string | null>>();

/**
 * The object URL of an exercise's image, fetched through the integration's media proxy with
 * `hass.fetchWithAuth`. A missing image (404) gives null and stays missing for the page; any other
 * failure gives null and the next call tries again.
 */
export function imageUrl(hass: ImageHass, exerciseId: string, kind: ImageKind): Promise<string | null> {
  const key = `${exerciseId}/${kind}`;
  let url = cache.get(key);
  if (!url) {
    url = load(hass, exerciseId, kind).catch(() => {
      cache.delete(key);
      return null;
    });
    cache.set(key, url);
  }
  return url;
}

async function load(hass: ImageHass, exerciseId: string, kind: ImageKind): Promise<string | null> {
  const response = await hass.fetchWithAuth(
    `/api/ha_fitness/media/${encodeURIComponent(exerciseId)}/${kind}`,
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`media ${response.status}`);
  return URL.createObjectURL(await response.blob());
}
