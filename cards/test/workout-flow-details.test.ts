import { getAllByRole, getByRole, queryAllByRole, queryByRole, queryByText } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { audioLocked } from "../src/audio";
import "../src/index";
import type { OverlayMode, SessionState, SessionView } from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// One audio context for the page (audio.ts keeps it at module level), so one fake for the file.
const audio = installFakeAudio("suspended");

// The image cache is page-wide too: every test's fake answers each image the same way.
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

const onsdag: Program = {
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

const solo: Program = {
  ...onsdag,
  id: 4,
  name: "Styrke",
  rounds: 3,
  total_minutes: 12,
  stations: [{ exercise_id: "0001", name: "Push-up" }],
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

/**
 * A fake `hass` with `callWS` for §4's commands: `ha_fitness/programs`, `ha_fitness/people` and
 * `ha_fitness/session/command`. Each session command waits until the test answers it.
 */
function fakeHass(language = "da", people = [thomas, maria], programs = [onsdag, solo]) {
  const commands: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/programs") return Promise.resolve(programs);
    if (message.type === "ha_fitness/people") return Promise.resolve(people);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve, reject) => commands.push({ message, resolve, reject }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  // Push-up has a thumbnail; the other exercises have none.
  const fetchWithAuth = vi.fn(async (path: string) =>
    path.includes("/0001/")
      ? new Response(new Blob(["GIF89a"]), { status: 200 })
      : new Response(null, { status: 404 }),
  );
  return { hass: { locale: { language }, callWS, fetchWithAuth }, callWS, commands };
}

type Fake = ReturnType<typeof fakeHass>;

/** A session view in the shape of spec §3.5. */
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

const NO_SESSION: SessionState = { available: true, session: null };

/**
 * Put the flow on the page the way the overlay controller does: append it first, then hand it
 * `hass`, the state, the mode and `onClose`.
 */
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

/** Let promises settle (the fetches, the images) and the flow render. */
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

function chip(flow: FlowElement, name: string): HTMLButtonElement {
  return getByRole(root(flow), "button", { name }) as HTMLButtonElement;
}

function pressed(flow: FlowElement): string[] {
  return queryAllByRole(root(flow), "button", { pressed: true }).map(text);
}

function chipColour(element: HTMLElement): string {
  return element.style.getPropertyValue("--person-color").trim().toUpperCase();
}

function sessionCommands(fake: Fake): Message[] {
  return fake.commands.map((command) => command.message);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

const details: OverlayMode = { kind: "details", programId: 3 };
const fromToday: OverlayMode = { kind: "details", programId: 3, trainingDayId: 12 };

test("details shows program, stations with thumbnails, rounds and seconds", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, details);

  expect(fake.callWS).toHaveBeenCalledWith({ type: "ha_fitness/programs" });
  expect(fake.callWS).toHaveBeenCalledWith({ type: "ha_fitness/people" });
  expect(text(getByRole(root(flow), "heading", { name: "Onsdag" }))).toBe("Onsdag");
  expect(queryByText(root(flow), "ca. 29 min · 5 runder")).not.toBeNull();
  expect(queryByText(root(flow), "Arbejde 45 s · Skift 15 s · Pause 60 s")).not.toBeNull();

  const stations = getAllByRole(getByRole(root(flow), "list", { name: "Øvelser" }), "listitem");
  expect(stations.map(text)).toEqual(["1 Push-up", "2 Squat", "3 Planke"]);
  // Push-up's thumbnail comes from the media proxy; the others show a neutral placeholder.
  expect(getByRole(stations[0], "img", { name: "Push-up" }).getAttribute("src")).toMatch(/^blob:image-/);
  expect(getByRole(stations[1], "img", { name: "Squat" }).getAttribute("src")).toBeNull();
  expect(fake.hass.fetchWithAuth).toHaveBeenCalledWith("/api/ha_fitness/media/0001/thumbnail");

  expect(button(flow, "Start").disabled).toBe(false);
  expect(button(flow, "Tilbage")).toBeTruthy();
});

test("details fetches once per open, whatever hass hand-overs come", async () => {
  const fake = fakeHass("da");
  let answer: (programs: Program[]) => void = () => undefined;
  const slow = new Promise<Program[]>((resolve) => {
    answer = resolve;
  });
  const callWS = fake.callWS.getMockImplementation()!;
  fake.callWS.mockImplementation((message: Message) =>
    message.type === "ha_fitness/programs" ? slow : callWS(message),
  );
  const { flow, onClose } = await mount(fake, details);

  // Home Assistant hands over a new hass object on every state change.
  for (let i = 0; i < 3; i += 1) {
    flow.hass = { ...fake.hass };
    await wait(flow, 20_000);
  }
  answer([onsdag]);
  await settle(flow);
  const calls = fake.callWS.mock.calls.map(([message]) => message.type);
  expect(calls.filter((type) => type === "ha_fitness/programs")).toHaveLength(1);
  expect(calls.filter((type) => type === "ha_fitness/people")).toHaveLength(1);
  // The idle guard ran from the open: 60 s after it, the flow closes.
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("Tilbage closes", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, details);
  await tap(flow, button(flow, "Tilbage"));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(sessionCommands(fake)).toEqual([]);
});

test("chips colours by people order", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, details);

  const group = getByRole(root(flow), "group", { name: "Hvem træner?" });
  const chips = getAllByRole(group, "button");
  expect(chips.map(text)).toEqual(["Thomas", "Maria"]);
  expect(chips.map(chipColour)).toEqual(["#B18CFF", "#3DD6C6"]);

  // The colour follows the person's place in people order, not the selection.
  await tap(flow, chip(flow, "Thomas"));
  expect(pressed(flow)).toEqual(["Maria"]);
  expect(chipColour(chip(flow, "Maria"))).toBe("#3DD6C6");
});

