import { findByRole, findByText, getAllByRole, getByRole, getByText, queryByText, within } from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/main";
import { brokenAt, fakeApi, program } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
});

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function people() {
  return {
    people: [
      { id: 1, name: "Thomas", person_entity_id: "person.thomas" },
      { id: 2, name: "Elin", person_entity_id: "person.elin" },
    ],
    ha_persons: null,
    ha_error: "Home Assistant can't be reached",
  };
}

test("the Status page shows the version, the library and the media state", async () => {
  const fake = fakeApi({
    health: { status: "ok", version: "2.1.0", api_version: 1 },
    library: { exercises: { library: 1324, custom: 3 }, media: { state: "downloading", present: 200, total: 1324 } },
  });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/status");

  expect(await findByText(root, "Version 2.1.0")).toBeTruthy();
  expect(getByText(root, "Exercises: 1,324 from the library, 3 custom")).toBeTruthy();
  expect(getByText(root, "Media: 200/1,324, downloading")).toBeTruthy();
  const paths = fake.requests.map((request) => `${request.method} ${request.path}`);
  expect(paths).toEqual(expect.arrayContaining(["GET api/v1/health", "GET api/v1/library"]));
});

test("the Status page lists the people and the programs", async () => {
  const fake = fakeApi({
    people: people(),
    programs: [
      program(1, { name: "Core", active: true, weekdays: ["mon", "thu"] }, { total_seconds: 840 }),
      program(2, { name: "Legs", active: false, weekdays: [] }, { total_seconds: 1050 }),
    ],
  });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/status");

  const peopleList = await findByRole(root, "list", { name: en.status.people });
  expect(within(peopleList).getAllByRole("listitem").map(text)).toEqual(["Thomas", "Elin"]);

  const table = getByRole(root, "table", { name: en.status.programs });
  const rows = within(table).getAllByRole("row").slice(1).map((row) => within(row).getAllByRole("cell").map(text));
  expect(rows).toEqual([
    ["Core", "On", "Mon, Thu", "14 min"],
    ["Legs", "Off", "None", "18 min"],
  ]);
});

test("the Status page says when there are no people and no programs", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("#/status");

  expect(await findByText(root, en.status.no_people)).toBeTruthy();
  expect(getByText(root, en.status.no_programs)).toBeTruthy();
});

test("the Status page links the library's JSON and the health check, relative to the panel", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("#/status");

  const library = await findByRole(root, "link", { name: en.status.library_json });
  expect(library.getAttribute("href")).toBe("api/v1/library");
  expect(getByRole(root, "link", { name: en.status.health }).getAttribute("href")).toBe("api/v1/health");
});

test("a refused read shows the add-on's message", async () => {
  const fake = fakeApi();
  fake.answer("GET", "api/v1/library", 503, { detail: "The library isn't loaded", code: "unavailable", field: null });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/status");

  const alert = await findByRole(root, "alert");
  expect(text(alert)).toContain("The library isn't loaded");
  expect(getAllByRole(root, "heading", { level: 1 }).map(text)).toEqual([en.status.title]);
});

test("one refused read leaves the other sections in place", async () => {
  const fake = fakeApi({ people: people(), health: { status: "ok", version: "2.1.0", api_version: 1 } });
  fake.answer("GET", "api/v1/library", 503, { detail: "The library isn't loaded", code: "unavailable", field: null });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/status");

  expect(text(await findByRole(root, "alert"))).toContain("The library isn't loaded");
  expect(getByText(root, "Version 2.1.0")).toBeTruthy();
  const peopleList = getByRole(root, "list", { name: en.status.people });
  expect(within(peopleList).getAllByRole("listitem").map(text)).toEqual(["Thomas", "Elin"]);
  expect(getByText(root, en.status.no_programs)).toBeTruthy();
  expect(queryByText(root, en.status.loading)).toBeNull();
});

test("when the add-on can't be reached, the page says so instead of loading forever", async () => {
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
  const root = await mount("#/status");

  const alert = await findByRole(root, "alert");
  expect(text(alert)).toContain(en.error.network);
  expect(queryByText(root, en.status.loading)).toBeNull();
});

test("the Status page shows “< 1 min” for a program under half a minute", async () => {
  const fake = fakeApi({
    programs: [
      program(1, { name: "Short" }, { total_seconds: 20 }),
      program(2, { name: "Half" }, { total_seconds: 30 }),
      program(3, { name: "Empty", stations: [] }, { total_seconds: 0 }),
    ],
  });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/status");

  const table = await findByRole(root, "table", { name: en.status.programs });
  const lengths = within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => text(within(row).getAllByRole("cell")[3]));
  expect(lengths).toEqual(["< 1 min", "1 min", "0 min"]);
});

test("a read that fails with a bug shows the generic message on the Status page and logs the bug", async () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", brokenAt(fakeApi(), "api/v1/programs"));
  const root = await mount("#/status");

  expect(await findByText(root, en.error.unexpected)).toBeTruthy();
  expect(logged).toHaveBeenCalledWith(expect.any(TypeError));
  logged.mockRestore();
});
