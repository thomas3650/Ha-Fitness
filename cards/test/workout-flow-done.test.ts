import { getAllByRole, getByRole, queryByRole, queryByText } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";
import type { OverlayMode, SessionState, SessionView } from "../src/overlay";
import type { StatsMessage } from "../src/stats-card";
import { installFakeAudio } from "./fake-audio";

// The flow element is defined once for the file; the audio and image modules keep page-wide state.
installFakeAudio("running");
vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:image");

/** The properties the overlay controller sets on the flow. */
interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: OverlayMode;
  onClose?: () => void;
  updateComplete: Promise<boolean>;
}

const thomas = { id: 1, name: "Thomas" };
const maria = { id: 2, name: "Maria" };

type Message = { type: string } & Record<string, unknown>;

/** A deferred answer to one `ha_fitness/session/command`. */
interface Pending {
  message: Message;
  resolve(view: SessionView): void;
  reject(error: unknown): void;
}

/**
 * A fake `hass`: `callWS` for the commands, each waiting for the test, and a connection whose
 * stats subscriptions the test feeds by hand.
 */
function fakeHass(language = "da") {
  const commands: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/people") return Promise.resolve([thomas, maria]);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve, reject) => commands.push({ message, resolve, reject }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  const fetchWithAuth = vi.fn(async () => new Response(new Blob(["GIF89a"]), { status: 200 }));
  const stats: ((message: StatsMessage) => void)[] = [];
  const unsubscribe = vi.fn();
  const subscribeMessage = vi.fn(async (callback: (message: never) => void, message: { type: string }) => {
    if (message.type === "ha_fitness/stats/subscribe") stats.push(callback as (message: StatsMessage) => void);
    return unsubscribe;
  });
  const connection = { subscribeMessage };
  return {
    hass: { locale: { language }, callWS, fetchWithAuth, connection },
    commands,
    subscribeMessage,
    unsubscribe,
    /** Send a stats message to the newest stats subscription. */
    sendStats(message: StatsMessage) {
      stats.at(-1)?.(message);
    },
  };
}

type Fake = ReturnType<typeof fakeHass>;

function statsMessage(streaks: [number, string, number][]): StatsMessage {
  const totals = { done: 0, extra: 0, missed: 0, skipped: 0, time_trained: 0 };
  return {
    available: true,
    stats: {
      counting_from: "2026-10-01",
      month: "2026-10",
      people: streaks.map(([id, name, streak]) => ({
        id,
        name,
        person_entity_id: `person.${name.toLowerCase()}`,
        streak,
        all_time: totals,
        this_month: totals,
      })),
    },
  };
}

/** A running two-person session, as the add-on sends it at 08:00:00. */
function running(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: 7,
    revision: 10,
    status: "running",
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [thomas, maria],
    phase: {
      index: 3,
      kind: "work",
      round: 2,
      interval: 1,
      duration: 45,
      ends_at: "2026-10-24T08:00:45.000Z",
      remaining: null,
    },
    next_phase: { kind: "switch", duration: 15 },
    stations: [
      { current: { number: 1, exercise_id: "0001", name: "Push-up" }, next: null },
      { current: { number: 2, exercise_id: "0002", name: "Squat" }, next: null },
    ],
    totals: { planned: 1740, rounds: 5 },
    started_at: "2026-10-24T07:54:00.000Z",
    ended_at: null,
    rounds_completed: 1,
    time_trained: 360,
    server_time: "2026-10-24T08:00:00.000Z",
    ...overrides,
  };
}

/** A completed session, rated nothing yet, as the add-on sends it at the finish. */
function completed(overrides: Partial<SessionView> = {}): SessionView {
  return running({
    revision: 40,
    status: "completed",
    counted: true,
    phase: null,
    next_phase: null,
    stations: null,
    ended_at: "2026-10-24T08:25:00.000Z",
    rounds_completed: 5,
    time_trained: 1530,
    server_time: "2026-10-24T08:25:00.000Z",
    feeling: null,
    ...overrides,
  });
}

/** An ended session, counted after a round or not counted. */
function ended(counted: boolean, overrides: Partial<SessionView> = {}): SessionView {
  return completed({
    status: "ended",
    counted,
    rounds_completed: counted ? 2 : 0,
    time_trained: counted ? 720 : 20,
    ...overrides,
  });
}

