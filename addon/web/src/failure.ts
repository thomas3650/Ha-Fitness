import { ApiError } from "./api";
import { t } from "./i18n";

/**
 * A failed request's text for the page. A refusal from the add-on (or no answer at all) keeps its own message.
 * Anything else is a bug in the site: the page shows a generic message, so no read waits forever and no bug's text
 * reaches the user, and the bug goes to the console.
 */
export function failure(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  console.error(error);
  return t("error.unexpected");
}
