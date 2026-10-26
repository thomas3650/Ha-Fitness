import { html, type TemplateResult } from "lit";

/**
 * An `@mdi/js` path as an inline `<svg>`: HA's `<ha-icon>` doesn't exist inside the Ingress iframe (website spec
 * §2.1.6, D62). The icon is decoration; the text next to it names the thing.
 */
export function icon(path: string): TemplateResult {
  return html`<svg class="icon" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false">
    <path d=${path} fill="currentColor"></path>
  </svg>`;
}
