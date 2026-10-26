/**
 * Testing Library's default error message prints the queried container, and its printer refuses a shadow root (the
 * app's pages live in one). This message prints the container's markup itself, so a failed query reads as one.
 */
import { configure } from "@testing-library/dom";

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
