import { afterEach, beforeEach, expect, test, vi } from "vitest";

type Images = typeof import("../src/images");

let images: Images;
let made = 0;

beforeEach(async () => {
  // The cache is page-wide; each test gets a fresh page.
  vi.resetModules();
  images = await import("../src/images");
  made = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:image-${++made}`);
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** A fake `hass` whose `fetchWithAuth` answers each path with the status `respond` gives. */
function fakeHass(respond: (path: string) => number | Error = () => 200) {
  const fetchWithAuth = vi.fn(async (path: string) => {
    const status = respond(path);
    if (status instanceof Error) throw status;
    return new Response(status === 200 ? new Blob(["GIF89a"]) : null, { status });
  });
  return { hass: { fetchWithAuth }, fetchWithAuth };
}

test("images cached per exercise and kind; 404 gives null", async () => {
  const { hass, fetchWithAuth } = fakeHass((path) => (path.includes("custom-7") ? 404 : 200));

  const [first, again] = await Promise.all([
    images.imageUrl(hass, "0001", "gif"),
    images.imageUrl(hass, "0001", "gif"),
  ]);
  expect(first).toBe("blob:image-1");
  expect(again).toBe(first);
  expect(await images.imageUrl(hass, "0001", "gif")).toBe(first);
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
  expect(fetchWithAuth).toHaveBeenCalledWith("/api/ha_fitness/media/0001/gif");

  expect(await images.imageUrl(hass, "0001", "thumbnail")).toBe("blob:image-2");
  expect(await images.imageUrl(hass, "0002", "gif")).toBe("blob:image-3");
  expect(fetchWithAuth).toHaveBeenCalledWith("/api/ha_fitness/media/0001/thumbnail");
  expect(fetchWithAuth).toHaveBeenCalledWith("/api/ha_fitness/media/0002/gif");

  expect(await images.imageUrl(hass, "custom-7", "gif")).toBeNull();
  expect(await images.imageUrl(hass, "custom-7", "gif")).toBeNull();
  // A missing image stays missing for the page.
  expect(fetchWithAuth).toHaveBeenCalledTimes(4);
});

test("an unreachable add-on gives null and the next call tries again", async () => {
  let answer: number | Error = 503;
  const { hass, fetchWithAuth } = fakeHass(() => answer);

  expect(await images.imageUrl(hass, "0001", "gif")).toBeNull();
  answer = new TypeError("Failed to fetch");
  expect(await images.imageUrl(hass, "0001", "gif")).toBeNull();
  answer = 200;
  expect(await images.imageUrl(hass, "0001", "gif")).toBe("blob:image-1");

  expect(fetchWithAuth).toHaveBeenCalledTimes(3);
});
