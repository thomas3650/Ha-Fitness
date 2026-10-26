import {
  findByRole,
  fireEvent,
  getAllByRole,
  getByRole,
  queryByRole,
  within,
} from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/main";
import { fakeApi, program, type FakeApi } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
});

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

const SESSION_RUNNING = { detail: "A session for this program is running", code: "session_running", field: null };

function programs() {
  return [
    program(
      1,
      {
        name: "Full body",
        active: true,
        weekdays: ["mon", "wed", "fri"],
        stations: [{ exercise: "0001" }, { exercise: "0002" }],
        music: { playlist: "library://playlist/1", playlist_name: "Workout Mix", speaker: "media_player.kitchen" },
      },
      { station_names: ["push-up", "squat"], total_seconds: 1320, created_by: "claude" },
    ),
    program(
      2,
      { name: "Core", active: true, weekdays: ["tue", "sat"], stations: [{ exercise: "0003" }] },
      { station_names: ["plank"], total_seconds: 840, created_by: "you" },
    ),
    program(
      3,
      { name: "Legs", active: false, weekdays: [], stations: [{ exercise: "0004" }] },
      { station_names: ["lunge"], total_seconds: 1050, created_by: null },
    ),
  ];
}

async function open(fake: FakeApi): Promise<HTMLElement> {
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/programs");
  await findByRole(root, "table", { name: en.programs.title });
  return root;
}

/** The table's rows below the header, by program name. */
function rowOf(root: HTMLElement, name: string): HTMLElement {
  const table = getByRole(root, "table", { name: en.programs.title });
  const row = within(table)
    .getAllByRole("row")
    .find((candidate) => {
      const header = within(candidate).queryByRole("rowheader");
      return header !== null && text(header).startsWith(`${name} `);
    });
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

function names(root: HTMLElement): string[] {
  const table = getByRole(root, "table", { name: en.programs.title });
  return within(table)
    .getAllByRole("switch")
    .map((element) => element.getAttribute("aria-label") ?? "");
}

function switchOf(root: HTMLElement, name: string): HTMLElement {
  return getByRole(root, "switch", { name: `Active: ${name}` });
}

function writes(fake: FakeApi): string[] {
  return fake.requests.filter((request) => request.method !== "GET").map((request) => `${request.method} ${request.path}`);
}

test("a row shows the name, length, weekdays, music, who created it and the active switch", async () => {
  const root = await open(fakeApi({ programs: programs() }));

  const full = rowOf(root, "Full body");
  expect(within(full).getByText("22 min")).toBeTruthy();
  expect(within(full).getByText("Mon, Wed, Fri")).toBeTruthy();
  expect(within(full).getByText("Workout Mix")).toBeTruthy();
  expect(within(full).getByText("Claude")).toBeTruthy();
  expect(switchOf(root, "Full body").getAttribute("aria-checked")).toBe("true");

  const core = rowOf(root, "Core");
  expect(within(core).getByText("14 min")).toBeTruthy();
  expect(within(core).getByText("Tue, Sat")).toBeTruthy();
  expect(within(core).getByText(en.programs.no_music)).toBeTruthy();
  expect(within(core).getByText("You")).toBeTruthy();

  const legs = rowOf(root, "Legs");
  expect(within(legs).getByText(en.programs.no_weekdays)).toBeTruthy();
  expect(within(legs).queryByText("Claude")).toBeNull();
  expect(within(legs).queryByText("You")).toBeNull();
  expect(switchOf(root, "Legs").getAttribute("aria-checked")).toBe("false");
});

test("music without a playlist name shows the playlist", async () => {
  const stored = program(1, {
    name: "Mix",
    music: { playlist: "library://playlist/9", speaker: "media_player.kitchen" },
  });
  const root = await open(fakeApi({ programs: [stored] }));

  expect(within(rowOf(root, "Mix")).getByText("library://playlist/9")).toBeTruthy();
});

test("a row shows a lazy, relative thumbnail per station, named by the exercise", async () => {
  const root = await open(fakeApi({ programs: programs() }));

  const images = getAllByRole(rowOf(root, "Full body"), "img");
  expect(images.map((image) => image.getAttribute("alt"))).toEqual(["push-up", "squat"]);
  expect(images.map((image) => image.getAttribute("src"))).toEqual([
    "api/v1/exercises/0001/thumbnail",
    "api/v1/exercises/0002/thumbnail",
  ]);
  expect(images.map((image) => image.getAttribute("loading"))).toEqual(["lazy", "lazy"]);
});

test("a thumbnail whose media is missing becomes a placeholder with the exercise's name", async () => {
  const root = await open(fakeApi({ programs: programs() }));

  const image = getByRole(rowOf(root, "Core"), "img", { name: "plank" });
  image.dispatchEvent(new Event("error"));

  await vi.waitFor(() => {
    const placeholder = getByRole(rowOf(root, "Core"), "img", { name: "plank" });
    expect(placeholder.getAttribute("src")).toBeNull();
  });
});

test("the filters narrow the rows to the active or the switched-off programs", async () => {
  const root = await open(fakeApi({ programs: programs() }));

  const all = getByRole(root, "button", { name: "All 3" });
  expect(all.getAttribute("aria-pressed")).toBe("true");
  expect(names(root)).toEqual(["Active: Full body", "Active: Core", "Active: Legs"]);

  fireEvent.click(getByRole(root, "button", { name: "Active 2" }));
  await vi.waitFor(() => expect(names(root)).toEqual(["Active: Full body", "Active: Core"]));
  expect(getByRole(root, "button", { name: "Active 2" }).getAttribute("aria-pressed")).toBe("true");

  fireEvent.click(getByRole(root, "button", { name: "Off 1" }));
  await vi.waitFor(() => expect(names(root)).toEqual(["Active: Legs"]));

  fireEvent.click(getByRole(root, "button", { name: "All 3" }));
  await vi.waitFor(() => expect(names(root)).toHaveLength(3));
});

test("the search narrows the rows by name, sending nothing", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);
  const before = fake.requests.length;

  fireEvent.input(getByRole(root, "searchbox", { name: en.programs.search }), { target: { value: "CO" } });
  await vi.waitFor(() => expect(names(root)).toEqual(["Active: Core"]));

  fireEvent.click(getByRole(root, "button", { name: "Off 1" }));
  await vi.waitFor(() => expect(getByRole(root, "status")).toBeTruthy());
  expect(text(getByRole(root, "status"))).toBe(en.programs.no_match);
  expect(fake.requests.length).toBe(before);
});

