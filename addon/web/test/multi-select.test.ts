import { fireEvent, getByPlaceholderText, getByRole, queryByRole, within } from "@testing-library/dom";
import { afterEach, expect, test } from "vitest";

import { MultiSelect } from "../src/components/multi-select";
import en from "../src/i18n/en.json";
import { unmount } from "./mount";

afterEach(() => {
  unmount();
});

const OPTIONS = ["band", "body weight", "cable", "dumbbell", "kettlebell"].map((value) => ({ value, label: value }));

/** The name of a multi-select tag's remove button. */
function removeName(value: string): string {
  return en.multi_select.remove.replace("{value}", value);
}

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Put a multi-select in the page and return its shadow root and the `change` events it fires. */
async function place(props: Partial<Pick<MultiSelect, "label" | "placeholder" | "options" | "selected" | "fixed">> = {}) {
  const element = new MultiSelect();
  Object.assign(element, { label: "Equipment", options: OPTIONS, ...props });
  const changes: string[][] = [];
  element.addEventListener("change", (event) => changes.push((event as CustomEvent<{ selected: string[] }>).detail.selected));
  document.body.append(element);
  await element.updateComplete;
  const host = getByRole(document.body, "group", { name: "Equipment" });
  return { element, root: host.shadowRoot as unknown as HTMLElement, changes };
}

function combobox(root: HTMLElement): HTMLInputElement {
  return getByRole(root, "combobox", { name: "Equipment" }) as HTMLInputElement;
}

/** The chosen values' tags. */
function tags(root: HTMLElement): string[] {
  const list = queryByRole(root, "list", { name: en.multi_select.chosen.replace("{label}", "Equipment") });
  return list ? within(list).queryAllByRole("listitem").map(text) : [];
}

function optionNames(root: HTMLElement): string[] {
  const list = queryByRole(root, "listbox", { name: "Equipment" });
  return list ? within(list).queryAllByRole("option").map(text) : [];
}

async function settle(element: MultiSelect): Promise<void> {
  await element.updateComplete;
}

test("a click opens the list, and typing filters it, case-insensitive", async () => {
  const { element, root } = await place();
  const input = combobox(root);
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(queryByRole(root, "listbox")).toBeNull();

  fireEvent.click(input);
  await settle(element);
  expect(input.getAttribute("aria-expanded")).toBe("true");
  const list = getByRole(root, "listbox", { name: "Equipment" });
  expect(list.getAttribute("aria-multiselectable")).toBe("true");
  expect(input.getAttribute("aria-controls")).toBe(list.id);
  expect(optionNames(root)).toEqual(["band", "body weight", "cable", "dumbbell", "kettlebell"]);

  fireEvent.input(input, { target: { value: "BE" } });
  await settle(element);
  expect(optionNames(root)).toEqual(["dumbbell", "kettlebell"]);
});

test("a click on an option chooses it, keeps the list open and fires change", async () => {
  const { element, root, changes } = await place({ selected: ["band"] });
  fireEvent.click(combobox(root));
  await settle(element);

  fireEvent.click(getByRole(root, "option", { name: "cable" }));
  await settle(element);
  expect(changes).toEqual([["band", "cable"]]);
  expect(getByRole(root, "option", { name: "cable", selected: true })).toBeTruthy();
  expect(getByRole(root, "option", { name: "dumbbell", selected: false })).toBeTruthy();
  expect(getByRole(root, "listbox")).toBeTruthy();
  // The chosen values show as tags.
  expect(getByRole(root, "button", { name: removeName("cable") })).toBeTruthy();

  // A second click takes it off again.
  fireEvent.click(getByRole(root, "option", { name: "cable" }));
  await settle(element);
  expect(changes.at(-1)).toEqual(["band"]);
  expect(queryByRole(root, "button", { name: removeName("cable") })).toBeNull();
});

test("the tag's remove button takes the value off", async () => {
  const { element, root, changes } = await place({ selected: ["band", "dumbbell"] });

  fireEvent.click(getByRole(root, "button", { name: removeName("dumbbell") }));
  await settle(element);
  expect(changes).toEqual([["band"]]);
  expect(queryByRole(root, "button", { name: removeName("dumbbell") })).toBeNull();
  expect(getByRole(root, "button", { name: removeName("band") })).toBeTruthy();
});

test("a fixed value is always chosen and has no remove button", async () => {
  const { element, root, changes } = await place({ selected: ["dumbbell"], fixed: ["body weight"] });

  expect(tags(root)).toEqual(["body weight", "dumbbell"]);
  expect(queryByRole(root, "button", { name: removeName("body weight") })).toBeNull();
  fireEvent.click(combobox(root));
  await settle(element);
  const fixed = getByRole(root, "option", { name: "body weight", selected: true });
  fireEvent.click(fixed);
  await settle(element);
  expect(changes).toEqual([]);

  // Backspace in an empty field removes the last value that isn't fixed.
  fireEvent.keyDown(combobox(root), { key: "Backspace" });
  await settle(element);
  // The fixed values are chosen too, so the event carries them.
  expect(changes).toEqual([["body weight"]]);
  fireEvent.keyDown(combobox(root), { key: "Backspace" });
  await settle(element);
  expect(changes).toHaveLength(1);
  expect(tags(root)).toEqual(["body weight"]);
});

