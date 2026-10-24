import { getAllByRole, getByRole, queryAllByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, onTestFinished, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/index";
import * as overlay from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// One audio context for the page (audio.ts keeps it at module level), so one fake for the file.
const audio = installFakeAudio("suspended");

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

/** Onsdag as `ha_fitness/programs` returns it (spec §4). */
const onsdag = {
  id: 3,
  name: "Onsdag",
  rounds: 5,
  work_seconds: 45,
  switch_seconds: 15,
  round_rest_seconds: 60,
  countdown_seconds: 10,
  total_minutes: 29,
  stations: [
    { exercise_id: "0001", name: "Push-up" },
    { exercise_id: "0002", name: "Squat" },
  ],
};

function today(open: Day[], date = "2026-10-28") {
  return { date, open, next: { date: "2026-10-31", programs: ["Lørdag"] } };
}

type Listener = (message: unknown) => void;

const NO_SESSION = { available: true, session: null };

/**
 * A fake of home-assistant-js-websocket's connection. The today card's `ha_fitness/today/subscribe`
 * and the page's `ha_fitness/session/subscribe` (the overlay controller's) are kept apart:
 * `subscribeMessage`, `listeners` and `unsubscribes` are the today subscription's, and
 * `subscribeSession` and `pushSession` the session's, and `subscribeStats` and `pushStats` the
 * stats' (`ha_fitness/stats/subscribe`), which sends nothing until the test does. Like the integration, the session
 * subscription sends at once: `{available: true, session: null}` unless the test says otherwise.
 * `fire` sends a connection event such as `ready` (sent after a reconnect).
 */
function fakeConnection(initialSession: unknown = NO_SESSION) {
  const listeners: Listener[] = [];
  const unsubscribes: ReturnType<typeof vi.fn>[] = [];
  const sessionListeners: Listener[] = [];
  const statsListeners: Listener[] = [];
  const events = new Map<string, Set<(...args: unknown[]) => void>>();
  const subscribeMessage = vi.fn<
    (callback: Listener, message: unknown, options?: unknown) => Promise<() => void>
  >(
    (callback) => {
      listeners.push(callback);
      const unsubscribe = vi.fn();
      unsubscribes.push(unsubscribe);
      return Promise.resolve(unsubscribe);
    },
  );
  const subscribeSession = vi.fn<
    (callback: Listener, message: unknown, options?: unknown) => Promise<() => void>
  >((callback) => {
    sessionListeners.push(callback);
    void Promise.resolve().then(() => callback(initialSession));
    return Promise.resolve(vi.fn());
  });
  const subscribeStats = vi.fn<
    (callback: Listener, message: unknown, options?: unknown) => Promise<() => void>
  >((callback) => {
    statsListeners.push(callback);
    return Promise.resolve(vi.fn());
  });
  const connection = {
    subscribeMessage(callback: Listener, message: { type: string }, options?: unknown) {
      if (message.type === "ha_fitness/session/subscribe") return subscribeSession(callback, message, options);
      if (message.type === "ha_fitness/stats/subscribe") return subscribeStats(callback, message, options);
      return subscribeMessage(callback, message, options);
    },
    addEventListener(type: string, callback: (...args: unknown[]) => void) {
      if (!events.has(type)) events.set(type, new Set());
      events.get(type)!.add(callback);
    },
    removeEventListener(type: string, callback: (...args: unknown[]) => void) {
      events.get(type)?.delete(callback);
    },
  };
  return {
    connection,
    subscribeMessage,
    subscribeSession,
    subscribeStats,
    listeners,
    unsubscribes,
    listenerCount: (type: string) => events.get(type)?.size ?? 0,
    fire(type: string) {
      for (const callback of events.get(type) ?? []) callback(connection);
    },
    /** Send a message on the newest today subscription. */
    push(message: unknown) {
      const listener = listeners.at(-1);
      if (!listener) throw new Error("the card has not subscribed");
      listener(message);
    },
    /** Send a message on the newest session subscription. */
    pushSession(message: unknown) {
      const listener = sessionListeners.at(-1);
      if (!listener) throw new Error("nothing has subscribed to the session");
      listener(message);
    },
    /** Send a message on the newest stats subscription. */
    pushStats(message: unknown) {
      const listener = statsListeners.at(-1);
      if (!listener) throw new Error("the card has not subscribed to the stats");
      listener(message);
    },
  };
}

type Message = { type: string } & Record<string, unknown>;

/**
 * A fake `hass`: a spy for `callService`, a `callWS` for §4's commands (the workout flow fetches the
 * programs and the people when it opens), `fetchWithAuth` for its images, and a fake connection the
 * test pushes messages into.
 */
function fakeHass(language = "da", initialSession: unknown = NO_SESSION) {
  const socket = fakeConnection(initialSession);
  const callService = vi.fn<(...args: unknown[]) => Promise<unknown>>(() => Promise.resolve({}));
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/programs") return Promise.resolve([onsdag]);
    if (message.type === "ha_fitness/people") return Promise.resolve([{ id: 1, name: "Thomas" }]);
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  const fetchWithAuth = vi.fn(async () => new Response(null, { status: 404 }));
  const hass = {
    locale: { language },
    callService,
    callWS,
    fetchWithAuth,
    connection: socket.connection,
  };
  return { ...socket, hass, callService, callWS };
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
  // The session subscription's first message.
  await vi.advanceTimersByTimeAsync(0);
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
  // The overlay controller is page-wide and has no reset; each test closes what it opened.
  overlay.close();
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

test("due and late rows in da and en", async () => {
  // Far west of UTC, a weekday read from the date as UTC would be a day early.
  vi.stubEnv("TZ", "America/Los_Angeles");

  const fake = fakeHass("da");
  const card = await mount(fake);
  // The card resubscribes itself after a reconnect, so the library must not (HA's own cards do the same).
  expect(fake.subscribeMessage).toHaveBeenCalledWith(
    expect.any(Function),
    { type: "ha_fitness/today/subscribe" },
    { resubscribe: false },
  );

  await push(card, fake, today([wednesday, strength]));
  expect(rows(card).map(text)).toEqual([
    "Onsdag I dag 5 øvelser · 29 min Start Spring over",
    "Styrke I dag 1 øvelse · 12 min Start Spring over",
  ]);

  await push(card, fake, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(card).map(text)).toEqual([
    "Onsdag Forfalden · onsdag 5 øvelser · 29 min Start Spring over",
  ]);

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, today([wednesday]));
  expect(rows(englishCard).map(text)).toEqual(["Onsdag Today 5 exercises · 29 min Start Skip"]);
  await push(englishCard, english, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(englishCard).map(text)).toEqual([
    "Onsdag Late · Wednesday 5 exercises · 29 min Start Skip",
  ]);
});

/** Record every `card-visibility-changed` that reaches the document. */
function visibilityEvents() {
  const events: { value: unknown; bubbles: boolean; composed: boolean }[] = [];
  const listener = (event: Event) => {
    const { detail, bubbles, composed } = event as CustomEvent<{ value: unknown }>;
    events.push({ value: detail.value, bubbles, composed });
  };
  document.addEventListener("card-visibility-changed", listener);
  onTestFinished(() => document.removeEventListener("card-visibility-changed", listener));
  return events;
}

const HIDE = { value: false, bubbles: true, composed: true };
const SHOW = { value: true, bubbles: true, composed: true };

test("starts hidden until the first message", async () => {
  const events = visibilityEvents();
  const fake = fakeHass();
  const card = document.createElement("ha-fitness-today-card") as unknown as CardElement;
  card.setConfig({ type: "custom:ha-fitness-today-card" });
  card.hass = fake.hass;
  document.body.append(card);
  // Hidden at once, before the first render, so no empty cell shows on a day with no training.
  expect(card.hidden).toBe(true);
  expect(card.style.display).toBe("none");
  await card.updateComplete;
  expect(events).toEqual([HIDE]);

  await push(card, fake, today([wednesday]));
  expect(card.hidden).toBe(false);
  expect(events).toEqual([HIDE, SHOW]);
});

test("hides when nothing open and returns when a day opens", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));
  const events = visibilityEvents();

  // hui-card removes a hidden card from the DOM unless it asks to stay, and the card must stay subscribed.
  expect(card.connectedWhileHidden).toBe(true);

  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);
  expect(card.style.display).toBe("none");
  expect(events).toEqual([HIDE]);

  await push(card, fake, today([]));
  expect(events).toEqual([HIDE]);

  await push(card, fake, today([wednesday]));
  expect(card.hidden).toBe(false);
  expect(card.style.display).toBe("");
  expect(events).toEqual([HIDE, SHOW]);
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
});

