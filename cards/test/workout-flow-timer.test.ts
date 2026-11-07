import {
  getAllByRole,
  getByRole,
  queryAllByRole,
  queryAllByText,
  queryByRole,
  queryByText,
} from "@testing-library/dom";
import { computeAccessibleName } from "dom-accessibility-api";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";
import * as overlay from "../src/overlay";
import type { MusicState, OverlayMode, SessionPhase, SessionState, SessionView } from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// The flow element is defined once for the file, so its modules are imported statically; the
// audio and image modules keep page-wide state, and every test's fakes answer them the same way.
const audio = installFakeAudio("running");
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
 * A fake `hass` with `callWS` for §4's commands; each session command and each music command
 * waits for the test.
 */
function fakeHass(language = "da", people = [thomas, maria], programs: unknown[] = []) {
  const commands: Pending[] = [];
  const music: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/people") return Promise.resolve(people);
    if (message.type === "ha_fitness/programs") return Promise.resolve(programs);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve, reject) => commands.push({ message, resolve, reject }));
    }
    if (message.type === "ha_fitness/music") {
      return new Promise((resolve, reject) => music.push({ message, resolve, reject }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  // Every exercise has a GIF and a thumbnail.
  const fetchWithAuth = vi.fn(async () => new Response(new Blob(["GIF89a"]), { status: 200 }));
  return { hass: { locale: { language }, callWS, fetchWithAuth }, callWS, commands, music };
}

type Fake = ReturnType<typeof fakeHass>;

const push_up = { number: 1, exercise_id: "0001", name: "Push-up" };
const squat = { number: 2, exercise_id: "0002", name: "Squat" };
const planke = { number: 3, exercise_id: "custom-7", name: "Planke" };

function phase(overrides: Partial<SessionPhase> = {}): SessionPhase {
  return {
    index: 3,
    kind: "work",
    round: 2,
    interval: 1,
    duration: 45,
    ends_at: "2026-10-24T08:00:45.000Z",
    remaining: null,
    ...overrides,
  };
}

/** A running two-person session in round 2's first work phase, as the add-on sends it at 08:00:00. */
function view(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: 7,
    revision: 10,
    status: "running",
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [thomas, maria],
    phase: phase(),
    next_phase: { kind: "switch", duration: 15 },
    stations: [
      { current: push_up, next: squat },
      { current: squat, next: planke },
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

function solo(overrides: Partial<SessionView> = {}): SessionView {
  return view({ participants: [thomas], stations: [{ current: push_up, next: squat }], ...overrides });
}

function paused(overrides: Partial<SessionView> = {}): SessionView {
  return view({ status: "paused", phase: phase({ ends_at: null, remaining: 30 }), ...overrides });
}

function soloPaused(overrides: Partial<SessionView> = {}): SessionView {
  return paused({ participants: [thomas], stations: [{ current: push_up, next: squat }], ...overrides });
}

function finished(counted: boolean, overrides: Partial<SessionView> = {}): SessionView {
  return view({
    revision: 40,
    status: counted ? "completed" : "ended",
    counted,
    phase: null,
    next_phase: null,
    stations: null,
    ended_at: "2026-10-24T08:25:00.000Z",
    rounds_completed: counted ? 5 : 0,
    time_trained: counted ? 1530 : 20,
    ...overrides,
  });
}

/** Put the flow on the page the way the overlay controller does, resuming the session `session`. */
async function mount(fake: Fake, session: SessionView | null, available = true, music?: MusicState | null) {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  const onClose = vi.fn();
  flow.hass = fake.hass;
  flow.state = music === undefined ? { available, session } : { available, session, music };
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

async function push(
  flow: FlowElement,
  session: SessionView | null,
  available = true,
  music?: MusicState | null,
): Promise<void> {
  flow.state = music === undefined ? { available, session } : { available, session, music };
  await settle(flow);
}

function root(flow: FlowElement): HTMLElement {
  return flow.shadowRoot as unknown as HTMLElement;
}

function text(element: HTMLElement): string {
  return (element.textContent ?? "").replace(/\s+/g, " ").trim();
}

function button(flow: FlowElement, name: string | RegExp): HTMLButtonElement {
  return getByRole(root(flow), "button", { name }) as HTMLButtonElement;
}

/** The whole-workout bar's name in each language. */
const WHOLE = new Set(["Whole workout", "Hele træningen"]);

/** The ring: the progressbar named after the phase, not the whole-workout bar. */
function ring(flow: FlowElement): HTMLElement {
  return getByRole(root(flow), "progressbar", { name: (name) => !WHOLE.has(name) });
}

/** The whole-workout bar. */
function whole(flow: FlowElement): HTMLElement {
  return getByRole(root(flow), "progressbar", { name: (name) => WHOLE.has(name) });
}

/** The ring's state: its name, its values, and the texts in it. */
function ringState(flow: FlowElement) {
  const element = ring(flow);
  return {
    name: computeAccessibleName(element),
    min: element.getAttribute("aria-valuemin"),
    max: element.getAttribute("aria-valuemax"),
    now: element.getAttribute("aria-valuenow"),
    text: text(element),
  };
}

function sent(fake: Fake): unknown[] {
  return fake.commands.map((command) => command.message.command);
}

function hasText(flow: FlowElement, value: string): boolean {
  return queryByText(root(flow), value) !== null;
}

function norm(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

/** A pill (or the elapsed time): the element whose whole text, bold parts included, reads `value`. */
function pill(flow: FlowElement, value: string): HTMLElement | null {
  return queryAllByText(root(flow), (_, element) => norm(element?.textContent) === value)[0] ?? null;
}

function hasPill(flow: FlowElement, value: string): boolean {
  return pill(flow, value) !== null;
}

/** Whether `first` comes before `second` in document order. */
function before(first: Node, second: Node): boolean {
  return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("timer text and ring from a view with a clock offset", async () => {
  // The tablet's clock is 10 s behind the add-on's.
  vi.setSystemTime(new Date("2026-10-24T07:59:50.000Z"));
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ server_time: "2026-10-24T08:00:15.000Z" }));

  // 08:00:45 is 30 s after the add-on's 08:00:15; the local clock doesn't matter.
  expect(ringState(flow)).toEqual({
    name: "ARBEJD",
    min: "0",
    max: "45",
    now: "30",
    text: "ARBEJD 30 sekunder tilbage",
  });
  await wait(flow, 4_000);
  expect(ringState(flow).now).toBe("26");

  // A newer message brings a new stamp, and with it a new offset: now the clocks agree.
  vi.setSystemTime(new Date("2026-10-24T08:00:20.000Z"));
  await push(flow, view({ revision: 11, server_time: "2026-10-24T08:00:20.000Z" }));
  expect(ringState(flow).now).toBe("25");
});

test("the offset updates on every message, even one that isn't applied", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());
  expect(ringState(flow).now).toBe("45");

  // The same revision again, stamped 5 s later by the add-on's clock while no local time passed.
  await push(flow, view({ server_time: "2026-10-24T08:00:05.000Z" }));
  expect(ringState(flow).now).toBe("40");
});

test("seconds rounded up", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  // 44.75 s left shows 45.
  await wait(flow, 250);
  expect(ringState(flow).now).toBe("45");
  await wait(flow, 750);
  expect(ringState(flow).now).toBe("44");
  // During the last second, 1 shows, even with 0.25 s left.
  await wait(flow, 43_750);
  expect(ringState(flow).now).toBe("1");
  expect(ringState(flow).text).toBe("ARBEJD 1 sekunder tilbage");
});

test("local zero shows next phase word", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  await wait(flow, 45_000);
  // No message yet: the switch shows from `next_phase`, at its full length.
  expect(ringState(flow)).toEqual({
    name: "SKIFT",
    min: "0",
    max: "15",
    now: "15",
    text: "SKIFT 15 sekunder tilbage",
  });

  // The message that follows confirms it.
  await push(
    flow,
    view({
      revision: 11,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:01:00.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [
        { current: squat, next: squat },
        { current: planke, next: planke },
      ],
      server_time: "2026-10-24T08:00:45.000Z",
    }),
  );
  expect(ringState(flow)).toMatchObject({ name: "SKIFT", now: "15", text: "SKIFT 15 sekunder tilbage" });

  // The last work phase has no next phase: it holds at 0 until the finish arrives.
  await push(
    flow,
    view({
      revision: 12,
      phase: phase({ index: 9, round: 5, interval: 3, ends_at: "2026-10-24T08:01:30.000Z" }),
      next_phase: null,
      server_time: "2026-10-24T08:00:45.000Z",
    }),
  );
  await wait(flow, 46_000);
  expect(ringState(flow)).toMatchObject({ name: "ARBEJD", now: "0", text: "ARBEJD 0 sekunder tilbage" });
});

