import { type TemplateResult, css, html, nothing } from "lit";

import { iconButton } from "../icon-button";
import { personColor } from "../people";
import { type ImageOf, type Translate, clock, renderError, renderImage } from "./shared";
import { RING_COLORS } from "./timer";

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
  /** The planned length in seconds; missing from an add-on older than the UI refresh. */
  total_seconds?: number;
  /** The distinct equipment of the stations, in station order; missing from an older add-on. */
  equipment?: string[];
  stations: { exercise_id: string; name: string }[];
}

/** A person, as `ha_fitness/people` returns it (spec §4). */
export interface Person {
  id: number;
  name: string;
}

/** What the details step shows: the program's pictures and facts, who trains, Start and Tilbage. */
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

/** The equipment the language files name, by its stored value in lower case (spec §3.2). */
const EQUIPMENT_KEYS: Record<string, string> = {
  dumbbell: "equipment.dumbbell",
  band: "equipment.band",
  kettlebell: "equipment.kettlebell",
  "resistance band": "equipment.resistance_band",
};

/** A known equipment value in the card's language; any other value as stored, as exercise names are. */
function equipmentName(t: Translate, value: string): string {
  const key = EQUIPMENT_KEYS[value.trim().toLowerCase()];
  return key ? t(key) : value;
}

/** Tilbage: the arrow at the top left, named by its label. */
function renderBackArrow(t: Translate, onBack: () => void): TemplateResult {
  return iconButton({ icon: "mdi:arrow-left", label: t("flow.back"), className: "back", onClick: onBack });
}

export function renderDetails(ctx: DetailsContext): TemplateResult {
  const { t } = ctx;
  if (ctx.programs === undefined) return html`<header class="top">${renderBackArrow(t, ctx.onBack)}</header>`;
  const program = ctx.program;
  if (!program) {
    return html`
      <header class="top">${renderBackArrow(t, ctx.onBack)}</header>
      <div class="error" role="alert">${t(ctx.programs === null ? "flow.error.unavailable" : "flow.error.not_found")}</div>
    `;
  }
  return html`
    <header class="top">
      ${renderBackArrow(t, ctx.onBack)}
      <h2>${program.name}</h2>
    </header>
    <div class="panels">
      <section class="panel pictures">
        <p class="lead">
          ${t("flow.stations_line", { stations: t("today.stations", { count: program.stations.length }) })}
        </p>
        <ol class="grid" aria-label=${t("flow.stations")}>
          ${program.stations.map(
            (station, index) => html`
              <li>
                ${renderImage(ctx.imageOf, station, "thumbnail", "picture")}
                <span class="name">${index + 1} · ${station.name}</span>
              </li>
            `,
          )}
        </ol>
      </section>
      <section class="panel facts">
        ${renderChips(ctx)}
        <dl>
          ${renderFacts(t, program)}
        </dl>
        ${renderError(ctx.error)}
        ${iconButton({
          icon: "mdi:play",
          label: t("flow.start"),
          text: t("flow.start"),
          className: "main start",
          disabled: ctx.busy || ctx.selected.size === 0,
          onClick: ctx.onStart,
        })}
        <p class="hint">${t("flow.ask_claude")}</p>
      </section>
    </div>
  `;
}

/** "Hvem træner?" with a chip per person, in people order (step 5's rules). */
function renderChips(ctx: DetailsContext): TemplateResult {
  const { t, people } = ctx;
  if (people.length === 0) return html`<p class="line">${t("flow.no_people")}</p>`;
  return html`
    <fieldset class="chips">
      <legend>${t("flow.who")}</legend>
      ${people.map((person, index) => {
        const chosen = ctx.selected.has(person.id);
        return html`
          <button
            class="chip"
            style="--person-color: ${personColor(index)}"
            aria-pressed=${chosen ? "true" : "false"}
            ?disabled=${ctx.busy || (!chosen && ctx.selected.size >= ctx.maxSelected)}
            @click=${() => ctx.onToggle(person)}
          >
            ${person.name}
          </button>
        `;
      })}
    </fieldset>
  `;
}

