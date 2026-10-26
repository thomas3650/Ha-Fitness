import { findByRole, fireEvent, getByPlaceholderText, getByRole, queryByRole, within } from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import type { ExerciseSummary, PeopleView, Setup } from "../src/api";
import en from "../src/i18n/en.json";
import "../src/main";
import { brokenAt, fakeApi, type FakeApi } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function summary(id: string, equipment: string | null, custom = false): ExerciseSummary {
  return { id, name: `exercise ${id}`, equipment, body_part: null, target: null, custom };
}

const EXERCISES: ExerciseSummary[] = [
  summary("0001", "body weight"),
  summary("0002", "dumbbell"),
  summary("0003", "kettlebell"),
  summary("0004", "band"),
  summary("0005", "resistance band"),
  summary("0006", "cable"),
  summary("0007", null),
  summary("custom-1", "sofa", true),
];

const THOMAS = { entity_id: "person.thomas", friendly_name: "Thomas" };
const ELIN = { entity_id: "person.elin", friendly_name: "Elin" };
const GUEST = { entity_id: "person.guest", friendly_name: "Guest" };

const PEOPLE: PeopleView = {
  people: [
    { id: 1, name: "Thomas", person_entity_id: THOMAS.entity_id },
    { id: 2, name: "Elin", person_entity_id: ELIN.entity_id },
  ],
  ha_persons: [THOMAS, ELIN, GUEST],
  ha_error: null,
};

const SETUP: Setup = {
  equipment: ["body weight", "dumbbell"],
  favourite_playlists: [{ uri: "library://playlist/1", name: "Workout Mix" }],
  default_speaker: "media_player.kitchen",
};

const KITCHEN = { entity_id: "media_player.kitchen", name: "Kitchen", available: true };
const LIVING = { entity_id: "media_player.living", name: "Living room", available: true };

function newFake(extra: Parameters<typeof fakeApi>[0] = {}): FakeApi {
  return fakeApi({
    exercises: EXERCISES,
    setup: structuredClone(SETUP),
    people: structuredClone(PEOPLE),
    speakers: [KITCHEN, LIVING],
    playlists: [
      { uri: "library://playlist/1", name: "Workout Mix" },
      { uri: "library://playlist/2", name: "Run 160 bpm" },
    ],
    ...extra,
  });
}

/** The name of a multi-select tag's remove button. */
function removeName(value: string): string {
  return en.multi_select.remove.replace("{value}", value);
}

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function writes(fake: FakeApi, path: string) {
  return fake.requests.filter((request) => request.method === "PUT" && request.path === path);
}

function region(root: HTMLElement, name: string): HTMLElement {
  return getByRole(root, "region", { name });
}

/** Open the Setup page and wait until it has read everything (it shows the page once every read answered). */
async function openSetup(fake: FakeApi): Promise<HTMLElement> {
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/setup");
  await findByRole(root, "button", { name: en.setup.save });
  return root;
}

/** The household equipment's multi-select: its parts are in its own shadow root. */
function equipment(root: HTMLElement): HTMLElement {
  const host = within(region(root, en.setup.equipment)).getByRole("group", { name: en.setup.equipment_have });
  return host.shadowRoot as unknown as HTMLElement;
}

/** Open the equipment list and return its options. */
async function options(root: HTMLElement): Promise<HTMLElement[]> {
  const select = equipment(root);
  fireEvent.click(getByRole(select, "combobox", { name: en.setup.equipment_have }));
  return within(await findByRole(select, "listbox", { name: en.setup.equipment_have })).getAllByRole("option");
}

async function option(root: HTMLElement, name: string): Promise<HTMLElement> {
  const found = (await options(root)).find((candidate) => text(candidate) === name);
  if (!found) throw new Error(`no option ${name}`);
  return found;
}

/** Choose an equipment, or take it off, through the combobox. */
async function toggle(root: HTMLElement, name: string): Promise<void> {
  fireEvent.click(await option(root, name));
}

async function chosen(root: HTMLElement, name: string): Promise<boolean> {
  return (await option(root, name)).getAttribute("aria-selected") === "true";
}

