import { type TemplateResult, css, html, nothing, unsafeCSS } from "lit";
import { live } from "lit/directives/live.js";

import { iconButton } from "../icon-button";
import type { MusicState, Part, PhaseKind, SessionStation, SessionView } from "../overlay";
import { personTextColor } from "../people";
import { ring } from "../ring";
import {
  type Countdown,
  type ImageOf,
  type ReachNote,
  type SoundButton,
  PHASE_TEXT_COLORS,
  RING_COLORS,
  type Translate,
  clock,
  renderError,
  renderImage,
  renderReach,
  renderSound,
} from "./shared";

/**
 * What the timer shows (the `TimerBand` mockup): the top row with Slut, the stations, the ring
 * with its button, and the time-left band.
 */
export interface TimerContext {
  t: Translate;
  view: SessionView;
  countdown: Countdown;
  /** The active seconds so far. */
  elapsed: number;
  /** Each participant's colour, in the order of `view.participants`. */
  colors: string[];
  imageOf: ImageOf;
  reach: ReachNote;
  sound: SoundButton;
  error: string | undefined;
  /** The session's music; null without, and then no player shows. */
  music: MusicState | null;
  /** The question that shows: Slut's, Skip cool-down's, or none. */
  asking: "end" | "skip" | undefined;
  /** The ring button: Pause while running, Fortsæt while paused (D73). */
  onRingTap: () => void;
  /** Slut's first tap. */
  onAskEnd: () => void;
  /** Skip cool-down's first tap. */
  onAskSkip: () => void;
  /** The question's Ja. */
  onConfirm: () => void;
  /** The question's Nej. */
  onKeepGoing: () => void;
  /** The player's Pause music or Play music. */
  onMusicToggle: () => void;
  /** The player's Next track. */
  onMusicNext: () => void;
  /** The level the volume slider shows instead of the music's, while held or just released. */
  volumeHeld: number | undefined;
  /** The volume slider moved, while its thumb is held (the `input` event). */
  onVolumeInput: (level: number) => void;
  /** The volume slider let go (the `change` event). */
  onVolumeChange: (level: number) => void;
  /** A cancelled touch or a lost focus on the volume slider (`pointercancel`, `blur`). */
  onVolumeRelease: (level: number) => void;
}

/** Whether a part is the cool-down; a missing part (an older add-on) is the circuit. */
function inCooldown(part: Part | undefined): boolean {
  return part === "cooldown";
}

/**
 * Skip cool-down applies in the cool-down and in the rest right before it (cool-down spec §4.5):
 * that rest is the one whose next phase is in the cool-down.
 */
export function canSkipCooldown(view: SessionView | undefined): boolean {
  const phase = view?.phase;
  if (!view || !phase || (view.status !== "running" && view.status !== "paused")) return false;
  return inCooldown(phase.part) || (phase.kind === "rest" && inCooldown(view.next_phase?.part));
}

/** The ring's word key: in the cool-down a work phase is a hold (STRETCH) and a switch a change (CHANGE). */
function phaseWord(kind: PhaseKind, part: Part): string {
  if (inCooldown(part) && kind === "work") return "flow.phase.stretch";
  if (inCooldown(part) && kind === "switch") return "flow.phase.change";
  return `flow.phase.${kind}`;
}

/**
 * The line above a moving person's exercise, or undefined during work and a hold: "COOL-DOWN NEXT"
 * in the rest before the cool-down, "NEXT STRETCH" in a change, else "GO TO THE NEXT STATION".
 */
function moveText(view: SessionView, current: SessionStation): string | undefined {
  const phase = view.phase!;
  if (phase.kind === "work") return undefined;
  if (!inCooldown(current.part)) return "flow.go_to_next";
  return inCooldown(phase.part) ? "flow.next_stretch" : "flow.cooldown_next";
}

