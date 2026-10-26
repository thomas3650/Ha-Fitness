import {
  mdiAccount,
  mdiAlertOutline,
  mdiArrowDown,
  mdiArrowUp,
  mdiClose,
  mdiContentSave,
  mdiCreation,
  mdiDelete,
  mdiDeleteAlertOutline,
  mdiDragVertical,
  mdiDumbbell,
  mdiExitRun,
  mdiPauseCircleOutline,
} from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import {
  ApiError,
  createApi,
  thumbnailUrl,
  type Api,
  type ErrorItem,
  type ExerciseSummary,
  type FavouritePlaylist,
  type Music,
  type PlaylistOut,
  type ProgramDocument,
  type ProgramOut,
  type Setup,
  type SpeakerOut,
  type Weekday,
} from "../api";
import "../components/confirm-dialog";
import "../components/exercise-details";
import "../components/exercise-picker";
import { applySelectValues } from "../components/select-value";
import { minutes } from "../format";
import { t } from "../i18n";
import { icon } from "../icons";

/** Which program the editor works on: a new one, a copy of a stored one (stored only on Save), or a stored one. */
export type EditorMode = { kind: "new" } | { kind: "copy"; id: number } | { kind: "edit"; id: number };

const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const COUNTDOWNS = [0, 5, 10];
const BODY_WEIGHT = "body weight";

type NumberField = "rounds" | "work_seconds" | "switch_seconds" | "round_rest_seconds";

const NUMBER_FIELDS: { field: NumberField; label: string }[] = [
  { field: "rounds", label: "editor.rounds" },
  { field: "work_seconds", label: "editor.work" },
  { field: "switch_seconds", label: "editor.switch" },
  { field: "round_rest_seconds", label: "editor.round_rest" },
];

/** The places on the form a refusal can be shown at; any other field shows above the form. */
const PLACES = new Set([
  "name",
  ...NUMBER_FIELDS.map((entry) => entry.field),
  "weekdays",
  "music",
  "countdown_seconds",
  "active",
  "stations",
]);

/** The form's values. A number field is null while it is empty: the add-on decides what it means (website spec §5). */
interface Form {
  name: string;
  active: boolean;
  weekdays: Weekday[];
  stations: { exercise: string }[];
  rounds: number | null;
  work_seconds: number | null;
  switch_seconds: number | null;
  round_rest_seconds: number | null;
  countdown_seconds: number;
  playlist: { uri: string; name: string | null } | null;
  speaker: string;
  /** The music's fields the editor doesn't show (`volume`, `shuffle`); a save sends them back unchanged. */
  musicRest: Omit<Music, "playlist" | "playlist_name" | "speaker">;
}

/** A music read: its list, or the add-on's message when it was refused. */
interface MusicRead<T> {
  items: T[];
  error: string | null;
}

/** The delete confirmation's state, as on the Programs page. */
interface Deleting {
  busy: boolean;
  error: string | null;
}

/** An element the shell asks before it leaves the page (website spec §2.2.4). */
export interface LeaveGuard {
  /** Return true to hold the leave; the page calls `go` once the user agrees. */
  guardLeave(go: () => void): boolean;
}

let nextId = 0;

function formOf(document: ProgramDocument, defaultSpeaker: string | null): Form {
  // Every music field the editor doesn't show is kept as it is, including any the add-on adds later.
  const { playlist, playlist_name, speaker, ...rest } = document.music ?? {};
  return {
    name: document.name,
    active: document.active !== false,
    weekdays: [...document.weekdays],
    stations: document.stations.map((station) => ({ ...station })),
    rounds: document.rounds ?? null,
    work_seconds: document.work_seconds ?? null,
    switch_seconds: document.switch_seconds ?? null,
    round_rest_seconds: document.round_rest_seconds ?? null,
    countdown_seconds: document.countdown_seconds ?? 5,
    playlist: playlist ? { uri: playlist, name: playlist_name ?? null } : null,
    speaker: speaker ?? defaultSpeaker ?? "",
    musicRest: rest,
  };
}

/**
 * The whole document a save sends (a save replaces the whole program). The music goes only once a playlist is
 * picked, since the add-on needs one; empty number fields go as they are, for the add-on to refuse.
 */
