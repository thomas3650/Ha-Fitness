import { fireEvent, getByRole, queryByRole, within } from "@testing-library/dom";
import { afterEach, expect, test } from "vitest";

import { EquipmentFilter } from "../src/components/equipment-filter";
import en from "../src/i18n/en.json";
import type { EquipmentChoice } from "../src/library-filter";
import { unmount } from "./mount";

afterEach(() => {
  unmount();
});

const VALUES = ["band", "barbell", "body weight", "cable", "dumbbell", "kettlebell"];
const HOME = ["body weight", "kettlebell", "dumbbell"];

const MINE_NAME = "My equipment, body weight, dumbbell, kettlebell · 325";
const ALL_NAME = "All equipment, 1,324";

type Props = Partial<Pick<EquipmentFilter, "label" | "values" | "home" | "counts" | "choice">>;

/** Put an equipment filter in the page and return its shadow root and the choices its `change` events carry. */
async function place(props: Props = {}) {
  const element = new EquipmentFilter();
  Object.assign(element, {
    label: "Equipment",
    values: VALUES,
    home: HOME,
    counts: { mine: 325, all: 1324 },
    ...props,
  });
  const changes: EquipmentChoice[] = [];
  element.addEventListener("change", (event) =>
    changes.push((event as CustomEvent<{ choice: EquipmentChoice }>).detail.choice),
  );
  document.body.append(element);
  await element.updateComplete;
  const host = getByRole(document.body, "group", { name: "Equipment" });
  return { element, root: host.shadowRoot as unknown as HTMLElement, changes };
}

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function combobox(root: HTMLElement): HTMLInputElement {
  return getByRole(root, "combobox", { name: "Equipment" }) as HTMLInputElement;
}

function listbox(root: HTMLElement): HTMLElement | null {
  return queryByRole(root, "listbox", { name: "Equipment" });
}

function optionName(option: HTMLElement): string {
  return option.getAttribute("aria-label") ?? text(option);
}

/** The options' accessible names, in one group or in the whole list. */
function optionNames(root: HTMLElement, group?: string): string[] {
  const list = listbox(root);
  if (!list) return [];
  const scope = group ? queryByRole(list, "group", { name: group }) : list;
  return scope ? within(scope).queryAllByRole("option").map(optionName) : [];
}

function option(root: HTMLElement, name: string): HTMLElement {
  return getByRole(listbox(root) as HTMLElement, "option", { name });
}

function selected(root: HTMLElement, name: string): boolean {
  return option(root, name).getAttribute("aria-selected") === "true";
}

function tagList(root: HTMLElement): HTMLElement | null {
  return queryByRole(root, "list", { name: en.multi_select.chosen.replace("{label}", "Equipment") });
}

function tags(root: HTMLElement): string[] {
  const list = tagList(root);
  return list ? within(list).queryAllByRole("listitem").map(text) : [];
}

function removeName(value: string): string {
  return en.multi_select.remove.replace("{value}", value);
}

async function open(element: EquipmentFilter, root: HTMLElement): Promise<void> {
  fireEvent.click(combobox(root));
  await element.updateComplete;
}

async function key(element: EquipmentFilter, root: HTMLElement, name: string): Promise<void> {
  fireEvent.keyDown(combobox(root), { key: name });
  await element.updateComplete;
}

async function type(element: EquipmentFilter, root: HTMLElement, value: string): Promise<void> {
  fireEvent.input(combobox(root), { target: { value } });
  await element.updateComplete;
}

test("one listbox with the groups Show and Or pick equipment; the mode lines carry their kinds and counts", async () => {
  const { element, root } = await place();
  expect(combobox(root).getAttribute("aria-expanded")).toBe("false");
  expect(listbox(root)).toBeNull();

  await open(element, root);
  expect(combobox(root).getAttribute("aria-expanded")).toBe("true");
  const list = listbox(root) as HTMLElement;
  expect(list.getAttribute("aria-multiselectable")).toBe("true");
  expect(combobox(root).getAttribute("aria-controls")).toBe(list.id);
  expect(within(list).getAllByRole("group")).toHaveLength(2);
  expect(getByRole(list, "group", { name: en.equipment_filter.show })).toBeTruthy();
  expect(getByRole(list, "group", { name: en.equipment_filter.pick })).toBeTruthy();
  expect(optionNames(root, en.equipment_filter.show)).toEqual([MINE_NAME, ALL_NAME]);
  expect(selected(root, MINE_NAME)).toBe(true);
  expect(selected(root, ALL_NAME)).toBe(false);
});

