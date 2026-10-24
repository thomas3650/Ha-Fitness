import { type TemplateResult, css, html } from "lit";

import { personColor } from "../people";
import { type ImageOf, type Translate, renderBack, renderError, renderThumbnail } from "./shared";

/** An active program, as `ha_fitness/programs` returns it (spec §4). */
export interface Program {
  id: number;
  name: string;
  rounds: number;
  work_seconds: number;
  switch_seconds: number;
  round_rest_seconds: number;
  countdown_seconds: number;
  total_minutes: number;
  stations: { exercise_id: string; name: string }[];
}

/** A person, as `ha_fitness/people` returns it (spec §4). */
export interface Person {
  id: number;
  name: string;
}

/** What the details step shows: the program, who trains, Start and Tilbage. */
export interface DetailsContext {
  t: Translate;
  /** The active programs: undefined while loading, null if the fetch failed. */
  programs: Program[] | null | undefined;
  /** The program the card opened, once found among them. */
  program: Program | undefined;
  /** The people, in people order. */
  people: Person[];
  /** The chosen people's ids. */
  selected: ReadonlySet<number>;
  /** How many people the program takes. */
  maxSelected: number;
  busy: boolean;
  error: string | undefined;
  imageOf: ImageOf;
  onToggle: (person: Person) => void;
  onStart: () => void;
  onBack: () => void;
}

export function renderDetails(ctx: DetailsContext): TemplateResult {
  const { t } = ctx;
  if (ctx.programs === undefined) return html`${renderBack(t, ctx.onBack)}`;
  const program = ctx.program;
  if (!program) {
    return html`
      <div class="error" role="alert">${t(ctx.programs === null ? "flow.error.unavailable" : "flow.error.not_found")}</div>
      ${renderBack(t, ctx.onBack)}
    `;
  }
  const people = ctx.people;
  const max = ctx.maxSelected;
  return html`
    <h2>${program.name}</h2>
    <p class="line">
      ${t("flow.summary", {
        minutes: t("today.minutes", { count: program.total_minutes }),
        rounds: t("today.rounds", { count: program.rounds }),
      })}
    </p>
    <p class="line">
      ${t("flow.seconds", {
        work: program.work_seconds,
        switch: program.switch_seconds,
        rest: program.round_rest_seconds,
      })}
    </p>
    <ol class="stations" aria-label=${t("flow.stations")}>
      ${program.stations.map(
        (station, index) => html`
          <li>
            <span class="number">${index + 1}</span>
            ${renderThumbnail(ctx.imageOf, station)}
            <span>${station.name}</span>
          </li>
        `,
      )}
    </ol>
    ${people.length === 0
      ? html`<p class="line">${t("flow.no_people")}</p>`
      : html`
          <fieldset class="chips">
            <legend>${t("flow.who")}</legend>
            ${people.map((person, index) => {
              const chosen = ctx.selected.has(person.id);
              return html`
                <button
                  class="chip"
                  style="--person-color: ${personColor(index)}"
                  aria-pressed=${chosen ? "true" : "false"}
                  ?disabled=${ctx.busy || (!chosen && ctx.selected.size >= max)}
                  @click=${() => ctx.onToggle(person)}
                >
                  ${person.name}
                </button>
              `;
            })}
          </fieldset>
        `}
    ${renderError(ctx.error)}
    <div class="actions">
      <button class="main" ?disabled=${ctx.busy || ctx.selected.size === 0} @click=${() => ctx.onStart()}>
        ${t("flow.start")}
      </button>
      ${renderBack(t, ctx.onBack)}
    </div>
  `;
}

export const detailsStyles = css`
  .stations li {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 8px 0;
  }
  .number {
    min-width: 1.5em;
    font-weight: 500;
    color: var(--secondary-text-color);
  }
`;
