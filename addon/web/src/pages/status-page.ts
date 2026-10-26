import { html, LitElement, nothing } from "lit";

import { ApiError, createApi, type Api, type Health, type LibraryStatus, type Person, type ProgramOut } from "../api";
import { t } from "../i18n";

interface StatusData {
  health: Health;
  library: LibraryStatus;
  people: Person[];
  programs: ProgramOut[];
}

/** A program's length in whole minutes, a half minute up, as the old status page showed it. */
function minutes(seconds: number): number {
  return Math.floor((seconds + 30) / 60);
}

/**
 * The Status page (website spec §2.5): the version, the library and media state, the people, the programs, and links
 * to the JSON library state and health. It renders into the shell's shadow root, so the shell's styles apply.
 */
export class StatusPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    data: { state: true },
    error: { state: true },
  };

  declare api: Api;
  declare data: StatusData | null;
  declare error: string | null;

  constructor() {
    super();
    this.api = createApi();
    this.data = null;
    this.error = null;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const [health, library, people, programs] = await Promise.all([
        this.api.health(),
        this.api.library(),
        this.api.people(),
        this.api.programs(),
      ]);
      this.data = { health, library, people: people.people, programs };
      this.error = null;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      this.error = error.message;
    }
  }

  protected override render() {
    return html`
      <h1>${t("status.title")}</h1>
      ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
      ${this.data ? this.renderData(this.data) : this.error ? nothing : html`<p>${t("status.loading")}</p>`}
    `;
  }

  private renderData({ health, library, people, programs }: StatusData) {
    const media = library.media;
    return html`
      <section class="card">
        <p>${t("status.version", { version: health.version })}</p>
      </section>
      <section class="card" aria-labelledby="status-library">
        <h2 id="status-library">${t("status.library")}</h2>
        <p>${t("status.exercises", { library: library.exercises.library, custom: library.exercises.custom })}</p>
        <p>
          ${t("status.media", { present: media.present, total: media.total, state: t(`status.media_${media.state}`) })}
        </p>
      </section>
      <section class="card" aria-labelledby="status-people">
        <h2 id="status-people">${t("status.people")}</h2>
        ${people.length
          ? html`<ul aria-labelledby="status-people">
              ${people.map((person) => html`<li>${person.name}</li>`)}
            </ul>`
          : html`<p>${t("status.no_people")}</p>`}
      </section>
      <section class="card" aria-labelledby="status-programs">
        <h2 id="status-programs">${t("status.programs")}</h2>
        ${programs.length ? this.renderPrograms(programs) : html`<p>${t("status.no_programs")}</p>`}
      </section>
      <section class="card" aria-labelledby="status-links">
        <h2 id="status-links">${t("status.links")}</h2>
        <ul>
          <li><a href="api/v1/library">${t("status.library_json")}</a></li>
          <li><a href="api/v1/health">${t("status.health")}</a></li>
        </ul>
      </section>
    `;
  }

  private renderPrograms(programs: ProgramOut[]) {
    return html`<table aria-labelledby="status-programs">
      <thead>
        <tr>
          <th>${t("status.program_name")}</th>
          <th>${t("status.program_state")}</th>
          <th>${t("status.program_weekdays")}</th>
          <th>${t("status.program_length")}</th>
        </tr>
      </thead>
      <tbody>
        ${programs.map(
          (stored) => html`<tr>
            <td>${stored.program.name}</td>
            <td>${stored.program.active === false ? t("status.off") : t("status.on")}</td>
            <td>
              ${stored.program.weekdays.map((day) => t(`weekday.${day}`)).join(t("list_separator")) ||
              t("status.no_weekdays")}
            </td>
            <td>${t("status.minutes", { minutes: minutes(stored.total_seconds) })}</td>
          </tr>`,
        )}
      </tbody>
    </table>`;
  }
}

if (!customElements.get("hf-status-page")) customElements.define("hf-status-page", StatusPage);

declare global {
  interface HTMLElementTagNameMap {
    "hf-status-page": StatusPage;
  }
}
