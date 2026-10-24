import { getByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";

import { type ToneKind, scheduleTone, unlockAudio } from "../src/audio";
import "../src/index";
import type { OverlayMode, SessionPhase, SessionState, SessionView } from "../src/overlay";
import { type FakeTone, installFakeAudio } from "./fake-audio";

// The audio module keeps one context for the page, so the file shares one fake context. Each test
// reads only the tones made after it began.
const audio = installFakeAudio("running");
vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:image");

interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: OverlayMode;
  onClose?: () => void;
  updateComplete: Promise<boolean>;
}

const thomas = { id: 1, name: "Thomas" };
const push_up = { number: 1, exercise_id: "0001", name: "Push-up" };
const squat = { number: 2, exercise_id: "0002", name: "Squat" };

type Message = { type: string } & Record<string, unknown>;

interface Pending {
  message: Message;
  resolve(view: SessionView): void;
}

function fakeHass(language = "da") {
  const commands: Pending[] = [];
  const callWS = vi.fn((message: Message): Promise<unknown> => {
    if (message.type === "ha_fitness/people") return Promise.resolve([thomas]);
    if (message.type === "ha_fitness/session/command") {
      return new Promise((resolve) => commands.push({ message, resolve }));
    }
    return Promise.reject({ code: "unknown_command", message: "Unknown command." });
  });
  const fetchWithAuth = vi.fn(async () => new Response(new Blob(["GIF89a"]), { status: 200 }));
  return { hass: { locale: { language }, callWS, fetchWithAuth }, commands };
}

type Fake = ReturnType<typeof fakeHass>;

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

/** A running one-person session in a 45 s work phase that started at 08:00:00, then a switch. */
function view(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: 7,
    revision: 10,
    status: "running",
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [thomas],
    phase: phase(),
    next_phase: { kind: "switch", duration: 15 },
    stations: [{ current: push_up, next: squat }],
    totals: { planned: 1740, rounds: 5 },
    started_at: "2026-10-24T07:54:00.000Z",
    ended_at: null,
    rounds_completed: 1,
    time_trained: 360,
    server_time: "2026-10-24T08:00:00.000Z",
    ...overrides,
  };
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

/** The add-on's ISO time `seconds` after 08:00:00. */
function at(seconds: number): string {
  return new Date(BASE + seconds * 1000).toISOString();
}

const BASE = Date.parse("2026-10-24T08:00:00.000Z");
/** Each tone kind's frequencies, learnt from the audio module itself. */
const kindOf = new Map<number, ToneKind>();
let mark = 0;

beforeAll(() => {
  unlockAudio();
  for (const kind of ["beep", "work", "rest", "chime"] as ToneKind[]) {
    const before = audio.tones().length;
    scheduleTone(kind, 0, 0)();
    for (const tone of audio.tones().slice(before)) kindOf.set(tone.frequency, kind);
  }
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(BASE));
  context().currentTime = 0;
  mark = audio.tones().length;
});

afterEach(() => {
  document.body.replaceChildren();
  context().setState("running");
  vi.useRealTimers();
});

function context() {
  return audio.contexts[0];
}

/** The tones this test made that weren't cancelled: their kind and start, in seconds after 08:00:00. */
function live(): { kind: ToneKind | undefined; start: number }[] {
  return audio
    .tones()
    .slice(mark)
    .filter((tone: FakeTone) => !tone.cancelled)
    .map((tone) => ({ kind: kindOf.get(tone.frequency), start: Math.round((tone.start ?? -1) * 1000) / 1000 }))
    .sort((a, b) => a.start - b.start);
}

function beeps(...starts: number[]) {
  return starts.map((start) => ({ kind: "beep", start }));
}

async function mount(fake: Fake, session: SessionView | null, available = true) {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  flow.hass = fake.hass;
  flow.state = { available, session };
  flow.mode = { kind: "resume" };
  flow.onClose = vi.fn();
  await settle(flow);
  return flow;
}

/** Let the flow settle, with the audio clock moved along with the page's. */
async function settle(flow: FlowElement): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
  await flow.updateComplete;
}

async function wait(flow: FlowElement, ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
  context().currentTime = (Date.now() - BASE) / 1000;
  await flow.updateComplete;
}

async function push(flow: FlowElement, session: SessionView | null, available = true): Promise<void> {
  flow.state = { available, session };
  await settle(flow);
}