test("kinds the household doesn't have are marked not at home, body weight never", async () => {
  const { element, root } = await place();
  await open(element, root);
  expect(optionNames(root, en.equipment_filter.pick)).toEqual([
    "band, not at home",
    "barbell, not at home",
    "body weight",
    "cable, not at home",
    "dumbbell",
    "kettlebell",
  ]);
  const kinds = getByRole(listbox(root) as HTMLElement, "group", { name: en.equipment_filter.pick });
  expect(
    within(kinds)
      .getAllByRole("option")
      .map((kind) => kind.getAttribute("aria-selected")),
  ).toEqual(VALUES.map(() => "false"));
});

test("without a setup, every kind but body weight is not at home, and band is at home with either name", async () => {
  const { element, root } = await place({ home: [] });
  await open(element, root);
  expect(optionNames(root, en.equipment_filter.pick)).toContain("body weight");
  expect(optionNames(root, en.equipment_filter.pick)).toContain("dumbbell, not at home");
  expect(optionNames(root, en.equipment_filter.show)[0]).toBe("My equipment, body weight · 325");

  unmount();
  const banded = await place({ home: ["resistance band"] });
  await open(banded.element, banded.root);
  expect(optionNames(banded.root, en.equipment_filter.pick)).toContain("band");
  expect(optionNames(banded.root, en.equipment_filter.show)[0]).toBe("My equipment, body weight, band · 325");
});

test("the default tag My equipment has no remove button", async () => {
  const { root } = await place();
  expect(tags(root)).toEqual([en.equipment_filter.mine]);
  expect(within(tagList(root) as HTMLElement).queryAllByRole("button")).toHaveLength(0);
});

test("choosing All equipment closes the list; its tag's remove goes back to My equipment", async () => {
  const { element, root, changes } = await place();
  await open(element, root);
  fireEvent.click(option(root, ALL_NAME));
  await element.updateComplete;
  expect(changes).toEqual([{ mode: "all" }]);
  expect(combobox(root).getAttribute("aria-expanded")).toBe("false");
  expect(tags(root)).toEqual([en.equipment_filter.all]);

  fireEvent.click(getByRole(tagList(root) as HTMLElement, "button", { name: removeName(en.equipment_filter.all) }));
  await element.updateComplete;
  expect(changes).toEqual([{ mode: "all" }, { mode: "mine" }]);
  expect(tags(root)).toEqual([en.equipment_filter.mine]);
});

test("choosing the mode that is already on emits nothing", async () => {
  const { element, root, changes } = await place();
  await open(element, root);
  fireEvent.click(option(root, MINE_NAME));
  await element.updateComplete;
  expect(changes).toEqual([]);

  unmount();
  const all = await place({ choice: { mode: "all" } });
  await open(all.element, all.root);
  fireEvent.click(option(all.root, ALL_NAME));
  await all.element.updateComplete;
  expect(all.changes).toEqual([]);
});

test("picking two kinds keeps the list open and emits them; a mode clears them", async () => {
  const { element, root, changes } = await place();
  await open(element, root);
  fireEvent.click(option(root, "cable, not at home"));
  await element.updateComplete;
  fireEvent.click(option(root, "barbell, not at home"));
  await element.updateComplete;
  expect(changes).toEqual([
    { mode: "picked", values: ["cable"] },
    { mode: "picked", values: ["barbell", "cable"] },
  ]);
  expect(combobox(root).getAttribute("aria-expanded")).toBe("true");
  expect(selected(root, "barbell, not at home")).toBe(true);
  expect(selected(root, "cable, not at home")).toBe(true);
  expect(selected(root, MINE_NAME)).toBe(false);
  expect(tags(root)).toEqual(["barbell", "cable"]);

  fireEvent.click(option(root, ALL_NAME));
  await element.updateComplete;
  expect(changes.at(-1)).toEqual({ mode: "all" });
  expect(tags(root)).toEqual([en.equipment_filter.all]);
});

