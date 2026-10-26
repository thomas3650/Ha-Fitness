import { mdiCheck, mdiChevronDown, mdiClose, mdiEarth, mdiHomeOutline } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { t } from "../i18n";
import { icon } from "../icons";
import { atHome, homeKinds, type EquipmentChoice } from "../library-filter";
import { theme } from "../theme";

let nextId = 0;

type Mode = "mine" | "all";

/** One line of the list: a mode of the Show group, or a kind of the Or pick equipment group. */
interface Line {
  group: "show" | "pick";
  /** The mode, or the equipment value. */
  value: string;
  label: string;
  /** The mode line's second line (its kinds and count). */
  detail?: string;
  /** The option's accessible name. */
  name: string;
  notAtHome: boolean;
}

/**
 * The equipment filter (spec §2.3, D66): one searchable dropdown with two groups in one multi-selectable listbox.
 * "Show" holds My equipment (the household's kinds plus body weight) and All equipment; "Or pick equipment" holds every
 * kind, those the household lacks marked "not at home". Choosing a mode clears the picked kinds and closes the list;
 * picking or unpicking a kind keeps it open; with no kind left the filter is My equipment again. The choice shows as
 * tags; My equipment's has no remove button. Backspace in the empty search removes the last picked kind, or turns All
 * equipment back into My equipment.
 *
 * The keyboard, the focus and the combobox follow `hf-multi-select`. It fires `change` with the new choice in
 * `detail.choice`; it never fires for the mode that is already on. The host is a group named by `label`.
 */
export class EquipmentFilter extends LitElement {
  static override properties = {
    label: {},
    hideLabel: { type: Boolean },
    values: { attribute: false },
    home: { attribute: false },
    counts: { attribute: false },
    choice: { attribute: false },
    query: { state: true },
    open: { state: true },
    active: { state: true },
  };

  declare label: string;
  /** Hide the label from sight; it still names the field (the editor's library panel, W7). */
  declare hideLabel: boolean;
  /** Every kind to pick from, band folded (`equipmentValues`). */
  declare values: string[];
  /** The household's equipment. */
  declare home: string[];
  /** How many exercises of the whole library each mode gives. */
  declare counts: { mine: number; all: number };
  declare choice: EquipmentChoice;
  declare query: string;
  declare open: boolean;
  /** The index of the active line among the shown ones; -1 for none. */
  declare active: number;

  private readonly uid = `hf-equipment-filter-${++nextId}`;

  private readonly outside = (event: Event): void => {
    if (this.open && !event.composedPath().includes(this)) this.open = false;
  };

  constructor() {
    super();
    this.label = "";
    this.hideLabel = false;
    this.values = [];
    this.home = [];
    this.counts = { mine: 0, all: 0 };
    this.choice = { mode: "mine" };
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
    const active = this.shadowRoot?.querySelector<HTMLElement>('[role="option"].active');
    active?.scrollIntoView?.({ block: "nearest" });
  }

  /** Focus leaving the component closes the list; focus moving inside it doesn't. */
  private readonly focusOut = (event: FocusEvent): void => {
    const next = event.relatedTarget;
    if (!(next instanceof Node && this.shadowRoot?.contains(next))) this.open = false;
  };

  private input(): HTMLInputElement | null {
    return this.shadowRoot?.querySelector("input") ?? null;
  }

  private picked(): string[] {
    return this.choice.mode === "picked" ? this.choice.values : [];
  }

  /** Kinds in the list's order, any unknown one after them. */
  private ordered(values: string[]): string[] {
    return [
      ...this.values.filter((value) => values.includes(value)),
      ...values.filter((value) => !this.values.includes(value)),
    ];
  }

  private selected(line: Line): boolean {
    return line.group === "show" ? this.choice.mode === line.value : this.picked().includes(line.value);
  }

  /** Every line, in the list's order. */
  private lines(): Line[] {
    const home = new Set(this.home);
    const modeLine = (mode: Mode, detail: string): Line => {
      const label = t(`equipment_filter.${mode}`);
      return {
        group: "show",
        value: mode,
        label,
        detail,
        name: t("equipment_filter.mode_name", { label, line: detail }),
        notAtHome: false,
      };
    };
    const kinds = homeKinds(this.home).join(t("list_separator"));
    return [
      modeLine("mine", t("equipment_filter.mine_line", { kinds, count: this.counts.mine })),
      modeLine("all", t("equipment_filter.all_line", { count: this.counts.all })),
      ...this.values.map((value): Line => {
        const notAtHome = !atHome(value, home);
        return {
          group: "pick",
          value,
          label: value,
          name: notAtHome ? t("equipment_filter.not_at_home_name", { value }) : value,
          notAtHome,
        };
      }),
    ];
  }

