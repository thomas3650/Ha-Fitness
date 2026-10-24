/** The part of a card's config that sets its language. */
export interface LanguageConfig {
  language?: string;
}

/** The part of Home Assistant's `hass` object that holds the user's language. */
export interface LanguageHass {
  locale?: { language?: string };
}

/**
 * The language a card shows its texts in: its `language` option if set,
 * else the user's language from `hass.locale.language`, else English.
 */
export function cardLanguage(config?: LanguageConfig, hass?: LanguageHass): string {
  return config?.language || hass?.locale?.language || "en";
}
