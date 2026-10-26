import { findByRole, fireEvent, getByRole, queryByRole, queryByText, within } from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import type { Exercise, ExerciseSummary } from "../src/api";
import en from "../src/i18n/en.json";
import "../src/main";
import { fakeApi, type FakeApi } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
});

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
  summary("0007", "mystery move", null, "waist", "abs"),
  summary("custom-1", "towel slide", null, null, null, true),
  summary("custom-2", "sofa dips", "sofa", "upper arms", "triceps", true),
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

function newFake(extra: Parameters<typeof fakeApi>[0] = {}): FakeApi {
  return fakeApi({
    exercises: EXERCISES,
    setup: { equipment: ["body weight", "dumbbell"], favourite_playlists: [], default_speaker: null },
    ...extra,
  });
}

function table(root: HTMLElement): HTMLElement {
  return getByRole(root, "table", { name: en.library.results });
}

function rows(root: HTMLElement): HTMLElement[] {
  const found = queryByRole(root, "table", { name: en.library.results });
  return found ? within(found).getAllByRole("row").slice(1) : [];
}

/** The names of the exercises in the table, in order. */
function names(root: HTMLElement): string[] {
  return rows(root).map((row) => text(within(row).getAllByRole("button")[0]));
}

function rowOf(root: HTMLElement, name: string): HTMLElement {
  const row = rows(root).find((candidate) => text(within(candidate).getAllByRole("button")[0]) === name);
  if (!row) throw new Error(`no row ${name}`);
  return row;
}

/** Open the Library page and wait until the table shows. */
async function openLibrary(fake: FakeApi): Promise<HTMLElement> {
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/library");
  await findByRole(root, "table", { name: en.library.results });
  return root;
}

function group(root: HTMLElement, name: string): HTMLElement {
  return getByRole(root, "group", { name });
}

function toggle(root: HTMLElement, facet: string, value: string): void {
  fireEvent.click(within(group(root, facet)).getByRole("button", { name: value }));
}

function showAll(root: HTMLElement): void {
  fireEvent.click(getByRole(root, "checkbox", { name: en.library.show_all }));
}

test("the Library page shows the household's exercises by default, and Show all shows the rest", async () => {
  const fake = newFake();
  const root = await openLibrary(fake);

  await vi.waitFor(() => expect(names(root)).toContain("goblet squat"));
  expect(names(root)).toEqual(
    expect.arrayContaining(["push-up", "squat", "goblet squat", "dumbbell row", "plank", "towel slide", "sofa dips"]),
  );
  expect(names(root)).not.toContain("cable row");
  // A library exercise without equipment is not one the household is known to have.
  expect(names(root)).not.toContain("mystery move");
  const checkbox = getByRole(root, "checkbox", { name: en.library.show_all }) as HTMLInputElement;
  expect(checkbox.checked).toBe(false);

  showAll(root);
  await vi.waitFor(() => expect(names(root)).toContain("cable row"));
  expect(names(root)).toContain("mystery move");
  expect(names(root)).toHaveLength(EXERCISES.length);
  const paths = fake.requests.map((request) => `${request.method} ${request.path}`);
  expect(paths).toEqual(expect.arrayContaining(["GET api/v1/exercises/all", "GET api/v1/setup"]));
});

test("body weight is always in the household, and custom exercises always show", async () => {
  const fake = newFake({ setup: { equipment: ["dumbbell"], favourite_playlists: [], default_speaker: null } });
  const root = await openLibrary(fake);

  await vi.waitFor(() => expect(names(root)).toContain("plank"));
  expect(names(root)).toEqual(
    expect.arrayContaining(["push-up", "squat", "plank", "goblet squat", "dumbbell row", "towel slide", "sofa dips"]),
  );
  expect(names(root)).not.toContain("cable row");
});

test("the search finds exercises by name, names that start with it first", async () => {
  const root = await openLibrary(newFake());
  showAll(root);

  fireEvent.input(getByRole(root, "searchbox", { name: en.library.search }), { target: { value: "squat" } });
  await vi.waitFor(() => expect(names(root)).toEqual(["squat", "goblet squat"]));

  fireEvent.input(getByRole(root, "searchbox", { name: en.library.search }), { target: { value: "row dumb" } });
  await vi.waitFor(() => expect(names(root)).toEqual(["dumbbell row"]));

  fireEvent.input(getByRole(root, "searchbox", { name: en.library.search }), { target: { value: "nothing like it" } });
  await vi.waitFor(() => expect(names(root)).toEqual([]));
  expect(getByRole(root, "status")).toBeTruthy();
  expect(text(getByRole(root, "status"))).toContain(en.library.none);
});

test("the filters offer every value as the dataset names it", async () => {
  const root = await openLibrary(newFake());

  const values = (name: string) =>
    within(group(root, name))
      .getAllByRole("button")
      .map(text);
  expect(values(en.library.equipment)).toEqual(["body weight", "cable", "dumbbell", "sofa"]);
  expect(values(en.library.body_part)).toEqual(["back", "chest", "upper arms", "upper legs", "waist"]);
  expect(values(en.library.target)).toEqual(["abs", "lats", "pectorals", "quads", "triceps"]);
  // The rows show the values as they are too.
  const row = rowOf(root, "push-up");
  expect(within(row).getByText("body weight")).toBeTruthy();
  expect(within(row).getByText("chest")).toBeTruthy();
  expect(within(row).getByText("pectorals")).toBeTruthy();
});

