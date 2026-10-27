import {
  mdiAccountGroup,
  mdiAlertOutline,
  mdiArrowDown,
  mdiArrowUp,
  mdiClose,
  mdiContentSave,
  mdiDumbbell,
  mdiExitRun,
  mdiPlaylistStar,
  mdiSpeaker,
  mdiStar,
} from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import {
  ApiError,
  createApi,
  type Api,
  type ErrorItem,
  type ExerciseSummary,
  type FavouritePlaylist,
  type HaPerson,
  type NewPerson,
  type PlaylistOut,
  type Setup,
  type SpeakerOut,
} from "../api";
import "../components/confirm-dialog";
import "../components/multi-select";
import { applySelectValues } from "../components/select-value";
import { failure } from "../failure";
import { t } from "../i18n";
import { icon } from "../icons";
import type { LeaveGuard } from "../leave-guard";
import { BAND, BAND_NAMES, BODY_WEIGHT, facetValues } from "../library-filter";

/**
 * Equipment the household chooses as one: the dataset names a band both ways, and the household filter compares
 * exactly, so the "band" chip stores both (website spec §2.4.1).
 */
const GROUPS: Record<string, readonly string[]> = { [BAND]: BAND_NAMES };

/** The people's colours, by people order, as the cards have them (design §3.4). */
const PERSON_COLORS = ["#B18CFF", "#3DD6C6"];

/** One equipment option: its label and the values it stands for. */
interface Choice {
  label: string;
  values: string[];
}

/** A list read from Music Assistant, or the add-on's reason it couldn't be read. */
interface MusicRead<T> {
  items: T[];
  error: string | null;
}

/** Where a setup refusal shows: at a card, or above the page. */
type Place = "equipment" | "playlists" | "speaker" | "page";

/** A failed save's items: a refusal's own, or a bug's generic message without a field (above the card). */
function itemsOf(error: unknown): ErrorItem[] {
  // The code stays empty: nothing reads the code of an item without a field.
  return error instanceof ApiError ? error.items : [{ field: null, code: "", message: failure(error) }];
}

function placeOf(item: ErrorItem): Place {
  const field = item.field ?? "";
  if (field === "equipment" || field.startsWith("equipment.")) return "equipment";
  if (field.startsWith("favourite_playlists")) return "playlists";
  if (field === "default_speaker") return "speaker";
  return "page";
}

/** The equipment as Save sends it: body weight is always in the household; the add-on adds it as well. */
function withBodyWeight(equipment: string[]): string[] {
  return equipment.includes(BODY_WEIGHT) ? equipment : [BODY_WEIGHT, ...equipment];
}

/**
 * What Save would send, for telling whether the setup is unsaved. The equipment is a set, so its order doesn't count
 * (taking an option off and on again puts its values last); the favourites' order does.
 */
function setupKey(setup: Setup): string {
  const { equipment, favourite_playlists, default_speaker } = setup;
  return JSON.stringify({ equipment: [...withBodyWeight(equipment)].sort(), favourite_playlists, default_speaker });
}

/** What "Save people" would send, in order, for telling whether the people are unsaved. */
function peopleKey(people: NewPerson[]): string {
  return JSON.stringify(people.map(({ name, person_entity_id }) => ({ name, person_entity_id })));
}

/**
 * The equipment options besides body weight: every equipment of the exercises and of the stored setup, sorted, with a
 * group (band and resistance band) as one option. A group stands only for the values the exercises or the setup
 * have, so an option never sends equipment the add-on doesn't know.
 */