test("the switch sends the new state and shows the add-on's answer", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  fireEvent.click(switchOf(root, "Full body"));

  await vi.waitFor(() => expect(switchOf(root, "Full body").getAttribute("aria-checked")).toBe("false"));
  expect(fake.requests.filter((request) => request.method === "PUT")).toEqual([
    { method: "PUT", path: "api/v1/programs/1/active", body: { active: false } },
  ]);

  fireEvent.click(switchOf(root, "Legs"));
  await vi.waitFor(() => expect(switchOf(root, "Legs").getAttribute("aria-checked")).toBe("true"));
  expect(fake.requests.at(-1)).toEqual({ method: "PUT", path: "api/v1/programs/3/active", body: { active: true } });
});

test("a running session refuses the switch: the message shows by the row and the switch stays", async () => {
  const fake = fakeApi({ programs: programs() });
  fake.answer("PUT", "api/v1/programs/1/active", 409, SESSION_RUNNING);
  const root = await open(fake);

  fireEvent.click(switchOf(root, "Full body"));

  const alert = await findByRole(root, "alert");
  expect(text(alert)).toBe(SESSION_RUNNING.detail);
  const row = within(getByRole(root, "table", { name: en.programs.title }))
    .getAllByRole("row")
    .find((candidate) => within(candidate).queryByRole("alert"));
  expect(row).toBe(rowOf(root, "Full body"));
  expect(switchOf(root, "Full body").getAttribute("aria-checked")).toBe("true");
});

test("Edit, Copy and New program are links to the editor's routes", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  expect(getByRole(root, "link", { name: en.programs.new }).getAttribute("href")).toBe("#/programs/new");
  expect(getByRole(root, "link", { name: "Edit Core" }).getAttribute("href")).toBe("#/programs/2");
  const copy = getByRole(root, "link", { name: "Copy Core" });
  expect(copy.getAttribute("href")).toBe("#/programs/new/copy/2");

  fireEvent.click(copy);
  await vi.waitFor(() => getByRole(root, "heading", { level: 1, name: en.editor.copy_title }));
  expect(writes(fake)).toEqual([]);
});

