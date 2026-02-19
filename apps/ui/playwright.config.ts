import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  outputDir: "tests/test-results",
  snapshotDir: "tests/snapshots",
  snapshotPathTemplate: "{snapshotDir}/{testFilePath}/{arg}-{projectName}{ext}",
  timeout: 45_000,
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
      animations: "disabled",
    },
  },
  use: {
    baseURL: "http://localhost:4173",
  },
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4173",
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
    {
      name: "laptop-dark",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        colorScheme: "dark",
      },
    },
    {
      name: "tablet-light",
      use: {
        ...devices["iPad (gen 7)"],
        // Use Chromium for all projects (only browser installed)
        channel: undefined,
        browserName: "chromium",
        colorScheme: "light",
        hasTouch: true,
      },
    },
    {
      name: "tablet-dark",
      use: {
        ...devices["iPad (gen 7)"],
        channel: undefined,
        browserName: "chromium",
        colorScheme: "dark",
        hasTouch: true,
      },
    },
  ],
});
