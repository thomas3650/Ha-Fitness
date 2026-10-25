import { LitElement, css, html, nothing } from "lit";

import { localize } from "./i18n";
import type { LanguageHass } from "./language";

/** The languages the cards ship, as option values; their names are never translated. */
const LANGUAGES = ["en", "da"];

/**
 * The visual editor of an HA Fitness card (card editors spec): one field, the card's language.
 * Home Assistant sets `hass`, calls `setConfig` with the card's config, and listens for
 * `config-changed`. The editor's own texts follow the user's language, not the card's. It fires
 * only when the user changes the field, and keeps every other key of the config as it is.
 */
export class CardEditor extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
  };

  declare hass?: LanguageHass;
  declare config?: Record<string, unknown>;

  static override styles = css`
    :host {
      display: block;
    }
    label {
      display: block;
      margin-bottom: 4px;
      color: var(--secondary-text-color);
      font-size: 0.875rem;
    }
    select {
      box-sizing: border-box;
      width: 100%;
      height: 56px;
      padding: 0 12px;
      border: 1px solid var(--divider-color);
      border-radius: 4px;
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font: inherit;
      font-size: 1rem;
    }
    select:focus {
      outline: none;
      border-color: var(--primary-color);
      box-shadow: inset 0 0 0 1px var(--primary-color);
    }
  `;

  setConfig(config: Record<string, unknown>): void {
    this.config = config;
  }

  /** The config's language, or "" when it follows the user's. */
  private get current(): string {
    const language = this.config?.language;
    return typeof language === "string" ? language : "";
  }

  private t(key: string): string {
    return localize(this.hass?.locale?.language, key);
  }

  private onChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    const config: Record<string, unknown> = { ...this.config };
    if (value) config.language = value;
    else delete config.language;
    this.config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  protected override render() {
    // Until Home Assistant has given a config, a change would send one without `type`.
    if (!this.config) return nothing;
    const current = this.current;
    return html`
      <label for="language">${this.t("editor.language")}</label>
      <select id="language" @change=${(event: Event) => this.onChange(event)}>
        <option value="">${this.t("editor.language_default")}</option>
        ${LANGUAGES.map(
          (language) => html`<option value=${language}>${this.t(`editor.language_${language}`)}</option>`,
        )}
        ${current && !LANGUAGES.includes(current) ? html`<option value=${current}>${current}</option>` : nothing}
      </select>
    `;
  }

  // The selection is set here, once the options exist: a `.value` binding on the select is
  // committed before them, and a `selected` attribute stops moving it once the user has chosen.
  protected override updated(): void {
    const select = this.renderRoot.querySelector("select");
    // Only when it differs, so Home Assistant's frequent `hass` updates leave an open dropdown alone.
    if (select && select.value !== this.current) select.value = this.current;
  }
}

/** Define an editor under `tag`; each card has its own tag, so each gets a fresh subclass. */
export function registerCardEditor(tag: string): void {
  if (customElements.get(tag)) return;
  customElements.define(tag, class extends CardEditor {});
}
