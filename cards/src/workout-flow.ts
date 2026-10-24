import { LitElement, type PropertyValues, css, html, nothing } from "lit";

import { unlockAudio } from "./audio";
import { type Vars, localize } from "./i18n";
import { type ImageHass, imageUrl } from "./images";
import { type LanguageHass, cardLanguage } from "./language";
import type { OverlayMode, SessionState, SessionView } from "./overlay";

/** An active program, as `ha_fitness/programs` returns it (spec §4). */
interface Program {
  id: number;
  name: string;
  rounds: number;
  work_seconds: number;
  switch_seconds: number;
  round_rest_seconds: number;
  countdown_seconds: number;
  total_minutes: number;
  stations: { exercise_id: string; name: string }[];
}

/** A person, as `ha_fitness/people` returns it (spec §4). */
interface Person {
  id: number;
  name: string;
}

/** The part of Home Assistant's `hass` object the flow uses. */
interface Hass extends LanguageHass, ImageHass {
  callWS<T>(message: { type: string } & Record<string, unknown>): Promise<T>;
}

type Command = "pause" | "resume" | "next" | "previous" | "end";
type Step = "details" | "ready" | "timer" | "done";

declare global {
  interface HTMLElementTagNameMap {
    "ha-fitness-workout-flow": WorkoutFlow;
  }
}

const TAG = "ha-fitness-workout-flow";
/** The people's colours, by people order (design §3.4). Used for borders and badges, never for text. */
const PERSON_COLORS = ["#B18CFF", "#3DD6C6"];
const IDLE_MS = 60_000;
const TICK_MS = 250;
/** The command errors with a text of their own; any other gets the general text. */
const KNOWN_ERRORS = new Set(["not_found", "invalid", "unavailable"]);

function isActive(session: SessionView | null | undefined): boolean {
  return session?.status === "running" || session?.status === "paused";
}

/** The ws error code of a rejected `callWS`, which rejects with `{code, message}`. */
function errorCode(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : undefined;
}

/**
 * The workout flow in the overlay (spec §5.2): details, get ready, the timer and done. The overlay
 * controller hands it `hass`, the live session state, the mode and `onClose`; it never subscribes.
 */
export class WorkoutFlow extends LitElement {
  static override properties = {
    hass: { attribute: false },
    state: { attribute: false },
    mode: { attribute: false },
    onClose: { attribute: false },
    programs: { state: true },
    people: { state: true },
    selected: { state: true },
    thumbnails: { state: true },
    busy: { state: true },
    error: { state: true },
    result: { state: true },
  };

  declare hass?: Hass;
  declare state?: SessionState;
  declare mode?: OverlayMode;
  declare onClose?: () => void;
  /** The active programs and the people: undefined while loading, null if the fetch failed. */
  declare programs?: Program[] | null;
  declare people?: Person[] | null;
  /** The chosen people's ids. */
  declare selected: Set<number>;
  /** The object URL of each exercise's thumbnail, or null when it has none. */
  declare thumbnails: Map<string, string | null>;
  declare busy: boolean;
  declare error?: string;
  /** The newest view a command returned. */
  declare result?: SessionView;

  /** The newest view the flow has seen, from a push or a command result. */
  private newest?: SessionView;
  /** Set once this flow has started a session, or shown one: details never comes back. */
  private leftDetails = false;
  /** Sessions annulled from get ready: their done step never shows. */
  private readonly annulled = new Set<number>();
  private idleTimer?: ReturnType<typeof setTimeout>;
  private tickTimer?: ReturnType<typeof setInterval>;
  /** `server_time − Date.now()` of the newest view, in ms. */
  private offset = 0;
  private readonly onActivity = (): void => this.armIdle();

  constructor() {
    super();
    this.selected = new Set();
    this.thumbnails = new Map();
    this.busy = false;
  }

