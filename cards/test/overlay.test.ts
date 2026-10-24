import { getAllByRole, queryAllByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

type Overlay = typeof import("../src/overlay");
type SessionState = import("../src/overlay").SessionState;

/** What the controller hands the flow element. */
interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: unknown;
  onClose?: () => void;
}

/** The flow element's stand-in (the real one is F2's); it records each one put on the page. */
const flows: FlowElement[] = [];
if (!customElements.get("ha-fitness-workout-flow")) {
  customElements.define(
    "ha-fitness-workout-flow",
    class extends HTMLElement {
      connectedCallback() {
        flows.push(this);
      }
    },
  );
}

type Listener = (message: unknown) => void;

/** A fake of home-assistant-js-websocket's connection, as in the today card's tests. */
function fakeConnection() {
  const listeners: Listener[] = [];
  const unsubscribes: ReturnType<typeof vi.fn>[] = [];
  const events = new Map<string, Set<() => void>>();
  let refuse = false;
  const subscribeMessage = vi.fn<
    (callback: Listener, message: unknown, options?: unknown) => Promise<() => void>
  >((callback) => {
    if (refuse) return Promise.reject(new Error("unknown command"));
    listeners.push(callback);
    const unsubscribe = vi.fn();
    unsubscribes.push(unsubscribe);
    return Promise.resolve(unsubscribe);
  });
  const connection = {
    subscribeMessage,
    addEventListener(type: string, callback: () => void) {
      if (!events.has(type)) events.set(type, new Set());
      events.get(type)!.add(callback);
    },
    removeEventListener(type: string, callback: () => void) {
      events.get(type)?.delete(callback);
    },
  };
  return {
    connection,
    subscribeMessage,
    listeners,
    unsubscribes,
    refuseNext() {
      refuse = true;
    },
    fire(type: string) {
      for (const callback of events.get(type) ?? []) callback();
    },
    push(message: unknown) {
      const listener = listeners.at(-1);
      if (!listener) throw new Error("the controller has not subscribed");
      listener(message);
    },
  };
}

function fakeHass() {
  const socket = fakeConnection();
  return { ...socket, hass: { locale: { language: "da" }, connection: socket.connection } };
}

/** A running session view, in the shape of spec §3.5. */
function view(revision = 1, status: "running" | "paused" | "completed" | "ended" = "running") {
  return {
    id: 4,
    revision,
    status,
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [{ id: 1, name: "Thomas" }],
    phase: {
      index: 1,
      kind: "work",
      round: 1,
      interval: 1,
      duration: 45,
      ends_at: "2026-10-24T08:00:45.000Z",
      remaining: null,
    },
    next_phase: { kind: "switch", duration: 15 },
    stations: [
      {
        current: { number: 1, exercise_id: "0001", name: "Push-up" },
        next: { number: 2, exercise_id: "0002", name: "Squat" },
      },
    ],
    totals: { planned: 1740, rounds: 5 },
    started_at: "2026-10-24T07:59:55.000Z",
    ended_at: null,
    rounds_completed: 0,
    time_trained: 0,
    server_time: "2026-10-24T08:00:00.000Z",
  };
}

let overlay: Overlay;

beforeEach(async () => {
  // The controller is page-wide; each test gets a fresh page.
  vi.resetModules();
  overlay = await import("../src/overlay");
  flows.length = 0;
  document.documentElement.style.overflow = "";
});

afterEach(() => {
  overlay.close();
  document.body.replaceChildren();
});

