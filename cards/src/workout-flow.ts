import { LitElement, type PropertyValues, html, nothing } from "lit";

import {
  type ToneKind,
  audioLocked,
  audioSupported,
  audioTime,
  onAudioStateChange,
  scheduleTone,
  unlockAudio,
} from "./audio";
import { type DetailsContext, type Person, type Program, detailsStyles, renderDetails } from "./flow/details";
import { type DoneContext, type Streak, doneStyles, renderDone } from "./flow/done";
import { type ReadyContext, readyStyles, renderReady } from "./flow/ready";
import { type Countdown, type ImageOf, type ReachNote, type SoundButton, renderBack, sharedStyles } from "./flow/shared";
import { type TimerContext, renderTimer, timerStyles } from "./flow/timer";
import { type Vars, localize } from "./i18n";
import { type ImageHass, type ImageKind, imageUrl } from "./images";
import { type LanguageHass, cardLanguage } from "./language";
import {
  type Feeling,
  type OverlayMode,
  type SessionState,
  type SessionView,
  isActive,
  lostAt,
  receivedAt,
} from "./overlay";
import { personColor } from "./people";
import type { StatsMessage } from "./stats-card";
import { type Connection, WsSubscription } from "./today-data";

/** The part of Home Assistant's `hass` object the flow uses. */
interface Hass extends LanguageHass, ImageHass {
  callWS<T>(message: { type: string } & Record<string, unknown>): Promise<T>;
  connection?: Connection;
}

type Command = "pause" | "resume" | "next" | "previous" | "end";
type Step = "details" | "ready" | "timer" | "done";

declare global {
  interface HTMLElementTagNameMap {
    "ha-fitness-workout-flow": WorkoutFlow;
  }
}

const TAG = "ha-fitness-workout-flow";
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
/** A running phase whose end moves later by more than this was started again (Forrige), in ms. */
const RESTART_MS = 500;
/** How long a started tone is remembered, so a new plan doesn't play it again (seconds). */
const STARTED_S = 2;
/** No beep falls this soon after a phase starts, where it would clash with the change tone. */
const QUIET_MS = 300;

/** Slut's question. */
interface EndQuestion {
  armed: boolean;
  timers: ReturnType<typeof setTimeout>[];
}
/** The command errors with a text of their own; any other gets the general text. */
const KNOWN_ERRORS = new Set(["not_found", "invalid", "unavailable"]);
/** The feeling command's errors with a text of their own; any other gets the general text. */
const FEELING_ERRORS = new Set(["conflict", "invalid", "unavailable"]);

/** The ws error code of a rejected `callWS`, which rejects with `{code, message}`. */
function errorCode(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : undefined;
}