export function renderTimer(ctx: TimerContext): TemplateResult {
  const { t, view, countdown } = ctx;
  const phase = view.phase!;
  const paused = view.status === "paused";
  // Paused, the ring keeps the phase word; the pill and the caption say it is paused, and the
  // colours turn blue (rest), so a paused work phase no longer looks like work.
  const word = t(phaseWord(countdown.kind, countdown.part));
  const tint = paused ? "rest" : countdown.kind;
  const theRing = ring({
    label: word,
    word,
    max: countdown.duration,
    value: countdown.seconds,
    fraction: countdown.fraction,
    color: RING_COLORS[tint],
    wordColor: PHASE_TEXT_COLORS[tint],
    caption: t(paused ? "flow.tap_to_resume" : "flow.seconds_left"),
    // The room stays while paused too, so the texts don't move on a pause or a resume.
    room: true,
  });
  const stations = view.stations ?? [];
  const one = stations.length === 1;
  // The one pill under the ring: the stretch in the cool-down, else the station (two people: the interval).
  const thePill = inCooldown(phase.part)
    ? renderPill(t("flow.cooldown_label"), phase.interval, view.totals.stretches)
    : renderPill(t(one ? "flow.station_label" : "flow.interval_label"), phase.interval, view.totals.stations);
  const centre = html`<div class="timer-centre">${renderRing(ctx, theRing, paused)} ${thePill}</div>`;
  return html`
    <div class="timer">
      ${renderHeader(ctx)} ${renderBanners(ctx)}
      ${
        one
          ? renderSolo(ctx, centre)
          : html`<div class="timer-duo">
              ${renderCard(ctx, 0)} ${centre} ${renderCard(ctx, 1)}
            </div>`
      }
      ${renderBand(ctx)}
    </div>
  `;
}

/**
 * The ring with its button laid over it (D73): a transparent button the ring's size, named Pause
 * while running and Fortsæt while paused. It is the ring's sibling, so the ring keeps its
 * progressbar role. While running it shows "tryk for pause" in the room under the ring's caption.
 */
function renderRing(ctx: TimerContext, theRing: TemplateResult, paused: boolean) {
  const { t } = ctx;
  const tap = html`<span class="ring-tap"
    ><ha-icon icon="mdi:pause" aria-hidden="true"></ha-icon>${t("flow.tap_to_pause")}</span
  >`;
  return html`
    <div class="timer-ring">
      ${theRing}
      <button
        class="ring-button"
        aria-label=${t(paused ? "flow.resume" : "flow.pause")}
        @click=${() => ctx.onRingTap()}
      >
        ${paused ? nothing : tap}
      </button>
    </div>
  `;
}

/** The banners between the top row and the cards: unreachable, Tryk for lyd, an error. With none, no row. */
function renderBanners(ctx: TimerContext) {
  const { t } = ctx;
  if (ctx.reach.reachable && !ctx.sound.shown && !ctx.error) return nothing;
  return html`
    <div class="timer-banners">${renderReach(t, ctx.reach)} ${renderSound(t, ctx.sound)} ${renderError(ctx.error)}</div>
  `;
}

/**
 * The time-left band at the bottom: the share done filled in the phase's colour (blue while
 * paused), a gap where each round after the first and the cool-down start (`totals.marks`; none
 * from an older add-on), the trained time on the left and the time left on the right. Both count
 * whole seconds: the time left is `planned` minus the trained whole seconds, never below 0:00.
 */
