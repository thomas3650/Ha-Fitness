import { getAllByRole, getByRole, queryAllByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";

interface Totals {
  done: number;
  extra: number;
  missed: number;
  skipped: number;
  time_trained: number;
}

interface PersonStats {
  id: number;
  name: string;
  person_entity_id: string;
  streak: number;
  all_time: Totals;
  this_month: Totals;
}

interface Stats {
  counting_from: string | null;
  month: string;
  people: PersonStats[];
}

/** The parts of the card's interface that Home Assistant's `hui-card` and the dashboard use. */
interface CardElement extends HTMLElement {
  setConfig(config: { type: string; language?: string }): void;
  hass?: unknown;
  getCardSize(): number;
  getGridOptions(): { columns?: number | "full"; min_columns?: number };
  updateComplete: Promise<boolean>;
}

type Listener = (message: unknown) => void;

const TAG = "ha-fitness-stats-card";

const zero: Totals = { done: 0, extra: 0, missed: 0, skipped: 0, time_trained: 0 };

function person(id: number, name: string, extra: Partial<PersonStats> = {}): PersonStats {
  return {
    id,
    name,
    person_entity_id: `person.${name.toLowerCase()}`,
    streak: 0,
    all_time: zero,
    this_month: zero,
    ...extra,
  };
}

const thomas = person(1, "Thomas", {
  streak: 7,
  this_month: { done: 5, extra: 0, missed: 2, skipped: 0, time_trained: 2100 },
  all_time: { done: 12, extra: 2, missed: 3, skipped: 1, time_trained: 16500 },
});
const maria = person(2, "Maria", { streak: 1 });
const anna = person(3, "Anna");

function stats(people: PersonStats[], countingFrom: string | null = "2026-10-01"): Stats {
  return { counting_from: countingFrom, month: "2026-10", people };
}

/**
 * A fake of home-assistant-js-websocket's connection that carries `ha_fitness/stats/subscribe`.
 * Like the integration, it sends `initial` at once; `push` sends the next message, and `refuse`
 * makes the next subscription fail.
 */
function fakeHass(language = "da", initial: unknown = { available: true, stats: stats([thomas, maria]) }) {
  const listeners: Listener[] = [];
  const fake = {
    refuse: false,
    types: [] as string[],
    push(message: unknown) {
      const listener = listeners.at(-1);
      if (!listener) throw new Error("nothing has subscribed to the stats");
      listener(message);
    },
    hass: {} as Record<string, unknown>,
  };
  const connection = {
    subscribeMessage(callback: Listener, message: { type: string }) {
      fake.types.push(message.type);
      if (message.type !== "ha_fitness/stats/subscribe") return Promise.resolve(vi.fn());
      if (fake.refuse) return Promise.reject({ code: "unknown_command", message: "Unknown command." });
      listeners.push(callback);
      void Promise.resolve().then(() => callback(initial));
      return Promise.resolve(vi.fn());
    },
    addEventListener() {},
    removeEventListener() {},
  };
  fake.hass = { locale: { language }, connection };
  return fake;
}

type Fake = ReturnType<typeof fakeHass>;

async function settle(card: CardElement): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
  await card.updateComplete;
}

async function mount(fake: Fake, config: { language?: string } = {}): Promise<CardElement> {
  const card = document.createElement(TAG) as CardElement;
  card.setConfig({ type: `custom:${TAG}`, ...config });
  card.hass = fake.hass;
  document.body.append(card);
  await settle(card);
  return card;
}

async function push(fake: Fake, card: CardElement, message: unknown): Promise<void> {
  fake.push(message);
  await settle(card);
}

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
function root(card: CardElement): HTMLElement {
  return card.shadowRoot as unknown as HTMLElement;
}

function text(element: Element): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function panels(card: CardElement): HTMLElement[] {
  return queryAllByRole(root(card), "region");
}

function panel(card: CardElement, name: string): HTMLElement {
  return getByRole(root(card), "region", { name });
}

function colour(element: HTMLElement): string {
  return element.style.getPropertyValue("--person-color").trim().toUpperCase();
}

/** The table of a panel: the header row, then each row as [header, this month, all time]. */
function table(element: HTMLElement): string[][] {
  return getAllByRole(element, "row").map((row) =>
    (["columnheader", "rowheader", "cell"] as const)
      .flatMap((role) => queryAllByRole(row, role))
      .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
      .map((cell) => text(cell)),
  );
}

function streak(element: HTMLElement): string {
  return text(getByRole(element, "paragraph"));
}