function documentOf(form: Form): ProgramDocument {
  const music: Music | null = form.playlist
    ? { ...form.musicRest, playlist: form.playlist.uri, playlist_name: form.playlist.name, speaker: form.speaker }
    : null;
  return {
    name: form.name,
    active: form.active,
    weekdays: WEEKDAYS.filter((day) => form.weekdays.includes(day)),
    stations: form.stations,
    rounds: form.rounds,
    work_seconds: form.work_seconds,
    switch_seconds: form.switch_seconds,
    round_rest_seconds: form.round_rest_seconds,
    countdown_seconds: form.countdown_seconds,
    music,
  } as ProgramDocument;
}

/** Where on the form a refusal's field shows: a station by its index, a known field, or null for above the form. */
function placeOf(field: string | null, stations: number): string | null {
  if (!field) return null;
  const [head, index] = field.split(".");
  if (head === "stations" && index !== undefined && /^\d+$/.test(index) && Number(index) < stations) {
    return `stations.${index}`;
  }
  return PLACES.has(head) ? head : null;
}

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  throw error;
}

/** A failed read's text for the page: the add-on's message, or the error's own, so no read leaves "Loading…". */
function failure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

/**
 * The program editor (W3, website spec §2.2.4): the fields at the top, the exercises as a list, the library beside
 * it, the summary line, and Save, Cancel and Delete. It holds no program rules: a save sends the whole document and
 * the add-on's refusal shows at the field it is about, or above the form, with nothing typed lost. An edit sends
 * the `updated_at` it loaded (`if_updated_at`), so a change made elsewhere isn't undone (§2.2.6).
 */
export class ProgramEditor extends LitElement implements LeaveGuard {
  static override properties = {
    api: { attribute: false },
    mode: { attribute: false },
    form: { state: true },
    saved: { state: true },
    loadError: { state: true },
    exercises: { state: true },
    exercisesError: { state: true },
    setupError: { state: true },
    setup: { state: true },
    speakers: { state: true },
    playlists: { state: true },
    createdBy: { state: true },
    storedName: { state: true },
    busy: { state: true },
    fieldErrors: { state: true },
    formErrors: { state: true },
    conflict: { state: true },
    justSaved: { state: true },
    leaving: { state: true },
    deleting: { state: true },
    details: { state: true },
    missing: { state: true },
  };

  declare api: Api;
  declare mode: EditorMode;
  declare form: Form | null;
  /** The document as last loaded or saved, to tell unsaved changes. */
  declare saved: string;
  declare loadError: string | null;
  declare exercises: ExerciseSummary[] | null;
  declare exercisesError: string | null;
  /** Why the setup couldn't be read, if it couldn't. */
  declare setupError: string | null;
  declare setup: Setup;
  declare speakers: MusicRead<SpeakerOut>;
  declare playlists: MusicRead<PlaylistOut>;
  declare createdBy: ProgramOut["created_by"];
  declare storedName: string;
  declare busy: boolean;
  declare fieldErrors: ReadonlyMap<string, string[]>;
  declare formErrors: string[];
  /** The add-on's message when the program was changed elsewhere; Reload loads it. */
  declare conflict: string | null;
  declare justSaved: boolean;
  /** The way out the user asked for while there are unsaved changes; the leave dialog shows while it is set. */
  declare leaving: (() => void) | null;
  declare deleting: Deleting | null;
  declare details: ExerciseSummary | null;
  declare missing: ReadonlySet<string>;

  private updatedAt: string | undefined;
  /**
   * The stored program this editor saves to: the edited one, or the one a create stored. From then on a Save
   * replaces it, so a second Save never creates another.
   */
  private storedId: number | null = null;
  /** Station names from the stored program, for exercises the summaries don't have. */
  private storedNames = new Map<string, string>();
  private dragIndex: number | null = null;
  private readonly ids = `hf-editor-${++nextId}`;
  private readonly onBeforeUnload = (event: BeforeUnloadEvent) => {
    if (!this.dirty) return;
    event.preventDefault();
    // Older browsers ask only when the return value is set.
    event.returnValue = "";
  };

  constructor() {
    super();
    this.api = createApi();
    this.mode = { kind: "new" };
    this.form = null;
    this.saved = "";
    this.loadError = null;
    this.exercises = null;
    this.exercisesError = null;
    this.setupError = null;
    this.setup = { equipment: [], favourite_playlists: [], default_speaker: null };
    this.speakers = { items: [], error: null };
    this.playlists = { items: [], error: null };
    this.createdBy = null;
    this.storedName = "";
    this.busy = false;
    this.fieldErrors = new Map();
    this.formErrors = [];
    this.conflict = null;
    this.justSaved = false;
    this.leaving = null;
    this.deleting = null;
    this.details = null;
    this.missing = new Set();
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  protected override updated(): void {
    applySelectValues(this);
  }

  override connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener("beforeunload", this.onBeforeUnload);
    void this.load();
  }

