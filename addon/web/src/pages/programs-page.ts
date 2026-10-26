import {
  mdiAccount,
  mdiContentCopy,
  mdiCreation,
  mdiDelete,
  mdiDeleteAlertOutline,
  mdiDumbbell,
  mdiMagnify,
  mdiPauseCircleOutline,
  mdiPencil,
  mdiPlus,
} from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { createApi, thumbnailUrl, type Api, type ProgramOut, type Weekday } from "../api";
import "../components/confirm-dialog";
import { FOCUSABLE } from "../components/focus-trap";
import { failure } from "../failure";
import { duration } from "../format";
import { t } from "../i18n";
import { icon } from "../icons";

type Filter = "all" | "active" | "off";

const FILTERS: Filter[] = ["all", "active", "off"];
const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** A program is on unless its document says otherwise (`active` defaults to true). */
function isActive(stored: ProgramOut): boolean {
  return stored.program.active !== false;
}

/** The delete confirmation's state: which program, whether a request runs, and the add-on's refusal. */
interface Deleting {
  id: number;
  busy: boolean;
  error: string | null;
}

/**
 * The Programs page (W1, website spec §2.2.1): search and filters, one row per program with its switch, and edit,
 * copy and delete. Delete asks first (W5); a refusal (a running session, D42) shows by the row or in the dialog.
 * A program's name links to its editor, and a click elsewhere on its row opens it too (#96).
 */
export class ProgramsPage extends LitElement {
  static override properties = {
    api: { attribute: false },
    programs: { state: true },
    loadError: { state: true },
    search: { state: true },
    filter: { state: true },
    pending: { state: true },
    rowErrors: { state: true },
    missing: { state: true },
    deleting: { state: true },
    note: { attribute: false },
  };

  declare api: Api;
  declare programs: ProgramOut[] | null;
  declare loadError: string | null;
  declare search: string;
  declare filter: Filter;
  /** Programs whose switch request runs. */
  declare pending: ReadonlySet<number>;
  /** The add-on's refusal of a switch, by program. */
  declare rowErrors: ReadonlyMap<number, string>;
  /** Exercises whose thumbnail didn't load. */
  declare missing: ReadonlySet<string>;
  declare deleting: Deleting | null;
  /** The shell's note after a save in the editor ("Saved …"); it goes on the next navigation. */
  declare note: string | null;