/** Put the flow on the page the way the overlay controller does, resuming the session `session`. */
async function mount(fake: Fake, session: SessionView | null) {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  const onClose = vi.fn();
  flow.hass = fake.hass;
  flow.state = { available: true, session };
  flow.mode = { kind: "resume" };
  flow.onClose = onClose;
  await settle(flow);
  return { flow, onClose };
}

async function settle(flow: FlowElement): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
  await flow.updateComplete;
}

async function wait(flow: FlowElement, ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
  await flow.updateComplete;
}

async function tap(flow: FlowElement, element: HTMLElement): Promise<void> {
  element.click();
  await settle(flow);
}

async function push(flow: FlowElement, session: SessionView | null): Promise<void> {
  flow.state = { available: true, session };
  await settle(flow);
}

function root(flow: FlowElement): HTMLElement {
  return flow.shadowRoot as unknown as HTMLElement;
}

function text(element: HTMLElement): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function button(flow: FlowElement, name: string): HTMLButtonElement {
  return getByRole(root(flow), "button", { name }) as HTMLButtonElement;
}

function heading(flow: FlowElement): string {
  return text(getByRole(root(flow), "heading"));
}

/** The tiles: each one's label and value. */
function tiles(flow: FlowElement): [string, string][] {
  const terms = getAllByRole(root(flow), "term").map(text);
  const definitions = getAllByRole(root(flow), "definition").map(text);
  return terms.map((term, index) => [term, definitions[index]]);
}

/** The feeling buttons' names and `aria-pressed`, or null without the group. */
function feelings(flow: FlowElement, name: string): [string, string | null][] | null {
  const group = queryByRole(root(flow), "group", { name });
  if (!group) return null;
  return getAllByRole(group, "button").map((element) => [text(element), element.getAttribute("aria-pressed")]);
}

function hasText(flow: FlowElement, value: string | RegExp): boolean {
  return queryByText(root(flow), value) !== null;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:25:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("complete: the check, the title, the program and the local date, and the tiles", async () => {
  // 23:30 UTC on Wednesday is 01:30 on Thursday in Copenhagen (the tests' time zone).
  const fake = fakeHass("da");
  const { flow } = await mount(fake, running());
  await push(flow, completed({ started_at: "2026-10-21T23:30:00.000Z" }));

  expect(getByRole(root(flow), "img", { name: "Gennemført" })).toBeTruthy();
  expect(heading(flow)).toBe("Træning gennemført");
  expect(hasText(flow, "Onsdag · torsdag 22. oktober")).toBe(true);
  // The streak tile waits for the stats.
  expect(tiles(flow)).toEqual([
    ["Tid", "25:30"],
    ["Runder", "5 / 5"],
    ["Trænede", "Thomas, Maria"],
  ]);
  expect(queryByRole(root(flow), "progressbar")).toBeNull();

  const en = await mount(fakeHass("en"), completed({ started_at: "2026-10-21T23:30:00.000Z" }));
  expect(getByRole(root(en.flow), "img", { name: "Completed" })).toBeTruthy();
  expect(heading(en.flow)).toBe("Workout complete");
  expect(hasText(en.flow, "Onsdag · Thursday 22 October")).toBe(true);
  expect(tiles(en.flow)).toEqual([
    ["Time", "25:30"],
    ["Rounds", "5 / 5"],
    ["Trained", "Thomas, Maria"],
  ]);
});

test("the streak tile shows each participant's streak once the stats arrive", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, running());
  // The flow subscribes to the stats only while done shows.
  const statsSubscriptions = () =>
    fake.subscribeMessage.mock.calls.filter(([, message]) => message.type === "ha_fitness/stats/subscribe").length;
  expect(statsSubscriptions()).toBe(0);

  await push(flow, completed());
  expect(statsSubscriptions()).toBe(1);
  // Matched by person id; someone who didn't train isn't shown.
  fake.sendStats(statsMessage([[3, "Elin", 9], [2, "Maria", 3], [1, "Thomas", 7]]));
  await settle(flow);
  expect(tiles(flow)).toEqual([
    ["Tid", "25:30"],
    ["Runder", "5 / 5"],
    ["Trænede", "Thomas, Maria"],
    ["I træk", "Thomas 7 Maria 3"],
  ]);

  // It follows the stats as they change after the finish.
  fake.sendStats(statsMessage([[1, "Thomas", 8], [2, "Maria", 4]]));
  await settle(flow);
  expect(tiles(flow).at(-1)).toEqual(["I træk", "Thomas 8 Maria 4"]);

  // While the add-on is unreachable there are no streaks to show.
  fake.sendStats({ available: false, stats: null });
  await settle(flow);
  expect(tiles(flow).map(([label]) => label)).toEqual(["Tid", "Runder", "Trænede"]);

  // Leaving the page stops the subscription.
  flow.remove();
  await vi.advanceTimersByTimeAsync(0);
  expect(fake.unsubscribe).toHaveBeenCalled();
});

