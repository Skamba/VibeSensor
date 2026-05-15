import { expect, test } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
  selectedCarSettings,
} from "./smoke.helpers";

test.describe.configure({ timeout: 12_000 });

const historyListRun = {
  run_id: "run-001",
  status: "complete",
  start_time_utc: "2026-01-01T00:00:00Z",
  end_time_utc: "2026-01-01T00:00:12Z",
  created_at: "2026-01-01T00:00:00Z",
  sample_count: 42,
  car_name: "Track Car",
  error_message: null,
};

test("history uses mobile run cards and keeps the primary action readable on narrow screens", async ({
  page,
}) => {
  await page.setViewportSize({ width: 430, height: 1300 });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, selectedCarSettings());
        return;
      }
      await fulfillJson(route, {});
    },
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (
        !pathname.startsWith("/api/history") ||
        pathname.includes("/insights")
      ) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [historyListRun] });
    },
  });
  await page.route("**/api/history/**/insights**", async (route) => {
    await fulfillJson(route, {
      run_id: "run-001",
      status: "complete",
      start_time_utc: "2026-01-01T00:00:00Z",
      duration_s: 12.3,
      sensor_count_used: 2,
      findings: [],
      sensor_intensity_by_location: [],
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  await expect(page.locator(".history-table thead")).toBeHidden();
  const row = page.locator('[data-run-row="1"][data-run="run-001"]');
  const toggle = page.locator(
    '[data-run-toggle="details"][data-run="run-001"]',
  );
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toHaveAttribute("data-run", "run-001");
  await expect(row).toContainText("Track Car");
  await expect(row).toContainText("Started");
  await expect(row).toContainText("Samples");
  await expect(row).toContainText("Quick report");
  await expect(row.locator(".history-row__diagnosis")).toContainText(
    "Duration: 12.3 s",
  );
  await expect(toggle).toContainText("Open diagnosis");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".history-details-row")).toBeVisible();
});

test("history empty state stays action-oriented on narrow screens", async ({
  page,
}) => {
  await page.setViewportSize({ width: 430, height: 1300 });
  await installCommonRoutes(page, {
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [] });
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  const emptyState = page.locator("#historyTableBody .empty-state");
  await expect(emptyState).toContainText("Capture the first run from Live.");
  await expect(emptyState).toContainText("Go to Live");
  await emptyState.getByRole("button", { name: "Go to Live" }).click();
  await expect(page.locator("#dashboardView")).toHaveJSProperty(
    "hidden",
    false,
  );
});