test("older revision ignored; new session applied", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ revision: 10 }));
  expect(hasPill(flow, "Interval 1")).toBe(true);

  // A command result and a push can arrive in either order: revision 9 is older.
  await push(flow, view({ revision: 9, phase: phase({ interval: 2 }) }));
  expect(hasPill(flow, "Interval 1")).toBe(true);
  // The same revision again changes nothing either.
  await push(flow, view({ revision: 10, phase: phase({ interval: 3 }) }));
  expect(hasPill(flow, "Interval 1")).toBe(true);

  // A different session applies whatever its revision.
  await push(flow, view({ id: 8, revision: 1, phase: phase({ interval: 2 }) }));
  expect(hasPill(flow, "Interval 2")).toBe(true);
});

test("pause, resume and ring tap", async () => {
  const fake = fakeHass("en");
  const { flow } = await mount(fake, solo());

  await tap(flow, button(flow, "Pause"));
  expect(sent(fake)).toEqual(["pause"]);
  fake.commands[0].resolve(soloPaused({ revision: 11 }));
  await settle(flow);

  // Paused: the ring stops, keeps the phase word and says to tap; a PAUSED pill shows; the ring
  // button resumes.
  expect(ringState(flow)).toMatchObject({ name: "WORK", now: "30", text: "WORK 30 tap the ring to resume" });
  expect(hasPill(flow, "PAUSED")).toBe(true);
  expect(button(flow, "Resume")).toBeTruthy();
  expect(queryByRole(root(flow), "button", { name: "Pause" })).toBeNull();
  await wait(flow, 5_000);
  expect(ringState(flow).now).toBe("30");

  // A tap on the paused ring resumes.
  await tap(flow, button(flow, "Resume"));
  expect(sent(fake)).toEqual(["pause", "resume"]);
  fake.commands[1].resolve(
    solo({
      revision: 12,
      phase: phase({ ends_at: "2026-10-24T08:00:35.000Z" }),
      server_time: "2026-10-24T08:00:05.000Z",
    }),
  );
  await settle(flow);
  expect(ringState(flow)).toMatchObject({ name: "WORK", now: "30", text: "WORK 30 seconds left" });
  expect(hasPill(flow, "PAUSED")).toBe(false);

  // Tapping the running ring pauses.
  await tap(flow, button(flow, "Pause"));
  expect(sent(fake)).toEqual(["pause", "resume", "pause"]);
});

test("the ring's progressbar is no tab stop; the ring button is", async () => {
  const { flow } = await mount(fakeHass("da"), solo());
  expect(ring(flow).getAttribute("tabindex")).toBeNull();
  expect(queryByRole(root(flow), "button", { name: "ARBEJD" })).toBeNull();
  const pause = button(flow, "Pause");
  expect(pause.tabIndex).toBe(0);
  expect(pause.disabled).toBe(false);
});

test("no transport buttons", async () => {
  for (const session of [solo(), view(), paused()]) {
    const { flow } = await mount(fakeHass("da"), session);
    expect(queryByRole(root(flow), "button", { name: "Forrige" })).toBeNull();
    expect(queryByRole(root(flow), "button", { name: "Næste" })).toBeNull();
    // The timer's own buttons are Slut and the ring's (and Tryk for lyd while the audio is locked).
    const names = getAllByRole(root(flow), "button").map((element) => computeAccessibleName(element));
    expect(names.filter((name) => name !== "Tryk for lyd")).toEqual([
      "Slut",
      session.status === "paused" ? "Fortsæt" : "Pause",
    ]);
    document.body.replaceChildren();
  }
  const { flow } = await mount(fakeHass("en"), view());
  expect(queryByRole(root(flow), "button", { name: "Previous" })).toBeNull();
  expect(queryByRole(root(flow), "button", { name: "Next" })).toBeNull();
});

test("the ring button pauses and resumes", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  // Running: one button named Pause, laid over the ring, not around its progressbar.
  expect(queryAllByRole(root(flow), "button", { name: "Pause" })).toHaveLength(1);
  const pause = button(flow, "Pause");
  expect(pause.contains(ring(flow))).toBe(false);
  expect(ring(flow).contains(pause)).toBe(false);
  expect(text(pause)).toBe("tryk for pause");
  expect(ringState(flow)).toMatchObject({ name: "ARBEJD", text: "ARBEJD 45 sekunder tilbage" });
  await tap(flow, pause);
  expect(sent(fake)).toEqual(["pause"]);
  fake.commands[0].resolve(paused({ revision: 11 }));
  await settle(flow);

  // Paused: one button named Fortsæt; the ring's caption says to tap.
  expect(queryAllByRole(root(flow), "button", { name: "Pause" })).toHaveLength(0);
  expect(queryAllByRole(root(flow), "button", { name: "Fortsæt" })).toHaveLength(1);
  expect(ringState(flow)).toMatchObject({ name: "ARBEJD", text: "ARBEJD 30 tryk på ringen for at fortsætte" });
  expect(queryByText(root(flow), "tryk for pause")).toBeNull();
  await tap(flow, button(flow, "Fortsæt"));
  expect(sent(fake)).toEqual(["pause", "resume"]);
});

test("get ready's ring has no button", async () => {
  const { flow } = await mount(
    fakeHass("da"),
    view({
      revision: 1,
      phase: phase({ index: 0, kind: "countdown", round: 1, duration: 10, ends_at: "2026-10-24T08:00:10.000Z" }),
      next_phase: { kind: "work", duration: 45 },
    }),
  );
  expect(ringState(flow)).toMatchObject({ name: "GØR KLAR", now: "10" });
  expect(queryByRole(root(flow), "button", { name: "Pause" })).toBeNull();
  expect(queryByText(root(flow), "tryk for pause")).toBeNull();
});

test("the interval pill", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(
    fake,
    view({ phase: phase({ interval: 3 }), totals: { planned: 1740, rounds: 5, stations: 5 } }),
  );
  expect(hasPill(flow, "Interval 3 / 5")).toBe(true);
  expect(text(getByRole(pill(flow, "Interval 3 / 5")!, "strong"))).toBe("3 / 5");
  expect(before(ring(flow), pill(flow, "Interval 3 / 5")!)).toBe(true);
  // No round pill: round 2 of 5 shows nowhere.
  expect(queryAllByText(root(flow), /Runde/)).toHaveLength(0);
  expect(queryAllByText(root(flow), /2 \/ 5/)).toHaveLength(0);
  document.body.replaceChildren();

  // One person: the station pill.
  const one = await mount(fakeHass("da"), solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasPill(one.flow, "Station 1 / 3")).toBe(true);
  expect(before(ring(one.flow), pill(one.flow, "Station 1 / 3")!)).toBe(true);
  expect(queryAllByText(root(one.flow), /Runde/)).toHaveLength(0);
});

test("the band's times", async () => {
  const { flow } = await mount(fakeHass("da"), view({ time_trained: 663, totals: { planned: 1725, rounds: 5 } }));
  const band = whole(flow);
  expect(hasPill(flow, "11:03")).toBe(true);
  expect(hasPill(flow, "17:42 tilbage")).toBe(true);
  expect(band.contains(pill(flow, "11:03"))).toBe(true);
  expect(band.contains(pill(flow, "17:42 tilbage"))).toBe(true);
  expect(band.getAttribute("aria-valuetext")).toBe("17:42 tilbage af træningen");
  expect(computeAccessibleName(band)).toBe("Hele træningen");
  expect(queryAllByText(root(flow), /\/ 28:45/)).toHaveLength(0);
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"), view({ time_trained: 663, totals: { planned: 1725, rounds: 5 } }));
  expect(hasPill(en.flow, "17:42 left")).toBe(true);
  expect(whole(en.flow).getAttribute("aria-valuetext")).toBe("17:42 left of the workout");
});

