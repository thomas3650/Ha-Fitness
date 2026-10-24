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
  started_at: string;
  ended_at: string | null;
  rounds_completed: number;
  /** Active seconds, as of `server_time`. */
  time_trained: number;
  /** The sender's UTC ISO time with milliseconds. */
  server_time: string;
}

/** What `ha_fitness/session/subscribe` sends: the add-on's reachability and the session view. */
export interface SessionState {
  available: boolean;
  session: SessionView | null;
}

/** A session is active while it runs or is paused; a finished view (kept 5 minutes) is not. */
export function isActive(session: SessionView | null | undefined): session is SessionView {
  return session?.status === "running" || session?.status === "paused";
}

/** How the flow opens: the details of a program (from a card's Start), or the running session. */
export type OverlayMode =
  | { kind: "details"; programId: number; trainingDayId?: number }
  | { kind: "resume" };

/** The part of Home Assistant's `hass` object the controller uses. */
export interface OverlayHass {
  connection?: Connection;
}

/** The properties the controller sets on the flow element; the flow never subscribes itself. */
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
let current: SessionState = { available: false, session: null };
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
  // the flow can keep counting down.
  receive(message ?? { available: false, session: current.session });
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

/** Hand the controller the newest `hass`. Every card calls this on each change; the first subscribes. */
export function setHass(next: OverlayHass): void {
  hass = next;
  if (flow) flow.hass = next;
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
