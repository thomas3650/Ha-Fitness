import { findByRole, fireEvent, getByRole, queryByRole, within } from "@testing-library/dom";
import { computeAccessibleName } from "dom-accessibility-api";
import { afterEach, expect, test, vi } from "vitest";

import type { Exercise, ExerciseSummary, ProgramDocument } from "../src/api";
import en from "../src/i18n/en.json";
import "../src/main";
import { fakeApi, program, type FakeApi } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
});

const STORED_AT = "2026-10-26T10:00:00+00:00";
const KITCHEN = "media_player.test_kitchen";

function summary(
  id: string,
  name: string,
  equipment: string | null,
  body_part: string | null,
  target: string | null,
  custom = false,
): ExerciseSummary {
  return { id, name, equipment, body_part, target, custom };
}

const EXERCISES: ExerciseSummary[] = [
  summary("0001", "push-up", "body weight", "chest", "pectorals"),
  summary("0002", "squat", "body weight", "upper legs", "quads"),
  summary("0003", "goblet squat", "dumbbell", "upper legs", "quads"),
  summary("0004", "cable row", "cable", "back", "lats"),
  summary("0005", "dumbbell row", "dumbbell", "back", "lats"),
  summary("0006", "plank", "body weight", "waist", "abs"),
  summary("custom-1", "towel slide", null, null, null, true),
];

const GOBLET: Exercise = {
  ...EXERCISES[2],
  steps: ["Hold the dumbbell at your chest.", "Squat down and stand up again."],
  secondary_muscles: ["calves", "core"],
  attribution: "Gym visual, test attribution",
};

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function writes(fake: FakeApi) {
  return fake.requests.filter((request) => request.method !== "GET");
}

function lastWrite(fake: FakeApi) {
  const all = writes(fake);
  return all[all.length - 1];
}

function fullBody(document: Partial<ProgramDocument> = {}) {
  return program(
    1,
    {
      name: "Full body",
      active: true,
      weekdays: ["mon", "wed"],
      stations: [{ exercise: "0001" }, { exercise: "0002" }, { exercise: "0006" }],
      rounds: 4,
      music: {
        playlist: "library://playlist/1",
        playlist_name: "Workout Mix",
        speaker: KITCHEN,
        volume: 35,
        shuffle: true,
      },
      ...document,
    },
    { updated_at: STORED_AT, station_names: ["push-up", "squat", "plank"] },
  );
}

function newFake(extra: Parameters<typeof fakeApi>[0] = {}): FakeApi {
  return fakeApi({
    exercises: EXERCISES,
    setup: { equipment: ["body weight", "dumbbell"], favourite_playlists: [], default_speaker: null },
    speakers: [{ entity_id: KITCHEN, name: "Test kitchen", available: true }],
    playlists: [
      { name: "Workout Mix", uri: "library://playlist/1" },
      { name: "Morning Run", uri: "library://playlist/2" },
    ],
    ...extra,
  });
}

/** Mount at a route and wait until the editor's form shows. */
async function openEditor(fake: FakeApi, hash: string): Promise<HTMLElement> {
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount(hash);
  await findByRole(root, "textbox", { name: en.editor.name });
  return root;
}

function field(root: HTMLElement, role: string, name: string): HTMLInputElement {
  return getByRole(root, role, { name }) as HTMLInputElement;
}

function stationList(root: HTMLElement): HTMLElement {
  return getByRole(root, "list", { name: en.editor.stations });
}

function stationNames(root: HTMLElement): string[] {
  return within(stationList(root))
    .getAllByRole("listitem")
    .map((item) => computeAccessibleName(within(item).getByRole("button", { name: /^Remove / })))
    .map((label) => label.replace(/^Remove /, ""));
}

function panel(root: HTMLElement): HTMLElement {
  return getByRole(root, "complementary", { name: en.picker.title });
}

function panelNames(root: HTMLElement): string[] {
  const list = within(panel(root)).queryByRole("list", { name: en.picker.results });
  if (!list) return [];
  return within(list)
    .getAllByRole("listitem")
    .map((item) => text(within(item).getAllByRole("button")[0]));
}

/** A dropdown (the equipment filter or a multi-select): the group named `name`, its parts in its own shadow root. */
function dropdown(scope: HTMLElement, name: string): HTMLElement {
  return getByRole(scope, "group", { name }).shadowRoot as unknown as HTMLElement;
}

/** Open a dropdown's list and return it. */
async function openList(scope: HTMLElement, name: string): Promise<HTMLElement> {
  const parts = dropdown(scope, name);
  fireEvent.click(getByRole(parts, "combobox", { name }));
  return findByRole(parts, "listbox", { name });
}

/** Choose an option of a dropdown by its accessible name. */
async function choose(scope: HTMLElement, name: string, option: string | RegExp): Promise<void> {
  fireEvent.click(within(await openList(scope, name)).getByRole("option", { name: option }));
}

/** A dropdown's options by their accessible names. */
async function optionNames(scope: HTMLElement, name: string): Promise<string[]> {
  return within(await openList(scope, name))
    .getAllByRole("option")
    .map((option) => computeAccessibleName(option));
}

/** A dropdown's tags. */
function tags(scope: HTMLElement, name: string): string[] {
  const list = getByRole(dropdown(scope, name), "list", { name: en.multi_select.chosen.replace("{label}", name) });
  return within(list).queryAllByRole("listitem").map(text);
}

function rename(root: HTMLElement, name: string): void {
  fireEvent.input(field(root, "textbox", en.editor.name), { target: { value: name } });
}