function renderBand(ctx: TimerContext) {
  const { t, view } = ctx;
  const planned = view.totals.planned;
  const now = Math.floor(ctx.elapsed);
  const left = clock(Math.max(0, planned - now));
  const share = planned > 0 ? Math.min(1, now / planned) : 0;
  const marks = planned > 0 ? (view.totals.marks ?? []).filter((mark) => mark > 0 && mark < planned) : [];
  return html`
    <div
      class="timer-band"
      role="progressbar"
      aria-label=${t("flow.whole_workout")}
      aria-valuemin="0"
      aria-valuemax=${planned}
      aria-valuenow=${Math.min(now, planned)}
      aria-valuetext=${t("flow.band_value", { time: left })}
      style="--ring-color: ${RING_COLORS[view.status === "paused" ? "rest" : ctx.countdown.kind]}"
    >
      <span class="timer-band-done" style="width: ${share * 100}%"></span>
      ${marks.map(
        (mark) =>
          html`<span
            class="timer-band-gap"
            role="separator"
            aria-hidden="true"
            style="left: ${(mark / planned) * 100}%"
          ></span>`,
      )}
      <span class="timer-band-trained">${clock(now)}</span>
      <span class="timer-band-left"><strong>${left}</strong> <span>${t("flow.band_left")}</span></span>
    </div>
  `;
}

/**
 * The top row: the music player on the left, PAUSET while paused, and on the right Skip
 * cool-down and Slut with their questions.
 */
function renderHeader(ctx: TimerContext) {
  const { t, view } = ctx;
  return html`
    <header class="timer-top ${ctx.music ? "with-music" : ""}">
      ${view.status === "paused" ? html`<span class="timer-pill paused">${t("flow.paused")}</span>` : nothing}
      ${renderPlayer(ctx)}
      <span class="timer-actions">
        ${
          canSkipCooldown(view)
            ? html`<span class="end">
                ${renderAsk(
                  ctx,
                  ctx.asking === "skip",
                  "flow.skip_cooldown_confirm",
                  "flow.skip_cooldown",
                  ctx.onAskSkip,
                )}
              </span>`
            : nothing
        }
        <span class="end">${renderAsk(ctx, ctx.asking === "end", "flow.end_confirm", "flow.end", ctx.onAskEnd)}</span>
      </span>
    </header>
  `;
}

/**
 * A button that asks first (Slut, Skip cool-down): the button, or while its question shows the
 * question with Ja and Nej. The other button keeps showing, so a tap on it swaps the question.
 */
function renderAsk(ctx: TimerContext, asking: boolean, question: string, label: string, onAsk: () => void) {
  const { t } = ctx;
  return asking
    ? html`
        <span class="question">${t(question)}</span>
        <button @click=${() => ctx.onConfirm()}>${t("flow.yes")}</button>
        <button class="slot" @click=${() => ctx.onKeepGoing()}>${t("flow.no")}</button>
      `
    : html`<button class="slot soft" @click=${() => onAsk()}>${t(label)}</button>`;
}

/**
 * The music player at the top row's start (music spec §6.2): the music badge, the playlist over the
 * speaker, and Pause or Play with Next. While waiting for the first work phase both are disabled;
 * while unavailable only Play works, so a failed start can be tried again. With a volume, the
 * volume slider follows Next, disabled when Next is (timer band and volume spec §2.2).
 */
function renderPlayer(ctx: TimerContext) {
  const { t, music } = ctx;
  if (!music) return nothing;
  const playing = music.state === "playing";
  const waiting = music.state === "waiting";
  const volume = typeof music.volume === "number" ? music.volume : undefined;
  return html`
    <div class="timer-music card ${volume === undefined ? "" : "with-volume"}" role="group" aria-label=${t("flow.music")}>
      <span class="timer-music-badge"><ha-icon icon="mdi:music" aria-hidden="true"></ha-icon></span>
      <span class="timer-music-lines">
        <span class="timer-music-playlist">${music.playlist_name}</span>
        <span class="timer-music-speaker"
          >${music.state === "unavailable" ? t("flow.music_unavailable") : music.speaker_name}</span
        >
      </span>
      ${iconButton({
        icon: playing ? "mdi:pause" : "mdi:play",
        label: t(playing ? "flow.music_pause" : "flow.music_play"),
        className: "soft timer-music-button",
        disabled: waiting,
        onClick: ctx.onMusicToggle,
      })}
      ${iconButton({
        icon: "mdi:skip-next",
        label: t("flow.music_next"),
        className: "soft timer-music-button",
        disabled: waiting || music.state === "unavailable",
        onClick: ctx.onMusicNext,
      })}
      ${volume === undefined ? nothing : renderVolume(ctx, ctx.volumeHeld ?? volume, waiting || music.state === "unavailable")}
    </div>
  `;
}