  static override styles = css`
    :host {
      display: block;
      box-sizing: border-box;
      min-height: 100%;
      padding: 32px;
      color: var(--primary-text-color);
      background: var(--card-background-color, var(--primary-background-color));
      font-size: 1.25rem;
    }
    h2 {
      margin: 0 0 8px;
      font-size: 2.5rem;
      font-weight: 500;
    }
    .line {
      color: var(--secondary-text-color);
      margin: 4px 0;
    }
    ol,
    ul {
      list-style: none;
      margin: 16px 0;
      padding: 0;
    }
    .stations li {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 8px 0;
    }
    .number {
      min-width: 1.5em;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .thumb {
      width: 64px;
      height: 64px;
      border-radius: 8px;
      object-fit: cover;
      background: var(--secondary-background-color, var(--divider-color));
    }
    .chips {
      display: flex;
      gap: 16px;
      margin: 16px 0;
      border: none;
      padding: 0;
    }
    .chips legend {
      padding: 0;
      margin-bottom: 8px;
      color: var(--secondary-text-color);
    }
    button {
      min-height: 48px;
      min-width: 96px;
      padding: 0 24px;
      border-radius: 24px;
      border: 2px solid var(--primary-color);
      background: none;
      color: var(--primary-text-color);
      font: inherit;
      font-weight: 500;
      cursor: pointer;
    }
    button.chip {
      border-color: var(--person-color);
      border-width: 3px;
    }
    button.chip[aria-pressed="true"] {
      background: color-mix(in srgb, var(--person-color) 25%, transparent);
    }
    button.main {
      min-height: 96px;
      min-width: 192px;
      border-radius: 48px;
      font-size: 1.5rem;
      background: var(--primary-color);
      color: var(--text-primary-color);
    }
    button:disabled {
      opacity: 0.4;
      cursor: default;
    }
    .actions {
      display: flex;
      gap: 24px;
      align-items: center;
      margin-top: 32px;
    }
    .count {
      font-size: 6rem;
      font-weight: 500;
      margin: 16px 0;
    }
    .badge {
      display: inline-block;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      margin-right: 12px;
      background: var(--person-color);
    }
    .starts li {
      padding: 8px 0;
      font-size: 1.5rem;
    }
    .error {
      color: var(--error-color);
      margin: 16px 0;
    }
  `;

