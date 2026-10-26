/** A program's length in whole minutes, a half minute up, as the old status page showed it. */
export function minutes(seconds: number): number {
  return Math.floor((seconds + 30) / 60);
}
