import { type TemplateResult, css, html, nothing } from "lit";

import { WEEKDAYS } from "../i18n";
import { iconButton } from "../icon-button";
import type { Feeling, SessionView } from "../overlay";
import { type Translate, clock, renderError } from "./shared";

/** A participant's streak, as the stats have it. */
export interface Streak {
  name: string;
  streak: number;
  color: string;
}

/**
 * What done shows (the `Complete` mockup): the check, the title, the program and the date, the
 * tiles, "How did it feel?" for a completed session, and Færdig.
 */
export interface DoneContext {
  t: Translate;
  view: SessionView;
  /** The participants' streaks, once the stats have come; none while there is nothing to show. */
  streaks: Streak[];
  /** The text of a failed feeling tap. */
  feelingError?: string;
  onFeeling: (feeling: Feeling) => void;
  onClose: () => void;
}

const MONTHS = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];
const FEELINGS: Feeling[] = ["too_easy", "just_right", "too_hard"];

/** The browser's local date of an ISO time, as "torsdag 22. oktober". */
function localDate(t: Translate, iso: string): string {
  const date = new Date(iso);
  return t("flow.done.date", {
    weekday: t(`weekday.${WEEKDAYS[date.getDay()]}`),
    day: date.getDate(),
    month: t(`month.${MONTHS[date.getMonth()]}`),
  });
}

export function renderDone(ctx: DoneContext): TemplateResult {
  const { t, view } = ctx;
  // Ended and not counted: no check, date, streak or feeling (spec §2.7).
  const counted = view.counted;
  const title = !counted
    ? t("flow.done.ended")
    : view.status === "completed"
      ? t("flow.done.complete")
      : t("flow.done.ended_after", { done: view.rounds_completed, rounds: view.totals.rounds });
  // The date the workout started; one ended before work began has only its end.
  const when = view.started_at ?? view.ended_at;
  return html`
    ${counted
      ? html`<div class="done-check" role="img" aria-label=${t("flow.done.check")}>
          <ha-icon icon="mdi:check" aria-hidden="true"></ha-icon>
        </div>`
      : nothing}
    <h2>${title}</h2>
    ${counted && when
      ? html`<p class="line">${t("flow.done.subtitle", { program: view.program_name, date: localDate(t, when) })}</p>`
      : nothing}
    <dl class="done-tiles">
      <div class="card done-tile">
        <dt>${t("flow.done.time")}</dt>
        <dd class="done-value">${clock(view.time_trained)}</dd>
      </div>
      <div class="card done-tile">
        <dt>${t("flow.done.rounds")}</dt>
        <dd class="done-value">
          ${t("flow.done.rounds_value", { done: view.rounds_completed, rounds: view.totals.rounds })}
        </dd>
      </div>
      <div class="card done-tile">
        <dt>${t("flow.done.trained")}</dt>
        <dd class="done-names">${view.participants.map((person) => person.name).join(", ")}</dd>
      </div>
      ${counted && ctx.streaks.length ? renderStreaks(ctx) : nothing}
    </dl>
    ${view.status === "completed" && view.feeling !== undefined ? renderFeeling(ctx, view.feeling) : nothing}
    <div class="actions">
      <button class="main" @click=${() => ctx.onClose()}>${t("flow.done.finish")}</button>
    </div>
  `;
}

/** The streak tile: each participant's colour dot, name and streak. */
function renderStreaks(ctx: DoneContext) {
  return html`
    <div class="card done-tile streak">
      <dt>${ctx.t("flow.done.streak")}</dt>
      <dd>
        <ul class="done-streaks">
          ${ctx.streaks.map(
            (person) => html`
              <li style="--person-color: ${person.color}">
                <span class="badge"></span>${person.name} <span class="done-streak">${person.streak}</span>
              </li>
            `,
          )}
        </ul>
      </dd>
    </div>
  `;
}

/** "How did it feel?": three toggles, the chosen one marked by a check as well as by colour. */
function renderFeeling(ctx: DoneContext, chosen: Feeling | null) {
  const { t } = ctx;
  return html`
    <div class="done-feeling" role="group" aria-labelledby="done-feeling">
      <span id="done-feeling" class="done-feeling-label">${t("flow.done.feeling")}</span>
      <div class="done-feelings">
        ${FEELINGS.map((feeling) =>
          iconButton({
            icon: feeling === chosen ? "mdi:check" : undefined,
            label: t(`flow.done.feelings.${feeling}`),
            text: t(`flow.done.feelings.${feeling}`),
            pressed: feeling === chosen,
            className: "done-option",
            onClick: () => ctx.onFeeling(feeling),
          }),
        )}
      </div>
      <p class="done-hint">${t("flow.done.feeling_hint")}</p>
      ${renderError(ctx.feelingError)}
    </div>
  `;
}

export const doneStyles = css`
  .done-check {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 112px;
    height: 112px;
    margin: 0 auto 24px;
    border-radius: 50%;
    background: var(--success-color, #43a047);
    color: var(--text-primary-color, #fff);
    --mdc-icon-size: 64px;
  }
  .done-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
    margin: 32px 0 0;
    text-align: left;
  }
  .done-tile {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 20px;
    border-radius: 20px;
  }
  .done-tile.streak {
    background: color-mix(in srgb, #ff8a3d 10%, var(--card-background-color, #fff));
  }
  .done-tile.streak dt {
    color: #b54708;
  }
  .done-tile dt {
    color: var(--secondary-text-color);
    font-size: 1rem;
  }
  .done-tile dd {
    margin: 0;
  }
  .done-value {
    font-size: 2.5rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .done-names {
    font-size: 1.5rem;
    font-weight: 700;
    line-height: 1.2;
  }
  .done-streaks {
    margin: 0;
  }
  .done-streaks li {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 1.25rem;
    font-weight: 500;
  }
  .done-streaks .badge {
    margin-right: 4px;
  }
  .done-streak {
    margin-left: auto;
    font-size: 1.5rem;
    font-weight: 700;
  }
  .done-feeling {
    margin-top: 32px;
    text-align: left;
  }
  .done-feeling-label {
    display: block;
    margin-bottom: 12px;
    font-weight: 600;
  }
  .done-feelings {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }
  button.done-option {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: center;
    min-width: 0;
    min-height: 64px;
    padding: 0 12px;
    border-radius: 16px;
    border: 1px solid var(--divider-color);
  }
  button.done-option[aria-pressed="true"] {
    border: 2px solid var(--success-color, var(--primary-color));
    background: color-mix(in srgb, var(--success-color, var(--primary-color)) 15%, transparent);
  }
  .done-hint {
    margin: 12px 0 0;
    color: var(--secondary-text-color);
    font-size: 0.875rem;
  }
  /* The column on an 800 px portrait tablet: two tiles a row. */
  @container (max-width: 900px) {
    .done-tiles {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  .done-feeling .error {
    margin: 12px 0 0;
  }
`;
