import { LitElement, type PropertyValues, css, html, nothing } from "lit";

import { unlockAudio } from "./audio";
import { type Vars, localize } from "./i18n";
import { type LanguageConfig, type LanguageHass, cardLanguage } from "./language";
import * as overlay from "./overlay";
import { type SessionView, isActive } from "./overlay";
import type { Connection } from "./today-data";

/** An active program, as `ha_fitness/programs` returns it (spec §4); the parts this card shows. */
interface Program {
  id: number;
  name: string;
  rounds: number;
  total_minutes: number;
  stations: { exercise_id: string; name: string }[];
}

/** The part of Home Assistant's `hass` object this card uses. */
interface Hass extends LanguageHass {
  connection?: Connection;
  callWS<T>(message: { type: string } & Record<string, unknown>): Promise<T>;
}

interface WorkoutCardConfig extends LanguageConfig {
  type: string;
}

declare global {
  interface HTMLElementTagNameMap {
    "ha-fitness-workout-card": WorkoutCard;
  }
}

const TAG = "ha-fitness-workout-card";
/** The waits before the retries of a failed fetch; the last one repeats. */
const RETRY_MS = [5_000, 10_000, 30_000];

/**
 * The workout tab's card (spec §5.1): the active programs, each with Start, which opens the page's
 * overlay for an extra session. While a session is active it shows "Træning i gang" and Fortsæt.
 * It has no flow of its own, so a view change can't tear down a running flow.
 */
