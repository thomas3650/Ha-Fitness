import { getAllByRole, getByRole, queryByRole, queryByText } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";
import type { OverlayMode, SessionState, SessionView } from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// One audio context for the page (audio.ts keeps it at module level), so one fake for the file.
installFakeAudio("suspended");

let objectUrls = 0;
vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:image-${++objectUrls}`);

/** The properties the overlay controller sets on the flow. */
interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: OverlayMode;
  onClose?: () => void;
  updateComplete: Promise<boolean>;
}

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
    { exercise_id: "custom-7", name: "Planke" },
  ],
};

const thomas = { id: 1, name: "Thomas" };
const maria = { id: 2, name: "Maria" };

type Message = { type: string } & Record<string, unknown>;

/** A deferred answer to one `ha_fitness/session/command`. */
interface Pending {
  message: Message;
  resolve(view: SessionView): void;
  reject(error: unknown): void;
}

/** A fake `hass` whose session commands wait until the test answers them. */
function fakeHass(language = "da") {
  const commands: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/programs") return Promise.resolve([onsdag]);
    if (message.type === "ha_fitness/people") return Promise.resolve([thomas, maria]);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve, reject) => commands.push({ message, resolve, reject }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  // Push-up has a picture; the other exercises have none.
  const fetchWithAuth = vi.fn(async (path: string) =>
    path.includes("/0001/")
      ? new Response(new Blob(["GIF89a"]), { status: 200 })
      : new Response(null, { status: 404 }),
  );
  return { hass: { locale: { language }, callWS, fetchWithAuth }, callWS, commands };
}

type Fake = ReturnType<typeof fakeHass>;

/** A session view on its countdown, in the shape of spec §3.5. */
function view(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: 7,
    revision: 1,
    status: "running",
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [thomas, maria],
    phase: {
      index: 0,
      kind: "countdown",
      round: 1,
      interval: 1,
      duration: 10,
      ends_at: "2026-10-24T08:00:10.000Z",
      remaining: null,
    },
    next_phase: { kind: "work", duration: 45 },
    stations: [
      {
        current: { number: 1, exercise_id: "0001", name: "Push-up" },
        next: { number: 2, exercise_id: "0002", name: "Squat" },
      },
      {
        current: { number: 2, exercise_id: "0002", name: "Squat" },
        next: { number: 3, exercise_id: "custom-7", name: "Planke" },
      },
    ],
    totals: { planned: 1740, rounds: 5 },
    started_at: "2026-10-24T08:00:10.000Z",
    ended_at: null,
    rounds_completed: 0,
    time_trained: 0,
    server_time: "2026-10-24T08:00:00.000Z",
    ...overrides,
  };
}

/** The countdown, paused with 7 s left (after an add-on stop, D40). */
function paused(overrides: Partial<SessionView> = {}): SessionView {
  return view({
    status: "paused",
    phase: { ...view().phase!, ends_at: null, remaining: 7 },
    ...overrides,
  });
}

const NO_SESSION: SessionState = { available: true, session: null };

async function mount(fake: Fake, mode: OverlayMode, state: SessionState = NO_SESSION) {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  const onClose = vi.fn();
  flow.hass = fake.hass;
  flow.state = state;
  flow.mode = mode;
  flow.onClose = onClose;
  await settle(flow);
  return { flow, onClose };
}

/** Get ready for a running session, as Fortsæt opens it. */
async function resume(fake: Fake, session: SessionView = view()) {
  return mount(fake, { kind: "resume" }, { available: true, session });
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

async function push(flow: FlowElement, session: SessionView | null, available = true): Promise<void> {
  flow.state = { available, session };
  await settle(flow);
}

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
function root(flow: FlowElement): HTMLElement {
  return flow.shadowRoot as unknown as HTMLElement;
}

function text(element: HTMLElement): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function button(flow: FlowElement, name: string | RegExp): HTMLButtonElement {
  return getByRole(root(flow), "button", { name }) as HTMLButtonElement;
}

function sessionCommands(fake: Fake): Message[] {
  return fake.commands.map((command) => command.message);
}

/** The start cards, one per participant. */
function cards(flow: FlowElement, name: string): HTMLElement[] {
  return getAllByRole(getByRole(root(flow), "list", { name }), "listitem");
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("the summary pill in Danish and English", async () => {
  const { flow } = await resume(fakeHass("da"));
  // 1740 s is 29 min, rounded as the add-on rounds total_minutes.
  expect(queryByText(root(flow), "Onsdag · 2 personer · 5 runder · 29 min")).not.toBeNull();
  document.body.replaceChildren();

  const english = await resume(fakeHass("en"));
  expect(queryByText(root(english.flow), "Onsdag · 2 people · 5 rounds · 29 min")).not.toBeNull();
  document.body.replaceChildren();

  // One person, and a half minute rounded up: 1770 s is 30 min.
  const solo = await resume(
    fakeHass("da"),
    view({ participants: [thomas], stations: [view().stations![0]], totals: { planned: 1770, rounds: 1 } }),
  );
  expect(queryByText(root(solo.flow), "Onsdag · 1 person · 1 runde · 30 min")).not.toBeNull();
});

test("the countdown sits in the ring under GØR KLAR, and a tap on it sends nothing", async () => {
  const fake = fakeHass("da");
  const { flow } = await resume(fake);

  const ring = getByRole(root(flow), "progressbar", { name: "GØR KLAR" });
  expect(text(ring)).toBe("GØR KLAR 10");
  expect(ring.getAttribute("aria-valuenow")).toBe("10");
  await wait(flow, 3_000);
  expect(text(ring)).toBe("GØR KLAR 7");

  await tap(flow, ring);
  expect(sessionCommands(fake)).toEqual([]);
});

test("one card per person: a numbered badge, the picture, name and station, the exercise", async () => {
  const { flow } = await resume(fakeHass("da"));

  expect(queryByText(root(flow), "GÅ TIL DIN STARTSTATION")).not.toBeNull();
  const starts = cards(flow, "GÅ TIL DIN STARTSTATION");
  expect(starts.map(text)).toEqual(["1 Thomas · station 1 Push-up", "2 Maria · station 2 Squat"]);
  // Push-up's still thumbnail; Squat has none, so a placeholder carries its name.
  expect(getByRole(starts[0], "img", { name: "Push-up" }).getAttribute("src")).toMatch(/^blob:image-/);
  expect(getByRole(starts[1], "img", { name: "Squat" }).getAttribute("src")).toBeNull();
  document.body.replaceChildren();

  const english = await resume(fakeHass("en"));
  expect(cards(english.flow, "GO TO YOUR START STATION").map(text)).toEqual([
    "1 Thomas · station 1 Push-up",
    "2 Maria · station 2 Squat",
  ]);
});

test("no Pause button on get ready, in either language", async () => {
  const { flow } = await resume(fakeHass("da"));
  expect(queryByRole(root(flow), "button", { name: "Pause" })).toBeNull();
  expect(queryByText(root(flow), "PAUSET")).toBeNull();
  document.body.replaceChildren();

  const english = await resume(fakeHass("en"));
  expect(queryByRole(root(english.flow), "button", { name: "Pause" })).toBeNull();
  expect(button(english.flow, "Start now")).toBeTruthy();
  expect(button(english.flow, "Cancel")).toBeTruthy();
});

test("a paused countdown shows PAUSET and Fortsæt, which sends resume; no Start nu", async () => {
  const fake = fakeHass("da");
  const { flow } = await resume(fake, paused());

  expect(queryByText(root(flow), "PAUSET")).not.toBeNull();
  expect(queryByRole(root(flow), "button", { name: "Start nu" })).toBeNull();
  // The countdown holds while paused.
  await wait(flow, 5_000);
  expect(text(getByRole(root(flow), "progressbar", { name: "GØR KLAR" }))).toBe("GØR KLAR 7");

  await tap(flow, button(flow, "Fortsæt"));
  expect(sessionCommands(fake)).toEqual([{ type: "ha_fitness/session/command", command: "resume" }]);
  fake.commands[0].resolve(view({ revision: 2, server_time: "2026-10-24T08:00:05.000Z" }));
  await settle(flow);
  expect(queryByText(root(flow), "PAUSET")).toBeNull();
  expect(button(flow, "Start nu")).toBeTruthy();
  document.body.replaceChildren();

  const english = await resume(fakeHass("en"), paused());
  expect(queryByText(root(english.flow), "PAUSED")).not.toBeNull();
  expect(button(english.flow, "Resume")).toBeTruthy();
});

test("get ready shows start stations; Start nu sends next; Annullér sends end and closes once it is done", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, { kind: "details", programId: 3, trainingDayId: 12 });
  await tap(flow, button(flow, "Start"));
  fake.commands[0].resolve(view());
  await settle(flow);

  // The command result moves the flow on, before any push.
  expect(queryByRole(root(flow), "button", { name: "Tilbage" })).toBeNull();
  expect(cards(flow, "GÅ TIL DIN STARTSTATION").map(text)).toEqual([
    "1 Thomas · station 1 Push-up",
    "2 Maria · station 2 Squat",
  ]);
  expect(queryByText(root(flow), "10")).not.toBeNull();
  await wait(flow, 3_000);
  expect(queryByText(root(flow), "7")).not.toBeNull();

  // Start nu jumps to the first work phase.
  await tap(flow, button(flow, "Start nu"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "next" });
  expect(onClose).not.toHaveBeenCalled();
  fake.commands.at(-1)!.resolve(view({ revision: 2 }));
  await settle(flow);

  // Annullér ends the session, and closes once the end has gone through.
  await tap(flow, button(flow, "Annullér"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "end" });
  expect(onClose).not.toHaveBeenCalled();
  const ended = view({ revision: 5, status: "ended", phase: null, stations: null, next_phase: null });
  fake.commands.at(-1)!.resolve(ended);
  await settle(flow);
  expect(onClose).toHaveBeenCalledTimes(1);

  // The ended view never shows the done step.
  await push(flow, ended);
  expect(queryByText(root(flow), "Træningen blev afsluttet")).toBeNull();
});
