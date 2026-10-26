import { expect, test } from "vitest";

import { ApiError, createApi, gifUrl, thumbnailUrl } from "../src/api";
import en from "../src/i18n/en.json";
import { fakeApi, program } from "./fake-api";

async function refusal(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("the call was not refused");
}

test("every call goes to a relative path, so it works under Ingress's prefix", async () => {
  const fake = fakeApi({ programs: [program(5)] });
  const api = createApi(fake.fetch);

  await api.health();
  await api.library();
  await api.people();
  await api.programs();
  await api.program(5);
  await api.programDefaults();
  await api.setup();
  await api.allExercises();
  await api.searchExercises({ q: "push up", household: true });
  await api.speakers();
  await api.playlists();
  await api.replaceProgram(5, program(5).program, "2026-10-26T10:00:00Z");
  await api.setActive(5, false);
  await api.deleteProgram(5);

  expect(fake.requests.map((request) => `${request.method} ${request.path}`)).toEqual([
    "GET api/v1/health",
    "GET api/v1/library",
    "GET api/v1/people",
    "GET api/v1/programs",
    "GET api/v1/programs/5",
    "GET api/v1/programs/defaults",
    "GET api/v1/setup",
    "GET api/v1/exercises/all",
    "GET api/v1/exercises?q=push+up&household=true",
    "GET api/v1/music/speakers",
    "GET api/v1/music/playlists",
    "PUT api/v1/programs/5?if_updated_at=2026-10-26T10%3A00%3A00Z",
    "PUT api/v1/programs/5/active",
    "DELETE api/v1/programs/5",
  ]);
});

test("the people write, one exercise, a playlist search and the media URLs are relative too", async () => {
  const fake = fakeApi();
  fake.answer("GET", "api/v1/exercises/0001", 200, {
    id: "0001",
    name: "push-up",
    equipment: "body weight",
    body_part: "chest",
    target: "pectorals",
    custom: false,
    steps: ["Push."],
    secondary_muscles: [],
    attribution: "ExerciseDB",
  });
  const api = createApi(fake.fetch);

  await api.putPeople([{ name: "Thomas", person_entity_id: "person.thomas" }]);
  await api.exercise("0001");
  await api.playlists("mix");

  expect(fake.requests.map((request) => `${request.method} ${request.path}`)).toEqual([
    "PUT api/v1/people",
    "GET api/v1/exercises/0001",
    "GET api/v1/music/playlists?search=mix",
  ]);
  expect(thumbnailUrl("0001")).toBe("api/v1/exercises/0001/thumbnail");
  expect(gifUrl("0001")).toBe("api/v1/exercises/0001/gif");
});

test("a write sends its JSON body and returns the answer", async () => {
  const fake = fakeApi();
  const api = createApi(fake.fetch);
  const doc = program(1, { name: "Core" }).program;

  const created = await api.createProgram(doc);
  const setup = await api.putSetup({ equipment: ["body weight", "dumbbell"], favourite_playlists: [], default_speaker: null });

  expect(created.program.name).toBe("Core");
  expect(setup.equipment).toEqual(["body weight", "dumbbell"]);
  expect(fake.requests.map((request) => [request.method, request.path, request.body])).toEqual([
    ["POST", "api/v1/programs", doc],
    ["PUT", "api/v1/setup", { equipment: ["body weight", "dumbbell"], favourite_playlists: [], default_speaker: null }],
  ]);
});

test("a refusal with a code and a field (D65) becomes an ApiError with one item", async () => {
  const fake = fakeApi();
  const body = { detail: "A program is already called Core", code: "name_taken", field: "name" };
  fake.answer("POST", "api/v1/programs", 409, body);

  const error = await refusal(createApi(fake.fetch).createProgram(program(1).program));

  expect(error.status).toBe(409);
  expect(error.code).toBe("name_taken");
  expect(error.field).toBe("name");
  expect(error.message).toBe("A program is already called Core");
  expect(error.detail).toBe("A program is already called Core");
  expect(error.items).toEqual([{ field: "name", code: "name_taken", message: "A program is already called Core" }]);
});

