import { html, nothing, svg } from "lit";

/** What the ring shows (spec §5.2 step 3). */
export interface RingOptions {
  /** The ring's accessible name: the phase word. */
  label: string;
  /** The phase's length in seconds: the progressbar's maximum. */
  max: number;
  /** The whole seconds left, rounded up: the progressbar's value and the big number. */
  value: number;
  /** The share of the phase left, 0..1, with fractions, so the ring moves smoothly. */
  fraction: number;
  /** The ring's colour; text never takes it (the word takes `wordColor`). */
  color: string;
  /** The phase word's colour, darker than the ring's for contrast; inherited when missing. */
  wordColor?: string;
  /** The phase word over the seconds. */
  word: string;
  /** The line under the seconds ("sekunder tilbage"), if any. */
  caption?: string;
  /**
   * Room for one more line under the caption, left empty: the timer's ring button puts its
   * "tryk for pause" there, so the texts stay centred together.
   */
  room?: boolean;
}

const SIZE = 320;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The ring: an SVG circle that empties as the phase runs, exposed as a progressbar with the
 * seconds left. The texts sit in the middle. The ring itself has no button role and no tab stop;
 * get ready's ring is only that. The timer lays a button of its own over it (D73), as a sibling,
 * so the progressbar keeps its role. It renders into the caller's shadow root.
 */
export function ring(options: RingOptions) {
  const fraction = Math.min(1, Math.max(0, options.fraction));
  return html`
    <div
      class="ring"
      role="progressbar"
      aria-label=${options.label}
      aria-valuemin="0"
      aria-valuemax=${options.max}
      aria-valuenow=${options.value}
      style="--ring-color: ${options.color}${options.wordColor ? `; --word-color: ${options.wordColor}` : ""}"
    >
      <svg viewBox="0 0 ${SIZE} ${SIZE}" aria-hidden="true">
        ${svg`
          <circle class="track" cx=${SIZE / 2} cy=${SIZE / 2} r=${RADIUS} stroke-width=${STROKE} fill="none" />
          <circle
            class="left"
            cx=${SIZE / 2}
            cy=${SIZE / 2}
            r=${RADIUS}
            stroke-width=${STROKE}
            fill="none"
            stroke-linecap="round"
            stroke-dasharray=${CIRCUMFERENCE}
            stroke-dashoffset=${CIRCUMFERENCE * (1 - fraction)}
            transform="rotate(-90 ${SIZE / 2} ${SIZE / 2})"
          />
        `}
      </svg>
      <div class="middle">
        <span class="word">${options.word}</span>
        <span class="seconds">${options.value}</span>
        ${options.caption ? html`<span class="caption">${options.caption}</span>` : nothing}
        ${options.room ? html`<span class="room"></span>` : nothing}
      </div>
    </div>
  `;
}