  override disconnectedCallback(): void {
    window.removeEventListener("beforeunload", this.onBeforeUnload);
    super.disconnectedCallback();
  }

  /** Whether the form differs from the document as last loaded or saved. */
  get dirty(): boolean {
    return this.form !== null && JSON.stringify(documentOf(this.form)) !== this.saved;
  }

  guardLeave(go: () => void): boolean {
    if (!this.dirty) return false;
    this.leaving = go;
    return true;
  }

  private async load(): Promise<void> {
    const mode = this.mode;
    if (mode.kind === "edit") this.storedId = mode.id;
    const first = mode.kind === "new" ? this.api.programDefaults() : this.api.program(mode.id);
    const [main, setup, exercises, speakers, playlists] = await Promise.allSettled([
      first,
      this.api.setup(),
      this.api.allExercises(),
      this.api.speakers(),
      this.api.playlists(),
    ]);
    // Without the setup the editor works with an empty one (body weight only, no favourites, no default speaker),
    // and says why.
    if (setup.status === "fulfilled") this.setup = setup.value;
    else this.setupError = failure(setup.reason);
    if (exercises.status === "fulfilled") this.exercises = exercises.value;
    else this.exercisesError = failure(exercises.reason);
    this.speakers =
      speakers.status === "fulfilled"
        ? { items: speakers.value, error: null }
        : { items: [], error: failure(speakers.reason) };
    this.playlists =
      playlists.status === "fulfilled"
        ? { items: playlists.value, error: null }
        : { items: [], error: failure(playlists.reason) };
    if (main.status === "rejected") {
      this.loadError = failure(main.reason);
      return;
    }
    if (mode.kind === "new") {
      const defaults = main.value as Awaited<ReturnType<Api["programDefaults"]>>;
      this.start(
        formOf(
          { name: "", active: true, weekdays: [], stations: [], music: null, ...defaults },
          this.setup.default_speaker,
        ),
      );
      return;
    }
    const stored = main.value as ProgramOut;
    this.remember(stored);
    if (mode.kind === "copy") {
      const form = formOf(stored.program, this.setup.default_speaker);
      this.start({ ...form, name: t("editor.copy_name", { name: stored.program.name }), active: false });
    } else {
      this.useStored(stored);
    }
  }

  private remember(stored: ProgramOut): void {
    stored.program.stations.forEach((station, index) => {
      const name = stored.station_names[index];
      if (name) this.storedNames.set(station.exercise, name);
    });
  }

  /** Show a form whose values count as saved. */
  private start(form: Form): void {
    this.form = form;
    this.saved = JSON.stringify(documentOf(form));
  }

  private useStored(stored: ProgramOut): void {
    this.updatedAt = stored.updated_at;
    this.createdBy = stored.created_by;
    this.storedName = stored.program.name;
    this.start(formOf(stored.program, this.setup.default_speaker));
  }

  private change(patch: Partial<Form>): void {
    if (!this.form) return;
    this.form = { ...this.form, ...patch };
    this.justSaved = false;
  }

  private summaryOf(id: string): ExerciseSummary | undefined {
    return this.exercises?.find((exercise) => exercise.id === id);
  }

  private nameOf(id: string): string {
    return this.summaryOf(id)?.name ?? this.storedNames.get(id) ?? id;
  }

  // The stations.

  private addStation(id: string): void {
    if (!this.form) return;
    this.change({ stations: [...this.form.stations, { exercise: id }] });
  }

  private removeStation(index: number): void {
    if (!this.form) return;
    this.change({ stations: this.form.stations.filter((_, at) => at !== index) });
  }

  private moveStation(from: number, to: number): void {
    if (!this.form || to < 0 || to >= this.form.stations.length || from === to) return;
    const stations = [...this.form.stations];
    const [moved] = stations.splice(from, 1);
    stations.splice(to, 0, moved);
    this.change({ stations });
  }

  // The music.

