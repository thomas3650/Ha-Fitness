import type { ExerciseSummary, Setup } from "./api";

/** Body weight needs no equipment, so the household always has it (website spec §2.3.2). */
export const BODY_WEIGHT = "body weight";

/** The one value that stands for both names the dataset gives a band, as on Setup (spec §2.3.1). */
export const BAND = "band";

/** The names `BAND` stands for. */
export const BAND_NAMES: readonly string[] = ["band", "resistance band"];

/**
 * The equipment filter's choice (D66): the household's equipment (custom exercises always show), no equipment filter,
 * or picked kinds (either of them; custom exercises only when they match).
 */
export type EquipmentChoice = { mode: "mine" } | { mode: "all" } | { mode: "picked"; values: string[] };

/** An equipment name as the filter shows it: a band's two names are one. */
function fold(equipment: string): string {
  return BAND_NAMES.includes(equipment) ? BAND : equipment;
}

/** The household's equipment: the setup's plus body weight; without a setup, body weight only. */
export function household(setup: Setup | null): Set<string> {
  return new Set([BODY_WEIGHT, ...(setup?.equipment ?? [])]);
}

/** Whether the household has a kind: body weight always; "band" when the setup has either of its names. */
export function atHome(value: string, home: ReadonlySet<string>): boolean {
  const kind = fold(value);
  if (kind === BODY_WEIGHT) return true;
  return kind === BAND ? BAND_NAMES.some((name) => home.has(name)) : home.has(kind);
}

/** Every equipment value of the exercises (library and custom), sorted, a band's two names as one. */
export function equipmentValues(exercises: ExerciseSummary[]): string[] {
  const values = exercises.map((exercise) => exercise.equipment).filter((value): value is string => !!value);
  return [...new Set(values.map(fold))].sort();
}

/** The kinds the My equipment line lists: body weight first, then the household's others, sorted, band folded. */
export function homeKinds(home: Iterable<string>): string[] {
  const others = new Set([...home].map(fold));
  others.delete(BODY_WEIGHT);
  return [BODY_WEIGHT, ...[...others].sort()];
}

/** Whether the equipment filter keeps an exercise (spec §2.3.1). */
export function matchesEquipment(
  exercise: ExerciseSummary,
  choice: EquipmentChoice,
  home: ReadonlySet<string>,
): boolean {
  const equipment = exercise.equipment;
  switch (choice.mode) {
    case "all":
      return true;
    case "mine":
      return exercise.custom || (equipment !== null && atHome(equipment, home));
    case "picked":
      return equipment !== null && choice.values.includes(fold(equipment));
  }
}

/** How many of the exercises My equipment shows: its line's count, ignoring the search and the other filters. */
export function countMine(exercises: ExerciseSummary[], home: ReadonlySet<string>): number {
  return exercises.filter((exercise) => matchesEquipment(exercise, { mode: "mine" }, home)).length;
}

/**
 * The exercises whose name has every word of the search, those that start with the whole search first; the order
 * is kept otherwise.
 */
export function searchByName(exercises: ExerciseSummary[], search: string): ExerciseSummary[] {
  const needle = search.trim().toLowerCase();
  const words = needle.split(/\s+/).filter(Boolean);
  const kept = exercises.filter((exercise) => words.every((word) => exercise.name.toLowerCase().includes(word)));
  const first = kept.filter((exercise) => exercise.name.toLowerCase().startsWith(needle));
  const rest = kept.filter((exercise) => !exercise.name.toLowerCase().startsWith(needle));
  return [...first, ...rest];
}

export type Facet = "equipment" | "body_part" | "target";

/** The values one facet has among the exercises, sorted, as the dataset names them. */
export function facetValues(exercises: ExerciseSummary[], facet: Facet): string[] {
  return [...new Set(exercises.map((exercise) => exercise[facet]).filter((value): value is string => !!value))].sort();
}