test("several values in one filter show either, and a second filter narrows them", async () => {
  const root = await openLibrary(newFake());
  showAll(root);

  toggle(root, en.library.body_part, "back");
  await vi.waitFor(() => expect(names(root)).toEqual(["cable row", "dumbbell row"]));
  expect(
    within(group(root, en.library.body_part)).getByRole("button", { name: "back", pressed: true }),
  ).toBeTruthy();

  toggle(root, en.library.body_part, "upper legs");
  await vi.waitFor(() => expect(names(root).sort()).toEqual(["cable row", "dumbbell row", "goblet squat", "squat"]));

  toggle(root, en.library.equipment, "dumbbell");
  await vi.waitFor(() => expect(names(root).sort()).toEqual(["dumbbell row", "goblet squat"]));

  toggle(root, en.library.equipment, "cable");
  await vi.waitFor(() => expect(names(root).sort()).toEqual(["cable row", "dumbbell row", "goblet squat"]));

  toggle(root, en.library.target, "quads");
  await vi.waitFor(() => expect(names(root)).toEqual(["goblet squat"]));
  toggle(root, en.library.target, "lats");
  await vi.waitFor(() => expect(names(root).sort()).toEqual(["cable row", "dumbbell row", "goblet squat"]));

  // A second click takes a value off again.
  toggle(root, en.library.body_part, "back");
  await vi.waitFor(() => expect(names(root)).toEqual(["goblet squat"]));
  expect(
    within(group(root, en.library.body_part)).getByRole("button", { name: "back", pressed: false }),
  ).toBeTruthy();
});

test("the filters and the household filter work together", async () => {
  const root = await openLibrary(newFake());

  toggle(root, en.library.body_part, "back");
  await vi.waitFor(() => expect(names(root)).toEqual(["dumbbell row"]));

  showAll(root);
  await vi.waitFor(() => expect(names(root)).toEqual(["cable row", "dumbbell row"]));
});

test("a custom exercise is marked as custom", async () => {
  const root = await openLibrary(newFake());

  expect(within(rowOf(root, "towel slide")).getByText(en.library.custom)).toBeTruthy();
  expect(within(rowOf(root, "push-up")).queryByText(en.library.custom)).toBeNull();
});

test("thumbnails load lazily, and a missing one shows a placeholder", async () => {
  const root = await openLibrary(newFake());

  const row = rowOf(root, "push-up");
  // The thumbnail is decorative (the name is beside it), so it has no name.
  const thumb = within(row).getByRole("presentation");
  expect(thumb.getAttribute("loading")).toBe("lazy");
  expect(thumb.getAttribute("src")).toBe("api/v1/exercises/0001/thumbnail");

  fireEvent.error(thumb);
  await vi.waitFor(() => expect(within(rowOf(root, "push-up")).queryByRole("presentation")).toBeNull());
  expect(within(rowOf(root, "push-up")).getByRole("img", { name: en.library.no_thumbnail })).toBeTruthy();
  // The other rows keep their thumbnails.
  expect(within(rowOf(root, "squat")).getByRole("presentation")).toBeTruthy();
  expect(within(rowOf(root, "squat")).queryByRole("img", { name: en.library.no_thumbnail })).toBeNull();
});

test("a click on an exercise opens its details, without Add to program, and Close closes them", async () => {
  const fake = newFake({ details: { "0003": GOBLET } });
  const root = await openLibrary(fake);

  fireEvent.click(within(table(root)).getByRole("button", { name: "goblet squat" }));

  const dialog = await findByRole(root, "dialog", { name: "goblet squat" });
  const gif = await within(dialog).findByRole("img", { name: "goblet squat" });
  expect(gif.getAttribute("src")).toBe("api/v1/exercises/0003/gif");
  expect(await within(dialog).findByText("Gym visual, test attribution")).toBeTruthy();
  expect(within(dialog).getByText("Target: quads")).toBeTruthy();
  expect(within(dialog).getByText("Also: calves, core")).toBeTruthy();
  expect(within(dialog).getByText("Squat down and stand up again.")).toBeTruthy();
  expect(within(dialog).queryByRole("button", { name: en.details.add })).toBeNull();
  expect(fake.requests.map((request) => request.path)).toContain("api/v1/exercises/0003");

  fireEvent.click(within(dialog).getByRole("button", { name: en.details.close }));
  await vi.waitFor(() => expect(queryByRole(root, "dialog")).toBeNull());
});

test("the page counts the exercises it shows", async () => {
  const root = await openLibrary(newFake());

  expect(getByRole(root, "heading", { level: 1, name: en.library.title })).toBeTruthy();
  showAll(root);
  await vi.waitFor(() => expect(queryByText(root, `${EXERCISES.length} exercises`)).toBeTruthy());
});

test("a refused read of the exercises shows the add-on's message instead of loading forever", async () => {
  const fake = newFake();
  fake.answer("GET", "api/v1/exercises/all", 503, {
    detail: "The library isn't loaded",
    code: "unavailable",
    field: null,
  });
  vi.stubGlobal("fetch", fake.fetch);
  const root = await mount("#/library");

  const alert = await findByRole(root, "alert");
  expect(text(alert)).toContain("The library isn't loaded");
  expect(queryByText(root, en.library.loading)).toBeNull();
});

test("a refused read of the setup says so; the household is then body weight and the custom exercises", async () => {
  const fake = newFake();
  fake.answer("GET", "api/v1/setup", 503, { detail: "The setup can't be read", code: "unavailable", field: null });
  const root = await openLibrary(fake);

  expect(text(await findByRole(root, "alert"))).toContain("The setup can't be read");
  await vi.waitFor(() => expect(names(root)).toContain("push-up"));
  expect(names(root)).toContain("towel slide");
  expect(names(root)).not.toContain("goblet squat");
  showAll(root);
  await vi.waitFor(() => expect(names(root)).toContain("goblet squat"));
});