function choices(exercises: ExerciseSummary[], stored: Iterable<string>): Choice[] {
  const known = new Set([...facetValues(exercises, "equipment"), ...stored]);
  known.delete(BODY_WEIGHT);
  const grouped = new Map<string, Choice>();
  for (const value of [...known].sort()) {
    const label = Object.keys(GROUPS).find((group) => GROUPS[group].includes(value)) ?? value;
    const choice = grouped.get(label) ?? { label, values: [] };
    choice.values.push(value);
    grouped.set(label, choice);
  }
  return [...grouped.values()].sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * The Setup page (website spec §2.4, W6): the household's equipment, the people who train, the default speaker and
 * the favourite playlists. Save stores the setup; the people save on their own with "Save people", since that write
 * can fail while Home Assistant is unreachable. The add-on decides both writes; its refusal shows where it belongs and
 * nothing chosen is lost. Either part unsaved shows "Not saved" by its Save, and leaving the page asks first.
 */
export class SetupPage extends LitElement implements LeaveGuard {
  static override properties = {
    api: { attribute: false },
    loaded: { state: true },
    setup: { state: true },
    loadError: { state: true },
    exercises: { state: true },
    exercisesError: { state: true },
    speakers: { state: true },
    playlists: { state: true },
    people: { state: true },
    haPersons: { state: true },
    peopleNote: { state: true },
    errors: { state: true },
    saving: { state: true },
    saved: { state: true },
    peopleErrors: { state: true },
    peopleSaving: { state: true },
    peopleSaved: { state: true },
    removing: { state: true },
    savedSetup: { state: true },
    savedPeople: { state: true },
    leaving: { state: true },
  };

  declare api: Api;
  declare loaded: boolean;
  /** The setup as edited; null when it couldn't be read. */
  declare setup: Setup | null;
  declare loadError: string | null;
  declare exercises: ExerciseSummary[];
  declare exercisesError: string | null;
  declare speakers: MusicRead<SpeakerOut>;
  declare playlists: MusicRead<PlaylistOut>;
  /**
   * The people as edited, in order; null when they couldn't be read. Then nothing is offered for saving: a save
   * would replace the stored people with an empty list (D33).
   */
  declare people: NewPerson[] | null;
  /** HA's persons; null when HA can't be read. */
  declare haPersons: HaPerson[] | null;
  /** Why the people or HA's persons couldn't be read. */
  declare peopleNote: string | null;
  declare errors: ErrorItem[];
  declare saving: boolean;
  declare saved: boolean;
  declare peopleErrors: ErrorItem[];
  declare peopleSaving: boolean;
  declare peopleSaved: boolean;
  /** The index of the person the removal dialog asks about. */
  declare removing: number | null;
  /** The setup as last loaded or saved (`setupKey`); empty while it isn't read. */
  declare savedSetup: string;
  /** The people as last loaded or saved (`peopleKey`); empty while they aren't read. */
  declare savedPeople: string;
  /** The way out the user asked for while something is unsaved; the leave dialog shows while it is set. */
  declare leaving: (() => void) | null;

  private readonly onBeforeUnload = (event: BeforeUnloadEvent) => {
    if (!this.dirty) return;
    event.preventDefault();
    // Older browsers ask only when the return value is set.
    event.returnValue = "";
  };

  constructor() {
    super();
    this.api = createApi();
    this.loaded = false;
    this.setup = null;
    this.loadError = null;
    this.exercises = [];
    this.exercisesError = null;
    this.speakers = { items: [], error: null };
    this.playlists = { items: [], error: null };
    this.people = null;
    this.haPersons = null;
    this.peopleNote = null;
    this.errors = [];
    this.saving = false;
    this.saved = false;
    this.peopleErrors = [];
    this.peopleSaving = false;
    this.peopleSaved = false;
    this.removing = null;
    this.savedSetup = "";
    this.savedPeople = "";
    this.leaving = null;
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

  /** Whether the setup differs from the one last loaded or saved; a setup that couldn't be read never does. */
  get setupDirty(): boolean {
    return this.setup !== null && setupKey(this.setup) !== this.savedSetup;
  }

  /** Whether the people differ from those last loaded or saved; people that couldn't be read never do. */
  get peopleDirty(): boolean {
    return this.people !== null && peopleKey(this.people) !== this.savedPeople;
  }

  get dirty(): boolean {
    return this.setupDirty || this.peopleDirty;
  }

  guardLeave(go: () => void): boolean {
    if (!this.dirty) return false;
    this.leaving = go;
    return true;
  }

  private leave(): void {
    const go = this.leaving;
    this.leaving = null;
    if (!go) return;
    // The user chose to drop the changes: they count as saved, so nothing asks again.
    if (this.setup) this.savedSetup = setupKey(this.setup);
    if (this.people) this.savedPeople = peopleKey(this.people);
    go();
  }

  private async load(): Promise<void> {
    const [setup, exercises, people, speakers, playlists] = await Promise.allSettled([
      this.api.setup(),
      this.api.allExercises(),
      this.api.people(),
      this.api.speakers(),
      this.api.playlists(),
    ]);
    if (setup.status === "fulfilled") {
      this.setup = setup.value;
      this.savedSetup = setupKey(setup.value);
    } else {
      this.loadError = failure(setup.reason);
    }
    if (exercises.status === "fulfilled") this.exercises = exercises.value;
    else this.exercisesError = failure(exercises.reason);
    if (people.status === "fulfilled") {
      this.people = people.value.people.map(({ name, person_entity_id }) => ({ name, person_entity_id }));
      this.savedPeople = peopleKey(this.people);
      this.haPersons = people.value.ha_persons;
      this.peopleNote = people.value.ha_error;
    } else {
      this.peopleNote = failure(people.reason);
    }
    this.speakers =
      speakers.status === "fulfilled"
        ? { items: speakers.value, error: null }
        : { items: [], error: failure(speakers.reason) };
    this.playlists =
      playlists.status === "fulfilled"
        ? { items: playlists.value, error: null }
        : { items: [], error: failure(playlists.reason) };
    this.loaded = true;
  }

  /** Change the setup being edited; a new change hides "Saved". */
  private edit(change: Partial<Setup>): void {
    if (!this.setup) return;
    this.setup = { ...this.setup, ...change };
    this.saved = false;
  }

  /** Apply the multi-select's choice: each option chosen or taken off toggles the values it stands for. */
  private choose(all: Choice[], selected: string[]): void {
    if (!this.setup) return;
    const before = new Set(this.chosen(all));
    const after = new Set(selected);
    for (const choice of all) {
      if (before.has(choice.label) !== after.has(choice.label)) this.toggle(choice);
    }
  }

  /** The options chosen now: those with any of their values in the setup. */
  private chosen(all: Choice[]): string[] {
    const equipment = new Set(this.setup?.equipment ?? []);
    return all.filter((choice) => choice.values.some((value) => equipment.has(value))).map((choice) => choice.label);
  }

  private toggle(choice: Choice): void {
    if (!this.setup) return;
    const equipment = new Set(this.setup.equipment);
    const on = choice.values.some((value) => equipment.has(value));
    for (const value of choice.values) {
      if (on) equipment.delete(value);
      else equipment.add(value);
    }
    this.edit({ equipment: [...equipment] });
  }

  private addFavourite(uri: string): void {
    const playlist = this.playlists.items.find((candidate) => candidate.uri === uri);
    if (!this.setup || !playlist) return;
    this.edit({ favourite_playlists: [...this.setup.favourite_playlists, { uri: playlist.uri, name: playlist.name }] });
  }

  private removeFavourite(favourite: FavouritePlaylist): void {
    if (!this.setup) return;
    this.edit({ favourite_playlists: this.setup.favourite_playlists.filter((kept) => kept !== favourite) });
  }

  private async save(): Promise<void> {
    if (!this.setup || this.saving) return;
    this.saving = true;
    this.errors = [];
    this.saved = false;
    const sent = this.setup;
    const { equipment, favourite_playlists, default_speaker } = sent;
    try {
      const stored = await this.api.putSetup({
        equipment: withBodyWeight(equipment),
        favourite_playlists,
        default_speaker,
      });
      this.savedSetup = setupKey(stored);
      // A change made while saving stays, unsaved.
      if (this.setup === sent) {
        this.setup = stored;
        this.saved = true;
      }
    } catch (error) {
      this.errors = itemsOf(error);
    } finally {
      this.saving = false;
    }
  }

  /** Change the people being edited; a new change hides "People saved". */
  private editPeople(people: NewPerson[]): void {
    if (!this.people) return;
    this.people = people;
    this.peopleSaved = false;
  }

  private addPerson(entityId: string): void {
    const person = this.haPersons?.find((candidate) => candidate.entity_id === entityId);
    if (!person) return;
    if (!this.people) return;
    this.editPeople([...this.people, { name: person.friendly_name, person_entity_id: person.entity_id }]);
  }

  private move(index: number, by: -1 | 1): void {
    if (!this.people) return;
    const people = [...this.people];
    const [person] = people.splice(index, 1);
    people.splice(index + by, 0, person);
    this.editPeople(people);
  }

  private removePerson(index: number): void {
    this.editPeople((this.people ?? []).filter((_, kept) => kept !== index));
    this.removing = null;
  }

  private async savePeople(): Promise<void> {
    if (!this.people || this.peopleSaving) return;
    this.peopleSaving = true;
    this.peopleErrors = [];
    this.peopleSaved = false;
    try {
      const sent = this.people;
      const stored = (await this.api.putPeople(sent)).map(({ name, person_entity_id }) => ({ name, person_entity_id }));
      this.savedPeople = peopleKey(stored);
      // A change made while saving stays, unsaved.
      if (this.people === sent) {
        this.people = stored;
        this.peopleSaved = true;
      }
    } catch (error) {
      this.peopleErrors = itemsOf(error);
    } finally {
      this.peopleSaving = false;
    }
  }

  private alerts(place: Place) {
    return this.errors
      .filter((item) => placeOf(item) === place)
      .map((item) => html`<p class="error" role="alert">${item.message}</p>`);
  }

  /** The people refusals whose field passes `at`: one without a field shows above the list, the others below it. */
  private peopleAlerts(at: (field: string | null) => boolean) {
    return this.peopleErrors
      .filter((item) => at(item.field))
      .map((item) => html`<p class="error" role="alert">${item.message}</p>`);
  }

  protected override render() {
    if (!this.loaded) {
      return html`<h1>${t("setup.title")}</h1>
        <p>${t("setup.loading")}</p>`;
    }
    const setup = this.setup;
    return html`
      <div class="setup-head">
        <h1>${t("setup.title")}</h1>
        ${this.setupDirty ? notSaved() : nothing}
        ${this.saved && !this.setupDirty
          ? html`<span class="secondary" role="status">${t("setup.saved")}</span>`
          : nothing}
        ${setup
          ? html`<button type="button" class="button primary" ?disabled=${this.saving} @click=${() => this.save()}>
              ${icon(mdiContentSave)}<span>${t("setup.save")}</span>
            </button>`
          : nothing}
      </div>
      ${this.loadError ? html`<p class="error" role="alert">${this.loadError}</p>` : nothing} ${this.alerts("page")}
      ${setup ? this.renderEquipment(setup) : nothing}
      <div class="setup-columns">
        ${this.renderPeople()}
        ${setup
          ? html`<div class="card setup-music">${this.renderSpeaker(setup)} ${this.renderPlaylists(setup)}</div>`
          : nothing}
      </div>
      ${this.people && this.removing !== null ? this.renderRemove(this.people[this.removing]) : nothing}
      ${this.leaving
        ? html`<hf-confirm-dialog
            .heading=${t("editor.leave_title")}
            .message=${t("setup.leave_message")}
            .confirmLabel=${t("editor.leave_confirm")}
            .icon=${mdiAlertOutline}
            .confirmIcon=${mdiExitRun}
            @confirm=${() => this.leave()}
            @cancel=${() => (this.leaving = null)}
          ></hf-confirm-dialog>`
        : nothing}
    `;
  }

  private renderEquipment(setup: Setup) {
    const all = choices(this.exercises, setup.equipment);
    return html`<section class="card" aria-labelledby="setup-equipment">
      <h2 id="setup-equipment">${icon(mdiDumbbell)}<span>${t("setup.equipment")}</span></h2>
      <p class="secondary">${t("setup.equipment_hint")}</p>
      ${this.exercisesError ? html`<p class="error" role="alert">${this.exercisesError}</p>` : nothing}
      <hf-multi-select
        .label=${t("setup.equipment_have")}
        .placeholder=${t("setup.add_equipment")}
        .options=${[
          { value: BODY_WEIGHT, label: BODY_WEIGHT },
          ...all.map((choice) => ({
            value: choice.label,
            label: GROUPS[choice.label] ? t(`setup.${choice.label}`) : choice.label,
          })),
        ]}
        .selected=${[BODY_WEIGHT, ...this.chosen(all)]}
        .fixed=${[BODY_WEIGHT]}
        @change=${(event: CustomEvent<{ selected: string[] }>) => this.choose(all, event.detail.selected)}
      ></hf-multi-select>
      ${this.alerts("equipment")}
    </section>`;
  }

  private renderPeople() {
    return html`<section class="card" aria-labelledby="setup-people">
      <h2 id="setup-people">${icon(mdiAccountGroup)}<span>${t("setup.people")}</span></h2>
      <p class="secondary">${t("setup.people_hint")}</p>
      ${this.peopleNote ? html`<p class="error">${this.peopleNote}</p>` : nothing}
      ${this.people ? this.renderPeopleForm(this.people) : nothing}
    </section>`;
  }

  private renderPeopleForm(people: NewPerson[]) {
    const listed = new Set(people.map((person) => person.person_entity_id));
    const addable = (this.haPersons ?? []).filter((person) => !listed.has(person.entity_id));
    const last = people.length - 1;
    return html`
      ${this.peopleAlerts((field) => field === null)}
      <ul class="setup-people" aria-label=${t("setup.people")}>
        ${people.map(
          (person, index) => html`<li>
            <span class="dot" style="background: ${PERSON_COLORS[index] ?? "var(--hf-primary)"}"></span>
            <span class="setup-name">${person.name}</span>
            <button
              type="button"
              class="icon-button"
              aria-label=${t("setup.move_up", { name: person.name })}
              ?disabled=${index === 0}
              @click=${() => this.move(index, -1)}
            >
              ${icon(mdiArrowUp)}
            </button>
            <button
              type="button"
              class="icon-button"
              aria-label=${t("setup.move_down", { name: person.name })}
              ?disabled=${index === last}
              @click=${() => this.move(index, 1)}
            >
              ${icon(mdiArrowDown)}
            </button>
            <button
              type="button"
              class="icon-button"
              aria-label=${t("setup.remove", { name: person.name })}
              @click=${() => (this.removing = index)}
            >
              ${icon(mdiClose)}
            </button>
          </li>`,
        )}
      </ul>
      ${people.length ? nothing : html`<p class="secondary">${t("setup.no_people")}</p>`}
      ${this.haPersons
        ? addable.length
          ? html`<label class="setup-add">
              <span>${t("setup.add_person")}</span>
              <select
                data-value=""
                @change=${(event: Event) => this.addPerson((event.target as HTMLSelectElement).value)}
              >
                <option value="">${t("setup.choose_person")}</option>
                ${addable.map((person) => html`<option value=${person.entity_id}>${person.friendly_name}</option>`)}
              </select>
            </label>`
          : html`<p class="secondary">${t("setup.no_persons")}</p>`
        : nothing}
      ${this.peopleAlerts((field) => field !== null)}
      <div class="setup-actions">
        ${this.peopleDirty ? notSaved() : nothing}
        ${this.peopleSaved && !this.peopleDirty
          ? html`<span class="secondary" role="status">${t("setup.people_saved")}</span>`
          : nothing}
        <button type="button" class="button primary" ?disabled=${this.peopleSaving} @click=${() => this.savePeople()}>
          ${icon(mdiContentSave)}<span>${t("setup.save_people")}</span>
        </button>
      </div>
    `;
  }

  private renderSpeaker(setup: Setup) {
    const speaker = setup.default_speaker ?? "";
    const listed = this.speakers.items.some((candidate) => candidate.entity_id === speaker);
    return html`<section aria-labelledby="setup-speaker">
      <h2 id="setup-speaker">${icon(mdiSpeaker)}<span>${t("setup.speaker")}</span></h2>
      <p class="secondary">${t("setup.speaker_hint")}</p>
      <select
        aria-labelledby="setup-speaker"
        data-value=${speaker}
        @change=${(event: Event) => this.edit({ default_speaker: (event.target as HTMLSelectElement).value || null })}
      >
        <option value="">${t("setup.no_speaker")}</option>
        ${this.speakers.items.map((item) => html`<option value=${item.entity_id}>${item.name}</option>`)}
        ${speaker && !listed ? html`<option value=${speaker}>${speaker}</option>` : nothing}
      </select>
      ${this.speakers.error || !this.speakers.items.length
        ? html`<p class="secondary">${this.speakers.error ?? t("setup.no_speakers")}</p>`
        : nothing}
      ${this.alerts("speaker")}
    </section>`;
  }

  private renderPlaylists(setup: Setup) {
    const favourites = setup.favourite_playlists;
    const chosen = new Set(favourites.map((favourite) => favourite.uri));
    const addable = this.playlists.items.filter((playlist) => !chosen.has(playlist.uri));
    return html`<section aria-labelledby="setup-playlists">
      <h2 id="setup-playlists">${icon(mdiPlaylistStar)}<span>${t("setup.playlists")}</span></h2>
      <p class="secondary">${t("setup.playlists_hint")}</p>
      ${favourites.length
        ? html`<ul class="setup-favourites" aria-label=${t("setup.playlists")}>
            ${favourites.map(
              (favourite) => html`<li>
                <span class="star">${icon(mdiStar)}</span>
                <span class="setup-name">${favourite.name}</span>
                <button
                  type="button"
                  class="icon-button"
                  aria-label=${t("setup.remove", { name: favourite.name })}
                  @click=${() => this.removeFavourite(favourite)}
                >
                  ${icon(mdiClose)}
                </button>
              </li>`,
            )}
          </ul>`
        : html`<p class="secondary">${t("setup.no_favourites")}</p>`}
      ${addable.length
        ? html`<label class="setup-add">
            <span>${t("setup.add_playlist")}</span>
            <select
              data-value=""
              @change=${(event: Event) => this.addFavourite((event.target as HTMLSelectElement).value)}
            >
              <option value="">${t("setup.choose_playlist")}</option>
              ${addable.map((playlist) => html`<option value=${playlist.uri}>${playlist.name}</option>`)}
            </select>
          </label>`
        : nothing}
      ${this.playlists.error || !this.playlists.items.length
        ? html`<p class="secondary">${this.playlists.error ?? t("setup.no_playlists")}</p>`
        : nothing}
      ${this.alerts("playlists")}
    </section>`;
  }

  private renderRemove(person: NewPerson) {
    return html`<hf-confirm-dialog
      .heading=${t("setup.remove_title", { name: person.name })}
      .message=${t("setup.remove_message")}
      .points=${[t("setup.remove_stats"), t("setup.remove_sensors"), t("setup.remove_new")]}
      .confirmLabel=${t("setup.remove_confirm")}
      .confirmIcon=${mdiClose}
      @confirm=${() => this.removing !== null && this.removePerson(this.removing)}
      @cancel=${() => (this.removing = null)}
    ></hf-confirm-dialog>`;
  }
}

/** The "Not saved" marker by a Save button, as in the program editor. */
function notSaved() {
  return html`<span class="not-saved"><span class="dot" aria-hidden="true"></span>${t("editor.not_saved")}</span>`;
}

/** The page's styles, for the shell's shadow root (it renders in light DOM). */
export const setupPageStyles = css`
  .setup-head {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 20px;
  }
  .setup-head h1 {
    flex: 1;
    margin: 0;
  }
  .card h2 {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .card h2 .icon {
    width: 22px;
    height: 22px;
    color: var(--hf-primary);
  }
  .secondary {
    color: var(--hf-text-secondary);
  }
  .card hf-multi-select {
    max-width: 480px;
    margin: 12px 0 4px;
  }
  .setup-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    align-items: start;
  }
  .setup-music section + section {
    margin-top: 20px;
  }
  .setup-people,
  .setup-favourites {
    list-style: none;
    margin: 12px 0;
    padding: 0;
  }
  .setup-people li {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    padding: 8px 12px;
    border: 1px solid var(--hf-border);
    border-radius: 8px;
  }
  .setup-favourites li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid var(--hf-border);
  }
  .setup-name {
    flex: 1;
  }
  .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }
  .star .icon {
    width: 20px;
    height: 20px;
    color: #fbc02d;
  }
  .setup-add {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 8px 0;
    color: var(--hf-text-secondary);
  }
  .card select {
    padding: 8px;
    border: 1px solid var(--hf-border);
    border-radius: 6px;
    background: var(--hf-card);
    font: inherit;
  }
  .setup-head .not-saved,
  .setup-actions .not-saved {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--hf-warning-text);
  }
  .setup-head .not-saved .dot,
  .setup-actions .not-saved .dot {
    width: 8px;
    height: 8px;
    background: var(--hf-warning);
  }
  .setup-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 16px;
    margin-top: 12px;
  }
`;

if (!customElements.get("hf-setup-page")) customElements.define("hf-setup-page", SetupPage);

declare global {
  interface HTMLElementTagNameMap {
    "hf-setup-page": SetupPage;
  }
}
