import { findByRole, fireEvent, getByRole, queryByRole, within } from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import type { ExerciseSummary, PeopleView, Setup } from "../src/api";
import en from "../src/i18n/en.json";
import "../src/main";
import { fakeApi, type FakeApi } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
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

function chip(root: HTMLElement, name: string): HTMLButtonElement {
  return within(region(root, en.setup.equipment)).getByRole("button", { name }) as HTMLButtonElement;
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

test("the equipment chips are every equipment of the exercises, the stored ones pressed", async () => {
  const root = await openSetup(newFake());

  const chips = within(region(root, en.setup.equipment)).getAllByRole("button");
  expect(chips.map(text)).toEqual(["body weight", "band", "cable", "dumbbell", "kettlebell", "sofa"]);
  expect(chip(root, "dumbbell").getAttribute("aria-pressed")).toBe("true");
  expect(chip(root, "kettlebell").getAttribute("aria-pressed")).toBe("false");
  expect(chip(root, "band").getAttribute("aria-pressed")).toBe("false");
});

test("body weight is always on and can't be turned off", async () => {
  const fake = newFake({ setup: { ...structuredClone(SETUP), equipment: [] } });
  const root = await openSetup(fake);

  const bodyWeight = chip(root, "body weight");
  expect(bodyWeight.getAttribute("aria-pressed")).toBe("true");
  expect(bodyWeight.disabled).toBe(true);
  fireEvent.click(bodyWeight);
  save(root);

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect((writes(fake, "api/v1/setup")[0].body as Setup).equipment).toContain("body weight");
});

test("the band chip stores both band and resistance band, and turning it off removes both", async () => {
  const fake = newFake();
  const root = await openSetup(fake);

  fireEvent.click(chip(root, "band"));
  await vi.waitFor(() => expect(chip(root, "band").getAttribute("aria-pressed")).toBe("true"));
  await saveAndWait(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  expect([...(writes(fake, "api/v1/setup")[0].body as Setup).equipment].sort()).toEqual([
    "band",
    "body weight",
    "dumbbell",
    "resistance band",
  ]);

  fireEvent.click(chip(root, "band"));
  await vi.waitFor(() => expect(chip(root, "band").getAttribute("aria-pressed")).toBe("false"));
  save(root);
  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(2));
  expect([...(writes(fake, "api/v1/setup")[1].body as Setup).equipment].sort()).toEqual(["body weight", "dumbbell"]);
});

test("with only one of the band names among the exercises, the band chip sends that one", async () => {
  const fake = newFake({ exercises: EXERCISES.filter((exercise) => exercise.equipment !== "band") });
  const root = await openSetup(fake);

  fireEvent.click(chip(root, "band"));
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

  save(root);
  fireEvent.click(chip(root, "kettlebell"));

  await vi.waitFor(() => expect(writes(fake, "api/v1/setup")).toHaveLength(1));
  const saveButton = getByRole(root, "button", { name: en.setup.save });
  await vi.waitFor(() => expect(saveButton.hasAttribute("disabled")).toBe(false));
  expect(chip(root, "kettlebell").getAttribute("aria-pressed")).toBe("true");
  expect(queryByRole(root, "status")).toBeNull();
});

test("a stored resistance band alone shows the band chip pressed", async () => {
  const fake = newFake({ setup: { ...structuredClone(SETUP), equipment: ["body weight", "resistance band"] } });
  const root = await openSetup(fake);

  expect(chip(root, "band").getAttribute("aria-pressed")).toBe("true");
});

test("Save sends the setup's equipment, favourites and default speaker, and only the setup", async () => {
  const fake = newFake();
  const root = await openSetup(fake);

  fireEvent.click(chip(root, "kettlebell"));
  fireEvent.click(chip(root, "dumbbell"));
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

  fireEvent.click(chip(root, "cable"));
  save(root);

  const equipment = region(root, en.setup.equipment);
  expect(text(await within(equipment).findByRole("alert"))).toBe("Unknown equipment: cable");
  expect(chip(root, "cable").getAttribute("aria-pressed")).toBe("true");
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

  fireEvent.click(within(playlists).getByRole("button", { name: "Remove Workout Mix" }));
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
  fireEvent.click(chip(root, "kettlebell"));
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

  fireEvent.click(within(people).getByRole("button", { name: "Remove Elin" }));
  const dialog = await findByRole(root, "dialog", { name: "Remove “Elin”?" });
  expect(within(dialog).getByText(en.setup.remove_stats)).toBeTruthy();
  expect(within(dialog).getByText(en.setup.remove_sensors)).toBeTruthy();
  expect(within(dialog).getByText(en.setup.remove_new)).toBeTruthy();

  fireEvent.click(within(dialog).getByRole("button", { name: en.dialog.cancel }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
  expect(peopleNames(root)).toEqual(["Thomas", "Elin"]);

  fireEvent.click(within(people).getByRole("button", { name: "Remove Elin" }));
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

  expect(text(await within(people).findByRole("alert"))).toBe("Home Assistant can't be reached");
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
