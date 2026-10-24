import { getAllByRole, getByRole, queryAllByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, onTestFinished, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/index";
import * as overlay from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// One audio context for the page (audio.ts keeps it at module level), so one fake for the file.
const audio = installFakeAudio("suspended");

interface Program {
  id: number;
  name: string;
  rounds: number;
  work_seconds: number;
  switch_seconds: number;
  round_rest_seconds: number;
  countdown_seconds: number;
  total_minutes: number;
  stations: { exercise_id: string; name: string }[];
}

/** The parts of the card's interface that Home Assistant's `hui-card` and the dashboard use. */
interface CardElement extends HTMLElement {
  setConfig(config: { type: string; language?: string }): void;
  hass?: unknown;
  getCardSize(): number;
  updateComplete: Promise<boolean>;
}

/** The flow element the overlay controller put in its dialog. */
interface FlowElement extends HTMLElement {
  mode?: unknown;
}

const stations = (count: number) =>
  Array.from({ length: count }, (_, i) => ({ exercise_id: `000${i + 1}`, name: `Øvelse ${i + 1}` }));

const onsdag: Program = {
  id: 3,
  name: "Onsdag",
  rounds: 5,
  work_seconds: 45,
  switch_seconds: 15,
  round_rest_seconds: 60,
  countdown_seconds: 10,
  total_minutes: 29,
  stations: stations(5),
};

const styrke: Program = { ...onsdag, id: 4, name: "Styrke", rounds: 1, total_minutes: 12, stations: stations(1) };

const NO_SESSION = { available: true, session: null };

type Listener = (message: unknown) => void;
type Message = { type: string } & Record<string, unknown>;

/**
 * A fake `hass` for §4's commands: `ha_fitness/programs` answers `programs` (the test may change
 * it), `ha_fitness/people` one person, and the connection carries the page's
 * `ha_fitness/session/subscribe`, which sends at once as the integration does.
 */
function fakeHass(language = "da", initialSession: unknown = NO_SESSION) {
  const sessionListeners: Listener[] = [];
  const fake = {
    programs: [onsdag, styrke] as Program[] | Error,
    callWS: vi.fn((message: Message): Promise<unknown> => {
      if (message.type === "ha_fitness/programs") {
        return fake.programs instanceof Error ? Promise.reject(fake.programs) : Promise.resolve(fake.programs);
      }
      if (message.type === "ha_fitness/people") return Promise.resolve([{ id: 1, name: "Thomas" }]);
      return Promise.reject({ code: "unknown_command", message: "Unknown command." });
    }),
    pushSession(message: unknown) {
      const listener = sessionListeners.at(-1);
      if (!listener) throw new Error("nothing has subscribed to the session");
      listener(message);
    },
    hass: {} as Record<string, unknown>,
  };
  const connection = {
    subscribeMessage(callback: Listener, message: { type: string }) {
      if (message.type !== "ha_fitness/session/subscribe") return Promise.reject(new Error("unexpected"));
      sessionListeners.push(callback);
      void Promise.resolve().then(() => callback(initialSession));
      return Promise.resolve(vi.fn());
    },
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  };
  fake.hass = {
    locale: { language },
    callWS: fake.callWS,
    fetchWithAuth: vi.fn(async () => new Response(null, { status: 404 })),
    connection,
  };
  return fake;
}

type Fake = ReturnType<typeof fakeHass>;

/** A running or finished session view in the shape of spec §3.5, an extra session (no training day). */
function sessionView(status: "running" | "paused" | "completed") {
  const finished = status === "completed";
  return {
    id: 8,
    revision: 1,
    status,
    counted: finished,
    program_name: "Styrke",
    training_day_id: null,
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
    next_phase: finished ? null : { kind: "rest", duration: 60 },
    stations: finished ? null : [{ current: { number: 1, exercise_id: "0001", name: "Øvelse 1" }, next: null }],
    totals: { planned: 720, rounds: 1, stations: 1 },
    started_at: "2026-10-24T08:00:10.000Z",
    ended_at: finished ? "2026-10-24T08:12:10.000Z" : null,
    rounds_completed: finished ? 1 : 0,
    time_trained: finished ? 720 : 0,
    server_time: "2026-10-24T08:00:00.000Z",
  };
}

async function mount(fake: Fake, language?: string): Promise<CardElement> {
  const card = document.createElement("ha-fitness-workout-card") as unknown as CardElement;
  card.setConfig({ type: "custom:ha-fitness-workout-card", ...(language ? { language } : {}) });
  card.hass = fake.hass;
  document.body.append(card);
  await settle(card);
  return card;
}

/** Let promises settle (the fetch, the session's first message) and the card render. */
async function settle(card: CardElement): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
  await card.updateComplete;
}

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
function root(card: CardElement): HTMLElement {
  return card.shadowRoot as unknown as HTMLElement;
}

function text(element: HTMLElement): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function rows(card: CardElement): HTMLElement[] {
  return queryAllByRole(root(card), "listitem");
}

