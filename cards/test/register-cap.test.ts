import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.useRealTimers();
});

test("if HA's frontend never boots, the cards register after about 15 s anyway", async () => {
  vi.useFakeTimers();
  document.body.append(document.createElement("home-assistant"));

  await import("../src/index");
  await vi.advanceTimersByTimeAsync(14_900);
  expect(customElements.get("ha-fitness-today-card")).toBeUndefined();
  await vi.advanceTimersByTimeAsync(200);
  for (const tag of ["ha-fitness-today-card", "ha-fitness-workout-card", "ha-fitness-workout-flow"]) {
    expect(customElements.get(tag), tag).toBeDefined();
  }
});
