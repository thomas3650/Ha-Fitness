import { getByRole, getByText } from "@testing-library/dom";
import { afterEach, expect, test } from "vitest";

import "../src/index";

// Testing Library's queries are typed for elements; a shadow root works just as well at runtime.
type Card = Omit<HTMLElement, "shadowRoot"> & { shadowRoot: HTMLElement | null };

/** Put a today card on the page for a user with the given language and wait for it to render. */
async function mount(hass: { language: string }): Promise<Card> {
  const card = document.createElement("ha-fitness-today-card");
  card.setConfig({ type: "custom:ha-fitness-today-card" });
  card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  return card as unknown as Card;
}

afterEach(() => {
  document.body.replaceChildren();
});

test("shows the Danish heading for a Danish user", async () => {
  const card = await mount({ language: "da" });
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Træning i dag");
  expect(getByText(card.shadowRoot!, "Kommer snart")).toBeTruthy();
});

test("shows the English heading for an English user", async () => {
  const card = await mount({ language: "en" });
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Today's training");
  expect(getByText(card.shadowRoot!, "Coming soon")).toBeTruthy();
});

test("is offered in the card picker", () => {
  const entry = window.customCards?.find((card) => card.type === "ha-fitness-today-card");
  expect(entry?.name).toBe("HA Fitness – today");
});
