import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { installFakeAudio } from "./fake-audio";

type Audio = typeof import("../src/audio");

let audio: Audio;

beforeEach(async () => {
  // The audio module keeps one context for the page; each test gets a fresh page.
  vi.resetModules();
  audio = await import("../src/audio");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("unlockAudio creates one context synchronously", () => {
  const fake = installFakeAudio("suspended");
  expect(audio.audioLocked()).toBe(true);

  audio.unlockAudio();

  // Nothing awaited: the context exists and is resumed within the tap.
  expect(fake.contexts).toHaveLength(1);
  expect(fake.contexts[0].resume).toHaveBeenCalledTimes(1);
  expect(audio.audioLocked()).toBe(false);

  audio.unlockAudio();
  expect(fake.contexts).toHaveLength(1);
});

test("unlockAudio resumes a context the browser suspended again", () => {
  const fake = installFakeAudio("running");
  audio.unlockAudio();
  expect(fake.contexts[0].resume).not.toHaveBeenCalled();

  fake.contexts[0].state = "suspended";
  expect(audio.audioLocked()).toBe(true);
  audio.unlockAudio();

  expect(fake.contexts).toHaveLength(1);
  expect(fake.contexts[0].resume).toHaveBeenCalledTimes(1);
  expect(audio.audioLocked()).toBe(false);
});

test("unlockAudio resumes an interrupted context", () => {
  const fake = installFakeAudio("running");
  audio.unlockAudio();

  // Safari interrupts a context, for example during a call; that is not "suspended".
  fake.contexts[0].state = "interrupted" as AudioContextState;
  expect(audio.audioLocked()).toBe(true);
  audio.unlockAudio();

  expect(fake.contexts[0].resume).toHaveBeenCalledTimes(1);
  expect(audio.audioLocked()).toBe(false);
});

test("onAudioStateChange tells listeners when the lock changes", () => {
  const fake = installFakeAudio("running");
  const listener = vi.fn(() => audio.audioLocked());
  // A listener added before the context exists still hears its changes.
  const stop = audio.onAudioStateChange(listener);
  audio.unlockAudio();

  fake.contexts[0].setState("suspended");
  expect(listener).toHaveBeenCalledTimes(1);
  expect(listener).toHaveLastReturnedWith(true);

  fake.contexts[0].setState("running");
  expect(listener).toHaveBeenCalledTimes(2);
  expect(listener).toHaveLastReturnedWith(false);

  stop();
  fake.contexts[0].setState("suspended");
  expect(listener).toHaveBeenCalledTimes(2);
});

test("without Web Audio nothing plays and audio stays locked", () => {
  vi.stubGlobal("AudioContext", undefined);

  expect(() => audio.unlockAudio()).not.toThrow();
  expect(audio.audioLocked()).toBe(true);
  expect(() => audio.scheduleTone("beep", 2_000, 1_000)()).not.toThrow();
});

test("scheduleTone before the unlock makes no context", () => {
  const fake = installFakeAudio();

  const cancel = audio.scheduleTone("work", 2_000, 1_000);

  expect(fake.contexts).toHaveLength(0);
  expect(() => cancel()).not.toThrow();
});

test("scheduleTone maps epoch ms to context time and cancels", () => {
  const fake = installFakeAudio();
  audio.unlockAudio();
  const context = fake.contexts[0];
  context.currentTime = 10;
  const now = 1_761_300_000_000;

  const cancelBeep = audio.scheduleTone("beep", now + 2_500, now);
  const [beep] = fake.tones();
  expect(beep.start).toBeCloseTo(12.5, 6);
  expect(beep.cancelled).toBe(false);

  cancelBeep();
  expect(beep.cancelled).toBe(true);
});

test("a tone whose time has passed plays at once", () => {
  const fake = installFakeAudio();
  audio.unlockAudio();
  fake.contexts[0].currentTime = 4;
  const now = 1_761_300_000_000;

  audio.scheduleTone("beep", now - 200, now);

  expect(fake.tones()[0].start).toBe(4);
});

test("work is higher than switch and rest, and the chime is three rising tones", () => {
  const fake = installFakeAudio();
  audio.unlockAudio();
  const now = 1_761_300_000_000;

  audio.scheduleTone("work", now + 1_000, now);
  audio.scheduleTone("rest", now + 1_000, now);
  const [work, rest] = fake.tones();
  expect(work.frequency).toBeGreaterThan(rest.frequency);

  const cancelChime = audio.scheduleTone("chime", now + 3_000, now);
  const chime = fake.tones().slice(2);
  expect(chime).toHaveLength(3);
  expect(chime[0].start).toBeCloseTo(3, 6);
  expect(chime[1].start!).toBeGreaterThan(chime[0].start!);
  expect(chime[2].start!).toBeGreaterThan(chime[1].start!);
  expect(chime[1].frequency).toBeGreaterThan(chime[0].frequency);
  expect(chime[2].frequency).toBeGreaterThan(chime[1].frequency);

  cancelChime();
  expect(chime.every((tone) => tone.cancelled)).toBe(true);
  expect(work.cancelled).toBe(false);
});
