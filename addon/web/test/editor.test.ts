import { findByRole, fireEvent, getByRole, queryByRole, within } from "@testing-library/dom";
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
    .map((item) => within(item).getByRole("button", { name: /^Remove / }).getAttribute("aria-label") ?? "")
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

test("the panel shows the household's exercises by default, and Show all shows the rest", async () => {
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

  fireEvent.click(within(panel(root)).getByRole("checkbox", { name: en.picker.show_all }));
  await vi.waitFor(() => expect(panelNames(root)).toContain("cable row"));
});

test("the panel searches by name and filters", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("squat"));
  fireEvent.click(within(panel(root)).getByRole("checkbox", { name: en.picker.show_all }));

  fireEvent.input(within(panel(root)).getByRole("searchbox", { name: en.picker.search }), {
    target: { value: "squat" },
  });
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["squat", "goblet squat"]));

  fireEvent.input(within(panel(root)).getByRole("searchbox", { name: en.picker.search }), {
    target: { value: "" },
  });
  fireEvent.change(within(panel(root)).getByRole("combobox", { name: en.picker.body_part }), {
    target: { value: "back" },
  });
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["cable row", "dumbbell row"]));

  fireEvent.change(within(panel(root)).getByRole("combobox", { name: en.picker.equipment }), {
    target: { value: "cable" },
  });
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["cable row"]));

  fireEvent.change(within(panel(root)).getByRole("combobox", { name: en.picker.body_part }), {
    target: { value: "" },
  });
  fireEvent.change(within(panel(root)).getByRole("combobox", { name: en.picker.equipment }), {
    target: { value: "" },
  });
  fireEvent.change(within(panel(root)).getByRole("combobox", { name: en.picker.target }), {
    target: { value: "quads" },
  });
  await vi.waitFor(() => expect(panelNames(root)).toEqual(["squat", "goblet squat"]));
});

test("✓ marks the exercises already in the program", async () => {
  const fake = newFake({ programs: [fullBody()] });
  const root = await openEditor(fake, "#/programs/1");
  await vi.waitFor(() => expect(panelNames(root)).toContain("push-up"));

  const list = within(panel(root)).getByRole("list", { name: en.picker.results });
  const pushUp = within(list)
    .getAllByRole("listitem")
    .find((item) => text(within(item).getAllByRole("button")[0]) === "push-up");
  expect(pushUp).toBeTruthy();
  expect(within(pushUp!).getByRole("img", { name: en.picker.in_program })).toBeTruthy();
  expect(within(pushUp!).queryByRole("button", { name: "Add push-up" })).toBeNull();
  expect(within(panel(root)).getByRole("button", { name: "Add goblet squat" })).toBeTruthy();
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
  expect(within(root).getByText("23 min")).toBeTruthy();
  expect(within(root).getByText("Equipment: dumbbell, cable")).toBeTruthy();
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
