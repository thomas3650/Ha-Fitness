import { type TemplateResult, css, html } from "lit";

import type { SessionView } from "../overlay";
import { type Translate, clock } from "./shared";

/** What done shows: counted or ended, the time, the rounds, who trained, and Luk. */
export interface DoneContext {
  t: Translate;
  view: SessionView;
  /** Each participant's colour, in the order of `view.participants`. */
  colors: string[];
  onClose: () => void;
}

export function renderDone(ctx: DoneContext): TemplateResult {
  const { t, view } = ctx;
  if (!view.counted) {
    return html`
      <h2>${t("flow.done.ended")}</h2>
      <div class="actions">
        <button class="main" @click=${() => ctx.onClose()}>${t("flow.close")}</button>
      </div>
    `;
  }
  return html`
    <h2>${t("flow.done.counted")}</h2>
    <p class="line">
      <span>${t("flow.done.time")}</span>
      <span class="big">${clock(view.time_trained)}</span>
    </p>
    <p class="big">${t("flow.done.rounds", { done: view.rounds_completed, rounds: view.totals.rounds })}</p>
    <ul class="starts" aria-label=${t("flow.done.who")}>
      ${view.participants.map(
        (person, index) => html`
          <li style="--person-color: ${ctx.colors[index]}">
            <span class="badge"></span>${person.name}
          </li>
        `,
      )}
    </ul>
    <div class="actions">
      <button class="main" @click=${() => ctx.onClose()}>${t("flow.close")}</button>
    </div>
  `;
}

export const doneStyles = css`
  .big {
    font-size: 2rem;
    font-weight: 500;
  }
`;