test("preselect both only when stations >= 2", async () => {
  const both = await mount(fakeHass("da"), details);
  expect(pressed(both.flow)).toEqual(["Thomas", "Maria"]);
  document.body.replaceChildren();

  const one = await mount(fakeHass("da"), { kind: "details", programId: 4 });
  expect(pressed(one.flow)).toEqual(["Thomas"]);

  const alone = await mount(fakeHass("da", [maria]), details);
  expect(pressed(alone.flow)).toEqual(["Maria"]);
});

test("select 1..2 and at most stations", async () => {
  // One station: only one person can train.
  const fake = fakeHass("da");
  const { flow } = await mount(fake, { kind: "details", programId: 4 });
  expect(chip(flow, "Maria").disabled).toBe(true);
  await tap(flow, chip(flow, "Maria"));
  expect(pressed(flow)).toEqual(["Thomas"]);

  // Swapping: drop Thomas, then Maria can be chosen.
  await tap(flow, chip(flow, "Thomas"));
  expect(pressed(flow)).toEqual([]);
  expect(button(flow, "Start").disabled).toBe(true);
  expect(chip(flow, "Maria").disabled).toBe(false);
  await tap(flow, chip(flow, "Maria"));
  expect(pressed(flow)).toEqual(["Maria"]);
  expect(button(flow, "Start").disabled).toBe(false);
  document.body.replaceChildren();

  // Three stations: at most two of three people.
  const three = fakeHass("da", [thomas, maria, { id: 3, name: "Ida" }]);
  const many = await mount(three, details);
  expect(pressed(many.flow)).toEqual(["Thomas", "Maria"]);
  expect(chip(many.flow, "Ida").disabled).toBe(true);
  await tap(many.flow, chip(many.flow, "Thomas"));
  await tap(many.flow, chip(many.flow, "Ida"));
  expect(pressed(many.flow)).toEqual(["Maria", "Ida"]);
});

test("no people disables Start", async () => {
  const fake = fakeHass("da", []);
  const { flow } = await mount(fake, details);

  expect(queryByText(root(flow), "Ingen personer – bed Claude oprette dem")).not.toBeNull();
  expect(button(flow, "Start").disabled).toBe(true);
  await tap(flow, button(flow, "Start"));
  expect(sessionCommands(fake)).toEqual([]);
});

