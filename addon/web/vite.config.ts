import { defineConfig } from "vitest/config";

// The add-on serves `dist/index.html` at the panel's root and `dist/web/*` at `web/`. Every URL is relative, so the
// site works under Ingress's changing prefix; `scripts/check-dist.mjs` checks that after each build.
export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    assetsDir: "web",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "happy-dom",
    // One time zone for the tests, so a local date means the same on a Mac and in CI.
    env: { TZ: "Europe/Copenhagen" },
  },
});
