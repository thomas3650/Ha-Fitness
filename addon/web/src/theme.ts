import { css } from "lit";

/**
 * Home Assistant's light theme, as the cards have it (D51, D52). Inside the Ingress iframe HA's CSS variables don't
 * exist, so the site defines the values itself (website spec §2.1.6).
 */
export const theme = css`
  :host {
    --hf-background: #fafafa;
    --hf-card: #fff;
    --hf-border: #e0e0e0;
    --hf-primary: #03a9f4;
    --hf-primary-light: #e1f5fe;
    --hf-text: #212121;
    --hf-text-secondary: #727272;
    --hf-error: #db4437;
    --hf-error-light: #fdecea;
    --hf-success: #43a047;
    --hf-radius: 12px;
    --hf-font: Roboto, Noto, "Noto Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
`;
