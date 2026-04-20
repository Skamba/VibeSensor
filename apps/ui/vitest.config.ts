import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// Vitest is the canonical frontend unit/integration test runner for logic-heavy
// modules (payload decoders, runtime helpers, feature orchestration, view-level
// pure helpers, signal-mounted islands). Playwright still owns browser/visual
// coverage via `tests/visual.spec.ts` and `tests/smoke*.spec.ts`.
export default defineConfig({
  plugins: [preact()],
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.spec.ts"],
    exclude: [
      // Playwright-owned browser/visual/smoke specs.
      "tests/visual.spec.ts",
      "tests/smoke.*.spec.ts",
      "tests/msw-browser.smoke.spec.ts",
      // Orphaned browser-style specs that rely on the Playwright `page`
      // fixture. They are not currently matched by any Playwright config and
      // are out of scope for the Vitest unit layer.
      "tests/realtime_logging_summary.spec.ts",
      "tests/settings_car_feedback_reset.spec.ts",
      "tests/settings_obd_scan_timeout.spec.ts",
      "tests/ui_shell_chrome.spec.ts",
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