function save(root: HTMLElement): void {
  fireEvent.click(getByRole(root, "button", { name: en.setup.save }));
}

/** Save, and wait until the add-on's answer shows. */
async function saveAndWait(root: HTMLElement): Promise<void> {
  save(root);
  await findByRole(root, "status");
}

function savePeople(root: HTMLElement): void {
  fireEvent.click(within(region(root, en.setup.people)).getByRole("button", { name: en.setup.save_people }));
}

function peopleNames(root: HTMLElement): string[] {
  const list = within(region(root, en.setup.people)).getByRole("list", { name: en.setup.people });
  return within(list)
    .queryAllByRole("listitem")
    .map((item) => text(item));
}

function favouriteNames(root: HTMLElement): string[] {
  const list = within(region(root, en.setup.playlists)).queryByRole("list", { name: en.setup.playlists });
  return list
    ? within(list)
        .queryAllByRole("listitem")
        .map((item) => text(item))
    : [];
}

test("the equipment options are every equipment of the exercises, the stored ones chosen", async () => {
  const root = await openSetup(newFake());

  expect((await options(root)).map(text)).toEqual(["body weight", "band", "cable", "dumbbell", "kettlebell", "sofa"]);
  expect(await chosen(root, "dumbbell")).toBe(true);
  expect(await chosen(root, "kettlebell")).toBe(false);
  expect(await chosen(root, "band")).toBe(false);
  expect(getByRole(equipment(root), "button", { name: removeName("dumbbell") })).toBeTruthy();
  expect(getByPlaceholderText(equipment(root), en.setup.add_equipment)).toBeTruthy();
});

test("body weight is always on and can't be turned off", async () => {
  const fake = newFake({ setup: { ...structuredClone(SETUP), equipment: [] } });
  const root = await openSetup(fake);

  expect(await chosen(root, "body weight")).toBe(true);
  expect(queryByRole(equipment(root), "button", { name: removeName("body weight") })).toBeNull();
  await toggle(root, "body weight");
  expect(await chosen(root, "body weight")).toBe(true);
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect((writes(fake, "api/v1/setup")[0].body as Setup).equipment).toContain("body weight");
});

test("the band option stores both band and resistance band, and taking it off removes both", async () => {
  const fake = newFake();
  const root = await openSetup(fake);

  await toggle(root, "band");
  await vi.waitFor(async () => expect(await chosen(root, "band")).toBe(true));
  await saveAndWait(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect([...(writes(fake, "api/v1/setup")[0].body as Setup).equipment].sort()).toEqual([
    "band",
    "body weight",
    "dumbbell",
    "resistance band",
  ]);

  fireEvent.click(getByRole(equipment(root), "button", { name: removeName("band") }));
  await vi.waitFor(async () => expect(await chosen(root, "band")).toBe(false));
  save(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(2));
  expect([...(writes(fake, "api/v1/setup")[1].body as Setup).equipment].sort()).toEqual(["body weight", "dumbbell"]);
});

test("with only one of the band names among the exercises, the band option sends that one", async () => {
  const fake = newFake({ exercises: EXERCISES.filter((exercise) => exercise.equipment !== "band") });
  const root = await openSetup(fake);

  await toggle(root, "band");
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect((writes(fake, "api/v1/setup")[0].body as Setup).equipment).toEqual([
    "body weight",
    "dumbbell",
    "resistance band",
  ]);
});

test("a change made while the setup saves stays, unsaved", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const kettlebell = await option(root, "kettlebell");

  save(root);
  fireEvent.click(kettlebell);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  const saveButton = getByRole(root, "button", { name: en.setup.save });
  await vi.waitFor(() => expect(saveButton.hasAttribute("disabled")).toBe(false));
  expect(await chosen(root, "kettlebell")).toBe(true);
  expect(queryByRole(root, "status")).toBeNull();
});

test("a stored resistance band alone shows the band option chosen", async () => {
  const fake = newFake({ setup: { ...structuredClone(SETUP), equipment: ["body weight", "resistance band"] } });
  const root = await openSetup(fake);

  expect(await chosen(root, "band")).toBe(true);
});