test("one rounding rule", async () => {
  const { flow } = await mount(fakeHass("da"), view({ time_trained: 663, totals: { planned: 1725, rounds: 5 } }));
  await wait(flow, 400);
  expect(hasPill(flow, "11:03")).toBe(true);
  expect(hasPill(flow, "17:42 tilbage")).toBe(true);
  expect(whole(flow).getAttribute("aria-valuetext")).toBe("17:42 tilbage af træningen");
  await wait(flow, 600);
  expect(hasPill(flow, "11:04")).toBe(true);
  expect(hasPill(flow, "17:41 tilbage")).toBe(true);
});

test("time left never below zero", async () => {
  const { flow } = await mount(fakeHass("da"), solo({ time_trained: 1800 }));
  expect(hasPill(flow, "30:00")).toBe(true);
  expect(hasPill(flow, "0:00 tilbage")).toBe(true);
  expect(whole(flow).getAttribute("aria-valuetext")).toBe("0:00 tilbage af træningen");
});

test("gaps from marks", async () => {
  const { flow } = await mount(fakeHass("da"), view({ totals: { planned: 1740, rounds: 3, marks: [300, 600] } }));
  const gaps = getAllByRole(whole(flow), "separator", { hidden: true });
  expect(gaps).toHaveLength(2);
  for (const gap of gaps) expect(gap.getAttribute("aria-hidden")).toBe("true");
});

test("no gaps without marks", async () => {
  const { flow } = await mount(fakeHass("da"), view());
  expect(queryAllByRole(whole(flow), "separator", { hidden: true })).toHaveLength(0);
  await push(flow, view({ revision: 11, totals: { planned: 1740, rounds: 1, marks: [] } }));
  expect(queryAllByRole(whole(flow), "separator", { hidden: true })).toHaveLength(0);
});

test("banners above the cards", async () => {
  const { flow } = await mount(fakeHass("da"), view());
  await push(flow, view(), false);
  const note = getByRole(root(flow), "status");
  expect(text(note)).toBe("HA Fitness kan ikke nås");
  expect(before(button(flow, "Slut"), note)).toBe(true);
  expect(before(note, getAllByRole(root(flow), "region")[0])).toBe(true);
  document.body.replaceChildren();

  // Locked: no audio context yet, or the page's one suspended.
  const context = audio.contexts[0];
  const locked = await mount(fakeHass("da"), view());
  try {
    context?.setState("suspended");
    await settle(locked.flow);
    const sound = button(locked.flow, "Tryk for lyd");
    expect(before(button(locked.flow, "Slut"), sound)).toBe(true);
    expect(before(sound, getAllByRole(root(locked.flow), "region")[0])).toBe(true);
  } finally {
    context?.setState("running");
  }
});

test("the pills by the ring for one person", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasPill(flow, "Station 1 / 3")).toBe(true);
  // Station comes after the ring.
  expect(before(ring(flow), pill(flow, "Station 1 / 3")!)).toBe(true);
  expect(hasPill(flow, "PAUSET")).toBe(false);

  // During a switch the pill keeps the interval.
  await push(
    flow,
    solo({
      revision: 11,
      totals: { planned: 1740, rounds: 5, stations: 3 },
      phase: phase({ index: 4, kind: "switch", interval: 1, duration: 15, ends_at: "2026-10-24T08:00:15.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [{ current: squat, next: planke }],
    }),
  );
  expect(hasPill(flow, "Station 1 / 3")).toBe(true);

  // Without the stations total, the number alone.
  await push(flow, solo({ revision: 12, phase: phase({ interval: 2 }) }));
  expect(hasPill(flow, "Station 2")).toBe(true);

  // Paused: the PAUSET pill.
  await push(flow, soloPaused({ revision: 13 }));
  expect(hasPill(flow, "PAUSET")).toBe(true);
});

test("each pill bolds its numbers", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(text(getByRole(pill(flow, "Station 1 / 3")!, "strong"))).toBe("1 / 3");

  // Without the stations total, the number alone is bold.
  await push(flow, solo({ revision: 11, phase: phase({ interval: 2 }) }));
  expect(text(getByRole(pill(flow, "Station 2")!, "strong"))).toBe("2");
});

test("the two-person card bolds the station number", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());
  const card = getByRole(root(flow), "region", { name: "Thomas" });
  expect(text(getByRole(card, "strong"))).toBe("1");
  const other = getByRole(root(flow), "region", { name: "Maria" });
  expect(text(getByRole(other, "strong"))).toBe("2");
});

test("the NEXT card's subtitle before a switch, a rest and a 0 s switch", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo());
  const card = () => getByRole(root(flow), "region", { name: "NÆSTE" });
  expect(text(card())).toBe("NÆSTE Squat efter 15 s skift");
  expect(getByRole(card(), "img", { name: "Squat" })).toBeTruthy();

  await push(flow, solo({ revision: 11, next_phase: { kind: "rest", duration: 60 } }));
  expect(text(card())).toBe("NÆSTE Squat efter 60 s pause");

  await push(flow, solo({ revision: 12, next_phase: { kind: "work", duration: 45 } }));
  expect(text(card())).toBe("NÆSTE Squat derefter");
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"), solo());
  expect(text(getByRole(root(en.flow), "region", { name: "NEXT" }))).toBe("NEXT Squat after 15 s switch");
  await push(en.flow, solo({ revision: 11, next_phase: { kind: "rest", duration: 60 } }));
  expect(text(getByRole(root(en.flow), "region", { name: "NEXT" }))).toBe("NEXT Squat after 60 s rest");
  await push(en.flow, solo({ revision: 12, next_phase: { kind: "work", duration: 45 } }));
  expect(text(getByRole(root(en.flow), "region", { name: "NEXT" }))).toBe("NEXT Squat next up");
});

test("THEN during a switch and a rest, with the move above the picture", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(
    fake,
    solo({
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:00:15.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [{ current: squat, next: planke }],
    }),
  );
  expect(text(getByRole(root(flow), "region", { name: "Thomas" }))).toBe("GÅ TIL NÆSTE STATION Squat");
  expect(text(getByRole(root(flow), "region", { name: "DEREFTER" }))).toBe("DEREFTER Planke efter 45 s arbejde");
  expect(queryByRole(root(flow), "region", { name: "NÆSTE" })).toBeNull();

  // A rest is a move to the next round's first station: it reads like a switch.
  await push(
    flow,
    solo({
      revision: 11,
      phase: phase({ index: 8, kind: "rest", duration: 60, ends_at: "2026-10-24T08:01:00.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [{ current: push_up, next: squat }],
    }),
  );
  expect(text(getByRole(root(flow), "region", { name: "Thomas" }))).toBe("GÅ TIL NÆSTE STATION Push-up");
  expect(text(getByRole(root(flow), "region", { name: "DEREFTER" }))).toBe("DEREFTER Squat efter 45 s arbejde");
  document.body.replaceChildren();

  const en = await mount(
    fakeHass("en"),
    solo({
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:00:15.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [{ current: squat, next: planke }],
    }),
  );
  expect(text(getByRole(root(en.flow), "region", { name: "Thomas" }))).toBe("GO TO THE NEXT STATION Squat");
  expect(text(getByRole(root(en.flow), "region", { name: "THEN" }))).toBe("THEN Planke after 45 s work");
});

test("the whole-workout bar's value stays within its maximum; the trained text doesn't", async () => {
  // Paused moments and a previous can take a workout past its planned time.
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo({ time_trained: 1800 }));
  expect(whole(flow).getAttribute("aria-valuemax")).toBe("1740");
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("1740");
  expect(hasPill(flow, "30:00")).toBe(true);
});

test("the whole-workout bar moves with the clock", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo());
  expect(computeAccessibleName(whole(flow))).toBe("Hele træningen");
  expect(whole(flow).getAttribute("aria-valuemin")).toBe("0");
  expect(whole(flow).getAttribute("aria-valuemax")).toBe("1740");
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("360");

  // Whole seconds, rounded down.
  await wait(flow, 12_750);
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("372");
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"), solo());
  expect(whole(en.flow).getAttribute("aria-valuemax")).toBe("1740");
});

test("a newer view from a next moves the flow", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  // A next from elsewhere moves the flow, like any newer view.
  await push(
    flow,
    view({
      revision: 11,
      phase: phase({ index: 5, interval: 2, ends_at: "2026-10-24T08:00:45.000Z" }),
      stations: [
        { current: squat, next: planke },
        { current: planke, next: push_up },
      ],
    }),
  );
  expect(hasPill(flow, "Interval 2")).toBe(true);
});

