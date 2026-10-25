/** The workout's sounds (spec §5.4): short sine tones from the Web Audio API, no sound files. */
export type ToneKind = "beep" | "work" | "rest" | "chime";

/** One note: its frequency in Hz, its offset from the tone's start and its length, in seconds. */
interface Note {
  frequency: number;
  offset: number;
  length: number;
}

const TONES: Record<ToneKind, Note[]> = {
  // A short beep for the last 5 seconds of a phase.
  beep: [{ frequency: 880, offset: 0, length: 0.12 }],
  // One long, higher beep of about a second when work starts.
  work: [{ frequency: 1320, offset: 0, length: 1.0 }],
  // A lower tone when a switch or rest starts.
  rest: [{ frequency: 523, offset: 0, length: 0.45 }],
  // Three rising tones when the session completes.
  chime: [
    { frequency: 659, offset: 0, length: 0.2 },
    { frequency: 784, offset: 0.22, length: 0.2 },
    { frequency: 1047, offset: 0.44, length: 0.4 },
  ],
};

const VOLUME = 0.3;
const RAMP = 0.01;

// One context for the page. The browser allows sound only after a gesture.
let context: AudioContext | undefined;
const stateListeners = new Set<() => void>();

function onStateChange(): void {
  for (const listener of [...stateListeners]) listener();
}

/**
 * Create or resume the page's audio context. Call it synchronously in a tap handler (Start,
 * Fortsæt), before anything awaits.
 */
export function unlockAudio(): void {
  if (!context) {
    const Context = globalThis.AudioContext as typeof AudioContext | undefined;
    if (!Context) return;
    context = new Context();
    context.addEventListener("statechange", onStateChange);
  }
  // Not only "suspended": Safari can also leave a context "interrupted".
  if (context.state !== "running") void context.resume().catch(() => undefined);
}

/**
 * Call `listener` each time the page's audio context changes state, so `audioLocked()` can be
 * checked again. It also hears a context made after the call. Returns the unsubscribe.
 */
export function onAudioStateChange(listener: () => void): () => void {
  stateListeners.add(listener);
  return () => {
    stateListeners.delete(listener);
  };
}

/** True while no sound can play: never unlocked, suspended again, or no Web Audio. */
export function audioLocked(): boolean {
  return !context || context.state !== "running";
}

/** False in a browser with no Web Audio at all, where no tap can bring sound. */
export function audioSupported(): boolean {
  return context !== undefined || typeof globalThis.AudioContext === "function";
}

/** The page's audio clock now, in seconds; 0 before there is a context. */
export function audioTime(): number {
  return context?.currentTime ?? 0;
}

/** A scheduled tone's cancel, with its start on the audio clock (`audioTime()`); never, with no context. */
export type ToneCancel = (() => void) & { when: number };

/**
 * Play `kind` at the epoch time `atEpochMs`, given that it is `nowEpochMs` now. A time already
 * passed plays at once. Returns the cancel, which silences the tone if it has not finished, and
 * carries the tone's start on the audio clock.
 */
export function scheduleTone(kind: ToneKind, atEpochMs: number, nowEpochMs: number): ToneCancel {
  const ctx = context;
  if (!ctx) return Object.assign(() => undefined, { when: Number.POSITIVE_INFINITY });
  const when = Math.max(ctx.currentTime, ctx.currentTime + (atEpochMs - nowEpochMs) / 1000);
  const oscillators = TONES[kind].map((note) => play(ctx, note, when + note.offset));
  const cancel = () => {
    for (const oscillator of oscillators) {
      try {
        oscillator.stop();
        oscillator.disconnect();
      } catch {
        // Already stopped; nothing left to silence.
      }
    }
  };
  return Object.assign(cancel, { when });
}

function play(ctx: AudioContext, note: Note, start: number): OscillatorNode {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = note.frequency;
  // A short ramp in and out keeps the tone from clicking.
  const end = start + note.length;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(VOLUME, start + RAMP);
  gain.gain.setValueAtTime(VOLUME, end - RAMP);
  gain.gain.linearRampToValueAtTime(0, end);
  oscillator.connect(gain).connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(end);
  return oscillator;
}