test("the streak tile in English", async () => {
  const fake = fakeHass("en");
  const { flow } = await mount(fake, completed());
  fake.sendStats(statsMessage([[1, "Thomas", 7], [2, "Maria", 3]]));
  await settle(flow);
  expect(tiles(flow).at(-1)).toEqual(["Streak", "Thomas 7 Maria 3"]);
});

test("how it felt: a tap sends the command, and the mark follows the view", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, completed());
  expect(feelings(flow, "Hvordan føltes det?")).toEqual([
    ["For let", "false"],
    ["Tilpas", "false"],
    ["For hårdt", "false"],
  ]);

  await tap(flow, button(flow, "Tilpas"));
  expect(fake.commands.map((command) => command.message)).toEqual([
    { type: "ha_fitness/session/command", command: "feeling", feeling: "just_right" },
  ]);
  // The mark is the view's, not the tap's.
  expect(feelings(flow, "Hvordan føltes det?")?.[1]).toEqual(["Tilpas", "false"]);
  fake.commands[0].resolve(completed({ revision: 41, feeling: "just_right" }));
  await settle(flow);
  expect(feelings(flow, "Hvordan føltes det?")).toEqual([
    ["For let", "false"],
    ["Tilpas", "true"],
    ["For hårdt", "false"],
  ]);

  // A second tap on another changes it.
  await tap(flow, button(flow, "For hårdt"));
  expect(fake.commands[1].message).toEqual({
    type: "ha_fitness/session/command",
    command: "feeling",
    feeling: "too_hard",
  });
  fake.commands[1].resolve(completed({ revision: 42, feeling: "too_hard" }));
  await settle(flow);
  expect(feelings(flow, "Hvordan føltes det?")).toEqual([
    ["For let", "false"],
    ["Tilpas", "false"],
    ["For hårdt", "true"],
  ]);

  // A push from another tablet moves the mark too.
  await push(flow, completed({ revision: 43, feeling: "too_easy" }));
  expect(feelings(flow, "Hvordan føltes det?")?.[0]).toEqual(["For let", "true"]);

  const en = await mount(fakeHass("en"), completed({ feeling: "just_right" }));
  expect(feelings(en.flow, "How did it feel?")).toEqual([
    ["Too easy", "false"],
    ["Just right", "true"],
    ["Too hard", "false"],
  ]);
});

test("a failed tap shows one text per code under the buttons", async () => {
  const cases: [string, string, string][] = [
    ["da", "conflict", "Træningen kan ikke længere vurderes."],
    ["da", "invalid", "Det svar kendes ikke."],
    ["da", "unavailable", "HA Fitness kan ikke nås. Prøv igen senere."],
    ["da", "unknown_error", "Noget gik galt. Prøv igen."],
    ["en", "conflict", "This workout can no longer be rated."],
    ["en", "invalid", "That answer isn't known."],
    ["en", "unavailable", "HA Fitness can't be reached. Try again later."],
    ["en", "unknown_error", "Something went wrong. Try again."],
  ];
  for (const [language, code, message] of cases) {
    const fake = fakeHass(language);
    const { flow } = await mount(fake, completed());
    await tap(flow, button(flow, language === "da" ? "For let" : "Too easy"));
    fake.commands[0].reject({ code, message: "Refused." });
    await settle(flow);
    expect(text(getByRole(root(flow), "alert")), code).toBe(message);
    document.body.replaceChildren();
  }

  // The next tap clears the error.
  const fake = fakeHass("da");
  const { flow } = await mount(fake, completed());
  await tap(flow, button(flow, "For let"));
  fake.commands[0].reject({ code: "unavailable", message: "Refused." });
  await settle(flow);
  await tap(flow, button(flow, "For let"));
  expect(queryByRole(root(flow), "alert")).toBeNull();
});