test("Slut two taps with guard", async () => {
  const fake = fakeHass("da");
  const { flow, onClose } = await mount(fake, view());

  // The first tap asks.
  await tap(flow, button(flow, "Slut"));
  expect(hasText(flow, "Afslut træningen?")).toBe(true);
  expect(queryByRole(root(flow), "button", { name: "Slut" })).toBeNull();

  // A tap on Ja right away (a wake tap, a double tap) does nothing.
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual([]);

  // Nej puts Slut back.
  await tap(flow, button(flow, "Nej"));
  expect(queryByText(root(flow), "Afslut træningen?")).toBeNull();
  await tap(flow, button(flow, "Slut"));
  await wait(flow, 499);
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual([]);
  await wait(flow, 1);
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual(["end"]);

  // The ended view shows done; the overlay stays open.
  fake.commands[0].resolve(finished(false, { revision: 11 }));
  await settle(flow);
  expect(hasText(flow, "Træningen blev afsluttet")).toBe(true);
  expect(onClose).not.toHaveBeenCalled();
});

test("an unanswered Slut question goes after 10 s", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  await tap(flow, button(flow, "Slut"));
  await wait(flow, 9_999);
  expect(hasText(flow, "Afslut træningen?")).toBe(true);
  await wait(flow, 1);
  expect(queryByText(root(flow), "Afslut træningen?")).toBeNull();
  expect(button(flow, "Slut")).toBeTruthy();
  expect(sent(fake)).toEqual([]);
});

test("one-person and two-person layouts in work and switch", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo());

  // One person: the current exercise big, with its GIF; NÆSTE beside it.
  const now = getByRole(root(flow), "region", { name: "Thomas" });
  expect(text(now)).toBe("Push-up");
  // The image cache is page-wide, so an earlier test may have fetched it: check what shows.
  expect(getByRole(now, "img", { name: "Push-up" }).getAttribute("src")).toMatch(/^blob:image-/);
  const next = getByRole(root(flow), "region", { name: "NÆSTE" });
  expect(text(next)).toBe("NÆSTE Squat efter 15 s skift");
  expect(getByRole(next, "img", { name: "Squat" }).getAttribute("src")).toMatch(/^blob:image-/);

  // During a switch, the big one is the station being moved to.
  await push(
    flow,
    solo({
      revision: 11,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:00:15.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [{ current: squat, next: squat }],
    }),
  );
  expect(text(getByRole(root(flow), "region", { name: "Thomas" }))).toBe("GÅ TIL NÆSTE STATION Squat");
  expect(ringState(flow).name).toBe("SKIFT");

  // On the last work phase there is no next station.
  await push(flow, solo({ revision: 12, next_phase: null, stations: [{ current: planke, next: null }] }));
  expect(queryByRole(root(flow), "region", { name: "NÆSTE" })).toBeNull();
  expect(queryByRole(root(flow), "region", { name: "DEREFTER" })).toBeNull();
  document.body.replaceChildren();

  // Two people: a card each, in the person's colour: the badge with the person's number, the name,
  // the station, the exercise and the next line.
  const two = await mount(fakeHass("da"), view());
  const panels = getAllByRole(root(two.flow), "region");
  expect(panels.map((panel) => computeAccessibleName(panel))).toEqual(["Thomas", "Maria"]);
  expect(panels.map(text)).toEqual([
    "1 Thomas Station 1 Push-up Næste: station 2 · Squat",
    "2 Maria Station 2 Squat Næste: station 3 · Planke",
  ]);
  expect(getByRole(panels[0], "img", { name: "Push-up" })).toBeTruthy();
  expect(panels.map((panel) => panel.style.getPropertyValue("--person-color").trim().toUpperCase())).toEqual([
    "#B18CFF",
    "#3DD6C6",
  ]);
  expect(getByRole(panels[1], "img", { name: "Squat" })).toBeTruthy();
  // The ring is shared; the whole-workout bar is the second progressbar.
  expect(queryAllByRole(root(two.flow), "progressbar")).toHaveLength(2);
  expect(whole(two.flow)).toBeTruthy();

  await push(
    two.flow,
    view({
      revision: 11,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:00:15.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [
        { current: squat, next: squat },
        { current: planke, next: planke },
      ],
    }),
  );
  expect(getAllByRole(root(two.flow), "region").map(text)).toEqual([
    "1 Thomas Station 2 Squat Næste: station 2 · Squat",
    "2 Maria Station 3 Planke Næste: station 3 · Planke",
  ]);

  // On the last work phase the next line goes.
  await push(
    two.flow,
    view({
      revision: 12,
      next_phase: null,
      stations: [
        { current: planke, next: null },
        { current: push_up, next: null },
      ],
    }),
  );
  expect(getAllByRole(root(two.flow), "region").map(text)).toEqual([
    "1 Thomas Station 3 Planke",
    "2 Maria Station 1 Push-up",
  ]);
});

test("the two-person timer has the same buttons and progress bar as one person's", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  // The pill by the ring: the interval after it, no Station pill; no NÆSTE card.
  expect(hasPill(flow, "Interval 1 / 3")).toBe(true);
  expect(before(ring(flow), pill(flow, "Interval 1 / 3")!)).toBe(true);
  expect(hasPill(flow, "Station 1 / 3")).toBe(false);
  expect(queryByRole(root(flow), "region", { name: "NÆSTE" })).toBeNull();
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("360");

  await tap(flow, button(flow, "Pause"));
  expect(sent(fake)).toEqual(["pause"]);
});

test("elapsed from time_trained and server_time", async () => {
  const fake = fakeHass("da");
  // 6:00 trained as of the add-on's 08:00:00; the program plans 29:00.
  const { flow } = await mount(fake, view());
  expect(hasPill(flow, "6:00")).toBe(true);
  expect(hasPill(flow, "23:00 tilbage")).toBe(true);
  expect(hasPill(flow, "Interval 1")).toBe(true);

  // Running past the countdown: the time since server_time counts.
  await wait(flow, 12_000);
  expect(hasPill(flow, "6:12")).toBe(true);
  expect(hasPill(flow, "22:48 tilbage")).toBe(true);

  // Paused: the view's time_trained only.
  await push(flow, paused({ revision: 11, time_trained: 372, server_time: "2026-10-24T08:00:12.000Z" }));
  await wait(flow, 30_000);
  expect(hasPill(flow, "6:12")).toBe(true);
  expect(hasPill(flow, "22:48 tilbage")).toBe(true);
});

test("unreachable keeps counting, holds at zero, Luk after 10 s", async () => {
  const fake = fakeHass("da");
  const last = view({ phase: phase({ ends_at: "2026-10-24T08:00:20.000Z" }) });
  const { flow, onClose } = await mount(fake, last);
  expect(queryByText(root(flow), "HA Fitness kan ikke nås")).toBeNull();

  // The controller keeps the last view when the subscription is refused: the same stamp again.
  await wait(flow, 2_000);
  await push(flow, last, false);
  expect(hasText(flow, "HA Fitness kan ikke nås")).toBe(true);
  expect(ringState(flow).now).toBe("18");
  await wait(flow, 5_000);
  // A second unreachable message doesn't start the 10 s over.
  await push(flow, last, false);
  expect(ringState(flow).now).toBe("13");
  expect(queryByRole(root(flow), "button", { name: "Luk" })).toBeNull();

  await wait(flow, 4_999);
  expect(queryByRole(root(flow), "button", { name: "Luk" })).toBeNull();
  await wait(flow, 1);
  await tap(flow, button(flow, "Luk"));
  expect(onClose).toHaveBeenCalledTimes(1);

  // At zero it holds: no next phase while nobody can confirm it.
  await wait(flow, 10_000);
  expect(ringState(flow)).toMatchObject({ name: "ARBEJD", now: "0" });

  // Back again: the note and Luk go, and the next message corrects everything.
  await push(
    flow,
    view({
      revision: 12,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: "2026-10-24T08:00:30.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      server_time: "2026-10-24T08:00:22.000Z",
    }),
  );
  expect(queryByText(root(flow), "HA Fitness kan ikke nås")).toBeNull();
  expect(queryByRole(root(flow), "button", { name: "Luk" })).toBeNull();
  expect(ringState(flow)).toMatchObject({ name: "SKIFT", now: "8" });
});