async function tap(flow: FlowElement, name: string): Promise<void> {
  (getByRole(root(flow), "button", { name }) as HTMLButtonElement).click();
  await settle(flow);
}

function root(flow: FlowElement): HTMLElement {
  return flow.shadowRoot as unknown as HTMLElement;
}

test("beeps at 5,4,3,2,1", async () => {
  await mount(fakeHass(), view());

  // 5 to 1 s before the end at 45 s, then the switch's change tone at local zero.
  expect(live()).toEqual([...beeps(40, 41, 42, 43, 44), { kind: "rest", start: 45 }]);
});

test("short phase beeps only its seconds", async () => {
  // A 3 s switch from 5 s to 8 s, in a view stamped before it starts, so 5 and 4 s before its end
  // are still ahead: only 2 and 1 s left beep; 3 s left is the phase's start.
  await mount(
    fakeHass(),
    view({
      phase: phase({ index: 4, kind: "switch", duration: 3, ends_at: at(8) }),
      next_phase: { kind: "work", duration: 45 },
    }),
  );

  expect(live()).toEqual([...beeps(6, 7), { kind: "work", start: 8 }]);
});

test("no beep in first 0.3 s", async () => {
  // A 5 s phase from 1 s to 6 s, in a view stamped before it starts: 5 s left is its first
  // instant, where the change tone plays.
  const flow = await mount(fakeHass(), view({ phase: phase({ duration: 5, ends_at: at(6) }) }));
  expect(live()).toEqual([...beeps(2, 3, 4, 5), { kind: "rest", start: 6 }]);

  // A view that arrives 2.5 s into a phase schedules only what is still ahead; nothing plays at once.
  document.body.replaceChildren();
  await wait(flow, 2_500);
  mark = audio.tones().length;
  await mount(fakeHass(), view({ revision: 11, phase: phase({ duration: 5, ends_at: at(5) }), server_time: at(2.5) }));
  expect(live()).toEqual([...beeps(3, 4), { kind: "rest", start: 5 }]);
});

test("rescheduled after pause, next and newer revision", async () => {
  const fake = fakeHass("da");
  const flow = await mount(fake, view());
  await wait(flow, 30_000);

  // Paused: every pending tone goes, and none comes.
  await tap(flow, "Pause");
  fake.commands[0].resolve(
    view({ revision: 11, status: "paused", phase: phase({ ends_at: null, remaining: 15 }), server_time: at(30) }),
  );
  await settle(flow);
  expect(live()).toEqual([]);

  // Resumed at 35 s with 15 s left: the end moves to 50 s.
  await wait(flow, 5_000);
  await tap(flow, "Fortsæt");
  fake.commands[1].resolve(view({ revision: 12, phase: phase({ ends_at: at(50) }), server_time: at(35) }));
  await settle(flow);
  expect(live()).toEqual([...beeps(45, 46, 47, 48, 49), { kind: "rest", start: 50 }]);

  // Næste: the switch starts now, with its change tone, and ends at 50 s; the old ones go, the new
  // ones come once.
  await tap(flow, "Næste");
  fake.commands[2].resolve(
    view({
      revision: 13,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: at(50) }),
      next_phase: { kind: "work", duration: 45 },
      server_time: at(35),
    }),
  );
  await settle(flow);
  expect(live()).toEqual([{ kind: "rest", start: 35 }, ...beeps(45, 46, 47, 48, 49), { kind: "work", start: 50 }]);
  mark = audio.tones().length;

  // A newer revision that moves the end to 52 s.
  await push(
    flow,
    view({
      revision: 14,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: at(52) }),
      next_phase: { kind: "work", duration: 45 },
      server_time: at(35),
    }),
  );
  expect(live()).toEqual([...beeps(47, 48, 49, 50, 51), { kind: "work", start: 52 }]);

  // An older revision changes nothing.
  await push(flow, view({ revision: 12, phase: phase({ ends_at: at(50) }), server_time: at(35) }));
  expect(live()).toEqual([...beeps(47, 48, 49, 50, 51), { kind: "work", start: 52 }]);
});

