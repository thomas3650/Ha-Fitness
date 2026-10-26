/** Mount `<hf-app>` at a hash route, and remove it again; the window outlives each test. */

interface AppElement extends HTMLElement {
  updateComplete: Promise<boolean>;
}

/**
 * Set the hash, put a fresh `<hf-app>` in the page and wait for its first render. It returns the app's shadow root,
 * which holds the menu and the pages, for Testing Library's queries (they work on a shadow root at runtime).
 */
export async function mount(hash: string): Promise<HTMLElement> {
  history.replaceState(null, "", hash || location.pathname);
  const app = document.createElement("hf-app") as AppElement;
  document.body.append(app);
  await app.updateComplete;
  return app.shadowRoot as unknown as HTMLElement;
}

export function unmount(): void {
  document.body.replaceChildren();
  history.replaceState(null, "", location.pathname);
}