test("Save sends the setup's equipment, favourites and default speaker, and only the setup", async () => {
  const fake = newFake();
  const root = await openSetup(fake);

  await toggle(root, "kettlebell");
  await toggle(root, "dumbbell");
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect(writes(fake, "api/v1/setup")[0].body).toEqual({
    equipment: ["body weight", "kettlebell"],
    favourite_playlists: [{ uri: "library://playlist/1", name: "Workout Mix" }],
    default_speaker: "media_player.kitchen",
  });
  expect(writes(fake, "api/v1/people")).toHaveLength(0);
  expect(await findByRole(root, "status")).toBeTruthy();
  expect(text(getByRole(root, "status"))).toBe(en.setup.saved);
});

test("the add-on's equipment refusal shows at the equipment, and the choice stays", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  fake.answer("PUT", "api/v1/setup", 422, {
    detail: "Unknown equipment: cable",
    code: "equipment_unknown",
    field: "equipment",
  });

  await toggle(root, "cable");
  save(root);

  const equipment = region(root, en.setup.equipment);
  expect(text(await within(equipment).findByRole("alert"))).toBe("Unknown equipment: cable");
  expect(await chosen(root, "cable")).toBe(true);
});

test("a refusal without a field shows above the setup", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  fake.answer("PUT", "api/v1/setup", 500, { detail: "Something broke", code: "", field: null });

  save(root);

  const alert = await findByRole(root, "alert");
  expect(text(alert)).toBe("Something broke");
  expect(within(region(root, en.setup.equipment)).queryByRole("alert")).toBeNull();
});

test("a favourite playlist is added from Music Assistant's playlists and another removed", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const playlists = region(root, en.setup.playlists);
  expect(favouriteNames(root)).toEqual(["Workout Mix"]);

  const add = within(playlists).getByRole("combobox", { name: en.setup.add_playlist }) as HTMLSelectElement;
  expect(within(add).getAllByRole("option").map(text)).toEqual([en.setup.choose_playlist, "Run 160 bpm"]);
  fireEvent.change(add, { target: { value: "library://playlist/2" } });
  await vi.waitFor(() => expect(favouriteNames(root)).toEqual(["Workout Mix", "Run 160 bpm"]));

  fireEvent.click(within(playlists).getByRole("button", { name: en.setup.remove.replace("{name}", "Workout Mix") }));
  await vi.waitFor(() => expect(favouriteNames(root)).toEqual(["Run 160 bpm"]));
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect((writes(fake, "api/v1/setup")[0].body as Setup).favourite_playlists).toEqual([
    { uri: "library://playlist/2", name: "Run 160 bpm" },
  ]);
});

test("the default speaker is chosen from Music Assistant's speakers, or none", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const speaker = within(region(root, en.setup.speaker)).getByRole("combobox", {
    name: en.setup.speaker,
  }) as HTMLSelectElement;
  await vi.waitFor(() => expect(speaker.value).toBe("media_player.kitchen"));
  expect(within(speaker).getAllByRole("option").map(text)).toEqual([en.setup.no_speaker, "Kitchen", "Living room"]);

  fireEvent.change(speaker, { target: { value: "media_player.living" } });
  await saveAndWait(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect((writes(fake, "api/v1/setup")[0].body as Setup).default_speaker).toBe("media_player.living");

  fireEvent.change(speaker, { target: { value: "" } });
  save(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(2));
  expect((writes(fake, "api/v1/setup")[1].body as Setup).default_speaker).toBeNull();
});

