import { type TemplateResult, css, html, nothing, unsafeCSS } from "lit";

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
 * What the timer shows (the `Timer`, `TimerRest` and `TimerDuo` mockups): the top row with Slut, the stations,
 * the ring, the controls and the whole workout's progress.
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
  onRingTap: () => void;
  onPrevious: () => void;
  onPause: () => void;
  onResume: () => void;
  onNext: () => void;
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
    onTap: () => ctx.onRingTap(),
  });
  const stations = view.stations ?? [];
  const one = stations.length === 1;
  const centre = inCooldown(phase.part)
    ? renderCooldownCentre(ctx, theRing, phase.interval)
    : renderCentre(ctx, theRing, phase.round, phase.interval, one);
  return html`
    ${renderHeader(ctx)}
    ${renderReach(t, ctx.reach)} ${renderSound(t, ctx.sound)}
    ${renderError(ctx.error)}
    ${
      one
        ? renderSolo(ctx, centre)
        : html`<div class="timer-duo">
            ${renderCard(ctx, 0)} ${centre} ${renderCard(ctx, 1)}
          </div>`
    }
    <div class="timer-controls">
      ${iconButton({
        icon: "mdi:skip-previous",
        label: t("flow.previous"),
        className: "timer-skip",
        onClick: ctx.onPrevious,
      })}
      ${iconButton({
        icon: paused ? "mdi:play" : "mdi:pause",
        label: t(paused ? "flow.resume" : "flow.pause"),
        className: "timer-play",
        onClick: paused ? ctx.onResume : ctx.onPause,
      })}
      ${iconButton({ icon: "mdi:skip-next", label: t("flow.next"), className: "timer-skip", onClick: ctx.onNext })}
    </div>
    ${renderWhole(ctx)}
  `;
}

/** The whole workout's progress: the elapsed whole seconds out of the planned total. */
function renderWhole(ctx: TimerContext) {
  const planned = ctx.view.totals.planned;
  const now = Math.floor(ctx.elapsed);
  const share = planned > 0 ? Math.min(1, now / planned) : 0;
  return html`
    <div
      class="timer-whole"
      role="progressbar"
      aria-label=${ctx.t("flow.whole_workout")}
      aria-valuemin="0"
      aria-valuemax=${planned}
      aria-valuenow=${Math.min(now, planned)}
      style="--ring-color: ${RING_COLORS[ctx.view.status === "paused" ? "rest" : ctx.countdown.kind]}"
    >
      <span class="timer-whole-done" style="width: ${share * 100}%"></span>
    </div>
  `;
}

/**
 * The ring's column (#60): the round pill directly above the ring, and the station pill (two
 * people: the interval) directly below it.
 */
function renderCentre(ctx: TimerContext, theRing: TemplateResult, round: number, interval: number, one: boolean) {
  const { t, view } = ctx;
  return html`
    <div class="timer-centre">
      ${renderPill(t("flow.round_label"), round, view.totals.rounds)} ${theRing}
      ${renderPill(t(one ? "flow.station_label" : "flow.interval_label"), interval, view.totals.stations)}
    </div>
  `;
}

/** The ring's column in the cool-down: the "Cool-down n / N" pill above the ring, nothing below. */
function renderCooldownCentre(ctx: TimerContext, theRing: TemplateResult, stretch: number) {
  const { t, view } = ctx;
  return html`
    <div class="timer-centre">${renderPill(t("flow.cooldown_label"), stretch, view.totals.stretches)} ${theRing}</div>
  `;
}

/**
 * The top row: the music player on the left, PAUSET while paused, and on the right the elapsed
 * time against the planned, and Slut with its question.
 */
