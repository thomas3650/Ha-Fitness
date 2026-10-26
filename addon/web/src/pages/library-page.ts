import { mdiDumbbell, mdiMagnify } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { ApiError, createApi, thumbnailUrl, type Api, type ExerciseSummary } from "../api";
import "../components/exercise-details";
import { facetValues, FACETS, inHousehold, searchByName, type Facet } from "../components/exercise-picker";
import { t } from "../i18n";
import { icon } from "../icons";

function failure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  throw error;
}

/**
 * The Library page (website spec §2.3, W4): every exercise, searched by name and filtered by equipment, body part and
 * target, several values each (either value of a filter, and every filter). The household filter is on by default
 * and shares its rule with the editor's library panel; "Show all" turns it off. A click on a name opens the details.
 *
 * Without the setup the household is body weight and the custom exercises, and the page says why.
 */
export class LibraryPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    exercises: { state: true },
    household: { state: true },
    errors: { state: true },
    query: { state: true },
    filters: { state: true },
    showAll: { state: true },
    missing: { state: true },
    details: { state: true },
  };

  declare api: Api;
  declare exercises: ExerciseSummary[] | null;
  /** The setup's equipment. */
  declare household: ReadonlySet<string>;
  declare errors: string[];
  declare query: string;
  declare filters: Record<Facet, ReadonlySet<string>>;
  declare showAll: boolean;
  /** Exercises whose thumbnail didn't load. */
  declare missing: ReadonlySet<string>;
  declare details: ExerciseSummary | null;

  constructor() {
    super();
    this.api = createApi();
    this.exercises = null;
    this.household = new Set();
    this.errors = [];
    this.query = "";
    this.filters = { equipment: new Set(), body_part: new Set(), target: new Set() };
    this.showAll = false;
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
    if (setup.status === "fulfilled") this.household = new Set(setup.value.equipment);
    else errors.push(failure(setup.reason));
    if (exercises.status === "fulfilled") this.exercises = exercises.value;
    else errors.push(failure(exercises.reason));
    this.errors = [...new Set(errors)];
  }

  /** The exercises the search, the filters and the household filter keep. */
  private found(exercises: ExerciseSummary[]): ExerciseSummary[] {
    const kept = exercises.filter(
      (exercise) =>
        FACETS.every((facet) => {
          const chosen = this.filters[facet];
          return !chosen.size || (exercise[facet] !== null && chosen.has(exercise[facet]));
        }) &&
        (this.showAll || inHousehold(exercise, this.household)),
    );
    return searchByName(kept, this.query);
  }

  private toggle(facet: Facet, value: string): void {
    const chosen = new Set(this.filters[facet]);
    if (chosen.has(value)) chosen.delete(value);
    else chosen.add(value);
    this.filters = { ...this.filters, [facet]: chosen };
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
    const found = this.found(exercises);
    return html`
      <div class="library-tools">
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
        <label class="check">
          <input
            type="checkbox"
            .checked=${this.showAll}
            @change=${(event: Event) => (this.showAll = (event.target as HTMLInputElement).checked)}
          />
          <span>${t("library.show_all")}</span>
        </label>
      </div>
      ${FACETS.map((facet) => this.renderFacet(exercises, facet))}
      <p class="secondary">
        ${t(found.length === 1 ? "library.count_one" : "library.count_other", { count: found.length })}
      </p>
      ${found.length
        ? html`<table aria-label=${t("library.results")}>
            <thead>
              <tr>
                <th><span class="visually-hidden">${t("library.col_picture")}</span></th>
                <th>${t("library.col_name")}</th>
                <th>${t("library.equipment")}</th>
                <th>${t("library.body_part")}</th>
                <th>${t("library.target")}</th>
              </tr>
            </thead>
            <tbody>
              ${found.map((exercise) => this.renderRow(exercise))}
            </tbody>
          </table>`
        : html`<p role="status">${t("library.none")}</p>`}
    `;
  }

  private renderFacet(exercises: ExerciseSummary[], facet: Facet) {
    const chosen = this.filters[facet];
    const headingId = `library-facet-${facet}`;
    return html`<div class="library-facet" role="group" aria-labelledby=${headingId}>
      <span id=${headingId} class="library-facet-name">${t(`library.${facet}`)}</span>
      ${facetValues(exercises, facet).map(
        (value) => html`<button
          type="button"
          class="chip"
          aria-pressed=${chosen.has(value) ? "true" : "false"}
          @click=${() => this.toggle(facet, value)}
        >
          ${value}
        </button>`,
      )}
    </div>`;
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
    align-items: center;
    gap: 16px;
    margin-bottom: 12px;
  }
  .library-tools label.check {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .library-facet {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }
  .library-facet-name {
    min-width: 90px;
    color: var(--hf-text-secondary);
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
  }
  .library-facet .chip {
    padding: 4px 12px;
    font-size: 13px;
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