test("subscribes once and unsubscribes when removed", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  // HA sets a new hass object on every state change; the connection stays the same.
  card.hass = { ...fake.hass };
  await card.updateComplete;
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(1);
  expect(fake.subscribeStats).toHaveBeenCalledTimes(1);

  card.remove();
  await vi.advanceTimersByTimeAsync(0);
  expect(fake.unsubscribes[0]).toHaveBeenCalledTimes(1);
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
    expect(text(root(card))).toBe("TRÆNING Ingen træning i dag");

    await push(card, fake, today([wednesday]));
    expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
  }

  // A card already hidden comes back when it is shown in the editor.
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);
  card.preview = true;
  await card.updateComplete;
  expect(card.hidden).toBe(false);
  expect(text(root(card))).toBe("TRÆNING Ingen træning i dag");
});

test("one tap never skips", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 0);

  expect(fake.callService).not.toHaveBeenCalled();
  expect(text(rows(card)[0])).toBe("Onsdag Spring over? 5 øvelser · 29 min Ja Nej");
});

test("Nej in place of Spring over", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday, strength]));

  // Spring over is the row's last button; after the first tap, Nej is.
  expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);
  await tap(card, getAllByRole(rows(card)[0], "button").at(-1)!);
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);
  // The other row is untouched.
  expect(buttonNames(rows(card)[1])).toEqual(["Start", "Spring over"]);

  // A double tap lands on Nej and cancels.
  await tap(card, getAllByRole(rows(card)[0], "button").at(-1)!);
  expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);
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
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
});

