import { getByRole, queryByRole } from "@testing-library/dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import "../src/index";
import type { OverlayMode, SessionState, SessionView } from "../src/overlay";

// A browser with no Web Audio at all: this file's page has no AudioContext.
vi.stubGlobal("AudioContext", undefined);
vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:image");

interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: OverlayMode;
  onClose?: () => void;
  updateComplete: Promise<boolean>;
}

const thomas = { id: 1, name: "Thomas" };

function fakeHass() {
  const callWS = vi.fn((message: { type: string }): Promise<unknown> =>
    message.type === "ha_fitness/people" ? Promise.resolve([thomas]) : new Promise(() => undefined),
  );
  const fetchWithAuth = vi.fn(async () => new Response(null, { status: 404 }));
  return { locale: { language: "da" }, callWS, fetchWithAuth };
}

/** A running one-person session in a 45 s work phase, as spec §3.5 has it. */
function view(): SessionView {
  return {
    id: 7,
    revision: 10,
    status: "running",
    counted: false,
    program_name: "Onsdag",
    training_day_id: 12,
    participants: [thomas],
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
      {
        current: { number: 1, exercise_id: "0001", name: "Push-up" },
        next: { number: 2, exercise_id: "0002", name: "Squat" },
      },
    ],
    totals: { planned: 1740, rounds: 5 },
    started_at: "2026-10-24T07:54:00.000Z",
    ended_at: null,
    rounds_completed: 1,
    time_trained: 360,
    server_time: "2026-10-24T08:00:00.000Z",
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00.000Z"));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

test("without Web Audio there is no Tryk for lyd", async () => {
  const flow = document.createElement("ha-fitness-workout-flow") as FlowElement;
  document.body.append(flow);
  flow.hass = fakeHass();
  flow.state = { available: true, session: view() };
  flow.mode = { kind: "resume" };
  flow.onClose = vi.fn();
  await vi.advanceTimersByTimeAsync(0);
  await flow.updateComplete;

  const root = flow.shadowRoot as unknown as HTMLElement;
  // The timer shows, with nothing to tap for sound: no tap could ever bring it.
  expect(getByRole(root, "button", { name: "Pause" })).toBeTruthy();
  expect(queryByRole(root, "button", { name: "Tryk for lyd" })).toBeNull();
});
