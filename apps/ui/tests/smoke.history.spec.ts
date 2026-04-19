import { expect, test } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openHistoryTab,
  readSemanticSurfaceStyles,
  readSemanticToneStyles,
  requestPath,
  installCommonRoutes,
} from "./smoke.helpers";

test.describe.configure({ timeout: 15_000 });

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

test("dark mode diagnosis cards use semantic theme surfaces", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  let confidenceTone: "success" | "warn" = "success";

  await bootLiveDashboard(page, {
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history") || pathname.includes("/insights")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [historyListRun] });
    },
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
          confidence: confidenceTone === "success" ? 0.92 : 0.67,
          confidence_pct: confidenceTone === "success" ? "92%" : "67%",
          confidence_tone: confidenceTone,
          evidence_summary: "Diagnostic evidence remains strongest at the front-right wheel.",
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
  const expectations = [
    {
      tone: "success",
      surfaceVar: "--history-diagnosis-success-surface",
      borderVar: "--history-diagnosis-success-border",
    },
    {
      tone: "warn",
      surfaceVar: "--history-diagnosis-warn-surface",
      borderVar: "--history-diagnosis-warn-border",
    },
  ] as const;

  for (const expectation of expectations) {
    confidenceTone = expectation.tone;
    await page.goto("/");
    await openHistoryTab(page);
    await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();
    const diagnosisCard = page.locator(`.history-diagnosis-card--${expectation.tone}`);
    await expect(diagnosisCard).toBeVisible();
    const styles = await readSemanticSurfaceStyles(
      diagnosisCard,
      expectation.surfaceVar,
      expectation.borderVar,
    );
    expect(styles.backgroundColor).toBe(styles.expectedBackgroundColor);
    expect(styles.borderColor).toBe(styles.expectedBorderColor);
  }
});

test("dark mode history warning pills and banners use semantic theme tokens", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });

  await bootLiveDashboard(page, {
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history") || pathname.includes("/insights")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [historyListRun] });
    },
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
        explanation: "Diagnostic evidence remains strongest at the front-right wheel.",
      },
      findings: [
        {
          finding_id: "finding-1",
          amplitude_metric: "db",
          confidence: 0.67,
          confidence_pct: "67%",
          confidence_tone: "warn",
          evidence_summary: "Secondary driveline evidence remains present.",
          frequency_hz_or_order: "1x wheel",
          strongest_location: "Front-right wheel",
          strongest_speed_band: "60-90 km/h",
          suspected_source: "Front-right wheel imbalance",
        },
      ],
      warnings: [
        {
          code: "speed-gap",
          severity: "warn",
          title: "history.warning.speed_gap",
          detail: "Speed samples were sparse through part of the run.",
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
  await page.goto("/");
  await openHistoryTab(page);
  await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();

  const confidencePill = page.locator(".history-diagnosis-card__confidence--warn");
  await expect(confidencePill).toBeVisible();
  const confidenceStyles = await readSemanticToneStyles(confidencePill, {
    surfaceVar: "--pill-warn-bg",
    textVar: "--pill-warn-text",
  });
  expect(confidenceStyles.backgroundColor).toBe(confidenceStyles.expectedBackgroundColor);
  expect(confidenceStyles.color).toBe(confidenceStyles.expectedColor);

  const warningBanner = page.locator(".history-warning-banner").first();
  await expect(warningBanner).toBeVisible();
  const bannerStyles = await readSemanticToneStyles(warningBanner, {
    surfaceVar: "--warning-surface",
    borderVar: "--warning-border",
    textVar: "--warning-text",
  });
  expect(bannerStyles.backgroundColor).toBe(bannerStyles.expectedBackgroundColor);
  expect(bannerStyles.borderColor).toBe(bannerStyles.expectedBorderColor);
  expect(bannerStyles.color).toBe(bannerStyles.expectedColor);
});