test("done closes by itself after 60 s, and a tap on a feeling starts that over", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, running());
  await push(flow, completed());

  // A later push of the same view doesn't start the 60 s over.
  await wait(flow, 30_000);
  await push(flow, completed());
  await wait(flow, 20_000);

  // A tap at 50 s does, and its result doesn't start it over again.
  await tap(flow, button(flow, "Tilpas"));
  await wait(flow, 5_000);
  fake.commands[0].resolve(completed({ revision: 41, feeling: "just_right" }));
  await wait(flow, 54_999);
  expect(onClose).not.toHaveBeenCalled();
  await wait(flow, 1);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("a failed tap starts the 60 s over too", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, completed());
  await wait(flow, 50_000);
  await tap(flow, button(flow, "Tilpas"));
  fake.commands[0].reject({ code: "unavailable", message: "Refused." });
  await wait(flow, 59_999);
  expect(onClose).not.toHaveBeenCalled();
  await wait(flow, 1);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("Færdig closes", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, completed());
  await tap(flow, button(flow, "Færdig"));
  expect(onClose).toHaveBeenCalledTimes(1);
  await wait(flow, 60_000);
  expect(onClose).toHaveBeenCalledTimes(1);

  const en = await mount(fakeHass("en"), completed());
  await tap(en.flow, button(en.flow, "Done"));
  expect(en.onClose).toHaveBeenCalledTimes(1);
});

test("no feeling buttons from an add-on that sends no feeling", async () => {
  const view = completed();
  delete view.feeling;
  const { flow } = await mount(fakeHass("da"), view);
  expect(heading(flow)).toBe("Træning gennemført");
  expect(feelings(flow, "Hvordan føltes det?")).toBeNull();
  expect(hasText(flow, "Tilpas")).toBe(false);
});

test("ended and counted: the check, how far it got, the four tiles, and no feeling buttons", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, running());
  await push(flow, ended(true));
  expect(getByRole(root(flow), "img", { name: "Gennemført" })).toBeTruthy();
  expect(heading(flow)).toBe("Afsluttet efter 2 af 5 runder");
  fake.sendStats(statsMessage([[1, "Thomas", 7], [2, "Maria", 3]]));
  await settle(flow);
  expect(tiles(flow)).toEqual([
    ["Tid", "12:00"],
    ["Runder", "2 / 5"],
    ["Trænede", "Thomas, Maria"],
    ["I træk", "Thomas 7 Maria 3"],
  ]);
  expect(feelings(flow, "Hvordan føltes det?")).toBeNull();
  await tap(flow, button(flow, "Færdig"));
  expect(onClose).toHaveBeenCalledTimes(1);

  const en = await mount(fakeHass("en"), ended(true));
  expect(heading(en.flow)).toBe("Ended after 2 of 5 rounds");
});

test("ended, not counted: the title, time, rounds and who trained; no check, streak or feeling", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, ended(false));
  expect(heading(flow)).toBe("Træningen blev afsluttet");
  expect(queryByRole(root(flow), "img")).toBeNull();
  fake.sendStats(statsMessage([[1, "Thomas", 7], [2, "Maria", 3]]));
  await settle(flow);
  expect(tiles(flow)).toEqual([
    ["Tid", "0:20"],
    ["Runder", "0 / 5"],
    ["Trænede", "Thomas, Maria"],
  ]);
  expect(feelings(flow, "Hvordan føltes det?")).toBeNull();
  await tap(flow, button(flow, "Færdig"));
  expect(onClose).toHaveBeenCalledTimes(1);
  await wait(flow, 60_000);
  expect(onClose).toHaveBeenCalledTimes(1);

  const en = await mount(fakeHass("en"), ended(false));
  expect(heading(en.flow)).toBe("The workout was ended");
  expect(tiles(en.flow).map(([label]) => label)).toEqual(["Time", "Rounds", "Trained"]);
});
