import { type Connection, WsSubscription } from "./today-data";

/** A station a participant is at, or moves to next (spec §3.1). */
export interface SessionStation {
  number: number;
  exercise_id: string;
  name: string;
}

export type PhaseKind = "countdown" | "work" | "switch" | "rest";

/** The phase a session is in (spec §3.5). */
export interface SessionPhase {
  index: number;
  kind: PhaseKind;
  round: number;
  interval: number;
  /** The phase's length in seconds. */
  duration: number;
  /** UTC ISO with milliseconds; null while paused or finished. */
  ends_at: string | null;
  /** The seconds left, set while paused. */
  remaining: number | null;
}

/** The add-on's session view (spec §3.5), as `ha_fitness/session/subscribe` sends it (spec §4). */
export interface SessionView {
  id: number;
  revision: number;
  status: "running" | "paused" | "completed" | "ended";
  counted: boolean;
  program_name: string;
  training_day_id: number | null;
  participants: { id: number; name: string }[];
  phase: SessionPhase | null;
  next_phase: { kind: PhaseKind; duration: number } | null;
  /** One per participant, in participant order. */
  stations: { current: SessionStation; next: SessionStation | null }[] | null;
  /** `stations` is the intervals per round; older add-ons leave it out. */
  totals: { planned: number; rounds: number; stations?: number };
  /** The start of the first work phase; null during the countdown, before work began. */
  started_at: string | null;
  ended_at: string | null;
  rounds_completed: number;
  /** Active seconds, as of `server_time`. */
  time_trained: number;
  /** The sender's UTC ISO time with milliseconds. */
  server_time: string;
  /** How a completed session felt (UI refresh spec §3.3); null until rated, absent from an older add-on. */
  feeling?: Feeling | null;
}

/** The answers to "How did it feel?" (UI refresh spec §3.3). */
export type Feeling = "too_easy" | "just_right" | "too_hard";

/** The music of the session, as `ha_fitness/session/subscribe` sends it (music spec §5.4). */
export interface MusicState {
  playlist_name: string;
  speaker: string;
  speaker_name: string;
  state: "waiting" | "playing" | "paused" | "unavailable";
}

/**
 * What `ha_fitness/session/subscribe` sends: the add-on's reachability, the session view and its
 * music. `music` is null without music; an integration older than music leaves it out.
 */
export interface SessionState {
  available: boolean;
  session: SessionView | null;
  music?: MusicState | null;
}

/** A session is active while it runs or is paused; a finished view (kept 5 minutes) is not. */
export function isActive(session: SessionView | null | undefined): session is SessionView {
  return session?.status === "running" || session?.status === "paused";
}

/**
 * How the flow opens: the details of a program (from a card's Start), or the running session.
 * `language` is the opening card's `language` option, if it has one; the flow then uses it too.
 */
export type OverlayMode =
  | { kind: "details"; programId: number; trainingDayId?: number; language?: string }
  | { kind: "resume"; language?: string };

/** The part of Home Assistant's `hass` object the controller uses. */
export interface OverlayHass {
  connection?: Connection;
}

/**
 * The properties the controller sets on the flow element. The flow never subscribes to the session
 * itself; it subscribes to the stats only, while its done step shows.
 */
interface FlowElement extends HTMLElement {
  hass?: unknown;
  state?: SessionState;
  mode?: OverlayMode;
  onClose?: () => void;
}

const FLOW_TAG = "ha-fitness-workout-flow";

/**
 * The dialog sits in the page's light DOM, where no card's styles reach, so it carries its own:
 * the whole viewport, with none of the browser's dialog defaults (size, border, padding). The
 * second `height` wins where `dvh` is known, so a tablet's browser bars don't cut it off.
 */
const DIALOG_STYLE = [
  "position: fixed",
  "inset: 0",
  "width: 100%",
  "height: 100%",
  "height: 100dvh",
  "max-width: none",
  "max-height: none",
  "margin: 0",
  "padding: 0",
  "border: none",
  "box-sizing: border-box",
  "background: var(--primary-background-color, #fafafa)",
  "color: var(--primary-text-color, #212121)",
  "overflow: auto",
].join("; ");