test("dark mode quiet danger buttons use semantic danger tokens in History", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await bootLiveDashboard(page, { runs: [historyListRun] });
  await openHistoryTab(page);
  await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();
  const deleteButton = page.locator('[data-run-action="delete-run"][data-run="run-001"]');
  await expect(deleteButton).toBeVisible();

  const idleStyles = await readSemanticToneStyles(deleteButton, {
    surfaceVar: "--button-danger-quiet-surface",
    borderVar: "--button-danger-quiet-border",
    textVar: "--button-danger-quiet-text",
  });
  await expect(deleteButton).toHaveCSS("background-color", idleStyles.expectedBackgroundColor);
  await expect(deleteButton).toHaveCSS("border-top-color", idleStyles.expectedBorderColor);
  await expect(deleteButton).toHaveCSS("color", idleStyles.expectedColor);

  const deleteButtonBox = await deleteButton.boundingBox();
  if (!deleteButtonBox) {
    throw new Error("expected history delete button to have a layout box");
  }
  await page.mouse.move(
    deleteButtonBox.x + (deleteButtonBox.width / 2),
    deleteButtonBox.y + (deleteButtonBox.height / 2),
  );
  await expect.poll(() => deleteButton.evaluate((element) => element.matches(":hover"))).toBe(true);
  const hoverStyles = await readSemanticToneStyles(deleteButton, {
    surfaceVar: "--button-danger-quiet-hover-surface",
    borderVar: "--button-danger-quiet-hover-border",
    textVar: "--button-danger-quiet-text",
  });
  await expect(deleteButton).toHaveCSS("background-color", hoverStyles.expectedBackgroundColor);
  await expect(deleteButton).toHaveCSS("border-top-color", hoverStyles.expectedBorderColor);
  await expect(deleteButton).toHaveCSS("color", hoverStyles.expectedColor);
});

test("history empty state points users back to Live", async ({ page }) => {
  await bootLiveDashboard(page, {
    settingsHandler: async (route) => {
      if (requestPath(route) === "/api/settings/cars") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" });
        return;
      }
      await fulfillJson(route, {});
    },
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [] });
    },
  });
  await openHistoryTab(page);
  const emptyState = page.locator("#historyTableBody .empty-state");
  await expect(emptyState).toContainText("Capture the first run from Live.");
  await expect(emptyState).toContainText("History fills automatically");
  await emptyState.getByRole("button", { name: "Go to Live" }).click();
  await expect(page.locator("#dashboardView")).toHaveJSProperty("hidden", false);
});

