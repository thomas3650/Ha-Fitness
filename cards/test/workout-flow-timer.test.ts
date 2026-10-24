import { getAllByRole, getByRole, queryAllByRole, queryByRole, queryByText } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";
import * as overlay from "../src/overlay";
import type { OverlayMode, SessionPhase, SessionState, SessionView } from "../src/overlay";
import { installFakeAudio } from "./fake-audio";

// The flow element is defined once for the file, so its modules are imported statically; the
// audio and image modules keep page-wide state, and every test's fakes answer them the same way.
installFakeAudio("running");
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

/** A fake `hass` with `callWS` for §4's commands; each session command waits for the test. */
function fakeHass(language = "da", people = [thomas, maria], programs: unknown[] = []) {
  const commands: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/people") return Promise.resolve(people);
    if (message.type === "ha_fitness/programs") return Promise.resolve(programs);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve, reject) => commands.push({ message, resolve, reject }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  // Every exercise has a GIF and a thumbnail.
  const fetchWithAuth = vi.fn(async () => new Response(new Blob(["GIF89a"]), { status: 200 }));
  return { hass: { locale: { language }, callWS, fetchWithAuth }, callWS, commands };
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
async function mount(fake: Fake, session: SessionView | null, available = true) {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  const onClose = vi.fn();
  flow.hass = fake.hass;
  flow.state = { available, session };
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

async function push(flow: FlowElement, session: SessionView | null, available = true): Promise<void> {
  flow.state = { available, session };
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
    name: element.getAttribute("aria-label"),
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
  expect(hasText(flow, "Runde 2/5")).toBe(true);

  // A command result and a push can arrive in either order: revision 9 is older.
  await push(flow, view({ revision: 9, phase: phase({ round: 1 }) }));
  expect(hasText(flow, "Runde 2/5")).toBe(true);
  // The same revision again changes nothing either.
  await push(flow, view({ revision: 10, phase: phase({ round: 3 }) }));
  expect(hasText(flow, "Runde 2/5")).toBe(true);

  // A different session applies whatever its revision.
  await push(flow, view({ id: 8, revision: 1, phase: phase({ round: 1 }) }));
  expect(hasText(flow, "Runde 1/5")).toBe(true);
});

test("pause, resume and ring tap", async () => {
  const fake = fakeHass("en");
  const { flow } = await mount(fake, solo());

  await tap(flow, button(flow, "Pause"));
  expect(sent(fake)).toEqual(["pause"]);
  fake.commands[0].resolve(soloPaused({ revision: 11 }));
  await settle(flow);

  // Paused: the ring stops, keeps the phase word and says to tap; a PAUSED pill shows; the round
  // button resumes.
  expect(ringState(flow)).toMatchObject({ name: "WORK", now: "30", text: "WORK 30 tap the ring to resume" });
  expect(hasText(flow, "PAUSED")).toBe(true);
  expect(button(flow, "Resume")).toBeTruthy();
  expect(queryByRole(root(flow), "button", { name: "Pause" })).toBeNull();
  await wait(flow, 5_000);
  expect(ringState(flow).now).toBe("30");

  // A tap on the paused ring resumes.
  await tap(flow, ring(flow));
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
  expect(hasText(flow, "PAUSED")).toBe(false);

  // Tapping the running ring pauses.
  await tap(flow, ring(flow));
  expect(sent(fake)).toEqual(["pause", "resume", "pause"]);
  fake.commands[2].resolve(soloPaused({ revision: 13 }));
  await settle(flow);

  // The round button named Resume resumes too.
  await tap(flow, button(flow, "Resume"));
  expect(sent(fake)).toEqual(["pause", "resume", "pause", "resume"]);
});

test("the ring is no button and no tab stop", async () => {
  const { flow } = await mount(fakeHass("da"), solo());
  expect(ring(flow).getAttribute("tabindex")).toBeNull();
  expect(queryByRole(root(flow), "button", { name: "ARBEJD" })).toBeNull();
});

test("the three icon buttons send previous, pause and next", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo());

  await tap(flow, button(flow, "Forrige"));
  await tap(flow, button(flow, "Pause"));
  await tap(flow, button(flow, "Næste"));
  expect(sent(fake)).toEqual(["previous", "pause", "next"]);
});

test("the top row's pills for one person", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasText(flow, "Runde 2/5")).toBe(true);
  expect(hasText(flow, "Station 1/3")).toBe(true);
  expect(hasText(flow, "PAUSET")).toBe(false);

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
  expect(hasText(flow, "Station 1/3")).toBe(true);

  // Without the stations total, the number alone.
  await push(flow, solo({ revision: 12, phase: phase({ interval: 2 }) }));
  expect(hasText(flow, "Station 2")).toBe(true);

  // Paused: the PAUSET pill.
  await push(flow, soloPaused({ revision: 13 }));
  expect(hasText(flow, "PAUSET")).toBe(true);
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

