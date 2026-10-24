import { LitElement, type PropertyValues, type TemplateResult, css, html, nothing, svg } from "lit";

import { unlockAudio } from "./audio";
import { type Vars, WEEKDAYS, localize } from "./i18n";
import { iconButton } from "./icon-button";
import { type LanguageConfig, type LanguageHass, cardLanguage } from "./language";
import * as overlay from "./overlay";
import { type SessionView, isActive } from "./overlay";
import { initials, personColor } from "./people";
import type { PersonStats, StatsMessage } from "./stats-card";
import { type Connection, type OpenDay, type Today, TodaySubscription, WsSubscription } from "./today-data";

/** The part of Home Assistant's `hass` object this card uses. */
interface Hass extends LanguageHass {
  connection?: Connection;
  callService(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
    target?: unknown,
    notifyOnError?: boolean,
    returnResponse?: boolean,
  ): Promise<unknown>;
}

interface TodayCardConfig extends LanguageConfig {
  type: string;
}

interface CustomCardEntry {
  type: string;
  name: string;
  description?: string;
  preview?: boolean;
}

declare global {
  interface Window {
    customCards?: CustomCardEntry[];
  }
  interface HTMLElementTagNameMap {
    "ha-fitness-today-card": TodayCard;
  }
}

/** A row asking "Spring over?". */
interface Confirming {
  /** Ja ignores taps until it has been shown for a moment, so a wake tap can't land on it. */
  armed: boolean;
  /** The skip service is running. */
  busy: boolean;
  timers: ReturnType<typeof setTimeout>[];
}

const TAG = "ha-fitness-today-card";
const ARM_MS = 500;
const CONFIRM_MS = 10_000;
const ERROR_MS = 5_000;
/** The week ring's size and stroke, in px. */
const WEEK_SIZE = 96;
const WEEK_STROKE = 10;
const WEEK_RADIUS = (WEEK_SIZE - WEEK_STROKE) / 2;
const WEEK_CIRCUMFERENCE = 2 * Math.PI * WEEK_RADIUS;
/** The service errors with a text of their own; any other error gets the general text. */
const KNOWN_ERRORS = new Set(["not_found", "not_open", "unavailable"]);

/** The weekday key of a `YYYY-MM-DD` date, the same in every timezone. */
function weekdayOf(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
}

/** The card's error text key for an error from `hass.callService`. */
function errorKey(error: unknown): string {
  const key = (error as { translation_key?: unknown } | null)?.translation_key;
  return typeof key === "string" && KNOWN_ERRORS.has(key) ? `error.${key}` : "error.general";
}

/**
 * "Træning i dag" (UI refresh spec §2.1): a top line with the title and the people's streaks, then
 * the open training days, each with Start and a two-step Spring over (step 4 spec §6). While a
 * session is active the days give way to the session row: the program, the state line and the
 * people line, with Fortsæt (UI polish spec §2). The week ring sits beside the first row's text,
 * and each row's buttons sit under the ring and the text (UI polish spec §2.6).
 */