test("work and switch/rest tones at local zero", async () => {
  // The countdown ends at 10 s; work follows.
  const flow = await mount(
    fakeHass(),
    view({
      revision: 1,
      phase: phase({ index: 0, kind: "countdown", round: 1, duration: 10, ends_at: at(10) }),
      next_phase: { kind: "work", duration: 45 },
    }),
  );
  expect(live()).toEqual([...beeps(5, 6, 7, 8, 9), { kind: "work", start: 10 }]);

  // The work tone plays at local zero; the message that confirms work, 50 ms later, doesn't cut it.
  await wait(flow, 10_050);
  await push(
    flow,
    view({
      revision: 2,
      phase: phase({ index: 1, round: 1, ends_at: at(55) }),
      next_phase: { kind: "rest", duration: 60 },
      server_time: at(10.05),
    }),
  );
  expect(live()).toEqual([
    ...beeps(5, 6, 7, 8, 9),
    { kind: "work", start: 10 },
    ...beeps(50, 51, 52, 53, 54),
    { kind: "rest", start: 55 },
  ]);

  // Unreachable: the ring holds at zero, so no change tone; the beeps stay.
  mark = audio.tones().length;
  await push(
    flow,
    view({
      revision: 2,
      phase: phase({ index: 1, round: 1, ends_at: at(55) }),
      next_phase: { kind: "rest", duration: 60 },
      server_time: at(10.05),
    }),
    false,
  );
  expect(live()).toEqual(beeps(50, 51, 52, 53, 54));
});

test("completion chime", async () => {
  const flow = await mount(fakeHass(), view({ phase: phase({ index: 9, round: 5, interval: 3 }), next_phase: null }));
  // The last phase: beeps, and no change tone.
  expect(live()).toEqual(beeps(40, 41, 42, 43, 44));

  await wait(flow, 45_000);
  mark = audio.tones().length;
  await push(flow, finished(true, { server_time: at(45) }));
  expect(live()).toEqual([
    { kind: "chime", start: 45 },
    { kind: "chime", start: 45.22 },
    { kind: "chime", start: 45.44 },
  ]);

  // A session ended with Slut doesn't chime, nor does a done step opened later.
  document.body.replaceChildren();
  mark = audio.tones().length;
  const ended = await mount(fakeHass(), view({ id: 8 }));
  mark = audio.tones().length;
  await push(ended, finished(false, { id: 8, server_time: at(45) }));
  expect(live()).toEqual([]);
  document.body.replaceChildren();
  await mount(fakeHass(), finished(true, { id: 9, server_time: at(45) }));
  expect(live()).toEqual([]);
});

test("Tryk for lyd when locked", async () => {
  // After a reload no tap has unlocked the audio.
  context().setState("suspended");
  const flow = await mount(fakeHass("da"), view());
  expect(live()).toEqual([]);

  // The tap unlocks it, and the pings come.
  await tap(flow, "Tryk for lyd");
  expect(queryByRole(root(flow), "button", { name: "Tryk for lyd" })).toBeNull();
  expect(live()).toEqual([...beeps(40, 41, 42, 43, 44), { kind: "rest", start: 45 }]);

  // The browser suspends it again: the pending ones go, and the button is back.
  await wait(flow, 1_000);
  context().setState("suspended");
  await settle(flow);
  expect(live()).toEqual([]);
  expect(getByRole(root(flow), "button", { name: "Tryk for lyd" })).toBeTruthy();

  // In English, and on get ready too.
  document.body.replaceChildren();
  const ready = await mount(
    fakeHass("en"),
    view({ phase: phase({ index: 0, kind: "countdown", round: 1, duration: 10, ends_at: at(11) }) }),
  );
  expect(getByRole(root(ready), "button", { name: "Tap for sound" })).toBeTruthy();
});

test("Fortsæt unlocks the audio in the tap", async () => {
  context().setState("suspended");
  const flow = await mount(
    fakeHass("da"),
    view({ status: "paused", phase: phase({ ends_at: null, remaining: 30 }) }),
  );

  context().resume.mockClear();
  (getByRole(root(flow), "button", { name: "Fortsæt" }) as HTMLButtonElement).click();
  // Synchronously, before the command's answer.
  expect(context().resume).toHaveBeenCalledTimes(1);
});

test("tones follow the add-on's clock, not the tablet's", async () => {
  // The add-on's clock is 3 s ahead of the tablet's: the view, stamped 3 s after 08:00:00 local,
  // has its work phase end at 48 s. On the tablet's audio clock everything is 3 s earlier.
  await mount(fakeHass(), view({ phase: phase({ ends_at: at(48) }), server_time: at(3) }));
  expect(live()).toEqual([...beeps(40, 41, 42, 43, 44), { kind: "rest", start: 45 }]);
});

