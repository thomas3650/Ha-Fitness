import { css, html, LitElement, nothing } from "lit";

import { t } from "../i18n";
import { icon } from "../icons";
import { trapFocus } from "./focus-trap";

let nextId = 0;

/**
 * A confirmation (W5): a heading, a message, points, an optional softer way out ("Just a pause? Turn it off
 * instead"), and Cancel and the confirming button. The add-on's refusal shows inside it, so nothing is lost.
 *
 * It renders in light DOM like the pages (the shell's styles apply) and is shown while it is in the page: the page
 * adds it to ask and removes it on `cancel` or once the action is done. It fires `confirm`, `secondary` and `cancel`
 * (Escape and Cancel); while `busy` its buttons are disabled. Tab and Shift+Tab keep the focus inside it.
 */
export class ConfirmDialog extends LitElement {
  static override properties = {
    heading: {},
    message: {},
    points: { attribute: false },
    secondaryLead: {},
    secondaryLabel: {},
    secondaryIcon: {},
    confirmLabel: {},
    icon: {},
    confirmIcon: {},
    error: {},
    busy: { type: Boolean },
  };

  declare heading: string;
  declare message: string;
  declare points: string[];
  declare secondaryLead: string;
  declare secondaryLabel: string;
  declare secondaryIcon: string;
  declare confirmLabel: string;
  declare icon: string;
  declare confirmIcon: string;
  declare error: string | null;
  declare busy: boolean;

  private readonly headingId = `hf-dialog-${++nextId}`;
  private returnFocus: HTMLElement | null = null;

  constructor() {
    super();
    this.heading = "";
    this.message = "";
    this.points = [];
    this.secondaryLead = "";
    this.secondaryLabel = "";
    this.secondaryIcon = "";
    this.confirmLabel = "";
    this.icon = "";
    this.confirmIcon = "";
    this.error = null;
    this.busy = false;
  }

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    const root = this.getRootNode() as Document | ShadowRoot;
    this.returnFocus = root.activeElement instanceof HTMLElement ? root.activeElement : null;
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this.returnFocus?.isConnected) this.returnFocus.focus();
  }

  protected override firstUpdated(): void {
    // Cancel has the focus first: Enter must not delete by accident.
    this.querySelector<HTMLButtonElement>("button[data-cancel]")?.focus();
  }

  private fire(name: "confirm" | "secondary" | "cancel"): void {
    this.dispatchEvent(new CustomEvent(name));
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape" && !this.busy) {
      event.preventDefault();
      this.fire("cancel");
    }
    trapFocus(event, event.currentTarget as HTMLElement);
  }

  protected override render() {
    return html`<div class="dialog-backdrop">
      <div
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby=${this.headingId}
        @keydown=${this.onKeyDown}
      >
        <h2 id=${this.headingId}>${this.icon ? icon(this.icon) : nothing}<span>${this.heading}</span></h2>
        ${this.message ? html`<p>${this.message}</p>` : nothing}
        ${this.points.length ? html`<ul>${this.points.map((point) => html`<li>${point}</li>`)}</ul>` : nothing}
        ${this.secondaryLabel
          ? html`<p class="dialog-secondary">
              ${this.secondaryIcon ? icon(this.secondaryIcon) : nothing}<span>${this.secondaryLead}</span>
              <button type="button" class="link" ?disabled=${this.busy} @click=${() => this.fire("secondary")}>
                ${this.secondaryLabel}
              </button>
            </p>`
          : nothing}
        ${this.error ? html`<p class="error" role="alert">${this.error}</p>` : nothing}
        <div class="dialog-actions">
          <button type="button" class="text" data-cancel ?disabled=${this.busy} @click=${() => this.fire("cancel")}>
            ${t("dialog.cancel")}
          </button>
          <button type="button" class="danger" ?disabled=${this.busy} @click=${() => this.fire("confirm")}>
            ${this.confirmIcon ? icon(this.confirmIcon) : nothing}<span>${this.confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>`;
  }
}

/** The dialog's styles, for the shell's shadow root (the dialog has no shadow root of its own). */
export const confirmDialogStyles = css`
  .dialog-backdrop {
    position: fixed;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgb(0 0 0 / 32%);
  }
  .dialog {
    width: min(500px, calc(100vw - 48px));
    padding: 24px;
    background: var(--hf-card);
    border-radius: 16px;
    box-shadow: 0 8px 32px rgb(0 0 0 / 24%);
  }
  .dialog h2 {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0 0 16px;
    font-size: 20px;
  }
  .dialog h2 .icon {
    width: 24px;
    height: 24px;
    color: var(--hf-error);
  }
  .dialog ul {
    margin: 12px 0;
    padding-left: 20px;
    color: var(--hf-text-secondary);
  }
  .dialog-secondary {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--hf-background);
  }
  .dialog-secondary .icon {
    width: 20px;
    height: 20px;
    color: var(--hf-primary);
  }
  .dialog-actions {
    display: flex;
    justify-content: flex-end;
    gap: 16px;
    margin-top: 20px;
  }
`;

if (!customElements.get("hf-confirm-dialog")) customElements.define("hf-confirm-dialog", ConfirmDialog);

declare global {
  interface HTMLElementTagNameMap {
    "hf-confirm-dialog": ConfirmDialog;
  }
}