test("10 s timeout cancels", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 9999);
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);
  await wait(card, 1);
  expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);
  expect(fake.callService).not.toHaveBeenCalled();
});

test("error text from translation_key for 5 s", async () => {
  const cases: [unknown, string][] = [
    [{ code: "service_validation_error", translation_key: "not_found" }, "Træningsdagen findes ikke længere."],
    [{ code: "service_validation_error", translation_key: "not_open" }, "Træningsdagen er allerede afsluttet."],
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
    expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);

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
  expect(text(root(card))).toBe("TRÆNING HA Fitness kan ikke nås");

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, null);
  expect(text(root(englishCard))).toBe("TRAINING HA Fitness can't be reached");
});

test("a subscription the integration refuses shows the unreachable line", async () => {
  const fake = fakeHass();
  fake.subscribeMessage.mockRejectedValue({ code: "unknown_command" });
  const card = await mount(fake);
  await wait(card, 0);
  expect(card.hidden).toBe(false);
  expect(text(root(card))).toBe("TRÆNING HA Fitness kan ikke nås");
});

test("retries a refused subscription after 5, 10 and 30 s, then every 30 s", async () => {
  const fake = fakeHass();
  for (let i = 0; i < 4; i++) fake.subscribeMessage.mockRejectedValueOnce({ code: "unknown_command" });
  const card = await mount(fake);
  await wait(card, 0);
  expect(text(root(card))).toBe("TRÆNING HA Fitness kan ikke nås");

  // The n-th retry comes this many ms after the refusal before it.
  for (const [delay, calls] of [
    [5_000, 2],
    [10_000, 3],
    [30_000, 4],
    [30_000, 5],
  ]) {
    await wait(card, delay - 1);
    expect(fake.subscribeMessage).toHaveBeenCalledTimes(calls - 1);
    await wait(card, 1);
    expect(fake.subscribeMessage).toHaveBeenCalledTimes(calls);
  }

  await push(card, fake, today([wednesday]));
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
  await wait(card, 120_000);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(5);
});

test("a reconnect subscribes at once and starts the waits over", async () => {
  const fake = fakeHass();
  for (let i = 0; i < 4; i++) fake.subscribeMessage.mockRejectedValueOnce({ code: "unknown_command" });
  const card = await mount(fake);
  await wait(card, 15_000);
  // Refused at 0, 5 and 15 s; the next wait would be 30 s.
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(3);

  fake.fire("ready");
  await wait(card, 0);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(4);
  await wait(card, 4_999);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(4);
  await wait(card, 1);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(5);

  await push(card, fake, today([wednesday]));
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
});

test("stops retrying and listening when removed", async () => {
  const fake = fakeHass();
  fake.subscribeMessage.mockRejectedValue({ code: "unknown_command" });
  const card = await mount(fake);
  await wait(card, 0);
  // The card's two listeners (today and stats) and the page-wide overlay controller's.
  expect(fake.listenerCount("ready")).toBe(3);

  card.remove();
  // The overlay controller keeps its own subscription; the card's listener is gone.
  expect(fake.listenerCount("ready")).toBe(1);
  await vi.advanceTimersByTimeAsync(120_000);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(1);
});

test("subscribes again when the connection is ready after a reconnect", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  fake.fire("ready");
  await wait(card, 0);
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);
  expect(fake.unsubscribes[0]).toHaveBeenCalledTimes(1);
  expect(fake.subscribeMessage).toHaveBeenLastCalledWith(
    expect.any(Function),
    { type: "ha_fitness/today/subscribe" },
    { resubscribe: false },
  );

  // A late message on the old subscription is ignored.
  fake.listeners[0](today([]));
  await card.updateComplete;
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);

  await push(card, fake, today([strength]));
  expect(rows(card).map(text)).toEqual(["Styrke I dag 1 øvelse · 12 min Start Spring over"]);
});

