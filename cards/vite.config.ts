import { defineConfig } from "vitest/config";

// One ES module, written straight into the integration, which serves it to Home Assistant's frontend.
export default defineConfig({
  build: {
    lib: {
      entry: "src/index.ts",
      formats: ["es"],
      fileName: () => "ha-fitness-cards.js",
    },
    outDir: "../custom_components/ha_fitness/frontend",
    // Keep frontend/.gitkeep (and everything else the integration ships there).
    emptyOutDir: false,
    sourcemap: false,
  },
  test: {
    environment: "happy-dom",
    // One time zone for the tests, so a local date means the same on a Mac and in CI.
    env: { TZ: "Europe/Copenhagen" },
  },
});
