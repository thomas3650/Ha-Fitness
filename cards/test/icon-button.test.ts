import { getByRole, queryByRole } from "@testing-library/dom";
import { render } from "lit";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { iconButton } from "../src/icon-button";

let container: HTMLElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
});

afterEach(() => {
  container.remove();
});

test("an icon-only button is named by its label", () => {
  const onClick = vi.fn();
  render(iconButton({ icon: "mdi:play", label: "Fortsæt", onClick }), container);
  getByRole(container, "button", { name: "Fortsæt" }).click();
  expect(onClick).toHaveBeenCalledOnce();
});

test("a button with text is named by the text instead of the label", () => {
  render(iconButton({ icon: "mdi:check", label: "Færdig", text: "Gem", onClick: () => undefined }), container);
  expect(getByRole(container, "button", { name: "Gem" })).toBeTruthy();
  expect(queryByRole(container, "button", { name: "Færdig" })).toBeNull();
});

test("a disabled button can't be tapped", () => {
  const onClick = vi.fn();
  render(iconButton({ icon: "mdi:skip-next", label: "Næste", disabled: true, onClick }), container);
  const button = getByRole(container, "button", { name: "Næste" }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
});

test("the pressed state shows only when given", () => {
  render(iconButton({ icon: "mdi:play", label: "Fortsæt", onClick: () => undefined }), container);
  expect(getByRole(container, "button", { name: "Fortsæt" })).toBeTruthy();
  expect(queryByRole(container, "button", { pressed: true })).toBeNull();
  expect(queryByRole(container, "button", { pressed: false })).toBeNull();

  render(iconButton({ label: "Thomas", text: "Thomas", pressed: false, onClick: () => undefined }), container);
  expect(getByRole(container, "button", { name: "Thomas", pressed: false })).toBeTruthy();

  render(iconButton({ label: "Thomas", text: "Thomas", pressed: true, onClick: () => undefined }), container);
  expect(getByRole(container, "button", { name: "Thomas", pressed: true })).toBeTruthy();
});
