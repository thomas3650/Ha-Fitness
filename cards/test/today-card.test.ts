import { getByRole } from "@testing-library/dom";
import { afterEach, expect, test } from "vitest";

import en from "../src/i18n/en.json";
import "../src/index";

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
type Card = Omit<HTMLElement, "shadowRoot"> & { shadowRoot: HTMLElement | null };

/** Put a today card on the page for a user with the given language and wait for it to render. */
async function mount(language: string): Promise<Card> {
  const card = document.createElement("ha-fitness-today-card");
  card.setConfig({ type: "custom:ha-fitness-today-card" });
  card.hass = { locale: { language } };
  document.body.append(card);
  await card.updateComplete;
  return card as unknown as Card;
}

afterEach(() => {
  document.body.replaceChildren();
});

test("shows the Danish heading for a Danish user", async () => {
  const card = await mount("da");
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Træning i dag");
});

test("shows the English heading for an English user", async () => {
  const card = await mount("en");
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Today's training");
});

test("is offered in the card picker, in English", () => {
  const entry = window.customCards?.find((card) => card.type === "ha-fitness-today-card");
  expect(entry?.name).toBe(en.picker.name);
  expect(entry?.description).toBe(en.picker.description);
});