test("the whole-workout bar's value stays within its maximum; the elapsed text doesn't", async () => {
  // Paused moments and Forrige can take a workout past its planned time.
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo({ time_trained: 1800 }));
  expect(whole(flow).getAttribute("aria-valuemax")).toBe("1740");
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("1740");
  expect(hasText(flow, "30:00 / 29:00")).toBe(true);
});

test("the whole-workout bar moves with the clock", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, solo());
  expect(whole(flow).getAttribute("aria-label")).toBe("Hele træningen");
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

test("previous and next send commands", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view());

  await tap(flow, button(flow, "Forrige"));
  await tap(flow, button(flow, "Næste"));
  expect(fake.commands.map((command) => command.message)).toEqual([
    { type: "ha_fitness/session/command", command: "previous" },
    { type: "ha_fitness/session/command", command: "next" },
  ]);

  // The result moves the flow, like any newer view.
  fake.commands[1].resolve(
    view({
      revision: 11,
      phase: phase({ index: 5, interval: 2, ends_at: "2026-10-24T08:00:45.000Z" }),
      stations: [
        { current: squat, next: planke },
        { current: planke, next: push_up },
      ],
    }),
  );
  await settle(flow);
  expect(hasText(flow, "Interval 2")).toBe(true);
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
  expect(panels.map((panel) => panel.getAttribute("aria-label"))).toEqual(["Thomas", "Maria"]);
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
  // The top row: the round and the interval, no Station pill; no NÆSTE card.
  expect(hasText(flow, "Runde 2/5")).toBe(true);
  expect(hasText(flow, "Interval 1/3")).toBe(true);
  expect(hasText(flow, "Station 1/3")).toBe(false);
  expect(queryByRole(root(flow), "region", { name: "NÆSTE" })).toBeNull();
  expect(whole(flow).getAttribute("aria-valuenow")).toBe("360");

  await tap(flow, button(flow, "Forrige"));
  await tap(flow, button(flow, "Pause"));
  await tap(flow, button(flow, "Næste"));
  await tap(flow, ring(flow));
  expect(sent(fake)).toEqual(["previous", "pause", "next", "pause"]);
});

test("elapsed from time_trained and server_time", async () => {
  const fake = fakeHass("da");
  // 6:00 trained as of the add-on's 08:00:00; the program plans 29:00.
  const { flow } = await mount(fake, view());
  expect(hasText(flow, "6:00 / 29:00")).toBe(true);
  expect(hasText(flow, "Runde 2/5")).toBe(true);
  expect(hasText(flow, "Interval 1")).toBe(true);

  // Running past the countdown: the time since server_time counts.
  await wait(flow, 12_000);
  expect(hasText(flow, "6:12 / 29:00")).toBe(true);

  // Paused: the view's time_trained only.
  await push(flow, paused({ revision: 11, time_trained: 372, server_time: "2026-10-24T08:00:12.000Z" }));
  await wait(flow, 30_000);
  expect(hasText(flow, "6:12 / 29:00")).toBe(true);
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
  expect(hasText(flow, "Round 2/5")).toBe(true);
  expect(button(flow, "Previous")).toBeTruthy();
  expect(button(flow, "Next")).toBeTruthy();
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
    expect(hasText(flow, "6:20 / 29:00")).toBe(true);
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

test("the header shows the intervals out of the stations when the view has them", async () => {
  const fake = fakeHass("da");
  const { flow } = await mount(fake, view({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasText(flow, "Interval 1/3")).toBe(true);
  expect(hasText(flow, "Station 1/3")).toBe(false);
  document.body.replaceChildren();

  const en = await mount(fakeHass("en"), view({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasText(en.flow, "Interval 1/3")).toBe(true);
  document.body.replaceChildren();

  // One person reads Station.
  const one = await mount(fakeHass("en"), solo({ totals: { planned: 1740, rounds: 5, stations: 3 } }));
  expect(hasText(one.flow, "Station 1/3")).toBe(true);
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
  const { flow } = await mount(fake, view({ id: 8, revision: 1, phase: phase({ round: 1 }) }));
  expect(hasText(flow, "Runde 1/5")).toBe(true);

  await push(flow, view({ id: 7, revision: 30, phase: phase({ round: 4 }) }));
  expect(hasText(flow, "Runde 1/5")).toBe(true);
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