test("Delete asks first, and says what stays, what goes and that it can't be undone", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));

  const dialog = await findByRole(root, "dialog", { name: "Delete “Core”?" });
  expect(within(dialog).getByText(en.programs.delete_history)).toBeTruthy();
  expect(within(dialog).getByText(en.programs.delete_open_days)).toBeTruthy();
  expect(within(dialog).getByText(en.programs.delete_undo)).toBeTruthy();
  expect(within(dialog).getByRole("button", { name: en.programs.turn_off })).toBeTruthy();
  expect(writes(fake)).toEqual([]);

  fireEvent.click(within(dialog).getByRole("button", { name: en.dialog.cancel }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(writes(fake)).toEqual([]);
  expect(rowOf(root, "Core")).toBeTruthy();
});

test("Escape closes the dialog without a write", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));
  const dialog = await findByRole(root, "dialog");
  fireEvent.keyDown(dialog, { key: "Escape" });

  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(writes(fake)).toEqual([]);
});

test("confirming the delete sends DELETE and the row goes", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));
  const dialog = await findByRole(root, "dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.delete_confirm }));

  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(writes(fake)).toEqual(["DELETE api/v1/programs/2"]);
  expect(names(root)).toEqual(["Active: Full body", "Active: Legs"]);
  expect(getByRole(root, "button", { name: "All 2" })).toBeTruthy();
});

test("“Turn it off instead” switches the program off and keeps it", async () => {
  const fake = fakeApi({ programs: programs() });
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));
  const dialog = await findByRole(root, "dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.turn_off }));

  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(fake.requests.filter((request) => request.method !== "GET")).toEqual([
    { method: "PUT", path: "api/v1/programs/2/active", body: { active: false } },
  ]);
  expect(switchOf(root, "Core").getAttribute("aria-checked")).toBe("false");
});

test("a program that is already off isn't offered “Turn it off instead”", async () => {
  const root = await open(fakeApi({ programs: programs() }));

  fireEvent.click(getByRole(root, "button", { name: "Delete Legs" }));
  const dialog = await findByRole(root, "dialog");
  expect(within(dialog).queryByRole("button", { name: en.programs.turn_off })).toBeNull();
});

test("a running session refuses the delete: the dialog says why and the row stays", async () => {
  const fake = fakeApi({ programs: programs() });
  fake.answer("DELETE", "api/v1/programs/2", 409, SESSION_RUNNING);
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));
  const dialog = await findByRole(root, "dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.delete_confirm }));

  const alert = await within(dialog).findByRole("alert");
  expect(text(alert)).toBe(SESSION_RUNNING.detail);
  expect(getByRole(root, "dialog")).toBe(dialog);
  expect(rowOf(root, "Core")).toBeTruthy();
});

test("a running session refuses “Turn it off instead”: the dialog says why and the switch stays", async () => {
  const fake = fakeApi({ programs: programs() });
  fake.answer("PUT", "api/v1/programs/2/active", 409, SESSION_RUNNING);
  const root = await open(fake);

  fireEvent.click(getByRole(root, "button", { name: "Delete Core" }));
  const dialog = await findByRole(root, "dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.turn_off }));

  const alert = await within(dialog).findByRole("alert");
  expect(text(alert)).toBe(SESSION_RUNNING.detail);
  expect(switchOf(root, "Core").getAttribute("aria-checked")).toBe("true");
});

test("without programs the page says so and offers New program", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("#/programs");

  expect(text(await findByRole(root, "status"))).toBe(en.programs.none);
  expect(getByRole(root, "link", { name: en.programs.new })).toBeTruthy();
});

test("a refused read shows the add-on's message instead of loading forever", async () => {
  const fake = fakeApi();
  fake.answer("GET", "api/v1/programs", 503, { detail: "The store isn't ready", code: "unavailable", field: null });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/programs");

  expect(text(await findByRole(root, "alert"))).toBe("The store isn't ready");
  expect(queryByRole(root, "table")).toBeNull();
});

test("when the add-on can't be reached, the page says so", async () => {
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
  const root = await mount("#/programs");

  expect(text(await findByRole(root, "alert"))).toBe(en.error.network);
});
