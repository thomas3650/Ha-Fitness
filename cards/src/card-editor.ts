import { LitElement, css, html, nothing } from "lit";

import { localize } from "./i18n";
import type { LanguageHass } from "./language";

/** The languages the cards ship, as option values; their names are never translated. */
const LANGUAGES = ["en", "da"];

/** The option value that stands for a value the field can't show as itself; choosing it keeps that value. */
const OTHER = "\u0000other";

/** The today card's `days_ahead` choices (today-ahead spec §2.3.1); 0 is the default. */
const DAYS_AHEAD = [0, 1, 2, 3, 4, 5, 6];

/** What a card's editor shows besides the language. */
export interface EditorOptions {
  /** The today card's "Days ahead" field. */
  daysAhead?: boolean;
}

/**
 * The visual editor of an HA Fitness card (card editors spec): the card's language, and for the
 * today card how many days ahead it shows (today-ahead spec §2.3.1). Home Assistant sets `hass`,
 * calls `setConfig` with the card's config, and listens for `config-changed`. The editor's own
 * texts follow the user's language, not the card's. It fires only when the user changes a field,
 * leaves a field's key out at its default, and keeps every other key of the config as it is.
 */
export class CardEditor extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
  };

  declare hass?: LanguageHass;
  declare config?: Record<string, unknown>;

  /** Which fields show besides the language; `registerCardEditor` sets them per card. */
  protected readonly options: EditorOptions = {};

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
    select + label {
      margin-top: 16px;
    }
  `;

  setConfig(config: Record<string, unknown>): void {
    this.config = config;
  }

  /** The language field's value: the config's language, OTHER for one that isn't a string, or "" when unset. */
  private get language(): string {
    const language = this.config?.language;
    if (typeof language === "string") return language;
    return language === undefined ? "" : OTHER;
  }

  /** The days ahead field's value: the config's number, "0" when unset, or OTHER for anything else. */
  private get daysAhead(): string {
    const days = this.config?.days_ahead;
    if (days === undefined) return "0";
    return typeof days === "number" && DAYS_AHEAD.includes(days) ? String(days) : OTHER;
  }

  private t(key: string): string {
    return localize(this.hass?.locale?.language, key);
  }

  private onLanguage(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.change("language", value || undefined, value);
  }

  private onDaysAhead(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.change("days_ahead", value === "0" ? undefined : Number(value), value);
  }

  /** Set `key` to `next`, or remove it for undefined, and tell Home Assistant. */
  private change(key: string, next: unknown, value: string): void {
    // The odd value chosen again: leave it as it is, rather than send it changed.
    if (value === OTHER) return;
    const config: Record<string, unknown> = { ...this.config };
    if (next === undefined) delete config[key];
    else config[key] = next;
    this.config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  protected override render() {
    // Until Home Assistant has given a config, a change would send one without `type`.
    if (!this.config) return nothing;
    const current = this.language;
    return html`
      <label for="language">${this.t("editor.language")}</label>
      <select id="language" @change=${(event: Event) => this.onLanguage(event)}>
        <option value="">${this.t("editor.language_default")}</option>
        ${LANGUAGES.map(
          (language) => html`<option value=${language}>${this.t(`editor.language_${language}`)}</option>`,
        )}
        ${current && current !== OTHER && !LANGUAGES.includes(current)
          ? html`<option value=${current}>${current}</option>`
          : nothing}
        ${current === OTHER ? html`<option value=${OTHER}>${String(this.config.language)}</option>` : nothing}
      </select>
      ${this.options.daysAhead ? this.renderDaysAhead() : nothing}
    `;
  }

  private renderDaysAhead() {
    return html`
      <label for="days_ahead">${this.t("editor.days_ahead")}</label>
      <select id="days_ahead" @change=${(event: Event) => this.onDaysAhead(event)}>
        ${DAYS_AHEAD.map((days) => html`<option value=${String(days)}>${days}</option>`)}
        ${this.daysAhead === OTHER
          ? html`<option value=${OTHER}>${String(this.config?.days_ahead)}</option>`
          : nothing}
      </select>
    `;
  }

  // The selections are set here, once the options exist: a `.value` binding on a select is
  // committed before them, and a `selected` attribute stops moving it once the user has chosen.
  protected override updated(): void {
    this.select("language", this.language);
    if (this.options.daysAhead) this.select("days_ahead", this.daysAhead);
  }

  private select(id: string, value: string): void {
    const select = this.renderRoot.querySelector<HTMLSelectElement>(`#${id}`);
    // Only when it differs, so Home Assistant's frequent `hass` updates leave an open dropdown alone.
    if (select && select.value !== value) select.value = value;
  }
}

/**
 * Define an editor under `tag` with the fields `options` asks for. Each card has its own tag, so
 * each gets a fresh subclass; only the today card's asks for `daysAhead`.
 */
export function registerCardEditor(tag: string, options: EditorOptions = {}): void {
  if (customElements.get(tag)) return;
  customElements.define(
    tag,
    class extends CardEditor {
      protected override readonly options = options;
    },
  );
}