test("music reads that fail say so, and the rest of the setup still saves", async () => {
  const fake = newFake();
  const unavailable = { detail: "Music Assistant can't be reached", code: "", field: null };
  fake.answer("GET", "api/v1/music/speakers", 503, unavailable);
  fake.answer("GET", "api/v1/music/playlists", 503, unavailable);
  const root = await openSetup(fake);

  expect(within(region(root, en.setup.speaker)).getByText("Music Assistant can't be reached")).toBeTruthy();
  expect(within(region(root, en.setup.playlists)).getByText("Music Assistant can't be reached")).toBeTruthy();
  // The stored speaker and favourites are still shown and kept.
  expect(favouriteNames(root)).toEqual(["Workout Mix"]);
  await toggle(root, "kettlebell");
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect(writes(fake, "api/v1/setup")[0].body).toEqual({
    equipment: ["body weight", "dumbbell", "kettlebell"],
    favourite_playlists: [{ uri: "library://playlist/1", name: "Workout Mix" }],
    default_speaker: "media_player.kitchen",
  });
});

test("empty music lists say so", async () => {
  const root = await openSetup(newFake({ speakers: [], playlists: [] }));

  expect(within(region(root, en.setup.speaker)).getByText(en.setup.no_speakers)).toBeTruthy();
  expect(within(region(root, en.setup.playlists)).getByText(en.setup.no_playlists)).toBeTruthy();
});

test("a setup that can't be read is not offered for saving", async () => {
  const fake = newFake();
  fake.answer("GET", "api/v1/setup", 503, { detail: "The setup can't be read", code: "", field: null });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/setup");

  expect(text(await findByRole(root, "alert"))).toBe("The setup can't be read");
  expect(queryByRole(root, "button", { name: en.setup.save })).toBeNull();
  // The people don't depend on the setup.
  expect(await within(region(root, en.setup.people)).findByText("Thomas")).toBeTruthy();
});

test("people are listed in order, reordered, added and saved on their own", async () => {
  const fake = newFake({
    people: { ...structuredClone(PEOPLE), people: [{ id: 1, name: "Thomas", person_entity_id: THOMAS.entity_id }] },
  });
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);
  expect(peopleNames(root)).toEqual(["Thomas"]);

  const add = within(people).getByRole("combobox", { name: en.setup.add_person });
  expect(within(add).getAllByRole("option").map(text)).toEqual([en.setup.choose_person, "Elin", "Guest"]);
  fireEvent.change(add, { target: { value: ELIN.entity_id } });
  await vi.waitFor(() => expect(peopleNames(root)).toEqual(["Thomas", "Elin"]));

  fireEvent.click(within(people).getByRole("button", { name: "Move Elin up" }));
  await vi.waitFor(() => expect(peopleNames(root)).toEqual(["Elin", "Thomas"]));
  savePeople(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/people")).toHaveLength(1));
  expect(writes(fake, "api/v1/people")[0].body).toEqual({
    people: [
      { name: "Elin", person_entity_id: ELIN.entity_id },
      { name: "Thomas", person_entity_id: THOMAS.entity_id },
    ],
  });
  expect(writes(fake, "api/v1/setup")).toHaveLength(0);
  expect(text(await within(people).findByRole("status"))).toBe(en.setup.people_saved);
});

test("a third person is sent, and the add-on's refusal is shown", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);
  fake.answer("PUT", "api/v1/people", 422, {
    detail: "At most 2 people, got 3",
    code: "too_many_people",
    field: "people",
  });

  fireEvent.change(within(people).getByRole("combobox", { name: en.setup.add_person }), {
    target: { value: GUEST.entity_id },
  });
  await vi.waitFor(() => expect(peopleNames(root)).toEqual(["Thomas", "Elin", "Guest"]));
  savePeople(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/people")).toHaveLength(1));
  expect((writes(fake, "api/v1/people")[0].body as { people: unknown[] }).people).toHaveLength(3);
  expect(text(await within(people).findByRole("alert"))).toBe("At most 2 people, got 3");
  expect(peopleNames(root)).toEqual(["Thomas", "Elin", "Guest"]);
});

