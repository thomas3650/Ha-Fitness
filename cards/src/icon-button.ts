import { type TemplateResult, html, nothing } from "lit";
import { ifDefined } from "lit/directives/if-defined.js";

/** What `iconButton` draws. */
export interface IconButtonOptions {
  /** An `mdi:` icon, drawn with Home Assistant's `<ha-icon>`. */
  icon?: string;
  /** The button's accessible name when it has no `text`; from the language files. */
  label: string;
  onClick: () => void;
  className?: string;
  disabled?: boolean;
  /** A toggle's state; left out, the button is no toggle. */
  pressed?: boolean;
  /** A visible text after the icon, which then names the button. */
  text?: string;
}

/** A button with an icon, a text or both; an icon-only one is named by its label. */
export function iconButton(options: IconButtonOptions): TemplateResult {
  const { icon, label, onClick, className, disabled, pressed, text } = options;
  return html`<button
    class=${ifDefined(className)}
    aria-label=${ifDefined(text === undefined ? label : undefined)}
    aria-pressed=${ifDefined(pressed === undefined ? undefined : String(pressed))}
    ?disabled=${disabled ?? false}
    @click=${() => onClick()}
  >
    ${icon ? html`<ha-icon icon=${icon} aria-hidden="true"></ha-icon>` : nothing}${text ?? nothing}
  </button>`;
}