test("idle 60 s closes", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, details);

  await wait(flow, 59_000);
  expect(onClose).not.toHaveBeenCalled();

  // A tap starts the 60 s over.
  getByRole(root(flow), "heading", { name: "Onsdag" }).dispatchEvent(
    new Event("pointerdown", { bubbles: true, composed: true }),
  );
  await wait(flow, 59_000);
  expect(onClose).not.toHaveBeenCalled();
  await tap(flow, chip(flow, "Maria"));
  await wait(flow, 59_000);
  expect(onClose).not.toHaveBeenCalled();

  await wait(flow, 1_000);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("idle guard stops once Start is tapped", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, details);

  await tap(flow, button(flow, "Start"));
  await wait(flow, 61_000);
  expect(onClose).not.toHaveBeenCalled();

  fake.commands[0].resolve(view());
  await settle(flow);
  await wait(flow, 61_000);
  expect(onClose).not.toHaveBeenCalled();
});

test("Start unlocks audio before the command resolves", async () => {
  // Earlier tests may have unlocked the page's context; lock it again.
  for (const context of audio.contexts) context.state = "suspended";
  expect(audioLocked()).toBe(true);
  const fake = fakeHass("da");
  const { flow } = await mount(fake, details);

  button(flow, "Start").click();

  // The command is still pending, and the context already exists and runs.
  expect(fake.commands).toHaveLength(1);
  expect(audio.contexts).toHaveLength(1);
  expect(audio.contexts[0].state).toBe("running");
  expect(audioLocked()).toBe(false);
  await settle(flow);
  expect(button(flow, "Start").disabled).toBe(true);
});

test("Start sends participants and training day", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, fromToday);

  // Chosen in reverse, sent in people order.
  await tap(flow, chip(flow, "Thomas"));
  await tap(flow, chip(flow, "Thomas"));
  await tap(flow, button(flow, "Start"));
  expect(sessionCommands(fake)).toEqual([
    {
      type: "ha_fitness/session/command",
      command: "start",
      program_id: 3,
      participants: [1, 2],
      training_day_id: 12,
    },
  ]);
  document.body.replaceChildren();

  // An extra session (from the workout card) sends no training day.
  const extra = fakeHass("da");
  const second = await mount(extra, { kind: "details", programId: 4 });
  await tap(second.flow, button(second.flow, "Start"));
  expect(sessionCommands(extra)).toEqual([
    { type: "ha_fitness/session/command", command: "start", program_id: 4, participants: [1] },
  ]);
});

test("error texts per code", async () => {
  const cases: [unknown, string][] = [
    [{ code: "conflict", message: "Program is not active" }, "Træningen kan ikke startes nu."],
    [{ code: "not_found", message: "No such program" }, "Programmet eller en person findes ikke længere."],
    [{ code: "invalid", message: "Too many participants" }, "Vælg 1–2 personer, højst én per øvelse."],
    [{ code: "unavailable", message: "Add-on down" }, "HA Fitness kan ikke nås. Prøv igen senere."],
    [{ code: "unknown_error", message: "Boom" }, "Noget gik galt. Prøv igen."],
  ];
  for (const [error, expected] of cases) {
    const fake = fakeHass("da");
    const { flow } = await mount(fake, fromToday);
    await tap(flow, button(flow, "Start"));
    fake.commands[0].reject(error);
    await settle(flow);

    expect(text(getByRole(root(flow), "alert"))).toBe(expected);
    // It stays on details, and Start can be tapped again.
    expect(getByRole(root(flow), "heading", { name: "Onsdag" })).toBeTruthy();
    expect(button(flow, "Start").disabled).toBe(false);
    document.body.replaceChildren();
  }

  // A conflict while a session is known to run: someone else started one meanwhile.
  const fake = fakeHass("da");
  const { flow } = await mount(fake, fromToday);
  await tap(flow, button(flow, "Start"));
  await push(flow, view({ id: 9 }));
  fake.commands[0].reject({ code: "conflict", message: "A session is already running" });
  await settle(flow);
  expect(text(getByRole(root(flow), "alert"))).toBe("En træning er allerede i gang.");
});

test("error texts in English", async () => {
  const fake = fakeHass("en");
  const { flow } = await mount(fake, fromToday);
  await tap(flow, button(flow, "Start"));
  fake.commands[0].reject({ code: "conflict", message: "Program is not active" });
  await settle(flow);
  expect(text(getByRole(root(flow), "alert"))).toBe("The workout can't start now.");
});

