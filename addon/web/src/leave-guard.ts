/** An element the shell asks before it leaves the page (website spec §2.2.4; the Setup page since #87). */
export interface LeaveGuard {
  /** Return true to hold the leave; the page calls `go` once the user agrees. */
  guardLeave(go: () => void): boolean;
}
