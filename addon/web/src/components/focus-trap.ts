const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Keep Tab and Shift+Tab inside a modal dialog: from its last focusable element Tab goes to the first, and Shift+Tab
 * from the first goes to the last. The elements are looked up at each key press, so a button disabled meanwhile
 * drops out.
 */
export function trapFocus(event: KeyboardEvent, container: HTMLElement): void {
  if (event.key !== "Tab") return;
  // Only what Tab reaches: not taken out of the order (tabindex -1), and not hidden from assistive tech.
  const focusable = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) => element.tabIndex >= 0 && !element.closest('[aria-hidden="true"]'),
  );
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const root = container.getRootNode() as Document | ShadowRoot;
  const active = root.activeElement;
  const inside = active instanceof HTMLElement && container.contains(active);
  if (event.shiftKey && (active === first || !inside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !inside)) {
    event.preventDefault();
    first.focus();
  }
}