  /** The playlists to pick from: the setup's favourites first, then Music Assistant's, then the stored one. */
  private playlistChoices(): { favourites: FavouritePlaylist[]; others: PlaylistOut[] } {
    const favourites = this.setup.favourite_playlists;
    const known = new Set(favourites.map((playlist) => playlist.uri));
    const others = this.playlists.items.filter((playlist) => !known.has(playlist.uri));
    const current = this.form?.playlist;
    if (current && !known.has(current.uri) && !others.some((playlist) => playlist.uri === current.uri)) {
      others.unshift({ uri: current.uri, name: current.name ?? current.uri });
    }
    return { favourites, others };
  }

  private pickPlaylist(uri: string): void {
    if (!uri) {
      this.change({ playlist: null });
      return;
    }
    const { favourites, others } = this.playlistChoices();
    const found = [...favourites, ...others].find((playlist) => playlist.uri === uri);
    this.change({ playlist: { uri, name: found?.name ?? null } });
  }

  // Saving.

  private clearRefusals(): void {
    this.fieldErrors = new Map();
    this.formErrors = [];
    this.conflict = null;
  }

  private showRefusal(error: ApiError): void {
    if (error.code === "changed_elsewhere") {
      this.conflict = error.message;
      return;
    }
    const fields = new Map<string, string[]>();
    const above: string[] = [];
    for (const item of error.items as ErrorItem[]) {
      const place = placeOf(item.field, this.form?.stations.length ?? 0);
      if (place) fields.set(place, [...(fields.get(place) ?? []), item.message]);
      else above.push(item.message);
    }
    this.fieldErrors = fields;
    this.formErrors = above;
  }

  private async save(): Promise<void> {
    if (!this.form || this.busy) return;
    this.busy = true;
    this.justSaved = false;
    this.clearRefusals();
    const document = documentOf(this.form);
    const sent = JSON.stringify(document);
    try {
      const stored =
        this.storedId === null
          ? await this.api.createProgram(document)
          : await this.api.replaceProgram(this.storedId, document, this.updatedAt);
      this.storedId = stored.id;
      this.updatedAt = stored.updated_at;
      this.createdBy = stored.created_by;
      this.storedName = stored.program.name;
      this.saved = sent;
      this.justSaved = true;
      const route = `#/programs/${stored.id}`;
      // A new program or a copy opens as the stored program. Anything typed while the request ran is still unsaved,
      // so the leave guard asks first; staying keeps it, and the next Save replaces the stored program.
      if (location.hash !== route) location.hash = route;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      this.showRefusal(error);
    } finally {
      this.busy = false;
    }
  }

  /** Load the stored program again after a change made elsewhere; what was typed gives way to it. */
  private async reload(): Promise<void> {
    if (this.storedId === null || this.busy) return;
    this.busy = true;
    try {
      const stored = await this.api.program(this.storedId);
      this.remember(stored);
      this.clearRefusals();
      this.useStored(stored);
    } catch (error) {
      this.formErrors = [message(error)];
    } finally {
      this.busy = false;
    }
  }

  private cancel(): void {
    location.hash = "#/programs";
  }

  private leave(): void {
    const go = this.leaving;
    this.leaving = null;
    if (!go || !this.form) return;
    // The user chose to drop the changes: the form counts as saved, so nothing asks again.
    this.saved = JSON.stringify(documentOf(this.form));
    go();
  }

  private async confirmDelete(): Promise<void> {
    const id = this.storedId;
    if (id === null || !this.deleting || this.deleting.busy) return;
    this.deleting = { busy: true, error: null };
    try {
      await this.api.deleteProgram(id);
      this.deleting = null;
      if (this.form) this.saved = JSON.stringify(documentOf(this.form));
      location.hash = "#/programs";
    } catch (error) {
      this.deleting = { busy: false, error: message(error) };
    }
  }

  private async turnOffInstead(): Promise<void> {
    const id = this.storedId;
    if (id === null || !this.deleting || this.deleting.busy) return;
    this.deleting = { busy: true, error: null };
    try {
      const stored = await this.api.setActive(id, false);
      this.updatedAt = stored.updated_at;
      const saved = JSON.parse(this.saved) as ProgramDocument;
      this.saved = JSON.stringify({ ...saved, active: false });
      this.change({ active: false });
      this.deleting = null;
    } catch (error) {
      this.deleting = { busy: false, error: message(error) };
    }
  }

  // Rendering.

  private errorId(place: string): string {
    return `${this.ids}-error-${place.replace(/\W/g, "-")}`;
  }

