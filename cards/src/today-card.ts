import { LitElement, type PropertyValues, css, html, nothing } from "lit";

import { unlockAudio } from "./audio";
import { type Vars, localize } from "./i18n";
import { type LanguageConfig, type LanguageHass, cardLanguage } from "./language";
import * as overlay from "./overlay";
import { type SessionView, isActive } from "./overlay";
import { type Connection, type OpenDay, type Today, TodaySubscription } from "./today-data";

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
const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
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
 * "Træning i dag": the open training days, each with Start and a two-step Spring over (step 4
 * spec §6). While a session is active it shows "Træning i gang" and Fortsæt instead (spec §5.1).
 */
export class TodayCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    preview: { type: Boolean },
    editMode: { attribute: false },
    config: { state: true },
    today: { state: true },
    session: { state: true },
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
  declare error?: string;

  /** HA's `hui-card` keeps a hidden card in the DOM only if it asks, and the card must stay subscribed. */
  readonly connectedWhileHidden = true;

  private readonly subscription = new TodaySubscription((today) => this.receive(today));
  private readonly confirming = new Map<number, Confirming>();
  private errorTimer?: ReturnType<typeof setTimeout>;
  private stopListening?: () => void;

  static override styles = css`
    :host {
      display: block;
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    li {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 12px 16px;
    }
    li + li {
      border-top: 1px solid var(--divider-color);
    }
    .text {
      flex: 1;
      min-width: 0;
    }
    .name {
      font-size: 1.5em;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .line,
    .muted {
      color: var(--secondary-text-color);
    }
    .muted {
      padding: 16px;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .question {
      color: var(--primary-text-color);
    }
    button {
      min-height: 48px;
      min-width: 64px;
      padding: 0 16px;
      border-radius: 24px;
      border: 1px solid var(--primary-color);
      background: none;
      color: var(--primary-color);
      font: inherit;
      font-weight: 500;
      cursor: pointer;
    }
    /* Spring over and Nej share one place and width, wide enough for either text in both languages. */
    button.slot {
      width: 9em;
      padding: 0 12px;
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

  /** Two rows of HA's grid per open day, so a name, a line and a 48 px button fit. */
  getGridOptions(): { columns: "full"; rows: number } {
    return { columns: "full", rows: 2 * this.rowCount };
  }

  getCardSize(): number {
    return 2 * this.rowCount;
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
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stopListening?.();
    this.stopListening = undefined;
    this.subscription.disconnect();
    for (const id of [...this.confirming.keys()]) this.endConfirm(id);
    clearTimeout(this.errorTimer);
    this.error = undefined;
    // Put back on the page, the card waits for fresh data from a new subscription.
    this.today = undefined;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.isConnected && this.hass) {
      overlay.setHass(this.hass);
      this.subscription.connect(this.hass.connection);
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

  private receiveSession(session: SessionView | null): void {
    this.session = isActive(session) ? session : undefined;
  }

  /** Start: unlock audio in the tap itself, before anything awaits, then show the program's details. */
  private start(day: OpenDay): void {
    unlockAudio();
    overlay.open({ kind: "details", programId: day.program_id, trainingDayId: day.id });
  }

  /** Fortsæt: unlock audio in the tap itself, then reopen the overlay at the session. */
  private resume(): void {
    unlockAudio();
    overlay.open({ kind: "resume" });
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

  private line(day: OpenDay): string {
    const summary = this.t("today.summary", {
      stations: this.t("today.stations", { count: day.station_count }),
      rounds: this.t("today.rounds", { count: day.rounds }),
      minutes: this.t("today.minutes", { count: day.total_minutes }),
    });
    if (day.state !== "late") return summary;
    return this.t("today.late", { weekday: this.t(`weekday.${weekdayOf(day.date)}`), summary });
  }

  private renderActions(day: OpenDay) {
    const confirming = this.confirming.get(day.id);
    if (!confirming) {
      // Start sits before Spring over, at the same size, so Spring over (and Nej after it) keeps the last place.
      return html`
        <button class="slot yes" @click=${() => this.start(day)}>${this.t("today.start")}</button>
        <button class="slot" @click=${() => this.ask(day.id)}>${this.t("today.skip")}</button>
      `;
    }
    // While it asks, Start is hidden: the row holds only the question, Ja and Nej. Nej is last and as wide as Spring over (the "slot"), so a double tap lands on Nej.
    return html`
      <span class="question">${this.t("today.skip_confirm")}</span>
      <button class="yes" ?disabled=${confirming.busy} @click=${() => this.skip(day.id)}>
        ${this.t("today.yes")}
      </button>
      <button class="slot" ?disabled=${confirming.busy} @click=${() => this.endConfirm(day.id)}>
        ${this.t("today.no")}
      </button>
    `;
  }

  private renderSession(session: SessionView) {
    return html`
      <ul>
        <li>
          <div class="text">
            <div class="name">${this.t("session.running", { program: session.program_name })}</div>
          </div>
          <div class="actions">
            <button class="slot yes" @click=${() => this.resume()}>${this.t("session.resume")}</button>
          </div>
        </li>
      </ul>
    `;
  }

  private renderBody() {
    if (this.session) return this.renderSession(this.session);
    const today = this.today;
    if (today === null) return html`<div class="muted">${this.t("today.unreachable")}</div>`;
    if (!today?.open.length) return html`<div class="muted">${this.t("today.nothing_open")}</div>`;
    return html`
      <ul>
        ${today.open.map(
          (day) => html`
            <li>
              <div class="text">
                <div class="name">${day.program_name}</div>
                <div class="line">${this.line(day)}</div>
              </div>
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
        ${this.renderBody()}
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