// The page-wide controller (spec §5.1). Cards hand it `hass` and ask it to open or close; the
// overlay outlives the card that opened it.
let hass: OverlayHass | undefined;
let current: SessionState = { available: false, session: null, music: null };
const listeners = new Set<(state: SessionState) => void>();
let dialog: HTMLDialogElement | undefined;
let flow: FlowElement | undefined;
let savedOverflow = "";
/** When each view arrived (`Date.now()`); a flow opened later counts from that, not from the hand-over. */
const arrivals = new WeakMap<SessionView, number>();
/** For each unavailable state, when the controller first learned the add-on was gone (`Date.now()`). */
const losses = new WeakMap<SessionState, number>();

const subscription = new WsSubscription<SessionState>("ha_fitness/session/subscribe", (message) => {
  // A refused subscription counts as unreachable; like the integration, it keeps the last view so
  // the flow can keep counting down. The music's state is unknown then, so it shows no player.
  receive(message ?? { available: false, session: current.session, music: null });
});

function receive(next: SessionState): void {
  // The refused path repeats the last view object; it keeps its first arrival.
  if (next.session && !arrivals.has(next.session)) arrivals.set(next.session, Date.now());
  // An outage starts at its first unavailable message; the ones after it carry that time on.
  if (!next.available) losses.set(next, (!current.available ? losses.get(current) : undefined) ?? Date.now());
  current = next;
  if (flow) flow.state = next;
  for (const listener of [...listeners]) listener(next);
}

/** The connection whose drop the controller watches. */
let watched: Connection | undefined;

/**
 * HA's websocket dropped: the integration can't send `available: false` then, so the controller
 * does, with the last view, until the integration's first message after `ready` (spec §5.3).
 */
function onDisconnected(): void {
  if (current.available) receive({ available: false, session: current.session, music: null });
}

function watch(connection: Connection | undefined): void {
  if (!connection || connection === watched) return;
  watched?.removeEventListener?.("disconnected", onDisconnected);
  watched = connection;
  connection.addEventListener?.("disconnected", onDisconnected);
}

/** Hand the controller the newest `hass`. Every card calls this on each change; the first subscribes. */
export function setHass(next: OverlayHass): void {
  hass = next;
  if (flow) flow.hass = next;
  watch(next.connection);
  subscription.connect(next.connection);
}

/** The latest message of `ha_fitness/session/subscribe`; unavailable with no session before the first. */
export function state(): SessionState {
  return current;
}

/** The local time (`Date.now()`) the controller received `view`, or undefined for a view it never had. */
export function receivedAt(view: SessionView): number | undefined {
  return arrivals.get(view);
}

/** The local time (`Date.now()`) the outage `state` belongs to began, or undefined for a state it never had. */
export function lostAt(state: SessionState): number | undefined {
  return losses.get(state);
}

/** Call `listener` with every new state. Returns the unsubscribe. */
export function subscribe(listener: (state: SessionState) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Open the overlay in `mode`, or switch the open one to it. */
export function open(mode: OverlayMode): void {
  // A dialog someone else took off the page counts as gone. The page still has the overflow this
  // controller set, so the one saved when it opened stays.
  const replacing = dialog !== undefined && !dialog.isConnected;
  if (replacing) {
    dialog?.removeEventListener("close", reopen);
    dialog = undefined;
    flow = undefined;
  }
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.style.cssText = DIALOG_STYLE;
    // Escape and the Android back gesture must not close it; Chrome honours `closedby`.
    dialog.setAttribute("closedby", "none");
    dialog.addEventListener("cancel", (event) => event.preventDefault());
    dialog.addEventListener("close", reopen);
    flow = document.createElement(FLOW_TAG) as FlowElement;
    flow.onClose = close;
    dialog.append(flow);
    document.body.append(dialog);
    if (!replacing) savedOverflow = document.documentElement.style.overflow;
    document.documentElement.style.overflow = "hidden";
  }
  if (flow) {
    flow.hass = hass;
    flow.state = current;
    flow.mode = mode;
  }
  if (!dialog.open) dialog.showModal();
}

/** A close the controller didn't ask for (a browser closing it anyway) opens the dialog again. */
function reopen(this: HTMLDialogElement): void {
  if (this === dialog && this.isConnected) this.showModal();
}

/** Close and remove the overlay, and let the page scroll again. */
export function close(): void {
  const closing = dialog;
  if (!closing) return;
  dialog = undefined;
  flow = undefined;
  closing.removeEventListener("close", reopen);
  closing.close();
  closing.remove();
  document.documentElement.style.overflow = savedOverflow;
}