/** The volume slider: a speaker icon and a native range input, 0 to 100, with a large thumb for touch. */
function renderVolume(ctx: TimerContext, level: number, disabled: boolean) {
  const value = (event: Event) => Number((event.target as HTMLInputElement).value);
  return html`
    <span class="timer-music-volume">
      <ha-icon icon="mdi:volume-high" aria-hidden="true"></ha-icon>
      <input
        type="range"
        min="0"
        max="100"
        step="1"
        aria-label=${ctx.t("flow.music_volume")}
        .value=${live(String(level))}
        ?disabled=${disabled}
        @input=${(event: Event) => ctx.onVolumeInput(value(event))}
        @change=${(event: Event) => ctx.onVolumeChange(value(event))}
        @pointercancel=${(event: Event) => ctx.onVolumeRelease(value(event))}
        @blur=${(event: Event) => ctx.onVolumeRelease(value(event))}
      />
    </span>
  `;
}

/**
 * The pill under the ring: the label, then the number out of the total in bold and large
 * ("Interval **3 / 5**"), or the number alone when the add-on sends no total. The " / " is a
 * numeric separator, not a word.
 */
function renderPill(label: string, current: number, total: number | undefined) {
  return html`<span class="timer-pill"
    >${label} <strong>${total === undefined ? current : `${current} / ${total}`}</strong></span
  >`;
}

/**
 * One person: the exercise big with its GIF, the ring in the middle, and the NÆSTE card on the
 * right. During a switch or a rest `current` is the station moved to, so it reads "GÅ TIL NÆSTE
 * STATION" and the card says DEREFTER. The three columns keep their widths without a card, so the
 * ring stays centred (#36).
 */
function renderSolo(ctx: TimerContext, centre: TemplateResult) {
  const { t, view } = ctx;
  const station = view.stations![0];
  const person = view.participants[0];
  const moving = view.phase!.kind !== "work";
  const move = moveText(view, station.current);
  return html`
    <div class="timer-solo">
      <section class="timer-now" aria-label=${person?.name ?? ""}>
        <span
          class="timer-move"
          style=${move ? "" : "visibility: hidden"}
          aria-hidden=${move ? "false" : "true"}
          >${move ? t(move) : "\u00a0"}</span
        >
        ${renderImage(ctx.imageOf, station.current, "gif", "gif")}
        <span class="exercise">${station.current.name}</span>
      </section>
      ${centre}
      ${station.next ? renderNext(ctx, station.current, station.next, moving) : nothing}
    </div>
  `;
}

/**
 * The NÆSTE (or DEREFTER) card: the next station's picture, its name, and what comes before it.
 * During the circuit's last work it shows the first stretch, titled UDSTRÆKNING.
 */
function renderNext(ctx: TimerContext, current: SessionStation, next: SessionStation, moving: boolean) {
  const { t, view } = ctx;
  const toCooldown = !moving && inCooldown(next.part) && !inCooldown(current.part);
  const label = t(moving ? "flow.then_card" : toCooldown ? "flow.cooldown_card" : "flow.next_card");
  const after = view.next_phase;
  // During work a 0 s switch makes the next phase work: "derefter". During a switch or a rest the
  // next phase is the coming work, so its length shows. In the cool-down a work is a hold and a
  // switch a change.
  const subtitle = !after
    ? undefined
    : !moving && after.kind === "work"
      ? t("flow.after.none")
      : t(`flow.after.${phaseAfter(after.kind, after.part ?? "circuit")}`, { seconds: after.duration });
  return html`
    <section class="timer-next card" aria-label=${label}>
      <span class="label">${label}</span>
      ${renderImage(ctx.imageOf, next, "thumbnail", "timer-next-image")}
      <span class="exercise">${next.name}</span>
      ${subtitle ? html`<span class="after">${subtitle}</span>` : nothing}
    </section>
  `;
}

