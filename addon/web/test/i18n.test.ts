import { expect, test } from "vitest";

import { t } from "../src/i18n";

test("a count reads with the English thousands separator and still picks the plural form", () => {
  expect(t("library.count", { count: 1324 })).toBe("1,324 exercises");
  expect(t("library.count", { count: 1 })).toBe("1 exercise");
  expect(t("library.count", { count: 0 })).toBe("0 exercises");
});

test("a string value is filled in as it is", () => {
  expect(t("menu.version", { version: "1.2.0" })).toBe("HA Fitness 1.2.0");
});
