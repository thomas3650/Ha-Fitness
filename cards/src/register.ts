/** How often to look for Home Assistant's frontend, and how long at most, in ms. */
const POLL_MS = 50;
const CAP_MS = 15_000;

/**
 * Call `register` once Home Assistant's frontend has booted. HA loads extra modules in parallel
 * with its own, and once it boots it replaces `customElements` with a scoped registry polyfill. A
 * card defined before then lands in the page's first registry, which the polyfill doesn't know, and
 * Lovelace shows a configuration error. So on an HA page (one with a `<home-assistant>` element)
 * this waits until `home-assistant` is defined in the registry `customElements` is then, read
 * again each time. It gives up after about 15 s and registers anyway. Any other page (tests,
 * other hosts) registers at once. Lovelace renders a custom card again once it is defined, so a
 * late define is fine.
 */
export function whenFrontendReady(register: () => void): void {
  if (!document.querySelector("home-assistant")) {
    register();
    return;
  }
  let waited = 0;
  const check = (): void => {
    if (customElements.get("home-assistant") || waited >= CAP_MS) {
      register();
      return;
    }
    waited += POLL_MS;
    setTimeout(check, POLL_MS);
  };
  check();
}
