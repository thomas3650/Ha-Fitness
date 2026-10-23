import { getAllByRole, getByRole, queryAllByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/index";

interface Day {
  id: number;
  program_id: number;
  program_name: string;
  date: string;
  state: "due" | "late";
  station_count: number;
  rounds: number;
  total_minutes: number;
}

/** The parts of the card's interface that Home Assistant's `hui-card` and the dashboard use. */
interface CardElement extends HTMLElement {
  setConfig(config: { type: string; language?: string }): void;
  hass?: unknown;
  preview?: boolean;
  editMode?: boolean;
  connectedWhileHidden?: boolean;
  getCardSize(): number;
  getGridOptions(): { columns?: number | "full"; rows?: number | "auto" };
  updateComplete: Promise<boolean>;
}

const wednesday: Day = {
  id: 12,
  program_id: 3,
  program_name: "Onsdag",
  date: "2026-10-28",
  state: "due",
  station_count: 5,
  rounds: 5,
  total_minutes: 29,
};

const strength: Day = {
  id: 13,
  program_id: 4,
  program_name: "Styrke",
  date: "2026-10-28",
  state: "due",
  station_count: 1,
  rounds: 3,
  total_minutes: 12,
};

function today(open: Day[], date = "2026-10-28") {
  return { date, open, next: { date: "2026-10-31", programs: ["Lørdag"] } };
}

/** A fake `hass`: a spy for `callService` and a subscription the test pushes messages into. */
function fakeHass(language = "da") {
  let listener: ((message: unknown) => void) | undefined;
  const unsubscribe = vi.fn();
  const callService = vi.fn<(...args: unknown[]) => Promise<unknown>>(() => Promise.resolve({}));
  const subscribeMessage = vi.fn<
    (callback: (message: unknown) => void, message: unknown) => Promise<() => void>
  >((callback) => {
    listener = callback;
    return Promise.resolve(unsubscribe);
  });
  const hass = {
    locale: { language },
    callService,
    connection: { subscribeMessage },
  };
  return {
    hass,
    callService,
    subscribeMessage,
    unsubscribe,
    push(message: unknown) {
      if (!listener) throw new Error("the card has not subscribed");
      listener(message);
    },
  };
}

type Fake = ReturnType<typeof fakeHass>;

async function mount(
  fake: Fake,
  options: { language?: string; preview?: boolean; editMode?: boolean } = {},
): Promise<CardElement> {
  const card = document.createElement("ha-fitness-today-card") as unknown as CardElement;
  card.setConfig({
    type: "custom:ha-fitness-today-card",
    ...(options.language ? { language: options.language } : {}),
  });
  if (options.preview) card.preview = true;
  if (options.editMode) card.editMode = true;
  card.hass = fake.hass;
  document.body.append(card);
  await card.updateComplete;
  return card;
}

async function push(card: CardElement, fake: Fake, message: unknown): Promise<void> {
  fake.push(message);
  await card.updateComplete;
}

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
function root(card: CardElement): HTMLElement {
  return card.shadowRoot as unknown as HTMLElement;
}

function rows(card: CardElement): HTMLElement[] {
  return queryAllByRole(root(card), "listitem");
}

function text(element: HTMLElement): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function buttonNames(row: HTMLElement): string[] {
  return getAllByRole(row, "button").map((button) => text(button));
}

/** Click and let the card render. */
async function tap(card: CardElement, element: HTMLElement): Promise<void> {
  element.click();
  await card.updateComplete;
}

/** Let fake time pass, then let promises settle and the card render. */
async function wait(card: CardElement, ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
  await card.updateComplete;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

test("due and late rows in da and en", async () => {
  // Far west of UTC, a weekday read from the date as UTC would be a day early.
  vi.stubEnv("TZ", "America/Los_Angeles");

  const fake = fakeHass("da");
  const card = await mount(fake);
  expect(fake.subscribeMessage).toHaveBeenCalledWith(expect.any(Function), {
    type: "ha_fitness/today/subscribe",
  });

  await push(card, fake, today([wednesday, strength]));
  expect(rows(card).map(text)).toEqual([
    "Onsdag 5 øvelser · 5 runder · ca. 29 min Spring over",
    "Styrke 1 øvelse · 3 runder · ca. 12 min Spring over",
  ]);

  await push(card, fake, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(card).map(text)).toEqual([
    "Onsdag Forfalden · onsdag · 5 øvelser · 5 runder · ca. 29 min Spring over",
  ]);

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, today([wednesday]));
  expect(rows(englishCard).map(text)).toEqual(["Onsdag 5 exercises · 5 rounds · about 29 min Skip"]);
  await push(englishCard, english, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(englishCard).map(text)).toEqual([
    "Onsdag Late · Wednesday · 5 exercises · 5 rounds · about 29 min Skip",
  ]);
});

test("hides when nothing open and returns when a day opens", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  const events: { value: unknown; bubbles: boolean; composed: boolean }[] = [];
  const listener = (event: Event) => {
    const { detail, bubbles, composed } = event as CustomEvent<{ value: unknown }>;
    events.push({ value: detail.value, bubbles, composed });
  };
  document.addEventListener("card-visibility-changed", listener);

  // hui-card removes a hidden card from the DOM unless it asks to stay, and the card must stay subscribed.
  expect(card.connectedWhileHidden).toBe(true);

  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);
  expect(card.style.display).toBe("none");
  expect(events).toEqual([{ value: false, bubbles: true, composed: true }]);

  await push(card, fake, today([]));
  expect(events).toHaveLength(1);

  await push(card, fake, today([wednesday]));
  expect(card.hidden).toBe(false);
  expect(card.style.display).toBe("");
  expect(events).toEqual([
    { value: false, bubbles: true, composed: true },
    { value: true, bubbles: true, composed: true },
  ]);
  expect(rows(card).map(text)).toEqual(["Onsdag 5 øvelser · 5 runder · ca. 29 min Spring over"]);
  document.removeEventListener("card-visibility-changed", listener);
});