function renderHeader(ctx: TimerContext) {
  const { t, view } = ctx;
  return html`
    <header class="timer-top ${ctx.music ? "with-music" : ""}">
      ${view.status === "paused" ? html`<span class="timer-pill paused">${t("flow.paused")}</span>` : nothing}
      ${renderPlayer(ctx)}
      <span class="elapsed"
        ><strong>${clock(ctx.elapsed)}</strong> <span class="planned">/ ${clock(view.totals.planned)}</span></span
      >
      ${
        canSkipCooldown(view)
          ? html`<span class="end">
              ${renderAsk(ctx, ctx.asking === "skip", "flow.skip_cooldown_confirm", "flow.skip_cooldown", ctx.onAskSkip)}
            </span>`
          : nothing
      }
      <span class="end">${renderAsk(ctx, ctx.asking === "end", "flow.end_confirm", "flow.end", ctx.onAskEnd)}</span>
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
 * while unavailable only Play works, so a failed start can be tried again.
 */
function renderPlayer(ctx: TimerContext) {
  const { t, music } = ctx;
  if (!music) return nothing;
  const playing = music.state === "playing";
  const waiting = music.state === "waiting";
  return html`
    <div class="timer-music card" role="group" aria-label=${t("flow.music")}>
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
    </div>
  `;
}

/**
 * A pill by the ring: the label, then the number out of the total in bold ("Runde **2 / 5**"),
 * or the number alone when the add-on sends no total. The " / " is a numeric separator, not a word.
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
  /* The pills by the ring take the card look (D52). */
  .timer-centre .timer-pill {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color);
    font-size: 1.25rem;
    white-space: nowrap;
  }
  /* The ring's column: the round pill, the ring and the station or interval pill, centred. */
  .timer-centre {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
  }
  .timer-pill.paused {
    font-weight: 700;
    letter-spacing: 0.1em;
    background: var(--primary-text-color);
    color: var(--primary-background-color);
  }
  .timer-top .elapsed {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  .timer-top .planned {
    color: var(--secondary-text-color);
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
    margin: 24px 0;
  }
  /* One person: a large ring, readable across a kitchen, a little smaller than get ready's so the
     pills above and below it fit. */
  .timer-solo > .timer-centre {
    grid-column: 2;
  }
  .timer-solo .timer-centre .ring {
    width: 340px;
    height: 340px;
  }
  .timer-solo .timer-centre .ring .seconds {
    font-size: 8.5rem;
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
    align-items: center;
    margin: 24px 0;
  }
  .timer-duo > .duo-card:first-child {
    justify-self: start;
  }
  .timer-duo > .duo-card:last-child {
    justify-self: end;
  }
  .timer-duo .timer-centre .ring {
    width: 320px;
    height: 320px;
  }
  .timer-duo .timer-centre .ring .seconds {
    font-size: 6rem;
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
  .timer-controls {
    display: flex;
    gap: 32px;
    align-items: center;
    justify-content: center;
  }
  /* Icon-only round buttons; the pause/play one is the largest control. */
  button.timer-skip,
  button.timer-play {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    border-radius: 50%;
  }
  button.timer-skip {
    width: 72px;
    min-width: 72px;
    height: 72px;
    background: var(--secondary-background-color, var(--divider-color));
    --mdc-icon-size: 32px;
  }
  button.timer-play {
    width: 104px;
    min-width: 104px;
    height: 104px;
    background: var(--primary-color);
    color: var(--text-primary-color);
    --mdc-icon-size: 48px;
  }
  .timer-whole {
    height: 8px;
    margin-top: 24px;
    border-radius: 4px;
    overflow: hidden;
    background: var(--divider-color);
  }
  .timer-whole-done {
    display: block;
    height: 100%;
    border-radius: 4px;
    background: var(--ring-color);
  }
  /* A portrait tablet (about 800 px wide): nothing scrolls sideways. */
  @container (max-width: 1000px) {
    /* The top row stays on one line: PAUSET shrinks and wraps its text, the elapsed time and
       Slut keep their room on the right. */
    .timer-top {
      flex-wrap: nowrap;
    }
    .timer-top > .timer-pill {
      white-space: normal;
      min-width: 0;
    }
    .timer-top > .elapsed {
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
    .timer-solo .timer-centre .ring {
      width: 320px;
      height: 320px;
    }
    .timer-solo .timer-centre .ring .seconds {
      font-size: 6rem;
    }
  }
`;
