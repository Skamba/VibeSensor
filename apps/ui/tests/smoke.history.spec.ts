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

test("history rows show diagnostic context before expansion", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" });
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
      most_likely_origin: {
        suspected_source: "Front-right wheel imbalance",
        location: "Front-right wheel",
        speed_band: "60-90 km/h",
        explanation: "Order content and spatial dominance agree on the front-right wheel.",
      },
      findings: [
        {
          finding_id: "finding-1",
          amplitude_metric: "db",
          confidence: 0.92,
          confidence_pct: "92%",
          confidence_tone: "success",
          evidence_summary: "Consistent wheel-order energy remains strongest at the front-right wheel.",
          frequency_hz_or_order: "1x wheel",
          strongest_location: "Front-right wheel",
          strongest_speed_band: "60-90 km/h",
          suspected_source: "Front-right wheel imbalance",
        },
      ],
      sensor_intensity_by_location: [
        {
          location: "Front Right Wheel",
          p50_intensity_db: 18,
          p95_intensity_db: 32,
          max_intensity_db: 40,
          dropped_frames_delta: 0,
          queue_overflow_drops_delta: 0,
          sample_count: 20,
        },
      ],
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  const row = page.locator('[data-run-row="1"][data-run="run-001"]');
  await expect(row).toContainText("Analysis ready");
  await expect(row).toContainText("Duration: 12.3 s");
  await expect(row).toContainText("Sensors: 2");
  await expect(row).toContainText("Front-right wheel imbalance");
  await expect(row).toContainText("confidence 92%");
  await expect(page.locator('[data-run-toggle="details"][data-run="run-001"]')).toHaveAttribute("aria-expanded", "false");
});

test("history preview uses dB intensity fields from insights payload", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" });
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
      sensor_count_used: 1,
      sensor_intensity_by_location: [
        {
          location: "Front Left Wheel",
          p50_intensity_db: 10,
          p95_intensity_db: 20,
          max_intensity_db: 30,
          dropped_frames_delta: 0,
          queue_overflow_drops_delta: 0,
          sample_count: 15,
        },
      ],
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  const toggle = page.locator('[data-run-toggle="details"][data-run="run-001"]');
  await expect(toggle).toContainText("View diagnosis and heatmap");
  const overflowMetrics = await toggle.evaluate((button) => {
    const hint = button.querySelector<HTMLElement>(".history-row__toggle-hint");
    return {
      buttonClientWidth: button.clientWidth,
      buttonScrollWidth: button.scrollWidth,
      hintClientWidth: hint?.clientWidth ?? 0,
      hintScrollWidth: hint?.scrollWidth ?? 0,
    };
  });
  const overflowTolerancePx = 2;
  expect(overflowMetrics.buttonScrollWidth).toBeLessThanOrEqual(overflowMetrics.buttonClientWidth + overflowTolerancePx);
  expect(overflowMetrics.hintScrollWidth).toBeLessThanOrEqual(overflowMetrics.hintClientWidth + overflowTolerancePx);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".history-details-row")).toBeVisible();
  await expect(page.locator(".history-details-header")).toContainText("Diagnostic panel");
  await expect(page.locator(".mini-car-dot")).toHaveAttribute("title", /20.0 dB$/);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".history-details-row")).toHaveCount(0);
});

test("history PDF download revokes object URL with safe delay", async ({ page }) => {
  let reportPdfCalls = 0;
  const revokeCallCount = () =>
    page.evaluate(() => (window as typeof window & { __revokeCallCount?: number }).__revokeCallCount ?? 0);
  await installCommonRoutes(page, { runs: [historyListRun] });
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
  expect(await revokeCallCount()).toBe(0);
  await page.waitForTimeout(1000);
  expect(await revokeCallCount()).toBe(1);
});

test("history loaded insights promote the result summary above supporting evidence", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" });
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
      most_likely_origin: {
        suspected_source: "Front-right wheel imbalance",
        location: "Front-right wheel",
        speed_band: "60-90 km/h",
        explanation: "Order content and spatial dominance agree on the front-right wheel.",
      },
      findings: [
        {
          finding_id: "finding-1",
          amplitude_metric: "db",
          confidence: 0.92,
          confidence_pct: "92%",
          confidence_tone: "success",
          evidence_summary: "Consistent wheel-order energy remains strongest at the front-right wheel.",
          frequency_hz_or_order: "1x wheel",
          strongest_location: "Front-right wheel",
          strongest_speed_band: "60-90 km/h",
          suspected_source: "Front-right wheel imbalance",
        },
        {
          finding_id: "finding-2",
          amplitude_metric: "db",
          confidence: 0.67,
          confidence_pct: "67%",
          confidence_tone: "warn",
          evidence_summary: "Secondary driveline energy appears at the tunnel but is weaker than the wheel finding.",
          frequency_hz_or_order: "1x driveshaft",
          strongest_location: "Driveshaft tunnel",
          strongest_speed_band: "70-90 km/h",
          suspected_source: "Secondary driveline contribution",
        },
      ],
      sensor_intensity_by_location: [
        {
          location: "Front Right Wheel",
          p50_intensity_db: 18,
          p95_intensity_db: 32,
          max_intensity_db: 40,
          dropped_frames_delta: 0,
          queue_overflow_drops_delta: 0,
          sample_count: 20,
        },
      ],
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-history").click();
  await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();
  await expect(page.locator(".history-details-header [data-run-action='load-insights']")).toBeVisible();
  await page.locator(".history-details-header [data-run-action='load-insights']").click();
  await expect(page.locator(".history-details-header")).toContainText("Diagnostic panel");
  await expect(page.locator(".history-diagnosis-card")).toContainText("Front-right wheel imbalance");
  await expect(page.locator(".history-diagnosis-card")).toContainText("1x wheel");
  await expect(page.locator(".history-diagnosis-card")).toContainText("Inspect first");
  await expect(page.locator(".history-secondary-findings")).toHaveCount(0);
  await expect(page.locator(".history-finding-card--secondary")).toHaveCount(0);
  await expect(page.locator(".history-evidence-column .history-preview-stats")).toHaveCount(0);
});
