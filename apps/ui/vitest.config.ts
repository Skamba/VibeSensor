import { defineConfig } from "vitest/config";

// Vitest is the canonical frontend unit/integration test runner for logic-heavy
// modules (payload decoders, runtime helpers, feature orchestration, view-level
// pure helpers, signal-mounted islands). Playwright owns the browser smoke
// suite in `tests/smoke*.spec.ts`.
export default defineConfig({
  oxc: {
    jsx: { runtime: "automatic", importSource: "preact" },
  },
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.spec.ts"],
    exclude: [
      // Playwright-owned smoke specs keep an explicit naming contract so
      // Vitest never silently owns browser-fixture tests.
      "tests/smoke.*.spec.ts",
      // Standard Vite/Vitest exclusions.
      "**/node_modules/**",
      "**/dist/**",
      "**/test-results/**",
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
