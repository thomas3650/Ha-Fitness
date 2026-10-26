import { mdiBookshelf, mdiFormatListBulleted, mdiHeartPulse, mdiTuneVariant } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";
import { keyed } from "lit/directives/keyed.js";

import { ApiError, createApi, type Api } from "./api";
import { confirmDialogStyles } from "./components/confirm-dialog";
import { exerciseDetailsStyles } from "./components/exercise-details";
import { exercisePickerStyles } from "./components/exercise-picker";
import { t } from "./i18n";
import { icon } from "./icons";
import { newProgramStyles } from "./pages/new-program";
import { programEditorStyles, type LeaveGuard } from "./pages/program-editor";
import { programsPageStyles } from "./pages/programs-page";
import "./pages/new-program";
import "./pages/program-editor";
import "./pages/status-page";
import { theme } from "./theme";

/** A page the site shows; the hash route says which (website spec §2.1.7). */
export type Route =
  | { page: "programs" }
  | { page: "new" }
  | { page: "empty" }
  | { page: "copy"; id: number }
  | { page: "edit"; id: number }
  | { page: "library" }
  | { page: "setup" }
  | { page: "status" };

type MenuPage = "programs" | "library" | "setup" | "status";

const MENU: { page: MenuPage; icon: string }[] = [
  { page: "programs", icon: mdiFormatListBulleted },
  { page: "library", icon: mdiBookshelf },
  { page: "setup", icon: mdiTuneVariant },
  { page: "status", icon: mdiHeartPulse },
];

/**
 * The route of a hash such as `#/programs/5`. Hash routes keep `/` the one HTML route, so a reload works under
 * Ingress's changing prefix. An empty or unknown hash is the Programs page.
 */
export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#\/?/, "").replace(/\/+$/, "");
  let match: RegExpMatchArray | null;
  if (path === "programs/new") return { page: "new" };
  if (path === "programs/new/empty") return { page: "empty" };
  if ((match = path.match(/^programs\/new\/copy\/(\d+)$/))) return { page: "copy", id: Number(match[1]) };
  if ((match = path.match(/^programs\/(\d+)$/))) return { page: "edit", id: Number(match[1]) };
  if (path === "library" || path === "setup" || path === "status") return { page: path };
  return { page: "programs" };
}

/** The menu entry a route belongs to: the editor's routes belong to Programs. */
function menuPage(route: Route): MenuPage {
  return route.page === "new" || route.page === "empty" || route.page === "copy" || route.page === "edit"
    ? "programs"
    : route.page;
}

/** The site's shell: the menu with the four pages, and the page of the current hash route. */
export class AppShell extends LitElement {
  static override properties = {
    route: { state: true },
    version: { state: true },
  };

  declare route: Route;
  declare version: string | null;

  private readonly api: Api = createApi();
  /** The hash of the page shown; it lags `location.hash` while the page asks whether to leave. */
  private shownHash = location.hash;
  private readonly onHashChange = () => {
    const hash = location.hash;
    if (hash === this.shownHash) return;
    const show = () => {
      this.shownHash = hash;
      this.route = parseRoute(hash);
    };
    const page = this.renderRoot.querySelector("main")?.firstElementChild as (Element & Partial<LeaveGuard>) | null;
    const held = page?.guardLeave?.(() => {
      // The user agreed to leave: go where they were going, without a second hashchange.
      history.replaceState(null, "", hash || location.pathname);
      show();
    });
    if (held) {
      // Stay until the page's answer; replaceState fires no hashchange.
      history.replaceState(null, "", this.shownHash || location.pathname);
      return;
    }
    show();
  };

  constructor() {
    super();
    this.route = parseRoute(location.hash);
    this.version = null;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.shownHash = location.hash;
    this.route = parseRoute(location.hash);
    window.addEventListener("hashchange", this.onHashChange);
    void this.loadVersion();
  }

