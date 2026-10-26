import { mdiContentCopy, mdiDumbbell, mdiFileOutline } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { ApiError, createApi, thumbnailUrl, type Api, type ProgramDefaults, type ProgramOut } from "../api";
import { minutes } from "../format";
import { t } from "../i18n";
import { icon } from "../icons";

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  throw error;
}

/**
 * The new-program page (W2, website spec §2.2.3): start empty, with the add-on's defaults, or copy a stored program.
 * Both are links (`#/programs/new/empty`, `#/programs/new/copy/<id>`), so the editor they open survives a reload.
 * Nothing is stored here; a copy is stored only when it is saved.
 */
export class NewProgramPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    defaults: { state: true },
    defaultsError: { state: true },
    programs: { state: true },
    programsError: { state: true },
    missing: { state: true },
  };

  declare api: Api;
  declare defaults: ProgramDefaults | null;
  declare defaultsError: string | null;
  declare programs: ProgramOut[] | null;
  declare programsError: string | null;
  declare missing: ReadonlySet<string>;

  constructor() {
    super();
    this.api = createApi();
    this.defaults = null;
    this.defaultsError = null;
    this.programs = null;
    this.programsError = null;
    this.missing = new Set();
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.load();
  }

  private async load(): Promise<void> {
    const [defaults, programs] = await Promise.allSettled([this.api.programDefaults(), this.api.programs()]);
    if (defaults.status === "fulfilled") this.defaults = defaults.value;
    else this.defaultsError = message(defaults.reason);
    if (programs.status === "fulfilled") this.programs = programs.value;
    else this.programsError = message(programs.reason);
  }

  protected override render() {
    return html`
      <nav class="breadcrumb" aria-label=${t("editor.breadcrumb")}>
        <a href="#/programs">${t("menu.programs")}</a> › <span>${t("editor.new_title")}</span>
      </nav>
      <h1>${t("editor.new_title")}</h1>
      <p class="lead">${t("new_program.heading")}</p>
      <div class="start-cards">
        <section class="card start-card">
          ${icon(mdiFileOutline)}
          <h2>${t("new_program.empty_title")}</h2>
          ${this.defaultsError
            ? html`<p class="error" role="alert">${this.defaultsError}</p>`
            : this.defaults
              ? html`<p class="secondary">
                  ${t("new_program.defaults", {
                    rounds: this.defaults.rounds,
                    work: this.defaults.work_seconds,
                    switch: this.defaults.switch_seconds,
                    rest: this.defaults.round_rest_seconds,
                    countdown: this.defaults.countdown_seconds,
                  })}
                </p>`
              : nothing}
          <p class="secondary">${t("new_program.empty_hint")}</p>
          <a class="button primary" href="#/programs/new/empty">${t("new_program.start_empty")}</a>
        </section>
        <section class="card start-card">
          ${icon(mdiContentCopy)}
          <h2>${t("new_program.copy_title")}</h2>
          ${this.renderPrograms()}
          <p class="secondary">${t("new_program.copy_hint")}</p>
        </section>
      </div>
    `;
  }

  private renderPrograms() {
    if (this.programsError) return html`<p class="error" role="alert">${this.programsError}</p>`;
    if (!this.programs) return html`<p>${t("programs.loading")}</p>`;
    if (!this.programs.length) return html`<p role="status">${t("new_program.no_programs")}</p>`;
    return html`<ul class="copy-list" aria-label=${t("new_program.programs")}>
      ${this.programs.map((stored) => {
        const first = stored.program.stations[0]?.exercise;
        return html`<li>
          <a href="#/programs/new/copy/${stored.id}">
            ${!first || this.missing.has(first)
              ? html`<span class="thumb placeholder" aria-hidden="true">${icon(mdiDumbbell)}</span>`
              : html`<img
                  class="thumb"
                  src=${thumbnailUrl(first)}
                  alt=""
                  loading="lazy"
                  width="32"
                  height="32"
                  @error=${() => (this.missing = new Set([...this.missing, first]))}
                />`}
            <strong>${stored.program.name}</strong>
            <span class="secondary">${t("new_program.minutes", { minutes: minutes(stored.total_seconds) })}</span>
          </a>
        </li>`;
      })}
    </ul>`;
  }
}

/** The page's styles, for the shell's shadow root. */
export const newProgramStyles = css`
  .lead {
    margin: -8px 0 16px;
    font-size: 18px;
  }
  .start-cards {
    display: flex;
    gap: 16px;
    align-items: stretch;
  }
  .start-card {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 8px;
    max-width: 420px;
  }
  .start-card > .icon {
    width: 32px;
    height: 32px;
    color: var(--hf-primary);
  }
  .start-card .button {
    align-self: flex-start;
    margin-top: auto;
  }
  .copy-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .copy-list a {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
    padding: 8px 12px;
    border: 1px solid var(--hf-border);
    border-radius: 8px;
    color: var(--hf-text);
    text-decoration: none;
  }
  .copy-list strong {
    flex: 1;
    font-weight: 500;
  }
`;

if (!customElements.get("hf-new-program")) customElements.define("hf-new-program", NewProgramPage);

declare global {
  interface HTMLElementTagNameMap {
    "hf-new-program": NewProgramPage;
  }
}