test("a new connection replaces the old subscription", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  const other = fakeConnection();
  card.hass = { ...fake.hass, connection: other.connection };
  await wait(card, 0);
  expect(fake.unsubscribes[0]).toHaveBeenCalledTimes(1);
  expect(fake.listenerCount("ready")).toBe(0);
  expect(other.subscribeMessage).toHaveBeenCalledTimes(1);

  // A late message on the old connection is ignored.
  fake.push(today([]));
  await card.updateComplete;
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);

  other.push(today([strength]));
  await card.updateComplete;
  expect(rows(card).map(text)).toEqual(["Styrke I dag 1 øvelse · 12 min Start Spring over"]);
});

test("subscribes again when put back on the page", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  card.remove();
  await vi.advanceTimersByTimeAsync(0);
  expect(fake.unsubscribes[0]).toHaveBeenCalledTimes(1);

  document.body.append(card);
  await card.updateComplete;
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);
  // The old data is dropped: hidden until the new subscription answers.
  expect(card.hidden).toBe(true);

  await push(card, fake, today([strength]));
  expect(card.hidden).toBe(false);
  expect(rows(card).map(text)).toEqual(["Styrke I dag 1 øvelse · 12 min Start Spring over"]);
});

test("a day that closes while asking drops its question", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday, strength]));
  await tap(card, getByRole(rows(card)[1], "button", { name: "Spring over" }));

  // Skipped from elsewhere, then open again: the row starts over at Spring over.
  await push(card, fake, today([wednesday]));
  await push(card, fake, today([wednesday, strength]));
  expect(buttonNames(rows(card)[1])).toEqual(["Start", "Spring over"]);
});

test("language option wins", async () => {
  const fake = fakeHass("en");
  const card = await mount(fake, { language: "da" });
  await push(card, fake, today([{ ...wednesday, state: "late" }], "2026-10-29"));
  expect(rows(card).map(text)).toEqual([
    "Onsdag Forfalden · onsdag 5 øvelser · 29 min Start Spring over",
  ]);

  // HA translates service errors in the system language; the card uses its own texts.
  fake.callService.mockRejectedValue({ translation_key: "not_open" });
  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  await wait(card, 500);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  await wait(card, 0);
  expect(text(getByRole(root(card), "alert"))).toBe("Træningsdagen er allerede afsluttet.");
});

test("the grid rows follow the days", async () => {
  // One row for the top line, then three per day (or for the session row).
  const fake = fakeHass();
  const card = await mount(fake);
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 4 });
  expect(card.getCardSize()).toBe(4);

  await push(card, fake, today([wednesday]));
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 4 });
  expect(card.getCardSize()).toBe(4);

  await push(card, fake, today([wednesday, strength]));
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 7 });
  expect(card.getCardSize()).toBe(7);

  fake.pushSession({ available: true, session: sessionView("running") });
  await card.updateComplete;
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 4 });
  expect(card.getCardSize()).toBe(4);
});

test("is offered in the card picker, in English", () => {
  const entry = window.customCards?.find((card) => card.type === "ha-fitness-today-card");
  expect(entry?.name).toBe(en.picker.name);
  expect(entry?.description).toBe(en.picker.description);
});

/** A session view in the shape of spec §3.5. */
function sessionView(status: "running" | "paused" | "completed" | "ended", trainingDayId: number | null = 12) {
  const finished = status === "completed" || status === "ended";
  return {
    id: 7,
    revision: 1,
    status,
    counted: status === "completed",
    program_name: "Onsdag",
    training_day_id: trainingDayId,
    participants: [{ id: 1, name: "Thomas" }],
    phase: finished
      ? null
      : {
          index: 1,
          kind: "work",
          round: 1,
          interval: 1,
          duration: 45,
          ends_at: status === "running" ? "2026-10-24T08:00:45.000Z" : null,
          remaining: status === "paused" ? 30 : null,
        },
    next_phase: finished ? null : { kind: "switch", duration: 15 },
    stations: finished
      ? null
      : [
          {
            current: { number: 1, exercise_id: "0001", name: "Push-up" },
            next: { number: 2, exercise_id: "0002", name: "Squat" },
          },
        ],
    totals: { planned: 1740, rounds: 5, stations: 2 },
    started_at: "2026-10-24T08:00:10.000Z",
    ended_at: finished ? "2026-10-24T08:29:10.000Z" : null,
    rounds_completed: finished ? 5 : 0,
    time_trained: finished ? 1740 : 0,
    server_time: "2026-10-24T08:00:00.000Z",
  };
}