function programFetches(fake: Fake): number {
  return fake.callWS.mock.calls.filter(([message]) => message.type === "ha_fitness/programs").length;
}

function theDialog(): HTMLDialogElement | null {
  const dialogs = queryAllByRole(document.body, "dialog") as HTMLDialogElement[];
  expect(dialogs.length).toBeLessThanOrEqual(1);
  return dialogs[0] ?? null;
}

function flowMode(): unknown {
  return (theDialog()?.querySelector("ha-fitness-workout-flow") as FlowElement | null)?.mode;
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

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  // The overlay controller is page-wide and has no reset; each test closes what it opened.
  overlay.close();
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("workout card lists active programs and refetches before Start", async () => {
  const fake = fakeHass();
  const card = await mount(fake);
  expect(programFetches(fake)).toBe(1);
  expect(rows(card).map(text)).toEqual([
    "Onsdag 5 øvelser · 5 runder · ca. 29 min Start",
    "Styrke 1 øvelse · 1 runde · ca. 12 min Start",
  ]);

  // Claude turned Onsdag off since; Start fetches again and only opens a program still active.
  fake.programs = [styrke];
  getAllByRole(root(card), "button", { name: "Start" })[0].click();
  await settle(card);
  expect(programFetches(fake)).toBe(2);
  expect(theDialog()).toBeNull();
  expect(rows(card).map(text)).toEqual(["Styrke 1 øvelse · 1 runde · ca. 12 min Start"]);

  // In English.
  const english = fakeHass("en");
  const englishCard = await mount(english);
  expect(rows(englishCard).map(text)).toEqual([
    "Onsdag 5 exercises · 5 rounds · about 29 min Start",
    "Styrke 1 exercise · 1 round · about 12 min Start",
  ]);
});

test("no programs, and an unreachable add-on", async () => {
  const fake = fakeHass();
  fake.programs = [];
  const card = await mount(fake);
  expect(text(root(card))).toBe("Ingen aktive programmer");

  const failing = fakeHass();
  failing.programs = new Error("unavailable");
  const failed = await mount(failing);
  expect(text(root(failed))).toBe("HA Fitness kan ikke nås");

  // A Start refetch that fails still opens the details; the flow shows its own error.
  const flaky = fakeHass();
  const flakyCard = await mount(flaky);
  flaky.programs = new Error("unavailable");
  getByRole(rows(flakyCard)[0], "button", { name: "Start" }).click();
  await settle(flakyCard);
  expect(flowMode()).toEqual({ kind: "details", programId: 3 });
});

test("workout card Start opens details without training day", async () => {
  const opened = audioAtOpen();
  const fake = fakeHass();
  const card = await mount(fake);

  lockAudio();
  const before = resumes();
  getByRole(rows(card)[1], "button", { name: "Start" }).click();
  // Synchronously, in the tap, before the refetch awaits.
  expect(resumes()).toBe(before + 1);
  await settle(card);
  expect(opened).toEqual([before + 1]);
  expect(theDialog()?.open).toBe(true);
  expect(flowMode()).toEqual({ kind: "details", programId: 4 });
  // Nothing starts until the flow's own Start.
  expect(fake.callWS.mock.calls.some(([message]) => message.type === "ha_fitness/session/command")).toBe(false);
});

test("workout card Fortsæt", async () => {
  const opened = audioAtOpen();
  const fake = fakeHass();
  const card = await mount(fake);

  for (const status of ["running", "paused"] as const) {
    fake.pushSession({ available: true, session: sessionView(status) });
    await card.updateComplete;
    expect(text(root(card))).toBe("Træning i gang · Styrke Fortsæt");
    expect(queryByRole(root(card), "button", { name: "Start" })).toBeNull();

    opened.length = 0;
    lockAudio();
    const before = resumes();
    getByRole(root(card), "button", { name: "Fortsæt" }).click();
    // Synchronously, in the tap: the audio unlocked before the overlay opened.
    expect(resumes()).toBe(before + 1);
    expect(opened).toEqual([before + 1]);
    expect(flowMode()).toEqual({ kind: "resume" });
    overlay.close();
  }

  // A finished view is not an active session: the programs are back.
  fake.pushSession({ available: true, session: sessionView("completed") });
  await card.updateComplete;
  expect(queryByRole(root(card), "button", { name: "Fortsæt" })).toBeNull();
  expect(rows(card).map(text)).toHaveLength(2);

  // A card that connects during a session shows Fortsæt at once.
  const during = fakeHass("en", { available: true, session: sessionView("running") });
  const second = await mount(during);
  expect(text(root(second))).toBe("Workout in progress · Styrke Continue");
});

test("is offered in the card picker, in English", () => {
  const entry = window.customCards?.find((card) => card.type === "ha-fitness-workout-card");
  expect(entry?.name).toBe(en.picker_workout.name);
  expect(entry?.description).toBe(en.picker_workout.description);
});