test("the keyboard: ArrowDown opens and moves, Enter chooses, Escape closes", async () => {
  const { element, root, changes } = await place();
  const input = combobox(root);

  fireEvent.keyDown(input, { key: "ArrowDown" });
  await settle(element);
  expect(input.getAttribute("aria-expanded")).toBe("true");
  fireEvent.keyDown(input, { key: "ArrowDown" });
  await settle(element);
  const active = input.getAttribute("aria-activedescendant");
  expect(active).toBeTruthy();
  expect(text(within(root).getAllByRole("option").find((option) => option.id === active) as HTMLElement)).toBe(
    "body weight",
  );
  fireEvent.keyDown(input, { key: "ArrowUp" });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  await settle(element);
  expect(changes).toEqual([["body weight"]]);
  expect(getByRole(root, "listbox")).toBeTruthy();

  fireEvent.keyDown(input, { key: "Escape" });
  await settle(element);
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(queryByRole(root, "listbox")).toBeNull();
});

test("a search that finds nothing says so", async () => {
  const { element, root } = await place();

  fireEvent.input(combobox(root), { target: { value: "trampoline" } });
  await settle(element);
  expect(optionNames(root)).toEqual([]);
  expect(text(getByRole(root, "status"))).toBe(en.multi_select.none);
});

test("a click outside closes the list", async () => {
  const { element, root } = await place();
  const outside = document.createElement("button");
  document.body.append(outside);
  fireEvent.click(combobox(root));
  await settle(element);
  expect(getByRole(root, "listbox")).toBeTruthy();

  fireEvent.pointerDown(outside);
  await settle(element);
  expect(queryByRole(root, "listbox")).toBeNull();
});

test("focus leaving the component closes the list; focus on a tag's remove button keeps it open", async () => {
  const { element, root } = await place({ selected: ["cable"] });
  const outside = document.createElement("button");
  document.body.append(outside);
  const input = combobox(root);
  fireEvent.click(input);
  await settle(element);

  fireEvent.focusOut(input, { relatedTarget: getByRole(root, "button", { name: removeName("cable") }) });
  await settle(element);
  expect(getByRole(root, "listbox")).toBeTruthy();

  fireEvent.focusOut(input, { relatedTarget: outside });
  await settle(element);
  expect(queryByRole(root, "listbox")).toBeNull();

  // Focus leaving from a tag's button closes it as well.
  fireEvent.click(input);
  await settle(element);
  fireEvent.focusOut(getByRole(root, "button", { name: removeName("cable") }), { relatedTarget: outside });
  await settle(element);
  expect(queryByRole(root, "listbox")).toBeNull();
});

test("the field shows the caller's placeholder", async () => {
  const { root } = await place({ placeholder: "Any equipment" });

  expect(getByPlaceholderText(root, "Any equipment")).toBe(combobox(root));
});

test("choosing an option clears the search and shows every option again, the list open", async () => {
  const { element, root, changes } = await place();
  const input = combobox(root);

  fireEvent.input(input, { target: { value: "kettle" } });
  await settle(element);
  expect(optionNames(root)).toEqual(["kettlebell"]);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  await settle(element);

  expect(changes).toEqual([["kettlebell"]]);
  expect(input.value).toBe("");
  expect(optionNames(root)).toEqual(["band", "body weight", "cable", "dumbbell", "kettlebell"]);

  fireEvent.input(input, { target: { value: "cab" } });
  await settle(element);
  fireEvent.click(getByRole(root, "option", { name: "cable" }));
  await settle(element);
  expect(input.value).toBe("");
  expect(optionNames(root)).toHaveLength(OPTIONS.length);
});

test("Backspace removes the last tag shown, which follows the options' order", async () => {
  const { element, root, changes } = await place({ selected: ["dumbbell", "band"] });

  expect(tags(root)).toEqual(["band", "dumbbell"]);
  fireEvent.keyDown(combobox(root), { key: "Backspace" });
  await settle(element);
  expect(changes).toEqual([["band"]]);
  expect(tags(root)).toEqual(["band"]);
});

test("a tag's remove button gives the focus back to the field", async () => {
  const { element, root } = await place({ selected: ["band", "cable"] });

  const remove = getByRole(root, "button", { name: removeName("cable") });
  remove.focus();
  fireEvent.click(remove);
  await settle(element);
  expect((root as unknown as ShadowRoot).activeElement).toBe(combobox(root));
});
