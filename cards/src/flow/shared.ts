import { type TemplateResult, css, html, nothing } from "lit";

import type { Vars } from "../i18n";
import type { ImageKind } from "../images";
import type { PhaseKind } from "../overlay";

/** The flow's texts in the card's language. */
export type Translate = (key: string, vars?: Vars) => string;

/** An exercise as a step shows it. */
export interface Exercise {
  exercise_id: string;
  name: string;
}

/** An exercise's image URL by kind: undefined or null while it loads or when it has none. */
export type ImageOf = (exerciseId: string, kind: ImageKind) => string | null | undefined;

/** The unreachable note: Luk shows once it has lasted long enough. */
export interface ReachNote {
  reachable: boolean;
  canClose: boolean;
  onClose: () => void;
}

/** The "Tryk for lyd" button: shown while no sound can play, but a tap could bring it. */
export interface SoundButton {
  shown: boolean;
  onTap: () => void;
}

/** What the timer shows of a phase at this moment (spec §5.3). */
export interface Countdown {
  /** The phase kind whose word shows: the next one at local zero. */
  kind: PhaseKind;
  /** The length of the phase shown, in seconds. */
  duration: number;
  /** The seconds left, rounded up. */
  seconds: number;
  /** The share of the phase left, 0..1. */
  fraction: number;
  /** True at local zero, before the message of the next phase has come. */
  ahead: boolean;
}

/** `seconds` as m:ss, or h:mm:ss from an hour. */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

/** An exercise's image, or a neutral placeholder while it loads or when it has none. */
export function renderImage(imageOf: ImageOf, station: Exercise, kind: ImageKind, className: string) {
  const url = imageOf(station.exercise_id, kind);
  return url
    ? html`<img class=${className} src=${url} alt=${station.name} />`
    : html`<span class=${className} role="img" aria-label=${station.name}></span>`;
}

export function renderThumbnail(imageOf: ImageOf, station: Exercise) {
  return renderImage(imageOf, station, "thumbnail", "thumb");
}

export function renderError(error: string | undefined) {
  return error ? html`<div class="error" role="alert">${error}</div>` : nothing;
}

/** The unreachable note, and Luk once it has lasted 10 s. */
export function renderReach(t: Translate, reach: ReachNote) {
  if (reach.reachable) return nothing;
  return html`
    <div class="note">
      <span role="status">${t("flow.unreachable")}</span>
      ${reach.canClose ? html`<button @click=${() => reach.onClose()}>${t("flow.close")}</button>` : nothing}
    </div>
  `;
}

/** The "Tryk for lyd" button, while no sound can play. */
export function renderSound(t: Translate, sound: SoundButton) {
  if (!sound.shown) return nothing;
  return html`<button class="sound" @click=${() => sound.onTap()}>${t("flow.tap_for_sound")}</button>`;
}

export function renderBack(t: Translate, onBack: () => void): TemplateResult {
  return html`<button @click=${() => onBack()}>${t("flow.back")}</button>`;
}

/** The page layout, the buttons, the chips and what more than one step uses. */
export const sharedStyles = css`
  /* The flow fills the overlay's dialog; each step is centred, and on a large screen kept to a
     readable width, on a landscape (1368×912) and a portrait (800×1280) tablet alike. */
  :host {
    display: flex;
    flex-direction: column;
    /* Centred while it fits; content taller than the screen starts at the top and scrolls. */
    justify-content: safe center;
    box-sizing: border-box;
    min-height: 100%;
    padding: 32px;
    color: var(--primary-text-color);
    background: var(--primary-background-color);
    font-size: 1.25rem;
  }
  /* The page is the container the sizes below follow (cqi: 1% of its width). */
  .page {
    box-sizing: border-box;
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
    container-type: inline-size;
  }
  /* Done: one centred column. The other steps use the wide page. */
  .page.column {
    max-width: 720px;
  }
  .page.column h2,
  .page.column > .line {
    text-align: center;
  }
  .page.column .actions {
    justify-content: center;
  }
  .page.centred {
    text-align: center;
  }
  .page.centred .starts li {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  h2 {
    margin: 0 0 8px;
    font-size: 2.5rem;
    font-weight: 500;
  }
  .line {
    color: var(--secondary-text-color);
    margin: 4px 0;
  }
  ol,
  ul {
    list-style: none;
    margin: 16px 0;
    padding: 0;
  }
  .thumb {
    width: 64px;
    height: 64px;
    border-radius: 8px;
    object-fit: cover;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .chips {
    display: flex;
    gap: 16px;
    margin: 16px 0;
    border: none;
    padding: 0;
  }
  .chips legend {
    padding: 0;
    margin-bottom: 8px;
    color: var(--secondary-text-color);
  }
  button {
    min-height: 48px;
    min-width: 96px;
    padding: 0 24px;
    border-radius: 24px;
    border: 2px solid var(--primary-color);
    background: none;
    color: var(--primary-text-color);
    font: inherit;
    font-weight: 500;
    cursor: pointer;
  }
  button.chip {
    border-color: var(--person-color);
    border-width: 3px;
  }
  button.chip[aria-pressed="true"] {
    background: color-mix(in srgb, var(--person-color) 25%, transparent);
  }
  button.main {
    min-height: 96px;
    min-width: 192px;
    border-radius: 48px;
    font-size: 1.5rem;
    background: var(--primary-color);
    color: var(--text-primary-color);
  }
  button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .actions {
    display: flex;
    gap: 24px;
    align-items: center;
    margin-top: 32px;
  }
  .badge {
    display: inline-block;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    margin-right: 12px;
    background: var(--person-color);
  }
  .starts li {
    padding: 8px 0;
    font-size: 1.5rem;
  }
  .error {
    color: var(--error-color);
    margin: 16px 0;
  }
  .note {
    display: flex;
    gap: 24px;
    align-items: center;
    margin: 16px 0;
    color: var(--secondary-text-color);
  }
`;