  /** The `aria-describedby` for a place with a refusal, or nothing. */
  private describedBy(place: string) {
    return this.fieldErrors.has(place) ? this.errorId(place) : nothing;
  }

  private renderFieldError(place: string) {
    const errors = this.fieldErrors.get(place);
    if (!errors) return nothing;
    return html`<p class="field-error" id=${this.errorId(place)}>${errors.join(t("sentence_separator"))}</p>`;
  }

  private pageTitle(): string {
    return t(`editor.${this.mode.kind === "new" ? "new" : this.mode.kind}_title`);
  }

  protected override render() {
    if (this.loadError) {
      return html`<h1>${this.pageTitle()}</h1>
        <p class="error" role="alert">${this.loadError}</p>`;
    }
    const form = this.form;
    if (!form) {
      return html`<h1>${this.pageTitle()}</h1>
        <p>${t("editor.loading")}</p>`;
    }
    return html`<div class="editor">
        <div class="editor-main">
          ${this.renderHeader(form)} ${this.renderAbove()} ${this.renderFields(form)} ${this.renderStations(form)}
          ${this.renderSummary(form)}
        </div>
        <hf-exercise-picker
          .exercises=${this.exercises}
          .error=${this.exercisesError}
          .household=${this.setup.equipment}
          .inProgram=${new Set(form.stations.map((station) => station.exercise))}
          @pick=${(event: CustomEvent<string>) => this.addStation(event.detail)}
          @details=${(event: CustomEvent<ExerciseSummary>) => (this.details = event.detail)}
        ></hf-exercise-picker>
      </div>
      ${this.renderDialogs()}`;
  }

  private renderHeader(form: Form) {
    return html`<header class="editor-header">
      <div>
        <nav class="breadcrumb" aria-label=${t("editor.breadcrumb")}>
          <a href="#/programs">${t("menu.programs")}</a> <span aria-hidden="true">${t("breadcrumb_separator")}</span>
          <span class="crumb">${form.name || t("editor.untitled")}</span>
          ${this.storedId !== null && this.createdBy === "claude"
            ? html`<span class="badge claude">${icon(mdiCreation)}<span>${t("editor.created_by_claude")}</span></span>`
            : this.storedId !== null && this.createdBy === "you"
              ? html`<span class="badge">${icon(mdiAccount)}<span>${t("editor.created_by_you")}</span></span>`
              : nothing}
        </nav>
        <h1>${this.pageTitle()}</h1>
      </div>
      <div class="editor-actions">
        ${this.storedId !== null
          ? html`<button
              type="button"
              class="text danger-text"
              @click=${() => (this.deleting = { busy: false, error: null })}
            >
              ${icon(mdiDelete)}<span>${t("editor.delete")}</span>
            </button>`
          : nothing}
        <button type="button" class="text" @click=${() => this.cancel()}>${t("editor.cancel")}</button>
        <button type="button" class="button primary" ?disabled=${this.busy} @click=${() => this.save()}>
          ${icon(mdiContentSave)}<span>${t("editor.save")}</span>
        </button>
      </div>
    </header>`;
  }

  private renderAbove() {
    if (!this.conflict && !this.formErrors.length) return nothing;
    return html`<div class="error" role="alert">
      ${this.formErrors.map((text) => html`<p>${text}</p>`)}
      ${this.conflict
        ? html`<p>
            <span>${this.conflict}</span>
            <button type="button" class="link" ?disabled=${this.busy} @click=${() => this.reload()}>
              ${t("editor.reload")}
            </button>
          </p>`
        : nothing}
    </div>`;
  }

