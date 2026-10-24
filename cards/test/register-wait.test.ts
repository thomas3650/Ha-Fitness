import { afterEach, expect, test, vi } from "vitest";

// HA's frontend replaces `window.customElements` with a scoped registry polyfill once it boots.
// The cards must land in that registry, not in the one the page started with.
const TAGS = [
  "ha-fitness-today-card",
  "ha-fitness-workout-card",
  "ha-fitness-stats-card",
  "ha-fitness-workout-flow",
];

/** A stand-in for HA's polyfill: a registry of its own that knows only what is defined in it. */
function polyfillRegistry() {
  const defined = new Map<string, CustomElementConstructor>();
  return {
    define: (name: string, constructor: CustomElementConstructor) => void defined.set(name, constructor),
    get: (name: string) => defined.get(name),
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("on an HA page the cards wait for HA's frontend, then register in its registry", async () => {
  vi.useFakeTimers();
  // HA's index.html has <home-assistant> in the body from the start; it is defined once HA boots.
  document.body.append(document.createElement("home-assistant"));

  await import("../src/index");
  for (const tag of TAGS) expect(customElements.get(tag)).toBeUndefined();
  await vi.advanceTimersByTimeAsync(5_000);
  for (const tag of TAGS) expect(customElements.get(tag)).toBeUndefined();

  // HA boots: its polyfill takes over `customElements`, with <home-assistant> defined in it.
  const registry = polyfillRegistry();
  registry.define("home-assistant", class extends HTMLElement {});
  vi.stubGlobal("customElements", registry);
  await vi.advanceTimersByTimeAsync(50);
  for (const tag of TAGS) expect(registry.get(tag), tag).toBeDefined();
  expect(window.customCards?.map((card) => card.type)).toEqual([
    "ha-fitness-today-card",
    "ha-fitness-workout-card",
    "ha-fitness-stats-card",
  ]);
});
