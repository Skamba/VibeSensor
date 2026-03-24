import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  // Smoke selection lives here so package.json and CI stay on one contract.
  testMatch: ["smoke*.spec.ts"],
  timeout: 45_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
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