  private renderFields(form: Form) {
    const { favourites, others } = this.playlistChoices();
    const speakerListed = this.speakers.items.some((speaker) => speaker.entity_id === form.speaker);
    return html`<div class="editor-fields" role="group" aria-label=${t("editor.form")}>
      <div class="field-row">
        <label class="field grow">
          <span>${t("editor.name")}</span>
          <input
            type="text"
            aria-label=${t("editor.name")}
            .value=${form.name}
            aria-invalid=${this.fieldErrors.has("name") ? "true" : "false"}
            aria-describedby=${this.describedBy("name")}
            @input=${(event: Event) => this.change({ name: (event.target as HTMLInputElement).value })}
          />
          ${this.renderFieldError("name")}
        </label>
        ${NUMBER_FIELDS.map(
          ({ field, label }) => html`<label class="field">
            <span>${t(label)}</span>
            <input
              type="number"
              min="0"
              aria-label=${t(label)}
              .value=${form[field] === null ? "" : String(form[field])}
              aria-invalid=${this.fieldErrors.has(field) ? "true" : "false"}
              aria-describedby=${this.describedBy(field)}
              @input=${(event: Event) => {
                const text = (event.target as HTMLInputElement).value;
                this.change({ [field]: text === "" ? null : Number(text) });
              }}
            />
            ${this.renderFieldError(field)}
          </label>`,
        )}
      </div>
      <div class="field">
        <span id=${`${this.ids}-weekdays`}>${t("editor.weekdays")}</span>
        <div
          class="chips"
          role="group"
          aria-labelledby=${`${this.ids}-weekdays`}
          aria-describedby=${this.describedBy("weekdays")}
        >
          ${WEEKDAYS.map(
            (day) => html`<button
              type="button"
              class="chip"
              aria-pressed=${form.weekdays.includes(day) ? "true" : "false"}
              @click=${() =>
                this.change({
                  weekdays: form.weekdays.includes(day)
                    ? form.weekdays.filter((other) => other !== day)
                    : WEEKDAYS.filter((other) => other === day || form.weekdays.includes(other)),
                })}
            >
              ${t(`weekday.${day}`)}
            </button>`,
          )}
        </div>
        ${this.renderFieldError("weekdays")}
      </div>
      <div class="field-row">
        <div
          class="field-row grow"
          role="group"
          aria-label=${t("editor.music_group")}
          aria-describedby=${this.describedBy("music")}
        >
          <label class="field grow">
            <span>${t("editor.music")}</span>
            <select
              aria-label=${t("editor.music")}
              data-value=${form.playlist?.uri ?? ""}
              @change=${(event: Event) => this.pickPlaylist((event.target as HTMLSelectElement).value)}>
              <option value="">${t("editor.no_music")}</option>
              ${favourites.length
                ? html`<optgroup label=${t("editor.favourites")}>
                    ${favourites.map(
                      (playlist) =>
                        html`<option value=${playlist.uri}>
                          ${playlist.name}
                        </option>`,
                    )}
                  </optgroup>`
                : nothing}
              ${others.length
                ? html`<optgroup label=${t("editor.playlists")}>
                    ${others.map(
                      (playlist) =>
                        html`<option value=${playlist.uri}>
                          ${playlist.name}
                        </option>`,
                    )}
                  </optgroup>`
                : nothing}
            </select>
            ${this.playlists.error || !this.playlists.items.length
              ? html`<span class="secondary">${this.playlists.error ?? t("editor.no_playlists")}</span>`
              : nothing}
          </label>
          <label class="field grow">
            <span>${t("editor.speaker")}</span>
            <select
              aria-label=${t("editor.speaker")}
              data-value=${form.speaker}
              @change=${(event: Event) => this.change({ speaker: (event.target as HTMLSelectElement).value })}>
              ${form.speaker
                ? nothing
                : html`<option value="">${t("editor.choose_speaker")}</option>`}
              ${form.speaker && !speakerListed
                ? html`<option value=${form.speaker}>${form.speaker}</option>`
                : nothing}
              ${this.speakers.items.map(
                (speaker) =>
                  html`<option value=${speaker.entity_id}>
                    ${speaker.name}
                  </option>`,
              )}
            </select>
            ${this.speakers.error || !this.speakers.items.length
              ? html`<span class="secondary">${this.speakers.error ?? t("editor.no_speakers")}</span>`
              : nothing}
          </label>
          ${this.setupError ? html`<span class="secondary">${this.setupError}</span>` : nothing}
          ${this.renderFieldError("music")}
        </div>
        <label class="field">
          <span>${t("editor.countdown")}</span>
          <select
            aria-label=${t("editor.countdown")}
            data-value=${String(form.countdown_seconds)}
            aria-describedby=${this.describedBy("countdown_seconds")}
            @change=${(event: Event) =>
              this.change({ countdown_seconds: Number((event.target as HTMLSelectElement).value) })}
          >
            ${COUNTDOWNS.map(
              (seconds) =>
                html`<option value=${String(seconds)}>
                  ${t("editor.seconds", { seconds })}
                </option>`,
            )}
          </select>
          ${this.renderFieldError("countdown_seconds")}
        </label>
        <div class="field">
          <span id=${`${this.ids}-active`}>${t("editor.active")}</span>
          <button
            type="button"
            class="switch"
            role="switch"
            aria-checked=${form.active ? "true" : "false"}
            aria-labelledby=${`${this.ids}-active`}
            aria-describedby=${this.describedBy("active")}
            @click=${() => this.change({ active: !form.active })}
          ></button>
          ${this.renderFieldError("active")}
        </div>
      </div>
    </div>`;
  }

