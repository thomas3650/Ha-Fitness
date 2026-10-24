import { type TemplateResult, css, html } from "lit";

import type { SessionView } from "../overlay";
import { type Countdown, type ReachNote, type SoundButton, type Translate, renderError, renderReach, renderSound } from "./shared";

/** What get ready shows: the countdown, where each person starts, Start nu, Pause and Annullér. */
export interface ReadyContext {
  t: Translate;
  view: SessionView;
  countdown: Countdown;
  /** Each participant's colour, in the order of `view.participants`. */
  colors: string[];
  reach: ReachNote;
  sound: SoundButton;
  error: string | undefined;
  onStartNow: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}

export function renderReady(ctx: ReadyContext): TemplateResult {
  const { t, view } = ctx;
  const paused = view.status === "paused";
  return html`
    <h2>${view.program_name}</h2>
    ${renderReach(t, ctx.reach)} ${renderSound(t, ctx.sound)}
    <div class="count">${renderCount(ctx)}</div>
    <ul class="starts" aria-label=${t("flow.get_ready")}>
      ${view.participants.map((person, index) => {
        const station = view.stations?.[index]?.current;
        return html`
          <li style="--person-color: ${ctx.colors[index]}">
            <span class="badge"></span>
            ${t("flow.starts_at", {
              name: person.name,
              number: station?.number ?? "",
              exercise: station?.name ?? "",
            })}
          </li>
        `;
      })}
    </ul>
    ${renderError(ctx.error)}
    <div class="actions">
      <button class="main" @click=${() => ctx.onStartNow()}>${t("flow.start_now")}</button>
      <button @click=${() => (paused ? ctx.onResume() : ctx.onPause())}>
        ${t(paused ? "flow.resume" : "flow.pause")}
      </button>
      <button @click=${() => ctx.onCancel()}>${t("flow.cancel")}</button>
    </div>
  `;
}

/** The countdown's seconds; at local zero, the word of the phase that follows. */
function renderCount(ctx: ReadyContext) {
  const { countdown } = ctx;
  return countdown.ahead ? ctx.t(`flow.phase.${countdown.kind}`) : countdown.seconds;
}

export const readyStyles = css`
  /* Get ready's countdown, readable across a kitchen: larger than the timer's ring number. */
  .count {
    font-size: clamp(8rem, 30cqi, 14rem);
    font-weight: 500;
    line-height: 1;
    text-align: center;
    font-variant-numeric: tabular-nums;
    margin: 16px 0;
  }
`;
