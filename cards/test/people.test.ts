import { expect, test } from "vitest";

import { PERSON_COLORS, initials, personColor, personTextColor } from "../src/people";

test("each name gets its first letter when no other name shares it", () => {
  expect(initials(["Thomas", "Elin"])).toEqual(["T", "E"]);
});

test("names that share a first letter get two letters", () => {
  expect(initials(["Thomas", "Tina"])).toEqual(["Th", "Ti"]);
});

test("names whose two letters still clash get the shortest unique prefix", () => {
  expect(initials(["Thomas", "Thea"])).toEqual(["Tho", "The"]);
});

test("only the names that share a first letter get more than one", () => {
  expect(initials(["Thomas", "Thea", "Elin"])).toEqual(["Tho", "The", "E"]);
});

test("one name gets its first letter, upper-cased", () => {
  expect(initials(["elin"])).toEqual(["E"]);
});

test("the same name twice is capped at the whole name", () => {
  expect(initials(["Ida", "Ida"])).toEqual(["Ida", "Ida"]);
});

test("the people's colours go in people order, then the theme's primary colour", () => {
  expect(PERSON_COLORS).toEqual(["#B18CFF", "#3DD6C6"]);
  expect(personColor(0)).toBe("#B18CFF");
  expect(personColor(1)).toBe("#3DD6C6");
  expect(personColor(2)).toBe("var(--primary-color)");
  expect(personColor(-1)).toBe("var(--primary-color)");
});

test("a number on a person's colour is dark on the fixed colours and the theme's on the primary colour", () => {
  expect(personTextColor(personColor(0))).toBe("#1c1c1c");
  expect(personTextColor(personColor(1))).toBe("#1c1c1c");
  expect(personTextColor(personColor(2))).toBe("var(--text-primary-color)");
});
