import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openHistoryTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

type HistoryServer = {
  runs: Array<Record<string, unknown>>;
  insightRequests: string[];
  deletes: string[];
  failDeletes: Set<string>;
  pdfStatus: number;
};

function run(runId: string, overrides: Record<string, unknown> = {}) {
  return {
    run_id: runId,
    status: "complete",
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    sample_count: 42,
    car_name: "Test Hatch",
    error_message: null,
    ...overrides,
  };
}

function insights(runId: string, lang: string) {
  const engine = lang === "nl" ? "motor-orde" : "engine order";
  return {
    run_id: runId,
    status: "complete",
    start_time_utc: "2026-01-01T00:00:00Z",
    duration_s: 12.3,
    sensor_count_used: 2,
    findings: [
      {
        suspected_source: "wheel_tire",
        confidence: 0.9,
        confidence_pct: "90%",
        confidence_tone: "success",
        frequency_hz_or_order: 32,
        strongest_location: "Front Left Wheel",
        strongest_speed_band: "80-100 km/h",
        evidence_summary: "Wheel order follows road speed.",
      },
      {
        suspected_source: "engine",
        confidence: 0.3,
        confidence_pct: "30%",
        confidence_tone: "warn",
        frequency_hz_or_order: 18,
        strongest_location: "Engine Bay",
        strongest_speed_band: "60-80 km/h",
        evidence_summary: `Weak ${engine}.`,
      },
    ],
    warnings: [],
    sensor_intensity_by_location: [
      {
        location: "Front Left Wheel",
        p50_intensity_db: 10,
        p95_intensity_db: 24,
        max_intensity_db: 30,
        dropped_frames_delta: 0,
        queue_overflow_drops_delta: 0,
        sample_count: 15,
      },
    ],
  };
}

async function bootWithHistory(page: Page, server: HistoryServer) {
  await bootLiveDashboard(page, {
    historyHandler: async (route: Route) => {
      const path = requestPath(route);
      const url = new URL(route.request().url());
      if (path === "/api/history") {
        await fulfillJson(route, { runs: server.runs });
        return;
      }
      const runId = decodeURIComponent(path.split("/")[3] ?? "");
      if (path.endsWith("/insights")) {
        const lang = url.searchParams.get("lang") ?? "en";
        server.insightRequests.push(`${runId}:${lang}`);
        await fulfillJson(route, insights(runId, lang));
        return;
      }
      if (path.endsWith("/report.pdf")) {
        if (server.pdfStatus !== 200) {
          await route.fulfill({
            status: server.pdfStatus,
            contentType: "application/json",
            body: JSON.stringify({ detail: "report renderer offline" }),
          });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/pdf",
          headers: {
            "content-disposition": `attachment; filename*=UTF-8''${runId}%20rapport.pdf`,
          },
          body: "%PDF-1.4",
        });
        return;
      }
      if (route.request().method() === "DELETE") {
        if (server.failDeletes.has(runId)) {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "run is locked" }),
          });
          return;
        }
        server.deletes.push(runId);
        server.runs = server.runs.filter((entry) => entry.run_id !== runId);
        await fulfillJson(route, { run_id: runId, status: "deleted" });
        return;
      }
      await fulfillJson(route, {});
    },
  });
}

function createServer(): HistoryServer {
  return {
    runs: [run("run-001"), run("run-002", { car_name: null })],
    insightRequests: [],
    deletes: [],
    failDeletes: new Set(),
    pdfStatus: 200,
  };
}

test("journey: history previews runs, opens a diagnosis, and reloads it in Dutch", async ({
  page,
}) => {
  const server = createServer();
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  await expect(page.locator("#historySummary")).toHaveText(
    "2 run(s) available",
  );
  // Analysed runs get their row summary prefetched.
  const firstRow = page.locator('[data-run-row="1"][data-run="run-001"]');
  await expect(firstRow.locator(".history-row__diagnosis-title")).toHaveText(
    "Wheel / Tire",
  );
  await expect(firstRow).toContainText("confidence 90%");

  await firstRow.locator('[data-run-toggle="details"]').click();
  const details = page.locator(".history-details-card");
  await expect(details).toContainText("Wheel order follows road speed.");
  await expect(details).toContainText("Weak engine order.");
  await expect(
    details.locator(
      '.history-heatmap__zone[data-location-key="front-left wheel"]',
    ),
  ).toContainText("24.0 dB");

  await details.locator('[data-run-action="load-insights"]').click();
  await expect.poll(() => server.insightRequests.length).toBeGreaterThan(2);

  await page.locator("#languageSelect").selectOption("nl");
  await expect(details).toContainText("Weak motor-orde.");
  expect(server.insightRequests).toContain("run-001:nl");

  // Clicking the open row again collapses it.
  await firstRow.click();
  await expect(details).toHaveCount(0);
});

test("journey: history downloads the PDF report and shows a failed download", async ({
  page,
}) => {
  const server = createServer();
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  const pdfButton = page.locator(
    '[data-run-action="download-pdf"][data-run="run-001"]',
  );
  const download = page.waitForEvent("download");
  await pdfButton.click();
  expect((await download).suggestedFilename()).toBe("run-001 rapport.pdf");
  // The click does not toggle the row.
  await expect(page.locator(".history-details-card")).toHaveCount(0);

  server.pdfStatus = 503;
  await pdfButton.click();
  await expect(
    page.locator(
      '[data-run-row="1"][data-run="run-001"] .history-inline-error',
    ),
  ).toHaveText("report renderer offline");
});

test("journey: history deletes one run and reports a partial delete-all", async ({
  page,
}) => {
  const server = createServer();
  server.runs.push(run("run-003"));
  await bootWithHistory(page, server);
  await openHistoryTab(page);

  await page.locator('[data-run-toggle="details"][data-run="run-002"]').click();
  await page
    .locator('[data-run-action="delete-run"][data-run="run-002"]')
    .click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText('Delete run "run-002"?');
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(
    page.locator('[data-run-row="1"][data-run="run-002"]'),
  ).toHaveCount(0);
  expect(server.deletes).toEqual(["run-002"]);

  server.failDeletes.add("run-003");
  await page.locator("#deleteAllRunsBtn").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "Deleted 1 of 2 runs. 1 failed.",
  );
  await expect(page.locator("#appErrorBanner")).toContainText("run is locked");
  await expect(page.locator("#historySummary")).toHaveText(
    "1 run(s) available",
  );
});