test("a refusal without a field keeps the field null", async () => {
  const fake = fakeApi();
  fake.answer("GET", "api/v1/people", 503, { detail: "Home Assistant can't be reached", code: "unavailable", field: null });

  const error = await refusal(createApi(fake.fetch).people());

  expect(error.status).toBe(503);
  expect(error.code).toBe("unavailable");
  expect(error.field).toBeNull();
  expect(error.message).toBe("Home Assistant can't be reached");
});

test("FastAPI's 422 list gives one item per error, at its field without `body`", async () => {
  const fake = fakeApi();
  fake.answer("POST", "api/v1/programs", 422, {
    detail: [
      { loc: ["body", "stations", 0, "exercise"], msg: "No exercise is called Pushup", type: "unknown_exercise" },
      { loc: ["body", "weekdays"], msg: "Value error, an active program needs at least one weekday", type: "weekday_needed" },
      { loc: ["body"], msg: "Field required", type: "missing" },
    ],
  });

  const error = await refusal(createApi(fake.fetch).createProgram(program(1).program));

  expect(error.status).toBe(422);
  expect(error.code).toBe("unknown_exercise");
  expect(error.field).toBe("stations.0.exercise");
  expect(error.message).toBe("No exercise is called Pushup");
  expect(error.items).toEqual([
    { field: "stations.0.exercise", code: "unknown_exercise", message: "No exercise is called Pushup" },
    { field: "weekdays", code: "weekday_needed", message: "Value error, an active program needs at least one weekday" },
    { field: null, code: "missing", message: "Field required" },
  ]);
});

test("a 422 item at the body alone has no field", async () => {
  const fake = fakeApi();
  fake.answer("PUT", "api/v1/setup", 422, { detail: [{ loc: ["body"], msg: "Field required", type: "missing" }] });

  const error = await refusal(
    createApi(fake.fetch).putSetup({ equipment: [], favourite_playlists: [], default_speaker: null }),
  );

  expect(error.field).toBeNull();
  expect(error.code).toBe("missing");
  expect(error.message).toBe("Field required");
});

test("a plain string detail is the message", async () => {
  const fake = fakeApi();

  const error = await refusal(createApi(fake.fetch).program(99));

  expect(error.status).toBe(404);
  expect(error.message).toBe("Not Found");
  expect(error.code).toBeNull();
  expect(error.field).toBeNull();
  expect(error.items).toEqual([{ field: null, code: "", message: "Not Found" }]);
});

test("a session refusal's `{code, message}` detail gives the code and the message", async () => {
  const fake = fakeApi();
  fake.answer("DELETE", "api/v1/programs/3", 409, {
    detail: { code: "conflict", message: "A session is running" },
  });

  const error = await refusal(createApi(fake.fetch).deleteProgram(3));

  expect(error.code).toBe("conflict");
  expect(error.message).toBe("A session is running");
  expect(error.detail).toEqual({ code: "conflict", message: "A session is running" });
});

test("a body that isn't JSON still becomes an ApiError with a message", async () => {
  const api = createApi(async () => new Response("<html>Bad gateway</html>", { status: 502 }));

  const error = await refusal(api.health());

  expect(error.status).toBe(502);
  expect(error.code).toBeNull();
  expect(error.message).toContain("502");
});

test("a fetch that fails (the add-on can't be reached) becomes an ApiError with status 0", async () => {
  const api = createApi(() => Promise.reject(new TypeError("Failed to fetch")));

  const error = await refusal(api.programs());

  expect(error.status).toBe(0);
  expect(error.code).toBeNull();
  expect(error.field).toBeNull();
  expect(error.message).toBe(en.error.network);
  expect(error.items).toEqual([{ field: null, code: "", message: en.error.network }]);
});

test("an unknown station's refusal (D65) gives its code, field and message", async () => {
  const fake = fakeApi();
  const detail = { message: "No exercise is called Pushup", station: 2, close_matches: ["push-up"] };
  fake.answer("POST", "api/v1/programs", 422, { detail, code: "station_unknown", field: "stations.2" });

  const error = await refusal(createApi(fake.fetch).createProgram(program(1).program));

  expect(error.status).toBe(422);
  expect(error.code).toBe("station_unknown");
  expect(error.field).toBe("stations.2");
  expect(error.message).toBe("No exercise is called Pushup");
  expect(error.detail).toEqual(detail);
  expect(error.items).toEqual([
    { field: "stations.2", code: "station_unknown", message: "No exercise is called Pushup" },
  ]);
});