export class WorkoutCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
    programs: { state: true },
    session: { state: true },
  };

  declare hass?: Hass;
  declare config?: WorkoutCardConfig;
  /** Nothing yet (undefined), the fetch failed (null), or the active programs. */
  declare programs?: Program[] | null;
  /** The page's active session (running or paused), from the overlay controller. */
  declare session?: SessionView;

  private stopListening?: () => void;
  /** Whether this connection of the card has fetched the programs yet. */
  private fetched = false;
  /** Only the newest fetch's answer counts. */
  private fetchCount = 0;
  /** The add-on's reach in the controller's last message, once this card has heard one. */
  private available?: boolean;
  /** The connection whose `ready` (after a reconnect) fetches again. */
  private connection?: Connection;
  private retries = 0;
  private retryTimer?: ReturnType<typeof setTimeout>;
  /** A Start's fetch is running; another tap waits for it. */
  private starting = false;
  private readonly onReady = (): void => {
    void this.fetchPrograms();
  };

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
    button {
      min-height: 48px;
      width: 9em;
      padding: 0 12px;
      border-radius: 24px;
      border: 1px solid var(--primary-color);
      background: var(--primary-color);
      color: var(--text-primary-color);
      font: inherit;
      font-weight: 500;
      cursor: pointer;
    }
  `;

  setConfig(config: WorkoutCardConfig): void {
    this.config = config;
  }

  getCardSize(): number {
    return 2 * Math.max(1, this.session ? 1 : (this.programs?.length ?? 0));
  }

  override connectedCallback(): void {
    super.connectedCallback();
    if (this.hass) overlay.setHass(this.hass);
    // Another card may already hold a session; the controller hands this one its state at once.
    this.receiveSession(overlay.state().session);
    this.available = undefined;
    this.stopListening = overlay.subscribe((state) => {
      this.receiveSession(state.session);
      // The add-on is back: the list may have changed while it was gone. The first message only
      // says how things stand.
      const back = this.available === false && state.available;
      this.available = state.available;
      if (back) void this.fetchPrograms();
    });
    this.listen(this.hass?.connection);
    this.fetchOnce();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.stopListening?.();
    this.stopListening = undefined;
    this.listen(undefined);
    this.stopRetry();
    this.fetched = false;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.isConnected && this.hass) {
      overlay.setHass(this.hass);
      this.listen(this.hass.connection);
      this.fetchOnce();
    }
  }

  /** Listen for `ready` on `connection`, and on no other. */
  private listen(connection: Connection | undefined): void {
    if (connection === this.connection) return;
    this.connection?.removeEventListener?.("ready", this.onReady);
    this.connection = connection;
    connection?.addEventListener?.("ready", this.onReady);
  }

  private stopRetry(): void {
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.retries = 0;
  }

  /** While the programs couldn't be fetched, try again after 5, 10 and 30 s, then every 30 s. */
  private retryLater(): void {
    clearTimeout(this.retryTimer);
    const delay = RETRY_MS[Math.min(this.retries, RETRY_MS.length - 1)];
    this.retries += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.fetchPrograms();
    }, delay);
  }

  private t(key: string, vars?: Vars): string {
    return localize(cardLanguage(this.config, this.hass), key, vars);
  }

  /** The card's language option, for the flow it opens. */
  private get flowLanguage(): { language?: string } {
    return this.config?.language ? { language: this.config.language } : {};
  }

  private receiveSession(session: SessionView | null): void {
    this.session = isActive(session) ? session : undefined;
  }

  /** The first fetch after the card is connected and has `hass`. */
  private fetchOnce(): void {
    if (this.fetched || !this.hass) return;
    this.fetched = true;
    void this.fetchPrograms();
  }

  /** Fetch the active programs; the answer, or null if the fetch failed. */
  private async fetchPrograms(): Promise<Program[] | null> {
    const hass = this.hass;
    if (!hass) return null;
    const count = ++this.fetchCount;
    let programs: Program[] | null;
    try {
      programs = await hass.callWS<Program[]>({ type: "ha_fitness/programs" });
    } catch {
      programs = null;
    }
    if (count === this.fetchCount && this.isConnected) {
      this.programs = programs;
      if (programs === null) this.retryLater();
      else this.stopRetry();
    }
    return programs;
  }

  /**
   * Start: unlock audio in the tap itself, before anything awaits. Then fetch the programs again
   * and open the details of this one if it is still active. A failed fetch still opens; the flow
   * shows its own error.
   */
  private async start(program: Program): Promise<void> {
    unlockAudio();
    // A double tap opens once.
    if (this.starting) return;
    this.starting = true;
    try {
      const programs = await this.fetchPrograms();
      if (programs !== null && !programs.some((fresh) => fresh.id === program.id)) return;
      overlay.open({ kind: "details", programId: program.id, ...this.flowLanguage });
    } finally {
      this.starting = false;
    }
  }

  /** Fortsæt: unlock audio in the tap itself, then reopen the overlay at the session. */
  private resume(): void {
    unlockAudio();
    overlay.open({ kind: "resume", ...this.flowLanguage });
  }

  private line(program: Program): string {
    return this.t("today.summary", {
      stations: this.t("today.stations", { count: program.stations.length }),
      rounds: this.t("today.rounds", { count: program.rounds }),
      minutes: this.t("today.minutes", { count: program.total_minutes }),
    });
  }

  private renderBody() {
    const session = this.session;
    if (session) {
      return html`
        <ul>
          <li>
            <div class="text">
              <div class="name">${this.t("session.running", { program: session.program_name })}</div>
            </div>
            <button @click=${() => this.resume()}>${this.t("session.resume")}</button>
          </li>
        </ul>
      `;
    }
    const programs = this.programs;
    if (programs === undefined) return nothing;
    if (programs === null) return html`<div class="muted">${this.t("workout.unreachable")}</div>`;
    if (!programs.length) return html`<div class="muted">${this.t("workout.no_programs")}</div>`;
    return html`
      <ul>
        ${programs.map(
          (program) => html`
            <li>
              <div class="text">
                <div class="name">${program.name}</div>
                <div class="line">${this.line(program)}</div>
              </div>
              <button @click=${() => this.start(program)}>${this.t("today.start")}</button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  protected override render() {
    return html`<ha-card>${this.renderBody()}</ha-card>`;
  }
}

/** Define the card and offer it in the card picker; `index.ts` calls this once HA has booted. */
export function registerWorkoutCard(): void {
  if (customElements.get(TAG)) return;
  customElements.define(TAG, WorkoutCard);
  window.customCards = window.customCards ?? [];
  window.customCards.push({
    type: TAG,
    // There is no `hass` at module load, so the picker shows the English texts.
    name: localize("en", "picker_workout.name"),
    description: localize("en", "picker_workout.description"),
  });
}