  private renderStations(form: Form) {
    return html`<div class="card stations">
      <ol aria-label=${t("editor.stations")} aria-describedby=${this.describedBy("stations")}>
        ${form.stations.map((station, index) => this.renderStation(station.exercise, index, form.stations.length))}
      </ol>
      <p class="secondary">${t(form.stations.length ? "editor.drag_hint" : "editor.no_stations")}</p>
      ${this.renderFieldError("stations")}
    </div>`;
  }

  private renderStation(id: string, index: number, count: number) {
    const name = this.nameOf(id);
    const summary = this.summaryOf(id);
    const meta = summary ? [summary.equipment, summary.body_part].filter(Boolean).join(t("meta_separator")) : "";
    const place = `stations.${index}`;
    return html`<li
      draggable="true"
      aria-describedby=${this.describedBy(place)}
      @dragstart=${() => (this.dragIndex = index)}
      @dragend=${() => (this.dragIndex = null)}
      @dragover=${(event: DragEvent) => event.preventDefault()}
      @drop=${(event: DragEvent) => {
        event.preventDefault();
        if (this.dragIndex !== null) this.moveStation(this.dragIndex, index);
        this.dragIndex = null;
      }}
    >
      <span class="drag" aria-hidden="true">${icon(mdiDragVertical)}</span>
      <span class="number">${index + 1}</span>
      ${this.missing.has(id)
        ? html`<span class="thumb placeholder" aria-hidden="true">${icon(mdiDumbbell)}</span>`
        : html`<img
            class="thumb"
            src=${thumbnailUrl(id)}
            alt=""
            loading="lazy"
            width="40"
            height="40"
            @error=${() => (this.missing = new Set([...this.missing, id]))}
          />`}
      <span class="station-name">${name}${this.renderFieldError(place)}</span>
      <span class="secondary station-meta">${meta}</span>
      <button
        type="button"
        class="icon-button"
        aria-label=${t("editor.move_up", { name })}
        ?disabled=${index === 0}
        @click=${() => this.moveStation(index, index - 1)}
      >
        ${icon(mdiArrowUp)}
      </button>
      <button
        type="button"
        class="icon-button"
        aria-label=${t("editor.move_down", { name })}
        ?disabled=${index === count - 1}
        @click=${() => this.moveStation(index, index + 1)}
      >
        ${icon(mdiArrowDown)}
      </button>
      <button
        type="button"
        class="icon-button"
        aria-label=${t("editor.remove", { name })}
        @click=${() => this.removeStation(index)}
      >
        ${icon(mdiClose)}
      </button>
    </li>`;
  }

  private renderSummary(form: Form) {
    const stations = form.stations.length;
    const rounds = form.rounds ?? 0;
    // The add-on's total_seconds: S·R·(W + switch) + (R − 1)·round rest.
    const seconds =
      stations * rounds * ((form.work_seconds ?? 0) + (form.switch_seconds ?? 0)) +
      Math.max(0, rounds - 1) * (form.round_rest_seconds ?? 0);
    const equipment = [
      ...new Set(
        form.stations
          .map((station) => this.summaryOf(station.exercise)?.equipment)
          .filter((value): value is string => !!value && value !== BODY_WEIGHT),
      ),
    ];
    return html`<p class="summary">
      <span><strong>${t("editor.exercises", { count: stations })}</strong></span>
      <span><strong>${t("editor.minutes", { minutes: minutes(Math.max(0, seconds)) })}</strong></span>
      <span
        >${equipment.length
          ? t("editor.equipment", { equipment: equipment.join(t("list_separator")) })
          : t("editor.no_equipment")}</span
      >
      ${this.dirty
        ? html`<span class="not-saved">${icon(mdiAlertOutline)}<span>${t("editor.not_saved")}</span></span>`
        : this.justSaved
          ? html`<span class="secondary" role="status">${t("editor.saved")}</span>`
          : nothing}
    </p>`;
  }