test("subscribes once and unsubscribes when removed", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  // HA sets a new hass object on every state change; the connection stays the same.
  card.hass = { ...fake.hass };
  await card.updateComplete;
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(1);

  card.remove();
  await vi.advanceTimersByTimeAsync(0);
  expect(fake.unsubscribe).toHaveBeenCalledTimes(1);
});

test("in preview never hides and shows the note", async () => {
  for (const options of [{ preview: true }, { editMode: true }]) {
    const fake = fakeHass();
    const card = await mount(fake, options);
    const events: unknown[] = [];
    card.addEventListener("card-visibility-changed", (event) => events.push(event));

    await push(card, fake, today([]));
    expect(card.hidden).toBe(false);
    expect(events).toEqual([]);
    expect(text(root(card))).toBe("Ingen træning i dag");

    await push(card, fake, today([wednesday]));
    expect(rows(card).map(text)).toEqual(["Onsdag 5 øvelser · 5 runder · ca. 29 min Spring over"]);
  }

  // A card already hidden comes back when it is shown in the editor.
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);
  card.preview = true;
  await card.updateComplete;
  expect(card.hidden).toBe(false);
  expect(text(root(card))).toBe("Ingen træning i dag");
});

test("one tap never skips", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 0);

  expect(fake.callService).not.toHaveBeenCalled();
  expect(text(rows(card)[0])).toBe("Onsdag 5 øvelser · 5 runder · ca. 29 min Spring over? Ja Nej");
});

test("Nej in place of Spring over", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday, strength]));

  // Spring over is the row's last button; after the first tap, Nej is.
  expect(buttonNames(rows(card)[0])).toEqual(["Spring over"]);
  await tap(card, getAllByRole(rows(card)[0], "button").at(-1)!);
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);
  // The other row is untouched.
  expect(buttonNames(rows(card)[1])).toEqual(["Spring over"]);

  // A double tap lands on Nej and cancels.
  await tap(card, getAllByRole(rows(card)[0], "button").at(-1)!);
  expect(buttonNames(rows(card)[0])).toEqual(["Spring over"]);
  await wait(card, 1000);
  expect(fake.callService).not.toHaveBeenCalled();
});

