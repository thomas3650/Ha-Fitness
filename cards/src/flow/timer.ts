import { type TemplateResult, css, html, nothing } from "lit";

import type { PhaseKind, SessionStation, SessionView } from "../overlay";
import { ring } from "../ring";
import {
  type Countdown,
  type ImageOf,
  type ReachNote,
  type SoundButton,
  type Translate,
  clock,
  renderError,
  renderImage,
  renderReach,
  renderSound,
  renderThumbnail,
} from "./shared";

/** The ring's colours: orange for work, blue for the rest (design §3.4). Never used for text. */
export const RING_COLORS: Record<PhaseKind, string> = {
  countdown: "#4DA8FF",
  work: "#FF8A3D",
  switch: "#4DA8FF",
  rest: "#4DA8FF",
};

/** What the timer shows: the header with Slut, the stations, the ring and the controls. */
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
  /** Slut's question shows. */
  asking: boolean;
  onRingTap: () => void;
  onPrevious: () => void;
  onPause: () => void;
  onResume: () => void;
  onNext: () => void;
  /** Slut's first tap. */
  onAskEnd: () => void;
  /** The question's Ja. */
  onConfirmEnd: () => void;
  /** The question's Nej. */
  onKeepGoing: () => void;
}

export function renderTimer(ctx: TimerContext): TemplateResult {
  const { t, view, countdown } = ctx;
  const phase = view.phase!;
  const paused = view.status === "paused";
  const word = t(`flow.phase.${paused ? "paused" : countdown.kind}`);
  const next = view.next_phase;
  const then = next && !countdown.ahead ? t(`flow.then.${next.kind}`, { seconds: next.duration }) : undefined;
  const theRing = ring({
    label: word,
    word,
    max: countdown.duration,
    value: countdown.seconds,
    fraction: countdown.fraction,
    color: RING_COLORS[countdown.kind],
    then,
    onTap: () => ctx.onRingTap(),
  });
  const stations = view.stations ?? [];
  return html`
    ${renderHeader(ctx, phase.round, phase.interval)} ${renderReach(t, ctx.reach)} ${renderSound(t, ctx.sound)}
    ${renderError(ctx.error)}
    ${stations.length === 1
      ? renderSolo(ctx, theRing)
      : html`<div class="duo">${renderPanel(ctx, 0)} ${theRing} ${renderPanel(ctx, 1)}</div>`}
    <div class="controls">
      <button @click=${() => ctx.onPrevious()}>${t("flow.previous")}</button>
      <button class="main" @click=${() => (paused ? ctx.onResume() : ctx.onPause())}>
        ${t(paused ? "flow.resume" : "flow.pause")}
      </button>
      <button @click=${() => ctx.onNext()}>${t("flow.next")}</button>
    </div>
  `;
}

/** Runde, Interval, the elapsed time against the planned, and Slut with its question. */
function renderHeader(ctx: TimerContext, round: number, interval: number) {
  const { t, view } = ctx;
  return html`
    <header class="top">
      <span>${t("flow.round", { round, rounds: view.totals.rounds })}</span>
      <span>
        ${view.totals.stations === undefined
          ? t("flow.interval", { interval })
          : t("flow.interval_of", { interval, intervals: view.totals.stations })}
      </span>
      <span class="elapsed">
        ${t("flow.elapsed", { elapsed: clock(ctx.elapsed), planned: clock(view.totals.planned) })}
      </span>
      <span class="end">
        ${ctx.asking
          ? html`
              <span class="question">${t("flow.end_confirm")}</span>
              <button @click=${() => ctx.onConfirmEnd()}>${t("flow.yes")}</button>
              <button class="slot" @click=${() => ctx.onKeepGoing()}>${t("flow.no")}</button>
            `
          : html`<button class="slot" @click=${() => ctx.onAskEnd()}>${t("flow.end")}</button>`}
      </span>
    </header>
  `;
}

/** One person: the current station big with its GIF, the ring, and Næste beside them. */
function renderSolo(ctx: TimerContext, theRing: TemplateResult) {
  const { t, view } = ctx;
  const station = view.stations![0];
  const person = view.participants[0];
  return html`
    <div class="solo">
      <section class="now" aria-label=${person?.name ?? ""}>
        ${renderImage(ctx.imageOf, station.current, "gif", "gif")}
        <span class="station">${t("flow.station", { number: station.current.number })}</span>
        <span class="exercise">${station.current.name}</span>
      </section>
      ${theRing} ${station.next ? renderNext(ctx, station.next) : nothing}
    </div>
  `;
}

