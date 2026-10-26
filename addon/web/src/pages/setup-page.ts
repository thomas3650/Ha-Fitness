import {
  mdiAccountGroup,
  mdiArrowDown,
  mdiArrowUp,
  mdiCheck,
  mdiClose,
  mdiContentSave,
  mdiDumbbell,
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
import { facetValues } from "../components/exercise-picker";
import { applySelectValues } from "../components/select-value";
import { t } from "../i18n";
import { icon } from "../icons";

/** Body weight needs no equipment: always on, never a choice (website spec §2.4.1). */
const BODY_WEIGHT = "body weight";

/**
 * Equipment the household chooses as one: the dataset names a band both ways, and the household filter compares
 * exactly, so the "band" chip stores both (website spec §2.4.1).
 */
const GROUPS: Record<string, string[]> = { band: ["band", "resistance band"] };

/** The people's colours, by people order, as the cards have them (design §3.4). */
const PERSON_COLORS = ["#B18CFF", "#3DD6C6"];

/** One equipment chip: its label and the values it stands for. */
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

function failure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  throw error;
}

function placeOf(item: ErrorItem): Place {
  const field = item.field ?? "";
  if (field === "equipment" || field.startsWith("equipment.")) return "equipment";
  if (field.startsWith("favourite_playlists")) return "playlists";
  if (field === "default_speaker") return "speaker";
  return "page";
}

/**
 * The equipment chips: body weight first, then every equipment of the exercises and of the stored setup, sorted,
 * with a group (band and resistance band) as one chip. A group stands only for the values the exercises or the
 * setup have, so a chip never sends equipment the add-on doesn't know.
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
 * nothing chosen is lost.
 */
export class SetupPage extends LitElement {
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
  /** The people as edited, in order. */
  declare people: NewPerson[];
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
    this.people = [];
    this.haPersons = null;
    this.peopleNote = null;
    this.errors = [];
    this.saving = false;
    this.saved = false;
    this.peopleErrors = [];
    this.peopleSaving = false;
    this.peopleSaved = false;
    this.removing = null;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  protected override updated(): void {
    applySelectValues(this);
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this.load();
  }

  private async load(): Promise<void> {
    const [setup, exercises, people, speakers, playlists] = await Promise.allSettled([
      this.api.setup(),
      this.api.allExercises(),
      this.api.people(),
      this.api.speakers(),
      this.api.playlists(),
    ]);
    if (setup.status === "fulfilled") this.setup = setup.value;
    else this.loadError = failure(setup.reason);
    if (exercises.status === "fulfilled") this.exercises = exercises.value;
    else this.exercisesError = failure(exercises.reason);
    if (people.status === "fulfilled") {
      this.people = people.value.people.map(({ name, person_entity_id }) => ({ name, person_entity_id }));
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
      // Body weight is always in the household; the add-on adds it as well.
      const all = equipment.includes(BODY_WEIGHT) ? equipment : [BODY_WEIGHT, ...equipment];
      const stored = await this.api.putSetup({ equipment: all, favourite_playlists, default_speaker });
      // A change made while saving stays, unsaved.
      if (this.setup === sent) {
        this.setup = stored;
        this.saved = true;
      }
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      this.errors = error.items;
    } finally {
      this.saving = false;
    }
  }

  /** Change the people being edited; a new change hides "People saved". */
  private editPeople(people: NewPerson[]): void {
    this.people = people;
    this.peopleSaved = false;
  }

  private addPerson(entityId: string): void {
    const person = this.haPersons?.find((candidate) => candidate.entity_id === entityId);
    if (!person) return;
    this.editPeople([...this.people, { name: person.friendly_name, person_entity_id: person.entity_id }]);
  }

  private move(index: number, by: -1 | 1): void {
    const people = [...this.people];
    const [person] = people.splice(index, 1);
    people.splice(index + by, 0, person);
    this.editPeople(people);
  }

  private removePerson(index: number): void {
    this.editPeople(this.people.filter((_, kept) => kept !== index));
    this.removing = null;
  }

  private async savePeople(): Promise<void> {
    if (this.peopleSaving) return;
    this.peopleSaving = true;
    this.peopleErrors = [];
    this.peopleSaved = false;
    try {
      const sent = this.people;
      const stored = await this.api.putPeople(sent);
      // A change made while saving stays, unsaved.
      if (this.people === sent) {
        this.people = stored.map(({ name, person_entity_id }) => ({ name, person_entity_id }));
        this.peopleSaved = true;
      }
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      this.peopleErrors = error.items;
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
        ${this.saved ? html`<span class="secondary" role="status">${t("setup.saved")}</span>` : nothing}
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
      ${this.removing !== null ? this.renderRemove(this.people[this.removing]) : nothing}
    `;
  }

  private renderEquipment(setup: Setup) {
    const equipment = new Set(setup.equipment);
    return html`<section class="card" aria-labelledby="setup-equipment">
      <h2 id="setup-equipment">${icon(mdiDumbbell)}<span>${t("setup.equipment")}</span></h2>
      <p class="secondary">${t("setup.equipment_hint")}</p>
      ${this.exercisesError ? html`<p class="error" role="alert">${this.exercisesError}</p>` : nothing}
      <div class="setup-chips">
        <button type="button" class="chip" aria-pressed="true" disabled>
          ${icon(mdiCheck)}<span>${BODY_WEIGHT}</span>
        </button>
        ${choices(this.exercises, setup.equipment).map((choice) => {
          const on = choice.values.some((value) => equipment.has(value));
          return html`<button
            type="button"
            class="chip"
            aria-pressed=${on ? "true" : "false"}
            @click=${() => this.toggle(choice)}
          >
            ${on ? icon(mdiCheck) : nothing}
            <span>${GROUPS[choice.label] ? t(`setup.${choice.label}`) : choice.label}</span>
          </button>`;
        })}
      </div>
      ${this.alerts("equipment")}
    </section>`;
  }

  private renderPeople() {
    const listed = new Set(this.people.map((person) => person.person_entity_id));
    const addable = (this.haPersons ?? []).filter((person) => !listed.has(person.entity_id));
    const last = this.people.length - 1;
    return html`<section class="card" aria-labelledby="setup-people">
      <h2 id="setup-people">${icon(mdiAccountGroup)}<span>${t("setup.people")}</span></h2>
      <p class="secondary">${t("setup.people_hint")}</p>
      ${this.peopleNote ? html`<p class="error">${this.peopleNote}</p>` : nothing}
      ${this.peopleAlerts((field) => field === null)}
      <ul class="setup-people" aria-label=${t("setup.people")}>
        ${this.people.map(
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
      ${this.people.length ? nothing : html`<p class="secondary">${t("setup.no_people")}</p>`}
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
        ${this.peopleSaved ? html`<span class="secondary" role="status">${t("setup.people_saved")}</span>` : nothing}
        <button type="button" class="button primary" ?disabled=${this.peopleSaving} @click=${() => this.savePeople()}>
          ${icon(mdiContentSave)}<span>${t("setup.save_people")}</span>
        </button>
      </div>
    </section>`;
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
  .setup-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0 4px;
  }
  .setup-chips .chip .icon {
    width: 16px;
    height: 16px;
    color: inherit;
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