/** Click Save and wait until the add-on's answer is in: the request is sent and Save can be pressed again. */
async function save(root: HTMLElement, fake: FakeApi): Promise<void> {
  const before = writes(fake).length;
  const button = getByRole(root, "button", { name: en.editor.save }) as HTMLButtonElement;
  fireEvent.click(button);
  await vi.waitFor(() => expect(writes(fake).length).toBe(before + 1));
  await vi.waitFor(() => expect(button.disabled).toBe(false));
}

// W2: the new-program page.

test("the new-program page offers to start empty, with the add-on's defaults, or to copy a program", async () => {
  const fake = newFake({ programs: [fullBody()] });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/programs/new");

  expect(getByRole(root, "heading", { level: 1, name: en.editor.new_title })).toBeTruthy();
  const start = await findByRole(root, "link", { name: en.new_program.start_empty });
  expect(start.getAttribute("href")).toBe("#/programs/new/empty");
  expect(
    await within(root).findByText(
      "Defaults: 5 rounds · 45 s work · 15 s break between exercises · 60 s between rounds · countdown 5 s.",
    ),
  ).toBeTruthy();
  expect(getByRole(root, "heading", { name: en.new_program.copy_title })).toBeTruthy();
  const copy = await findByRole(root, "link", { name: /Full body/ });
  expect(copy.getAttribute("href")).toBe("#/programs/new/copy/1");
  expect(writes(fake)).toEqual([]);
});

test("an empty program starts active, with no weekdays or music, and the add-on's defaults", async () => {
  const fake = newFake({
    defaults: { rounds: 6, work_seconds: 40, switch_seconds: 20, round_rest_seconds: 90, countdown_seconds: 10 },
  });
  const root = await openEditor(fake, "#/programs/new/empty");

  expect(fake.requests.some((request) => request.path === "api/v1/programs/defaults")).toBe(true);
  expect(field(root, "textbox", en.editor.name).value).toBe("");
  expect(field(root, "spinbutton", en.editor.rounds).value).toBe("6");
  expect(field(root, "spinbutton", en.editor.work).value).toBe("40");
  expect(field(root, "spinbutton", en.editor.switch).value).toBe("20");
  expect(field(root, "spinbutton", en.editor.round_rest).value).toBe("90");
  const countdown = field(root, "combobox", en.editor.countdown);
  expect(countdown.value).toBe("10");
  expect(within(countdown).getAllByRole("option").map(text)).toEqual(["0 s", "5 s", "10 s"]);
  expect(getByRole(root, "switch", { name: en.editor.active }).getAttribute("aria-checked")).toBe("true");
  const weekdays = getByRole(root, "group", { name: en.editor.weekdays });
  expect(within(weekdays).getAllByRole("button").map((day) => day.getAttribute("aria-pressed"))).toEqual(
    Array(7).fill("false"),
  );
  expect(field(root, "combobox", en.editor.music).value).toBe("");
  expect(writes(fake)).toEqual([]);
});

test("the shown defaults are the add-on's: 5 rounds, 45 s, 15 s, 60 s and a countdown of 5 of 0, 5 and 10", async () => {
  const root = await openEditor(newFake(), "#/programs/new/empty");

  expect(field(root, "spinbutton", en.editor.rounds).value).toBe("5");
  expect(field(root, "spinbutton", en.editor.work).value).toBe("45");
  expect(field(root, "spinbutton", en.editor.switch).value).toBe("15");
  expect(field(root, "spinbutton", en.editor.round_rest).value).toBe("60");
  expect(field(root, "combobox", en.editor.countdown).value).toBe("5");
});

test("saving an empty program without a weekday shows the add-on's message at the weekdays and keeps the form", async () => {
  const fake = newFake();
  const message = "Value error, an active program needs at least one weekday";
  fake.answer("POST", "api/v1/programs", 422, {
    detail: [{ loc: ["body", "weekdays"], msg: message, type: "weekday_needed" }],
  });
  const root = await openEditor(fake, "#/programs/new/empty");

  rename(root, "Morning");
  fireEvent.input(field(root, "spinbutton", en.editor.rounds), { target: { value: "3" } });
  await save(root, fake);

  expect(await findByRole(root, "group", { name: en.editor.weekdays, description: message })).toBeTruthy();
  expect(field(root, "textbox", en.editor.name).value).toBe("Morning");
  expect(field(root, "spinbutton", en.editor.rounds).value).toBe("3");
  expect(lastWrite(fake).body).toMatchObject({ name: "Morning", active: true, weekdays: [], rounds: 3, music: null });
});

test("a new program's speaker is the setup's default speaker, and its music is sent once a playlist is picked", async () => {
  const fake = newFake({
    setup: { equipment: ["body weight"], favourite_playlists: [], default_speaker: KITCHEN },
  });
  const root = await openEditor(fake, "#/programs/new/empty");

  expect(field(root, "combobox", en.editor.speaker).value).toBe(KITCHEN);
  rename(root, "Morning");
  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).music).toBeNull();
});

test("picking a playlist in a new program sends the music with the default speaker; saved, it opens for editing", async () => {
  const fake = newFake({
    setup: { equipment: ["body weight"], favourite_playlists: [], default_speaker: KITCHEN },
  });
  const root = await openEditor(fake, "#/programs/new/empty");

  rename(root, "Morning");
  fireEvent.click(within(getByRole(root, "group", { name: en.editor.weekdays })).getByRole("button", { name: "Tue" }));
  fireEvent.click(await within(panel(root)).findByRole("button", { name: "Add push-up" }));
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up"]));
  fireEvent.change(field(root, "combobox", en.editor.music), { target: { value: "library://playlist/2" } });
  await save(root, fake);

  const sent = lastWrite(fake);
  expect(sent.method).toBe("POST");
  expect(sent.body).toEqual({
    name: "Morning",
    active: true,
    weekdays: ["tue"],
    stations: [{ exercise: "0001" }],
    rounds: 5,
    work_seconds: 45,
    switch_seconds: 15,
    round_rest_seconds: 60,
    countdown_seconds: 5,
    music: { playlist: "library://playlist/2", playlist_name: "Morning Run", speaker: KITCHEN },
  });
  await vi.waitFor(() => expect(location.hash).toBe("#/programs/1"));
  await findByRole(root, "heading", { level: 1, name: en.editor.edit_title });
});