test("the timer in English", async () => {
  const fake = fakeHass("en");
  const { flow } = await mount(fake, view());
  expect(ringState(flow).text).toBe("WORK 45 seconds left");
  expect(hasPill(flow, "Interval 1")).toBe(true);
  expect(hasPill(flow, "23:00 left")).toBe(true);
  expect(button(flow, "Pause")).toBeTruthy();
  expect(getAllByRole(root(flow), "region").map(text)[0]).toBe("1 Thomas Station 1 Push-up Next: station 2 · Squat");
  await tap(flow, button(flow, "End"));
  expect(hasText(flow, "End the workout?")).toBe(true);
  expect(button(flow, "Yes")).toBeTruthy();
  expect(button(flow, "No")).toBeTruthy();
});

test("a view handed over later counts from when it arrived", async () => {
  // The page's controller subscribed long before Fortsæt; messages come only on a change.
  let deliver: (message: SessionState) => void = () => undefined;
  const connection = {
    subscribeMessage: vi.fn(async (callback: (message: SessionState) => void) => {
      deliver = callback;
      return () => undefined;
    }),
  };
  const fake = fakeHass("da");
  overlay.setHass({ ...fake.hass, connection } as unknown as overlay.OverlayHass);
  await vi.advanceTimersByTimeAsync(0);
  deliver({ available: true, session: view() });

  await vi.advanceTimersByTimeAsync(20_000);
  overlay.open({ kind: "resume" });
  const flow = getByRole(document.body, "dialog").firstElementChild as FlowElement;
  await settle(flow);
  try {
    expect(ringState(flow).now).toBe("25");
    expect(hasPill(flow, "6:20")).toBe(true);
  } finally {
    overlay.close();
  }
});

test("a session's first view clears an alert from details", async () => {
  const program = {
    id: 3,
    name: "Onsdag",
    rounds: 5,
    work_seconds: 45,
    switch_seconds: 15,
    round_rest_seconds: 60,
    countdown_seconds: 10,
    total_minutes: 29,
    stations: [push_up, squat, planke].map(({ exercise_id, name }) => ({ exercise_id, name })),
  };
  const fake = fakeHass("da", [thomas, maria], [program]);
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  flow.hass = fake.hass;
  flow.state = { available: true, session: null };
  flow.mode = { kind: "details", programId: 3 };
  flow.onClose = vi.fn();
  await settle(flow);
  await tap(flow, button(flow, "Start"));
  fake.commands[0].reject({ code: "invalid", message: "Too many participants" });
  await settle(flow);
  expect(queryByRole(root(flow), "alert")).not.toBeNull();

  // A session started elsewhere arrives: the flow moves on, and the alert doesn't come along.
  await push(flow, view());
  expect(ring(flow)).toBeTruthy();
  expect(queryByRole(root(flow), "alert")).toBeNull();
});

test("the pills by the ring show the intervals out of the stations when the view has them", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasPill(flow, "Interval 1 / 3")).toBe(true);
  expect(hasPill(flow, "Station 1 / 3")).toBe(false);
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"), view({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasPill(en.flow, "Interval 1 / 3")).toBe(true);
  document.body.replaceChildren();

  // One person reads Station.
  const one = await mount(fakeHass("en"), solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasPill(one.flow, "Station 1 / 3")).toBe(true);
});

test("unreachable with no session keeps the ring counting", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());
  await wait(flow, 2_000);

  await push(flow, null, false);
  expect(hasText(flow, "HA Fitness kan ikke nås")).toBe(true);
  expect(ringState(flow).now).toBe("43");
  await wait(flow, 3_000);
  expect(ringState(flow).now).toBe("40");
});

test("unreachable with a new view object, a fresh stamp and the same revision keeps counting", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());
  await wait(flow, 2_000);

  await push(flow, view({ server_time: "2026-10-24T08:00:02.000Z" }), false);
  expect(ringState(flow).now).toBe("43");
  await wait(flow, 3_000);
  expect(ringState(flow).now).toBe("40");
});

test("get ready shows the work word at the countdown's local zero", async () => {
  const fake = fakeHass("da");
  const countdown = view({
    revision: 1,
    phase: phase({ index: 0, kind: "countdown", round: 1, duration: 10, ends_at: "2026-10-24T08:00:10.000Z" }),
    next_phase: { kind: "work", duration: 45 },
  });
  const { flow } = await mount(fake, countdown);
  expect(hasText(flow, "ARBEJD")).toBe(false);
  expect(hasText(flow, "10")).toBe(true);

  await wait(flow, 10_000);
  expect(hasText(flow, "ARBEJD")).toBe(true);
});

test("a late view of an older session can't pull the flow back", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ id: 8, revision: 1, phase: phase({ interval: 1 }) }));
  expect(hasPill(flow, "Interval 1")).toBe(true);

  await push(flow, view({ id: 7, revision: 30, phase: phase({ interval: 3 }) }));
  expect(hasPill(flow, "Interval 1")).toBe(true);
});

test("Luk counts from when the controller first learned the add-on was gone", async () => {
  let deliver: (message: SessionState) => void = () => undefined;
  const connection = {
    subscribeMessage: vi.fn(async (callback: (message: SessionState) => void) => {
      deliver = callback;
      return () => undefined;
    }),
  };
  const fake = fakeHass("da");
  overlay.setHass({ ...fake.hass, connection } as unknown as overlay.OverlayHass);
  await vi.advanceTimersByTimeAsync(0);
  const last = view({ revision: 50 });
  deliver({ available: true, session: last });
  await vi.advanceTimersByTimeAsync(1_000);
  deliver({ available: false, session: last });
  await vi.advanceTimersByTimeAsync(5_000);
  // A second unavailable message during the outage doesn't start it over.
  deliver({ available: false, session: last });
  await vi.advanceTimersByTimeAsync(6_000);

  // Fortsæt 11 s into the outage, 6 s after its second message: Luk shows at once.
  overlay.open({ kind: "resume" });
  const flow = getByRole(document.body, "dialog").firstElementChild as FlowElement;
  await settle(flow);
  try {
    expect(hasText(flow, "HA Fitness kan ikke nås")).toBe(true);
    expect(button(flow, "Luk")).toBeTruthy();
  } finally {
    overlay.close();
    deliver({ available: true, session: null });
  }
});

test("the GIFs coming up are fetched ahead", async () => {
  // Exercises no other test fetched: the image cache is page-wide.
  const burpee = { number: 1, exercise_id: "0901", name: "Burpee" };
  const lunge = { number: 2, exercise_id: "0902", name: "Lunge" };
  const row = { number: 3, exercise_id: "0903", name: "Row" };
  const gif = (id: string) => `/api/ha_fitness/media/${id}/gif`;
  const fake = fakeHass();

  // Get ready: the start stations' GIFs, so the first work phase doesn't start blank.
  const { flow } = await mount(
    fake,
    view({
      phase: phase({ index: 0, kind: "countdown", round: 1, duration: 10, ends_at: "2026-10-24T08:00:10.000Z" }),
      next_phase: { kind: "work", duration: 45 },
      stations: [
        { current: burpee, next: lunge },
        { current: lunge, next: row },
      ],
    }),
  );
  const fetched = () => fake.hass.fetchWithAuth.mock.calls.map((call) => (call as unknown[])[0]);
  expect(fetched()).toEqual(expect.arrayContaining([gif("0901"), gif("0902")]));

  // In a phase: the next stations' GIFs too.
  flow.state = {
    available: true,
    session: view({
      revision: 11,
      stations: [
        { current: burpee, next: lunge },
        { current: lunge, next: row },
      ],
    }),
  };
  await settle(flow);
  expect(fetched()).toContain(gif("0903"));
});

// The music player (music spec §6.2).

function music(state: MusicState["state"] = "playing", volume?: number | null): MusicState {
  const base: MusicState = { playlist_name: "Workout Mix", speaker: "media_player.living_room", speaker_name: "Stue", state };
  return volume === undefined ? base : { ...base, volume };
}

function player(flow: FlowElement, name = "Musik"): HTMLElement {
  return getByRole(root(flow), "group", { name });
}

function playerButton(flow: FlowElement, name: string, group = "Musik"): HTMLButtonElement {
  return getByRole(player(flow, group), "button", { name }) as HTMLButtonElement;
}

function musicSent(fake: Fake): Message[] {
  return fake.music.map((command) => command.message);
}

