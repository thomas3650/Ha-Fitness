import { vi } from "vitest";

/** One oscillator the code under test made: its frequency, when it starts, and its stop calls. */
export interface FakeTone {
  frequency: number;
  start?: number;
  /** Each `stop(when)` call's `when`; `undefined` is a stop without a time, which means now. */
  stops: (number | undefined)[];
  /** Stopped at once, or at a time not after the context's time of the call. */
  cancelled: boolean;
}

/**
 * A fake Web Audio `AudioContext`, installed as the global one. It records each context made,
 * and each oscillator's frequency, `start(when)` and stops. `currentTime` is settable.
 */
export function installFakeAudio(initialState: AudioContextState = "suspended") {
  const contexts: FakeAudioContext[] = [];

  class FakeAudioContext {
    state: AudioContextState = initialState;
    currentTime = 0;
    readonly destination = {};
    readonly tones: FakeTone[] = [];
    readonly resume = vi.fn(() => {
      this.state = "running";
      return Promise.resolve();
    });
    private readonly stateListeners = new Set<() => void>();

    constructor() {
      contexts.push(this);
    }

    addEventListener(type: string, listener: () => void) {
      if (type === "statechange") this.stateListeners.add(listener);
    }

    removeEventListener(type: string, listener: () => void) {
      if (type === "statechange") this.stateListeners.delete(listener);
    }

    /** Change the state as the browser would, and fire `statechange`. */
    setState(state: AudioContextState) {
      this.state = state;
      for (const listener of [...this.stateListeners]) listener();
    }

    createOscillator() {
      const context = this as FakeAudioContext;
      const tone: FakeTone = { frequency: 0, stops: [], cancelled: false };
      context.tones.push(tone);
      return {
        type: "sine",
        frequency: {
          set value(value: number) {
            tone.frequency = value;
          },
          get value() {
            return tone.frequency;
          },
          setValueAtTime(value: number) {
            tone.frequency = value;
          },
        },
        connect: (node: unknown) => node,
        disconnect: () => undefined,
        start(when = 0) {
          tone.start = when;
        },
        stop(when?: number) {
          tone.stops.push(when);
          if (when === undefined || when <= context.currentTime) tone.cancelled = true;
        },
      };
    }

    createGain() {
      return {
        gain: {
          value: 1,
          setValueAtTime: () => undefined,
          linearRampToValueAtTime: () => undefined,
          exponentialRampToValueAtTime: () => undefined,
          cancelScheduledValues: () => undefined,
        },
        connect: (node: unknown) => node,
        disconnect: () => undefined,
      };
    }
  }

  vi.stubGlobal("AudioContext", FakeAudioContext);
  return {
    contexts,
    /** Every oscillator of every context, in the order they were made. */
    tones: () => contexts.flatMap((context) => context.tones),
  };
}