// The copy route.

test("a copy opens prefilled and switched off, sends nothing before Save, and Save sends one POST", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/new/copy/1");

  expect(getByRole(root, "heading", { level: 1, name: en.editor.copy_title })).toBeTruthy();
  expect(field(root, "textbox", en.editor.name).value).toBe("Full body (copy)");
  expect(getByRole(root, "switch", { name: en.editor.active }).getAttribute("aria-checked")).toBe("false");
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "squat", "plank"]));
  expect(field(root, "combobox", en.editor.music).value).toBe("library://playlist/1");
  expect(writes(fake)).toEqual([]);

  await save(root, fake);

  expect(writes(fake).map((request) => `${request.method} ${request.path}`)).toEqual(["POST api/v1/programs"]);
  expect(lastWrite(fake).body).toEqual({
    ...fullBody().program,
    name: "Full body (copy)",
    active: false,
  });
});

test("a taken name shows the add-on's message at the name field", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const message = "Program name 'Full body (copy)' is taken";
  fake.answer("POST", "api/v1/programs", 409, { detail: message, code: "name_taken", field: "name" });
  const root = await openEditor(fake, "#/programs/new/copy/1");

  await save(root, fake);

  expect(await findByRole(root, "textbox", { name: en.editor.name, description: message })).toBeTruthy();
  expect(location.hash).toBe("#/programs/new/copy/1");
});

// Editing.

test("editing loads the program; Save sends the whole document with its url-encoded updated_at", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  expect(fake.requests.some((request) => request.method === "GET" && request.path === "api/v1/programs/1")).toBe(true);
  rename(root, "Full body 2");
  await save(root, fake);

  const first = lastWrite(fake);
  expect(first.method).toBe("PUT");
  expect(first.path).toBe("api/v1/programs/1?if_updated_at=2026-10-26T10%3A00%3A00%2B00%3A00");
  expect(first.body).toEqual({ ...fullBody().program, name: "Full body 2" });

  const answered = fake.state.programs[0].updated_at;
  rename(root, "Full body 3");
  await save(root, fake);
  expect(lastWrite(fake).path).toBe(`api/v1/programs/1?if_updated_at=${encodeURIComponent(answered)}`);
});

test("saving keeps the music's volume and shuffle; another playlist sets its uri and name", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).music).toEqual({
    playlist: "library://playlist/1",
    playlist_name: "Workout Mix",
    speaker: KITCHEN,
    volume: 35,
    shuffle: true,
  });

  fireEvent.change(field(root, "combobox", en.editor.music), { target: { value: "library://playlist/2" } });
  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).music).toEqual({
    playlist: "library://playlist/2",
    playlist_name: "Morning Run",
    speaker: KITCHEN,
    volume: 35,
    shuffle: true,
  });
});

test("the setup's favourite playlists come first in the music choice", async () => {
  const fake = newFake({
    programs: [fullBody()],
    setup: {
      equipment: ["body weight"],
      favourite_playlists: [{ uri: "library://playlist/3", name: "Favourite Beats" }],
      default_speaker: null,
    },
    playlists: [
      { name: "Workout Mix", uri: "library://playlist/1" },
      { name: "Morning Run", uri: "library://playlist/2" },
      { name: "Favourite Beats", uri: "library://playlist/3" },
    ],
  });
  const root = await openEditor(fake, "#/programs/1");

  const music = field(root, "combobox", en.editor.music);
  await vi.waitFor(() =>
    expect(within(music).getAllByRole("option").map(text)).toEqual([
      en.editor.no_music,
      "Favourite Beats",
      "Workout Mix",
      "Morning Run",
    ]),
  );
});

test("a speaker Music Assistant doesn't list still shows and is kept", async () => {
  const gone = "media_player.test_gone";
  const fake = newFake({
    programs: [fullBody({ music: { playlist: "library://playlist/1", playlist_name: "Workout Mix", speaker: gone } })],
  });
  const root = await openEditor(fake, "#/programs/1");

  const speaker = field(root, "combobox", en.editor.speaker);
  await vi.waitFor(() => expect(within(speaker).getAllByRole("option").map(text)).toContain(gone));
  expect(speaker.value).toBe(gone);
  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).music?.speaker).toBe(gone);
});

test("music reads that fail say so, and the program still saves", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const unavailable = { detail: "Music Assistant can't be reached", code: "", field: null };
  fake.answer("GET", "api/v1/music/speakers", 503, unavailable);
  fake.answer("GET", "api/v1/music/playlists", 503, unavailable);
  const root = await openEditor(fake, "#/programs/1");

  const music = getByRole(root, "group", { name: en.editor.music_group });
  await vi.waitFor(() => expect(within(music).getAllByText("Music Assistant can't be reached").length).toBe(2));
  await save(root, fake);
  expect(lastWrite(fake).method).toBe("PUT");
});

test("empty music lists say so", async () => {
  const fake = newFake({ programs: [fullBody()], speakers: [], playlists: [] });
  const root = await openEditor(fake, "#/programs/1");

  const music = getByRole(root, "group", { name: en.editor.music_group });
  expect(await within(music).findByText(en.editor.no_speakers)).toBeTruthy();
  expect(within(music).getByText(en.editor.no_playlists)).toBeTruthy();
});

// The stations.

