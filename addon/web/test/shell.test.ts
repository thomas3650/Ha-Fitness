import { findByText, getByRole, queryByRole } from "@testing-library/dom";
import { afterEach, expect, test, vi } from "vitest";

import en from "../src/i18n/en.json";
import "../src/main";
import { fakeApi, program } from "./fake-api";
import { mount, unmount } from "./mount";

afterEach(() => {
  unmount();
  vi.unstubAllGlobals();
});

test("the menu has the four pages, as links to their hash routes", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("");

  const menu = getByRole(root, "navigation", { name: en.menu.label });
  expect(getByRole(menu, "link", { name: en.menu.programs }).getAttribute("href")).toBe("#/programs");
  expect(getByRole(menu, "link", { name: en.menu.library }).getAttribute("href")).toBe("#/library");
  expect(getByRole(menu, "link", { name: en.menu.setup }).getAttribute("href")).toBe("#/setup");
  expect(getByRole(menu, "link", { name: en.menu.status }).getAttribute("href")).toBe("#/status");
});

test("the foot of the menu shows the add-on's version", async () => {
  vi.stubGlobal("fetch", fakeApi({ health: { status: "ok", version: "2.3.1", api_version: 1 } }).fetch);
  const root = await mount("#/programs");

  const menu = getByRole(root, "navigation", { name: en.menu.label });
  expect(await findByText(menu, "HA Fitness 2.3.1")).toBeTruthy();
});

test("without a route the shell shows Programs, and marks it in the menu", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("");

  expect(getByRole(root, "heading", { level: 1, name: en.programs.title })).toBeTruthy();
  expect(getByRole(root, "link", { name: en.menu.programs }).getAttribute("aria-current")).toBe("page");
});

test("changing the hash switches the page", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("#/programs");

  location.hash = "#/library";
  await vi.waitFor(() => getByRole(root, "heading", { level: 1, name: en.library.title }));
  expect(getByRole(root, "link", { name: en.menu.library }).getAttribute("aria-current")).toBe("page");
  expect(getByRole(root, "link", { name: en.menu.programs }).getAttribute("aria-current")).toBeNull();

  location.hash = "#/setup";
  await vi.waitFor(() => getByRole(root, "heading", { level: 1, name: en.setup.title }));

  location.hash = "#/status";
  await vi.waitFor(() => getByRole(root, "heading", { level: 1, name: en.status.title }));
});

test("starting at a program's route renders that route", async () => {
  vi.stubGlobal("fetch", fakeApi({ programs: [program(5)] }).fetch);
  const root = await mount("#/programs/5");

  expect(getByRole(root, "heading", { level: 1, name: en.editor.edit_title })).toBeTruthy();
  expect(getByRole(root, "link", { name: en.menu.programs }).getAttribute("aria-current")).toBe("page");
});

test("the new-program routes render the new-program page", async () => {
  vi.stubGlobal("fetch", fakeApi({ programs: [program(5)] }).fetch);
  const root = await mount("#/programs/new");
  expect(getByRole(root, "heading", { level: 1, name: en.editor.new_title })).toBeTruthy();

  location.hash = "#/programs/new/copy/5";
  await vi.waitFor(() => getByRole(root, "heading", { level: 1, name: en.editor.copy_title }));
});

test("an unknown route falls back to Programs", async () => {
  vi.stubGlobal("fetch", fakeApi().fetch);
  const root = await mount("#/nowhere");

  expect(getByRole(root, "heading", { level: 1, name: en.programs.title })).toBeTruthy();
  expect(queryByRole(root, "heading", { level: 1, name: en.status.title })).toBeNull();
});

test("the page title comes from the language file", () => {
  expect(document.title).toBe(en.title);
});
