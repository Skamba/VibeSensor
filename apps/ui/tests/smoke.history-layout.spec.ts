import { expect, test } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
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
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }],
          active_car_id: "car-1",
        });
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
  await expect(row).toContainText("Track Car");
  await expect(row).toContainText("Started");
  await expect(row).toContainText("Samples");
  await expect(row).toContainText("Quick report");
  await expect(row.locator(".history-row__diagnosis")).toContainText(
    "Duration: 12.3 s",
  );

  const metrics = await row.evaluate((element) => {
    const diagnosisTitle = element.querySelector<HTMLElement>(
      ".history-row__diagnosis-title",
    );
    const diagnosisMeta = element.querySelector<HTMLElement>(
      ".history-row__diagnosis-meta",
    );
    const button = element.querySelector<HTMLElement>(
      '[data-run-toggle="details"]',
    );
    if (!diagnosisTitle || !diagnosisMeta || !button) {
      throw new Error("history row content is missing");
    }
    const lineMetrics = (el: HTMLElement) => {
      const style = getComputedStyle(el);
      const fontSize = Number.parseFloat(style.fontSize) || 16;
      const lineHeight = Number.parseFloat(style.lineHeight) || fontSize * 1.2;
      return {
        lines: Math.round(el.getBoundingClientRect().height / lineHeight),
      };
    };
    return {
      buttonWidth: Math.round(button.getBoundingClientRect().width),
      diagnosisTitleLines: lineMetrics(diagnosisTitle).lines,
      diagnosisMetaLines: lineMetrics(diagnosisMeta).lines,
    };
  });

  expect(metrics.buttonWidth).toBeGreaterThanOrEqual(140);
  expect(metrics.diagnosisTitleLines).toBeLessThanOrEqual(2);
  expect(metrics.diagnosisMetaLines).toBeLessThanOrEqual(3);
  const rowDisplay = await row.evaluate(
    (element) => getComputedStyle(element).display,
  );
  expect(rowDisplay).toBe("grid");
  await expect(toggle).toContainText("Open diagnosis");
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
});
