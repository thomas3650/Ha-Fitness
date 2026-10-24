import { LitElement, type PropertyValues, type TemplateResult, css, html, nothing } from "lit";

import {
  type ToneKind,
  audioLocked,
  audioSupported,
  audioTime,
  onAudioStateChange,
  scheduleTone,
  unlockAudio,
} from "./audio";
import { type Vars, localize } from "./i18n";
import { type ImageHass, type ImageKind, imageUrl } from "./images";
import { type LanguageHass, cardLanguage } from "./language";
import {
  type OverlayMode,
  type PhaseKind,
  type SessionState,
  type SessionStation,
  type SessionView,
  lostAt,
  receivedAt,
} from "./overlay";
import { ring } from "./ring";

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
/** Luk shows after this long unreachable, so a touch-only kiosk is never trapped (spec §5.3). */
const UNREACHABLE_MS = 10_000;
/** Slut's Ja ignores taps until it has shown this long, so a wake tap can't end a workout. */
const ARM_MS = 500;
/** An unanswered "Afslut træningen?" goes after this long. */
const CONFIRM_MS = 10_000;
/** The done step closes by itself after this long. */
const DONE_MS = 60_000;
/** The beeps before a phase ends, in seconds left (spec §5.4). */
const BEEP_SECONDS = 5;
/** How long a started tone is remembered, so a new plan doesn't play it again (seconds). */
const STARTED_S = 2;
/** No beep falls this soon after a phase starts, where it would clash with the change tone. */
const QUIET_MS = 300;
/** The ring's colours: orange for work, blue for the rest (design §3.4). Never used for text. */
const RING_COLORS: Record<PhaseKind, string> = {
  countdown: "#4DA8FF",
  work: "#FF8A3D",
  switch: "#4DA8FF",
  rest: "#4DA8FF",
};

/** What the timer shows of a phase at this moment (spec §5.3). */
interface Countdown {
  /** The phase kind whose word shows: the next one at local zero. */
  kind: PhaseKind;
  /** The length of the phase shown, in seconds. */
  duration: number;
  /** The seconds left, rounded up. */
  seconds: number;
  /** The share of the phase left, 0..1. */
  fraction: number;
  /** True at local zero, before the message of the next phase has come. */
  ahead: boolean;
}

/** `seconds` as m:ss, or h:mm:ss from an hour. */
function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

