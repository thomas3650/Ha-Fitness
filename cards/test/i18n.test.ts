import { expect, test } from "vitest";

import da from "../src/i18n/da.json";
import en from "../src/i18n/en.json";
import { localize } from "../src/i18n";

/** Every dotted key path to a string in a language file, sorted. */
function keysOf(tree: object, prefix = ""): string[] {
  return Object.entries(tree)
    .flatMap(([key, value]) =>
      typeof value === "object" && value !== null
        ? keysOf(value as object, `${prefix}${key}.`)
        : [`${prefix}${key}`],
    )
    .sort();
}

test("Danish for da and da-DK", () => {
  expect(localize("da", "today.title")).toBe("Træning i dag");
  expect(localize("da-DK", "today.title")).toBe("Træning i dag");
});

test("falls back to English, then to the key", () => {
  expect(localize("fr", "today.title")).toBe("Today's training");
  expect(localize(undefined, "today.title")).toBe("Today's training");
  expect(localize("da", "no.such.key")).toBe("no.such.key");
});

test("every English key exists in Danish", () => {
  expect(keysOf(da)).toEqual(keysOf(en));
});
