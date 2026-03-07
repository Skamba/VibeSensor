import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("history preview uses dB intensity fields from insights payload", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], activeCarId: "car-1" });
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
      await fulfillJson(route, { runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }] });
    },
  });
  await page.route("**/api/history/**/insights**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", duration_s: 12.3, sensor_count_used: 1, sensor_intensity_by_location: [{ location: "Front Left Wheel", p50_intensity_db: 10, p95_intensity_db: 20, max_intensity_db: 30, dropped_frames_delta: 0, queue_overflow_drops_delta: 0, sample_count: 15 }] }) });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  await page.locator('tr[data-run="run-001"] td').first().click();
  await expect(page.locator(".history-details-row")).toBeVisible();
  await expect(page.locator(".mini-car-dot")).toHaveAttribute("title", /20.0 dB$/);
});

test("history PDF download revokes object URL with safe delay", async ({ page }) => {
  let reportPdfCalls = 0;
  await installCommonRoutes(page, { runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }] });
  await page.route("**/api/history/**/report.pdf**", async (route) => {
    reportPdfCalls += 1;
    await route.fulfill({ status: 200, headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="run-001_report.pdf"' }, body: "PDF" });
  });
  await page.addInitScript(() => {
    const globalState = window as typeof window & { __revokeCallCount?: number };
    globalState.__revokeCallCount = 0;
    URL.createObjectURL = (() => "blob:history-download-test") as typeof URL.createObjectURL;
    URL.revokeObjectURL = ((_: string) => {
      globalState.__revokeCallCount = (globalState.__revokeCallCount ?? 0) + 1;
    }) as typeof URL.revokeObjectURL;
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  await page.locator('[data-run-action="download-pdf"][data-run="run-001"]').click();
  await expect.poll(() => reportPdfCalls).toBe(1);
  await page.waitForTimeout(200);
  await expect(page.evaluate(() => (window as typeof window & { __revokeCallCount?: number }).__revokeCallCount ?? 0)).resolves.toBe(0);
  await page.waitForTimeout(1000);
  await expect(page.evaluate(() => (window as typeof window & { __revokeCallCount?: number }).__revokeCallCount ?? 0)).resolves.toBe(1);
});