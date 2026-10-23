import { LitElement, css, html } from "lit";

import { localize } from "./i18n";

/** The part of Home Assistant's `hass` object this card reads. */
interface Hass {
  language?: string;
}

interface TodayCardConfig {
  type: string;
}

interface CustomCardEntry {
  type: string;
  name: string;
  description?: string;
  preview?: boolean;
}

declare global {
  interface Window {
    customCards?: CustomCardEntry[];
  }
  interface HTMLElementTagNameMap {
    "ha-fitness-today-card": TodayCard;
  }
}

const TAG = "ha-fitness-today-card";

/** Today's training. A placeholder until the training plan exists. */
export class TodayCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
  };

  declare hass?: Hass;
  declare config?: TodayCardConfig;

  static override styles = css`
    :host {
      display: block;
    }
    .content {
      padding: 16px;
    }
    h2 {
      margin: 0 0 8px;
      font-size: 1.25em;
      font-weight: 500;
    }
    p {
      margin: 0;
      color: var(--secondary-text-color);
    }
  `;

  setConfig(config: TodayCardConfig): void {
    this.config = config;
  }

  getCardSize(): number {
    return 2;
  }

  private t(key: string): string {
    return localize(this.hass?.language, key);
  }

  protected override render() {
    return html`
      <ha-card>
        <div class="content">
          <h2>${this.t("today.title")}</h2>
          <p>${this.t("common.coming_soon")}</p>
        </div>
      </ha-card>
    `;
  }
}

if (!customElements.get(TAG)) {
  customElements.define(TAG, TodayCard);
  window.customCards = window.customCards ?? [];
  window.customCards.push({
    type: TAG,
    name: "HA Fitness – today",
    description: localize("en", "today.title"),
  });
}
