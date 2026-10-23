import da from "./da.json";
import en from "./en.json";

type Strings = { [key: string]: string | Strings };

const languages: Record<string, Strings> = { da, en };

/** Find a dotted key such as "today.title" in a language file. */
function lookup(strings: Strings | undefined, key: string): string | undefined {
  let node: string | Strings | undefined = strings;
  for (const part of key.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/**
 * The text for `key` in the user's language ("da" and "da-DK" both mean Danish),
 * falling back to English, then to the key itself.
 */
export function localize(language: string | undefined, key: string): string {
  const base = language?.split("-")[0].toLowerCase();
  return (
    lookup(base ? languages[base] : undefined, key) ?? lookup(languages.en, key) ?? key
  );
}
