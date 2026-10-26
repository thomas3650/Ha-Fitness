import en from "./i18n/en.json";

type Strings = { [key: string]: string | Strings };

/** Values for a text's `{name}` placeholders. A `count` also picks the plural form. */
export type Vars = Record<string, string | number>;

/** Find a dotted key such as "status.title" in the language file. */
function lookup(strings: Strings, key: string): string | undefined {
  let node: string | Strings | undefined = strings;
  for (const part of key.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** With a `count`, the plural form comes first: `key_one` for 1 and `key_other` for any other number. */
function find(key: string, count: number | undefined): string | undefined {
  if (count === undefined) return lookup(en, key);
  const form = count === 1 ? "one" : "other";
  return lookup(en, `${key}_${form}`) ?? lookup(en, `${key}_other`) ?? lookup(en, key);
}

/** Numbers read the English way, with a thousands separator: "1,324". */
const NUMBER = new Intl.NumberFormat("en");

/** Fill in the `{name}` placeholders, numbers formatted; one with no value stays as it is. */
function fill(text: string, vars: Vars): string {
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
    if (!Object.hasOwn(vars, name)) return placeholder;
    const value = vars[name];
    return typeof value === "number" ? NUMBER.format(value) : value;
  });
}

/**
 * The English text for `key` (the site is English only in v2, D62), else the key itself. `vars` fills its
 * placeholders, and `vars.count` picks the plural form.
 */
export function t(key: string, vars: Vars = {}): string {
  const count = typeof vars.count === "number" ? vars.count : undefined;
  return fill(find(key, count) ?? key, vars);
}
