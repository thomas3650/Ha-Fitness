/**
 * Testing Library's default error message prints the queried container, and its printer refuses a shadow root (the
 * app's pages live in one). This message prints the container's markup itself, so a failed query reads as one.
 */
import { configure } from "@testing-library/dom";
import { afterEach, beforeEach } from "vitest";

const LIMIT = 4000;

configure({
  getElementError(message, container) {
    // An element and a shadow root both have `innerHTML`; the document has none.
    const markup = (container as { innerHTML?: string } | null)?.innerHTML ?? "";
    const shown = markup.length > LIMIT ? `${markup.slice(0, LIMIT)}…` : markup;
    const error = new Error([message, shown].filter(Boolean).join("\n\n"));
    error.name = "TestingLibraryElementError";
    return error;
  },
});

/**
 * A test fails on any `console.error` it didn't expect, so a bug that `failure()` turns into the generic message
 * can't pass unseen. A test that expects one replaces `console.error` with `vi.spyOn(...).mockImplementation(...)`;
 * its calls then go to that spy instead of here.
 */
const originalError = console.error;
let unexpected: unknown[][] = [];

beforeEach(() => {
  unexpected = [];
  console.error = (...args: unknown[]) => {
    unexpected.push(args);
    originalError(...args);
  };
});

afterEach(() => {
  console.error = originalError;
  if (unexpected.length) {
    const shown = unexpected.map((args) => args.map(String).join(" ")).join("\n");
    throw new Error(`console.error was called ${unexpected.length} time(s) unexpectedly:\n${shown}`);
  }
});