  override connectedCallback(): void {
    super.connectedCallback();
    this.addEventListener("pointerdown", this.onActivity);
    this.addEventListener("click", this.onActivity);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.removeEventListener("pointerdown", this.onActivity);
    this.removeEventListener("click", this.onActivity);
    this.stopIdle();
    this.stopTick();
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("state")) this.take(this.state?.session ?? undefined);
    if (changed.has("result")) this.take(this.result);
    // A new details mode on the same flow (a Start while a finished view shows) starts over.
    if (changed.has("mode")) this.leftDetails = isActive(this.newest);
    // The controller hands over `hass` on every card update; only a new mode loads again.
    if (changed.has("mode") || (changed.has("hass") && this.programs === undefined)) this.load();
  }

  protected override updated(): void {
    const step = this.step();
    if (step === "details") {
      if (!this.idleTimer && !this.busy) this.armIdle();
    } else {
      this.stopIdle();
    }
    if (step === "ready" && this.newest?.status === "running") this.startTick();
    else this.stopTick();
    if (step === "done" && this.newest && this.annulled.has(this.newest.id)) this.onClose?.();
  }

  /** Keep the newer of the flow's view and `view`: a higher revision, or another session. */
  private take(view: SessionView | undefined): void {
    if (!view) return;
    const newest = this.newest;
    if (newest && newest.id === view.id && newest.revision >= view.revision) return;
    this.newest = view;
    this.offset = Date.parse(view.server_time) - Date.now();
    if (isActive(view)) this.leftDetails = true;
  }

  /** Fetch the programs and the people for a details mode, and start the choice over. */
  private load(): void {
    const mode = this.mode;
    const hass = this.hass;
    if (mode?.kind !== "details" || !hass) return;
    this.error = undefined;
    this.selected = new Set();
    this.programs = undefined;
    this.people = undefined;
    this.armIdle();
    void Promise.all([
      hass.callWS<Program[]>({ type: "ha_fitness/programs" }),
      hass.callWS<Person[]>({ type: "ha_fitness/people" }),
    ]).then(
      ([programs, people]) => {
        if (this.mode !== mode) return;
        this.programs = programs;
        this.people = people;
        const program = this.program();
        const max = Math.min(2, program?.stations.length ?? 0);
        this.selected = new Set(people.slice(0, max).map((person) => person.id));
        for (const station of program?.stations ?? []) this.loadThumbnail(hass, station.exercise_id);
      },
      () => {
        if (this.mode !== mode) return;
        this.programs = null;
        this.people = null;
      },
    );
  }

  private loadThumbnail(hass: Hass, exerciseId: string): void {
    if (this.thumbnails.has(exerciseId)) return;
    void imageUrl(hass, exerciseId, "thumbnail").then((url) => {
      this.thumbnails = new Map(this.thumbnails).set(exerciseId, url);
    });
  }

  private program(): Program | undefined {
    const mode = this.mode;
    if (mode?.kind !== "details") return undefined;
    return this.programs?.find((program) => program.id === mode.programId);
  }

  /** Which step shows (the brief of F2). */
  private step(): Step | undefined {
    const view = this.newest;
    if (this.mode?.kind === "details" && !this.leftDetails && !isActive(view)) return "details";
    if (!view) return undefined;
    if (!isActive(view)) return "done";
    return view.phase?.kind === "countdown" ? "ready" : "timer";
  }

  private t(key: string, vars?: Vars): string {
    return localize(cardLanguage(undefined, this.hass), key, vars);
  }

  private armIdle(): void {
    this.stopIdle();
    if (this.step() !== "details" && this.step() !== undefined) return;
    if (this.mode?.kind !== "details" || this.busy) return;
    this.idleTimer = setTimeout(() => {
      this.idleTimer = undefined;
      if (this.step() === "details" && !this.busy) this.onClose?.();
    }, IDLE_MS);
  }

  private stopIdle(): void {
    clearTimeout(this.idleTimer);
    this.idleTimer = undefined;
  }

  private startTick(): void {
    if (this.tickTimer) return;
    this.tickTimer = setInterval(() => this.requestUpdate(), TICK_MS);
  }

  private stopTick(): void {
    clearInterval(this.tickTimer);
    this.tickTimer = undefined;
  }

  private toggle(person: Person): void {
    const selected = new Set(this.selected);
    if (selected.has(person.id)) selected.delete(person.id);
    else if (selected.size < this.maxSelected()) selected.add(person.id);
    this.selected = selected;
  }

  private maxSelected(): number {
    return Math.min(2, this.program()?.stations.length ?? 0);
  }

  private async start(): Promise<void> {
    // The browser allows sound only after a gesture: unlock before anything awaits.
    unlockAudio();
    const mode = this.mode;
    const program = this.program();
    const hass = this.hass;
    if (mode?.kind !== "details" || !program || !hass || this.busy || this.selected.size === 0) return;
    this.busy = true;
    this.error = undefined;
    this.stopIdle();
    // Participants go in people order, whatever order they were tapped in.
    const participants = (this.people ?? []).filter((person) => this.selected.has(person.id)).map((p) => p.id);
    try {
      this.result = await hass.callWS<SessionView>({
        type: "ha_fitness/session/command",
        command: "start",
        program_id: program.id,
        participants,
        ...(mode.trainingDayId === undefined ? {} : { training_day_id: mode.trainingDayId }),
      });
    } catch (error) {
      this.error = this.t(this.startErrorKey(error));
    } finally {
      this.busy = false;
    }
  }

  private startErrorKey(error: unknown): string {
    const code = errorCode(error);
    if (code === "conflict") {
      return isActive(this.state?.session) ? "flow.error.already_running" : "flow.error.cant_start";
    }
    return code && KNOWN_ERRORS.has(code) ? `flow.error.${code}` : "flow.error.general";
  }

  /** Send a command to the running session; its result is a view like any push. */
  private async command(command: Command): Promise<void> {
    const hass = this.hass;
    if (!hass) return;
    try {
      this.result = await hass.callWS<SessionView>({ type: "ha_fitness/session/command", command });
    } catch (error) {
      const code = errorCode(error);
      this.error = this.t(code && KNOWN_ERRORS.has(code) ? `flow.error.${code}` : "flow.error.general");
    }
  }

  /** Annullér: end the session, close at once, and never show its done step. */
  private annul(): void {
    const view = this.newest;
    if (view) this.annulled.add(view.id);
    this.onClose?.();
    void this.command("end");
  }

  /** The seconds left of the view's phase, rounded up, from the local clock corrected to the add-on's. */
  private secondsLeft(view: SessionView): number {
    const phase = view.phase;
    if (!phase) return 0;
    if (phase.ends_at === null) return Math.ceil(phase.remaining ?? phase.duration);
    const left = (Date.parse(phase.ends_at) - (Date.now() + this.offset)) / 1000;
    return Math.max(0, Math.ceil(left));
  }

  private renderError() {
    return this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing;
  }

  private renderThumbnail(station: { exercise_id: string; name: string }) {
    const url = this.thumbnails.get(station.exercise_id);
    return url
      ? html`<img class="thumb" src=${url} alt=${station.name} />`
      : html`<span class="thumb" role="img" aria-label=${station.name}></span>`;
  }

  private renderDetails() {
    if (this.programs === undefined) return html`${this.renderBack()}`;
    const program = this.program();
    if (!program) {
      return html`
        <div class="error" role="alert">${this.t(this.programs === null ? "flow.error.unavailable" : "flow.error.not_found")}</div>
        ${this.renderBack()}
      `;
    }
    const people = this.people ?? [];
    const max = this.maxSelected();
    return html`
      <h2>${program.name}</h2>
      <p class="line">
        ${this.t("flow.summary", {
          minutes: this.t("today.minutes", { count: program.total_minutes }),
          rounds: this.t("today.rounds", { count: program.rounds }),
        })}
      </p>
      <p class="line">
        ${this.t("flow.seconds", {
          work: program.work_seconds,
          switch: program.switch_seconds,
          rest: program.round_rest_seconds,
        })}
      </p>
      <ol class="stations" aria-label=${this.t("flow.stations")}>
        ${program.stations.map(
          (station, index) => html`
            <li>
              <span class="number">${index + 1}</span>
              ${this.renderThumbnail(station)}
              <span>${station.name}</span>
            </li>
          `,
        )}
      </ol>
      ${people.length === 0
        ? html`<p class="line">${this.t("flow.no_people")}</p>`
        : html`
            <fieldset class="chips">
              <legend>${this.t("flow.who")}</legend>
              ${people.map((person, index) => {
                const chosen = this.selected.has(person.id);
                return html`
                  <button
                    class="chip"
                    style="--person-color: ${PERSON_COLORS[index] ?? "var(--primary-color)"}"
                    aria-pressed=${chosen ? "true" : "false"}
                    ?disabled=${this.busy || (!chosen && this.selected.size >= max)}
                    @click=${() => this.toggle(person)}
                  >
                    ${person.name}
                  </button>
                `;
              })}
            </fieldset>
          `}
      ${this.renderError()}
      <div class="actions">
        <button
          class="main"
          ?disabled=${this.busy || this.selected.size === 0}
          @click=${() => this.start()}
        >
          ${this.t("flow.start")}
        </button>
        ${this.renderBack()}
      </div>
    `;
  }

  private renderBack() {
    return html`<button @click=${() => this.onClose?.()}>${this.t("flow.back")}</button>`;
  }

  private renderReady(view: SessionView) {
    const paused = view.status === "paused";
    return html`
      <h2>${view.program_name}</h2>
      <div class="count">${this.secondsLeft(view)}</div>
      <ul class="starts" aria-label=${this.t("flow.get_ready")}>
        ${view.participants.map((person, index) => {
          const station = view.stations?.[index]?.current;
          return html`
            <li>
              <span class="badge" style="--person-color: ${PERSON_COLORS[index]}"></span>
              ${this.t("flow.starts_at", {
                name: person.name,
                number: station?.number ?? "",
                exercise: station?.name ?? "",
              })}
            </li>
          `;
        })}
      </ul>
      ${this.renderError()}
      <div class="actions">
        <button class="main" @click=${() => this.command("next")}>${this.t("flow.start_now")}</button>
        <button @click=${() => this.command(paused ? "resume" : "pause")}>
          ${this.t(paused ? "flow.resume" : "flow.pause")}
        </button>
        <button @click=${() => this.annul()}>${this.t("flow.cancel")}</button>
      </div>
    `;
  }

  // F3 replaces the timer and done placeholders.
  private renderTimer(view: SessionView) {
    const kind = view.status === "paused" ? "paused" : (view.phase?.kind ?? "work");
    return html`<h2>${this.t(`flow.phase.${kind}`)}</h2>`;
  }

  private renderDone(view: SessionView) {
    return html`
      <h2>${this.t(view.counted ? "flow.done.counted" : "flow.done.ended")}</h2>
      <div class="actions">
        <button class="main" @click=${() => this.onClose?.()}>${this.t("flow.close")}</button>
      </div>
    `;
  }

  protected override render() {
    const view = this.newest;
    switch (this.step()) {
      case "details":
        return this.renderDetails();
      case "ready":
        return this.renderReady(view!);
      case "timer":
        return this.renderTimer(view!);
      case "done":
        return view && this.annulled.has(view.id) ? nothing : this.renderDone(view!);
      default:
        // No session to show (a Fortsæt after the session was gone): only a way out.
        return html`<div class="actions">${this.renderBack()}</div>`;
    }
  }
}

if (!customElements.get(TAG)) customElements.define(TAG, WorkoutFlow);