test("player shows playlist and speaker name", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, music());
  expect(text(player(flow))).toBe("Workout Mix Stue");
  document.body.replaceChildren();

  const english = await mount(fakeHass("en"), solo(), true, music());
  expect(text(player(english.flow, "Music"))).toBe("Workout Mix Stue");
  expect(playerButton(english.flow, "Pause music", "Music")).toBeTruthy();
  expect(playerButton(english.flow, "Next track", "Music")).toBeTruthy();
});

test("player shows Musik utilgængelig when unavailable", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, music("unavailable"));
  expect(text(player(flow))).toBe("Workout Mix Musik utilgængelig");
  document.body.replaceChildren();

  const english = await mount(fakeHass("en"), solo(), true, music("unavailable"));
  expect(text(player(english.flow, "Music"))).toBe("Workout Mix Music unavailable");
});

test("pause and next send ha_fitness/music", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("playing"));

  await tap(flow, playerButton(flow, "Pause musik"));
  await tap(flow, playerButton(flow, "Næste nummer"));
  expect(musicSent(fake)).toEqual([
    { type: "ha_fitness/music", action: "pause" },
    { type: "ha_fitness/music", action: "next" },
  ]);

  // A refused music command shows nothing; the subscription shows the real state.
  fake.music[0].reject({ code: "unavailable", message: "Speaker gone" });
  fake.music[1].resolve(view());
  await settle(flow);
  expect(queryByRole(root(flow), "alert")).toBeNull();

  await push(flow, solo(), true, music("paused"));
  await tap(flow, playerButton(flow, "Afspil musik"));
  expect(musicSent(fake).at(-1)).toEqual({ type: "ha_fitness/music", action: "play" });
  // The music commands are no session commands.
  expect(sent(fake)).toEqual([]);
});

test("buttons per state", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("waiting"));
  /** The player's two buttons, found by role and name in order (Pause or Play, then Next), and whether each is disabled. */
  const disabled = (toggle: string) => {
    const buttons = getAllByRole(player(flow), "button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toBe(playerButton(flow, toggle));
    expect(buttons[1]).toBe(playerButton(flow, "Næste nummer"));
    return buttons.map((element) => (element as HTMLButtonElement).disabled);
  };

  // Waiting for the first work phase: both disabled.
  expect(disabled("Afspil musik")).toEqual([true, true]);

  // Unavailable: Play can retry a failed start; Next can't.
  await push(flow, solo(), true, music("unavailable"));
  expect(disabled("Afspil musik")).toEqual([false, true]);

  await push(flow, solo(), true, music("playing"));
  expect(disabled("Pause musik")).toEqual([false, false]);

  await push(flow, solo(), true, music("paused"));
  expect(disabled("Afspil musik")).toEqual([false, false]);
});

test("no player when music is null", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, null);
  expect(queryByRole(root(flow), "group", { name: "Musik" })).toBeNull();
  expect(queryByRole(root(flow), "button", { name: "Næste nummer" })).toBeNull();
  document.body.replaceChildren();

  // An older integration sends no music at all.
  const older = await mount(fakeHass("da"), solo());
  expect(queryByRole(root(older.flow), "group", { name: "Musik" })).toBeNull();
});

// The volume slider (timer band and volume spec §2.2).

const VOLUME = "Musikkens lydstyrke";

function slider(flow: FlowElement): HTMLInputElement {
  return getByRole(player(flow), "slider", { name: VOLUME }) as HTMLInputElement;
}

/** Drag the thumb to `level`: the range input's `input` event. */
async function drag(flow: FlowElement, level: number): Promise<void> {
  const element = slider(flow);
  element.value = String(level);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  await settle(flow);
}

/** Let go of the thumb at `level`: the range input's `change` event. */
async function release(flow: FlowElement, level: number): Promise<void> {
  const element = slider(flow);
  element.value = String(level);
  element.dispatchEvent(new Event("change", { bubbles: true }));
  await settle(flow);
}

function volumeSent(fake: Fake): Message[] {
  return musicSent(fake).filter((message) => message.action === "volume");
}

test("no slider without volume", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, music("playing"));
  expect(queryByRole(player(flow), "slider")).toBeNull();
  document.body.replaceChildren();

  const nulled = await mount(fakeHass("da"), solo(), true, music("playing", null));
  expect(queryByRole(player(nulled.flow), "slider")).toBeNull();
});

test("the slider shows the volume", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, music("playing", 40));
  const element = slider(flow);
  expect(element.value).toBe("40");
  expect(element.min).toBe("0");
  expect(element.max).toBe("100");
  // The slider adds no text to the player.
  expect(text(player(flow))).toBe("Workout Mix Stue");
  document.body.replaceChildren();

  const english = await mount(fakeHass("en"), solo(), true, music("playing", 40));
  expect(getByRole(player(english.flow, "Music"), "slider", { name: "Music volume" })).toBeTruthy();
});

test("the slider is disabled while waiting and unavailable", async () => {
  const { flow } = await mount(fakeHass("da"), solo(), true, music("waiting", 40));
  expect(slider(flow).disabled).toBe(true);
  await push(flow, solo(), true, music("unavailable", 40));
  expect(slider(flow).disabled).toBe(true);
  await push(flow, solo(), true, music("playing", 40));
  expect(slider(flow).disabled).toBe(false);
  await push(flow, solo(), true, music("paused", 40));
  expect(slider(flow).disabled).toBe(false);
});

test("the slider sends throttled levels and one on release", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("playing", 40));

  await drag(flow, 50);
  expect(volumeSent(fake)).toEqual([{ type: "ha_fitness/music", action: "volume", level: 50 }]);
  await wait(flow, 100);
  await drag(flow, 55);
  await wait(flow, 100);
  await drag(flow, 60);
  expect(volumeSent(fake)).toHaveLength(1);
  await wait(flow, 100);
  expect(volumeSent(fake).map((message) => message.level)).toEqual([50, 60]);
  // Nothing new to send: the throttle sends nothing more.
  await wait(flow, 600);
  expect(volumeSent(fake)).toHaveLength(2);

  await release(flow, 60);
  expect(volumeSent(fake)).toEqual([
    { type: "ha_fitness/music", action: "volume", level: 50 },
    { type: "ha_fitness/music", action: "volume", level: 60 },
    { type: "ha_fitness/music", action: "volume", level: 60 },
  ]);
  // The volume is no session command.
  expect(sent(fake)).toEqual([]);
});

test("a release cancels the pending send and sends its own level", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("playing", 40));

  await drag(flow, 50);
  await wait(flow, 100);
  await drag(flow, 70);
  await wait(flow, 50);
  await release(flow, 75);
  await wait(flow, 600);

  expect(volumeSent(fake).map((message) => message.level)).toEqual([50, 75]);
});

test("a state while held doesn't move the thumb; after release it follows the state", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("playing", 40));

  await drag(flow, 50);
  await push(flow, solo(), true, music("playing", 45));
  expect(slider(flow).value).toBe("50");

  await release(flow, 50);
  await push(flow, solo(), true, music("playing", 52));
  expect(slider(flow).value).toBe("52");
  await push(flow, solo(), true, music("playing", 30));
  expect(slider(flow).value).toBe("30");
});

test("a refused set shows nothing", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo(), true, music("playing", 40));

  await release(flow, 65);
  fake.music[0].reject({ code: "unavailable", message: "Speaker gone" });
  await settle(flow);

  expect(queryByRole(root(flow), "alert")).toBeNull();
  // The slider follows the next music state.
  await push(flow, solo(), true, music("playing", 40));
  expect(slider(flow).value).toBe("40");
});

test("player in the two-person timer", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view(), true, music("playing"));
  expect(text(player(flow))).toBe("Workout Mix Stue");
  await tap(flow, playerButton(flow, "Næste nummer"));
  expect(musicSent(fake)).toEqual([{ type: "ha_fitness/music", action: "next" }]);
  // The timer's own control is still there.
  expect(button(flow, "Pause")).toBeTruthy();
});

// The cool-down (cool-down spec §4.7): four stretches after the circuit, each a hold and a change.
const lowerBack = { number: 1, exercise_id: "s-1", name: "Seated lower back stretch", part: "cooldown" as const };
const quad = { number: 2, exercise_id: "s-2", name: "Quad stretch", part: "cooldown" as const };
const hamstring = { number: 3, exercise_id: "s-3", name: "Hamstring stretch", part: "cooldown" as const };
const calf = { number: 4, exercise_id: "s-4", name: "Calf stretch", part: "cooldown" as const };
const COOLDOWN_TOTALS = { planned: 1900, rounds: 5, stations: 3, stretches: 4 };

