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
  // A longer, higher tone when work starts.
  work: [{ frequency: 1320, offset: 0, length: 0.45 }],
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

/**
 * Create or resume the page's audio context. Call it synchronously in a tap handler (Start,
 * Fortsæt), before anything awaits.
 */
export function unlockAudio(): void {
  if (!context) {
    const Context = globalThis.AudioContext as typeof AudioContext | undefined;
    if (!Context) return;
    context = new Context();
  }
  if (context.state === "suspended") void context.resume().catch(() => undefined);
}

/** True while no sound can play: never unlocked, suspended again, or no Web Audio. */
export function audioLocked(): boolean {
  return !context || context.state !== "running";
}

/**
 * Play `kind` at the epoch time `atEpochMs`, given that it is `nowEpochMs` now. A time already
 * passed plays at once. Returns the cancel, which silences the tone if it has not finished.
 */
export function scheduleTone(kind: ToneKind, atEpochMs: number, nowEpochMs: number): () => void {
  const ctx = context;
  if (!ctx) return () => undefined;
  const when = Math.max(ctx.currentTime, ctx.currentTime + (atEpochMs - nowEpochMs) / 1000);
  const oscillators = TONES[kind].map((note) => play(ctx, note, when + note.offset));
  return () => {
    for (const oscillator of oscillators) {
      try {
        oscillator.stop();
        oscillator.disconnect();
      } catch {
        // Already stopped; nothing left to silence.
      }
    }
  };
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