test("history rows show diagnostic context before expansion", async ({ page }) => {
  await bootLiveDashboard(page, {
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
  await openHistoryTab(page);
  const row = page.locator('[data-run-row="1"][data-run="run-001"]');
  await expect(row).toContainText("Analysis ready");
  await expect(row).toContainText("Front-right wheel imbalance");
  await expect(row).toContainText("confidence 92%");
  await expect(row).toContainText("Duration: 12.3 s");
  await expect(row).toContainText("Sensors: 2");
  await expect(row.locator(".history-row__diagnosis-title")).toHaveText("Front-right wheel imbalance");
  await expect(row.locator(".history-row__diagnosis-meta")).toContainText("confidence 92%");
  const chipTexts = await row.locator(".history-row__summary-chip").allTextContents();
  expect(chipTexts).toContain("Analysis ready");
  await expect(page.locator('[data-run-toggle="details"][data-run="run-001"]')).toContainText("Open diagnosis");
  await expect(page.locator('[data-run-action="download-pdf"][data-run="run-001"]')).toContainText("PDF");
  await expect(page.locator('[data-run-toggle="details"][data-run="run-001"]')).toHaveAttribute("aria-expanded", "false");
});

test("history preview uses dB intensity fields from insights payload", async ({ page }) => {
  await bootLiveDashboard(page, {
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
  await openHistoryTab(page);
  const toggle = page.locator('[data-run-toggle="details"][data-run="run-001"]');
  const diagnosisSummary = page.locator('[data-run-row="1"][data-run="run-001"] .history-row__diagnosis');
  await expect(toggle).toContainText("Open diagnosis");
  await expect(diagnosisSummary).toContainText("Duration: 12.3 s");
  await expect(diagnosisSummary).toContainText("Sensors: 1");
  const overflowMetrics = await toggle.evaluate((button) => {
    const title = button.querySelector<HTMLElement>(".history-row__toggle-title");
    return {
      buttonClientWidth: button.clientWidth,
      buttonScrollWidth: button.scrollWidth,
      buttonClientHeight: button.clientHeight,
      buttonScrollHeight: button.scrollHeight,
      titleClientWidth: title?.clientWidth ?? 0,
      titleScrollWidth: title?.scrollWidth ?? 0,
    };
  });
  const overflowTolerancePx = 2;
  expect(overflowMetrics.buttonScrollWidth).toBeLessThanOrEqual(overflowMetrics.buttonClientWidth + overflowTolerancePx);
  expect(overflowMetrics.titleScrollWidth).toBeLessThanOrEqual(overflowMetrics.titleClientWidth + overflowTolerancePx);
  expect(overflowMetrics.buttonScrollHeight).toBeLessThanOrEqual(overflowMetrics.buttonClientHeight + 1);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toContainText("Close diagnosis");
  await expect(page.locator(".history-details-row")).toBeVisible();
  await expect(page.locator(".history-details-header")).toContainText("Diagnostic panel");
  const frontLeftZone = page.locator('.history-heatmap__zone[data-location-key="front-left wheel"]');
  await expect(frontLeftZone).toContainText("Front Left Wheel");
  await expect(frontLeftZone).toContainText("20.0 dB");
  await expect(page.locator(".history-heatmap__zone-meter-fill")).toHaveCount(1);
  await expect(page.locator(".mini-car-dot")).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".history-details-row")).toHaveCount(0);
});

test("history keeps destructive actions inside the expanded management footer", async ({ page }) => {
  await bootLiveDashboard(page, { runs: [historyListRun] });
  await openHistoryTab(page);
  const row = page.locator('[data-run-row="1"][data-run="run-001"]');
  const actionCell = row.locator("td").nth(3);
  await expect(actionCell.locator('[data-run-action="download-pdf"][data-run="run-001"]')).toContainText("PDF");
  await expect(actionCell).not.toContainText("PDF after preview.");
  await expect(actionCell).not.toContainText("Export");
  await expect(actionCell).not.toContainText("Delete");
  await row.locator('[data-run-toggle="details"]').click();
  const footer = page.locator(".history-details-footer");
  await expect(page.locator(".history-main-column .history-details-footer")).toHaveCount(1);
  await expect(footer).toContainText("Reports and data");
  await expect(footer.locator('[data-run-action="download-raw"][data-run="run-001"]')).toContainText("Export");
  const deleteButton = footer.locator('[data-run-action="delete-run"][data-run="run-001"]');
  await expect(deleteButton).toContainText("Delete");
  await expect(deleteButton).toHaveClass(/btn--danger-quiet/);
});

test("history PDF download revokes object URL with safe delay", async ({ page }) => {
  let reportPdfCalls = 0;
  const revokeCallCount = () =>
    page.evaluate(() => (window as typeof window & { __revokeCallCount?: number }).__revokeCallCount ?? 0);
  await installCommonRoutes(page, { runs: [historyListRun] });
  await page.route("**/api/history/**/insights**", async (route) => {
    await fulfillJson(route, {
      run_id: "run-001",
      status: "complete",
      start_time_utc: "2026-01-01T00:00:00Z",
      duration_s: 12.3,
      sensor_count_used: 1,
      findings: [],
      sensor_intensity_by_location: [],
    });
  });
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
  await bootLiveDashboard(page, { installRoutes: false });
  await openHistoryTab(page);
  const pdfButton = page.locator('[data-run-action="download-pdf"][data-run="run-001"]');
  await expect(pdfButton).toBeVisible();
  await pdfButton.click();
  await expect.poll(() => reportPdfCalls).toBe(1);
  expect(await revokeCallCount()).toBe(0);
  await expect.poll(revokeCallCount, { timeout: 2_000 }).toBe(1);
});

test("history loaded insights promote the result summary above supporting evidence", async ({ page }) => {
  await bootLiveDashboard(page, {
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
  await openHistoryTab(page);
  await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();
  await expect(page.locator(".history-details-header [data-run-action='load-insights']")).toBeVisible();
  await page.locator(".history-details-header [data-run-action='load-insights']").click();
  await expect(page.locator(".history-details-header")).toContainText("Diagnostic panel");
  await expect(page.locator(".history-diagnosis-card")).toContainText("Front-right wheel imbalance");
  await expect(page.locator(".history-diagnosis-card")).toContainText("1x wheel");
  await expect(page.locator(".history-diagnosis-card")).toContainText("Inspect first");
  await expect(page.locator('.history-heatmap__zone[data-location-key="front-right wheel"]')).toContainText("32.0 dB");
  await expect(page.locator(".history-secondary-findings")).toContainText("Secondary candidates");
  await expect(page.locator(".history-finding-card--secondary")).toHaveCount(1);
  await expect(page.locator(".history-finding-card--secondary")).toContainText("Secondary driveline contribution");
  await expect(page.locator(".history-main-column .history-details-footer")).toHaveCount(1);
  await expect(page.locator(".history-evidence-column .history-preview-stats")).toHaveCount(0);
  const layoutMetrics = await page.locator(".history-results-layout").evaluate((layout) => {
    const mainColumn = layout.querySelector<HTMLElement>(".history-main-column");
    const insights = layout.querySelector<HTMLElement>(".history-insights-block");
    const footer = layout.querySelector<HTMLElement>(".history-details-footer");
    if (!mainColumn || !insights || !footer) {
      throw new Error("history detail layout is missing expected sections");
    }
    return {
      footerAfterInsightsGap: Math.round(footer.getBoundingClientRect().top - insights.getBoundingClientRect().bottom),
    };
  });
  expect(layoutMetrics.footerAfterInsightsGap).toBeLessThanOrEqual(24);
});