  /** The add-on's version for the foot of the menu (W1); without an answer the foot stays empty. */
  private async loadVersion(): Promise<void> {
    try {
      this.version = (await this.api.health()).version;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
  }

  override disconnectedCallback(): void {
    window.removeEventListener("hashchange", this.onHashChange);
    super.disconnectedCallback();
  }

  protected override render() {
    const current = menuPage(this.route);
    return html`
      <nav aria-label=${t("menu.label")}>
        <ul>
          ${MENU.map(
            (entry) => html`<li>
              <a href="#/${entry.page}" aria-current=${current === entry.page ? "page" : nothing}
                >${icon(entry.icon)}<span>${t(`menu.${entry.page}`)}</span></a
              >
            </li>`,
          )}
        </ul>
        ${this.version ? html`<p class="version">${t("menu.version", { version: this.version })}</p>` : nothing}
      </nav>
      <main>${this.renderPage()}</main>
    `;
  }

  private renderPage() {
    switch (this.route.page) {
      case "programs":
        return html`<hf-programs-page .api=${this.api}></hf-programs-page>`;
      case "new":
        return html`<hf-new-program .api=${this.api}></hf-new-program>`;
      case "empty":
        return keyed(
          "empty",
          html`<hf-program-editor .api=${this.api} .mode=${{ kind: "new" }}></hf-program-editor>`,
        );
      case "copy":
      case "edit": {
        // A new editor per program and per kind: it loads when it is connected.
        const { page, id } = this.route;
        return keyed(
          `${page}-${id}`,
          html`<hf-program-editor .api=${this.api} .mode=${{ kind: page, id }}></hf-program-editor>`,
        );
      }
      case "library":
        return html`<h1>${t("library.title")}</h1>`;
      case "setup":
        return html`<h1>${t("setup.title")}</h1>`;
      case "status":
        return html`<hf-status-page .api=${this.api}></hf-status-page>`;
    }
  }

  static override styles = [
    theme,
    css`
      :host {
        display: flex;
        min-height: 100vh;
        background: var(--hf-background);
        color: var(--hf-text);
        font-family: var(--hf-font);
        font-size: 14px;
      }
      nav {
        display: flex;
        flex-direction: column;
        flex: 0 0 210px;
        padding: 16px 8px;
        border-right: 1px solid var(--hf-border);
        background: var(--hf-card);
      }
      nav ul {
        flex: 1;
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .version {
        margin: 0;
        padding: 12px;
        color: var(--hf-text-secondary);
        font-size: 12px;
      }
      nav a {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 10px 12px;
        border-radius: 8px;
        color: var(--hf-text);
        font-weight: 500;
        text-decoration: none;
      }
      nav a:hover {
        background: var(--hf-background);
      }
      nav a[aria-current="page"] {
        background: var(--hf-primary-light);
        color: var(--hf-primary);
      }
      .icon {
        flex: none;
        width: 20px;
        height: 20px;
        color: var(--hf-text-secondary);
      }
      nav a[aria-current="page"] .icon {
        color: var(--hf-primary);
      }
      main {
        flex: 1;
        min-width: 0;
        padding: 24px 28px;
      }
      h1 {
        margin: 0 0 20px;
        font-size: 24px;
        font-weight: 500;
      }
      h2 {
        margin: 0 0 8px;
        font-size: 16px;
        font-weight: 500;
      }
      .card {
        margin-bottom: 16px;
        padding: 16px 20px;
        background: var(--hf-card);
        border: 1px solid var(--hf-border);
        border-radius: var(--hf-radius);
      }
      .card p {
        margin: 4px 0;
      }
      .error {
        padding: 12px 16px;
        border-radius: 8px;
        background: var(--hf-error-light);
        color: var(--hf-error);
      }
      table {
        border-collapse: collapse;
        width: 100%;
      }
      th {
        color: var(--hf-text-secondary);
        font-size: 12px;
        font-weight: 500;
        text-align: left;
        text-transform: uppercase;
      }
      th,
      td {
        padding: 8px 12px 8px 0;
        border-bottom: 1px solid var(--hf-border);
      }
      a {
        color: var(--hf-primary);
      }
      button {
        font: inherit;
        cursor: pointer;
      }
      button:disabled {
        cursor: default;
        opacity: 0.6;
      }
      .button,
      button.danger,
      button.text,
      button.link,
      .chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: none;
        text-decoration: none;
        font-weight: 500;
      }
      .button,
      button.danger {
        padding: 10px 20px;
        border-radius: 20px;
      }
      .button.primary {
        background: var(--hf-primary);
        color: #fff;
      }
      .button .icon,
      button.danger .icon {
        width: 18px;
        height: 18px;
        color: inherit;
      }
      button.danger {
        background: var(--hf-error);
        color: #fff;
      }
      button.text,
      button.link {
        padding: 8px;
        background: none;
        color: var(--hf-primary);
      }
      button.link {
        padding: 0;
      }
      .chip {
        padding: 6px 14px;
        border-radius: 16px;
        background: #eeeeee;
        color: var(--hf-text);
      }
      .chip[aria-pressed="true"] {
        background: var(--hf-primary);
        color: #fff;
      }
      .icon-button {
        display: inline-flex;
        padding: 4px;
        border: none;
        border-radius: 50%;
        background: none;
        color: var(--hf-text-secondary);
      }
      .icon-button:hover {
        background: var(--hf-background);
      }
      .switch {
        position: relative;
        width: 36px;
        height: 20px;
        padding: 0;
        border: none;
        border-radius: 10px;
        background: #bdbdbd;
      }
      .switch::after {
        content: "";
        position: absolute;
        top: 2px;
        left: 2px;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background: #fff;
        transition: left 0.15s;
      }
      .switch[aria-checked="true"] {
        background: var(--hf-primary);
      }
      .switch[aria-checked="true"]::after {
        left: 18px;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
    `,
    programsPageStyles,
    confirmDialogStyles,
    newProgramStyles,
    programEditorStyles,
    exercisePickerStyles,
    exerciseDetailsStyles,
  ];
}

if (!customElements.get("hf-app")) customElements.define("hf-app", AppShell);

declare global {
  interface HTMLElementTagNameMap {
    "hf-app": AppShell;
  }
}
