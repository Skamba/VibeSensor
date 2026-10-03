import { defineConfig, devices } from "@playwright/test";

const configuredSmokeWorkers = Number.parseInt(
  process.env.PLAYWRIGHT_SMOKE_WORKERS ?? "1",
  10,
);

// Parallel worktrees can each pick their own port so one run never reuses
// (and then loses) another's dev server.
const port = Number.parseInt(process.env.PLAYWRIGHT_SMOKE_PORT ?? "4173", 10);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "tests",
  // One journey file per page; Vitest excludes the same smoke.*.spec.ts names.
  testMatch: ["smoke.*.spec.ts"],
  outputDir: "test-results/playwright-smoke",
  timeout: 15_000,
  workers:
    Number.isFinite(configuredSmokeWorkers) && configuredSmokeWorkers > 0
      ? configuredSmokeWorkers
      : 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
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
