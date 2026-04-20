import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testMatch: ["smoke.msw-browser.spec.ts"],
  timeout: 15_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    command: "npm run dev:mock -- --host 127.0.0.1 --port 4173 --strictPort",
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