/** The subtitle's key under `flow.after`: the phase kind, or in the cool-down `stretch` and `change`. */
function phaseAfter(kind: PhaseKind, part: Part): string {
  if (inCooldown(part) && kind === "work") return "stretch";
  if (inCooldown(part) && kind === "switch") return "change";
  return kind;
}

/** A two-person card's next line: the next station, the cool-down's first stretch, or the next stretch. */
function nextLine(t: Translate, current: SessionStation, next: SessionStation): string {
  if (!inCooldown(next.part)) return t("flow.next_station", { number: next.number, exercise: next.name });
  return t(inCooldown(current.part) ? "flow.next_stretch_line" : "flow.next_cooldown", { exercise: next.name });
}

/**
 * A person's card in the two-person layout (the `TimerDuo` mockup): the badge with the person's
 * number and name, the station on the right with its number in bold, the GIF, the exercise big, and
 * the next station small.
 */
function renderCard(ctx: TimerContext, index: number) {
  const { t, view } = ctx;
  const person = view.participants[index];
  const station = view.stations?.[index];
  if (!person || !station) return nothing;
  const stretch = inCooldown(station.current.part);
  // The circuit's cards show no move line; the cool-down's say what comes (cool-down spec §4.7).
  const move = stretch ? moveText(view, station.current) : undefined;
  return html`
    <section
      class="duo-card card"
      aria-label=${person.name}
      style="--person-color: ${ctx.colors[index]}; --person-text: ${personTextColor(ctx.colors[index])}"
    >
      <div class="duo-who">
        <span class="duo-number">${index + 1}</span>
        <span class="duo-name">${person.name}</span>
        ${
          stretch
            ? nothing
            : html`<span class="duo-station"
                >${t("flow.station_label")} <strong>${station.current.number}</strong></span
              >`
        }
      </div>
      ${move ? html`<span class="timer-move">${t(move)}</span>` : nothing}
      ${renderImage(ctx.imageOf, station.current, "gif", "gif")}
      <span class="duo-exercise">${station.current.name}</span>
      ${station.next ? html`<span class="duo-next">${nextLine(t, station.current, station.next)}</span>` : nothing}
    </section>
  `;
}