/** The one open overlay dialog, or null. */
function theDialog(): HTMLDialogElement | null {
  const dialogs = queryAllByRole(document.body, "dialog") as HTMLDialogElement[];
  expect(dialogs.length).toBeLessThanOrEqual(1);
  return dialogs[0] ?? null;
}


/** The shadow root of the flow in the open overlay, for queries. */
function flowRoot(): HTMLElement {
  const flow = theDialog()?.firstElementChild;
  expect(flow?.shadowRoot).toBeTruthy();
  return flow!.shadowRoot as unknown as HTMLElement;
}

/** The `ha_fitness/session/command` messages sent so far. */
function sessionCommands(fake: { callWS: { mock: { calls: [Message][] } } }): Message[] {
  return fake.callWS.mock.calls.map(([message]) => message).filter((message) => message.type === "ha_fitness/session/command");
}

/** The overlay shows the running or paused session: the timer with Slut, not the details' Start. */
function showsTimer(): boolean {
  return queryByRole(flowRoot(), "button", { name: "Slut" }) !== null && queryByRole(flowRoot(), "button", { name: "Start" }) === null;
}

/** The calls of `resume()` on the page's audio contexts so far; each unlock of a locked page makes one. */
function resumes(): number {
  return audio.contexts.reduce((count, context) => count + context.resume.mock.calls.length, 0);
}

/** Lock the page's audio again, as a reload or a quiet tablet can. */
function lockAudio(): void {
  for (const context of audio.contexts) context.setState("suspended");
}

/** Record, at each moment the overlay opened, how many unlocks the page had seen. */
function audioAtOpen(): number[] {
  const seen: number[] = [];
  const showModal = HTMLDialogElement.prototype.showModal;
  const spy = vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    seen.push(resumes());
    showModal.call(this);
  });
  onTestFinished(() => spy.mockRestore());
  return seen;
}

test("Start opens overlay with the day, nothing started, audio unlocked synchronously", async () => {
  const opened = audioAtOpen();
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday, strength]));

  // Start sits next to Spring over, before it, so Spring over and Nej keep the last place.
  expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);
  expect(theDialog()).toBeNull();

  lockAudio();
  const before = resumes();
  getByRole(rows(card)[0], "button", { name: "Start" }).click();
  // Synchronously, in the tap: the audio unlocked before the overlay opened.
  expect(resumes()).toBe(before + 1);
  expect(opened).toEqual([before + 1]);
  expect(theDialog()?.open).toBe(true);

  // The details of the day's program show; nothing is started until the flow's own Start, which
  // starts the day's training.
  await wait(card, 0);
  expect(text(flowRoot())).toContain("Onsdag");
  expect(sessionCommands(fake)).toEqual([]);
  getByRole(flowRoot(), "button", { name: "Start" }).click();
  await wait(card, 0);
  expect(sessionCommands(fake)).toEqual([
    { type: "ha_fitness/session/command", command: "start", program_id: 3, participants: [1], training_day_id: 12 },
  ]);
});

test("Start is hidden while Spring over asks", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  await tap(card, getByRole(rows(card)[0], "button", { name: "Spring over" }));
  expect(buttonNames(rows(card)[0])).toEqual(["Ja", "Nej"]);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Nej" }));
  expect(buttonNames(rows(card)[0])).toEqual(["Start", "Spring over"]);
});

test("Fortsæt while session active unlocks audio and resumes; Spring over hidden", async () => {
  const opened = audioAtOpen();
  const expected = {
    running: "Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt",
    paused: "Onsdag Pauset · runde 1 af 5 Thomas · 29 min Fortsæt",
  };
  for (const status of ["running", "paused"] as const) {
    opened.length = 0;
    const fake = fakeHass();
    const card = await mount(fake);
    await push(card, fake, today([wednesday, strength]));

    fake.pushSession({ available: true, session: sessionView(status) });
    await card.updateComplete;
    expect(rows(card).map(text)).toEqual([expected[status]]);
    expect(queryByRole(root(card), "button", { name: "Spring over" })).toBeNull();
    expect(queryByRole(root(card), "button", { name: "Start" })).toBeNull();

    // A reload, or a tablet that went quiet, can leave the page's audio suspended.
    lockAudio();
    const before = resumes();
    getByRole(root(card), "button", { name: "Fortsæt" }).click();
    // Synchronously, in the tap: the audio unlocked before the overlay opened.
    expect(resumes()).toBe(before + 1);
    expect(opened).toEqual([before + 1]);
    await wait(card, 0);
    expect(showsTimer()).toBe(true);

    overlay.close();
    card.remove();
  }

  // In English too.
  const english = fakeHass("en");
  const card = await mount(english);
  english.pushSession({ available: true, session: sessionView("running") });
  await card.updateComplete;
  expect(rows(card).map(text)).toEqual(["Onsdag Running · round 1 of 5 Thomas · 29 min Continue"]);
});