test("+ adds, × removes and the move buttons reorder; the sent stations follow", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "squat", "plank"]));

  fireEvent.click(within(panel(root)).getByRole("button", { name: "Add goblet squat" }));
  fireEvent.click(await findByRole(root, "button", { name: "Remove squat" }));
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "plank", "goblet squat"]));
  fireEvent.click(getByRole(root, "button", { name: "Move goblet squat up" }));
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "goblet squat", "plank"]));
  fireEvent.click(getByRole(root, "button", { name: "Move push-up down" }));
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["goblet squat", "push-up", "plank"]));

  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).stations).toEqual([
    { exercise: "0003" },
    { exercise: "0001" },
    { exercise: "0006" },
  ]);
});

test("a 16th station is sent, and the add-on's refusal shows at the list", async () => {
  const fifteen = Array.from({ length: 15 }, () => ({ exercise: "0001" }));
  const fake = newFake({ programs: [fullBody({ stations: fifteen })] });
  const message = "List should have at most 15 items after validation, not 16";
  fake.answer("PUT", "api/v1/programs/1", 422, {
    detail: [{ loc: ["body", "stations"], msg: message, type: "too_long" }],
  });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.click(await within(panel(root)).findByRole("button", { name: "Add squat" }));
  await save(root, fake);

  expect((lastWrite(fake).body as ProgramDocument).stations).toHaveLength(16);
  expect(await findByRole(root, "list", { name: en.editor.stations, description: message })).toBeTruthy();
  expect(stationNames(root)).toHaveLength(16);
});

test("a refused station shows the add-on's message at that station", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const message = "Station 2: no exercise 'squat'";
  fake.answer("PUT", "api/v1/programs/1", 422, {
    detail: { message, station: 2, close_matches: [] },
    code: "station_unknown",
    field: "stations.1",
  });
  const root = await openEditor(fake, "#/programs/1");

  await save(root, fake);

  const item = await findByRole(root, "listitem", { description: message });
  expect(within(item).getByRole("button", { name: "Remove squat" })).toBeTruthy();
});

// The library panel and the details.

test("the panel starts on My equipment: the household's exercises and every custom one; All equipment shows the rest", async () => {
  const fake = newFake({
    programs: [fullBody()],
    setup: { equipment: ["dumbbell"], favourite_playlists: [], default_speaker: null },
  });
  const root = await openEditor(fake, "#/programs/1");

  await vi.waitFor(() => expect(panelNames(root)).toContain("goblet squat"));
  const names = panelNames(root);
  expect(names).toContain("towel slide");
  expect(names).toContain("plank");
  expect(names).not.toContain("cable row");
  expect(text(panel(root))).toContain("6 exercises");
  expect(tags(panel(root), en.picker.equipment)).toEqual([en.equipment_filter.mine]);

  await choose(panel(root), en.picker.equipment, /^All equipment/);
  await vi.waitFor(() => expect(panelNames(root)).toContain("cable row"));
  expect(panelNames(root)).toHaveLength(EXERCISES.length);
  expect(text(panel(root))).toContain(`${EXERCISES.length} exercises`);
});

test("picking a kind shows its exercises even when it isn't at home, and a custom exercise only when it matches", async () => {
  const swing = summary("0008", "kettlebell swing", "kettlebell", "upper legs", "glutes");
  const fake = newFake({ programs: [fullBody()], exercises: [...EXERCISES, swing] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));
  expect(panelNames(root)).not.toContain("kettlebell swing");

  await choose(panel(root), en.picker.equipment, "kettlebell, not at home");
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["kettlebell swing"]));
  expect(text(panel(root))).toContain("1 exercise");

  await choose(panel(root), en.picker.equipment, "dumbbell");
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["goblet squat", "dumbbell row", "kettlebell swing"]));
  expect(tags(panel(root), en.picker.equipment)).toEqual(["dumbbell", "kettlebell"]);

  await choose(panel(root), en.picker.equipment, /^All equipment/);
  await vi.waitFor(() => expect(panelNames(root)).toHaveLength(EXERCISES.length + 1));
  expect(panelNames(root)).toContain("towel slide");
});

test("the panel searches by name and filters by body part; it has no target filter and no native selects", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("squat"));
  expect(within(panel(root)).queryByRole("group", { name: en.library.target })).toBeNull();
  expect(within(panel(root)).queryByRole("checkbox")).toBeNull();
  expect(within(panel(root)).queryAllByRole("combobox")).toEqual([]);

  fireEvent.input(within(panel(root)).getByRole("searchbox", { name: en.picker.search }), {
    target: { value: "squat" },
  });
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["squat", "goblet squat"]));
  fireEvent.input(within(panel(root)).getByRole("searchbox", { name: en.picker.search }), {
    target: { value: "" },
  });

  await choose(panel(root), en.picker.body_part, "back");
  // My equipment is on: the cable row isn't the household's.
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["dumbbell row"]));
  await choose(panel(root), en.picker.body_part, "waist");
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["dumbbell row", "plank"]));
  expect(text(panel(root))).toContain("2 exercises");

  await choose(panel(root), en.picker.equipment, /^All equipment/);
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["cable row", "dumbbell row", "plank"]));
});

test("with a search typed and a body part chosen, the panel's mode lines still count the whole library", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("squat"));

  fireEvent.input(within(panel(root)).getByRole("searchbox", { name: en.picker.search }), {
    target: { value: "row" },
  });
  await choose(panel(root), en.picker.body_part, "back");
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["dumbbell row"]));

  expect((await optionNames(panel(root), en.picker.equipment)).slice(0, 2)).toEqual([
    "My equipment, body weight, dumbbell · 6",
    `All equipment, ${EXERCISES.length}`,
  ]);
});