  constructor() {
    super();
    this.api = createApi();
    this.programs = null;
    this.loadError = null;
    this.search = "";
    this.filter = "all";
    this.pending = new Set();
    this.rowErrors = new Map();
    this.missing = new Set();
    this.deleting = null;
    this.note = null;
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
      this.programs = await this.api.programs();
    } catch (error) {
      this.loadError = failure(error);
    }
  }

  /** Put the add-on's answer for one program in place of the stored one. */
  private replace(changed: ProgramOut): void {
    this.programs = (this.programs ?? []).map((stored) => (stored.id === changed.id ? changed : stored));
  }

  private setRowError(id: number, text: string | null): void {
    const errors = new Map(this.rowErrors);
    if (text === null) errors.delete(id);
    else errors.set(id, text);
    this.rowErrors = errors;
  }

  /** The switch shows the stored state until the add-on answers; a refusal leaves it and shows by the row. */
  private async toggle(stored: ProgramOut): Promise<void> {
    if (this.pending.has(stored.id)) return;
    this.pending = new Set([...this.pending, stored.id]);
    this.setRowError(stored.id, null);
    try {
      this.replace(await this.api.setActive(stored.id, !isActive(stored)));
    } catch (error) {
      this.setRowError(stored.id, failure(error));
    } finally {
      const pending = new Set(this.pending);
      pending.delete(stored.id);
      this.pending = pending;
    }
  }

  private async confirmDelete(): Promise<void> {
    const deleting = this.deleting;
    if (!deleting || deleting.busy) return;
    this.deleting = { ...deleting, busy: true, error: null };
    try {
      await this.api.deleteProgram(deleting.id);
    } catch (error) {
      this.deleting = { ...deleting, busy: false, error: failure(error) };
      return;
    }
    // The focus was on the deleted row's Delete button: it goes to the row shown after it, else the one before it,
    // else (no row left) the page heading.
    const shown = this.shown(this.programs ?? []);
    const at = shown.findIndex((stored) => stored.id === deleting.id);
    const neighbour = shown[at + 1] ?? shown[at - 1] ?? null;
    this.programs = (this.programs ?? []).filter((stored) => stored.id !== deleting.id);
    this.setRowError(deleting.id, null);
    this.deleting = null;
    await this.updateComplete;
    this.focusAfterDelete(neighbour?.id ?? null);
  }

  /**
   * Focus a row's first control after its name link (its switch, or its edit link while the switch waits), or the
   * heading for none.
   */
  private focusAfterDelete(id: number | null): void {
    const row = id === null ? null : this.querySelector(`tr[data-program="${id}"]`);
    const control = row
      ? [...row.querySelectorAll<HTMLElement>(FOCUSABLE)].find(
          (element) => element.tabIndex >= 0 && !element.matches("a.program-name"),
        )
      : undefined;
    (control ?? this.querySelector<HTMLElement>("h1"))?.focus();
  }

  private async turnOffInstead(): Promise<void> {
    const deleting = this.deleting;
    if (!deleting || deleting.busy) return;
    this.deleting = { ...deleting, busy: true, error: null };
    try {
      this.replace(await this.api.setActive(deleting.id, false));
      this.setRowError(deleting.id, null);
      this.deleting = null;
    } catch (error) {
      this.deleting = { ...deleting, busy: false, error: failure(error) };
    }
  }

  /**
   * A click on a row opens the program, for touch (the name link is the keyboard's way). A click on a link or a
   * button, or anywhere in the Active and Actions cells, does only what it does there.
   */
  private openFromRow(event: MouseEvent, id: number): void {
    const target = event.target as Element | null;
    if (!target || target.closest("a, button, .active-cell, .actions")) return;
    location.hash = `#/programs/${id}`;
  }

  private markMissing(exercise: string): void {
    if (!this.missing.has(exercise)) this.missing = new Set([...this.missing, exercise]);
  }

  protected override render() {
    return html`
      <header class="page-header">
        <h1 tabindex="-1">${t("programs.title")}</h1>
        <a class="button primary" href="#/programs/new">${icon(mdiPlus)}<span>${t("programs.new")}</span></a>
      </header>
      ${this.note ? html`<p class="saved-note" role="status">${this.note}</p>` : nothing} ${this.renderBody()}
      ${this.renderDialog()}
    `;
  }

  /** The programs the search and the filter keep, in the table's order. */
  private shown(programs: ProgramOut[]): ProgramOut[] {
    const query = this.search.trim().toLowerCase();
    return programs.filter(
      (stored) =>
        (this.filter === "all" || isActive(stored) === (this.filter === "active")) &&
        stored.program.name.toLowerCase().includes(query),
    );
  }

  private renderBody() {
    if (this.loadError) return html`<p class="error" role="alert">${this.loadError}</p>`;
    if (!this.programs) return html`<p>${t("programs.loading")}</p>`;
    if (!this.programs.length) return html`<p role="status">${t("programs.none")}</p>`;
    const programs = this.programs;
    const counts: Record<Filter, number> = {
      all: programs.length,
      active: programs.filter(isActive).length,
      off: programs.filter((stored) => !isActive(stored)).length,
    };
    const shown = this.shown(programs);
    return html`
      <div class="toolbar">
        <label class="search">
          ${icon(mdiMagnify)}
          <input
            type="search"
            aria-label=${t("programs.search")}
            placeholder=${t("programs.search")}
            .value=${this.search}
            @input=${(event: Event) => (this.search = (event.target as HTMLInputElement).value)}
          />
        </label>
        <div class="chips" role="group" aria-label=${t("programs.filters")}>
          ${FILTERS.map(
            (filter) =>
              html`<button
                type="button"
                class="chip"
                aria-pressed=${this.filter === filter ? "true" : "false"}
                @click=${() => (this.filter = filter)}
              >
                ${t(`programs.filter_${filter}`, { count: counts[filter] })}
              </button>`,
          )}
        </div>
      </div>
      <table class="card programs" aria-label=${t("programs.title")}>
        <thead>
          <tr>
            <th scope="col">${t("programs.col_name")}</th>
            <th scope="col">${t("programs.col_days")}</th>
            <th scope="col">${t("programs.col_exercises")}</th>
            <th scope="col">${t("programs.col_music")}</th>
            <th scope="col">${t("programs.col_created_by")}</th>
            <th scope="col">${t("programs.col_active")}</th>
            <th scope="col"><span class="visually-hidden">${t("programs.col_actions")}</span></th>
          </tr>
        </thead>
        <tbody>
          ${shown.map((stored) => this.renderRow(stored))}
        </tbody>
      </table>
      ${shown.length ? nothing : html`<p role="status">${t("programs.no_match")}</p>`}
    `;
  }

  private renderRow(stored: ProgramOut) {
    const { program } = stored;
    const name = program.name;
    const active = isActive(stored);
    const error = this.rowErrors.get(stored.id);
    const days = program.weekdays.map((day) => t(`weekday.${day}`)).join(t("list_separator"));
    const music = program.music ? program.music.playlist_name || program.music.playlist : null;
    return html`<tr
      class=${active ? "" : "off"}
      data-program=${stored.id}
      @click=${(event: MouseEvent) => this.openFromRow(event, stored.id)}
    >
      <th scope="row">
        <a class="program-name" href="#/programs/${stored.id}"><strong>${name}</strong></a>
        <span class="secondary">${duration(stored.total_seconds)}</span>
        ${error ? html`<p class="error" role="alert">${error}</p>` : nothing}
      </th>
      <td>
        <span class="days" aria-hidden="true"
          >${WEEKDAYS.map(
            (day) => html`<span class=${program.weekdays.includes(day) ? "day on" : "day"}
              >${t(`weekday_letter.${day}`)}</span
            >`,
          )}</span
        >
        <span class="visually-hidden">${days || t("programs.no_weekdays")}</span>
      </td>
      <td>
        <span class="thumbs">
          ${program.stations.map((station, index) => {
            const label = stored.station_names[index] ?? station.exercise;
            return this.missing.has(station.exercise)
              ? html`<span class="thumb placeholder" role="img" aria-label=${label}>${icon(mdiDumbbell)}</span>`
              : html`<img
                  class="thumb"
                  src=${thumbnailUrl(station.exercise)}
                  alt=${label}
                  loading="lazy"
                  width="32"
                  height="32"
                  @error=${() => this.markMissing(station.exercise)}
                />`;
          })}
        </span>
      </td>
      <td>${music ?? html`<span class="secondary">${t("programs.no_music")}</span>`}</td>
      <td>
        ${stored.created_by === "claude"
          ? html`<span class="badge claude">${icon(mdiCreation)}<span>${t("programs.created_by_claude")}</span></span>`
          : stored.created_by === "you"
            ? html`<span class="badge">${icon(mdiAccount)}<span>${t("programs.created_by_you")}</span></span>`
            : nothing}
      </td>
      <td class="active-cell">
        <button
          type="button"
          class="switch"
          role="switch"
          aria-checked=${active ? "true" : "false"}
          aria-label=${t("programs.active", { name })}
          ?disabled=${this.pending.has(stored.id)}
          @click=${() => this.toggle(stored)}
        ></button>
      </td>
      <td class="actions">
        <a class="icon-button" href="#/programs/${stored.id}" aria-label=${t("programs.edit", { name })}
          >${icon(mdiPencil)}</a
        >
        <a class="icon-button" href="#/programs/new/copy/${stored.id}" aria-label=${t("programs.copy", { name })}
          >${icon(mdiContentCopy)}</a
        >
        <button
          type="button"
          class="icon-button"
          aria-label=${t("programs.delete", { name })}
          @click=${() => (this.deleting = { id: stored.id, busy: false, error: null })}
        >
          ${icon(mdiDelete)}
        </button>
      </td>
    </tr>`;
  }

  private renderDialog() {
    const deleting = this.deleting;
    const stored = deleting && this.programs?.find((candidate) => candidate.id === deleting.id);
    if (!deleting || !stored) return nothing;
    return html`<hf-confirm-dialog
      .heading=${t("programs.delete_title", { name: stored.program.name })}
      .message=${t("programs.delete_message")}
      .points=${[t("programs.delete_history"), t("programs.delete_open_days"), t("programs.delete_undo")]}
      .secondaryLead=${t("programs.delete_pause")}
      .secondaryLabel=${t("programs.turn_off")}
      .secondaryIcon=${mdiPauseCircleOutline}
      .confirmLabel=${t("programs.delete_confirm")}
      .icon=${mdiDeleteAlertOutline}
      .confirmIcon=${mdiDelete}
      .error=${deleting.error}
      .busy=${deleting.busy}
      @confirm=${() => this.confirmDelete()}
      @secondary=${() => this.turnOffInstead()}
      @cancel=${() => (this.deleting = null)}
    ></hf-confirm-dialog>`;
  }
}