/** The card's text outside the panels. */
function lines(card: CardElement): string[] {
  return queryAllByRole(root(card), "status").map(text);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("the card picker lists the card in English", () => {
  const entry = window.customCards?.find((card) => card.type === TAG);
  expect(entry?.name).toBe("HA Fitness – stats");
  expect(entry?.description).toBeTruthy();
});

test("takes the full width of a section", async () => {
  const card = await mount(fakeHass());
  expect(card.getGridOptions()).toEqual({ columns: "full", min_columns: 6 });
});

test("subscribes to ha_fitness/stats/subscribe", async () => {
  const fake = fakeHass();
  await mount(fake);
  expect(fake.types).toContain("ha_fitness/stats/subscribe");
});

test("panels per person in order with colour dots and names", async () => {
  const fake = fakeHass("da", { available: true, stats: stats([thomas, maria, anna]) });
  const card = await mount(fake);

  const found = panels(card);
  expect(found.map((element) => text(getByRole(element, "heading")))).toEqual(["Thomas", "Maria", "Anna"]);
  expect(found.map(colour)).toEqual(["#B18CFF", "#3DD6C6", "VAR(--PRIMARY-COLOR)"]);

  // The order is the people's order, not the ids'.
  await push(fake, card, { available: true, stats: stats([maria, thomas]) });
  expect(panels(card).map((element) => text(getByRole(element, "heading")))).toEqual(["Maria", "Thomas"]);
  expect(colour(panel(card, "Maria"))).toBe("#B18CFF");
  expect(colour(panel(card, "Thomas"))).toBe("#3DD6C6");
});

test("streak with plurals", async () => {
  const da = await mount(fakeHass("da"));
  expect(streak(panel(da, "Thomas"))).toBe("7 i træk");
  expect(streak(panel(da, "Maria"))).toBe("1 i træk");
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"));
  expect(streak(panel(en, "Thomas"))).toBe("7 in a row");
  expect(streak(panel(en, "Maria"))).toBe("1 in a row");
});

test("table rows this month and all time", async () => {
  const da = await mount(fakeHass("da"));
  expect(table(panel(da, "Thomas"))).toEqual([
    ["", "Denne måned", "I alt"],
    ["Gennemført", "5", "12 · 2 ekstra"],
    ["Missede", "2", "4 · 1 sprunget over"],
    ["Tid", "35 min", "4 t 35 min"],
  ]);
  expect(table(panel(da, "Maria"))).toEqual([
    ["", "Denne måned", "I alt"],
    ["Gennemført", "0", "0"],
    ["Missede", "0", "0"],
    ["Tid", "0 min", "0 min"],
  ]);
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"));
  expect(table(panel(en, "Thomas"))).toEqual([
    ["", "This month", "All time"],
    ["Done", "5", "12 · 2 extra"],
    ["Missed", "2", "4 · 1 skipped"],
    ["Time", "35 min", "4 h 35 min"],
  ]);
});

test("time rounds down to whole minutes", async () => {
  const exact = person(1, "Thomas", {
    this_month: { ...zero, time_trained: 3599 },
    all_time: { ...zero, time_trained: 3600 },
  });
  const card = await mount(fakeHass("da", { available: true, stats: stats([exact]) }));
  expect(table(panel(card, "Thomas"))[3]).toEqual(["Tid", "59 min", "1 t 0 min"]);
});

test("which line shows", async () => {
  // 1. Never had stats and unavailable.
  const fake = fakeHass("da", { available: false, stats: null });
  const card = await mount(fake);
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås"]);
  expect(panels(card)).toEqual([]);

  // 2. No people, before 3: counting_from is null too.
  await push(fake, card, { available: true, stats: stats([], null) });
  expect(lines(card)).toEqual(["Ingen personer"]);
  expect(panels(card)).toEqual([]);

  // 3. counting_from null.
  await push(fake, card, { available: true, stats: stats([thomas], null) });
  expect(lines(card)).toEqual(["Statistikken starter ved første træning"]);
  expect(panels(card)).toEqual([]);

  // 4. The panels.
  await push(fake, card, { available: true, stats: stats([thomas]) });
  expect(lines(card)).toEqual([]);
  expect(panels(card)).toHaveLength(1);
});

test("which line shows in English", async () => {
  const fake = fakeHass("en", { available: false, stats: null });
  const card = await mount(fake);
  expect(lines(card)).toEqual(["HA Fitness can't be reached"]);
  await push(fake, card, { available: true, stats: stats([], null) });
  expect(lines(card)).toEqual(["No people"]);
  await push(fake, card, { available: true, stats: stats([thomas], null) });
  expect(lines(card)).toEqual(["Stats start at the first workout"]);
});

test("a refused subscription before any stats shows the unreachable line", async () => {
  const fake = fakeHass("da");
  fake.refuse = true;
  const card = await mount(fake);
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås"]);
  expect(panels(card)).toEqual([]);
});

test("unreachable note keeps the last numbers", async () => {
  const fake = fakeHass("da");
  const card = await mount(fake);
  expect(lines(card)).toEqual([]);

  // The integration sends the last stats it knows while the add-on is gone.
  await push(fake, card, { available: false, stats: stats([thomas, maria]) });
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås"]);
  expect(streak(panel(card, "Thomas"))).toBe("7 i træk");
  expect(table(panel(card, "Thomas"))[1]).toEqual(["Gennemført", "5", "12 · 2 ekstra"]);

  // A message with no stats keeps the last numbers too.
  await push(fake, card, { available: false, stats: null });
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås"]);
  expect(panels(card)).toHaveLength(2);

  // Back: the note goes.
  await push(fake, card, { available: true, stats: stats([thomas, maria]) });
  expect(lines(card)).toEqual([]);
  expect(queryByRole(root(card), "region", { name: "Thomas" })).not.toBeNull();
});

test("the unreachable note also shows with the no people and not started lines", async () => {
  const fake = fakeHass("da", { available: true, stats: stats([], null) });
  const card = await mount(fake);
  expect(lines(card)).toEqual(["Ingen personer"]);

  await push(fake, card, { available: false, stats: null });
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås", "Ingen personer"]);

  await push(fake, card, { available: true, stats: stats([thomas], null) });
  expect(lines(card)).toEqual(["Statistikken starter ved første træning"]);

  await push(fake, card, { available: false, stats: stats([thomas], null) });
  expect(lines(card)).toEqual(["HA Fitness kan ikke nås", "Statistikken starter ved første træning"]);
});

test("language option", async () => {
  const card = await mount(fakeHass("en"), { language: "da" });
  expect(streak(panel(card, "Thomas"))).toBe("7 i træk");
  expect(table(panel(card, "Thomas"))[0]).toEqual(["", "Denne måned", "I alt"]);
});
