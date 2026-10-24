/** The people's colours, by people order (design §3.4). Used for borders and badges, never for text. */
export const PERSON_COLORS = ["#B18CFF", "#3DD6C6"];

/** The colour of the person at `index` in people order; from the third on (or none), the theme's. */
export function personColor(index: number): string {
  return PERSON_COLORS[index] ?? "var(--primary-color)";
}

/**
 * Each name's initials: its first letter, upper-cased. A name whose first letter another name shares
 * gets two letters; if those still clash, the shortest prefix no other name shares, up to the whole
 * name ("Thomas", "Thea" → "Tho", "The").
 */
export function initials(names: string[]): string[] {
  const lower = names.map((name) => name.toLowerCase());
  return names.map((name, index) => {
    const own = lower[index];
    const others = lower.filter((other, at) => at !== index && other[0] === own[0]);
    let length = others.length > 0 ? 2 : 1;
    while (length < name.length && others.some((other) => other.slice(0, length) === own.slice(0, length))) {
      length++;
    }
    const prefix = name.slice(0, length);
    return prefix.charAt(0).toUpperCase() + prefix.slice(1);
  });
}