test("get ready shows start stations; Start nu sends next; Annullér sends end and closes without done", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, fromToday);
  await tap(flow, button(flow, "Start"));
  fake.commands[0].resolve(view());
  await settle(flow);

  // The command result moves the flow on, before any push.
  expect(queryByRole(root(flow), "heading", { name: "Onsdag" })).not.toBeNull();
  expect(queryByRole(root(flow), "button", { name: "Tilbage" })).toBeNull();
  const starts = getAllByRole(getByRole(root(flow), "list", { name: "Gør klar" }), "listitem");
  expect(starts.map(text)).toEqual(["Thomas · station 1 · Push-up", "Maria · station 2 · Squat"]);
  expect(queryByText(root(flow), "10")).not.toBeNull();
  await wait(flow, 3_000);
  expect(queryByText(root(flow), "7")).not.toBeNull();

  // Pause and resume.
  await tap(flow, button(flow, "Pause"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "pause" });
  fake.commands.at(-1)!.resolve(
    view({
      revision: 2,
      status: "paused",
      phase: { ...view().phase!, ends_at: null, remaining: 7 },
      server_time: "2026-10-24T08:00:03.000Z",
    }),
  );
  await settle(flow);
  await wait(flow, 5_000);
  expect(queryByText(root(flow), "7")).not.toBeNull();
  await tap(flow, button(flow, "Fortsæt"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "resume" });
  fake.commands.at(-1)!.resolve(view({ revision: 3 }));
  await settle(flow);

  // Start nu jumps to the first work phase.
  await tap(flow, button(flow, "Start nu"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "next" });
  expect(onClose).not.toHaveBeenCalled();

  // Annullér ends the session and closes at once.
  await tap(flow, button(flow, "Annullér"));
  expect(sessionCommands(fake).at(-1)).toEqual({ type: "ha_fitness/session/command", command: "end" });
  expect(onClose).toHaveBeenCalledTimes(1);

  // The ended view that follows never shows the done step.
  const ended = view({ revision: 5, status: "ended", phase: null, stations: null, next_phase: null });
  fake.commands.at(-1)!.resolve(ended);
  await push(flow, ended);
  expect(queryByText(root(flow), "Træningen blev afsluttet")).toBeNull();
});

test("an ended session that wasn't annulled shows done", async () => {
  const fake = fakeHass("da");
  const ended = view({ revision: 5, status: "ended", phase: null, stations: null, next_phase: null });
  const { flow } = await mount(fake, { kind: "resume" }, { available: true, session: ended });
  expect(queryByText(root(flow), "Træningen blev afsluttet")).not.toBeNull();
});

test("a running session past the countdown shows the timer, not details", async () => {
  const fake = fakeHass("da");
  const work = view({
    revision: 4,
    phase: { ...view().phase!, index: 1, kind: "work", duration: 45 },
  });
  const { flow } = await mount(fake, details, { available: true, session: work });
  expect(queryByRole(root(flow), "button", { name: "Tilbage" })).toBeNull();
  expect(queryByText(root(flow), "ARBEJD")).not.toBeNull();
});

test("renders in Danish and English", async () => {
  const english = fakeHass("en");
  const { flow } = await mount(english, details);
  expect(queryByText(root(flow), "about 29 min · 5 rounds")).not.toBeNull();
  expect(queryByText(root(flow), "Work 45 s · Switch 15 s · Rest 60 s")).not.toBeNull();
  expect(getByRole(root(flow), "group", { name: "Who's training?" })).toBeTruthy();
  expect(button(flow, "Back")).toBeTruthy();
  await tap(flow, button(flow, "Start"));
  english.commands[0].resolve(view());
  await settle(flow);
  expect(getAllByRole(getByRole(root(flow), "list", { name: "Get ready" }), "listitem").map(text)).toEqual([
    "Thomas · station 1 · Push-up",
    "Maria · station 2 · Squat",
  ]);
  expect(button(flow, "Start now")).toBeTruthy();
  expect(button(flow, "Cancel")).toBeTruthy();
  expect(button(flow, "Pause")).toBeTruthy();
  document.body.replaceChildren();

  const nobody = await mount(fakeHass("en", []), details);
  expect(queryByText(root(nobody.flow), "No people – ask Claude to add them")).not.toBeNull();
});
