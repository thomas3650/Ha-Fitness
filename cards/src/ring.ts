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
  onTap?: () => void;
}

const SIZE = 320;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The timer's ring: an SVG circle that empties as the phase runs, exposed as a progressbar with
 * the seconds left. The texts sit in the middle. A tap is a pointer shortcut only: the ring has no
 * button role and no tab stop. It renders into the caller's shadow root.
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
      @click=${() => options.onTap?.()}
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
      </div>
    </div>
  `;
}
