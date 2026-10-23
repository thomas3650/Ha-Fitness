import { expect, test } from "vitest";

import da from "../src/i18n/da.json";
import en from "../src/i18n/en.json";
import { localize } from "../src/i18n";

/** Every dotted key path to a string in a language file, with its text, sorted by key. */
function entriesOf(tree: object, prefix = ""): [string, string][] {
  return Object.entries(tree)
    .flatMap(([key, value]): [string, string][] =>
      typeof value === "object" && value !== null
        ? entriesOf(value as object, `${prefix}${key}.`)
        : [[`${prefix}${key}`, String(value)]],
    )
    .sort(([a], [b]) => a.localeCompare(b));
}

function keysOf(tree: object): string[] {
  return entriesOf(tree).map(([key]) => key);
}

/** The `{name}` placeholders of a text, sorted. */
function placeholdersOf(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
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

test("each text has the same placeholders in both languages", () => {
  const danish = new Map(entriesOf(da));
  for (const [key, text] of entriesOf(en)) {
    expect(placeholdersOf(danish.get(key) ?? ""), key).toEqual(placeholdersOf(text));
  }
});

test("every plural has an _other form", () => {
  const keys = keysOf(en);
  for (const key of keys.filter((key) => key.endsWith("_one"))) {
    expect(keys).toContain(key.replace(/_one$/, "_other"));
  }
});

test("the plural choice: one for 1, other for the rest", () => {
  expect(localize("da", "today.stations", { count: 1 })).toBe("1 øvelse");
  expect(localize("da", "today.stations", { count: 5 })).toBe("5 øvelser");
  expect(localize("da", "today.rounds", { count: 1 })).toBe("1 runde");
  expect(localize("da", "today.rounds", { count: 3 })).toBe("3 runder");
  expect(localize("en", "today.stations", { count: 1 })).toBe("1 exercise");
  expect(localize("en", "today.stations", { count: 0 })).toBe("0 exercises");
  expect(localize("en", "today.rounds", { count: 2 })).toBe("2 rounds");
});

test("the English fallback picks the English plural", () => {
  expect(localize("fr", "today.stations", { count: 0 })).toBe("0 exercises");
  expect(localize("fr", "today.stations", { count: 1 })).toBe("1 exercise");
});

test("the day's line, due and late", () => {
  const line = localize("da", "today.summary", {
    stations: localize("da", "today.stations", { count: 5 }),
    rounds: localize("da", "today.rounds", { count: 5 }),
    minutes: localize("da", "today.minutes", { count: 29 }),
  });
  expect(line).toBe("5 øvelser · 5 runder · ca. 29 min");
  expect(
    localize("da", "today.late", { weekday: localize("da", "weekday.wednesday"), summary: line }),
  ).toBe("Forfalden · onsdag · 5 øvelser · 5 runder · ca. 29 min");
});

test("the card's fixed texts in Danish", () => {
  expect(localize("da", "today.skip")).toBe("Spring over");
  expect(localize("da", "today.skip_confirm")).toBe("Spring over?");
  expect(localize("da", "today.yes")).toBe("Ja");
  expect(localize("da", "today.no")).toBe("Nej");
  expect(localize("da", "today.nothing_open")).toBe("Ingen træning i dag");
  expect(localize("da", "today.unreachable")).toBe("HA Fitness kan ikke nås");
});

test("the weekdays, Monday to Sunday", () => {
  const days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  expect(days.map((day) => localize("da", `weekday.${day}`))).toEqual([
    "mandag",
    "tirsdag",
    "onsdag",
    "torsdag",
    "fredag",
    "lørdag",
    "søndag",
  ]);
  expect(days.map((day) => localize("en", `weekday.${day}`))).toEqual([
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
  ]);
});

test("an error text for each service error, and a general one", () => {
  for (const key of ["not_found", "not_open", "unavailable", "general"]) {
    expect(localize("da", `error.${key}`)).not.toBe(`error.${key}`);
    expect(localize("en", `error.${key}`)).not.toBe(`error.${key}`);
  }
});

test("a placeholder with no value stays as it is", () => {
  expect(localize("en", "today.summary", { stations: "5 exercises" })).toBe(
    "5 exercises · {rounds} · {minutes}",
  );
});