/**
 * The workout flow in the overlay (spec §5.2): details, get ready, the timer and done. The overlay
 * controller hands it `hass`, the live session state, the mode and `onClose`; it never subscribes
 * to the session itself. While done shows, it subscribes to the stats, for the streak tile.
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
    stats: { state: true },
    feelingError: { state: true },
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
  /** The last stats message while done shows: nothing yet, or null while the subscription is refused. */
  declare stats?: StatsMessage | null;
  /** The text of a failed feeling tap. */
  declare feelingError?: string;

  /** The newest view the flow has seen, from a push or a command result. */
  private newest?: SessionView;
  /** Set once this flow has started a session, or shown one: details never comes back. */
  private leftDetails = false;
  /** The mode the programs and people were fetched for; one fetch per open. */
  private loadedFor?: OverlayMode;
  /** Sessions annulled from get ready: their done step never shows. */
  private readonly annulled = new Set<number>();
  /** Annullér's end is on its way. */
  private annulling = false;
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
  private readonly statsSubscription = new WsSubscription<StatsMessage>("ha_fitness/stats/subscribe", (message) => {
    this.stats = message;
  });

  constructor() {
    super();
    this.selected = new Set();
    this.images = new Map();
    this.busy = false;
  }

  static override styles = [sharedStyles, detailsStyles, readyStyles, timerStyles, doneStyles];

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
    this.statsSubscription.disconnect();
    this.stats = undefined;
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
    this.watchStats(this.step());
  }

  /**
   * The stats subscription is held while done shows a counted session, for the streak tile; an
   * uncounted end shows no streak. Leaving done drops it.
   */
  private watchStats(step: Step | undefined): void {
    if (step === "done" && this.newest?.counted) {
      this.statsSubscription.connect(this.hass?.connection);
      return;
    }
    this.statsSubscription.disconnect();
    if (this.stats !== undefined) this.stats = undefined;
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
    if (this.hass && (step === "ready" || step === "timer")) this.loadStationImages(this.hass, this.newest!);
    // Get ready's cards show the start stations' thumbnails.
    if (this.hass && step === "ready") {
      for (const station of this.newest!.stations ?? []) this.loadThumbnail(this.hass, station.current.exercise_id);
    }
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
    this.doneFor = view.id;
    this.restartDone();
  }

  /** Start the done step's 60 s close (again). */
  private restartDone(): void {
    clearTimeout(this.doneTimer);
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
    if (newest?.id !== view.id) {
      this.error = undefined;
      this.feelingError = undefined;
    }
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

  /**
   * The GIFs of the stations worked at (during get ready, the start stations), and ahead of time
   * the next stations', so a phase doesn't start with a blank image. With one person, also the next
   * station's thumbnail.
   */
  private loadStationImages(hass: Hass, view: SessionView): void {
    const stations = view.stations ?? [];
    for (const station of stations) this.loadImage(hass, station.current.exercise_id, "gif");
    for (const station of stations) if (station.next) this.loadImage(hass, station.next.exercise_id, "gif");
    const next = stations.length === 1 ? stations[0].next : null;
    if (next) this.loadImage(hass, next.exercise_id, "thumbnail");
  }

  /**
   * A participant's colour, by the person's place in people order (design §3.4). Beyond the
   * second person, or before the people have loaded for someone not among them, the theme's.
   */
  private participantColor(id: number, participantIndex: number): string {
    const people = this.people;
    return personColor(people ? people.findIndex((person) => person.id === id) : participantIndex);
  }

  /** The colours of the view's participants, in their order. */
  private participantColors(view: SessionView): string[] {
    return view.participants.map((person, index) => this.participantColor(person.id, index));
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
    // The opening card's language option wins, as on the card itself (D38).
    return localize(cardLanguage({ language: this.mode?.language }, this.hass), key, vars);
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

  /**
   * Send a command to the running session; its result is a view like any push. True once it went
   * through; a failure shows its text.
   */
  private async command(command: Command): Promise<boolean> {
    // Fortsæt is a tap, like Start: unlock before anything awaits.
    if (command === "resume") unlockAudio();
    const hass = this.hass;
    if (!hass) return false;
    this.error = undefined;
    try {
      const result = await hass.callWS<SessionView>({ type: "ha_fitness/session/command", command });
      if (this.isConnected) this.result = result;
      return true;
    } catch (error) {
      if (!this.isConnected) return false;
      const code = errorCode(error);
      this.error = this.t(code && KNOWN_ERRORS.has(code) ? `flow.error.${code}` : "flow.error.general");
      return false;
    }
  }

  /**
   * "How did it feel?": send the answer; the mark follows the view it returns. A tap starts the
   * 60 s close over, whether it goes through or not; a failure shows its text under the buttons.
   */
  private async sendFeeling(feeling: Feeling): Promise<void> {
    const hass = this.hass;
    if (!hass) return;
    if (this.doneTimer) this.restartDone();
    this.feelingError = undefined;
    try {
      const result = await hass.callWS<SessionView>({ type: "ha_fitness/session/command", command: "feeling", feeling });
      if (this.isConnected) this.result = result;
    } catch (error) {
      if (!this.isConnected) return;
      const code = errorCode(error);
      this.feelingError = this.t(`flow.done.feeling_error.${code && FEELING_ERRORS.has(code) ? code : "general"}`);
    }
  }

  /** The participants' streaks from the stats, matched by person id, in participant order. */
  private streaks(view: SessionView): Streak[] {
    const stats = this.stats;
    if (!stats?.available || !stats.stats) return [];
    const people = stats.stats.people;
    return view.participants.flatMap((participant, index) => {
      const person = people.find((candidate) => candidate.id === participant.id);
      return person
        ? [{ name: participant.name, streak: person.streak, color: this.participantColor(participant.id, index) }]
        : [];
    });
  }

  /**
   * Annullér: end the session, close once the end has gone through, and never show its done step.
   * A failed end leaves the session running, so the flow stays on get ready with the error: closed,
   * the session would run on and count a workout nobody did.
   */
  private async annul(): Promise<void> {
    const view = this.newest;
    if (!view || this.annulling) return;
    this.annulling = true;
    this.annulled.add(view.id);
    const ended = await this.command("end");
    this.annulling = false;
    if (ended) this.close();
    else this.annulled.delete(view.id);
  }

  /**
   * Næste and Forrige start a phase before the old one ran out: its change tone plays now. That
   * includes Forrige restarting the running phase, which keeps its index, ends later and has its
   * whole length left. A phase that started because the old one ran out had its tone at local
   * zero, so it gets none here.
   * Nothing plays while paused.
   */
  private playSkipTone(previous: SessionView | undefined, view: SessionView): void {
    const before = previous?.id === view.id ? previous.phase : null;
    const after = view.phase;
    if (!before?.ends_at || !after) return;
    // A pause and resume the flow never saw also moves the end later; a restart has, per the
    // view, its whole length still ahead.
    const restarted =
      after.index === before.index &&
      after.ends_at !== null &&
      Date.parse(after.ends_at) - Date.parse(before.ends_at) > RESTART_MS &&
      Date.parse(after.ends_at) - Date.parse(view.server_time) >= after.duration * 1000 - RESTART_MS;
    if (after.index === before.index && !restarted) return;
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

  /** The "Tryk for lyd" button: shown while no sound can play, but a tap could bring it. */
  private sound(): SoundButton {
    // With no Web Audio at all, no tap could bring sound.
    return { shown: audioSupported() && audioLocked(), onTap: () => this.tapForSound() };
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
  private reach(): ReachNote {
    const since = this.unreachableSince;
    return {
      reachable: this.reachable(),
      canClose: since !== undefined && Date.now() - since >= UNREACHABLE_MS,
      onClose: () => this.close(),
    };
  }

  private readonly imageOf: ImageOf = (exerciseId, kind) => this.images.get(`${kind}/${exerciseId}`);

  private readonly texts = (key: string, vars?: Vars): string => this.t(key, vars);

  private detailsContext(): DetailsContext {
    return {
      t: this.texts,
      programs: this.programs,
      program: this.program(),
      people: this.people ?? [],
      selected: this.selected,
      maxSelected: this.maxSelected(),
      busy: this.busy,
      error: this.error,
      imageOf: this.imageOf,
      onToggle: (person) => this.toggle(person),
      onStart: () => void this.start(),
      onBack: () => this.close(),
    };
  }

  private readyContext(view: SessionView): ReadyContext {
    return {
      t: this.texts,
      view,
      countdown: this.countdown(view),
      colors: this.participantColors(view),
      imageOf: this.imageOf,
      reach: this.reach(),
      sound: this.sound(),
      error: this.error,
      onStartNow: () => void this.command("next"),
      onResume: () => void this.command("resume"),
      onCancel: () => void this.annul(),
    };
  }

  private timerContext(view: SessionView): TimerContext {
    return {
      t: this.texts,
      view,
      countdown: this.countdown(view),
      elapsed: this.elapsed(view),
      colors: this.participantColors(view),
      imageOf: this.imageOf,
      reach: this.reach(),
      sound: this.sound(),
      error: this.error,
      asking: this.endQuestion !== undefined,
      // The ring is a pointer shortcut: a tap pauses while running and resumes while paused.
      onRingTap: () => {
        const status = this.newest?.status;
        if (status === "running") void this.command("pause");
        else if (status === "paused") void this.command("resume");
      },
      onPrevious: () => void this.command("previous"),
      onPause: () => void this.command("pause"),
      onResume: () => void this.command("resume"),
      onNext: () => void this.command("next"),
      onAskEnd: () => this.askEnd(),
      onConfirmEnd: () => this.confirmEnd(),
      onKeepGoing: () => this.endAsk(),
    };
  }

  private doneContext(view: SessionView): DoneContext {
    return {
      t: this.texts,
      view,
      streaks: this.streaks(view),
      feelingError: this.feelingError,
      onFeeling: (feeling) => void this.sendFeeling(feeling),
      onClose: () => this.close(),
    };
  }

  protected override render() {
    // The timer, details and get ready use the wide page; done one centred column with centred text.
    const step = this.step();
    const layout = step === "done" || step === undefined ? "column centred" : "";
    return html`<div class="page ${layout}">${this.renderStep()}</div>`;
  }

  private renderStep() {
    const view = this.newest;
    switch (this.step()) {
      case "details":
        return renderDetails(this.detailsContext());
      case "ready":
        return renderReady(this.readyContext(view!));
      case "timer":
        return renderTimer(this.timerContext(view!));
      case "done":
        return view && this.annulled.has(view.id) ? nothing : renderDone(this.doneContext(view!));
      default:
        // No session to show (a Fortsæt after the session was gone): only a way out.
        return html`<div class="actions">${renderBack(this.texts, () => this.close())}</div>`;
    }
  }
}

/** Define the flow element; `index.ts` calls this once HA has booted. */
export function registerWorkoutFlow(): void {
  if (!customElements.get(TAG)) customElements.define(TAG, WorkoutFlow);
}
