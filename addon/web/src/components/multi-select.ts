import { mdiCheck, mdiChevronDown, mdiClose } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { t } from "../i18n";
import { icon } from "../icons";
import { theme } from "../theme";

let nextId = 0;

export interface MultiSelectOption {
  value: string;
  label: string;
}

/**
 * A searchable multi-select (WAI-ARIA combobox with a multi-selectable listbox): typing filters the options, a click
 * or Enter toggles one, clears the search and keeps the list open; Escape, a click outside or focus leaving closes it.
 * The chosen values show as tags in the options' order, with a remove button, except the `fixed` ones, which are
 * always chosen. Backspace in an empty field removes the last tag that isn't fixed.
 *
 * It fires `change` with the chosen values in `detail.selected` (the fixed ones included). The host is a group named
 * by `label`; the parts live in its own shadow root.
 */
export class MultiSelect extends LitElement {
  static override properties = {
    label: {},
    placeholder: {},
    options: { attribute: false },
    selected: { attribute: false },
    fixed: { attribute: false },
    query: { state: true },
    open: { state: true },
    active: { state: true },
  };

  declare label: string;
  /** The empty field's hint, such as "Any equipment". */
  declare placeholder: string;
  declare options: MultiSelectOption[];
  declare selected: string[];
  declare fixed: string[];
  declare query: string;
  declare open: boolean;
  /** The index of the active option among the matching ones; -1 for none. */
  declare active: number;

  private readonly uid = `hf-multi-select-${++nextId}`;

  private readonly outside = (event: Event): void => {
    if (this.open && !event.composedPath().includes(this)) this.open = false;
  };

  constructor() {
    super();
    this.label = "";
    this.placeholder = "";
    this.options = [];
    this.selected = [];
    this.fixed = [];
    this.query = "";
    this.open = false;
    this.active = -1;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.setAttribute("role", "group");
    this.addEventListener("focusout", this.focusOut);
    document.addEventListener("pointerdown", this.outside);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.removeEventListener("focusout", this.focusOut);
    document.removeEventListener("pointerdown", this.outside);
  }

  protected override updated(): void {
    this.setAttribute("aria-label", this.label);
    // The active option stays in view while the arrow keys move through a long list.
    const active = this.shadowRoot?.querySelector<HTMLElement>('[role="option"].active');
    active?.scrollIntoView?.({ block: "nearest" });
  }

  /** Focus leaving the component (Tab to the next field) closes the list; focus moving inside it doesn't. */
  private readonly focusOut = (event: FocusEvent): void => {
    const next = event.relatedTarget;
    if (!(next instanceof Node && this.shadowRoot?.contains(next))) this.open = false;
  };

  private input(): HTMLInputElement | null {
    return this.shadowRoot?.querySelector("input") ?? null;
  }

  private chosen(value: string): boolean {
    return this.fixed.includes(value) || this.selected.includes(value);
  }

  /** The chosen options, in the options' order: the tags. */
  private tags(): MultiSelectOption[] {
    return this.options.filter((option) => this.chosen(option.value));
  }

  /** The options the search keeps: their label has it, case-insensitive. */
  private matching(): MultiSelectOption[] {
    const needle = this.query.trim().toLowerCase();
    return this.options.filter((option) => option.label.toLowerCase().includes(needle));
  }

  private commit(selected: string[]): void {
    this.selected = selected;
    this.dispatchEvent(new CustomEvent("change", { detail: { selected } }));
  }

  /** Toggle an option from the list; the search clears so every option shows again. */
  private toggle(value: string): void {
    if (this.fixed.includes(value)) return;
    const values = [...new Set([...this.fixed, ...this.selected])];
    this.commit(values.includes(value) ? values.filter((kept) => kept !== value) : [...values, value]);
    this.query = "";
    this.active = this.options.findIndex((option) => option.value === value);
  }

  private removeValue(value: string): void {
    this.commit([...new Set([...this.fixed, ...this.selected])].filter((kept) => kept !== value));
  }

  private onInput(event: Event): void {
    this.query = (event.target as HTMLInputElement).value;
    this.open = true;
    this.active = -1;
  }

