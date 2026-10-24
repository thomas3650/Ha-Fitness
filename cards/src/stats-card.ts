import { LitElement, type PropertyValues, css, html, nothing } from "lit";

import { type Vars, localize } from "./i18n";
import { type LanguageConfig, type LanguageHass, cardLanguage } from "./language";
import { PERSON_COLORS } from "./people";
import { type Connection, WsSubscription } from "./today-data";

/** One person's numbers for a period (spec §3.4). */
export interface Totals {
  /** Days done plus extra sessions done. */
  done: number;
  /** Of `done`, how many were extra sessions. */
  extra: number;
  missed: number;
  skipped: number;
  /** Whole seconds. */
  time_trained: number;
}

/** One person's stats (spec §3.4). */
export interface PersonStats {
  id: number;
  name: string;
  person_entity_id: string;
  streak: number;
  all_time: Totals;
  this_month: Totals;
}

/** What the add-on computes (spec §3.4); the people are in their order. */
export interface Stats {
  counting_from: string | null;
  /** The add-on's current local month, `YYYY-MM`. */
  month: string;
  people: PersonStats[];
}

/** A message of `ha_fitness/stats/subscribe` (spec §5.1). */
export interface StatsMessage {
  available: boolean;
  /** The last stats known; null before the first. */
  stats: Stats | null;
}

/** The part of Home Assistant's `hass` object this card uses. */
interface Hass extends LanguageHass {
  connection?: Connection;
}

interface StatsCardConfig extends LanguageConfig {
  type: string;
}

declare global {
  interface HTMLElementTagNameMap {
    "ha-fitness-stats-card": StatsCard;
  }
}

const TAG = "ha-fitness-stats-card";

/**
 * The workout tab's stats (spec §5.2): one panel per person with the streak and a table of this
 * month and all time. While the add-on is unreachable it keeps the last numbers, with a note.
 */