export const timerStyles = css`
  /* The screen is one grid: the top row, the banners (only while one shows), the stations with
     the ring, and the band. The gaps are the only spacing. */
  .timer {
    display: grid;
    gap: 20px;
  }
  .timer-banners {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 24px;
    align-items: center;
  }
  .timer-banners > .note,
  .timer-banners > .error {
    margin: 0;
  }
  .timer-top {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 16px;
    align-items: center;
    font-size: 1.25rem;
  }
  /* Each part stays on one line; at a narrow width whole parts wrap instead. */
  .timer-top > span,
  .timer-top .question {
    white-space: nowrap;
  }
  .timer-top .end {
    flex: none;
  }
  .timer-pill {
    padding: 10px 18px;
    border-radius: 999px;
    background: var(--secondary-background-color, var(--divider-color));
  }
  /* The pill under the ring takes the card look (D52): the label in normal text, the numbers
     large in the numbers' font. */
  .timer-centre .timer-pill {
    display: flex;
    gap: 12px;
    align-items: baseline;
    padding: 8px 28px;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color);
    font-size: 1.375rem;
    white-space: nowrap;
  }
  .timer-centre .timer-pill strong {
    font-size: 2.25rem;
    font-weight: 700;
    line-height: 1.2;
    font-variant-numeric: tabular-nums;
  }
  /* The ring's column, as tall as the cards: the ring centred, the pill at the bottom. */
  .timer-centre {
    display: grid;
    grid-template-rows: 1fr auto 1fr;
    justify-items: center;
    row-gap: 14px;
    align-self: stretch;
  }
  .timer-centre > .timer-ring {
    grid-row: 2;
  }
  .timer-centre > .timer-pill {
    grid-row: 3;
    align-self: end;
  }
  .timer-pill.paused {
    font-weight: 700;
    letter-spacing: 0.1em;
    background: var(--primary-text-color);
    color: var(--primary-background-color);
  }
  /* Skip cool-down and Slut on the right. */
  .timer-top .timer-actions {
    display: flex;
    gap: 16px;
    align-items: center;
    margin-left: auto;
  }
  .timer-top .end {
    display: flex;
    gap: 16px;
    align-items: center;
  }
  button.slot {
    min-width: 120px;
  }
  /* The music player: a pill-shaped card that takes the room left in the row, up to 400 px, and
     shrinks with ellipsis before PAUSET or Slut do. */
  .timer-music {
    display: flex;
    flex: 1 1 0;
    align-items: center;
    gap: 12px;
    min-width: 0;
    max-width: 400px;
    height: 56px;
    padding: 0 8px 0 9px;
    border-radius: 999px;
    font-size: 1rem;
  }
  /* With the volume slider the player grows, toward the mockup's 640 px on the tablet. */
  .timer-music.with-volume {
    max-width: 640px;
    padding-right: 18px;
  }
  .timer-music-volume {
    display: flex;
    flex: 1 1 160px;
    align-items: center;
    gap: 8px;
    min-width: 120px;
    color: var(--secondary-text-color);
    --mdc-icon-size: 22px;
  }
  .timer-music-volume ha-icon {
    flex: none;
  }
  /* A touch-friendly range: a 44 px tall hit area, a thick track and a large thumb. */
  .timer-music-volume input {
    flex: 1;
    min-width: 0;
    height: 44px;
    margin: 0;
    background: transparent;
    accent-color: ${unsafeCSS(RING_COLORS.work)};
    cursor: pointer;
    appearance: none;
    -webkit-appearance: none;
  }
  .timer-music-volume input:disabled {
    cursor: default;
    opacity: 0.4;
  }
  .timer-music-volume input::-webkit-slider-runnable-track {
    height: 6px;
    border-radius: 3px;
    background: var(--divider-color, rgba(0, 0, 0, 0.12));
  }
  .timer-music-volume input::-moz-range-track {
    height: 6px;
    border-radius: 3px;
    background: var(--divider-color, rgba(0, 0, 0, 0.12));
  }
  .timer-music-volume input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 24px;
    height: 24px;
    margin-top: -9px;
    border: none;
    border-radius: 50%;
    background: ${unsafeCSS(RING_COLORS.work)};
  }
  .timer-music-volume input::-moz-range-thumb {
    width: 24px;
    height: 24px;
    border: none;
    border-radius: 50%;
    background: ${unsafeCSS(RING_COLORS.work)};
  }
  .timer-music-badge {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    border-radius: 50%;
    background: color-mix(in srgb, ${unsafeCSS(RING_COLORS.work)} 18%, transparent);
    color: ${unsafeCSS(PHASE_TEXT_COLORS.work)};
    --mdc-icon-size: 20px;
  }
  .timer-music-lines {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }
  .timer-music-lines > span {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .timer-music-playlist {
    font-weight: 600;
  }
  .timer-music-speaker {
    font-size: 0.875rem;
    color: var(--secondary-text-color);
  }
  button.timer-music-button {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 44px;
    min-width: 44px;
    height: 44px;
    min-height: 44px;
    padding: 0;
    border-radius: 50%;
    --mdc-icon-size: 20px;
  }
  /* One person: three columns whose sides keep their widths, so the ring stays centred with or
     without the NÆSTE card (#36). */
  .timer-solo {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 32px;
    align-items: center;
  }
  /* One person: a large ring, readable across a kitchen. */
  .timer-solo > .timer-centre {
    grid-column: 2;
  }
  .timer-solo .timer-ring {
    --ring-size: 380px;
    --seconds-size: 8.5rem;
  }
  .timer-now {
    grid-column: 1;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .timer-now .gif {
    width: min(320px, 100%);
    height: auto;
    aspect-ratio: 1;
    box-sizing: border-box;
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color);
  }
  .timer-now .exercise {
    font-size: 2.25rem;
    font-weight: 700;
  }
  .timer-move,
  .timer-next .label {
    font-size: 1rem;
    font-weight: 500;
    letter-spacing: 0.08em;
  }
  .timer-move {
    color: ${unsafeCSS(PHASE_TEXT_COLORS.switch)};
  }
  .timer-next {
    grid-column: 3;
    justify-self: end;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-sizing: border-box;
    width: min(300px, 100%);
    min-width: 0;
    padding: 18px;
    border-radius: 20px;
    overflow-wrap: anywhere;
  }
  .timer-next .label,
  .timer-next .after {
    color: var(--secondary-text-color);
  }
  .timer-next-image {
    width: 100%;
    aspect-ratio: 16 / 11;
    border-radius: 12px;
    object-fit: cover;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .timer-next .exercise {
    font-size: 1.5rem;
    font-weight: 700;
  }
  /* Two people: a card each side of the ring. The sides keep equal widths, so the ring stays
     centred. */
  .timer-duo {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 32px;
    align-items: stretch;
  }
  .timer-duo > .duo-card:first-child {
    justify-self: start;
  }
  .timer-duo > .duo-card:last-child {
    justify-self: end;
  }
  .timer-duo .timer-ring {
    --ring-size: 360px;
    --seconds-size: 6.5rem;
  }
  .duo-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-sizing: border-box;
    width: min(380px, 100%);
    min-width: 0;
    padding: 18px;
    border-radius: 24px;
    overflow-wrap: anywhere;
  }
  .duo-who {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .duo-number {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--person-color);
    color: var(--person-text);
    font-size: 1.375rem;
    font-weight: 700;
  }
  .duo-name {
    min-width: 0;
    font-size: 1.5rem;
    font-weight: 700;
  }
  .duo-station {
    margin-left: auto;
    font-size: 1.125rem;
    color: var(--secondary-text-color);
    white-space: nowrap;
  }
  .duo-exercise {
    font-size: 2rem;
    font-weight: 700;
  }
  .duo-next {
    color: var(--secondary-text-color);
  }
  .gif {
    width: 280px;
    height: 280px;
    border-radius: 16px;
    object-fit: cover;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .duo-card .gif {
    width: 100%;
    height: 280px;
    object-fit: contain;
    background: #fff;
  }
  .ring {
    position: relative;
    flex: none;
    width: 320px;
    height: 320px;
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
    color: var(--word-color, inherit);
    font-size: 1.5rem;
    font-weight: 500;
    letter-spacing: 0.1em;
  }
  .ring .seconds {
    font-size: 6rem;
    font-weight: 700;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .ring .caption {
    color: var(--secondary-text-color);
  }
  /* The timer's ring and its button share one box. The texts' line heights are fixed, so the
     button's "tryk for pause" lands in the ring's empty room under the caption. */
  .timer-ring {
    position: relative;
    flex: none;
    width: var(--ring-size, 320px);
    height: var(--ring-size, 320px);
    --line-word: 1.8rem;
    --line-caption: 1.5rem;
    --line-tap: 2rem;
  }
  .timer-ring .ring {
    width: 100%;
    height: 100%;
  }
  .timer-ring .ring .word {
    line-height: var(--line-word);
  }
  .timer-ring .ring .seconds {
    font-size: var(--seconds-size, 6rem);
    line-height: 1;
  }
  .timer-ring .ring .caption {
    line-height: var(--line-caption);
  }
  .timer-ring .ring .room {
    height: var(--line-tap);
  }
  /* The ring button: transparent, round, the ring's size, laid over it (D73). */
  button.ring-button {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-width: 0;
    min-height: 0;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: none;
    cursor: pointer;
  }
  button.ring-button:focus-visible {
    outline: 3px solid var(--primary-color);
    outline-offset: 4px;
  }
  /* As tall as the word, the seconds and the caption, so the tap line sits right under them. */
  button.ring-button::before {
    content: "";
    height: calc(var(--line-word) + var(--seconds-size, 6rem) + var(--line-caption));
  }
  .ring-tap {
    display: flex;
    gap: 6px;
    align-items: center;
    height: var(--line-tap);
    color: ${unsafeCSS(PHASE_TEXT_COLORS.rest)};
    font-size: 1rem;
    font-weight: 600;
    --mdc-icon-size: 18px;
  }
  /* The time-left band: the share done in the phase's colour, the rounds split by gaps, and both
     times in the primary text colour, which keeps its contrast on the fill and the grey alike. */
  .timer-band {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 44px;
    padding: 0 20px;
    border-radius: 22px;
    overflow: hidden;
    background: var(--divider-color);
    color: var(--primary-text-color);
  }
  .timer-band-done {
    position: absolute;
    inset: 0 auto 0 0;
    background: var(--ring-color);
  }
  .timer-band-gap {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 4px;
    margin-left: -2px;
    background: var(--primary-background-color);
  }
  .timer-band-trained,
  .timer-band-left {
    position: relative;
    font-variant-numeric: tabular-nums;
  }
  .timer-band-trained {
    font-size: 1.25rem;
    font-weight: 600;
  }
  .timer-band-left {
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  .timer-band-left strong {
    font-size: 2rem;
    font-weight: 700;
  }
  /* A portrait tablet (about 800 px wide): nothing scrolls sideways. */
  @container (max-width: 1000px) {
    /* The top row stays on one line: PAUSET shrinks and wraps its text, Skip cool-down and Slut
       keep their room on the right. */
    .timer-top {
      flex-wrap: nowrap;
    }
    .timer-top > .timer-pill {
      white-space: normal;
      min-width: 0;
    }
    .timer-top > .timer-actions {
      flex: none;
    }
    /* With the player, the row wraps after Slut and the player takes its own line below: the
       ::after item fills the first line's rest. PAUSET keeps shrinking as without it, since it
       grows from 0 up to its text's width. */
    .timer-top.with-music {
      flex-wrap: wrap;
      row-gap: 0;
    }
    .timer-top.with-music > .timer-pill {
      flex: 1 1 0;
      max-width: max-content;
    }
    .timer-top.with-music::after {
      content: "";
      order: 1;
      flex-basis: 100%;
    }
    /* The break item takes a line of its own, so the gap above the player is its margin. */
    .timer-top.with-music > .timer-music {
      order: 2;
      margin-top: 12px;
    }
    /* Two people: both cards side by side, the ring below them. */
    .timer-duo {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      grid-template-areas:
        "first second"
        "ring ring";
      gap: 24px;
      align-items: stretch;
    }
    .timer-duo > .duo-card:first-child {
      grid-area: first;
      width: 100%;
    }
    .timer-duo > .duo-card:last-child {
      grid-area: second;
      width: 100%;
    }
    .timer-duo > .timer-centre {
      grid-area: ring;
      justify-self: center;
    }
    /* One person: the exercise and NÆSTE side by side, the ring below them. */
    .timer-solo {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      grid-template-areas:
        "now next"
        "ring ring";
      gap: 24px;
    }
    .timer-now {
      grid-area: now;
    }
    .timer-next {
      grid-area: next;
    }
    .timer-solo > .timer-centre {
      grid-area: ring;
      justify-self: center;
    }
    .timer-solo .timer-ring,
    .timer-duo .timer-ring {
      --ring-size: 320px;
      --seconds-size: 6rem;
    }
  }
`;
