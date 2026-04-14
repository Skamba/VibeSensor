import { expect, test } from "@playwright/test";

import type { HistoryEntry, HistoryInsightsPayload } from "../src/transport/http_models";
import type { RunDetail } from "../src/app/ui_app_state";
import {
  renderHistoryEmptyState,
  renderHistoryTable,
} from "../src/app/views/history_table_view";
import {
  findByAttribute,
  findByClass,
  installFakeDomGlobals,
  type FakeElement,
  FakeHTMLElement,
} from "./dom_render_test_support";

let restoreDom = () => undefined;

test.beforeEach(() => {
  restoreDom = installFakeDomGlobals();
});

test.afterEach(() => {
  restoreDom();
  restoreDom = () => undefined;
});

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function historyListRun(runId: string): HistoryEntry {
  return {
    run_id: runId,
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    sample_count: 2048,
    status: "complete",
    car_name: "Track Car",
    error_message: null,
  } as HistoryEntry;
}

function populatedInsights(runId: string): HistoryInsightsPayload {
  return {
    run_id: runId,
    status: "complete",
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    duration_s: 12.3,
    sensor_count_used: 2,
    most_likely_origin: {
      suspected_source: "wheel_tire",
      location: "front-right wheel",
      speed_band: "80-100 km/h",
      explanation: "Most likely wheel-tire contribution.",
    },
    findings: [
      {
        suspected_source: "wheel_tire",
        confidence: 0.92,
        confidence_pct: "92%",
        confidence_tone: "success",
        strongest_location: "front-right wheel",
        strongest_speed_band: "80-100 km/h",
        frequency_hz_or_order: 32,
        evidence_summary: "Front-right wheel imbalance",
      },
      {
        suspected_source: "driveline",
        confidence: 0.61,
        confidence_pct: "61%",
        confidence_tone: "warn",
        strongest_location: "driveshaft tunnel",
        strongest_speed_band: "60-80 km/h",
        frequency_hz_or_order: 18.5,
        evidence_summary: "Secondary driveline contribution",
      },
    ],
    warnings: [
      { code: "speed-gap", severity: "warn", title: "history.warning.speed_gap", detail: "Gap" },
    ],
    sensor_intensity_by_location: [
      { location: "front-right wheel", p95_intensity_db: 32 },
      { location: "driveshaft tunnel", p95_intensity_db: 25.5 },
    ],
  } as HistoryInsightsPayload;
}

function defaultDetail(detail: Partial<RunDetail>): RunDetail {
  return {
    preview: null,
    previewLoading: false,
    previewError: "",
    insights: null,
    insightsLoading: false,
    insightsError: "",
    pdfLoading: false,
    pdfError: "",
    ...detail,
  };
}

function expectSingleByAttribute(
  root: FakeElement,
  attributeName: string,
  expectedValue: string,
): FakeElement {
  const matches = findByAttribute(root, attributeName, expectedValue);
  expect(matches, `Expected exactly one [${attributeName}="${expectedValue}"] element`).toHaveLength(1);
  return matches[0];
}

test("renderHistoryEmptyState builds an actionable empty-state row", () => {
  const container = new FakeHTMLElement("TBODY") as unknown as HTMLElement;

  renderHistoryEmptyState(container, {
    t: testTranslation,
  });

  const root = container as unknown as FakeElement;
  expect(findByAttribute(root, "colspan", "4")).toHaveLength(1);
  expect(findByClass(root, "empty-state")).toHaveLength(1);
  expect(findByClass(root, "empty-state__title")[0].textContent).toBe("history.empty.title");
  expect(findByClass(root, "empty-state__body")[0].textContent).toBe("history.empty.body");
  expect(findByAttribute(root, "data-inline-state-action", "open-live")).toHaveLength(1);
});

test("renderHistoryTable builds rows and expanded details from typed history models", () => {
  const container = new FakeHTMLElement("TBODY") as unknown as HTMLElement;

  renderHistoryTable(container, {
    runs: [historyListRun("run-001")],
    expandedRunId: "run-001",
    runDetailsById: {
      "run-001": defaultDetail({
        preview: populatedInsights("run-001") as RunDetail["preview"],
        insights: populatedInsights("run-001") as RunDetail["insights"],
      }),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
    historyExportUrl: (runId) => `/api/history/${runId}/export`,
  });

  const root = container as unknown as FakeElement;
  const row = expectSingleByAttribute(root, "data-run-row", "1");
  const toggle = expectSingleByAttribute(root, "data-run-toggle", "details");
  const zone = expectSingleByAttribute(root, "data-location-key", "front-right wheel");
  const rawExport = expectSingleByAttribute(root, "data-run-action", "download-raw");
  const mainColumn = findByClass(root, "history-main-column");

  expect(row.getAttribute("data-run")).toBe("run-001");
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(findByClass(root, "history-details-row")).toHaveLength(1);
  expect(mainColumn).toHaveLength(1);
  expect(findByClass(mainColumn[0], "history-details-footer")).toHaveLength(1);
  expect(findByClass(root, "history-warning-banner")).toHaveLength(1);
  expect(zone.textContent).toContain("32.0 dB");
  expect(findByClass(root, "history-findings-chip__label").map((label) => label.textContent))
    .toContain("history.findings_signature");
  expect(rawExport.getAttribute("href")).toBe("/api/history/run-001/export");
  expect(rawExport.getAttribute("download")).toBe("run-001.zip");
});