/** The session row's text, once the session is pushed to a card on a Danish (or the given) HA. */
async function sessionRow(session: ReturnType<typeof sessionView>, language = "da"): Promise<string> {
  const fake = fakeHass(language);
  const card = await mount(fake);
  fake.pushSession({ available: true, session });
  await card.updateComplete;
  const [row] = rows(card).map(text);
  card.remove();
  return row;
}

test("a two-person session joins the names with og", async () => {
  const session = {
    ...sessionView("running"),
    participants: [
      { id: 1, name: "Thomas" },
      { id: 2, name: "Elin" },
    ],
  };
  expect(await sessionRow(session)).toContain("Thomas og Elin · 29 min");
});

test("the running row rounds the planned time to the nearest minute", async () => {
  const base = sessionView("running");
  expect(await sessionRow({ ...base, totals: { ...base.totals, planned: 1769 } })).toContain("· 29 min");
  expect(await sessionRow({ ...base, totals: { ...base.totals, planned: 1770 } })).toContain("· 30 min");
});

test("a session without a phase reads I gang alone", async () => {
  expect(await sessionRow({ ...sessionView("running"), phase: null })).toBe("Onsdag I gang Thomas · 29 min Fortsæt");
});

test("the running row in English", async () => {
  expect(await sessionRow(sessionView("running"), "en")).toBe("Onsdag Running · round 1 of 5 Thomas · 29 min Continue");
});

test("after a completed view the today card shows no Fortsæt and hides when nothing is open", async () => {
  for (const status of ["completed", "ended"] as const) {
    const fake = fakeHass();
    const card = await mount(fake);
    await push(card, fake, today([wednesday]));
    fake.pushSession({ available: true, session: sessionView("running") });
    await card.updateComplete;
    expect(rows(card).map(text)).toEqual(["Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt"]);

    // The finished view is kept for 5 minutes, but it is not an active session.
    fake.pushSession({ available: true, session: sessionView(status) });
    await card.updateComplete;
    expect(queryByRole(root(card), "button", { name: "Fortsæt" })).toBeNull();
    expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);

    await push(card, fake, today([]));
    expect(card.hidden).toBe(true);
    card.remove();
  }
});

test("today card visible during extra session with nothing open", async () => {
  const events = visibilityEvents();
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([]));
  expect(card.hidden).toBe(true);

  // An extra session, from the workout card: no training day, nothing open.
  fake.pushSession({ available: true, session: sessionView("running", null) });
  await card.updateComplete;
  expect(card.hidden).toBe(false);
  expect(card.style.display).toBe("");
  expect(text(root(card))).toBe("TRÆNING Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt");
  expect(card.getGridOptions()).toEqual({ columns: "full", rows: 4 });

  // The add-on unreachable: the last view still counts as active, so the card stays.
  fake.pushSession({ available: false, session: sessionView("paused", null) });
  await card.updateComplete;
  expect(card.hidden).toBe(false);

  fake.pushSession({ available: true, session: sessionView("completed", null) });
  await card.updateComplete;
  expect(card.hidden).toBe(true);
  expect(events).toEqual([HIDE, SHOW, HIDE]);
});

test("a card that connects during a session shows Fortsæt at once", async () => {
  const fake = fakeHass("da", { available: true, session: sessionView("running") });
  const first = await mount(fake);
  expect(text(root(first))).toBe("TRÆNING Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt");

  // A second card on the page: the controller already holds the session.
  const second = document.createElement("ha-fitness-today-card") as unknown as CardElement;
  second.setConfig({ type: "custom:ha-fitness-today-card" });
  second.hass = fake.hass;
  document.body.append(second);
  await second.updateComplete;
  expect(second.hidden).toBe(false);
  expect(text(root(second))).toBe("TRÆNING Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt");
});

test("the card's language option carries into the flow, from Start and from Fortsæt", async () => {
  const fake = fakeHass("en");
  const card = await mount(fake, { language: "da" });
  await push(card, fake, today([wednesday]));

  getByRole(rows(card)[0], "button", { name: "Start" }).click();
  await wait(card, 0);
  expect(getByRole(flowRoot(), "button", { name: "Tilbage" })).toBeTruthy();
  overlay.close();

  fake.pushSession({ available: true, session: sessionView("running") });
  await card.updateComplete;
  getByRole(root(card), "button", { name: "Fortsæt" }).click();
  await wait(card, 0);
  expect(getByRole(flowRoot(), "button", { name: "Slut" })).toBeTruthy();
});