/** Let the subscription's promise settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function theDialog(): HTMLDialogElement {
  const dialogs = getAllByRole(document.body, "dialog");
  expect(dialogs).toHaveLength(1);
  return dialogs[0] as HTMLDialogElement;
}

function theFlow(): FlowElement {
  expect(flows).toHaveLength(1);
  return flows[0];
}

test("opens one dialog in body that survives the opening card's removal", () => {
  const fake = fakeHass();
  const card = document.createElement("div");
  document.body.append(card);
  overlay.setHass(fake.hass);

  overlay.open({ kind: "details", programId: 3, trainingDayId: 12 });
  card.remove();

  const dialog = theDialog();
  expect(dialog.parentElement).toBe(document.body);
  expect(dialog.open).toBe(true);
  const flow = theFlow();
  expect(dialog.contains(flow)).toBe(true);
  expect(flow.hass).toBe(fake.hass);
  expect(flow.mode).toEqual({ kind: "details", programId: 3, trainingDayId: 12 });
  expect(flow.state).toEqual({ available: false, session: null });

  // Opening again (Fortsæt) reuses the one dialog and flow.
  overlay.open({ kind: "resume" });
  expect(theDialog()).toBe(dialog);
  expect(theFlow().mode).toEqual({ kind: "resume" });
});

test("cancel event is prevented and the dialog stays open", () => {
  overlay.setHass(fakeHass().hass);
  overlay.open({ kind: "resume" });
  const dialog = theDialog();

  const cancel = new Event("cancel", { cancelable: true });
  dialog.dispatchEvent(cancel);

  expect(cancel.defaultPrevented).toBe(true);
  expect(theDialog().open).toBe(true);
  expect(dialog.getAttribute("closedby")).toBe("none");
});

test("backdrop click ignored", () => {
  overlay.setHass(fakeHass().hass);
  overlay.open({ kind: "resume" });
  const dialog = theDialog();

  // A tap on the backdrop reaches the dialog itself.
  dialog.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

  expect(theDialog()).toBe(dialog);
  expect(dialog.open).toBe(true);
  expect(dialog.contains(theFlow())).toBe(true);
});

test("a close the controller didn't ask for opens the dialog again", () => {
  overlay.setHass(fakeHass().hass);
  overlay.open({ kind: "resume" });
  const dialog = theDialog();

  dialog.close();

  expect(theDialog()).toBe(dialog);
  expect(dialog.open).toBe(true);
  expect(document.documentElement.style.overflow).toBe("hidden");
});

test("scroll locked while open and restored on close", () => {
  document.documentElement.style.overflow = "auto";
  overlay.setHass(fakeHass().hass);

  overlay.open({ kind: "details", programId: 3 });
  expect(document.documentElement.style.overflow).toBe("hidden");

  // The flow's own button closes it.
  theFlow().onClose!();

  expect(queryAllByRole(document.body, "dialog", { hidden: true })).toHaveLength(0);
  expect(document.documentElement.style.overflow).toBe("auto");

  // It opens again later as new.
  overlay.open({ kind: "resume" });
  expect(theDialog().open).toBe(true);
  expect(document.documentElement.style.overflow).toBe("hidden");
  overlay.close();
  expect(document.documentElement.style.overflow).toBe("auto");
});

test("subscribes from first setHass with resubscribe false; listeners get state", async () => {
  const fake = fakeHass();
  const listener = vi.fn();
  const unsubscribe = overlay.subscribe(listener);

  overlay.setHass(fake.hass);
  overlay.setHass({ ...fake.hass });
  await settle();

  expect(fake.subscribeMessage).toHaveBeenCalledTimes(1);
  expect(fake.subscribeMessage).toHaveBeenCalledWith(
    expect.any(Function),
    { type: "ha_fitness/session/subscribe" },
    { resubscribe: false },
  );

  overlay.open({ kind: "resume" });
  const session = view();
  fake.push({ available: true, session });

  expect(overlay.state()).toEqual({ available: true, session });
  expect(listener).toHaveBeenLastCalledWith({ available: true, session });
  // The flow doesn't subscribe itself; the controller sets its state.
  expect(theFlow().state).toEqual({ available: true, session });

  unsubscribe();
  fake.push({ available: true, session: null });
  expect(listener).toHaveBeenCalledTimes(1);
  expect(overlay.state()).toEqual({ available: true, session: null });
});

test("setHass while open hands the flow the newest hass", () => {
  const fake = fakeHass();
  overlay.setHass(fake.hass);
  overlay.open({ kind: "resume" });

  const newer = { ...fake.hass, locale: { language: "en" } };
  overlay.setHass(newer);

  expect(theFlow().hass).toBe(newer);
});

test("a reconnect subscribes again and the old subscription's messages are ignored", async () => {
  const fake = fakeHass();
  overlay.setHass(fake.hass);
  await settle();
  const [oldListener] = fake.listeners;

  fake.fire("ready");
  await settle();

  expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);
  expect(fake.unsubscribes[0]).toHaveBeenCalled();
  fake.push({ available: true, session: view(2) });
  oldListener({ available: true, session: null });

  expect(overlay.state()).toEqual({ available: true, session: view(2) });
});

test("a refused subscription keeps the last view, unavailable, and retries after 5 s", async () => {
  vi.useFakeTimers();
  try {
    const fake = fakeHass();
    overlay.setHass(fake.hass);
    await vi.advanceTimersByTimeAsync(0);
    fake.push({ available: true, session: view(3) });

    fake.refuseNext();
    fake.fire("ready");
    await vi.advanceTimersByTimeAsync(0);
    expect(overlay.state()).toEqual({ available: false, session: view(3) });
    expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(4_999);
    expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fake.subscribeMessage).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});

test("a dialog removed from the page by someone else is built again", () => {
  document.documentElement.style.overflow = "auto";
  overlay.setHass(fakeHass().hass);
  overlay.open({ kind: "details", programId: 3 });

  // Home Assistant can replace the page's body content, taking the dialog with it.
  document.body.replaceChildren();
  flows.length = 0;
  overlay.open({ kind: "resume" });

  const dialog = theDialog();
  expect(dialog.isConnected).toBe(true);
  expect(dialog.open).toBe(true);
  expect(theFlow().mode).toEqual({ kind: "resume" });

  overlay.close();
  expect(queryAllByRole(document.body, "dialog", { hidden: true })).toHaveLength(0);
  expect(document.documentElement.style.overflow).toBe("auto");
});

test("a dropped HA connection counts as unreachable until it is ready again", async () => {
  const fake = fakeHass();
  overlay.setHass(fake.hass);
  await settle();
  fake.push({ available: true, session: view(1) });
  const states: SessionState[] = [];
  overlay.subscribe((state) => states.push(state));
  overlay.open({ kind: "resume" });

  // The websocket drops: the integration can't say so, so the controller does, keeping the last
  // view so the flow can count down (its note shows, and Luk after 10 s).
  const before = Date.now();
  fake.fire("disconnected");
  expect(overlay.state()).toEqual({ available: false, session: view(1) });
  expect(states).toHaveLength(1);
  expect(theFlow().state).toEqual({ available: false, session: view(1) });
  expect(overlay.lostAt(overlay.state())).toBeGreaterThanOrEqual(before);

  // Ready again: the controller subscribes again, and the integration's first message says how it is.
  fake.fire("ready");
  await settle();
  expect(fake.subscribeMessage).toHaveBeenCalledTimes(2);
  expect(overlay.state().available).toBe(false);
  fake.push({ available: true, session: view(2) });
  expect(overlay.state()).toEqual({ available: true, session: view(2) });

  // A new connection: the old one's events count no more.
  const other = fakeHass();
  overlay.setHass(other.hass);
  await settle();
  other.push({ available: true, session: view(3) });
  fake.fire("disconnected");
  expect(overlay.state().available).toBe(true);
});