/** Runder, Arbejde / skift, the round rest above 0, the equipment when there is any, and the total. */
function renderFacts(t: Translate, program: Program): TemplateResult {
  const seconds = (value: number) => t("flow.seconds", { seconds: value });
  const equipment = program.equipment ?? [];
  const total = program.total_seconds ?? program.total_minutes * 60;
  return html`
    <div class="row">
      <dt>${t("flow.rounds")}</dt>
      <dd>${program.rounds}</dd>
    </div>
    <div class="row">
      <dt>${t("flow.work_switch")}</dt>
      <dd>
        <span class="phase" style="--phase-color: ${RING_COLORS.work}">${seconds(program.work_seconds)}</span>
        /
        <span class="phase" style="--phase-color: ${RING_COLORS.switch}">${seconds(program.switch_seconds)}</span>
      </dd>
    </div>
    ${program.round_rest_seconds > 0
      ? html`
          <div class="row">
            <dt>${t("flow.round_rest")}</dt>
            <dd>${seconds(program.round_rest_seconds)}</dd>
          </div>
        `
      : nothing}
    ${equipment.length > 0
      ? html`
          <div class="row stacked">
            <dt>${t("flow.need")}</dt>
            <dd>
              <!-- The space after each chip keeps the words apart in the row's text. -->
              <ul class="equipment" aria-label=${t("flow.need")}>
                ${equipment.map((value) => html`<li>${equipmentName(t, value)}</li> `)}
              </ul>
            </dd>
          </div>
        `
      : nothing}
    <div class="row total">
      <dt>${t("flow.total")}</dt>
      <dd>${clock(total)}</dd>
    </div>
  `;
}

/* Landscape: the pictures on the left, the facts in a fixed column on the right (the
   WorkoutDetails mockup). Portrait (800 px wide): the panels stack. */
export const detailsStyles = css`
  .top {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }
  .top h2 {
    margin: 0;
  }
  button.back {
    min-width: 48px;
    width: 48px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .panels {
    display: flex;
    gap: 24px;
    align-items: stretch;
  }
  .panel {
    box-sizing: border-box;
    padding: 24px;
    border-radius: var(--ha-card-border-radius, 12px);
    background: var(--card-background-color, var(--primary-background-color));
    border: 1px solid var(--divider-color);
  }
  .pictures {
    flex: 1;
    min-width: 0;
  }
  .facts {
    flex: none;
    width: 380px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  @container (max-width: 860px) {
    .panels {
      flex-direction: column;
    }
    .facts {
      width: auto;
    }
  }
  .lead {
    margin: 0 0 16px;
    font-weight: 500;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 12px;
    margin: 0;
  }
  .grid li {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px;
    border-radius: 12px;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .picture {
    display: block;
    width: 100%;
    aspect-ratio: 1;
    border-radius: 8px;
    object-fit: contain;
    background: #fff;
  }
  .name {
    font-size: 1rem;
    font-weight: 500;
  }
  .facts .chips {
    margin: 0 0 8px;
    flex-wrap: wrap;
  }
  dl {
    margin: 0;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 16px;
    padding: 12px 0;
    border-top: 1px solid var(--divider-color);
  }
  .row.stacked {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  dt {
    color: var(--secondary-text-color);
  }
  dd {
    margin: 0;
    font-weight: 500;
  }
  /* The phase colours mark the seconds with a dot; the numbers keep the text colour, for contrast. */
  .phase::before {
    content: "";
    display: inline-block;
    width: 10px;
    height: 10px;
    margin-right: 6px;
    border-radius: 50%;
    background: var(--phase-color);
  }
  .equipment {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0;
  }
  .equipment li {
    padding: 6px 14px;
    border-radius: 16px;
    font-size: 1rem;
    font-weight: 400;
    background: var(--secondary-background-color, var(--divider-color));
  }
  .row.total {
    margin-top: auto;
  }
  .row.total dd {
    font-size: 2.5rem;
    font-weight: 600;
  }
  button.start {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
  button.start ha-icon {
    --mdc-icon-size: 32px;
  }
  .hint {
    margin: 4px 0 0;
    text-align: center;
    font-size: 0.875rem;
    color: var(--secondary-text-color);
  }
`;