function renderNext(ctx: TimerContext, next: SessionStation) {
  const { t } = ctx;
  const label = t("flow.next_label");
  return html`
    <section class="next" aria-label=${label}>
      <span class="label">${label}</span>
      ${renderThumbnail(ctx.imageOf, next)}
      <span>${t("flow.station", { number: next.number })}</span>
      <span>${next.name}</span>
    </section>
  `;
}

/** A person's panel in the two-person layout, in the person's colour. */
function renderPanel(ctx: TimerContext, index: number) {
  const { t, view } = ctx;
  const person = view.participants[index];
  const station = view.stations?.[index];
  if (!person || !station) return nothing;
  return html`
    <section class="panel" aria-label=${person.name} style="--person-color: ${ctx.colors[index]}">
      <div class="who">
        <span class="badge"></span>
        <span class="name">${person.name}</span>
        <span class="station">${t("flow.station", { number: station.current.number })}</span>
      </div>
      ${renderImage(ctx.imageOf, station.current, "gif", "gif")}
      <span class="exercise">${station.current.name}</span>
      ${station.next
        ? html`<span class="line">
            ${t("flow.next_station", { number: station.next.number, exercise: station.next.name })}
          </span>`
        : nothing}
    </section>
  `;
}

export const timerStyles = css`
  header.top {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 32px;
    align-items: center;
    font-size: 1.5rem;
  }
  /* Each part stays on one line; at a narrow width whole parts wrap instead. */
  header.top > span,
  header.top .question {
    white-space: nowrap;
  }
  header.top .elapsed {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
  }
  header.top .end {
    display: flex;
    gap: 16px;
    align-items: center;
  }
  button.slot {
    min-width: 120px;
  }
  .solo,
  .duo {
    display: flex;
    gap: 32px;
    align-items: center;
    justify-content: center;
    margin: 24px 0;
  }
  .now,
  .panel,
  .next {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    text-align: center;
  }
  .now .exercise {
    font-size: 2rem;
    font-weight: 500;
  }
  .panel {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    padding: 16px;
    border: 4px solid var(--person-color);
    border-radius: 16px;
  }
  .panel .who {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .panel .name,
  .panel .exercise {
    font-weight: 500;
  }
  .next .label {
    color: var(--secondary-text-color);
    font-weight: 500;
  }
  .gif {
    width: 280px;
    height: 280px;
    border-radius: 16px;
    object-fit: cover;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .duo .gif {
    width: min(200px, 30cqi);
    height: min(200px, 30cqi);
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
    font-size: 1.5rem;
    font-weight: 500;
    letter-spacing: 0.1em;
  }
  .ring .seconds {
    font-size: 6rem;
    font-weight: 500;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .ring .then {
    color: var(--secondary-text-color);
  }
  .controls {
    display: flex;
    gap: 32px;
    align-items: center;
    justify-content: center;
  }
  /* A portrait tablet (about 800 px wide): nothing scrolls sideways. */
  @container (max-width: 1000px) {
    header.top {
      gap: 12px 20px;
      font-size: 1.25rem;
    }
    /* Slut, and its question in its place, get a line of their own, right-aligned, so Nej
       lands where Slut was. */
    header.top .end {
      flex-basis: 100%;
      justify-content: flex-end;
    }
    /* Two people: both panels side by side, the ring below them. */
    .duo {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      grid-template-areas:
        "first second"
        "ring ring";
      gap: 24px;
      align-items: stretch;
    }
    .duo > .panel:first-child {
      grid-area: first;
    }
    .duo > .panel:last-child {
      grid-area: second;
    }
    .duo > .ring {
      grid-area: ring;
      justify-self: center;
    }
    /* One person: the station and Næste side by side, the ring below them. */
    .solo {
      display: grid;
      grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
      grid-template-areas:
        "now next"
        "ring ring";
      gap: 24px;
    }
    .solo > .now {
      grid-area: now;
    }
    .solo > .next {
      grid-area: next;
    }
    .solo > .ring {
      grid-area: ring;
      justify-self: center;
    }
    .solo .gif {
      width: min(280px, 50cqi);
      height: min(280px, 50cqi);
    }
  }
`;
