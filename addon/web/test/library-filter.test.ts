import { expect, test } from "vitest";

import type { ExerciseSummary } from "../src/api";
import {
  atHome,
  BAND,
  countMine,
  equipmentValues,
  homeKinds,
  household,
  matchesEquipment,
  type EquipmentChoice,
} from "../src/library-filter";

function exercise(id: string, equipment: string | null, custom = false): ExerciseSummary {
  return { id, name: `exercise ${id}`, equipment, body_part: "chest", target: "pectorals", custom };
}

const MINE: EquipmentChoice = { mode: "mine" };
const ALL: EquipmentChoice = { mode: "all" };

function picked(...values: string[]): EquipmentChoice {
  return { mode: "picked", values };
}

const HOME = household({ equipment: ["dumbbell"], favourite_playlists: [], default_speaker: null });

test("the household is the setup's equipment plus body weight; without a setup it is body weight only", () => {
  expect([...HOME].sort()).toEqual(["body weight", "dumbbell"]);
  expect([...household(null)]).toEqual(["body weight"]);
  expect([...household({ equipment: [], favourite_playlists: [], default_speaker: null })]).toEqual(["body weight"]);
});

test("a custom exercise shows under My equipment whatever its equipment", () => {
  expect(matchesEquipment(exercise("c1", "barbell", true), MINE, HOME)).toBe(true);
  expect(matchesEquipment(exercise("c2", null, true), MINE, HOME)).toBe(true);
  expect(matchesEquipment(exercise("c3", "barbell", true), MINE, household(null))).toBe(true);
});

test("a custom exercise shows under picked kinds only when its equipment matches", () => {
  expect(matchesEquipment(exercise("c1", "barbell", true), picked("barbell"), HOME)).toBe(true);
  expect(matchesEquipment(exercise("c1", "barbell", true), picked("dumbbell"), HOME)).toBe(false);
  expect(matchesEquipment(exercise("c2", null, true), picked("dumbbell"), HOME)).toBe(false);
});

test("All equipment shows every exercise, custom or not, with or without equipment", () => {
  expect(matchesEquipment(exercise("c1", "barbell", true), ALL, HOME)).toBe(true);
  expect(matchesEquipment(exercise("1", "barbell"), ALL, HOME)).toBe(true);
  expect(matchesEquipment(exercise("2", null), ALL, HOME)).toBe(true);
});

test("My equipment shows the household's equipment and body weight, not a library exercise without equipment", () => {
  expect(matchesEquipment(exercise("1", "dumbbell"), MINE, HOME)).toBe(true);
  expect(matchesEquipment(exercise("2", "body weight"), MINE, HOME)).toBe(true);
  expect(matchesEquipment(exercise("3", "barbell"), MINE, HOME)).toBe(false);
  expect(matchesEquipment(exercise("4", null), MINE, HOME)).toBe(false);
  expect(matchesEquipment(exercise("2", "body weight"), MINE, household(null))).toBe(true);
  expect(matchesEquipment(exercise("1", "dumbbell"), MINE, household(null))).toBe(false);
});

test("picked kinds show either of them", () => {
  expect(matchesEquipment(exercise("1", "dumbbell"), picked("barbell", "dumbbell"), HOME)).toBe(true);
  expect(matchesEquipment(exercise("2", "barbell"), picked("barbell", "dumbbell"), HOME)).toBe(true);
  expect(matchesEquipment(exercise("3", "cable"), picked("barbell", "dumbbell"), HOME)).toBe(false);
  expect(matchesEquipment(exercise("4", null), picked("barbell"), HOME)).toBe(false);
});

test("the equipment values are every kind of the library and the custom exercises, sorted, band folded", () => {
  const exercises = [
    exercise("1", "kettlebell"),
    exercise("2", "resistance band"),
    exercise("3", "band"),
    exercise("4", null),
    exercise("5", "body weight"),
    exercise("c1", "sofa", true),
    exercise("6", "kettlebell"),
  ];
  expect(equipmentValues(exercises)).toEqual(["band", "body weight", "kettlebell", "sofa"]);
  expect(equipmentValues([exercise("2", "resistance band")])).toEqual([BAND]);
});

test("picking band matches both band names", () => {
  expect(matchesEquipment(exercise("1", "band"), picked(BAND), HOME)).toBe(true);
  expect(matchesEquipment(exercise("2", "resistance band"), picked(BAND), HOME)).toBe(true);
  expect(matchesEquipment(exercise("3", "dumbbell"), picked(BAND), HOME)).toBe(false);
});

test("band is at home when either name is in the setup, and My equipment then shows both names", () => {
  const resistance = household({ equipment: ["resistance band"], favourite_playlists: [], default_speaker: null });
  const plain = household({ equipment: ["band"], favourite_playlists: [], default_speaker: null });
  expect(atHome(BAND, resistance)).toBe(true);
  expect(atHome(BAND, plain)).toBe(true);
  expect(atHome(BAND, HOME)).toBe(false);
  for (const home of [resistance, plain]) {
    expect(matchesEquipment(exercise("1", "band"), MINE, home)).toBe(true);
    expect(matchesEquipment(exercise("2", "resistance band"), MINE, home)).toBe(true);
  }
  expect(matchesEquipment(exercise("1", "band"), MINE, HOME)).toBe(false);
});

test("body weight is always at home; other kinds only when the setup has them", () => {
  expect(atHome("body weight", new Set())).toBe(true);
  expect(atHome("body weight", household(null))).toBe(true);
  expect(atHome("dumbbell", HOME)).toBe(true);
  expect(atHome("barbell", HOME)).toBe(false);
  expect(atHome("dumbbell", household(null))).toBe(false);
});

test("the My equipment line's kinds: body weight first, then the rest sorted, band folded as in the values", () => {
  expect(homeKinds(["kettlebell", "body weight", "resistance band", "band", "dumbbell"])).toEqual([
    "body weight",
    BAND,
    "dumbbell",
    "kettlebell",
  ]);
  expect(homeKinds(["resistance band"])).toEqual(["body weight", BAND]);
  expect(homeKinds(household(null))).toEqual(["body weight"]);
});

test("My equipment's count is how many exercises it shows: the household's kinds and every custom one", () => {
  const exercises = [
    exercise("1", "body weight"),
    exercise("2", "dumbbell"),
    exercise("3", "barbell"),
    exercise("4", null),
    exercise("c1", "barbell", true),
    exercise("c2", null, true),
  ];
  expect(countMine(exercises, HOME)).toBe(4);
  expect(countMine(exercises, HOME)).toBe(exercises.filter((one) => matchesEquipment(one, MINE, HOME)).length);
  expect(countMine(exercises, household(null))).toBe(3);
  expect(countMine([], HOME)).toBe(0);
});