/** The circuit's last work phase, with the rest before the cool-down next. */
function lastWork(overrides: Partial<SessionView> = {}): SessionView {
  return view({
    phase: phase({ index: 15, round: 5, interval: 3, part: "circuit" }),
    next_phase: { kind: "rest", duration: 60, part: "circuit" },
    stations: [
      { current: planke, next: lowerBack },
      { current: push_up, next: lowerBack },
    ],
    totals: COOLDOWN_TOTALS,
    ...overrides,
  });
}

/** The rest before the cool-down: everyone moves to the first stretch. */
function restBefore(overrides: Partial<SessionView> = {}): SessionView {
  return view({
    phase: phase({
      index: 16,
      kind: "rest",
      round: 5,
      interval: 3,
      duration: 60,
      ends_at: "2026-10-24T08:01:00.000Z",
      part: "circuit",
    }),
    next_phase: { kind: "work", duration: 30, part: "cooldown" },
    stations: [
      { current: lowerBack, next: quad },
      { current: lowerBack, next: quad },
    ],
    totals: COOLDOWN_TOTALS,
    ...overrides,
  });
}

/** The second stretch's hold. */
function hold(overrides: Partial<SessionView> = {}): SessionView {
  return view({
    phase: phase({
      index: 19,
      kind: "work",
      round: 1,
      interval: 2,
      duration: 30,
      ends_at: "2026-10-24T08:00:30.000Z",
      part: "cooldown",
    }),
    next_phase: { kind: "switch", duration: 10, part: "cooldown" },
    stations: [
      { current: quad, next: hamstring },
      { current: quad, next: hamstring },
    ],
    totals: COOLDOWN_TOTALS,
    ...overrides,
  });
}

/** The change from the second stretch to the third. */
function change(overrides: Partial<SessionView> = {}): SessionView {
  return view({
    phase: phase({
      index: 20,
      kind: "switch",
      round: 1,
      interval: 2,
      duration: 10,
      ends_at: "2026-10-24T08:00:10.000Z",
      part: "cooldown",
    }),
    next_phase: { kind: "work", duration: 30, part: "cooldown" },
    stations: [
      { current: hamstring, next: calf },
      { current: hamstring, next: calf },
    ],
    totals: COOLDOWN_TOTALS,
    ...overrides,
  });
}

/** One person: the first participant and station only. */
function alone(session: SessionView): SessionView {
  return { ...session, participants: [thomas], stations: session.stations!.slice(0, 1) };
}

function cards(flow: FlowElement): string[] {
  return getAllByRole(root(flow), "region").map(text);
}

function hasButton(flow: FlowElement, name: string): boolean {
  return queryByRole(root(flow), "button", { name }) !== null;
}

test("cool-down: the last circuit work points at the cool-down", async () => {
  const two = await mount(fakeHass("da"), lastWork());
  expect(ringState(two.flow).name).toBe("ARBEJD");
  expect(cards(two.flow)).toEqual([
    "1 Thomas Station 3 Planke Næste: udstrækning · Seated lower back stretch",
    "2 Maria Station 1 Push-up Næste: udstrækning · Seated lower back stretch",
  ]);
  expect(hasButton(two.flow, "Spring udstrækning over")).toBe(false);
  document.body.replaceChildren();

  // One person: the NEXT card is titled for the cool-down.
  const one = await mount(fakeHass("da"), alone(lastWork()));
  expect(text(getByRole(root(one.flow), "region", { name: "UDSTRÆKNING" }))).toBe(
    "UDSTRÆKNING Seated lower back stretch efter 60 s pause",
  );
  expect(queryByRole(root(one.flow), "region", { name: "NÆSTE" })).toBeNull();
});

test("cool-down: the rest before it reads COOL-DOWN NEXT and offers Skip", async () => {
  const two = await mount(fakeHass("da"), restBefore());
  expect(ringState(two.flow).name).toBe("PAUSE");
  // No station badge: the stretch has no station.
  expect(cards(two.flow)).toEqual([
    "1 Thomas NU KOMMER UDSTRÆKNING Seated lower back stretch Næste: Quad stretch",
    "2 Maria NU KOMMER UDSTRÆKNING Seated lower back stretch Næste: Quad stretch",
  ]);
  // The pill stays as the circuit's.
  expect(hasPill(two.flow, "Interval 3 / 3")).toBe(true);
  expect(hasButton(two.flow, "Spring udstrækning over")).toBe(true);
  expect(hasButton(two.flow, "Slut")).toBe(true);
  document.body.replaceChildren();

  const one = await mount(fakeHass("da"), alone(restBefore()));
  expect(text(getByRole(root(one.flow), "region", { name: "Thomas" }))).toBe(
    "NU KOMMER UDSTRÆKNING Seated lower back stretch",
  );
  expect(text(getByRole(root(one.flow), "region", { name: "DEREFTER" }))).toBe(
    "DEREFTER Quad stretch efter 30 s stræk",
  );
  expect(hasButton(one.flow, "Spring udstrækning over")).toBe(true);
});

test("cool-down: a hold shows STRETCH, the cool-down pill and the next stretch", async () => {
  const two = await mount(fakeHass("da"), hold());
  expect(ringState(two.flow)).toMatchObject({ name: "STRÆK", now: "30", text: "STRÆK 30 sekunder tilbage" });
  expect(hasPill(two.flow, "Udstrækning 2 / 4")).toBe(true);
  // Under the ring, the only pill.
  expect(before(ring(two.flow), pill(two.flow, "Udstrækning 2 / 4")!)).toBe(true);
  expect(queryAllByText(root(two.flow), /^Runde/)).toHaveLength(0);
  expect(queryAllByText(root(two.flow), /^Interval/)).toHaveLength(0);
  expect(cards(two.flow)).toEqual(["1 Thomas Quad stretch Næste: Hamstring stretch", "2 Maria Quad stretch Næste: Hamstring stretch"]);
  expect(getByRole(getAllByRole(root(two.flow), "region")[0], "img", { name: "Quad stretch" })).toBeTruthy();
  expect(hasButton(two.flow, "Spring udstrækning over")).toBe(true);

  // The last stretch: no next line.
  await push(
    two.flow,
    hold({
      revision: 11,
      phase: phase({ index: 23, round: 1, interval: 4, duration: 30, ends_at: "2026-10-24T08:00:30.000Z", part: "cooldown" }),
      next_phase: null,
      stations: [
        { current: calf, next: null },
        { current: calf, next: null },
      ],
    }),
  );
  expect(cards(two.flow)).toEqual(["1 Thomas Calf stretch", "2 Maria Calf stretch"]);
  expect(hasPill(two.flow, "Udstrækning 4 / 4")).toBe(true);
  document.body.replaceChildren();

  // One person: no Station pill either; the NEXT card shows the next stretch.
  const one = await mount(fakeHass("da"), alone(hold()));
  expect(text(getByRole(root(one.flow), "region", { name: "Thomas" }))).toBe("Quad stretch");
  expect(text(getByRole(root(one.flow), "region", { name: "NÆSTE" }))).toBe("NÆSTE Hamstring stretch efter 10 s skift");
  expect(queryAllByText(root(one.flow), /^Station/)).toHaveLength(0);
  expect(hasPill(one.flow, "Udstrækning 2 / 4")).toBe(true);
});

test("cool-down: a change shows CHANGE and NEXT STRETCH", async () => {
  const two = await mount(fakeHass("da"), change());
  expect(ringState(two.flow)).toMatchObject({ name: "SKIFT", text: "SKIFT 10 sekunder tilbage" });
  expect(hasPill(two.flow, "Udstrækning 2 / 4")).toBe(true);
  expect(cards(two.flow)).toEqual([
    "1 Thomas NÆSTE STRÆK Hamstring stretch Næste: Calf stretch",
    "2 Maria NÆSTE STRÆK Hamstring stretch Næste: Calf stretch",
  ]);
  document.body.replaceChildren();

  const one = await mount(fakeHass("da"), alone(change()));
  expect(text(getByRole(root(one.flow), "region", { name: "Thomas" }))).toBe("NÆSTE STRÆK Hamstring stretch");
  expect(text(getByRole(root(one.flow), "region", { name: "DEREFTER" }))).toBe("DEREFTER Calf stretch efter 30 s stræk");
});