  /** The lines the search keeps: their label has it, case-insensitive (a mode line's kinds don't count). */
  private matching(): Line[] {
    const needle = this.query.trim().toLowerCase();
    return this.lines().filter((line) => line.label.toLowerCase().includes(needle));
  }

  private commit(choice: EquipmentChoice): void {
    this.choice = choice;
    this.dispatchEvent(new CustomEvent("change", { detail: { choice } }));
  }

  private chooseMode(mode: Mode): void {
    if (this.choice.mode === mode) return;
    this.commit({ mode });
    this.query = "";
    this.open = false;
    this.active = -1;
  }

  private withoutKind(value: string): EquipmentChoice {
    const values = this.picked().filter((kept) => kept !== value);
    return values.length ? { mode: "picked", values } : { mode: "mine" };
  }

  /** Pick or unpick a kind; the list stays open and the search clears so every line shows again. */
  private toggleKind(value: string): void {
    const picked = this.picked();
    this.commit(
      picked.includes(value) ? this.withoutKind(value) : { mode: "picked", values: this.ordered([...picked, value]) },
    );
    this.query = "";
    this.active = this.lines().findIndex((line) => line.group === "pick" && line.value === value);
  }

  private choose(line: Line): void {
    if (line.group === "show") this.chooseMode(line.value as Mode);
    else this.toggleKind(line.value);
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
        const line = this.open ? matching[this.active] : undefined;
        if (line) {
          event.preventDefault();
          this.choose(line);
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
        const last = this.ordered(this.picked()).at(-1);
        if (last !== undefined) this.commit(this.withoutKind(last));
        else if (this.choice.mode === "all") this.commit({ mode: "mine" });
        return;
      }
    }
  }

  protected override render() {
    const matching = this.matching();
    const active = this.open ? matching[this.active] : undefined;
    const listId = `${this.uid}-list`;
    const optionId = (index: number) => `${this.uid}-option-${index}`;
    return html`
      <label for=${`${this.uid}-input`} class=${this.hideLabel ? "hidden-label" : ""}>${this.label}</label>
      <div class="field">
        ${this.renderTags()}
        <input
          id=${`${this.uid}-input`}
          type="text"
          role="combobox"
          autocomplete="off"
          aria-autocomplete="list"
          aria-expanded=${this.open ? "true" : "false"}
          aria-controls=${listId}
          aria-activedescendant=${active ? optionId(this.active) : nothing}
          placeholder=${this.open ? t("equipment_filter.search") : nothing}
          .value=${this.query}
          @click=${() => (this.open = true)}
          @input=${(event: Event) => this.onInput(event)}
          @keydown=${(event: KeyboardEvent) => this.onKeyDown(event)}
        />
        <span class=${this.open ? "chevron open" : "chevron"}>${icon(mdiChevronDown)}</span>
        ${
          this.open
            ? html`<div class="popup">
                <div id=${listId} role="listbox" aria-multiselectable="true" aria-label=${this.label}>
                  ${this.renderGroup(matching, "show", optionId)} ${this.renderGroup(matching, "pick", optionId)}
                </div>
                ${matching.length ? nothing : html`<p class="none" role="status">${t("multi_select.none")}</p>`}
              </div>`
            : html`<div id=${listId} role="listbox" aria-multiselectable="true" aria-label=${this.label} hidden></div>`
        }
      </div>
    `;
  }

  private renderGroup(matching: Line[], group: Line["group"], optionId: (index: number) => string) {
    const lines = matching.map((line, index) => ({ line, index })).filter(({ line }) => line.group === group);
    if (!lines.length) return nothing;
    const heading = `${this.uid}-${group}`;
    const options = lines.map(({ line, index }) => this.renderLine(line, index, optionId(index)));
    return group === "show"
      ? html`<div role="group" class="show" aria-label=${t("equipment_filter.show")}>${options}</div>`
      : html`<div role="group" class="pick" aria-labelledby=${heading}>
          <div id=${heading} class="heading" role="presentation">${t("equipment_filter.pick")}</div>
          ${options}
        </div>`;
  }

  private renderLine(line: Line, index: number, id: string) {
    const selected = this.selected(line);
    return html`<div
      id=${id}
      role="option"
      aria-selected=${selected ? "true" : "false"}
      aria-label=${line.name}
      class=${[line.group, index === this.active ? "active" : ""].join(" ")}
      @pointerdown=${(event: Event) => event.preventDefault()}
      @mousedown=${(event: Event) => event.preventDefault()}
      @click=${() => {
        this.active = index;
        this.choose(line);
      }}
    >
      <span class="tick">${selected ? icon(mdiCheck) : nothing}</span>
      ${
        line.group === "show"
          ? html`<span class="mode-icon">${icon(line.value === "mine" ? mdiHomeOutline : mdiEarth)}</span>
              <span class="mode-text">
                <span class="mode-label">${line.label}</span>
                <span class="mode-detail">${line.detail}</span>
              </span>`
          : html`<span class="kind">${line.label}</span>
              ${line.notAtHome ? html`<span class="badge">${t("equipment_filter.not_at_home")}</span>` : nothing}`
      }
    </div>`;
  }

  private renderTags() {
    const remove = (name: string, then: EquipmentChoice) =>
      html`<button
        type="button"
        aria-label=${t("multi_select.remove", { value: name })}
        @click=${() => {
          this.commit(then);
          this.input()?.focus();
        }}
      >
        ${icon(mdiClose)}
      </button>`;
    const tags =
      this.choice.mode === "mine"
        ? [html`<li class="mode"><span>${t("equipment_filter.mine")}</span></li>`]
        : this.choice.mode === "all"
          ? [
              html`<li class="mode">
                <span>${t("equipment_filter.all")}</span>${remove(t("equipment_filter.all"), { mode: "mine" })}
              </li>`,
            ]
          : this.ordered(this.choice.values).map(
              (value) => html`<li><span>${value}</span>${remove(value, this.withoutKind(value))}</li>`,
            );
    return html`<ul class="tags" aria-label=${t("multi_select.chosen", { label: this.label })}>
      ${tags}
    </ul>`;
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
      label.hidden-label {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
        white-space: nowrap;
      }
      .field {
        position: relative;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        box-sizing: border-box;
        min-height: 36px;
        padding: 3px 36px 3px 6px;
        border: 1px solid var(--hf-border);
        border-radius: 8px;
        background: var(--hf-card);
      }
      .field:focus-within {
        border-color: var(--hf-primary);
      }
      input {
        flex: 1;
        min-width: 40px;
        height: 28px;
        padding: 0 4px;
        border: none;
        background: none;
        color: inherit;
        font: inherit;
        outline: none;
      }
      .chevron {
        position: absolute;
        top: calc(50% - 12px);
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
        min-width: 100%;
        width: max-content;
        max-width: 320px;
        max-height: 360px;
        overflow-y: auto;
        background: var(--hf-card);
        border: 1px solid var(--hf-border);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
      }
      [role="listbox"] {
        padding: 4px 0;
      }
      .pick {
        border-top: 1px solid var(--hf-border);
      }
      .show + .pick {
        margin-top: 4px;
      }
      .heading {
        padding: 10px 12px 4px;
        color: var(--hf-text-secondary);
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.5px;
        text-transform: uppercase;
      }
      [role="option"] {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        cursor: pointer;
      }
      [role="option"].show {
        padding: 8px 12px;
      }
      [role="option"]:hover,
      [role="option"].active {
        background: var(--hf-primary-light);
      }
      .tick {
        display: inline-flex;
        flex: none;
        width: 18px;
        height: 18px;
      }
      .icon {
        width: 18px;
        height: 18px;
        color: var(--hf-primary);
      }
      .mode-icon .icon {
        width: 20px;
        height: 20px;
        color: var(--hf-text-secondary);
      }
      [role="option"][aria-selected="true"] .mode-icon .icon,
      [role="option"][aria-selected="true"] .mode-label {
        color: var(--hf-primary);
      }
      .mode-text {
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .mode-label {
        font-weight: 500;
      }
      .mode-detail {
        color: var(--hf-text-secondary);
        font-size: 12px;
      }
      .kind {
        flex: 1;
      }
      .badge {
        padding: 1px 6px;
        border-radius: 8px;
        background: var(--hf-background);
        color: var(--hf-text-secondary);
        font-size: 11px;
        white-space: nowrap;
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
        margin: 0;
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
      .tags li.mode {
        color: var(--hf-primary);
        font-weight: 500;
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

if (!customElements.get("hf-equipment-filter")) customElements.define("hf-equipment-filter", EquipmentFilter);

declare global {
  interface HTMLElementTagNameMap {
    "hf-equipment-filter": EquipmentFilter;
  }
}
