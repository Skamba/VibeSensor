import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openHistoryTab,
  requestPath,
} from "./smoke.helpers";
import type {
  DeleteHistoryRunPayload,
  HistoryEntry,
  HistoryInsightsPayload,
  HistoryListPayload,
  SpeedUnitPayload,
} from "../src/api/types";
import {
  makeDiagnosis,
  makeHistoryFinding,
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
} from "./history_payload_test_support";

test.describe.configure({ timeout: 20_000 });

type HistoryServer = {
  runs: HistoryEntry[];
  insightRequests: string[];
  deletes: string[];
  failDeletes: Set<string>;
  pdfStatus: number;
  insights?: (runId: string, lang: string) => HistoryInsightsPayload;
};

function run(
  runId: string,
  overrides: Partial<HistoryEntry> = {},
): HistoryEntry {
  return {
    run_id: runId,
    status: "complete",
    start_time_utc: "2026-01-01T00:00:00Z",
    start_time_unverified: false,
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    raw_sample_count: 12080,
    car_name: "Test Hatch",
    error_message: null,
    ...overrides,
  };
}

function insights(runId: string, lang: string): HistoryInsightsPayload {
  const engine = lang === "nl" ? "motor-orde" : "engine order";
  return makeHistoryInsightsPayload({
    run_id: runId,
    lang,
    duration_s: 12.3,
    sensor_count_used: 2,
    metadata: {
      sensor_snapshots: [
        { sensor_id: "s1", location_code: "front_left_wheel" },
      ],
    },
    diagnosis: makeDiagnosis({
      verdict: "fault",
      confidence_level: "strong",
      finding_id: "F001",
      source: "wheel/tire",
      location: "Front Left Wheel",
      zone: "front_left_wheel",
      order_code: "T1",
      frequency_hz: 12.1,
      reference_speed_kmh: 85,
      speed_min_kmh: 63,
      speed_max_kmh: 105,
      source_checks: [
        { source: "wheel/tire", status: "candidate", reason: null },
        {
          source: "driveline",
          status: "ruled_out",
          reason: "no_matching_order",
        },
        {
          source: "engine",
          status: "not_testable",
          reason: "no_engine_reference",
        },
      ],
    }),
    speed_stats: {
      min_kmh: 60,
      max_kmh: 110,
      mean_kmh: null,
      range_kmh: null,
      sample_count: 0,
      stddev_kmh: null,
      steady_speed: false,
    },
    findings: [
      makeHistoryFinding({
        finding_id: "F001",
        suspected_source: "wheel/tire",
        confidence: 0.9,
        confidence_level: "strong",
        frequency_hz_or_order: 32,
        strongest_location: "Front Left Wheel",
        strongest_speed_band: "80-100 km/h",
        evidence_summary: "Wheel order follows road speed.",
      }),
      makeHistoryFinding({
        finding_id: "F002",
        suspected_source: "engine",
        confidence: 0.3,
        confidence_level: "weak",
        frequency_hz_or_order: 18,
        strongest_location: "Engine Bay",
        strongest_speed_band: "60-80 km/h",
        evidence_summary: `Weak ${engine}.`,
      }),
    ],
    sensor_intensity_by_location: [
      makeLocationIntensityRow({
        location: "Front Left Wheel",
        p50_intensity_db: 10,
        p95_intensity_db: 24,
        max_intensity_db: 30,
        sample_count: 15,
      }),
    ],
  });
}

