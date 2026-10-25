/** The part of a card's config that sets its language. */
export interface LanguageConfig {
  language?: string;
}

/** The part of Home Assistant's `hass` object that holds the user's language. */
export interface LanguageHass {
  locale?: { language?: string };
}

/**
 * The language a card shows its texts in: its `language` option if it is a non-empty string,
 * else the user's language from `hass.locale.language`, else English. YAML can give the option
 * any type (a number, a list); such a value is ignored, so the card still renders.
 */
export function cardLanguage(config?: LanguageConfig, hass?: LanguageHass): string {
  const language: unknown = config?.language;
  return (typeof language === "string" && language) || hass?.locale?.language || "en";
}