test("an exercise already in the program is added again with its own button, and it adds a station", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));

  const list = within(panel(root)).getByRole("list", { name: en.picker.results });
  expect(within(list).queryByRole("button", { name: "Add push-up" })).toBeNull();
  expect(within(list).getByRole("button", { name: "Add goblet squat" })).toBeTruthy();
  // One button per row: the tick is the add button, not a second mark beside it.
  expect(within(list).queryAllByRole("img")).toEqual([]);

  fireEvent.click(within(list).getByRole("button", { name: "Add push-up again (in the program)" }));
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "squat", "plank", "push-up"]));
  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).stations).toEqual([
    { exercise: "0001" },
    { exercise: "0002" },
    { exercise: "0006" },
    { exercise: "0001" },
  ]);
});

test("a failed setup read shows at the top of the panel; My equipment is then body weight and the custom exercises", async () => {
  const fake = newFake({ programs: [fullBody()] });
  fake.answer("GET", "api/v1/setup", 503, { detail: "The setup can't be read", code: "", field: null });
  const root = await openEditor(fake, "#/programs/1");

  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));
  expect(text(panel(root))).toContain("The setup can't be read");
  expect(text(panel(root))).toContain(en.picker.setup_note);
  expect(panelNames(root)).toContain("towel slide");
  expect(panelNames(root)).not.toContain("goblet squat");
  const names = await optionNames(panel(root), en.picker.equipment);
  expect(names).toContain("My equipment, body weight · 4");
  expect(names).toContain("dumbbell, not at home");
  expect(names).toContain("body weight");
});

test("the panel draws at most 100 exercises and says how to narrow the list", async () => {
  const many = Array.from({ length: 120 }, (_, index) => {
    const number = String(index).padStart(3, "0");
    return summary(`9${number}`, `drill ${number}`, "body weight", "chest", "pectorals");
  });
  const fake = newFake({ programs: [fullBody()], exercises: many });
  const root = await openEditor(fake, "#/programs/1");

  await vi.waitFor(() => expect(panelNames(root)).toHaveLength(100));
  expect(text(panel(root))).toContain("Showing 100 of 120. Search to narrow the list.");
  expect(text(panel(root))).toContain("120 exercises");
});

test("the details dialog adds an exercise that is already in the program", async () => {
  const details: Exercise = { ...EXERCISES[0], steps: ["Push."], secondary_muscles: [], attribution: null };
  const fake = newFake({ programs: [fullBody()], details: { "0001": details } });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));

  fireEvent.click(within(panel(root)).getByRole("button", { name: "push-up" }));
  const dialog = await findByRole(root, "dialog", { name: "push-up" });
  fireEvent.click(within(dialog).getByRole("button", { name: en.details.add }));

  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "squat", "plank", "push-up"]));
});

test("a click on a panel exercise opens its details: the GIF with its attribution, the muscles and the steps", async () => {
  const fake = newFake({ programs: [fullBody()], details: { "0003": GOBLET } });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("goblet squat"));

  fireEvent.click(within(panel(root)).getByRole("button", { name: "goblet squat" }));

  const dialog = await findByRole(root, "dialog", { name: "goblet squat" });
  const gif = await within(dialog).findByRole("img", { name: "goblet squat" });
  expect(gif.getAttribute("src")).toBe("api/v1/exercises/0003/gif");
  expect(await within(dialog).findByText("Gym visual, test attribution")).toBeTruthy();
  expect(within(dialog).getByText("dumbbell")).toBeTruthy();
  expect(within(dialog).getByText("upper legs")).toBeTruthy();
  expect(within(dialog).getByText("Target: quads")).toBeTruthy();
  expect(within(dialog).getByText("Also: calves, core")).toBeTruthy();
  expect(within(within(dialog).getByRole("list")).getAllByRole("listitem").map(text)).toEqual(GOBLET.steps);

  fireEvent.click(within(dialog).getByRole("button", { name: en.details.add }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(stationNames(root)).toEqual(["push-up", "squat", "plank", "goblet squat"]);
});

test("the details dialog closes with Close and with Escape", async () => {
  const fake = newFake({ programs: [fullBody()], details: { "0003": GOBLET } });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("goblet squat"));

  fireEvent.click(within(panel(root)).getByRole("button", { name: "goblet squat" }));
  let dialog = await findByRole(root, "dialog", { name: "goblet squat" });
  fireEvent.click(within(dialog).getByRole("button", { name: en.details.close }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());

  fireEvent.click(within(panel(root)).getByRole("button", { name: "goblet squat" }));
  dialog = await findByRole(root, "dialog", { name: "goblet squat" });
  fireEvent.keyDown(dialog, { key: "Escape" });
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(writes(fake)).toEqual([]);
});

// The summary line.

test("the summary says the number of exercises, the add-on's total time and the equipment without body weight", async () => {
  const fake = newFake({
    programs: [
      fullBody({
        stations: [
          { exercise: "0001" },
          { exercise: "0003" },
          { exercise: "0005" },
          { exercise: "0006" },
          { exercise: "0004" },
        ],
        rounds: 4,
        work_seconds: 45,
        switch_seconds: 15,
        round_rest_seconds: 60,
      }),
    ],
  });
  const root = await openEditor(fake, "#/programs/1");

  expect(await within(root).findByText("5 exercises")).toBeTruthy();
  expect(within(root).getByText("23 min in all · 4 rounds × 5 exercises")).toBeTruthy();
  expect(within(root).getByText("Equipment: dumbbell, cable")).toBeTruthy();
});

test("the summary names a band once, whichever of its two names the exercises use", async () => {
  const pull = summary("0010", "band pull apart", "band", "shoulders", "delts");
  const curl = summary("0011", "resistance band curl", "resistance band", "upper arms", "biceps");
  const fake = newFake({
    exercises: [...EXERCISES, pull, curl],
    programs: [fullBody({ stations: [{ exercise: "0010" }, { exercise: "0003" }, { exercise: "0011" }] })],
  });
  const root = await openEditor(fake, "#/programs/1");

  expect(await within(root).findByText("Equipment: band, dumbbell")).toBeTruthy();
});

// Unsaved changes.

test("a change shows Not saved, and only then the page's unload is cancelled", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  expect(within(root).queryByText(en.editor.not_saved)).toBeNull();
  const clean = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);

  rename(root, "Changed");
  expect(await within(root).findByText(en.editor.not_saved)).toBeTruthy();
  const dirty = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirty);
  expect(dirty.defaultPrevented).toBe(true);

  await save(root, fake);
  await vi.waitFor(() => expect(within(root).queryByText(en.editor.not_saved)).toBeNull());
  const saved = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(saved);
  expect(saved.defaultPrevented).toBe(false);
});

