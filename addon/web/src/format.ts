import { t } from "./i18n";

/** A program's length in whole minutes, a half minute up, as the old status page showed it. */
export function minutes(seconds: number): number {
  return Math.floor((seconds + 30) / 60);
}

/**
 * A program's length as the site shows it: whole minutes, a half minute up, and "< 1 min" for a program that has a
 * length but rounds to 0. An empty program (0 s) shows 0 min.
 */
export function duration(seconds: number): string {
  if (seconds > 0 && seconds < 30) return t("duration.under_minute");
  return t("duration.minutes", { minutes: minutes(seconds) });
}
