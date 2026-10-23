import da from "./da.json";
import en from "./en.json";

type Strings = { [key: string]: string | Strings };

/** Values for a text's `{name}` placeholders. A `count` also picks the plural form. */
export type Vars = Record<string, string | number>;

const languages: Record<string, Strings> = { da, en };

/** Find a dotted key such as "today.skip" in a language file. */
function lookup(strings: Strings | undefined, key: string): string | undefined {
  let node: string | Strings | undefined = strings;
  for (const part of key.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/**
 * The text for `key` in one language file. With a `count`, the plural form comes first:
 * `key_one` for 1 and `key_other` for any other number. That rule holds in Danish and English,
 * the two languages that ship.
 */
function find(strings: Strings | undefined, key: string, count: number | undefined): string | undefined {
  if (count === undefined) return lookup(strings, key);
  const form = count === 1 ? "one" : "other";
  return lookup(strings, `${key}_${form}`) ?? lookup(strings, `${key}_other`) ?? lookup(strings, key);
}

/** Fill in the `{name}` placeholders; one with no value stays as it is. */
function fill(text: string, vars: Vars): string {
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : placeholder,
  );
}

/**
 * The text for `key` in the user's language ("da" and "da-DK" both mean Danish),
 * falling back to English, then to the key itself. `vars` fills its placeholders,
 * and `vars.count` picks the plural form.
 */
export function localize(language: string | undefined, key: string, vars: Vars = {}): string {
  const base = language?.split("-")[0].toLowerCase();
  const count = typeof vars.count === "number" ? vars.count : undefined;
  const text =
    find(base ? languages[base] : undefined, key, count) ?? find(languages.en, key, count) ?? key;
  return fill(text, vars);
}
