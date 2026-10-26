import { mdiClose, mdiDumbbell, mdiPlus } from "@mdi/js";
import { css, html, LitElement, nothing, type PropertyValues } from "lit";

import { createApi, gifUrl, type Api, type Exercise, type ExerciseSummary } from "../api";
import { failure } from "../failure";
import { t } from "../i18n";
import { icon } from "../icons";
import { trapFocus } from "./focus-trap";

let nextId = 0;

/**
 * An exercise's details (W4): the big GIF with its attribution, the equipment, body part, target and secondary
 * muscles, and the steps in English (names and steps are never translated). It loads the details of `exercise` (a
 * summary, so the heading shows at once).
 *
 * Like `<hf-confirm-dialog>` it renders in light DOM and shows while it is in the page. It fires `close` (Close,
 * the ×, Escape) and, with `canAdd`, `add` ("Add to program"). The focus stays inside while it is open.
 */
export class ExerciseDetails extends LitElement {
  static override properties = {
    api: { attribute: false },
    exercise: { attribute: false },
    canAdd: { type: Boolean },
    details: { state: true },
    error: { state: true },
    gifMissing: { state: true },
  };

  declare api: Api;
  declare exercise: ExerciseSummary | null;
  declare canAdd: boolean;
  declare details: Exercise | null;
  declare error: string | null;
  declare gifMissing: boolean;

  private readonly headingId = `hf-details-${++nextId}`;
  private returnFocus: HTMLElement | null = null;

  constructor() {
    super();
    this.api = createApi();
    this.exercise = null;
    this.canAdd = false;
    this.details = null;
    this.error = null;
    this.gifMissing = false;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    const root = this.getRootNode() as Document | ShadowRoot;
    this.returnFocus = root.activeElement instanceof HTMLElement ? root.activeElement : null;
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this.returnFocus?.isConnected) this.returnFocus.focus();
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("exercise") && this.exercise) void this.load(this.exercise.id);
  }

  protected override firstUpdated(): void {
    this.querySelector<HTMLButtonElement>("button[data-close]")?.focus();
  }

  private async load(id: string): Promise<void> {
    this.details = null;
    this.error = null;
    this.gifMissing = false;
    try {
      const details = await this.api.exercise(id);
      if (this.exercise?.id === id) this.details = details;
    } catch (error) {
      // Always through failure(), so a bug is logged even when another exercise is shown by now.
      const text = failure(error);
      if (this.exercise?.id === id) this.error = text;
    }
  }

  private fire(name: "close" | "add"): void {
    this.dispatchEvent(new CustomEvent(name));
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      this.fire("close");
    }
    trapFocus(event, event.currentTarget as HTMLElement);
  }

  protected override render() {
    const exercise = this.exercise;
    if (!exercise) return nothing;
    const details = this.details;
    return html`<div class="dialog-backdrop">
      <div
        class="dialog details"
        role="dialog"
        aria-modal="true"
        aria-labelledby=${this.headingId}
        @keydown=${this.onKeyDown}
      >
        <div class="details-media">
          ${this.gifMissing
            ? html`<span class="details-gif placeholder" role="img" aria-label=${exercise.name}
                >${icon(mdiDumbbell)}</span
              >`
            : html`<img
                class="details-gif"
                src=${gifUrl(exercise.id)}
                alt=${exercise.name}
                @error=${() => (this.gifMissing = true)}
              />`}
        </div>
        <div class="details-body">
          <header class="details-header">
            <h2 id=${this.headingId}>${exercise.name}</h2>
            <!-- The × repeats Close for the mouse; Close is the one for the keyboard and screen readers. -->
            <button
              type="button"
              class="icon-button"
              tabindex="-1"
              aria-hidden="true"
              @click=${() => this.fire("close")}
            >
              ${icon(mdiClose)}
            </button>
          </header>
          ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
          ${details ? this.renderDetails(details) : this.error ? nothing : html`<p>${t("details.loading")}</p>`}
          <div class="dialog-actions">
            <button type="button" class="text" data-close @click=${() => this.fire("close")}>
              ${t("details.close")}
            </button>
            ${this.canAdd
              ? html`<button type="button" class="button primary" @click=${() => this.fire("add")}>
                  ${icon(mdiPlus)}<span>${t("details.add")}</span>
                </button>`
              : nothing}
          </div>
        </div>
      </div>
    </div>`;
  }

  private renderDetails(details: Exercise) {
    const chips = [
      details.equipment,
      details.body_part,
      details.target ? t("details.target", { target: details.target }) : null,
      details.secondary_muscles.length
        ? t("details.also", { muscles: details.secondary_muscles.join(t("list_separator")) })
        : null,
    ].filter((chip): chip is string => !!chip);
    return html`
      ${chips.length
        ? html`<p class="details-chips">${chips.map((chip) => html`<span class="tag">${chip}</span>`)}</p>`
        : nothing}
      ${details.steps.length
        ? html`<h3>${t("details.instructions")}</h3>
            <ol>
              ${details.steps.map((step) => html`<li>${step}</li>`)}
            </ol>`
        : nothing}
      ${details.attribution ? html`<p class="secondary">${details.attribution}</p>` : nothing}
    `;
  }
}

/** The dialog's styles, for the shell's shadow root; it shares `.dialog` with `<hf-confirm-dialog>`. */
export const exerciseDetailsStyles = css`
  .dialog.details {
    display: flex;
    gap: 24px;
    width: min(760px, calc(100vw - 48px));
  }
  .details-media {
    display: flex;
    flex: 0 0 280px;
    align-items: center;
    justify-content: center;
    border-right: 1px solid var(--hf-border);
  }
  .details-gif {
    width: 260px;
    max-width: 100%;
  }
  .details-gif.placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 260px;
  }
  .details-body {
    flex: 1;
    min-width: 0;
  }
  .details-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
  }
  .dialog.details h2 {
    margin: 0 0 12px;
  }
  .dialog.details h3 {
    margin: 12px 0 4px;
    color: var(--hf-text-secondary);
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
  }
  .dialog.details ol {
    margin: 0;
    padding-left: 20px;
    color: var(--hf-text);
  }
  .details-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .tag {
    padding: 4px 12px;
    border-radius: 16px;
    background: #eeeeee;
    font-weight: 500;
  }
`;

if (!customElements.get("hf-exercise-details")) customElements.define("hf-exercise-details", ExerciseDetails);

declare global {
  interface HTMLElementTagNameMap {
    "hf-exercise-details": ExerciseDetails;
  }
}