/** The page's styles, for the shell's shadow root (the page renders in light DOM). */
export const programsPageStyles = css`
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }
  .page-header h1 {
    margin: 0;
  }
  /* The heading takes the focus from code after the last row is deleted; a heading draws no ring. */
  .page-header h1[tabindex="-1"]:focus {
    outline: none;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .search {
    display: flex;
    flex: 0 1 320px;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    background: var(--hf-card);
    border: 1px solid var(--hf-border);
    border-radius: 8px;
  }
  .search input {
    flex: 1;
    min-width: 0;
    padding: 10px 0;
    border: none;
    outline: none;
    background: transparent;
    font: inherit;
  }
  .chips {
    display: flex;
    gap: 8px;
  }
  table.programs {
    padding: 0;
  }
  .programs th[scope="row"] {
    color: var(--hf-text);
    font-size: 14px;
    font-weight: 400;
    text-transform: none;
  }
  .programs th,
  .programs td {
    padding: 12px;
    vertical-align: middle;
  }
  .programs th[scope="row"] strong,
  .programs th[scope="row"] .secondary {
    display: block;
  }
  /* A click on a row opens the program (#96). */
  .programs tbody tr {
    cursor: pointer;
  }
  .programs tbody tr:hover {
    background: var(--hf-background);
  }
  .programs td.active-cell,
  .programs td.actions {
    cursor: default;
  }
  .programs a.program-name {
    color: inherit;
    text-decoration: none;
  }
  .programs a.program-name:hover {
    text-decoration: underline;
  }
  .saved-note {
    margin: 0 0 16px;
    color: var(--hf-text-secondary);
  }
  .programs tr.off strong {
    color: var(--hf-text-secondary);
  }
  .secondary {
    color: var(--hf-text-secondary);
    font-size: 12px;
  }
  .days {
    display: inline-flex;
    gap: 4px;
  }
  .day {
    width: 16px;
    color: #bdbdbd;
    font-size: 12px;
    text-align: center;
  }
  .day.on {
    border-radius: 4px;
    background: var(--hf-primary-light);
    color: var(--hf-primary);
    font-weight: 500;
  }
  .thumbs {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .thumb {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 1px solid var(--hf-border);
    border-radius: 4px;
    background: var(--hf-card);
    object-fit: contain;
  }
  .thumb.placeholder .icon {
    width: 18px;
    height: 18px;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border-radius: 10px;
    background: #eeeeee;
    color: var(--hf-text-secondary);
    font-size: 12px;
  }
  .badge .icon {
    width: 14px;
    height: 14px;
    color: inherit;
  }
  .badge.claude {
    background: #fbe9e7;
    color: #d84315;
  }
  .actions {
    white-space: nowrap;
  }
  .programs p.error {
    margin: 6px 0 0;
    font-size: 12px;
  }
`;

if (!customElements.get("hf-programs-page")) customElements.define("hf-programs-page", ProgramsPage);

declare global {
  interface HTMLElementTagNameMap {
    "hf-programs-page": ProgramsPage;
  }
}