test("removing a person asks first and says what it means", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);

  fireEvent.click(within(people).getByRole("button", { name: en.setup.remove.replace("{name}", "Elin") }));
  const dialog = await findByRole(root, "dialog", { name: en.setup.remove_title.replace("{name}", "Elin") });
  expect(within(dialog).getByText(en.setup.remove_stats)).toBeTruthy();
  expect(within(dialog).getByText(en.setup.remove_sensors)).toBeTruthy();
  expect(within(dialog).getByText(en.setup.remove_new)).toBeTruthy();

  fireEvent.click(within(dialog).getByRole("button", { name: en.dialog.cancel }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(peopleNames(root)).toEqual(["Thomas", "Elin"]);

  fireEvent.click(within(people).getByRole("button", { name: en.setup.remove.replace("{name}", "Elin") }));
  fireEvent.click(within(await findByRole(root, "dialog")).getByRole("button", { name: en.setup.remove_confirm }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(peopleNames(root)).toEqual(["Thomas"]);
  savePeople(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/people")).toHaveLength(1));
  expect(writes(fake, "api/v1/people")[0].body).toEqual({
    people: [{ name: "Thomas", person_entity_id: THOMAS.entity_id }],
  });
});

test("Home Assistant unreachable on saving people shows the message and keeps the choice", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);
  fake.answer("PUT", "api/v1/people", 503, {
    detail: "Home Assistant can't be reached",
    code: "ha_unavailable",
    field: null,
  });

  fireEvent.click(within(people).getByRole("button", { name: "Move Elin up" }));
  await vi.waitFor(() => expect(peopleNames(root)).toEqual(["Elin", "Thomas"]));
  savePeople(root);

  const alert = await within(people).findByRole("alert");
  expect(text(alert)).toBe("Home Assistant can't be reached");
  // A refusal without a field shows above the people, not below them.
  const list = within(people).getByRole("list", { name: en.setup.people });
  expect(alert.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(peopleNames(root)).toEqual(["Elin", "Thomas"]);

  fake.restore("PUT", "api/v1/people");
  savePeople(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/people")).toHaveLength(2));
  expect(writes(fake, "api/v1/people")[1].body).toEqual(writes(fake, "api/v1/people")[0].body);
  await vi.waitFor(() => expect(within(people).queryByRole("alert")).toBeNull());
});

test("when Home Assistant's persons can't be read, the stored people show and the page says why", async () => {
  const fake = newFake({ people: { ...structuredClone(PEOPLE), ha_persons: null, ha_error: "HA is restarting" } });
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);

  expect(peopleNames(root)).toEqual(["Thomas", "Elin"]);
  expect(within(people).getByText("HA is restarting")).toBeTruthy();
});

test("people that can't be read can't be saved, so no empty list is ever sent", async () => {
  const fake = newFake();
  fake.answer("GET", "api/v1/people", 500, { detail: "The people can't be read", code: "", field: null });
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);

  expect(within(people).getByText("The people can't be read")).toBeTruthy();
  expect(within(people).queryByRole("button", { name: en.setup.save_people })).toBeNull();
  expect(within(people).queryByRole("combobox", { name: en.setup.add_person })).toBeNull();
  expect(within(people).queryByText(en.setup.no_people)).toBeNull();
  expect(writes(fake, "api/v1/people")).toHaveLength(0);
});

test("a person Home Assistant doesn't know is refused, and the add-on's message shows", async () => {
  const fake = newFake();
  const root = await openSetup(fake);
  const people = region(root, en.setup.people);
  fake.answer("PUT", "api/v1/people", 422, {
    detail: {
      message: "'person.guest' isn't a person in Home Assistant",
      entity_id: GUEST.entity_id,
      ha_persons: [THOMAS, ELIN],
    },
    code: "person_unknown",
    field: "people",
  });

  fireEvent.click(within(people).getByRole("button", { name: "Move Elin up" }));
  savePeople(root);

  expect(text(await within(people).findByRole("alert"))).toBe("'person.guest' isn't a person in Home Assistant");
});

test("a setup read that fails with a bug shows the generic message and logs the bug", async () => {
  const logged = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", brokenAt(newFake(), "api/v1/setup"));
  const root = await mount("#/setup");

  expect(text(await findByRole(root, "alert"))).toBe(en.error.unexpected);
  expect(logged).toHaveBeenCalledWith(expect.any(TypeError));
});