  private renderDialogs() {
    return html`
      ${this.details
        ? html`<hf-exercise-details
            .api=${this.api}
            .exercise=${this.details}
            .canAdd=${true}
            @close=${() => (this.details = null)}
            @add=${() => {
              if (this.details) this.addStation(this.details.id);
              this.details = null;
            }}
          ></hf-exercise-details>`
        : nothing}
      ${this.leaving
        ? html`<hf-confirm-dialog
            .heading=${t("editor.leave_title")}
            .message=${t("editor.leave_message")}
            .confirmLabel=${t("editor.leave_confirm")}
            .icon=${mdiAlertOutline}
            .confirmIcon=${mdiExitRun}
            @confirm=${() => this.leave()}
            @cancel=${() => (this.leaving = null)}
          ></hf-confirm-dialog>`
        : nothing}
      ${this.deleting
        ? html`<hf-confirm-dialog
            .heading=${t("programs.delete_title", { name: this.storedName })}
            .message=${t("programs.delete_message")}
            .points=${[t("programs.delete_history"), t("programs.delete_open_days"), t("programs.delete_undo")]}
            .secondaryLead=${t("programs.delete_pause")}
            .secondaryLabel=${t("programs.turn_off")}
            .secondaryIcon=${mdiPauseCircleOutline}
            .confirmLabel=${t("programs.delete_confirm")}
            .icon=${mdiDeleteAlertOutline}
            .confirmIcon=${mdiDelete}
            .error=${this.deleting.error}
            .busy=${this.deleting.busy}
            @confirm=${() => this.confirmDelete()}
            @secondary=${() => this.turnOffInstead()}
            @cancel=${() => (this.deleting = null)}
          ></hf-confirm-dialog>`
        : nothing}
    `;
  }
}

/** The editor's styles, for the shell's shadow root (the editor renders in light DOM). */
export const programEditorStyles = css`
  .editor {
    display: flex;
    gap: 24px;
    align-items: flex-start;
  }
  .editor-main {
    flex: 1;
    min-width: 0;
  }
  hf-exercise-picker {
    flex: 0 0 300px;
    padding-left: 20px;
    border-left: 1px solid var(--hf-border);
  }
  .editor-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
  }
  .editor-header h1 {
    margin: 4px 0 0;
  }
  .breadcrumb {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--hf-text-secondary);
  }
  .breadcrumb .crumb {
    color: var(--hf-text);
    font-weight: 500;
  }
  .editor-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  button.danger-text {
    color: var(--hf-error);
  }
  button.danger-text .icon {
    width: 18px;
    height: 18px;
    color: inherit;
  }
  .editor-fields {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 16px;
  }
  .field-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 12px;
    background: var(--hf-card);
    border: 1px solid var(--hf-border);
    border-radius: 8px;
    color: var(--hf-text-secondary);
    font-size: 12px;
  }
  .field-row > .field-row {
    padding: 0;
  }
  .field.grow,
  .field-row.grow {
    flex: 1;
  }
  .field input,
  .field select {
    width: 100%;
    min-width: 72px;
    padding: 4px 0;
    border: none;
    background: transparent;
    color: var(--hf-text);
    font: inherit;
    font-size: 14px;
  }
  .field input[aria-invalid="true"] {
    color: var(--hf-error);
  }
  .field-error {
    margin: 2px 0 0;
    color: var(--hf-error);
    font-size: 12px;
  }
  .stations {
    padding: 0;
  }
  .stations ol {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .stations li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--hf-border);
  }
  .stations .drag {
    cursor: grab;
  }
  .stations .number {
    width: 20px;
    color: var(--hf-text-secondary);
  }
  .stations .thumb {
    width: 40px;
    height: 40px;
  }
  .station-name {
    flex: 1;
  }
  .station-meta {
    flex: 1;
  }
  .stations > p {
    margin: 12px 16px;
  }
  .summary {
    display: flex;
    align-items: center;
    gap: 16px;
    color: var(--hf-text-secondary);
  }
  .summary strong {
    color: var(--hf-text);
  }
  .not-saved {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #e65100;
  }
  .not-saved .icon {
    width: 16px;
    height: 16px;
    color: inherit;
  }
  .error p {
    margin: 4px 0;
  }
`;

if (!customElements.get("hf-program-editor")) customElements.define("hf-program-editor", ProgramEditor);

declare global {
  interface HTMLElementTagNameMap {
    "hf-program-editor": ProgramEditor;
  }
}