export class StatsCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
    stats: { state: true },
    available: { state: true },
  };

  declare hass?: Hass;
  declare config?: StatsCardConfig;
  /** The last stats received, once there are any. */
  declare stats?: Stats;
  /** Whether the add-on is reachable: undefined before the first message. */
  declare available?: boolean;

  private readonly subscription = new WsSubscription<StatsMessage>("ha_fitness/stats/subscribe", (message) =>
    this.receive(message),
  );

  static override styles = css`
    :host {
      display: block;
    }
    .wrap {
      container-type: inline-size;
    }
    .panels {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: 1fr;
    }
    /* Below about 600 px of card width the panels stack. */
    @container (max-width: 600px) {
      .panels {
        grid-auto-flow: row;
      }
    }
    section {
      padding: 12px 16px 16px;
      min-width: 0;
    }
    h2 {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      font-size: 1.25em;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .dot {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--person-color);
      flex: none;
    }
    .streak {
      margin: 8px 0 12px;
      font-size: 2em;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th,
    td {
      padding: 4px 8px 4px 0;
      text-align: left;
      font-weight: normal;
      vertical-align: top;
    }
    thead th,
    tbody th {
      color: var(--secondary-text-color);
    }
    td {
      color: var(--primary-text-color);
    }
    .note {
      color: var(--secondary-text-color);
    }
    .muted {
      padding: 16px;
      color: var(--secondary-text-color);
    }
    .muted.small {
      padding: 12px 16px 0;
      font-size: 0.875em;
    }
  `;

  setConfig(config: StatsCardConfig): void {
    this.config = config;
  }

  /** The full width of a section, so two panels fit side by side; never under half of it. */
  getGridOptions(): { columns: "full"; min_columns: number } {
    return { columns: "full", min_columns: 6 };
  }

  getCardSize(): number {
    return this.panelsShown ? 4 : 1;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.subscription.connect(this.hass?.connection);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.subscription.disconnect();
    // Put back on the page, the card waits for fresh data from a new subscription.
    this.stats = undefined;
    this.available = undefined;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.isConnected && this.hass) {
      this.subscription.connect(this.hass.connection);
    }
  }

  /** A message, or null while the subscription is refused: then the add-on counts as unreachable. */
  private receive(message: StatsMessage | null): void {
    this.available = message?.available ?? false;
    if (message?.stats) this.stats = message.stats;
  }

  private t(key: string, vars?: Vars): string {
    return localize(cardLanguage(this.config, this.hass), key, vars);
  }

  private get panelsShown(): boolean {
    const stats = this.stats;
    return Boolean(stats && stats.people.length && stats.counting_from !== null);
  }

  /** Whole minutes, rounded down: "4 t 35 min", or minutes only under an hour. */
  private time(seconds: number): string {
    const total = Math.floor(seconds / 60);
    if (total < 60) return this.t("stats.minutes", { minutes: total });
    return this.t("stats.hours_minutes", { hours: Math.floor(total / 60), minutes: total % 60 });
  }

  private done(totals: Totals) {
    return html`${totals.done}${totals.extra > 0
      ? html` <span class="note">${this.t("stats.extra", { count: totals.extra })}</span>`
      : nothing}`;
  }

  private missed(totals: Totals) {
    return html`${totals.missed + totals.skipped}${totals.skipped > 0
      ? html` <span class="note">${this.t("stats.skipped", { count: totals.skipped })}</span>`
      : nothing}`;
  }

  private renderPanel(person: PersonStats, index: number) {
    const id = `person-${person.id}`;
    const color = PERSON_COLORS[index] ?? "var(--primary-color)";
    return html`
      <section aria-labelledby=${id} style="--person-color: ${color}">
        <h2 id=${id}><span class="dot" aria-hidden="true"></span>${person.name}</h2>
        <p class="streak">${this.t("stats.streak", { count: person.streak })}</p>
        <table>
          <thead>
            <tr>
              <td></td>
              <th scope="col">${this.t("stats.this_month")}</th>
              <th scope="col">${this.t("stats.all_time")}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">${this.t("stats.done")}</th>
              <td>${this.done(person.this_month)}</td>
              <td>${this.done(person.all_time)}</td>
            </tr>
            <tr>
              <th scope="row">${this.t("stats.missed")}</th>
              <td>${this.missed(person.this_month)}</td>
              <td>${this.missed(person.all_time)}</td>
            </tr>
            <tr>
              <th scope="row">${this.t("stats.time")}</th>
              <td>${this.time(person.this_month.time_trained)}</td>
              <td>${this.time(person.all_time.time_trained)}</td>
            </tr>
          </tbody>
        </table>
      </section>
    `;
  }

  /** The first line of spec §5.2 that applies, or the panels. */
  private renderBody() {
    const stats = this.stats;
    if (this.available === undefined) return nothing;
    const line = (key: string) => html`<div class="muted" role="status">${this.t(key)}</div>`;
    if (!stats) return line("stats.unreachable");
    // With older stats, the note says that what follows may be out of date, whichever line it is.
    const note = this.available
      ? nothing
      : html`<div class="muted small" role="status">${this.t("stats.unreachable")}</div>`;
    if (!stats.people.length) return html`${note}${line("stats.no_people")}`;
    if (stats.counting_from === null) return html`${note}${line("stats.not_started")}`;
    return html`
      ${note}
      <div class="panels">${stats.people.map((person, index) => this.renderPanel(person, index))}</div>
    `;
  }

  protected override render() {
    return html`<ha-card><div class="wrap">${this.renderBody()}</div></ha-card>`;
  }
}

/** Define the card and offer it in the card picker; `index.ts` calls this once HA has booted. */
export function registerStatsCard(): void {
  if (customElements.get(TAG)) return;
  customElements.define(TAG, StatsCard);
  window.customCards = window.customCards ?? [];
  window.customCards.push({
    type: TAG,
    // There is no `hass` at module load, so the picker shows the English texts.
    name: localize("en", "picker_stats.name"),
    description: localize("en", "picker_stats.description"),
  });
}