/** A stats message in the shape of `ha_fitness/stats/subscribe` (spec §5.1). */
function statsMessage(
  people: { name: string; streak: number }[],
  options: { available?: boolean; countingFrom?: string | null } = {},
) {
  const zero = { done: 0, extra: 0, missed: 0, skipped: 0, time_trained: 0 };
  return {
    available: options.available ?? true,
    stats: {
      counting_from: options.countingFrom === undefined ? "2026-10-01" : options.countingFrom,
      month: "2026-10",
      people: people.map((person, index) => ({
        id: index + 1,
        name: person.name,
        person_entity_id: `person.p${index + 1}`,
        streak: person.streak,
        all_time: zero,
        this_month: zero,
      })),
    },
  };
}

async function pushStats(card: CardElement, fake: Fake, message: unknown): Promise<void> {
  fake.pushStats(message);
  await card.updateComplete;
}

/** The streak badge: the card's one `img` (its icons are all aria-hidden), whatever the language. */
function streakBadge(card: CardElement): HTMLElement | null {
  return queryByRole(root(card), "img");
}

function weekRing(card: CardElement, name: string): HTMLElement | null {
  return queryByRole(root(card), "progressbar", { name });
}

test("streak badge shows initials, numbers and an accessible name", async () => {
  const fake = fakeHass("da");
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));
  expect(fake.subscribeStats).toHaveBeenCalledWith(
    expect.any(Function),
    { type: "ha_fitness/stats/subscribe" },
    { resubscribe: false },
  );

  await pushStats(card, fake, statsMessage([{ name: "Thomas", streak: 6 }, { name: "Elin", streak: 4 }]));
  const badge = getByRole(root(card), "img", { name: "I træk: Thomas 6, Elin 4" });
  expect(text(badge)).toBe("T 6 E 4");
  // The top line: the title on the left, the badge on the right.
  expect(text(root(card)).startsWith("TRÆNING T 6 E 4")).toBe(true);

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, today([wednesday]));
  await pushStats(englishCard, english, statsMessage([{ name: "Elin", streak: 0 }]));
  expect(text(getByRole(root(englishCard), "img", { name: "Streak: Elin 0" }))).toBe("E 0");
  expect(text(root(englishCard)).startsWith("TRAINING E 0")).toBe(true);
});

test("two-letter initials on a clash", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));
  await pushStats(card, fake, statsMessage([{ name: "Thomas", streak: 6 }, { name: "Tina", streak: 2 }]));
  const badge = getByRole(root(card), "img", { name: "I træk: Thomas 6, Tina 2" });
  expect(text(badge)).toBe("Th 6 Ti 2");
});

test("streak badge hidden before counting, while stats are unavailable or refused, and with no people", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));
  // No stats message yet.
  expect(streakBadge(card)).toBeNull();

  const people = [{ name: "Thomas", streak: 6 }];
  await pushStats(card, fake, statsMessage(people, { countingFrom: null }));
  expect(streakBadge(card)).toBeNull();

  await pushStats(card, fake, statsMessage(people));
  expect(streakBadge(card)).not.toBeNull();

  await pushStats(card, fake, statsMessage(people, { available: false }));
  expect(streakBadge(card)).toBeNull();

  await pushStats(card, fake, { available: false, stats: null });
  expect(streakBadge(card)).toBeNull();

  await pushStats(card, fake, statsMessage([]));
  expect(streakBadge(card)).toBeNull();

  // A refused subscription: shown with good stats, then refused after a reconnect.
  await pushStats(card, fake, statsMessage(people));
  expect(streakBadge(card)).not.toBeNull();
  fake.subscribeStats.mockRejectedValue({ code: "unknown_command" });
  fake.fire("ready");
  await wait(card, 0);
  expect(streakBadge(card)).toBeNull();
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);
});

test("stats alone never show a hidden card", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([]));
  await pushStats(card, fake, statsMessage([{ name: "Thomas", streak: 6 }]));
  expect(card.hidden).toBe(true);
});

test("week ring shows done of planned", async () => {
  const fake = fakeHass("da");
  const card = await mount(fake);
  await push(card, fake, { ...today([wednesday]), week: { done: 2, planned: 4 } });
  const ring = weekRing(card, "Denne uge")!;
  expect(ring).not.toBeNull();
  expect(ring.getAttribute("aria-valuenow")).toBe("2");
  expect(ring.getAttribute("aria-valuemax")).toBe("4");
  expect(text(ring)).toBe("2/4 Denne uge");

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, { ...today([wednesday]), week: { done: 3, planned: 4 } });
  const englishRing = weekRing(englishCard, "This week")!;
  expect(englishRing.getAttribute("aria-valuenow")).toBe("3");
  expect(englishRing.getAttribute("aria-valuemax")).toBe("4");
  expect(text(englishRing)).toBe("3/4 This week");
});