test("leaving within the site with unsaved changes asks first", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  rename(root, "Changed");

  location.hash = "#/library";
  const dialog = await findByRole(root, "dialog", { name: en.editor.leave_title });
  expect(location.hash).toBe("#/programs/1");
  expect(getByRole(root, "heading", { level: 1, name: en.editor.edit_title })).toBeTruthy();

  fireEvent.click(within(dialog).getByRole("button", { name: en.dialog.cancel }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(field(root, "textbox", en.editor.name).value).toBe("Changed");

  location.hash = "#/library";
  const again = await findByRole(root, "dialog", { name: en.editor.leave_title });
  fireEvent.click(within(again).getByRole("button", { name: en.editor.leave_confirm }));
  await findByRole(root, "heading", { level: 1, name: en.library.title });
  expect(location.hash).toBe("#/library");
  expect(writes(fake)).toEqual([]);

  const after = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(after);
  expect(after.defaultPrevented).toBe(false);
});

test("Cancel returns to the programs at once when nothing changed", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.click(getByRole(root, "button", { name: en.editor.cancel }));

  await findByRole(root, "heading", { level: 1, name: en.programs.title });
  expect(location.hash).toBe("#/programs");
});

test("Cancel with unsaved changes asks first", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  rename(root, "Changed");

  fireEvent.click(getByRole(root, "button", { name: en.editor.cancel }));
  const dialog = await findByRole(root, "dialog", { name: en.editor.leave_title });
  fireEvent.click(within(dialog).getByRole("button", { name: en.editor.leave_confirm }));

  await findByRole(root, "heading", { level: 1, name: en.programs.title });
  expect(writes(fake)).toEqual([]);
});

// Refusals.

test("a change made elsewhere shows the add-on's message with Reload, and keeps what was typed", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const message = "The program was changed elsewhere; reload it";
  fake.answer("PUT", "api/v1/programs/1", 409, { detail: message, code: "changed_elsewhere", field: null });
  const root = await openEditor(fake, "#/programs/1");

  rename(root, "Mine");
  await save(root, fake);

  const alert = await findByRole(root, "alert");
  expect(within(alert).getByText(message)).toBeTruthy();
  expect(field(root, "textbox", en.editor.name).value).toBe("Mine");

  const stored = fake.state.programs[0];
  fake.state.programs[0] = {
    ...stored,
    program: { ...stored.program, name: "Theirs" },
    updated_at: "2026-10-26T11:00:00+00:00",
  };
  fake.restore("PUT", "api/v1/programs/1");
  fireEvent.click(within(alert).getByRole("button", { name: en.editor.reload }));

  await vi.waitFor(() => expect(field(root, "textbox", en.editor.name).value).toBe("Theirs"));
  expect(queryByRole(root, "alert")).toBeNull();
  await save(root, fake);
  expect(lastWrite(fake).path).toBe("api/v1/programs/1?if_updated_at=2026-10-26T11%3A00%3A00%2B00%3A00");
});

test("a refusal without a field, or at a field the form doesn't show, shows above the form", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const message = "A session for this program is running";
  fake.answer("PUT", "api/v1/programs/1", 409, { detail: message, code: "session_running", field: null });
  const root = await openEditor(fake, "#/programs/1");

  await save(root, fake);
  expect(within(await findByRole(root, "alert")).getByText(message)).toBeTruthy();

  fake.answer("PUT", "api/v1/programs/1", 422, {
    detail: [{ loc: ["body", "surprise"], msg: "Extra inputs are not permitted", type: "extra_forbidden" }],
  });
  await save(root, fake);
  await vi.waitFor(() =>
    expect(within(getByRole(root, "alert")).getByText("Extra inputs are not permitted")).toBeTruthy(),
  );
});

test("a refused number shows at its field", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const message = "Input should be greater than or equal to 1";
  fake.answer("PUT", "api/v1/programs/1", 422, {
    detail: [{ loc: ["body", "rounds"], msg: message, type: "greater_than_equal" }],
  });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.input(field(root, "spinbutton", en.editor.rounds), { target: { value: "0" } });
  await save(root, fake);

  expect(await findByRole(root, "spinbutton", { name: en.editor.rounds, description: message })).toBeTruthy();
  expect((lastWrite(fake).body as ProgramDocument).rounds).toBe(0);
  expect(field(root, "spinbutton", en.editor.rounds).value).toBe("0");
});

test("Delete asks with the delete dialog and goes back to the programs", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.click(getByRole(root, "button", { name: en.editor.delete }));
  const dialog = await findByRole(root, "dialog", { name: "Delete “Full body”?" });
  expect(within(dialog).getByText(en.programs.delete_history)).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.delete_confirm }));

  await findByRole(root, "heading", { level: 1, name: en.programs.title });
  expect(writes(fake).map((request) => `${request.method} ${request.path}`)).toEqual(["DELETE api/v1/programs/1"]);
});

