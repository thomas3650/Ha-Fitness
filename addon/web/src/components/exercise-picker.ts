import { mdiCheckCircle, mdiDumbbell, mdiMagnify, mdiPlusCircle } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { thumbnailUrl, type ExerciseSummary } from "../api";
import { t } from "../i18n";
import { icon } from "../icons";
import { applySelectValues } from "./select-value";

/** Body weight needs no equipment, so the household always has it (website spec §2.3.2). */
const BODY_WEIGHT = "body weight";

/** The most results the panel draws at once; a search narrows the rest. */
const SHOWN = 100;

type Facet = "equipment" | "body_part" | "target";

const FACETS: Facet[] = ["equipment", "body_part", "target"];

/** The values one facet has among the exercises, sorted, as the dataset names them. */
function values(exercises: ExerciseSummary[], facet: Facet): string[] {
  return [...new Set(exercises.map((exercise) => exercise[facet]).filter((value): value is string => !!value))].sort();
}

/**
 * The library beside the editor (W3), searched and filtered in the site from the summaries of all exercises (website
 * spec §2.3.3). By default it shows the household's exercises: those whose equipment the setup has, body weight
 * always, and every custom one; "Show all" shows the rest.
 *
 * It fires `pick` (+, the exercise's id in `detail`) and `details` (a click on the name, the summary in `detail`).
 * An exercise in `inProgram` gets a ✓ instead of +.
 */
export class ExercisePicker extends LitElement {
  static override properties = {
    exercises: { attribute: false },
    error: {},
    household: { attribute: false },
    inProgram: { attribute: false },
    query: { state: true },
    filters: { state: true },
    showAll: { state: true },
    missing: { state: true },
  };

  declare exercises: ExerciseSummary[] | null;
  declare error: string | null;
  /** The setup's equipment. */
  declare household: string[];
  declare inProgram: ReadonlySet<string>;
  declare query: string;
  declare filters: Record<Facet, string>;
  declare showAll: boolean;
  /** Exercises whose thumbnail didn't load. */
  declare missing: ReadonlySet<string>;

