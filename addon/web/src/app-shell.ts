import { mdiBookshelf, mdiFormatListBulleted, mdiHeartPulse, mdiTuneVariant } from "@mdi/js";
import { css, html, LitElement, nothing } from "lit";

import { createApi, type Api } from "./api";
import { t } from "./i18n";
import { icon } from "./icons";
import "./pages/status-page";
import { theme } from "./theme";

/** A page the site shows; the hash route says which (website spec §2.1.7). */
export type Route =
  | { page: "programs" }
  | { page: "new" }
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
  if ((match = path.match(/^programs\/new\/copy\/(\d+)$/))) return { page: "copy", id: Number(match[1]) };
  if ((match = path.match(/^programs\/(\d+)$/))) return { page: "edit", id: Number(match[1]) };
  if (path === "library" || path === "setup" || path === "status") return { page: path };
  return { page: "programs" };
}

/** The menu entry a route belongs to: the editor's routes belong to Programs. */
function menuPage(route: Route): MenuPage {
  return route.page === "new" || route.page === "copy" || route.page === "edit" ? "programs" : route.page;
}

/** The site's shell: the menu with the four pages, and the page of the current hash route. */
export class AppShell extends LitElement {
  static override properties = {
    route: { state: true },
  };

  declare route: Route;

  private readonly api: Api = createApi();
  private readonly onHashChange = () => {
    this.route = parseRoute(location.hash);
  };

  constructor() {
    super();
    this.route = parseRoute(location.hash);
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.route = parseRoute(location.hash);
    window.addEventListener("hashchange", this.onHashChange);
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
      </nav>
      <main>${this.renderPage()}</main>
    `;
  }

  private renderPage() {
    switch (this.route.page) {
      case "programs":
        return html`<h1>${t("programs.title")}</h1>`;
      case "new":
        return html`<h1>${t("editor.new_title")}</h1>`;
      case "copy":
        return html`<h1>${t("editor.copy_title")}</h1>`;
      case "edit":
        return html`<h1>${t("editor.edit_title")}</h1>`;
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
        flex: 0 0 210px;
        padding: 16px 8px;
        border-right: 1px solid var(--hf-border);
        background: var(--hf-card);
      }
      nav ul {
        list-style: none;
        margin: 0;
        padding: 0;
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
    `,
  ];
}

if (!customElements.get("hf-app")) customElements.define("hf-app", AppShell);

declare global {
  interface HTMLElementTagNameMap {
    "hf-app": AppShell;
  }
}
