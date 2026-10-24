import { expect, test } from "vitest";

test("on a page without <home-assistant> the cards register at once", async () => {
  await import("../src/index");
  for (const tag of [
    "ha-fitness-today-card",
    "ha-fitness-workout-card",
    "ha-fitness-stats-card",
    "ha-fitness-workout-flow",
  ]) {
    expect(customElements.get(tag), tag).toBeDefined();
  }
});
