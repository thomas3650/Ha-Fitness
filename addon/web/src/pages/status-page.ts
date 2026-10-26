import { html, LitElement, nothing } from "lit";

import { ApiError, createApi, type Api, type Health, type LibraryStatus, type Person, type ProgramOut } from "../api";
import { duration } from "../format";
import { t } from "../i18n";

/** What the page read; a read that was refused stays null, and its message is in `errors`. */
interface StatusData {
  health: Health | null;
  library: LibraryStatus | null;
  people: Person[] | null;
  programs: ProgramOut[] | null;
  errors: string[];
}

/** The value of a settled read, or null; a refusal's message goes into `errors` once. */
function settled<T>(result: PromiseSettledResult<T>, errors: string[]): T | null {
  if (result.status === "fulfilled") return result.value;
  if (!(result.reason instanceof ApiError)) throw result.reason;
  if (!errors.includes(result.reason.message)) errors.push(result.reason.message);
  return null;
}

/**
 * The Status page (website spec §2.5): the version, the library and media state, the people, the programs, and links
 * to the JSON library state and health. It renders into the shell's shadow root, so the shell's styles apply.
 */
export class StatusPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    data: { state: true },
  };

  declare api: Api;
  declare data: StatusData | null;

  constructor() {
    super();
    this.api = createApi();
    this.data = null;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.load();
  }

  /** Read the four parts at once; one refused read doesn't hide the others (website spec §2.5). */
  private async load(): Promise<void> {
    const [health, library, people, programs] = await Promise.allSettled([
      this.api.health(),
      this.api.library(),
      this.api.people(),
      this.api.programs(),
    ]);
    const errors: string[] = [];
    this.data = {
      health: settled(health, errors),
      library: settled(library, errors),
      people: settled(people, errors)?.people ?? null,
      programs: settled(programs, errors),
      errors,
    };
  }

  protected override render() {
    return html`
      <h1>${t("status.title")}</h1>
      ${this.data ? this.renderData(this.data) : html`<p>${t("status.loading")}</p>`}
    `;
  }

  private renderData({ health, library, people, programs, errors }: StatusData) {
    return html`
      ${errors.map((message) => html`<p class="error" role="alert">${message}</p>`)}
      ${health
        ? html`<section class="card">
            <p>${t("status.version", { version: health.version })}</p>
          </section>`
        : nothing}
      ${library
        ? html`<section class="card" aria-labelledby="status-library">
            <h2 id="status-library">${t("status.library")}</h2>
            <p>${t("status.exercises", { library: library.exercises.library, custom: library.exercises.custom })}</p>
            <p>
              ${t("status.media", {
                present: library.media.present,
                total: library.media.total,
                state: t(`status.media_${library.media.state}`),
              })}
            </p>
          </section>`
        : nothing}
      ${people
        ? html`<section class="card" aria-labelledby="status-people">
            <h2 id="status-people">${t("status.people")}</h2>
            ${people.length
              ? html`<ul aria-labelledby="status-people">
                  ${people.map((person) => html`<li>${person.name}</li>`)}
                </ul>`
              : html`<p>${t("status.no_people")}</p>`}
          </section>`
        : nothing}
      ${programs
        ? html`<section class="card" aria-labelledby="status-programs">
            <h2 id="status-programs">${t("status.programs")}</h2>
            ${programs.length ? this.renderPrograms(programs) : html`<p>${t("status.no_programs")}</p>`}
          </section>`
        : nothing}
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
            <td>${duration(stored.total_seconds)}</td>
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
