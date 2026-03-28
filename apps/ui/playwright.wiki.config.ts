import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  outputDir: "tests/test-results/wiki",
  timeout: 45_000,
  use: {
    baseURL: "http://localhost:4173",
  },
  webServer: {
    command: "npm run preview",
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
  ],
});