test("no ring without week or with planned 0", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  // An older add-on sends no week (spec §4): the card still works, with no ring.
  await push(card, fake, today([wednesday]));
  expect(queryByRole(root(card), "progressbar")).toBeNull();
  expect(rows(card).map(text)).toEqual(["Onsdag I dag 5 øvelser · 29 min Start Spring over"]);

  await push(card, fake, { ...today([wednesday]), week: { done: 0, planned: 0 } });
  expect(queryByRole(root(card), "progressbar")).toBeNull();
});

test("due day says I dag, late day keeps Forfalden", async () => {
  const fake = fakeHass("da");
  const card = await mount(fake);
  await push(card, fake, today([wednesday, { ...strength, state: "late", date: "2026-10-23" }]));
  expect(rows(card).map(text)).toEqual([
    "Onsdag I dag 5 øvelser · 29 min Start Spring over",
    "Styrke Forfalden · fredag 1 øvelse · 12 min Start Spring over",
  ]);

  const english = fakeHass("en");
  const englishCard = await mount(english);
  await push(englishCard, english, today([wednesday, { ...strength, state: "late", date: "2026-10-23" }]));
  expect(rows(englishCard).map(text)).toEqual([
    "Onsdag Today 5 exercises · 29 min Start Skip",
    "Styrke Late · Friday 1 exercise · 12 min Start Skip",
  ]);
});

test("Start comes before Spring over, and Spring over keeps its two taps", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, today([wednesday]));

  const row = rows(card)[0];
  const [start, skip] = getAllByRole(row, "button");
  expect([text(start), text(skip)]).toEqual(["Start", "Spring over"]);
  // The buttons come after the day's text, under it.
  expect(text(row)).toBe("Onsdag I dag 5 øvelser · 29 min Start Spring over");

  await tap(card, skip);
  expect(fake.callService).not.toHaveBeenCalled();
  expect(text(rows(card)[0])).toBe("Onsdag Spring over? 5 øvelser · 29 min Ja Nej");
  await wait(card, 500);
  await tap(card, getByRole(rows(card)[0], "button", { name: "Ja" }));
  expect(fake.callService).toHaveBeenCalledWith("ha_fitness", "skip", { training_day_id: 12 }, undefined, false);
});

test("several open days share one top line and ring", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, { ...today([wednesday, strength]), week: { done: 1, planned: 3 } });
  await pushStats(card, fake, statsMessage([{ name: "Thomas", streak: 6 }]));

  expect(rows(card)).toHaveLength(2);
  expect(queryAllByRole(root(card), "progressbar")).toHaveLength(1);
  expect(queryAllByRole(root(card), "img")).toHaveLength(1);
  expect(text(root(card)).match(/TRÆNING/g)).toHaveLength(1);
});

test("the week ring sits in the first row only", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, { ...today([wednesday, strength]), week: { done: 2, planned: 4 } });

  const [first, second] = rows(card);
  expect(getByRole(first, "progressbar", { name: "Denne uge" })).toBeTruthy();
  expect(queryByRole(second, "progressbar")).toBeNull();
  expect(rows(card).map(text)).toEqual([
    "2/4 Denne uge Onsdag I dag 5 øvelser · 29 min Start Spring over",
    "Styrke I dag 1 øvelse · 12 min Start Spring over",
  ]);
});

test("session row replaces the days but keeps the top line", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  await push(card, fake, { ...today([wednesday, strength]), week: { done: 2, planned: 4 } });
  await pushStats(card, fake, statsMessage([{ name: "Thomas", streak: 6 }]));

  fake.pushSession({ available: true, session: sessionView("running") });
  await card.updateComplete;
  // The ring sits in the session row, before its text.
  expect(rows(card).map(text)).toEqual(["2/4 Denne uge Onsdag I gang · runde 1 af 5 Thomas · 29 min Fortsæt"]);
  expect(getByRole(rows(card)[0], "progressbar", { name: "Denne uge" })).toBeTruthy();
  expect(getByRole(root(card), "img", { name: "I træk: Thomas 6" })).toBeTruthy();
  expect(weekRing(card, "Denne uge")?.getAttribute("aria-valuenow")).toBe("2");
  expect(text(root(card)).startsWith("TRÆNING T 6")).toBe(true);
});
