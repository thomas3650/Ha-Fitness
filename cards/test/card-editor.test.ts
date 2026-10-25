import { getByRole, queryByRole } from "@testing-library/dom";
import { afterEach, describe, expect, onTestFinished, test } from "vitest";

import "../src/index";

/** The statics Home Assistant's card picker and editor read from a card class. */
interface CardClass {
  getConfigElement(): HTMLElement;
  getStubConfig(): Record<string, unknown>;
}

/** The parts of a card editor that Home Assistant's `hui-card-element-editor` uses. */
interface EditorElement extends HTMLElement {
  hass?: { locale?: { language?: string } };
  setConfig(config: Record<string, unknown>): void;
  updateComplete: Promise<boolean>;
}

const CARD_TAGS = ["ha-fitness-today-card", "ha-fitness-workout-card", "ha-fitness-stats-card"];

afterEach(() => {
  document.body.replaceChildren();
});

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
function root(editor: EditorElement): HTMLElement {
  return editor.shadowRoot as unknown as HTMLElement;
}

function cardClass(tag: string): CardClass {
  return customElements.get(tag) as unknown as CardClass;
}

/** Freeze a config and everything in it, so an editor that changes HA's config throws. */
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null) {
    for (const inner of Object.values(value)) deepFreeze(inner);
    Object.freeze(value);
  }
  return value;
}

interface Mounted {
  editor: EditorElement;
  /** The config of each `config-changed` event, in order. */
  events: Record<string, unknown>[];
}

/** Mount the card's editor; `language` null leaves `hass` unset, as before HA sets it. */
async function mount(tag: string, config: Record<string, unknown>, language: string | null = "da"): Promise<Mounted> {
  const editor = cardClass(tag).getConfigElement() as EditorElement;
  const events: Record<string, unknown>[] = [];
  // Listened for on the body: HA's dialog hears the event only if it bubbles out of the editor.
  const listener = (event: Event): void => {
    events.push((event as CustomEvent<{ config: Record<string, unknown> }>).detail.config);
  };
  document.body.addEventListener("config-changed", listener);
  onTestFinished(() => document.body.removeEventListener("config-changed", listener));
  document.body.append(editor);
  if (language !== null) editor.hass = { locale: { language } };
  editor.setConfig(deepFreeze(config));
  await editor.updateComplete;
  return { editor, events };
}

function field(editor: EditorElement, name: string): HTMLSelectElement {
  return getByRole(root(editor), "combobox", { name }) as HTMLSelectElement;
}

function optionTexts(select: HTMLSelectElement): string[] {
  return [...select.options].map((option) => option.textContent?.trim() ?? "");
}

function selectedText(select: HTMLSelectElement): string {
  return select.options[select.selectedIndex]?.textContent?.trim() ?? "";
}

/** Choose the option with this text, as a user does. */
function choose(select: HTMLSelectElement, text: string): void {
  const option = [...select.options].find((candidate) => candidate.textContent?.trim() === text);
  if (!option) throw new Error(`no option ${text}`);
  select.value = option.value;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

describe.each(CARD_TAGS)("%s", (tag) => {
  test("opens with the language field in Danish", async () => {
    const { editor } = await mount(tag, { type: tag });
    const select = field(editor, "Sprog");
    expect(optionTexts(select)).toEqual(["Følg brugerens sprog", "English", "Dansk"]);
    expect(selectedText(select)).toBe("Følg brugerens sprog");
  });

  test("labels in English", async () => {
    const { editor } = await mount(tag, { type: tag }, "en");
    const select = field(editor, "Language");
    expect(optionTexts(select)).toEqual(["Follow the user's language", "English", "Dansk"]);
  });

  test("follows the user's language, not the card's", async () => {
    const { editor } = await mount(tag, { type: tag, language: "en" });
    expect(selectedText(field(editor, "Sprog"))).toBe("English");
  });

  test("choosing English sets language", async () => {
    const { editor, events } = await mount(tag, { type: tag });
    choose(field(editor, "Sprog"), "English");
    expect(events).toEqual([{ type: tag, language: "en" }]);
  });

  test("the event leaves the editor's shadow root", async () => {
    const { editor } = await mount(tag, { type: tag });
    let sent: Event | undefined;
    editor.addEventListener("config-changed", (event) => {
      sent = event;
    });
    choose(field(editor, "Sprog"), "English");
    expect(sent?.bubbles).toBe(true);
    expect(sent?.composed).toBe(true);
  });

  test("choosing the default removes language", async () => {
    const { editor, events } = await mount(tag, { type: tag, language: "da" });
    choose(field(editor, "Sprog"), "Følg brugerens sprog");
    expect(events).toEqual([{ type: tag }]);
    expect(Object.hasOwn(events[0], "language")).toBe(false);
  });

  test("keeps the rest of the config", async () => {
    const rest = {
      grid_options: { columns: 6, rows: "auto" },
      visibility: [{ condition: "user", users: ["x"] }],
      foo: 1,
    };
    const { editor, events } = await mount(tag, { type: tag, language: "da", ...structuredClone(rest) });
    choose(field(editor, "Sprog"), "English");
    expect(events).toEqual([{ type: tag, language: "en", ...rest }]);
  });

  test("keeps an unknown language until changed", async () => {
    const { editor, events } = await mount(tag, { type: tag, language: "da-DK" });
    const select = field(editor, "Sprog");
    expect(selectedText(select)).toBe("da-DK");
    expect(events).toEqual([]);
    choose(select, "Dansk");
    expect(events).toEqual([{ type: tag, language: "da" }]);
  });

  test("sends nothing until changed", async () => {
    const { editor, events } = await mount(tag, { type: tag });
    editor.setConfig(deepFreeze({ type: tag, language: "en" }));
    await editor.updateComplete;
    editor.hass = { locale: { language: "en" } };
    await editor.updateComplete;
    expect(events).toEqual([]);
  });

  test("the stub config adds no options", () => {
    expect(cardClass(tag).getStubConfig()).toEqual({});
  });

  test("renders no field until it has a config", async () => {
    const editor = cardClass(tag).getConfigElement() as EditorElement;
    document.body.append(editor);
    await editor.updateComplete;
    expect(queryByRole(root(editor), "combobox")).toBeNull();
    editor.setConfig(deepFreeze({ type: tag }));
    await editor.updateComplete;
    expect(queryByRole(root(editor), "combobox")).not.toBeNull();
  });

  test("labels in English before hass", async () => {
    const { editor } = await mount(tag, { type: tag }, null);
    expect(field(editor, "Language")).toBeDefined();
  });
});