export class TodayCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    preview: { type: Boolean },
    editMode: { attribute: false },
    config: { state: true },
    today: { state: true },
    session: { state: true },
    stats: { state: true },
    error: { state: true },
  };

  declare hass?: Hass;
  /** Set by HA's `hui-card` in the card editor. */
  declare preview?: boolean;
  /** Set by HA's `hui-card` while the dashboard is in edit mode. */
  declare editMode?: boolean;
  declare config?: TodayCardConfig;
  /** Nothing yet (undefined), the add-on unreachable (null), or the today data. */
  declare today?: Today | null;
  /** The page's active session (running or paused), from the overlay controller. */
  declare session?: SessionView;
  /** The last stats message: nothing yet (undefined), or null while the subscription is refused. */
  declare stats?: StatsMessage | null;
  declare error?: string;

  /** HA's `hui-card` keeps a hidden card in the DOM only if it asks, and the card must stay subscribed. */
  readonly connectedWhileHidden = true;

  private readonly subscription = new TodaySubscription((today) => this.receive(today));
  private readonly statsSubscription = new WsSubscription<StatsMessage>("ha_fitness/stats/subscribe", (message) => {
    this.stats = message;
  });
  private readonly confirming = new Map<number, Confirming>();
  private errorTimer?: ReturnType<typeof setTimeout>;
  private stopListening?: () => void;

  static override styles = css`
    :host {
      display: block;
    }
    .top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 20px 0;
    }
    .title {
      font-size: 0.875em;
      font-weight: 600;
      letter-spacing: 0.1em;
      color: var(--secondary-text-color);
    }
    .streak {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      color: var(--primary-text-color);
    }
    .streak ha-icon {
      --mdc-icon-size: 20px;
      color: var(--warning-color);
    }
    .person {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }
    .body {
      padding: 8px 20px 20px;
    }
    /* The ring (first row only) beside the text, centred against it. */
    .head {
      display: flex;
      align-items: center;
      gap: 20px;
    }
    .text {
      display: flex;
      flex-direction: column;
      gap: 4px;
      flex: 1;
      min-width: 0;
    }
    .week {
      position: relative;
      flex: none;
      width: ${WEEK_SIZE}px;
      height: ${WEEK_SIZE}px;
    }
    .week svg {
      display: block;
      width: 100%;
      height: 100%;
    }
    .week .track {
      stroke: var(--divider-color);
    }
    .week .done {
      stroke: var(--success-color);
    }
    .week .numbers {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .week .count {
      font-size: 1.5em;
      font-weight: 700;
      color: var(--primary-text-color);
    }
    .week .label {
      font-size: 0.75em;
      color: var(--secondary-text-color);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    li + li {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--divider-color);
    }
    .name {
      font-size: 1.5em;
      font-weight: 600;
      line-height: 1.2;
      color: var(--primary-text-color);
    }
    .line {
      font-size: 1.0625em;
    }
    .line,
    .muted {
      color: var(--secondary-text-color);
    }
    .muted {
      padding: 16px 0;
    }
    /* Under the ring and the text, from the row's left edge. */
    .actions {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 12px;
      margin-top: 16px;
    }
    /* Start, Ja or Fortsæt: the first place, at the left. */
    .lead {
      display: flex;
      align-items: center;
    }
    .question {
      color: var(--primary-text-color);
    }
    button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      min-height: 48px;
      min-width: 64px;
      padding: 0 16px;
      border-radius: 24px;
      border: 1px solid var(--primary-color);
      background: none;
      color: var(--primary-color);
      font: inherit;
      font-weight: 500;
      white-space: nowrap;
      cursor: pointer;
    }
    button ha-icon {
      --mdc-icon-size: 20px;
    }
    /*
     * Start, Spring over, Ja, Nej and Fortsæt share one fixed width, wide enough for each text in both
     * languages, so Ja lands where Start was and Nej where Spring over was.
     */
    button.slot,
    button.yes {
      flex: none;
      width: 10em;
      padding: 0 12px;
      font-size: 1.0625em;
      font-weight: 600;
    }
    button.yes {
      background: var(--primary-color);
      color: var(--text-primary-color);
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .error {
      padding: 12px 16px 0;
      color: var(--error-color);
    }
  `;

  setConfig(config: TodayCardConfig): void {
    this.config = config;
  }

  /** One row of HA's grid for the top line, then three per open day (or for the session row). */
  getGridOptions(): { columns: "full"; rows: number } {
    return { columns: "full", rows: 1 + 3 * this.rowCount };
  }

  getCardSize(): number {
    return 1 + 3 * this.rowCount;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    if (this.hass) overlay.setHass(this.hass);
    // Another card may already hold a session; the controller hands this one its state at once.
    this.receiveSession(overlay.state().session);
    this.stopListening = overlay.subscribe((state) => this.receiveSession(state.session));
    // Hidden before the first render, so a day with no training never shows an empty cell.
    this.syncHidden();
    this.subscription.connect(this.hass?.connection);
    this.statsSubscription.connect(this.hass?.connection);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stopListening?.();
    this.stopListening = undefined;
    this.subscription.disconnect();
    this.statsSubscription.disconnect();
    for (const id of [...this.confirming.keys()]) this.endConfirm(id);
    clearTimeout(this.errorTimer);
    this.error = undefined;
    // Put back on the page, the card waits for fresh data from a new subscription.
    this.today = undefined;
    this.stats = undefined;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.isConnected && this.hass) {
      overlay.setHass(this.hass);
      this.subscription.connect(this.hass.connection);
      this.statsSubscription.connect(this.hass.connection);
    }
  }

  protected override updated(): void {
    this.syncHidden();
  }

  /**
   * Hidden, outside preview, until the first message and whenever nothing is open, unless a session
   * is active: then it shows, an extra session too.
   */
  private syncHidden(): void {
    const hide =
      !this.inPreview && !this.session && (this.today === undefined || this.today?.open.length === 0);
    if (hide === this.hidden) return;
    // As HA's own cards do: hui-card hides a card that sets `hidden` and says so.
    this.toggleAttribute("hidden", hide);
    this.style.display = hide ? "none" : "";
    this.dispatchEvent(
      new CustomEvent("card-visibility-changed", { detail: { value: !hide }, bubbles: true, composed: true }),
    );
  }

  private get inPreview(): boolean {
    return Boolean(this.preview || this.editMode);
  }

  /** One row for the session, else one per open day. */
  private get rowCount(): number {
    if (this.session) return 1;
    return Math.max(1, this.today?.open.length ?? 0);
  }

  private t(key: string, vars?: Vars): string {
    return localize(cardLanguage(this.config, this.hass), key, vars);
  }

  private receive(today: Today | null): void {
    this.today = today;
    const open = new Set(today?.open.map((day) => day.id));
    for (const id of [...this.confirming.keys()]) if (!open.has(id)) this.endConfirm(id);
  }

  /** The card's language option, for the flow it opens. */
  private get flowLanguage(): { language?: string } {
    return this.config?.language ? { language: this.config.language } : {};
  }

  private receiveSession(session: SessionView | null): void {
    this.session = isActive(session) ? session : undefined;
  }

  /** Start: unlock audio in the tap itself, before anything awaits, then show the program's details. */
  private start(day: OpenDay): void {
    unlockAudio();
    overlay.open({ kind: "details", programId: day.program_id, trainingDayId: day.id, ...this.flowLanguage });
  }

  /** Fortsæt: unlock audio in the tap itself, then reopen the overlay at the session. */
  private resume(): void {
    unlockAudio();
    overlay.open({ kind: "resume", ...this.flowLanguage });
  }

  /** The first tap: ask, and put the row back after 10 s with no answer. */
  private ask(id: number): void {
    const confirming: Confirming = { armed: false, busy: false, timers: [] };
    confirming.timers.push(
      setTimeout(() => {
        confirming.armed = true;
      }, ARM_MS),
      setTimeout(() => this.endConfirm(id), CONFIRM_MS),
    );
    this.confirming.set(id, confirming);
    this.requestUpdate();
  }

  private endConfirm(id: number): void {
    const confirming = this.confirming.get(id);
    if (!confirming) return;
    confirming.timers.forEach(clearTimeout);
    this.confirming.delete(id);
    this.requestUpdate();
  }

  private async skip(id: number): Promise<void> {
    const confirming = this.confirming.get(id);
    if (!confirming?.armed || confirming.busy || !this.hass) return;
    confirming.busy = true;
    confirming.timers.forEach(clearTimeout);
    this.requestUpdate();
    try {
      // notifyOnError false: HA shows no toast of its own, in the system language; the card shows its text.
      await this.hass.callService("ha_fitness", "skip", { training_day_id: id }, undefined, false);
    } catch (error) {
      this.showError(this.t(errorKey(error)));
    } finally {
      this.endConfirm(id);
    }
  }

  private showError(text: string): void {
    clearTimeout(this.errorTimer);
    this.error = text;
    this.errorTimer = setTimeout(() => {
      this.error = undefined;
    }, ERROR_MS);
  }

  /** "I dag", or "Forfalden · fredag" for a late day. */
  private stateLine(day: OpenDay): string {
    if (day.state !== "late") return this.t("today.due");
    return this.t("today.late", { weekday: this.t(`weekday.${weekdayOf(day.date)}`) });
  }

  /** "5 øvelser · 29 min". */
  private summaryLine(day: OpenDay): string {
    return this.t("today.short_summary", {
      stations: this.t("today.stations", { count: day.station_count }),
      minutes: this.t("today.short_minutes", { count: day.total_minutes }),
    });
  }

  /** The people whose streaks the badge shows, or none while there is nothing to show. */
  private get streakPeople(): PersonStats[] {
    const stats = this.stats;
    if (!stats?.available || !stats.stats || stats.stats.counting_from === null) return [];
    return stats.stats.people;
  }

  private renderStreak() {
    const people = this.streakPeople;
    if (!people.length) return nothing;
    const letters = initials(people.map((person) => person.name));
    const list = people.map((person) => `${person.name} ${person.streak}`).join(", ");
    // A colour dot never stands alone: each number has its person's initial.
    return html`
      <span class="streak" role="img" aria-label=${this.t("today.streak_label", { list })}>
        <ha-icon icon="mdi:lightning-bolt" aria-hidden="true"></ha-icon>
        ${people.map(
          (person, index) =>
            html`<span class="person" aria-hidden="true"
                ><span class="dot" style="background: ${personColor(index)}"></span>${letters[index]}
                ${person.streak}</span
              > `,
        )}
      </span>
    `;
  }

  /** The week ring: done of planned this week; none from an older add-on or with nothing planned. */
  private renderWeek() {
    const week = this.today?.week;
    if (!week || week.planned <= 0) return nothing;
    const fraction = Math.min(1, Math.max(0, week.done / week.planned));
    const centre = WEEK_SIZE / 2;
    const label = this.t("today.week");
    return html`
      <div
        class="week"
        role="progressbar"
        aria-label=${label}
        aria-valuemin="0"
        aria-valuemax=${week.planned}
        aria-valuenow=${week.done}
      >
        <svg viewBox="0 0 ${WEEK_SIZE} ${WEEK_SIZE}" aria-hidden="true">
          ${svg`
            <circle class="track" cx=${centre} cy=${centre} r=${WEEK_RADIUS} stroke-width=${WEEK_STROKE} fill="none" />
            <circle
              class="done"
              cx=${centre}
              cy=${centre}
              r=${WEEK_RADIUS}
              stroke-width=${WEEK_STROKE}
              fill="none"
              stroke-linecap="round"
              stroke-dasharray=${WEEK_CIRCUMFERENCE}
              stroke-dashoffset=${WEEK_CIRCUMFERENCE * (1 - fraction)}
              transform="rotate(-90 ${centre} ${centre})"
            />
          `}
        </svg>
        <div class="numbers">
          <span class="count">${week.done}/${week.planned}</span>
          <span class="label">${label}</span>
        </div>
      </div>
    `;
  }

  private renderActions(day: OpenDay) {
    const confirming = this.confirming.get(day.id);
    if (!confirming) {
      // Left-aligned: Start in the first place, Spring over in the second, where Nej comes after the first tap.
      return html`
        <div class="lead">
          ${iconButton({
            icon: "mdi:play",
            label: this.t("today.start"),
            text: this.t("today.start"),
            className: "yes",
            onClick: () => this.start(day),
          })}
        </div>
        ${iconButton({
          icon: "mdi:debug-step-over",
          label: this.t("today.skip"),
          text: this.t("today.skip"),
          className: "slot",
          onClick: () => this.ask(day.id),
        })}
      `;
    }
    // While it asks, the question takes the state line's place (see renderDays) and Ja and Nej take Start's and Spring
    // over's places, at the same widths, so a double tap on Spring over lands on Nej.
    return html`
      <div class="lead">
        ${iconButton({
          label: this.t("today.yes"),
          text: this.t("today.yes"),
          className: "yes",
          disabled: confirming.busy,
          onClick: () => void this.skip(day.id),
        })}
      </div>
      ${iconButton({
        label: this.t("today.no"),
        text: this.t("today.no"),
        className: "slot",
        disabled: confirming.busy,
        onClick: () => this.endConfirm(day.id),
      })}
    `;
  }

  /** "I gang · runde 2 af 5", "Pauset · runde 2 af 5", or the state word alone without a phase. */
  private sessionStateLine(session: SessionView): string {
    const state = this.t(session.status === "paused" ? "session.state_paused" : "session.state_running");
    if (!session.phase) return state;
    return this.t("session.state_round", { state, round: session.phase.round, rounds: session.totals.rounds });
  }

  /** "Thomas og Elin · 29 min": the minutes rounded as get ready's summary and the add-on's `total_minutes`. */
  private sessionPeopleLine(session: SessionView): string {
    const [first, second] = session.participants.map((person) => person.name);
    const people = second === undefined ? (first ?? "") : this.t("session.people_two", { first, second });
    return this.t("session.people_minutes", {
      people,
      minutes: this.t("today.short_minutes", { count: Math.floor((session.totals.planned + 30) / 60) }),
    });
  }

  /** A row's head: the week ring in the first row only, beside the text. */
  private renderHead(first: boolean, text: TemplateResult) {
    return html`<div class="head">${first ? this.renderWeek() : nothing}<div class="text">${text}</div></div>`;
  }

  private renderSession(session: SessionView) {
    return html`
      <ul>
        <li>
          ${this.renderHead(
            true,
            html`
              <div class="name">${session.program_name}</div>
              <div class="line">${this.sessionStateLine(session)}</div>
              <div class="line">${this.sessionPeopleLine(session)}</div>
            `,
          )}
          <div class="actions">
            <div class="lead">
              ${iconButton({
                icon: "mdi:play",
                label: this.t("session.resume"),
                text: this.t("session.resume"),
                className: "yes",
                onClick: () => this.resume(),
              })}
            </div>
          </div>
        </li>
      </ul>
    `;
  }

  private renderDays() {
    if (this.session) return this.renderSession(this.session);
    const today = this.today;
    // Without rows, the ring and the text sit side by side.
    if (today === null) return this.renderHead(true, html`<div class="muted">${this.t("today.unreachable")}</div>`);
    if (!today?.open.length) {
      return this.renderHead(true, html`<div class="muted">${this.t("today.nothing_open")}</div>`);
    }
    return html`
      <ul>
        ${today.open.map(
          (day, index) => html`
            <li>
              ${this.renderHead(
                index === 0,
                html`
                  <div class="name">${day.program_name}</div>
                  ${this.confirming.has(day.id)
                    ? html`<div class="line question">${this.t("today.skip_confirm")}</div>`
                    : html`<div class="line">${this.stateLine(day)}</div>`}
                  <div class="line">${this.summaryLine(day)}</div>
                `,
              )}
              <div class="actions">${this.renderActions(day)}</div>
            </li>
          `,
        )}
      </ul>
    `;
  }

  protected override render() {
    // No data yet, or hidden with nothing open; an active session always shows.
    if (!this.session) {
      if (this.today === undefined) return nothing;
      if (this.today !== null && this.today.open.length === 0 && !this.inPreview) return nothing;
    }
    return html`
      <ha-card>
        ${this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing}
        <div class="top">
          <span class="title">${this.t("today.title")}</span>
          ${this.renderStreak()}
        </div>
        <div class="body">${this.renderDays()}</div>
      </ha-card>
    `;
  }
}

/** Define the card and offer it in the card picker; `index.ts` calls this once HA has booted. */
export function registerTodayCard(): void {
  if (customElements.get(TAG)) return;
  customElements.define(TAG, TodayCard);
  window.customCards = window.customCards ?? [];
  window.customCards.push({
    type: TAG,
    // There is no `hass` at module load, so the picker shows the English texts.
    name: localize("en", "picker.name"),
    description: localize("en", "picker.description"),
  });
}