test("Ja ignores taps for 0.5 s", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  await wait(card, 499);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  expect(fake.callService).not.toHaveBeenCalled();
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);

  await wait(card, 1);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  expect(fake.callService).toHaveBeenCalledTimes(1);
});

test("Ja calls skip with notifyOnError false", async () => {
  const fake = fakeHass();
  let finish: (value: unknown) => void = () => undefined;
  fake.callService.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const card = await mount(fake);
  await push(card, fake, today([wednesday, strength]));

  await tap(card, getByRole(rows(card)[1], "button", { name: "Spring over" }));
  await wait(card, 500);
  await tap(card, getByRole(rows(card)[1], "button", { name: "Ja" }));
  expect(fake.callService).toHaveBeenCalledWith(
    "ha_fitness",
    "skip",
    { training_day_id: 13 },
    undefined,
    false,
  );

  // While the call runs, a second Ja does nothing.
  await tap(card, getByRole(rows(card)[1], "button", { name: "Ja" }));
  expect(fake.callService).toHaveBeenCalledTimes(1);

  finish({});
  await push(card, fake, today([wednesday]));
  expect(rows(card).map(text)).toEqual(["Onsdag 5 øvelser · 5 runder · ca. 29 min Spring over"]);
});

test("10 s timeout cancels", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 9999);
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);
  await wait(card, 1);
  expect(buttonNames(rows(card)[0])).toEqual(["Spring over"]);
  expect(fake.callService).not.toHaveBeenCalled();
});

test("error text from translation_key for 5 s", async () => {
  const cases: [unknown, string][] = [
    [{ code: "service_validation_error", translation_key: "not_found" }, "Træningsdagen findes ikke længere."],
    [{ code: "service_validation_error", translation_key: "not_open" }, "Træningsdagen er allerede lukket."],
    [{ code: "home_assistant_error", translation_key: "unavailable" }, "HA Fitness kan ikke nås. Prøv igen senere."],
    [{ code: "home_assistant_error", translation_key: "something_else" }, "Noget gik galt. Prøv igen."],
    [new Error("boom"), "Noget gik galt. Prøv igen."],
  ];
  for (const [error, message] of cases) {
    const fake = fakeHass();
    fake.callService.mockRejectedValue(error);
    const card = await mount(fake);
    await push(card, fake, today([wednesday]));

    await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
    await wait(card, 500);
    await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
    await wait(card, 0);
    expect(text(getByRole(root(card), "alert"))).toBe(message);
    expect(buttonNames(rows(card)[0])).toEqual(["Spring over"]);

    await wait(card, 4999);
    expect(queryByRole(root(card), "alert")).not.toBeNull();
    await wait(card, 1);
    expect(queryByRole(root(card), "alert")).toBeNull();
    card.remove();
  }
});

test("unreachable line", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);

  await push(card, fake, null);
  expect(card.hidden).toBe(false);
  expect(rows(card)).toEqual([]);
  expect(text(root(card))).toBe("HA Fitness kan ikke nås");

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, null);
  expect(text(root(englishCard))).toBe("HA Fitness can't be reached");
});

test("language option wins", async () => {
  const fake = fakeHass("en");
  const card = await mount(fake, { language: "da" });
  await push(card, fake, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(card).map(text)).toEqual([
    "Onsdag Forfalden · onsdag · 5 øvelser · 5 runder · ca. 29 min Spring over",
  ]);

  // HA translates service errors in the system language; the card uses its own texts.
  fake.callService.mockRejectedValue({ translation_key: "not_open" });
  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 500);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  await wait(card, 0);
  expect(text(getByRole(root(card), "alert"))).toBe("Træningsdagen er allerede lukket.");
});

test("grid options 2 rows per day", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 2 });
  expect(card.getCardSize()).toBe(2);

  await push(card, fake, today([wednesday]));
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 2 });
  expect(card.getCardSize()).toBe(2);

  await push(card, fake, today([wednesday, strength]));
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 4 });
  expect(card.getCardSize()).toBe(4);
});

test("is offered in the card picker, in English", () => {
  const entry = window.customCards?.find((card) => card.type === "ha-fitness-today-card");
  expect(entry?.name).toBe(en.picker.name);
  expect(entry?.description).toBe(en.picker.description);
});