test("cool-down: at local zero the ring shows the next phase's cool-down word", async () => {
  const { flow } = await mount(fakeHass("da"), hold());
  await wait(flow, 30_000);
  expect(ringState(flow)).toMatchObject({ name: "SKIFT", now: "10" });
  document.body.replaceChildren();

  // With no rest before it, the circuit's last work goes straight into the first hold.
  const straight = await mount(
    fakeHass("da"),
    lastWork({ next_phase: { kind: "work", duration: 30, part: "cooldown" } }),
  );
  await wait(straight.flow, 45_000);
  expect(ringState(straight.flow)).toMatchObject({ name: "STRÆK", now: "30" });
});

test("cool-down with no rest before it: the last work points at it, with no Skip", async () => {
  const { flow } = await mount(fakeHass("da"), lastWork({ next_phase: { kind: "work", duration: 30, part: "cooldown" } }));
  expect(cards(flow)).toEqual([
    "1 Thomas Station 3 Planke Næste: udstrækning · Seated lower back stretch",
    "2 Maria Station 1 Push-up Næste: udstrækning · Seated lower back stretch",
  ]);
  expect(hasButton(flow, "Spring udstrækning over")).toBe(false);
});

test("in a program with a cool-down, a rest between rounds and a circuit switch offer no Skip", async () => {
  const rest = view({
    phase: phase({ index: 6, kind: "rest", round: 2, interval: 3, duration: 60, part: "circuit" }),
    next_phase: { kind: "work", duration: 45, part: "circuit" },
    totals: COOLDOWN_TOTALS,
  });
  const restFlow = await mount(fakeHass("da"), rest);
  expect(ringState(restFlow.flow).name).toBe("PAUSE");
  expect(hasButton(restFlow.flow, "Spring udstrækning over")).toBe(false);
  expect(hasButton(restFlow.flow, "Slut")).toBe(true);
  document.body.replaceChildren();

  const circuitSwitch = view({
    phase: phase({ index: 2, kind: "switch", round: 1, interval: 1, duration: 15, part: "circuit" }),
    next_phase: { kind: "work", duration: 45, part: "circuit" },
    totals: COOLDOWN_TOTALS,
  });
  const switchFlow = await mount(fakeHass("da"), circuitSwitch);
  expect(ringState(switchFlow.flow).name).toBe("SKIFT");
  expect(hasButton(switchFlow.flow, "Spring udstrækning over")).toBe(false);
  expect(hasButton(switchFlow.flow, "Slut")).toBe(true);
});

test("Skip cool-down asks, with the wake-tap guard", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, hold());

  await tap(flow, button(flow, "Spring udstrækning over"));
  expect(hasText(flow, "Spring udstrækningen over?")).toBe(true);
  expect(hasButton(flow, "Spring udstrækning over")).toBe(false);

  // A tap on Ja right away does nothing.
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual([]);

  // Nej closes the question.
  await tap(flow, button(flow, "Nej"));
  expect(queryByText(root(flow), "Spring udstrækningen over?")).toBeNull();

  await tap(flow, button(flow, "Spring udstrækning over"));
  await wait(flow, 499);
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual([]);
  await wait(flow, 1);
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual(["skip_cooldown"]);
  expect(queryByText(root(flow), "Spring udstrækningen over?")).toBeNull();

  fake.commands[0].resolve(finished(true, { revision: 11 }));
  await settle(flow);
  expect(hasText(flow, "Træning gennemført")).toBe(true);
});

test("an unanswered Skip question goes after 10 s", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, restBefore());

  await tap(flow, button(flow, "Spring udstrækning over"));
  await wait(flow, 9_999);
  expect(hasText(flow, "Spring udstrækningen over?")).toBe(true);
  await wait(flow, 1);
  expect(queryByText(root(flow), "Spring udstrækningen over?")).toBeNull();
  expect(button(flow, "Spring udstrækning over")).toBeTruthy();
  expect(sent(fake)).toEqual([]);
});

test("opening the Skip or the End question closes the other", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, hold());

  await tap(flow, button(flow, "Slut"));
  expect(hasText(flow, "Afslut træningen?")).toBe(true);
  await tap(flow, button(flow, "Spring udstrækning over"));
  expect(queryByText(root(flow), "Afslut træningen?")).toBeNull();
  expect(hasText(flow, "Spring udstrækningen over?")).toBe(true);

  await tap(flow, button(flow, "Slut"));
  expect(queryByText(root(flow), "Spring udstrækningen over?")).toBeNull();
  expect(hasText(flow, "Afslut træningen?")).toBe(true);

  // The End question opened last is armed by itself, and sends end.
  await wait(flow, 500);
  await tap(flow, button(flow, "Ja"));
  expect(sent(fake)).toEqual(["end"]);
});

test("the Skip question goes when the session leaves the cool-down's reach", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, restBefore());

  await tap(flow, button(flow, "Spring udstrækning over"));
  expect(hasText(flow, "Spring udstrækningen over?")).toBe(true);

  // Forrige from another tablet: back in the circuit's last work.
  await push(flow, lastWork({ revision: 11 }));
  expect(queryByText(root(flow), "Spring udstrækningen over?")).toBeNull();
  expect(hasButton(flow, "Spring udstrækning over")).toBe(false);
  expect(button(flow, "Slut")).toBeTruthy();
});

test("an older add-on's view (no part, no stretches) renders the circuit as today", async () => {
  const { flow } = await mount(
    fakeHass("da"),
    view({ phase: phase({ index: 9, round: 5, interval: 3 }), next_phase: null, totals: { planned: 1740, rounds: 5, stations: 3 } }),
  );
  expect(ringState(flow).name).toBe("ARBEJD");
  expect(hasPill(flow, "Interval 3 / 3")).toBe(true);
  // No marks: the band has no gaps.
  expect(queryAllByRole(whole(flow), "separator", { hidden: true })).toHaveLength(0);
  expect(cards(flow)).toEqual([
    "1 Thomas Station 1 Push-up Næste: station 2 · Squat",
    "2 Maria Station 2 Squat Næste: station 3 · Planke",
  ]);
  expect(hasButton(flow, "Spring udstrækning over")).toBe(false);
});

test("the cool-down in English", async () => {
  const two = await mount(fakeHass("en"), lastWork());
  expect(cards(two.flow)[0]).toBe("1 Thomas Station 3 Planke Next: cool-down · Seated lower back stretch");
  await push(two.flow, restBefore({ revision: 11 }));
  expect(cards(two.flow)[0]).toBe("1 Thomas COOL-DOWN NEXT Seated lower back stretch Next: Quad stretch");
  expect(hasButton(two.flow, "Skip cool-down")).toBe(true);
  await push(two.flow, hold({ revision: 12 }));
  expect(ringState(two.flow)).toMatchObject({ name: "STRETCH", text: "STRETCH 30 seconds left" });
  expect(hasPill(two.flow, "Cool-down 2 / 4")).toBe(true);
  expect(cards(two.flow)[0]).toBe("1 Thomas Quad stretch Next: Hamstring stretch");
  await tap(two.flow, button(two.flow, "Skip cool-down"));
  expect(hasText(two.flow, "Skip the cool-down?")).toBe(true);
  await push(two.flow, change({ revision: 13 }));
  expect(ringState(two.flow).name).toBe("CHANGE");
  expect(cards(two.flow)[0]).toBe("1 Thomas NEXT STRETCH Hamstring stretch Next: Calf stretch");
  document.body.replaceChildren();

  const one = await mount(fakeHass("en"), alone(lastWork()));
  expect(text(getByRole(root(one.flow), "region", { name: "COOL-DOWN" }))).toBe(
    "COOL-DOWN Seated lower back stretch after 60 s rest",
  );
  await push(one.flow, alone(hold({ revision: 11 })));
  expect(text(getByRole(root(one.flow), "region", { name: "NEXT" }))).toBe("NEXT Hamstring stretch after 10 s change");
  await push(one.flow, alone(change({ revision: 12 })));
  expect(text(getByRole(root(one.flow), "region", { name: "THEN" }))).toBe("THEN Calf stretch after 30 s stretch");
});
