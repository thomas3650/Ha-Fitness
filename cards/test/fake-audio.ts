import { vi } from "vitest";

import { KEEP_ALIVE_HZ } from "../src/audio";

/**
 * One oscillator the code under test made: its frequency, when it starts, its stop calls and its
 * loudest gain.
 */
export interface FakeTone {
  frequency: number;
  start?: number;
  /** Each `stop(when)` call's `when`; `undefined` is a stop without a time, which means now. */
  stops: (number | undefined)[];
  /** Stopped at once, or at a time not after the context's time of the call. */
  cancelled: boolean;
  /**
   * The highest value of the gain node the oscillator connects to: of its automation, or with
   * none its `value` (Web Audio's default 1).
   */
  readonly peak: number;
}

/** A fake gain node's record: its `value`, and every value its automation sets or ramps to. */
interface GainRecord {
  value: number;
  automation: number[];
}

/**
 * A fake Web Audio `AudioContext`, installed as the global one. It records each context made,
 * and each oscillator's frequency, `start(when)`, stops and gain. An oscillator set to
 * `KEEP_ALIVE_HZ` is the keep-alive: it goes in `keepAlives`, not in `tones`. `currentTime` is
 * settable.
 */
export function installFakeAudio(initialState: AudioContextState = "suspended") {
  const contexts: FakeAudioContext[] = [];

  class FakeAudioContext {
    state: AudioContextState = initialState;
    currentTime = 0;
    readonly destination = {};
    readonly tones: FakeTone[] = [];
    /** The keep-alive oscillators; one is live while it isn't cancelled. */
    readonly keepAlives: FakeTone[] = [];
    /** As browsers do: the state changes, and `statechange` fires, after the call returns. */
    readonly resume = vi.fn(async () => {
      await Promise.resolve();
      this.setState("running");
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
      let gain: GainRecord | undefined;
      const tone: FakeTone = {
        frequency: 0,
        stops: [],
        cancelled: false,
        get peak() {
          if (!gain) return 1;
          return gain.automation.length ? Math.max(...gain.automation) : gain.value;
        },
      };
      context.tones.push(tone);
      const setFrequency = (value: number) => {
        tone.frequency = value;
        if (value !== KEEP_ALIVE_HZ) return;
        const index = context.tones.indexOf(tone);
        if (index >= 0) context.tones.splice(index, 1);
        if (!context.keepAlives.includes(tone)) context.keepAlives.push(tone);
      };
      return {
        type: "sine",
        frequency: {
          set value(value: number) {
            setFrequency(value);
          },
          get value() {
            return tone.frequency;
          },
          setValueAtTime(value: number) {
            setFrequency(value);
          },
        },
        connect: (node: { record?: GainRecord }) => {
          if (node.record) gain = node.record;
          return node;
        },
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
      const record: GainRecord = { value: 1, automation: [] };
      const automate = (value: number) => {
        record.automation.push(value);
      };
      return {
        record,
        gain: {
          set value(value: number) {
            record.value = value;
          },
          get value() {
            return record.value;
          },
          setValueAtTime: automate,
          linearRampToValueAtTime: automate,
          exponentialRampToValueAtTime: automate,
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
    /** Every keep-alive oscillator of every context, in the order they were made. */
    keepAlives: () => contexts.flatMap((context) => context.keepAlives),
  };
}
