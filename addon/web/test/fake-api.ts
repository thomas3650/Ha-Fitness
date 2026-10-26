/**
 * A fake of the add-on's REST API, as a `fetch`: it keeps programs, exercises, the setup, people, speakers,
 * playlists and the defaults in memory, records every request, and answers a set status and body per route.
 *
 * It holds no program rules: a write is stored as it is sent. A test that needs a refusal sets it with `answer`.
 */
import type {
  ExerciseSummary,
  Health,
  LibraryStatus,
  PeopleView,
  PlaylistOut,
  ProgramDefaults,
  ProgramDocument,
  ProgramOut,
  Setup,
  SpeakerOut,
} from "../src/api";

/** One request the site sent: the method, the path with its query, and the parsed JSON body (or null). */
export interface Recorded {
  method: string;
  path: string;
  body: unknown;
}

interface Answer {
  status: number;
  body?: unknown;
}

export interface FakeState {
  health: Health;
  library: LibraryStatus;
  people: PeopleView;
  programs: ProgramOut[];
  defaults: ProgramDefaults;
  setup: Setup;
  exercises: ExerciseSummary[];
  speakers: SpeakerOut[];
  playlists: PlaylistOut[];
}

const NOW = "2026-10-26T10:00:00Z";

/** A stored program around a document; the station names come from the fake's exercises. */
export function program(id: number, document: Partial<ProgramDocument> = {}, extra: Partial<ProgramOut> = {}): ProgramOut {
  const doc: ProgramDocument = {
    name: `Program ${id}`,
    active: true,
    weekdays: ["mon"],
    stations: [{ exercise: "0001" }],
    rounds: 5,
    work_seconds: 45,
    switch_seconds: 15,
    round_rest_seconds: 60,
    countdown_seconds: 5,
    music: null,
    ...document,
  };
  return {
    id,
    program: doc,
    station_names: doc.stations.map((station) => station.exercise),
    equipment: [],
    total_seconds: 600,
    created_at: NOW,
    updated_at: NOW,
    created_by: "you",
    ...extra,
  };
}

export function defaultState(): FakeState {
  return {
    health: { status: "ok", version: "2.0.0", api_version: 1 },
    library: { exercises: { library: 1324, custom: 2 }, media: { state: "done", present: 1324, total: 1324 } },
    people: { people: [], ha_persons: [], ha_error: null },
    programs: [],
    defaults: { rounds: 5, work_seconds: 45, switch_seconds: 15, round_rest_seconds: 60, countdown_seconds: 5 },
    setup: { equipment: ["body weight"], favourite_playlists: [], default_speaker: null },
    exercises: [],
    speakers: [],
    playlists: [],
  };
}

function json(status: number, body: unknown): Response {
  if (status === 204) return new Response(null, { status });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function fakeApi(initial: Partial<FakeState> = {}) {
  const state: FakeState = { ...defaultState(), ...initial };
  const requests: Recorded[] = [];
  const answers = new Map<string, Answer>();
  let nextId = Math.max(0, ...state.programs.map((stored) => stored.id)) + 1;

  function stored(id: number): ProgramOut | undefined {
    return state.programs.find((candidate) => candidate.id === id);
  }

  function withNames(doc: ProgramDocument): string[] {
    return doc.stations.map(
      (station) => state.exercises.find((exercise) => exercise.id === station.exercise)?.name ?? station.exercise,
    );
  }

  const notFound = { status: 404, body: { detail: "Not Found" } };

  /** The default answer for a route, from the state; a write changes the state. */
  function route(method: string, path: string, body: unknown): Answer {
    const [route, query = ""] = path.split("?");
    const params = new URLSearchParams(query);
    const programMatch = route.match(/^api\/v1\/programs\/(\d+)(\/active)?$/);
    const key = `${method} ${route}`;
    switch (key) {
      case "GET api/v1/health":
        return { status: 200, body: state.health };
      case "GET api/v1/library":
        return { status: 200, body: state.library };
      case "GET api/v1/people":
        return { status: 200, body: state.people };
      case "PUT api/v1/people": {
        const people = (body as { people: { name: string; person_entity_id: string }[] }).people;
        state.people = { ...state.people, people: people.map((person, index) => ({ id: index + 1, ...person })) };
        return { status: 200, body: state.people.people };
      }
      case "GET api/v1/programs":
        return { status: 200, body: state.programs };
      case "POST api/v1/programs": {
        const doc = body as ProgramDocument;
        const created = program(nextId++, doc, { station_names: withNames(doc), created_by: "you" });
        state.programs.push(created);
        return { status: 201, body: created };
      }
      case "GET api/v1/programs/defaults":
        return { status: 200, body: state.defaults };
      case "GET api/v1/setup":
        return { status: 200, body: state.setup };
      case "PUT api/v1/setup":
        state.setup = body as Setup;
        return { status: 200, body: state.setup };
      case "GET api/v1/exercises/all":
        return { status: 200, body: state.exercises };
      case "GET api/v1/exercises": {
        const q = (params.get("q") ?? "").toLowerCase();
        const results = state.exercises.filter((exercise) => exercise.name.toLowerCase().includes(q));
        return { status: 200, body: { results, facets: null } };
      }
      case "GET api/v1/music/speakers":
        return { status: 200, body: state.speakers };
      case "GET api/v1/music/playlists":
        return { status: 200, body: state.playlists };
    }
    if (programMatch) {
      const id = Number(programMatch[1]);
      const current = stored(id);
      if (!current) return notFound;
      const index = state.programs.indexOf(current);
      const updatedAt = new Date(Date.parse(current.updated_at) + 1000).toISOString();
      if (programMatch[2]) {
        if (method !== "PUT") return notFound;
        const active = (body as { active: boolean }).active;
        const changed = { ...current, program: { ...current.program, active }, updated_at: updatedAt };
        state.programs[index] = changed;
        return { status: 200, body: changed };
      }
      if (method === "GET") return { status: 200, body: current };
      if (method === "PUT") {
        const doc = body as ProgramDocument;
        const changed = { ...current, program: doc, station_names: withNames(doc), updated_at: updatedAt };
        state.programs[index] = changed;
        return { status: 200, body: changed };
      }
      if (method === "DELETE") {
        state.programs.splice(index, 1);
        return { status: 204 };
      }
    }
    return notFound;
  }

  async function fakeFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    const path = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : null;
    requests.push({ method, path, body });
    const set = answers.get(`${method} ${path.split("?")[0]}`);
    if (set) return json(set.status, set.body);
    const answer = route(method, path, body);
    return json(answer.status, answer.body);
  }

  return {
    state,
    requests,
    fetch: fakeFetch,
    /** Answer every `method path` (the path without its query) with this status and body from now on. */
    answer(method: string, path: string, status: number, body?: unknown) {
      answers.set(`${method} ${path}`, { status, body });
    },
    /** Answer a route from the state again. */
    restore(method: string, path: string) {
      answers.delete(`${method} ${path}`);
    },
  };
}

export type FakeApi = ReturnType<typeof fakeApi>;
