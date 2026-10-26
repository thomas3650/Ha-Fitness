import { mdiDumbbell, mdiMagnify } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { ApiError, createApi, thumbnailUrl, type Api, type ExerciseSummary, type Setup } from "../api";
import "../components/equipment-filter";
import "../components/exercise-details";
import "../components/multi-select";
import { t } from "../i18n";
import { icon } from "../icons";
import {
  equipmentValues,
  facetValues,
  household,
  matchesEquipment,
  searchByName,
  type EquipmentChoice,
  type Facet,
} from "../library-filter";

/** The filters besides equipment: multi-selects of the dataset's values. */
type ValueFacet = Exclude<Facet, "equipment">;

const VALUE_FACETS: ValueFacet[] = ["body_part", "target"];

function failure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  throw error;
}

/**
 * The Library page (website spec §2.3, W4): every exercise, searched by name and filtered by equipment, body part and
 * target (either value of a filter, and every filter). The equipment filter starts on My equipment and shares its rule
 * with the editor's library panel (D66). A click on a name opens the details.
 *
 * Without the setup My equipment is body weight and the custom exercises, and the page says why.
 */
export class LibraryPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    exercises: { state: true },
    setup: { state: true },
    errors: { state: true },
    query: { state: true },
    equipment: { state: true },
    filters: { state: true },
    missing: { state: true },
    details: { state: true },
  };

  declare api: Api;
  declare exercises: ExerciseSummary[] | null;
  /** The household's setup; null until read, or when it couldn't be. */
  declare setup: Setup | null;
  declare errors: string[];
  declare query: string;
  declare equipment: EquipmentChoice;
  declare filters: Record<ValueFacet, ReadonlySet<string>>;
  /** Exercises whose thumbnail didn't load. */
  declare missing: ReadonlySet<string>;
  declare details: ExerciseSummary | null;

  constructor() {
    super();
    this.api = createApi();
    this.exercises = null;
    this.setup = null;
    this.errors = [];
    this.query = "";
    this.equipment = { mode: "mine" };
    this.filters = { body_part: new Set(), target: new Set() };
    this.missing = new Set();
    this.details = null;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.load();
  }

  private async load(): Promise<void> {
    const [setup, exercises] = await Promise.allSettled([this.api.setup(), this.api.allExercises()]);
    const errors: string[] = [];
    if (setup.status === "fulfilled") this.setup = setup.value;
    else errors.push(failure(setup.reason));
    if (exercises.status === "fulfilled") this.exercises = exercises.value;
    else errors.push(failure(exercises.reason));
    this.errors = [...new Set(errors)];
  }

  /** The exercises the search and the filters keep. */
  private found(exercises: ExerciseSummary[], home: ReadonlySet<string>): ExerciseSummary[] {
    const kept = exercises.filter(
      (exercise) =>
        matchesEquipment(exercise, this.equipment, home) &&
        VALUE_FACETS.every((facet) => {
          const chosen = this.filters[facet];
          return !chosen.size || (exercise[facet] !== null && chosen.has(exercise[facet]));
        }),
    );
    return searchByName(kept, this.query);
  }

  private choose(facet: ValueFacet, selected: string[]): void {
    this.filters = { ...this.filters, [facet]: new Set(selected) };
  }

  protected override render() {
    return html`
      <h1>${t("library.title")}</h1>
      ${this.errors.map((message) => html`<p class="error" role="alert">${message}</p>`)}
      ${this.exercises
        ? this.renderLibrary(this.exercises)
        : this.errors.length
          ? nothing
          : html`<p>${t("library.loading")}</p>`}
      ${this.details
        ? html`<hf-exercise-details
            .api=${this.api}
            .exercise=${this.details}
            @close=${() => (this.details = null)}
          ></hf-exercise-details>`
        : nothing}
    `;
  }

  private renderLibrary(exercises: ExerciseSummary[]) {
    const home = household(this.setup);
    const found = this.found(exercises, home);
    const mine = exercises.filter((exercise) => matchesEquipment(exercise, { mode: "mine" }, home)).length;
    return html`
      <div class="library-tools">
        <div class="library-search">
          <span class="library-label" aria-hidden="true">${t("library.name")}</span>
          <label class="search">
            ${icon(mdiMagnify)}
            <input
              type="search"
              aria-label=${t("library.search")}
              placeholder=${t("library.search")}
              .value=${this.query}
              @input=${(event: Event) => (this.query = (event.target as HTMLInputElement).value)}
            />
          </label>
        </div>
        <hf-equipment-filter
          .label=${t("library.equipment")}
          .values=${equipmentValues(exercises)}
          .home=${[...home]}
          .counts=${{ mine, all: exercises.length }}
          .choice=${this.equipment}
          @change=${(event: CustomEvent<{ choice: EquipmentChoice }>) => (this.equipment = event.detail.choice)}
        ></hf-equipment-filter>
        ${VALUE_FACETS.map((facet) => this.renderFacet(exercises, facet))}
      </div>
      <p class="secondary">
        ${t("library.count", { count: found.length })}
      </p>
      ${found.length
        ? html`<table aria-label=${t("library.results")}>
            <thead>
              <tr>
                <th scope="col"><span class="visually-hidden">${t("library.col_picture")}</span></th>
                <th scope="col">${t("library.col_name")}</th>
                <th scope="col">${t("library.equipment")}</th>
                <th scope="col">${t("library.body_part")}</th>
                <th scope="col">${t("library.target")}</th>
              </tr>
            </thead>
            <tbody>
              ${found.map((exercise) => this.renderRow(exercise))}
            </tbody>
          </table>`
        : html`<p role="status">${t("library.none")}</p>`}
    `;
  }

  private renderFacet(exercises: ExerciseSummary[], facet: ValueFacet) {
    return html`<hf-multi-select
      .label=${t(`library.${facet}`)}
      .placeholder=${t(`library.any_${facet}`)}
      .options=${facetValues(exercises, facet).map((value) => ({ value, label: value }))}
      .selected=${[...this.filters[facet]]}
      @change=${(event: CustomEvent<{ selected: string[] }>) => this.choose(facet, event.detail.selected)}
    ></hf-multi-select>`;
  }

  private renderRow(exercise: ExerciseSummary) {
    return html`<tr>
      <td>
        ${this.missing.has(exercise.id)
          ? html`<span class="thumb placeholder" role="img" aria-label=${t("library.no_thumbnail")}
              >${icon(mdiDumbbell)}</span
            >`
          : html`<img
              class="thumb"
              src=${thumbnailUrl(exercise.id)}
              alt=""
              loading="lazy"
              width="32"
              height="32"
              @error=${() => (this.missing = new Set([...this.missing, exercise.id]))}
            />`}
      </td>
      <td>
        <button type="button" class="link library-name" @click=${() => (this.details = exercise)}>
          ${exercise.name}
        </button>
        ${exercise.custom ? html`<span class="badge">${t("library.custom")}</span>` : nothing}
      </td>
      <td>${exercise.equipment ?? ""}</td>
      <td>${exercise.body_part ?? ""}</td>
      <td>${exercise.target ?? ""}</td>
    </tr>`;
  }
}

/** The page's styles, for the shell's shadow root (it renders in light DOM). */
export const libraryPageStyles = css`
  .library-tools {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 12px;
  }
  /* Every field has its name above it, as the filters have, and is 36px high. */
  .library-search {
    display: flex;
    flex: 1 1 220px;
    flex-direction: column;
    gap: 4px;
    max-width: 320px;
  }
  .library-label {
    color: var(--hf-text-secondary);
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
    text-transform: uppercase;
  }
  .library-tools .search {
    box-sizing: border-box;
    flex: none;
    height: 36px;
  }
  .library-tools .search input {
    padding: 0;
  }
  .library-tools hf-multi-select,
  .library-tools hf-equipment-filter {
    flex: 1 1 180px;
    max-width: 280px;
  }
  td button.library-name {
    color: var(--hf-text);
    text-align: left;
  }
  td .badge {
    margin-left: 8px;
  }
`;

if (!customElements.get("hf-library-page")) customElements.define("hf-library-page", LibraryPage);

declare global {
  interface HTMLElementTagNameMap {
    "hf-library-page": LibraryPage;
  }
}