test("removing the last picked kind goes back to My equipment, from its tag or from the list", async () => {
  const { element, root, changes } = await place({ choice: { mode: "picked", values: ["cable"] } });
  expect(tags(root)).toEqual(["cable"]);
  fireEvent.click(getByRole(tagList(root) as HTMLElement, "button", { name: removeName("cable") }));
  await element.updateComplete;
  expect(changes).toEqual([{ mode: "mine" }]);
  expect(tags(root)).toEqual([en.equipment_filter.mine]);

  unmount();
  const listed = await place({ choice: { mode: "picked", values: ["band"] } });
  await open(listed.element, listed.root);
  fireEvent.click(option(listed.root, "band, not at home"));
  await listed.element.updateComplete;
  expect(listed.changes).toEqual([{ mode: "mine" }]);
  expect(combobox(listed.root).getAttribute("aria-expanded")).toBe("true");
  expect(selected(listed.root, MINE_NAME)).toBe(true);
});

test("Backspace in the empty search removes the last picked kind, then goes back to My equipment, then does nothing", async () => {
  const { element, root, changes } = await place({ choice: { mode: "picked", values: ["barbell", "cable"] } });
  await key(element, root, "Backspace");
  expect(changes).toEqual([{ mode: "picked", values: ["barbell"] }]);
  await key(element, root, "Backspace");
  expect(changes.at(-1)).toEqual({ mode: "mine" });
  await key(element, root, "Backspace");
  expect(changes).toHaveLength(2);
  expect(tags(root)).toEqual([en.equipment_filter.mine]);
});

test("Backspace turns All equipment back into My equipment, but not while the search has text", async () => {
  const { element, root, changes } = await place({ choice: { mode: "all" } });
  await type(element, root, "ca");
  await key(element, root, "Backspace");
  expect(changes).toEqual([]);
  await type(element, root, "");
  await key(element, root, "Backspace");
  expect(changes).toEqual([{ mode: "mine" }]);
});

test("typing filters the kinds by name; the mode lines show only while their label matches", async () => {
  const { element, root } = await place();
  await type(element, root, "kettle");
  expect(optionNames(root)).toEqual(["kettlebell"]);
  expect(queryByRole(listbox(root) as HTMLElement, "group", { name: en.equipment_filter.show })).toBeNull();

  await type(element, root, "ALL");
  expect(optionNames(root)).toEqual([ALL_NAME]);
  expect(queryByRole(listbox(root) as HTMLElement, "group", { name: en.equipment_filter.pick })).toBeNull();

  await type(element, root, "xyz");
  expect(optionNames(root)).toEqual([]);
  expect(getByRole(root, "status").textContent).toContain(en.multi_select.none);
});

test("the arrow keys move the active option across both groups, Enter chooses it, Escape closes", async () => {
  const { element, root, changes } = await place();
  const input = combobox(root);
  expect(input.getAttribute("aria-activedescendant")).toBeNull();

  await key(element, root, "ArrowDown");
  expect(input.getAttribute("aria-expanded")).toBe("true");
  const active = () => root.querySelector(`#${input.getAttribute("aria-activedescendant")}`) as HTMLElement;
  expect(optionName(active())).toBe(MINE_NAME);

  await key(element, root, "ArrowDown");
  expect(optionName(active())).toBe(ALL_NAME);
  await key(element, root, "ArrowDown");
  expect(optionName(active())).toBe("band, not at home");
  await key(element, root, "ArrowUp");
  expect(optionName(active())).toBe(ALL_NAME);
  await key(element, root, "ArrowDown");

  await key(element, root, "Enter");
  expect(changes).toEqual([{ mode: "picked", values: ["band"] }]);
  expect(input.getAttribute("aria-expanded")).toBe("true");

  await key(element, root, "ArrowUp");
  await key(element, root, "Enter");
  expect(changes.at(-1)).toEqual({ mode: "all" });
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(input.getAttribute("aria-activedescendant")).toBeNull();

  await key(element, root, "ArrowUp");
  expect(input.getAttribute("aria-expanded")).toBe("true");
  expect(optionName(active())).toBe("kettlebell");
  await key(element, root, "Escape");
  expect(input.getAttribute("aria-expanded")).toBe("false");
});

test("a choice set from outside shows as it is", async () => {
  const { element, root } = await place({ choice: { mode: "picked", values: ["kettlebell", "band"] } });
  expect(tags(root)).toEqual(["band", "kettlebell"]);
  await open(element, root);
  expect(selected(root, "kettlebell")).toBe(true);
  expect(selected(root, "band, not at home")).toBe(true);
  expect(selected(root, MINE_NAME)).toBe(false);
});