test("the editor shows who created the program", async () => {
  const root = await openEditor(newFake({ programs: [fullBody()] }), "#/programs/1");

  expect(await within(root).findByText(en.editor.created_by_you)).toBeTruthy();
});

// Fix round 1.

test("Tab and Shift+Tab keep the focus inside the details dialog", async () => {
  const fake = newFake({ programs: [fullBody()], details: { "0003": GOBLET } });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("goblet squat"));

  fireEvent.click(within(panel(root)).getByRole("button", { name: "goblet squat" }));
  const dialog = await findByRole(root, "dialog", { name: "goblet squat" });
  const first = within(dialog).getByRole("button", { name: en.details.close });
  const last = within(dialog).getByRole("button", { name: en.details.add });
  const active = () => (root as unknown as ShadowRoot).activeElement;

  last.focus();
  fireEvent.keyDown(last, { key: "Tab" });
  expect(active()).toBe(first);

  fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
  expect(active()).toBe(last);
});

test("a failed setup read says so, and the editor still works", async () => {
  const fake = newFake({ programs: [fullBody()] });
  fake.answer("GET", "api/v1/setup", 503, { detail: "The setup can't be read", code: "", field: null });
  const root = await openEditor(fake, "#/programs/1");

  const music = getByRole(root, "group", { name: en.editor.music_group });
  expect(await within(music).findByText("The setup can't be read")).toBeTruthy();
  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));
  rename(root, "Still works");
  await save(root, fake);
  expect(lastWrite(fake).method).toBe("PUT");
});

test("a change typed while a new program is being created isn't lost, and no second program is created", async () => {
  const fake = newFake();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let posted = false;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init: RequestInit = {}) => {
    if (init.method === "POST") {
      posted = true;
      await gate;
    }
    return fake.fetch(input, init);
  });
  const root = await mount("#/programs/new/empty");
  await findByRole(root, "textbox", { name: en.editor.name });

  rename(root, "First");
  fireEvent.click(getByRole(root, "button", { name: en.editor.save }));
  await vi.waitFor(() => expect(posted).toBe(true));
  rename(root, "Later");
  release();

  const dialog = await findByRole(root, "dialog", { name: en.editor.leave_title });
  expect(field(root, "textbox", en.editor.name).value).toBe("Later");
  fireEvent.click(within(dialog).getByRole("button", { name: en.dialog.cancel }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());

  await save(root, fake);
  const sent = writes(fake).map((request) => `${request.method} ${request.path.split("?")[0]}`);
  expect(sent).toEqual(["POST api/v1/programs", "PUT api/v1/programs/1"]);
  expect((lastWrite(fake).body as ProgramDocument).name).toBe("Later");
  await vi.waitFor(() => expect(location.hash).toBe("#/programs/1"));
});

test("dragging a station onto another moves it there", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["push-up", "squat", "plank"]));

  const items = within(stationList(root)).getAllByRole("listitem");
  fireEvent.dragStart(items[2]);
  fireEvent.dragOver(items[0]);
  fireEvent.drop(items[0]);
  fireEvent.dragEnd(items[2]);
  await vi.waitFor(() => expect(stationNames(root)).toEqual(["plank", "push-up", "squat"]));

  await save(root, fake);
  expect((lastWrite(fake).body as ProgramDocument).stations).toEqual([
    { exercise: "0006" },
    { exercise: "0001" },
    { exercise: "0002" },
  ]);
});

test("“Turn it off instead” in the editor switches the program off, and a later Save uses that answer's updated_at", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.click(getByRole(root, "button", { name: en.editor.delete }));
  const dialog = await findByRole(root, "dialog", { name: "Delete “Full body”?" });
  fireEvent.click(within(dialog).getByRole("button", { name: en.programs.turn_off }));

  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(lastWrite(fake)).toMatchObject({ method: "PUT", path: "api/v1/programs/1/active", body: { active: false } });
  expect(getByRole(root, "switch", { name: en.editor.active }).getAttribute("aria-checked")).toBe("false");
  expect(within(root).queryByText(en.editor.not_saved)).toBeNull();

  const answered = fake.state.programs[0].updated_at;
  rename(root, "Paused");
  await save(root, fake);
  expect(lastWrite(fake).path).toBe(`api/v1/programs/1?if_updated_at=${encodeURIComponent(answered)}`);
  expect((lastWrite(fake).body as ProgramDocument).active).toBe(false);
});

// The editor in cards (W7).

function stepper(root: HTMLElement, name: string): HTMLButtonElement {
  return getByRole(root, "button", { name }) as HTMLButtonElement;
}

/** Wait until a number field shows `value`. */
async function shows(root: HTMLElement, name: string, value: string): Promise<void> {
  await vi.waitFor(() => expect(field(root, "spinbutton", name).value).toBe(value));
}

test("the head: the Programs link, the page title, and the name field with its placeholder", async () => {
  const root = await openEditor(newFake({ programs: [fullBody()] }), "#/programs/1");

  const breadcrumb = getByRole(root, "navigation", { name: en.editor.breadcrumb });
  expect(within(breadcrumb).getByRole("link", { name: en.menu.programs }).getAttribute("href")).toBe("#/programs");
  expect(getByRole(root, "heading", { level: 1, name: en.editor.edit_title })).toBeTruthy();
  const name = field(root, "textbox", en.editor.name);
  expect(name.placeholder).toBe("Unnamed program");
  expect(name.value).toBe("Full body");
  expect((root as unknown as ShadowRoot).activeElement).not.toBe(name);
});

test("a new program and a copy open with the focus in the name field", async () => {
  const active = (root: HTMLElement) => (root as unknown as ShadowRoot).activeElement;
  let root = await openEditor(newFake(), "#/programs/new/empty");
  await vi.waitFor(() => expect(active(root)).toBe(field(root, "textbox", en.editor.name)));
  unmount();

  root = await openEditor(newFake({ programs: [fullBody()] }), "#/programs/new/copy/1");
  await vi.waitFor(() => expect(active(root)).toBe(field(root, "textbox", en.editor.name)));
});