async function bootWithHistory(page: Page, server: HistoryServer) {
  await bootLiveDashboard(page, {
    historyHandler: async (route: Route) => {
      const path = requestPath(route);
      const url = new URL(route.request().url());
      if (path === "/api/history") {
        await fulfillJson<HistoryListPayload>(route, { runs: server.runs });
        return;
      }
      const runId = decodeURIComponent(path.split("/")[3] ?? "");
      if (path.endsWith("/insights")) {
        const lang = url.searchParams.get("lang") ?? "en";
        server.insightRequests.push(`${runId}:${lang}`);
        await fulfillJson<HistoryInsightsPayload>(
          route,
          (server.insights ?? insights)(runId, lang),
        );
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
        await fulfillJson<DeleteHistoryRunPayload>(route, {
          run_id: runId,
          status: "deleted",
        });
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
  await expect(page.locator("#historySummary")).toHaveText("2 runs available");
  // Analysed runs get their row summary prefetched.
  const firstRow = page.locator('[data-run-row="1"][data-run="run-001"]');
  await expect(firstRow.locator(".history-row__diagnosis-title")).toHaveText(
    "Wheel / Tire",
  );
  await expect(firstRow).toContainText("Confidence: Strong");
  await expect(firstRow).not.toContainText("%");
  await expect(firstRow.locator(".history-row__meta-cell--samples")).toHaveText(
    "Raw samples12,080",
  );

  await firstRow.locator('[data-run-toggle="details"]').click();
  const details = page.locator(".history-details-card");
  await expect(details).toContainText("Wheel order follows road speed.");
  await expect(details).toContainText("Weak engine order.");
  await expect(
    details.locator(
      '.history-heatmap__zone[data-location-key="front_left_wheel"]',
    ),
  ).toContainText("24.0 dB");
  // Only the assigned front-left sensor reported; elsewhere no sensor was fitted.
  const engineBay = details.locator(
    '.history-heatmap__zone[data-location-key="engine_bay"]',
  );
  await expect(engineBay).toContainText("no sensor");
  // What the run checked and what it couldn't, in the PDF's words.
  const checks = details.locator(".history-checks");
  await expect(checks.locator(".history-checks__group--checked")).toContainText(
    "Driveline: no propshaft-order vibration found",
  );
  await expect(
    checks.locator(".history-checks__group--not-checked"),
  ).toContainText(
    "Couldn't checkEngine: no engine RPM — connect an OBD-II adapter",
  );

  await details.locator('[data-run-action="load-insights"]').click();
  await expect.poll(() => server.insightRequests.length).toBeGreaterThan(2);

  await page.locator("#languageSelect").selectOption("nl");
  await expect(details).toContainText("Weak motor-orde.");
  await expect(engineBay).toContainText("geen sensor");
  await expect(checks).toContainText(
    "Motor: geen motortoerental — sluit een OBD-II-adapter aan",
  );
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
  await expect(page.locator("#historySummary")).toHaveText("1 run available");
});

test("journey: history speeds follow the speed unit setting in English and Dutch", async ({
  page,
}) => {
  const server = createServer();
  let unit: SpeedUnitPayload["speed_unit"] = "kmh";
  // The server words its warnings in the saved speed unit.
  server.insights = (runId, lang) => ({
    ...insights(runId, lang),
    warnings: [
      {
        code: "suitability_speed_variation",
        severity: "warn",
        applies_to: "run_suitability",
        title: "Speed variation",
        detail: `Record with GPS speed above ${
          unit === "mps" ? "6 m/s" : lang === "nl" ? "20 km/u" : "20 km/h"
        }.`,
      },
    ],
  });
  await bootWithHistory(page, server);
  // Routes added later win over the common settings route.
  await page.route("**/api/settings/speed-unit", async (route) => {
    if (route.request().method() !== "GET") {
      unit = (route.request().postDataJSON() as SpeedUnitPayload).speed_unit;
    }
    await fulfillJson<SpeedUnitPayload>(route, { speed_unit: unit });
  });
  await openHistoryTab(page);
  await page.locator('[data-run-toggle="details"][data-run="run-001"]').click();
  const details = page.locator(".history-details-card");
  await expect(details).toContainText("T1 · 12.1 Hz @ 85 km/h");
  await expect(details).toContainText("63–105 km/h");
  await expect(details).toContainText("60–80 km/h");
  await expect(details).toContainText("speed above 20 km/h.");

  await page.locator("#speedUnitSelect").selectOption("mps");
  // The open diagnosis reloads, so the server's warnings follow the unit too.
  await expect(details).toContainText("speed above 6 m/s.");
  await expect(details).toContainText("T1 · 12.1 Hz @ 24 m/s");
  await expect(details).toContainText("18–29 m/s");
  await expect(details).toContainText("17–22 m/s");
  await expect(details).not.toContainText("km/h");
  expect(unit).toBe("mps");

  await page.locator("#languageSelect").selectOption("nl");
  await expect(details).toContainText("Weak motor-orde.");
  await expect(details).toContainText("@ 24 m/s");

  await page.locator("#speedUnitSelect").selectOption("kmh");
  // Dutch decimals and translated heatmap locations.
  await expect(details).toContainText("T1 · 12,1 Hz @ 85 km/u");
  await expect(details).toContainText("63–105 km/u");
  await expect(details).not.toContainText("km/h");
  await expect(
    page.locator(
      '.history-heatmap__zone[data-location-key="front_left_wheel"] .history-heatmap__zone-label',
    ),
  ).toHaveText("Voorwiel links");
});

test("journey: a no-fault run at one steady speed shows that speed and no empty badge", async ({
  page,
}) => {
  const server = createServer();
  server.runs = [run("run-ok")];
  server.insights = (runId, lang) =>
    makeHistoryInsightsPayload({
      run_id: runId,
      lang,
      duration_s: 15,
      sensor_count_used: 1,
      diagnosis: makeDiagnosis({
        verdict: "no_fault",
        // It checked the wheels: a real "nothing found", not a run that
        // could check nothing.
        source_checks: [
          {
            source: "wheel/tire",
            status: "ruled_out",
            reason: "no_matching_order",
          },
        ],
      }),
      speed_stats: {
        min_kmh: 50,
        max_kmh: 50,
        mean_kmh: 50,
        range_kmh: 0,
        sample_count: 0,
        stddev_kmh: 0,
        steady_speed: true,
      },
    });
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  await page
    .locator(
      '[data-run-row="1"][data-run="run-ok"] [data-run-toggle="details"]',
    )
    .click();
  const card = page.locator(".history-diagnosis-card");
  await expect(card).toContainText("No significant vibration found");
  await expect(card).toContainText("50 km/h");
  await expect(card).not.toContainText("50–50");
  await expect(card.locator(".history-diagnosis-card__confidence")).toHaveCount(
    0,
  );
});
