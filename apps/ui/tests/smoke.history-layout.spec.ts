import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

const historyListRun = {
  run_id: "run-001",
  status: "complete",
  start_time_utc: "2026-01-01T00:00:00Z",
  end_time_utc: "2026-01-01T00:00:12Z",
  created_at: "2026-01-01T00:00:00Z",
  sample_count: 42,
  error_message: null,
};

test("history detail toggle stays readable on narrow screens", async ({ page }) => {
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
      if (!pathname.startsWith("/api/history") || pathname.includes("/insights")) {
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
  const toggle = page.locator('[data-run-toggle="details"][data-run="run-001"]');
  await expect(toggle).toBeVisible();

  const metrics = await toggle.evaluate((button) => {
    const title = button.querySelector<HTMLElement>(".history-row__toggle-title");
    const hint = button.querySelector<HTMLElement>(".history-row__toggle-hint");
    if (!title || !hint) {
      throw new Error("history toggle content is missing");
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
      titleLines: lineMetrics(title).lines,
      hintLines: lineMetrics(hint).lines,
    };
  });

  expect(metrics.buttonWidth).toBeGreaterThanOrEqual(140);
  expect(metrics.titleLines).toBeLessThanOrEqual(2);
  expect(metrics.hintLines).toBeLessThanOrEqual(3);
  await expect(toggle).toContainText("Expand details");
  await expect(toggle).toContainText("View diagnosis and heatmap");
});
