import { type TemplateResult, css, html, nothing } from "lit";

import { iconButton } from "../icon-button";
import type { SessionView } from "../overlay";
import { personTextColor } from "../people";
import { ring } from "../ring";
import {
  type Countdown,
  type ImageOf,
  PHASE_TEXT_COLORS,
  RING_COLORS,
  type ReachNote,
  type SoundButton,
  type Translate,
  renderError,
  renderReach,
  renderSound,
  renderThumbnail,
} from "./shared";

/**
 * What get ready shows (the `GetReady` mockup, #62): the countdown in a ring; the summary card over
 * a card per person at their start station; and Start nu (Fortsæt for a paused countdown) with
 * Annullér beside it.
 */
export interface ReadyContext {
  t: Translate;
  view: SessionView;
  countdown: Countdown;
  /** Each participant's colour, in the order of `view.participants`. */
  colors: string[];
  imageOf: ImageOf;
  reach: ReachNote;
  sound: SoundButton;
  error: string | undefined;
  onStartNow: () => void;
  onResume: () => void;
  onCancel: () => void;
}

export function renderReady(ctx: ReadyContext): TemplateResult {
  const { t, view } = ctx;
  const paused = view.status === "paused";
  return html`
    ${renderReach(t, ctx.reach)} ${renderSound(t, ctx.sound)}
    <div class="ready">
      <div class="countdown">${renderRing(ctx)}</div>
      ${renderStarts(ctx)}
    </div>
    ${renderError(ctx.error)}
    <div class="actions ready-actions">
      ${paused
        ? iconButton({
            icon: "mdi:play",
            label: t("flow.resume"),
            text: t("flow.resume"),
            className: "main",
            onClick: ctx.onResume,
          })
        : html`<button class="main" @click=${() => ctx.onStartNow()}>${t("flow.start_now")}</button>`}
      <button class="cancel soft" @click=${() => ctx.onCancel()}>${t("flow.cancel")}</button>
    </div>
  `;
}

/** "Onsdag · 2 personer · 5 runder · 29 min": the minutes rounded as the add-on's `total_minutes`. */
function summary(t: Translate, view: SessionView): string {
  return t("flow.ready_summary", {
    program: view.program_name,
    people: t("flow.people", { count: view.participants.length }),
    rounds: t("flow.round_count", { count: view.totals.rounds }),
    minutes: t("flow.minutes", { count: Math.floor((view.totals.planned + 30) / 60) }),
  });
}

/** The countdown's ring: "GØR KLAR" over the seconds; at local zero, the next phase's word. No tap. */
function renderRing(ctx: ReadyContext): TemplateResult {
  const { countdown } = ctx;
  const word = ctx.t(`flow.phase.${countdown.kind}`);
  return ring({
    label: word,
    word,
    max: countdown.duration,
    value: countdown.seconds,
    fraction: countdown.fraction,
    color: RING_COLORS[countdown.kind],
    wordColor: PHASE_TEXT_COLORS[countdown.kind],
  });
}

/**
 * The summary card (PAUSET beside the summary while paused) over a card per participant, numbered
 * in participant order.
 */
function renderStarts(ctx: ReadyContext): TemplateResult {
  const { t, view } = ctx;
  return html`
    <section class="ready-starts">
      <div class="ready-summary card">
        <span>${summary(t, view)}</span>
        ${view.status === "paused" ? html`<span class="pill paused">${t("flow.paused")}</span>` : nothing}
      </div>
      <ul>
        ${view.participants.map((person, index) => {
          const station = view.stations?.[index]?.current;
          return html`
            <li
              class="ready-card card"
              style="--person-color: ${ctx.colors[index]}; --person-text: ${personTextColor(ctx.colors[index])}"
            >
              <span class="number">${index + 1}</span>
              ${station ? renderThumbnail(ctx.imageOf, station) : nothing}
              <span class="where">
                <span class="station">
                  ${t("flow.start_station", { name: person.name, number: station?.number ?? "" })}
                </span>
                <span class="exercise">${station?.name ?? ""}</span>
              </span>
            </li>
          `;
        })}
      </ul>
    </section>
  `;
}

/* Landscape: the ring on the left, the cards on the right. Portrait (800 px wide): they stack. */
export const readyStyles = css`
  .ready-actions button.main {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
  .ready-actions button.main ha-icon {
    --mdc-icon-size: 32px;
  }
  /* Annullér beside Start nu (or Fortsæt) at the same width, height, radius and font, in the soft
     grey style, so Start nu stays the main button. */
  .ready-actions button.main,
  .ready-actions button.cancel {
    box-sizing: border-box;
    width: 240px;
    min-height: 96px;
    border-radius: 48px;
    font-size: 1.5rem;
  }
  .pill {
    padding: 10px 18px;
    border-radius: 999px;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .pill.paused {
    font-weight: 500;
    letter-spacing: 0.1em;
  }
  /* Landscape: the ring and the cards start level at the top. */
  .ready {
    display: flex;
    align-items: start;
    justify-content: center;
    gap: 64px;
    margin: 32px 0;
  }
  /* Get ready's countdown, readable across a kitchen: a larger ring and number than the timer's. */
  .countdown .ring {
    width: 400px;
    height: 400px;
    cursor: default;
  }
  .countdown .ring .seconds {
    font-size: 10rem;
  }
  .ready-starts {
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: min(440px, 100%);
  }
  /* The summary takes the cards' look and width (D52). */
  .ready-summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px 16px;
    padding: 18px 20px;
    border-radius: 20px;
    font-size: 1.25rem;
  }
  .ready-summary .pill {
    margin-left: auto;
  }
  .ready-starts ul {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin: 0;
  }
  .ready-starts .ready-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px;
    border-radius: 20px;
    font-size: 1.25rem;
  }
  .ready-card .number {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: var(--person-color);
    color: var(--person-text);
    font-size: 1.5rem;
    font-weight: 700;
  }
  .ready-card .thumb {
    flex: none;
    width: 112px;
    height: 112px;
  }
  .ready-card .where {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .ready-card .station {
    color: var(--secondary-text-color);
  }
  .ready-card .exercise {
    font-size: 1.75rem;
    font-weight: 700;
  }
  .ready-actions {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 16px;
  }
  @container (max-width: 1000px) {
    .ready {
      flex-direction: column;
      align-items: center;
      gap: 32px;
    }
  }
`;
