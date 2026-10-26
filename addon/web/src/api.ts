/**
 * The add-on's REST API, typed as `addon/server/src/ha_fitness_server/schemas.py` has it. Every path is relative
 * (`api/v1/...`), so the site works under Ingress's changing prefix.
 */
import { t } from "./i18n";

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface Health {
  status: string;
  version: string;
  api_version: number;
}

export interface LibraryStatus {
  exercises: { library: number; custom: number };
  media: { state: "idle" | "downloading" | "done" | "failed"; present: number; total: number };
}

export interface Person {
  id: number;
  name: string;
  person_entity_id: string;
}

export interface HaPerson {
  entity_id: string;
  friendly_name: string;
}

export interface PeopleView {
  people: Person[];
  ha_persons: HaPerson[] | null;
  ha_error: string | null;
}

export interface NewPerson {
  name: string;
  person_entity_id: string;
}

export interface Music {
  playlist: string;
  playlist_name?: string | null;
  speaker: string;
  volume?: number | null;
  shuffle?: boolean;
}

export interface ProgramDocument {
  name: string;
  active?: boolean;
  weekdays: Weekday[];
  stations: { exercise: string }[];
  rounds?: number;
  work_seconds?: number;
  switch_seconds?: number;
  round_rest_seconds?: number;
  countdown_seconds?: number;
  music?: Music | null;
}

export interface ProgramOut {
  id: number;
  program: ProgramDocument;
  station_names: string[];
  equipment: string[];
  total_seconds: number;
  created_at: string;
  updated_at: string;
  created_by: "claude" | "you" | null;
}

export interface ProgramDefaults {
  rounds: number;
  work_seconds: number;
  switch_seconds: number;
  round_rest_seconds: number;
  countdown_seconds: number;
}

export interface FavouritePlaylist {
  uri: string;
  name: string;
}

export interface Setup {
  equipment: string[];
  favourite_playlists: FavouritePlaylist[];
  default_speaker: string | null;
}

export interface ExerciseSummary {
  id: string;
  name: string;
  equipment: string | null;
  body_part: string | null;
  target: string | null;
  custom: boolean;
}

export interface Exercise extends ExerciseSummary {
  steps: string[];
  secondary_muscles: string[];
  attribution: string | null;
}

export interface ExerciseSearch {
  results: ExerciseSummary[];
  facets: { equipment: string[]; body_part: string[]; target: string[] } | null;
}

export interface SearchQuery {
  q?: string;
  equipment?: string;
  body_part?: string;
  limit?: number;
  household?: boolean;
}

export interface SpeakerOut {
  entity_id: string;
  name: string;
  available: boolean;
}

export interface PlaylistOut {
  name: string;
  uri: string;
}

/** One thing a refusal is about: the field it is at (null for none), its code and the add-on's message. */
export interface ErrorItem {
  field: string | null;
  code: string;
  message: string;
}

interface ValidationItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isValidationList(value: unknown): value is ValidationItem[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => isRecord(item) && Array.isArray(item.loc) && typeof item.msg === "string")
  );
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** A 422 item's field: its `loc` without the leading `body`, joined with `.`; null when it is the body itself. */
function fieldOf(loc: (string | number)[]): string | null {
  const path = loc[0] === "body" ? loc.slice(1) : loc;
  return path.length ? path.join(".") : null;
}

/**
 * A refusal from the add-on. It reads the three shapes the API answers with: D65's `{detail, code, field}`,
 * FastAPI's 422 list `{detail: [{loc, msg, type}]}`, and the session routes' `{detail: {code, message}}`.
 * A form shows every item at its field, and an item without a field above the form.
 */
export class ApiError extends Error {
  status: number;
  code: string | null;
  field: string | null;
  detail: unknown;
  items: ErrorItem[];

  constructor(status: number, body: unknown) {
    const detail = isRecord(body) ? body.detail : undefined;
    let items: ErrorItem[];
    if (isValidationList(detail)) {
      items = detail.map((item) => ({ field: fieldOf(item.loc), code: String(item.type ?? ""), message: item.msg }));
    } else {
      const message =
        (typeof detail === "string" && detail) ||
        (isRecord(detail) && typeof detail.message === "string" && detail.message) ||
        t("error.unknown", { status });
      // The session routes put their code in the detail.
      const code = (isRecord(body) && stringOrNull(body.code)) || (isRecord(detail) && stringOrNull(detail.code)) || "";
      const field = isRecord(body) ? stringOrNull(body.field) : null;
      items = [{ field, code, message }];
    }
    super(items[0].message);
    this.name = "ApiError";
    this.status = status;
    this.code = items[0].code || null;
    this.field = items[0].field;
    this.detail = detail;
    this.items = items;
  }
}

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** The query string for a request, empty when there is nothing to send. */
function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * The REST client. `fetchFn` defaults to the page's `fetch`, looked up at each call, and is only ever called as a
 * plain function (a method call on another object would throw "Illegal invocation" in a browser).
 */
export function createApi(fetchFn: Fetch = (input, init) => fetch(input, init)) {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { Accept: "application/json", "Content-Type": "application/json" };
    }
    const response = await fetchFn(`api/v1/${path}`, init);
    if (response.status === 204) return undefined as T;
    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    if (!response.ok) throw new ApiError(response.status, parsed);
    return parsed as T;
  }

  return {
    health: () => call<Health>("GET", "health"),
    library: () => call<LibraryStatus>("GET", "library"),
    people: () => call<PeopleView>("GET", "people"),
    putPeople: (people: NewPerson[]) => call<Person[]>("PUT", "people", { people }),
    programs: () => call<ProgramOut[]>("GET", "programs"),
    program: (id: number) => call<ProgramOut>("GET", `programs/${id}`),
    programDefaults: () => call<ProgramDefaults>("GET", "programs/defaults"),
    createProgram: (program: ProgramDocument) => call<ProgramOut>("POST", "programs", program),
    /** Replace a program; with `ifUpdatedAt` only while it is still the stored `updated_at` (409 otherwise). */
    replaceProgram: (id: number, program: ProgramDocument, ifUpdatedAt?: string) =>
      call<ProgramOut>("PUT", `programs/${id}${query({ if_updated_at: ifUpdatedAt })}`, program),
    setActive: (id: number, active: boolean) => call<ProgramOut>("PUT", `programs/${id}/active`, { active }),
    deleteProgram: (id: number) => call<void>("DELETE", `programs/${id}`),
    setup: () => call<Setup>("GET", "setup"),
    putSetup: (setup: Setup) => call<Setup>("PUT", "setup", setup),
    allExercises: () => call<ExerciseSummary[]>("GET", "exercises/all"),
    searchExercises: (search: SearchQuery) =>
      call<ExerciseSearch>(
        "GET",
        `exercises${query({ ...search, household: search.household ? true : undefined })}`,
      ),
    exercise: (id: string) => call<Exercise>("GET", `exercises/${encodeURIComponent(id)}`),
    speakers: () => call<SpeakerOut[]>("GET", "music/speakers"),
    playlists: (search?: string) => call<PlaylistOut[]>("GET", `music/playlists${query({ search })}`),
  };
}

export type Api = ReturnType<typeof createApi>;

/** An exercise's thumbnail and GIF, relative like every other URL. */
export function thumbnailUrl(id: string): string {
  return `api/v1/exercises/${encodeURIComponent(id)}/thumbnail`;
}

export function gifUrl(id: string): string {
  return `api/v1/exercises/${encodeURIComponent(id)}/gif`;
}