test("Delete shows only once the program is stored", async () => {
  const fresh = newFake();
  let root = await openEditor(fresh, "#/programs/new/empty");
  expect(queryByRole(root, "button", { name: en.editor.delete })).toBeNull();
  rename(root, "Morning");
  await save(root, fresh);
  expect(await findByRole(root, "button", { name: en.editor.delete })).toBeTruthy();
  unmount();

  root = await openEditor(newFake({ programs: [fullBody()] }), "#/programs/new/copy/1");
  expect(queryByRole(root, "button", { name: en.editor.delete })).toBeNull();
  unmount();

  root = await openEditor(newFake({ programs: [fullBody()] }), "#/programs/1");
  expect(getByRole(root, "button", { name: en.editor.delete })).toBeTruthy();
});

test("Not saved shows while there are changes, and Saved right after a save", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");

  expect(queryByRole(root, "status")).toBeNull();
  rename(root, "Changed");
  expect(await within(root).findByText(en.editor.not_saved)).toBeTruthy();
  await save(root, fake);
  await vi.waitFor(() => expect(text(getByRole(root, "status"))).toBe(en.editor.saved));
  expect(within(root).queryByText(en.editor.not_saved)).toBeNull();
});

test("+ and − step the timing: rounds by 1, the seconds by 5, and − stops at 0", async () => {
  const fake = newFake({ programs: [fullBody({ rounds: 5, work_seconds: 45, switch_seconds: 0, round_rest_seconds: 3 })] });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.click(stepper(root, "More rounds"));
  await shows(root, en.editor.rounds, "6");
  fireEvent.click(stepper(root, "Fewer rounds"));
  fireEvent.click(stepper(root, "Fewer rounds"));
  await shows(root, en.editor.rounds, "4");
  fireEvent.click(stepper(root, "More work"));
  await shows(root, en.editor.work, "50");
  fireEvent.click(stepper(root, "Less work"));
  fireEvent.click(stepper(root, "Less work"));
  await shows(root, en.editor.work, "40");
  fireEvent.click(stepper(root, "Shorter break"));
  await shows(root, en.editor.switch, "0");
  fireEvent.click(stepper(root, "Longer break"));
  await shows(root, en.editor.switch, "5");
  fireEvent.click(stepper(root, "Shorter rest"));
  await shows(root, en.editor.round_rest, "0");
  fireEvent.click(stepper(root, "Longer rest"));
  await shows(root, en.editor.round_rest, "5");
  expect(await within(root).findByText(en.editor.not_saved)).toBeTruthy();

  await save(root, fake);
  expect(lastWrite(fake).body).toMatchObject({ rounds: 4, work_seconds: 40, switch_seconds: 5, round_rest_seconds: 5 });
});

test("on an emptied field + and − set the add-on's default, and an empty field is sent as null", async () => {
  const fake = newFake({ programs: [fullBody({ work_seconds: 30, round_rest_seconds: 20 })] });
  const root = await openEditor(fake, "#/programs/1");

  fireEvent.input(field(root, "spinbutton", en.editor.work), { target: { value: "" } });
  fireEvent.click(stepper(root, "More work"));
  await shows(root, en.editor.work, "45");
  fireEvent.input(field(root, "spinbutton", en.editor.round_rest), { target: { value: "" } });
  fireEvent.click(stepper(root, "Shorter rest"));
  await shows(root, en.editor.round_rest, "60");

  fireEvent.input(field(root, "spinbutton", en.editor.switch), { target: { value: "" } });
  await save(root, fake);
  expect(lastWrite(fake).body).toMatchObject({ work_seconds: 45, switch_seconds: null, round_rest_seconds: 60 });
});

test("with the defaults read failing, + and − on an emptied field set 0", async () => {
  const fake = newFake({ programs: [fullBody()] });
  fake.answer("GET", "api/v1/programs/defaults", 503, { detail: "No defaults", code: "", field: null });
  const root = await openEditor(fake, "#/programs/new/copy/1");

  fireEvent.input(field(root, "spinbutton", en.editor.work), { target: { value: "" } });
  fireEvent.click(stepper(root, "More work"));
  await shows(root, en.editor.work, "0");
  fireEvent.input(field(root, "spinbutton", en.editor.rounds), { target: { value: "" } });
  fireEvent.click(stepper(root, "Fewer rounds"));
  await shows(root, en.editor.rounds, "0");
});

test("the timing's title row shows the total, and Countdown is still a choice of 0, 5 and 10 s", async () => {
  const fake = newFake({
    programs: [
      fullBody({
        stations: ["0001", "0002", "0003", "0005", "0006"].map((exercise) => ({ exercise })),
        rounds: 5,
        work_seconds: 45,
        switch_seconds: 15,
        round_rest_seconds: 60,
      }),
    ],
  });
  const root = await openEditor(fake, "#/programs/1");

  expect(await within(root).findByText("29 min in all · 5 rounds × 5 exercises")).toBeTruthy();
  fireEvent.click(stepper(root, "Fewer rounds"));
  fireEvent.click(stepper(root, "Fewer rounds"));
  fireEvent.click(stepper(root, "Fewer rounds"));
  fireEvent.click(stepper(root, "Fewer rounds"));
  expect(await within(root).findByText("5 min in all · 1 round × 5 exercises")).toBeTruthy();

  const countdown = field(root, "combobox", en.editor.countdown);
  expect(within(countdown).getAllByRole("option").map(text)).toEqual(["0 s", "5 s", "10 s"]);
});