  constructor() {
    super();
    this.exercises = null;
    this.error = null;
    this.household = [];
    this.inProgram = new Set();
    this.query = "";
    this.filters = { equipment: "", body_part: "", target: "" };
    this.showAll = false;
    this.missing = new Set();
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  protected override updated(): void {
    applySelectValues(this);
  }

  /** The exercises the search and the filters keep; names that start with the search come first. */
  private found(exercises: ExerciseSummary[]): ExerciseSummary[] {
    const household = new Set([...this.household, BODY_WEIGHT]);
    const needle = this.query.trim().toLowerCase();
    const words = needle.split(/\s+/).filter(Boolean);
    const kept = exercises.filter(
      (exercise) =>
        words.every((word) => exercise.name.toLowerCase().includes(word)) &&
        FACETS.every((facet) => !this.filters[facet] || exercise[facet] === this.filters[facet]) &&
        (this.showAll || exercise.custom || (exercise.equipment !== null && household.has(exercise.equipment))),
    );
    const first = kept.filter((exercise) => exercise.name.toLowerCase().startsWith(needle));
    const rest = kept.filter((exercise) => !exercise.name.toLowerCase().startsWith(needle));
    return [...first, ...rest];
  }

  private fire(name: "pick" | "details", detail: unknown): void {
    this.dispatchEvent(new CustomEvent(name, { detail }));
  }

  private setFilter(facet: Facet, value: string): void {
    this.filters = { ...this.filters, [facet]: value };
  }

  protected override render() {
    return html`<aside class="picker" aria-label=${t("picker.title")}>
      <h2>${t("picker.title")}</h2>
      ${this.renderBody()}
    </aside>`;
  }

  private renderBody() {
    if (this.error) return html`<p class="error">${this.error}</p>`;
    if (!this.exercises) return html`<p>${t("picker.loading")}</p>`;
    const exercises = this.exercises;
    const found = this.found(exercises);
    const shown = found.slice(0, SHOWN);
    return html`
      <label class="search">
        ${icon(mdiMagnify)}
        <input
          type="search"
          aria-label=${t("picker.search")}
          placeholder=${t("picker.search")}
          .value=${this.query}
          @input=${(event: Event) => (this.query = (event.target as HTMLInputElement).value)}
        />
      </label>
      <div class="picker-filters">
        ${FACETS.map(
          (facet) => html`<label>
            <span aria-hidden="true">${t(`picker.${facet}`)}</span>
            <select
              aria-label=${t(`picker.${facet}`)}
              data-value=${this.filters[facet]}
              @change=${(event: Event) => this.setFilter(facet, (event.target as HTMLSelectElement).value)}
            >
              <option value="">${t("picker.any")}</option>
              ${values(exercises, facet).map(
                (value) => html`<option value=${value}>${value}</option>`,
              )}
            </select>
          </label>`,
        )}
        <label class="check">
          <input
            type="checkbox"
            .checked=${this.showAll}
            @change=${(event: Event) => (this.showAll = (event.target as HTMLInputElement).checked)}
          />
          <span>${t("picker.show_all")}</span>
        </label>
      </div>
      ${shown.length
        ? html`<ul class="picker-results" aria-label=${t("picker.results")}>
            ${shown.map((exercise) => this.renderItem(exercise))}
          </ul>`
        : html`<p role="status">${t("picker.none")}</p>`}
      ${found.length > shown.length
        ? html`<p class="secondary">${t("picker.more", { shown: shown.length, count: found.length })}</p>`
        : nothing}
      <p class="secondary">${t("picker.hint")}</p>
    `;
  }

  private renderItem(exercise: ExerciseSummary) {
    const meta = [exercise.equipment, exercise.body_part].filter(Boolean).join(" · ");
    return html`<li>
      ${this.missing.has(exercise.id)
        ? html`<span class="thumb placeholder" aria-hidden="true">${icon(mdiDumbbell)}</span>`
        : html`<img
            class="thumb"
            src=${thumbnailUrl(exercise.id)}
            alt=""
            loading="lazy"
            width="40"
            height="40"
            @error=${() => (this.missing = new Set([...this.missing, exercise.id]))}
          />`}
      <span class="picker-text">
        <button type="button" class="link" @click=${() => this.fire("details", exercise)}>${exercise.name}</button>
        ${meta ? html`<span class="secondary">${meta}</span>` : nothing}
      </span>
      ${this.inProgram.has(exercise.id)
        ? html`<span class="picker-in" role="img" aria-label=${t("picker.in_program")}>${icon(mdiCheckCircle)}</span>`
        : html`<button
            type="button"
            class="icon-button picker-add"
            aria-label=${t("picker.add", { name: exercise.name })}
            @click=${() => this.fire("pick", exercise.id)}
          >
            ${icon(mdiPlusCircle)}
          </button>`}
    </li>`;
  }
}

/** The panel's styles, for the shell's shadow root (it renders in light DOM). */
export const exercisePickerStyles = css`
  .picker h2 {
    margin-bottom: 12px;
  }
  .picker .search {
    margin-bottom: 8px;
  }
  .picker-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 8px;
  }
  .picker-filters label {
    display: flex;
    flex-direction: column;
    gap: 2px;
    color: var(--hf-text-secondary);
    font-size: 12px;
  }
  .picker-filters label.check {
    flex-direction: row;
    align-items: center;
    gap: 6px;
    color: var(--hf-text);
    font-size: 14px;
  }
  .picker-filters select {
    max-width: 120px;
    font: inherit;
  }
  .picker-results {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .picker-results li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
  }
  .picker-results .thumb {
    width: 40px;
    height: 40px;
  }
  .picker-text {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }
  .picker-text button.link {
    color: var(--hf-text);
    text-align: left;
  }
  .picker-in .icon,
  .picker-add .icon {
    color: var(--hf-primary);
  }
`;

if (!customElements.get("hf-exercise-picker")) customElements.define("hf-exercise-picker", ExercisePicker);

declare global {
  interface HTMLElementTagNameMap {
    "hf-exercise-picker": ExercisePicker;
  }
}