/** Slut's question. */
interface EndQuestion {
  armed: boolean;
  timers: ReturnType<typeof setTimeout>[];
}
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
    images: { state: true },
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
  /** The object URL of each exercise's image by `kind/id`, or null when it has none. */
  declare images: Map<string, string | null>;
  declare busy: boolean;
  declare error?: string;
  /** The newest view a command returned. */
  declare result?: SessionView;

  /** The newest view the flow has seen, from a push or a command result. */
  private newest?: SessionView;
  /** Set once this flow has started a session, or shown one: details never comes back. */
  private leftDetails = false;
  /** The mode the programs and people were fetched for; one fetch per open. */
  private loadedFor?: OverlayMode;
  /** Sessions annulled from get ready: their done step never shows. */
  private readonly annulled = new Set<number>();
  private idleTimer?: ReturnType<typeof setTimeout>;
  private tickTimer?: ReturnType<typeof setInterval>;
  /** `server_time − Date.now()` of the newest message, in ms. */
  private offset = 0;
  /** The `server_time` the offset was taken from. */
  private stamp?: string;
  /** When the flow last heard the add-on was unreachable (`Date.now()`), while it still is. */
  private unreachableSince?: number;
  private unreachableTimer?: ReturnType<typeof setTimeout>;
  private endQuestion?: EndQuestion;
  /** The session whose done step the 60 s close is armed for. */
  private doneFor?: number;
  private doneTimer?: ReturnType<typeof setTimeout>;
  /** Set once this flow has asked to close; it never asks twice. */
  private closed = false;
  /**
   * The tones scheduled, and those started a moment ago: each one's kind, when it is due (the
   * add-on's epoch ms), when it starts on the audio clock (s), and its cancel.
   */
  private tones: { kind: ToneKind; at: number; when: number; cancel: () => void }[] = [];
  /** What the pending tones were planned from; a change plans them again. */
  private plannedFrom?: { view?: SessionView; offset: number; reachable: boolean; locked: boolean; counting: boolean };
  private stopAudioWatch?: () => void;
  private readonly onActivity = (): void => this.armIdle();

  constructor() {
    super();
    this.selected = new Set();
    this.images = new Map();
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
    .note {
      display: flex;
      gap: 24px;
      align-items: center;
      margin: 16px 0;
      color: var(--secondary-text-color);
    }
    header.top {
      display: flex;
      gap: 32px;
      align-items: center;
      font-size: 1.5rem;
    }
    header.top .elapsed {
      margin-left: auto;
      font-variant-numeric: tabular-nums;
    }
    header.top .end {
      display: flex;
      gap: 16px;
      align-items: center;
    }
    button.slot {
      min-width: 120px;
    }
    .solo,
    .duo {
      display: flex;
      gap: 32px;
      align-items: center;
      justify-content: center;
      margin: 24px 0;
    }
    .now,
    .panel,
    .next {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      text-align: center;
    }
    .now .exercise {
      font-size: 2rem;
      font-weight: 500;
    }
    .panel {
      flex: 1;
      padding: 16px;
      border: 4px solid var(--person-color);
      border-radius: 16px;
    }
    .panel .who {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .panel .name,
    .panel .exercise {
      font-weight: 500;
    }
    .next .label {
      color: var(--secondary-text-color);
      font-weight: 500;
    }
    .gif {
      width: 280px;
      height: 280px;
      border-radius: 16px;
      object-fit: cover;
      background: var(--secondary-background-color, var(--divider-color));
    }
    .duo .gif {
      width: 200px;
      height: 200px;
    }
    .ring {
      position: relative;
      flex: none;
      width: 320px;
      height: 320px;
      cursor: pointer;
    }
    .ring svg {
      width: 100%;
      height: 100%;
    }
    .ring .track {
      stroke: var(--divider-color);
    }
    .ring .left {
      stroke: var(--ring-color);
    }
    .ring .middle {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .ring .word {
      font-size: 1.5rem;
      font-weight: 500;
      letter-spacing: 0.1em;
    }
    .ring .seconds {
      font-size: 6rem;
      font-weight: 500;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }
    .ring .then {
      color: var(--secondary-text-color);
    }
    .controls {
      display: flex;
      gap: 32px;
      align-items: center;
      justify-content: center;
    }
    .big {
      font-size: 2rem;
      font-weight: 500;
    }
  `;

  override connectedCallback(): void {
    super.connectedCallback();
    this.addEventListener("pointerdown", this.onActivity);
    this.addEventListener("click", this.onActivity);
    this.stopAudioWatch = onAudioStateChange(() => this.requestUpdate());
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.removeEventListener("pointerdown", this.onActivity);
    this.removeEventListener("click", this.onActivity);
    this.stopAudioWatch?.();
    this.stopAudioWatch = undefined;
    this.silence();
    this.plannedFrom = undefined;
    this.stopIdle();
    this.stopTick();
    this.endAsk(false);
    clearTimeout(this.unreachableTimer);
    clearTimeout(this.doneTimer);
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("state")) {
      this.watchReach(this.state);
      this.take(this.state?.session ?? undefined);
    }
    if (changed.has("result")) this.take(this.result);
    // A new details mode on the same flow (a Start while a finished view shows) starts over.
    if (changed.has("mode")) this.leftDetails = isActive(this.newest);
    // The controller hands over `hass` on every card update; only a new mode loads again.
    if (changed.has("mode") || (changed.has("hass") && this.loadedFor !== this.mode)) this.load();
  }

  protected override updated(): void {
    const step = this.step();
    if (step === "details") {
      if (!this.idleTimer && !this.busy) this.armIdle();
    } else {
      this.stopIdle();
    }
    const counting = step === "ready" || step === "timer";
    if (counting && this.newest?.status === "running") this.startTick();
    else this.stopTick();
    this.plan(counting);
    if (step !== "timer") this.endAsk(false);
    if (this.hass && step === "timer") this.loadStationImages(this.hass, this.newest!);
    this.armDone(step);
    if (step === "done" && this.newest && this.annulled.has(this.newest.id)) this.close();
  }

  /** Arm the done step's 60 s close once per session; leaving done disarms it. */
  private armDone(step: Step | undefined): void {
    const view = this.newest;
    if (step !== "done" || !view) {
      clearTimeout(this.doneTimer);
      this.doneTimer = undefined;
      this.doneFor = undefined;
      return;
    }
    if (this.doneFor === view.id) return;
    clearTimeout(this.doneTimer);
    this.doneFor = view.id;
    this.doneTimer = setTimeout(() => this.close(), DONE_MS);
  }

  /**
   * Note when the add-on became unreachable: when the controller first learned it, or now. Luk shows
   * 10 s after that, until it is back.
   */
  private watchReach(state: SessionState | undefined): void {
    if (!state || state.available) {
      clearTimeout(this.unreachableTimer);
      this.unreachableTimer = undefined;
      this.unreachableSince = undefined;
      return;
    }
    if (this.unreachableSince !== undefined) return;
    this.unreachableSince = lostAt(state) ?? Date.now();
    const wait = Math.max(0, this.unreachableSince + UNREACHABLE_MS - Date.now());
    this.unreachableTimer = setTimeout(() => this.requestUpdate(), wait);
  }

  private reachable(): boolean {
    return this.state?.available !== false;
  }

  /** Ask the controller to close the overlay: once, and only while this flow is on the page. */
  private close(): void {
    if (this.closed || !this.isConnected) return;
    this.closed = true;
    this.onClose?.();
  }

  /** Keep the newer of the flow's view and `view`: a higher revision, or a newer session. */
  private take(view: SessionView | undefined): void {
    if (!view) return;
    // Every message's stamp corrects the clock, applied or not, as of when the message arrived:
    // a flow opened later gets the controller's last view. A stamp seen before (the controller
    // repeats the last view while refused) is old, so it would set the clock back.
    if (view.server_time !== this.stamp) {
      this.stamp = view.server_time;
      this.offset = Date.parse(view.server_time) - (receivedAt(view) ?? Date.now());
    }
    const newest = this.newest;
    // A late view of an older session can't pull the flow back.
    if (newest && view.id < newest.id) return;
    if (newest && newest.id === view.id && newest.revision >= view.revision) return;
    // An alert belongs to the session it came from.
    if (newest?.id !== view.id) this.error = undefined;
    // The chime plays when this flow sees its session complete, not for a done step shown later.
    if (view.status === "completed" && newest?.id === view.id && isActive(newest) && !audioLocked()) {
      const now = this.now();
      scheduleTone("chime", now, now);
    }
    this.playSkipTone(newest, view);
    this.newest = view;
    if (isActive(view)) this.leftDetails = true;
  }

  /**
   * Fetch the programs and the people for a details mode, and start the choice over. Any other
   * mode fetches the people only, for the colours of the session's participants.
   */
  private load(): void {
    const mode = this.mode;
    const hass = this.hass;
    if (!mode || !hass) return;
    this.loadedFor = mode;
    if (mode.kind !== "details") {
      void hass.callWS<Person[]>({ type: "ha_fitness/people" }).then(
        (people) => {
          if (this.mode === mode) this.people = people;
        },
        () => undefined,
      );
      return;
    }
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
    this.loadImage(hass, exerciseId, "thumbnail");
  }

  private loadImage(hass: Hass, exerciseId: string, kind: ImageKind): void {
    const key = `${kind}/${exerciseId}`;
    if (this.images.has(key)) return;
    // Mark it as asked for, so each update doesn't ask again.
    this.images.set(key, null);
    void imageUrl(hass, exerciseId, kind).then((url) => {
      if (url) this.images = new Map(this.images).set(key, url);
    });
  }

  /** The GIFs of the stations worked at, and with one person, the next station's thumbnail. */
  private loadStationImages(hass: Hass, view: SessionView): void {
    const stations = view.stations ?? [];
    for (const station of stations) this.loadImage(hass, station.current.exercise_id, "gif");
    const next = stations.length === 1 ? stations[0].next : null;
    if (next) this.loadImage(hass, next.exercise_id, "thumbnail");
  }

  /**
   * A participant's colour, by the person's place in people order (design §3.4). Beyond the
   * second person, or before the people have loaded for someone not among them, the theme's.
   */
  private personColor(id: number, participantIndex: number): string {
    const people = this.people;
    const index = people ? people.findIndex((person) => person.id === id) : participantIndex;
    return PERSON_COLORS[index] ?? "var(--primary-color)";
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
      if (this.step() === "details" && !this.busy) this.close();
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
      const result = await hass.callWS<SessionView>({
        type: "ha_fitness/session/command",
        command: "start",
        program_id: program.id,
        participants,
        ...(mode.trainingDayId === undefined ? {} : { training_day_id: mode.trainingDayId }),
      });
      if (this.isConnected) this.result = result;
    } catch (error) {
      if (this.isConnected) this.error = this.t(this.startErrorKey(error));
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
    // Fortsæt is a tap, like Start: unlock before anything awaits.
    if (command === "resume") unlockAudio();
    const hass = this.hass;
    if (!hass) return;
    this.error = undefined;
    try {
      const result = await hass.callWS<SessionView>({ type: "ha_fitness/session/command", command });
      if (this.isConnected) this.result = result;
    } catch (error) {
      if (!this.isConnected) return;
      const code = errorCode(error);
      this.error = this.t(code && KNOWN_ERRORS.has(code) ? `flow.error.${code}` : "flow.error.general");
    }
  }

  /** Annullér: end the session, close at once, and never show its done step. */
  private annul(): void {
    const view = this.newest;
    if (view) this.annulled.add(view.id);
    this.close();
    void this.command("end");
  }

  /**
   * Næste and Forrige start a phase before the old one ran out: its change tone plays now. A phase
   * that started because the old one ran out had its tone at local zero, so it gets none here.
   */
  private playSkipTone(previous: SessionView | undefined, view: SessionView): void {
    const before = previous?.id === view.id ? previous.phase : null;
    const after = view.phase;
    if (!before?.ends_at || !after || after.index === before.index) return;
    if (view.status !== "running" || after.kind === "countdown" || audioLocked()) return;
    const now = this.now();
    if (Date.parse(before.ends_at) <= now) return;
    scheduleTone(after.kind === "work" ? "work" : "rest", now, now);
  }

  /** The add-on's time now, from the local clock and the newest message's offset. */
  private now(): number {
    return Date.now() + this.offset;
  }

  /**
   * The timing core (spec §5.3): the view's phase counted down locally. At local zero it shows the
   * next phase from `next_phase` at its full length, until the message that confirms it. While
   * unreachable, or with no next phase, it holds at zero instead.
   */
  private countdown(view: SessionView): Countdown {
    const phase = view.phase;
    if (!phase) return { kind: "work", duration: 0, seconds: 0, fraction: 0, ahead: false };
    const leftMs =
      phase.ends_at === null
        ? (phase.remaining ?? phase.duration) * 1000
        : Date.parse(phase.ends_at) - this.now();
    const next = view.next_phase;
    if (leftMs <= 0 && view.status === "running" && next && this.reachable()) {
      return { kind: next.kind, duration: next.duration, seconds: next.duration, fraction: 1, ahead: true };
    }
    const left = Math.max(0, leftMs);
    return {
      kind: phase.kind,
      duration: phase.duration,
      seconds: Math.ceil(left / 1000),
      fraction: phase.duration > 0 ? left / (phase.duration * 1000) : 0,
      ahead: false,
    };
  }

  /** The active seconds: `time_trained`, plus the time since `server_time` while running past the countdown. */
  private elapsed(view: SessionView): number {
    const since =
      view.status === "running" && view.phase && view.phase.kind !== "countdown"
        ? Math.max(0, (this.now() - Date.parse(view.server_time)) / 1000)
        : 0;
    return view.time_trained + since;
  }

  /**
   * Plan the tones again when what they depend on changed: the view applied, the clock offset,
   * the reach, the audio lock, or whether a running step shows. The redraws in between leave them.
   */
  private plan(counting: boolean): void {
    const from = {
      view: this.newest,
      offset: this.offset,
      reachable: this.reachable(),
      locked: audioLocked(),
      counting,
    };
    const last = this.plannedFrom;
    if (
      last &&
      last.view === from.view &&
      last.offset === from.offset &&
      last.reachable === from.reachable &&
      last.locked === from.locked &&
      last.counting === from.counting
    ) {
      return;
    }
    this.plannedFrom = from;
    // What has started is judged on the audio clock, which a clock correction doesn't move.
    const pending = this.tones.filter((tone) => tone.when > audioTime());
    this.silence();
    const started = this.tones;
    const view = from.view;
    if (!counting || from.locked || view?.status !== "running") return;
    const now = this.now();
    for (const [kind, at] of this.tonesOf(view)) {
      const same = (tone: { kind: ToneKind; at: number }) => tone.kind === kind && tone.at === at;
      // A tone that has started isn't played again. One that was waiting still plays, at once if
      // the corrected clock says its time has passed.
      if (started.some(same) || (at <= now && !pending.some(same))) continue;
      const cancel = scheduleTone(kind, at, now);
      this.tones.push({ kind, at, when: cancel.when, cancel });
    }
  }

  /**
   * The current phase's tones (spec §5.4): a beep at 5 to 1 s left, none in the phase's first
   * 0.3 s, and the next phase's change tone at local zero. While unreachable the ring holds at
   * zero, so no change tone.
   */
  private tonesOf(view: SessionView): [ToneKind, number][] {
    const phase = view.phase;
    if (!phase?.ends_at) return [];
    const end = Date.parse(phase.ends_at);
    const start = end - phase.duration * 1000;
    const tones: [ToneKind, number][] = [];
    for (let left = BEEP_SECONDS; left >= 1; left--) {
      const at = end - left * 1000;
      if (at >= start + QUIET_MS) tones.push(["beep", at]);
    }
    const next = view.next_phase;
    if (next && this.reachable()) tones.push([next.kind === "work" ? "work" : "rest", end]);
    return tones;
  }

  /**
   * Cancel the tones still ahead on the audio clock; one already playing finishes. The ones that
   * started in the last few seconds are kept, so a plan made right after can't play them twice.
   */
  private silence(): void {
    const now = audioTime();
    for (const tone of this.tones) if (tone.when > now) tone.cancel();
    this.tones = this.tones.filter((tone) => tone.when <= now && tone.when > now - STARTED_S);
  }

  /** "Tryk for lyd": unlock in the tap, then plan the tones with sound. */
  private tapForSound(): void {
    unlockAudio();
    this.requestUpdate();
  }

  /** The "Tryk for lyd" button, while no sound can play. */
  private renderSound() {
    // With no Web Audio at all, no tap could bring sound.
    if (!audioSupported() || !audioLocked()) return nothing;
    return html`<button class="sound" @click=${() => this.tapForSound()}>${this.t("flow.tap_for_sound")}</button>`;
  }

  /** Slut's first tap asks; Ja counts only after 0.5 s, and the question goes after 10 s. */
  private askEnd(): void {
    this.endAsk(false);
    const question: EndQuestion = { armed: false, timers: [] };
    question.timers.push(
      setTimeout(() => {
        question.armed = true;
      }, ARM_MS),
      setTimeout(() => this.endAsk(), CONFIRM_MS),
    );
    this.endQuestion = question;
    this.requestUpdate();
  }

  /** Drop Slut's question; `redraw` false when called from an update. */
  private endAsk(redraw = true): void {
    const question = this.endQuestion;
    if (!question) return;
    question.timers.forEach(clearTimeout);
    this.endQuestion = undefined;
    if (redraw) this.requestUpdate();
  }

  private confirmEnd(): void {
    if (!this.endQuestion?.armed) return;
    this.endAsk();
    void this.command("end");
  }

  /** The unreachable note, and Luk once it has lasted 10 s. */
  private renderReach() {
    if (this.reachable()) return nothing;
    const since = this.unreachableSince;
    const luk = since !== undefined && Date.now() - since >= UNREACHABLE_MS;
    return html`
      <div class="note">
        <span role="status">${this.t("flow.unreachable")}</span>
        ${luk ? html`<button @click=${() => this.close()}>${this.t("flow.close")}</button>` : nothing}
      </div>
    `;
  }

  private renderError() {
    return this.error ? html`<div class="error" role="alert">${this.error}</div>` : nothing;
  }

  private renderThumbnail(station: { exercise_id: string; name: string }) {
    return this.renderImage(station, "thumbnail", "thumb");
  }

  /** An exercise's image, or a neutral placeholder while it loads or when it has none. */
  private renderImage(station: { exercise_id: string; name: string }, kind: ImageKind, className: string) {
    const url = this.images.get(`${kind}/${station.exercise_id}`);
    return url
      ? html`<img class=${className} src=${url} alt=${station.name} />`
      : html`<span class=${className} role="img" aria-label=${station.name}></span>`;
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
    return html`<button @click=${() => this.close()}>${this.t("flow.back")}</button>`;
  }

  private renderReady(view: SessionView) {
    const paused = view.status === "paused";
    return html`
      <h2>${view.program_name}</h2>
      ${this.renderReach()} ${this.renderSound()}
      <div class="count">${this.renderReadyCount(view)}</div>
      <ul class="starts" aria-label=${this.t("flow.get_ready")}>
        ${view.participants.map((person, index) => {
          const station = view.stations?.[index]?.current;
          return html`
            <li style="--person-color: ${this.personColor(person.id, index)}">
              <span class="badge"></span>
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

  /** The countdown's seconds; at local zero, the word of the phase that follows. */
  private renderReadyCount(view: SessionView) {
    const countdown = this.countdown(view);
    return countdown.ahead ? this.t(`flow.phase.${countdown.kind}`) : countdown.seconds;
  }

  private renderTimer(view: SessionView) {
    const phase = view.phase!;
    const paused = view.status === "paused";
    const countdown = this.countdown(view);
    const word = this.t(`flow.phase.${paused ? "paused" : countdown.kind}`);
    const next = view.next_phase;
    const then =
      next && !countdown.ahead ? this.t(`flow.then.${next.kind}`, { seconds: next.duration }) : undefined;
    const theRing = ring({
      label: word,
      word,
      max: countdown.duration,
      value: countdown.seconds,
      fraction: countdown.fraction,
      color: RING_COLORS[countdown.kind],
      then,
      onTap: () => {
        if (this.newest?.status === "running") void this.command("pause");
      },
    });
    const stations = view.stations ?? [];
    return html`
      ${this.renderHeader(view, phase.round, phase.interval)} ${this.renderReach()} ${this.renderSound()}
      ${this.renderError()}
      ${stations.length === 1
        ? this.renderSolo(view, theRing)
        : html`<div class="duo">${this.renderPanel(view, 0)} ${theRing} ${this.renderPanel(view, 1)}</div>`}
      <div class="controls">
        <button @click=${() => this.command("previous")}>${this.t("flow.previous")}</button>
        <button class="main" @click=${() => this.command(paused ? "resume" : "pause")}>
          ${this.t(paused ? "flow.resume" : "flow.pause")}
        </button>
        <button @click=${() => this.command("next")}>${this.t("flow.next")}</button>
      </div>
    `;
  }

  /** Runde, Interval, the elapsed time against the planned, and Slut with its question. */
  private renderHeader(view: SessionView, round: number, interval: number) {
    const question = this.endQuestion;
    return html`
      <header class="top">
        <span>${this.t("flow.round", { round, rounds: view.totals.rounds })}</span>
        <span>
          ${view.totals.stations === undefined
            ? this.t("flow.interval", { interval })
            : this.t("flow.interval_of", { interval, intervals: view.totals.stations })}
        </span>
        <span class="elapsed">
          ${this.t("flow.elapsed", { elapsed: clock(this.elapsed(view)), planned: clock(view.totals.planned) })}
        </span>
        <span class="end">
          ${question
            ? html`
                <span class="question">${this.t("flow.end_confirm")}</span>
                <button @click=${() => this.confirmEnd()}>${this.t("flow.yes")}</button>
                <button class="slot" @click=${() => this.endAsk()}>${this.t("flow.no")}</button>
              `
            : html`<button class="slot" @click=${() => this.askEnd()}>${this.t("flow.end")}</button>`}
        </span>
      </header>
    `;
  }

  /** One person: the current station big with its GIF, the ring, and Næste beside them. */
  private renderSolo(view: SessionView, theRing: TemplateResult) {
    const station = view.stations![0];
    const person = view.participants[0];
    return html`
      <div class="solo">
        <section class="now" aria-label=${person?.name ?? ""}>
          ${this.renderImage(station.current, "gif", "gif")}
          <span class="station">${this.t("flow.station", { number: station.current.number })}</span>
          <span class="exercise">${station.current.name}</span>
        </section>
        ${theRing} ${station.next ? this.renderNext(station.next) : nothing}
      </div>
    `;
  }

  private renderNext(next: SessionStation) {
    const label = this.t("flow.next_label");
    return html`
      <section class="next" aria-label=${label}>
        <span class="label">${label}</span>
        ${this.renderThumbnail(next)}
        <span>${this.t("flow.station", { number: next.number })}</span>
        <span>${next.name}</span>
      </section>
    `;
  }

  /** A person's panel in the two-person layout, in the person's colour. */
  private renderPanel(view: SessionView, index: number) {
    const person = view.participants[index];
    const station = view.stations?.[index];
    if (!person || !station) return nothing;
    return html`
      <section class="panel" aria-label=${person.name} style="--person-color: ${this.personColor(person.id, index)}">
        <div class="who">
          <span class="badge"></span>
          <span class="name">${person.name}</span>
          <span class="station">${this.t("flow.station", { number: station.current.number })}</span>
        </div>
        ${this.renderImage(station.current, "gif", "gif")}
        <span class="exercise">${station.current.name}</span>
        ${station.next
          ? html`<span class="line">
              ${this.t("flow.next_station", { number: station.next.number, exercise: station.next.name })}
            </span>`
          : nothing}
      </section>
    `;
  }

  private renderDone(view: SessionView) {
    if (!view.counted) {
      return html`
        <h2>${this.t("flow.done.ended")}</h2>
        <div class="actions">
          <button class="main" @click=${() => this.close()}>${this.t("flow.close")}</button>
        </div>
      `;
    }
    return html`
      <h2>${this.t("flow.done.counted")}</h2>
      <p class="line">
        <span>${this.t("flow.done.time")}</span>
        <span class="big">${clock(view.time_trained)}</span>
      </p>
      <p class="big">${this.t("flow.done.rounds", { done: view.rounds_completed, rounds: view.totals.rounds })}</p>
      <ul class="starts" aria-label=${this.t("flow.done.who")}>
        ${view.participants.map(
          (person, index) => html`
            <li style="--person-color: ${this.personColor(person.id, index)}">
              <span class="badge"></span>${person.name}
            </li>
          `,
        )}
      </ul>
      <div class="actions">
        <button class="main" @click=${() => this.close()}>${this.t("flow.close")}</button>
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