test("Næste and Forrige play the change tone of the phase they start", async () => {
  const fake = fakeHass("da");
  const flow = await mount(fake, view());
  await wait(flow, 30_000);

  // Næste in the middle of work: the switch starts now, with its low tone, and ends at 45 s.
  await tap(flow, "Næste");
  fake.commands[0].resolve(
    view({
      revision: 11,
      phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: at(45) }),
      next_phase: { kind: "work", duration: 45 },
      server_time: at(30),
    }),
  );
  await settle(flow);
  expect(live()).toEqual([{ kind: "rest", start: 30 }, ...beeps(40, 41, 42, 43, 44), { kind: "work", start: 45 }]);

  // Forrige 2 s later: work starts again, with its high tone, and ends at 77 s.
  await wait(flow, 2_000);
  mark = audio.tones().length;
  await tap(flow, "Forrige");
  fake.commands[1].resolve(
    view({ revision: 12, phase: phase({ index: 3, ends_at: at(77) }), server_time: at(32) }),
  );
  await settle(flow);
  expect(live()).toEqual([{ kind: "work", start: 32 }, ...beeps(72, 73, 74, 75, 76), { kind: "rest", start: 77 }]);
});

test("a natural phase change gets its change tone once", async () => {
  // The switch ends at 45 s; its work tone plays at local zero. The message that confirms work
  // arrives just after, and adds no second tone.
  const flow = await mount(fakeHass(), view({ phase: phase({ index: 4, kind: "switch", duration: 15, ends_at: at(45) }), next_phase: { kind: "work", duration: 45 } }));
  await wait(flow, 45_020);
  mark = audio.tones().length;
  await push(flow, view({ revision: 11, phase: phase({ index: 5, ends_at: at(90) }), server_time: at(45.02) }));
  expect(live()).toEqual([...beeps(85, 86, 87, 88, 89), { kind: "rest", start: 90 }]);
});

test("a clock correction alone never plays a tone twice", async () => {
  const flow = await mount(fakeHass(), view());
  // 50 ms into the beep at 40 s (5 s left).
  await wait(flow, 40_050);

  // The same revision again, stamped 0.2 s behind: only the clock moves. The beep already playing
  // isn't cut or played again; the ones still ahead move by the 0.2 s.
  await push(flow, view({ server_time: at(39.85) }));
  expect(live()).toEqual([...beeps(40, 41.2, 42.2, 43.2, 44.2), { kind: "rest", start: 45.2 }]);
});

test("Tryk for lyd goes when the audio runs, however it was unlocked", async () => {
  context().setState("suspended");
  const flow = await mount(fakeHass("da"), view());
  expect(getByRole(root(flow), "button", { name: "Tryk for lyd" })).toBeTruthy();

  // Another tap on the page (a card's Fortsæt, say) unlocked it; the browser says so with `statechange`.
  context().setState("running");
  await settle(flow);
  expect(queryByRole(root(flow), "button", { name: "Tryk for lyd" })).toBeNull();
  expect(live()).toEqual([...beeps(40, 41, 42, 43, 44), { kind: "rest", start: 45 }]);

  // The flow's own button: resume() finishes after the tap, and the button goes then.
  context().setState("suspended");
  await settle(flow);
  (getByRole(root(flow), "button", { name: "Tryk for lyd" }) as HTMLButtonElement).click();
  expect(context().state).toBe("suspended");
  await settle(flow);
  expect(queryByRole(root(flow), "button", { name: "Tryk for lyd" })).toBeNull();
});

test("a clock correction never loses a tone that was waiting", async () => {
  const flow = await mount(fakeHass(), view());
  // 0.15 s before the beep at 41 s (4 s left).
  await wait(flow, 40_850);

  // The same revision again, stamped 0.2 s ahead: on the corrected clock the beep at 41 s is due
  // already. It plays at once instead of being dropped; the ones ahead move by the 0.2 s.
  await push(flow, view({ server_time: at(41.05) }));
  expect(live()).toEqual([...beeps(40, 40.85, 41.8, 42.8, 43.8), { kind: "rest", start: 44.8 }]);
});
