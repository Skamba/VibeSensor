import { defineConfig, devices } from "@playwright/test";

const configuredRegressionWorkers = Number.parseInt(
  process.env.PLAYWRIGHT_REGRESSION_WORKERS ?? "1",
  10,
);

export default defineConfig({
  testDir: "tests",
  testMatch: ["regression*.spec.ts"],
  outputDir: "test-results/playwright-regression",
  timeout: 20_000,
  workers:
    Number.isFinite(configuredRegressionWorkers) &&
    configuredRegressionWorkers > 0
      ? configuredRegressionWorkers
      : 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: "laptop-light",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        colorScheme: "light",
      },
    },
  ],
});
