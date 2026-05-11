import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// Vitest is the canonical frontend unit/integration test runner for logic-heavy
// modules (payload decoders, runtime helpers, feature orchestration, view-level
// pure helpers, signal-mounted islands). Playwright still owns browser/visual
// coverage via `tests/visual.spec.ts`, `tests/smoke*.spec.ts`, and
// `tests/regression*.spec.ts`.
export default defineConfig({
  plugins: [preact()],
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.spec.ts"],
    exclude: [
      // Playwright-owned browser/visual specs keep explicit naming contracts so
      // Vitest never silently owns browser-fixture tests.
      "tests/visual.spec.ts",
      "tests/smoke.*.spec.ts",
      "tests/regression.*.spec.ts",
      "tests/msw-browser.smoke.spec.ts",
      // Standard Vite/Vitest exclusions.
      "**/node_modules/**",
      "**/dist/**",
      "**/test-results/**",
      "**/snapshots/**",
    ],
    // Keep explicit imports; do not pollute the global namespace.
    globals: false,
    // Reuse Vite's module graph but keep tests deterministic.
    reporters: process.env.CI ? ["default", "junit"] : ["default"],
    outputFile: {
      junit: "test-results/vitest-junit.xml",
    },
  },
});
