import { expect, test, type Page, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  fulfillJson,
  openHistoryTab,
  requestPath,
  selectPreference,
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
  makeOwnerPage,
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
    interrupted: false,
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    raw_sample_count: 12080,
    car_name: "Test Hatch",
    error_message: null,
    ...overrides,
  };
}

const DUTCH_OWNER = {
  result: "Wiel linksvoor",
  headline:
    "Waarschijnlijke oorzaak: een wiel- of bandprobleem bij het wiel linksvoor",
  confidence_label: "Zekerheid",
  level_word: "Matig",
  level_meaning: "doe eerst de goedkope controle.",
  confirm_title: "Eerst goedkoop controleren",
  next_step_title: "Volgende stap",
} as const;

function insights(runId: string, lang: string): HistoryInsightsPayload {
  const engine = lang === "nl" ? "motor-orde" : "engine order";
  return makeHistoryInsightsPayload({
    run_id: runId,
    lang,
    // The server words page 1 of the report in the requested language.
    owner: makeOwnerPage(lang === "nl" ? DUTCH_OWNER : {}),
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

test("journey: history titles runs by date and result, opens on the report's page 1, and keeps the title when closed", async ({
  page,
}) => {
  const server = createServer();
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  await expect(page.locator("#historySummary")).toHaveText("2 runs available");
  // Analysed runs get their title prefetched: date, result and level.
  const firstRow = page.locator('[data-run-row="1"][data-run="run-001"]');
  const title = firstRow.locator(".history-row__title");
  await expect(title).toContainText(" · Front-left wheel · Moderate");
  await expect(firstRow.locator(".history-row__subtitle")).toHaveText(
    "Test Hatch · 0:12",
  );
  // The run ID is for the details footer only.
  const list = page.locator("#historyTableBody");
  await expect(list).not.toContainText("run-001");

  await firstRow.locator('[data-run-toggle="details"]').click();
  const details = page.locator(".history-details-card");
  const owner = details.locator(".history-owner");
  await expect(owner.locator(".history-owner__headline")).toHaveText(
    "Likely cause: a wheel or tire problem at the front-left wheel",
  );
  await expect(owner.locator(".history-owner__level")).toHaveText("Moderate");
  await expect(owner).toContainText("What you feel");
  await expect(owner).toContainText("Cheap check first");
  await expect(owner).toContainText("If that doesn't fix it");
  await expect(owner).toContainText("Check the fix");
  await expect(
    owner.locator(
      '.history-car__marker--strongest[data-location-key="front_left_wheel"]',
    ),
  ).toContainText("118 mg");
  await expect(
    owner.locator(
      '.history-car__wheel--highlighted[data-wheel="front_left_wheel"]',
    ),
  ).toHaveCount(1);
  // The level labels stay readable (at least 12 px) on a laptop and a phone.
  const labelPx = () =>
    owner
      .locator(".history-car__marker text")
      .first()
      .evaluate((text) => {
        const svg = (text as SVGTextElement).ownerSVGElement;
        const scale = svg?.getScreenCTM()?.a ?? 0;
        return Number.parseFloat(getComputedStyle(text).fontSize) * scale;
      });
  expect(await labelPx()).toBeGreaterThanOrEqual(12);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(labelPx).toBeGreaterThanOrEqual(12);
  await page.setViewportSize({ width: 1280, height: 800 });
  // The workshop detail waits behind "More details".
  const more = details.locator(".history-more");
  await expect(more).not.toHaveAttribute("open", "");
  await expect(
    more.locator(".history-finding-card--primary"),
  ).not.toBeVisible();
  await more.locator("summary").click();
  await expect(more).toContainText("Wheel order follows road speed.");
  await expect(more).toContainText("Weak engine order.");
  await expect(
    more.locator(
      '.history-heatmap__zone[data-location-key="front_left_wheel"]',
    ),
  ).toContainText("24.0 dB");
  // Only the assigned front-left sensor reported; elsewhere no sensor was fitted.
  const engineBay = more.locator(
    '.history-heatmap__zone[data-location-key="engine_bay"]',
  );
  await expect(engineBay).toContainText("no sensor");
  // What the run checked and what it couldn't, in the PDF's words.
  const checks = more.locator(".history-checks");
  await expect(checks.locator(".history-checks__group--checked")).toContainText(
    "Driveline: no propshaft-order vibration found",
  );
  await expect(
    checks.locator(".history-checks__group--not-checked"),
  ).toContainText(
    "Couldn't checkEngine: no engine RPM — connect an OBD-II adapter",
  );
  // The run ID once, in the footer.
  const footer = details.locator(".history-details-footer");
  await expect(footer).toContainText("Run IDrun-001");
  expect(((await list.textContent()) ?? "").split("run-001")).toHaveLength(2);

  const before = server.insightRequests.length;
  await footer.locator('[data-run-action="load-insights"]').click();
  await expect
    .poll(() => server.insightRequests.length)
    .toBeGreaterThan(before);

  await selectPreference(page, "#languageSelect", "nl");
  await expect(owner.locator(".history-owner__headline")).toHaveText(
    DUTCH_OWNER.headline,
  );
  await expect(title).toContainText(" · Wiel linksvoor · Matig");
  await expect(details).toContainText("Weak motor-orde.");
  await expect(engineBay).toContainText("geen sensor");
  await expect(checks).toContainText(
    "Motor: geen motortoerental — sluit een OBD-II-adapter aan",
  );
  expect(server.insightRequests).toContain("run-001:nl");
  expect(server.insightRequests).toContain("run-002:nl");

  // Closing keeps the run's title; it never falls back to loading.
  await firstRow.locator('[data-run-toggle="details"]').click();
  await expect(details).toHaveCount(0);
  await expect(title).toContainText(" · Wiel linksvoor · Matig");
  await expect(title).not.toContainText("laden");
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
  // The click does not open the run.
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

  const second = page.locator('[data-run-row="1"][data-run="run-002"]');
  await expect(second.locator(".history-row__subtitle")).toHaveText(
    "Not recorded · 0:12",
  );
  await second.locator('[data-run-toggle="details"]').click();
  await page
    .locator('[data-run-action="delete-run"][data-run="run-002"]')
    .click();
  const dialog = page.getByRole("alertdialog");
  // The run is named by its title, as the list shows it.
  await expect(dialog).toContainText(' · Front-left wheel · Moderate"?');
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(second).toHaveCount(0);
  expect(server.deletes).toEqual(["run-002"]);

  // Deleting everything is a quiet action at the end of the list, confirmed.
  server.failDeletes.add("run-003");
  await page.locator(".history-list-footer #deleteAllRunsBtn").click();
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
  await details.locator(".history-more summary").click();
  await expect(details).toContainText("T1 · 12.1 Hz @ 85 km/h");
  await expect(details).toContainText("63–105 km/h");
  await expect(details).toContainText("60–80 km/h");
  await expect(details).toContainText("speed above 20 km/h.");

  await selectPreference(page, "#speedUnitSelect", "mps");
  // The diagnosis reloads, so the server's warnings follow the unit too.
  await expect(details).toContainText("speed above 6 m/s.");
  await expect(details).toContainText("T1 · 12.1 Hz @ 24 m/s");
  await expect(details).toContainText("18–29 m/s");
  await expect(details).toContainText("17–22 m/s");
  await expect(details).not.toContainText("km/h");
  expect(unit).toBe("mps");

  await selectPreference(page, "#languageSelect", "nl");
  await expect(details).toContainText("Weak motor-orde.");
  await expect(details).toContainText("@ 24 m/s");

  await selectPreference(page, "#speedUnitSelect", "kmh");
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

test("journey: a no-fault run, one with a loose sensor and one that could check nothing read as the PDF does", async ({
  page,
}) => {
  const server = createServer();
  server.runs = [run("run-ok"), run("run-loose"), run("run-manual")];
  const noFault: Partial<HistoryInsightsPayload["owner"]> = {
    verdict: "no_fault",
    level: null,
    level_word: null,
    level_meaning: null,
    candidate: null,
    confirm_title: null,
    confirm: null,
    fallback_step: null,
    verify_title: null,
    verify: null,
    felt_title: null,
    felt: null,
    covered_title: "What this test covered",
    covered: "50 km/h (cruise) with a sensor at the front-left wheel.",
    not_covered_title: "Not covered",
    not_covered: ["Speeds below 50 km/h", "Coasting"],
    diagram: {
      zone: null,
      front_label: "FRONT",
      markers: [
        {
          code: "front_left_wheel",
          label: "front-left wheel",
          value: "3.9 mg",
          ratio: 1,
          strongest: true,
        },
      ],
    },
  };
  server.insights = (runId, lang) =>
    makeHistoryInsightsPayload({
      run_id: runId,
      lang,
      duration_s: 15,
      sensor_count_used: 1,
      diagnosis: makeDiagnosis(),
      owner: makeOwnerPage(
        runId === "run-ok" || runId === "run-loose"
          ? {
              ...noFault,
              tone: runId === "run-ok" ? "good" : "caution",
              result: "No significant vibration",
              headline: "No significant vibration found",
              description:
                runId === "run-ok"
                  ? "Nothing stood out in the checks this run could make: wheels/tires."
                  : "Nothing stood out. The rear-left wheel sensor may be loosely mounted; check its mount and record again, because a loose sensor can hide a fault.",
              next_step: "Nothing to fix for what this run checked.",
            }
          : {
              ...noFault,
              tone: "muted",
              result: "No result",
              headline: "No result: this run could not check for a cause",
              description:
                "No vibration stood out, but this run could not check the wheels.",
              next_step:
                "Record again with live speed from GPS or an OBD-II adapter.",
            },
      ),
    });
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  const ok = page.locator('[data-run-row="1"][data-run="run-ok"]');
  await expect(ok.locator(".history-row__title")).toContainText(
    " · No significant vibration",
  );
  await expect(
    page.locator(
      '[data-run-row="1"][data-run="run-manual"] .history-row__title',
    ),
  ).toContainText(" · No result");

  await ok.locator('[data-run-toggle="details"]').click();
  const owner = page.locator(".history-owner");
  await expect(owner).toHaveClass(/history-owner--good/);
  await expect(owner).toContainText("What this test covered");
  await expect(owner).toContainText("Speeds below 50 km/h");
  await expect(owner.locator(".history-owner__level")).toHaveCount(0);

  await page
    .locator('[data-run-toggle="details"][data-run="run-manual"]')
    .click();
  // Never green: a run that checked nothing does not show the car is fine.
  await expect(owner).toHaveClass(/history-owner--muted/);
  await expect(owner).toContainText("Record again with live speed");

  // A loose sensor can hide a fault: amber, the warning color, in both themes.
  await page
    .locator('[data-run-toggle="details"][data-run="run-loose"]')
    .click();
  await expect(owner).toHaveClass(/history-owner--caution/);
  await expect(owner).toContainText("may be loosely mounted");
  const colors = () =>
    owner.locator(".history-owner__verdict").evaluate((box) => {
      const root = getComputedStyle(document.documentElement);
      const probe = document.createElement("div");
      document.body.append(probe);
      const resolve = (token: string) => {
        probe.style.backgroundColor = root.getPropertyValue(token);
        return getComputedStyle(probe).backgroundColor;
      };
      const result = {
        box: getComputedStyle(box).backgroundColor,
        warn: resolve("--pill-warn-bg"),
        ok: resolve("--pill-ok-bg"),
      };
      probe.remove();
      return result;
    });
  const light = await colors();
  expect(light.box).toBe(light.warn);
  expect(light.box).not.toBe(light.ok);
  await page.emulateMedia({ colorScheme: "dark" });
  const dark = await colors();
  expect(dark.box).toBe(dark.warn);
  expect(dark.box).not.toBe(light.box);
});

test("journey: the car diagram's labels never overlap, with a sensor at every location", async ({
  page,
}) => {
  const codes = [
    "front_left_wheel",
    "front_right_wheel",
    "rear_left_wheel",
    "rear_right_wheel",
    "engine_bay",
    "front_subframe",
    "transmission",
    "driveshaft_tunnel",
    "driver_seat",
    "front_passenger_seat",
    "rear_left_seat",
    "rear_center_seat",
    "rear_right_seat",
    "rear_subframe",
    "trunk",
  ];
  const server = createServer();
  server.runs = [run("run-full")];
  server.insights = (runId, lang) =>
    makeHistoryInsightsPayload({
      run_id: runId,
      lang,
      diagnosis: makeDiagnosis(),
      owner: makeOwnerPage({
        diagram: {
          zone: "rear_axle",
          front_label: "FRONT",
          markers: codes.map((code, index) => ({
            code,
            label: code,
            value: `${(10 + index * 7.3).toFixed(1)} mg`,
            ratio: (index % 3) / 2,
            strongest: index === 12,
          })),
        },
      }),
    });
  await bootWithHistory(page, server);
  await openHistoryTab(page);
  await page
    .locator('[data-run-toggle="details"][data-run="run-full"]')
    .click();
  const car = page.locator(".history-owner .history-car");
  await expect(car.locator(".history-car__marker")).toHaveCount(codes.length);
  // The rendered text's real boxes, in the diagram's own units.
  const problems = () =>
    car.evaluate((svg) => {
      const view = (svg as SVGSVGElement).viewBox.baseVal;
      const boxes = [
        ...svg.querySelectorAll<SVGTextElement>(".history-car__marker text"),
      ].map((text) => ({
        code: text.parentElement?.getAttribute("data-location-key"),
        box: text.getBBox(),
      }));
      const found: string[] = [];
      boxes.forEach(({ code, box }, index) => {
        if (
          box.x < view.x ||
          box.x + box.width > view.x + view.width ||
          box.y < view.y ||
          box.y + box.height > view.y + view.height
        ) {
          found.push(`${code} clipped`);
        }
        for (const other of boxes.slice(index + 1)) {
          const b = other.box;
          if (
            box.x < b.x + b.width &&
            b.x < box.x + box.width &&
            box.y < b.y + b.height &&
            b.y < box.y + box.height
          ) {
            found.push(`${code}/${other.code}`);
          }
        }
      });
      return found;
    });
  expect(await problems()).toEqual([]);
  await expect(car.locator(".history-car__leader")).not.toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(car).toBeVisible();
  expect(await problems()).toEqual([]);
});
