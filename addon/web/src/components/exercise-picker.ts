import { mdiCheckCircle, mdiDumbbell, mdiMagnify, mdiPlusCircle } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { thumbnailUrl, type ExerciseSummary, type Setup } from "../api";
import { t } from "../i18n";
import { icon } from "../icons";
import {
  countMine,
  equipmentValues,
  facetValues,
  household,
  matchesEquipment,
  searchByName,
  type EquipmentChoice,
} from "../library-filter";
import "./equipment-filter";
import "./multi-select";

/** The most results the panel draws at once; a search narrows the rest. */
const SHOWN = 100;

/**
 * The library beside the editor (W7), searched and filtered in the site from the summaries of all exercises (spec
 * §2.4): a search, the equipment filter (My equipment by default, D66) and the body parts. Without the setup, My
 * equipment is body weight and the custom exercises, and the panel says why at its top.
 *
 * It fires `pick` (the add button, the exercise's id in `detail`) and `details` (a click on the name, the summary in
 * `detail`). An exercise in `inProgram` has a tick as its add button: a program may have an exercise twice, the add-on
 * decides.
 */
export class ExercisePicker extends LitElement {
  static override properties = {
    exercises: { attribute: false },
    error: {},
    setup: { attribute: false },
    setupError: { attribute: false },
    inProgram: { attribute: false },
    query: { state: true },
    equipment: { state: true },
    bodyParts: { state: true },
    missing: { state: true },
  };

  declare exercises: ExerciseSummary[] | null;
  declare error: string | null;
  /** The household's setup; null when it couldn't be read. */
  declare setup: Setup | null;
  /** Why the setup couldn't be read, if it couldn't. */
  declare setupError: string | null;
  declare inProgram: ReadonlySet<string>;
  declare query: string;
  declare equipment: EquipmentChoice;
  declare bodyParts: string[];
  /** Exercises whose thumbnail didn't load. */
  declare missing: ReadonlySet<string>;

  constructor() {
    super();
    this.exercises = null;
    this.error = null;
    this.setup = null;
    this.setupError = null;
    this.inProgram = new Set();
    this.query = "";
    this.equipment = { mode: "mine" };
    this.bodyParts = [];
    this.missing = new Set();
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  /** The exercises the search and the filters keep; names that start with the search come first. */
  private found(exercises: ExerciseSummary[], home: ReadonlySet<string>): ExerciseSummary[] {
    const kept = exercises.filter(
      (exercise) =>
        matchesEquipment(exercise, this.equipment, home) &&
        (!this.bodyParts.length || (exercise.body_part !== null && this.bodyParts.includes(exercise.body_part))),
    );
    return searchByName(kept, this.query);
  }

  private fire(name: "pick" | "details", detail: unknown): void {
    this.dispatchEvent(new CustomEvent(name, { detail }));
  }

  protected override render() {
    const home = household(this.setup);
    const found = this.exercises && !this.error ? this.found(this.exercises, home) : null;
    return html`<aside class="picker" aria-label=${t("picker.title")}>
      <div class="picker-title">
        <h2>${t("picker.title")}</h2>
        ${found ? html`<span class="secondary">${t("library.count", { count: found.length })}</span>` : nothing}
      </div>
      ${this.setupError
        ? html`<p class="picker-note">
            <span>${this.setupError}</span>
            <span>${t("picker.setup_note")}</span>
          </p>`
        : nothing}
      ${this.renderBody(home, found)}
    </aside>`;
  }

  private renderBody(home: ReadonlySet<string>, found: ExerciseSummary[] | null) {
    if (this.error) return html`<p class="error">${this.error}</p>`;
    const exercises = this.exercises;
    if (!exercises || !found) return html`<p>${t("picker.loading")}</p>`;
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
        <hf-equipment-filter
          .hideLabel=${true}
          .label=${t("picker.equipment")}
          .values=${equipmentValues(exercises)}
          .home=${[...home]}
          .counts=${{ mine: countMine(exercises, home), all: exercises.length }}
          .choice=${this.equipment}
          @change=${(event: CustomEvent<{ choice: EquipmentChoice }>) => (this.equipment = event.detail.choice)}
        ></hf-equipment-filter>
        <hf-multi-select
          .hideLabel=${true}
          .label=${t("picker.body_part")}
          .placeholder=${t("picker.any_body_part")}
          .options=${facetValues(exercises, "body_part").map((value) => ({ value, label: value }))}
          .selected=${this.bodyParts}
          @change=${(event: CustomEvent<{ selected: string[] }>) => (this.bodyParts = event.detail.selected)}
        ></hf-multi-select>
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
    const meta = [exercise.equipment, exercise.body_part].filter(Boolean).join(t("meta_separator"));
    const again = this.inProgram.has(exercise.id);
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
      <button
        type="button"
        class=${again ? "icon-button picker-add again" : "icon-button picker-add"}
        aria-label=${t(again ? "picker.add_again" : "picker.add", { name: exercise.name })}
        @click=${() => this.fire("pick", exercise.id)}
      >
        ${icon(again ? mdiCheckCircle : mdiPlusCircle)}
      </button>
    </li>`;
  }
}

/** The panel's styles, for the shell's shadow root (it renders in light DOM). */
export const exercisePickerStyles = css`
  .picker-title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;
  }
  .picker-title h2 {
    margin: 0;
  }
  .picker-title .secondary {
    font-size: 13px;
  }
  .picker-note {
    margin: 0 0 12px;
    color: var(--hf-text-secondary);
    font-size: 13px;
  }
  .picker-note span {
    display: block;
  }
  .picker .search {
    margin-bottom: 8px;
  }
  /*
   * The two dropdowns side by side (W7): the equipment filter as wide as its tags (about half the row at most), the
   * body part the rest. In the 300px panel both read in full: "My equipment" and "Any body part".
   */
  .picker-filters {
    display: flex;
    gap: 6px;
    margin-bottom: 8px;
  }
  .picker-filters hf-equipment-filter {
    flex: 0 1 auto;
    min-width: 0;
    max-width: 52%;
  }
  .picker-filters hf-multi-select {
    flex: 1 1 0;
    min-width: 0;
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
  .picker-add .icon {
    color: var(--hf-primary);
  }
  .picker-add.again .icon {
    color: var(--hf-success);
  }
`;

if (!customElements.get("hf-exercise-picker")) customElements.define("hf-exercise-picker", ExercisePicker);

declare global {
  interface HTMLElementTagNameMap {
    "hf-exercise-picker": ExercisePicker;
  }
}
