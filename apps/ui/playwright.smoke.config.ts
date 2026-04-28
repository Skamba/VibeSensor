import { defineConfig, devices } from "@playwright/test";

const configuredSmokeWorkers = Number.parseInt(
  process.env.PLAYWRIGHT_SMOKE_WORKERS ?? "1",
  10,
);

export default defineConfig({
  testDir: "tests",
  // Smoke selection lives here so package.json and CI stay on one contract.
  testMatch: ["smoke*.spec.ts"],
  outputDir: "test-results/playwright-smoke",
  timeout: 15_000,
  workers:
    Number.isFinite(configuredSmokeWorkers) && configuredSmokeWorkers > 0
      ? configuredSmokeWorkers
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