  private onKeyDown(event: KeyboardEvent): void {
    const matching = this.matching();
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        if (!matching.length) {
          this.open = true;
          return;
        }
        if (!this.open) {
          this.open = true;
          this.active = event.key === "ArrowDown" ? 0 : matching.length - 1;
          return;
        }
        const by = event.key === "ArrowDown" ? 1 : -1;
        this.active = Math.min(Math.max(this.active + by, 0), matching.length - 1);
        return;
      }
      case "Enter": {
        const option = this.open ? matching[this.active] : undefined;
        if (option) {
          event.preventDefault();
          this.toggle(option.value);
        }
        return;
      }
      case "Escape":
        if (this.open) {
          event.preventDefault();
          event.stopPropagation();
          this.open = false;
        }
        return;
      case "Backspace": {
        if (this.query) return;
        const last = this.tags()
          .filter((option) => !this.fixed.includes(option.value))
          .at(-1);
        if (last) this.removeValue(last.value);
        return;
      }
    }
  }

  protected override render() {
    const matching = this.matching();
    const active = this.open ? matching[this.active] : undefined;
    const listId = `${this.uid}-list`;
    const optionId = (index: number) => `${this.uid}-option-${index}`;
    const tags = this.tags();
    return html`
      <label for=${`${this.uid}-input`}>${this.label}</label>
      <div class="field">
        <input
          id=${`${this.uid}-input`}
          type="text"
          role="combobox"
          autocomplete="off"
          aria-autocomplete="list"
          aria-expanded=${this.open ? "true" : "false"}
          aria-controls=${listId}
          aria-activedescendant=${active ? optionId(this.active) : nothing}
          placeholder=${this.placeholder || nothing}
          .value=${this.query}
          @click=${() => (this.open = true)}
          @input=${(event: Event) => this.onInput(event)}
          @keydown=${(event: KeyboardEvent) => this.onKeyDown(event)}
        />
        <span class=${this.open ? "chevron open" : "chevron"}>${icon(mdiChevronDown)}</span>
        ${this.open
          ? html`<div class="popup">
              <ul id=${listId} role="listbox" aria-multiselectable="true" aria-label=${this.label}>
                ${matching.map(
                  (option, index) => html`<li
                    id=${optionId(index)}
                    role="option"
                    aria-selected=${this.chosen(option.value) ? "true" : "false"}
                    aria-disabled=${this.fixed.includes(option.value) ? "true" : nothing}
                    class=${index === this.active ? "active" : ""}
                    @pointerdown=${(event: Event) => event.preventDefault()}
                    @mousedown=${(event: Event) => event.preventDefault()}
                    @click=${() => {
                      this.active = index;
                      this.toggle(option.value);
                    }}
                  >
                    <span class="tick">${this.chosen(option.value) ? icon(mdiCheck) : nothing}</span>
                    <span>${option.label}</span>
                  </li>`,
                )}
              </ul>
              ${matching.length ? nothing : html`<p class="none" role="status">${t("multi_select.none")}</p>`}
            </div>`
          : html`<ul id=${listId} role="listbox" aria-multiselectable="true" aria-label=${this.label} hidden></ul>`}
      </div>
      ${tags.length
        ? html`<ul class="tags" aria-label=${t("multi_select.chosen", { label: this.label })}>
            ${tags.map(
              (option) => html`<li>
                <span>${option.label}</span>
                ${this.fixed.includes(option.value)
                  ? nothing
                  : html`<button
                      type="button"
                      aria-label=${t("multi_select.remove", { value: option.label })}
                      @click=${() => {
                        this.removeValue(option.value);
                        this.input()?.focus();
                      }}
                    >
                      ${icon(mdiClose)}
                    </button>`}
              </li>`,
            )}
          </ul>`
        : nothing}
    `;
  }

  static override styles = [
    theme,
    css`
      :host {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 180px;
        color: var(--hf-text);
        font-family: var(--hf-font);
        font-size: 14px;
      }
      label {
        color: var(--hf-text-secondary);
        font-size: 12px;
        font-weight: 500;
        line-height: 16px;
        text-transform: uppercase;
      }
      .field {
        position: relative;
      }
      input {
        box-sizing: border-box;
        width: 100%;
        height: 36px;
        padding: 0 36px 0 12px;
        border: 1px solid var(--hf-border);
        border-radius: 8px;
        background: var(--hf-card);
        color: inherit;
        font: inherit;
        outline: none;
      }
      input:focus {
        border-color: var(--hf-primary);
      }
      .chevron {
        position: absolute;
        top: 6px;
        right: 8px;
        display: inline-flex;
        pointer-events: none;
      }
      .chevron .icon {
        width: 24px;
        height: 24px;
        color: var(--hf-text-secondary);
        transition: transform 0.15s;
      }
      .chevron.open .icon {
        transform: rotate(180deg);
      }
      .popup {
        position: absolute;
        z-index: 10;
        top: calc(100% + 4px);
        left: 0;
        right: 0;
        max-height: 280px;
        overflow-y: auto;
        background: var(--hf-card);
        border: 1px solid var(--hf-border);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
      }
      [role="listbox"] {
        margin: 0;
        padding: 4px 0;
        list-style: none;
      }
      [role="option"] {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        cursor: pointer;
      }
      [role="option"]:hover,
      [role="option"].active {
        background: var(--hf-primary-light);
      }
      [role="option"][aria-disabled="true"] {
        cursor: default;
        color: var(--hf-text-secondary);
      }
      .tick {
        display: inline-flex;
        width: 18px;
        height: 18px;
      }
      .icon {
        width: 18px;
        height: 18px;
        color: var(--hf-primary);
      }
      .none {
        margin: 0;
        padding: 8px 12px;
        color: var(--hf-text-secondary);
      }
      .tags {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        margin: 2px 0 0;
        padding: 0;
        list-style: none;
      }
      .tags li {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        padding: 2px 4px 2px 10px;
        border-radius: 12px;
        background: var(--hf-primary-light);
        font-size: 13px;
      }
      .tags li:not(:has(button)) {
        padding-right: 10px;
      }
      .tags button {
        display: inline-flex;
        padding: 2px;
        border: none;
        border-radius: 50%;
        background: none;
        cursor: pointer;
      }
      .tags button .icon {
        width: 14px;
        height: 14px;
        color: var(--hf-text-secondary);
      }
    `,
  ];
}

if (!customElements.get("hf-multi-select")) customElements.define("hf-multi-select", MultiSelect);

declare global {
  interface HTMLElementTagNameMap {
    "hf-multi-select": MultiSelect;
  }
}
