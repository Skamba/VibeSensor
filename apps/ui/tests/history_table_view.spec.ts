import { expect, test } from "vitest";
import type { HistoryEntry, HistoryInsightsPayload } from "../src/api/types";
import type { RunDetail } from "../src/app/ui_app_state";
import { buildHistoryTableRowsViewModel } from "../src/app/views/history_table_presenters";

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

test("buildHistoryTableRowsViewModel builds rows and expanded details from typed history models", () => {
  const rows = buildHistoryTableRowsViewModel({
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

  expect(rows).toHaveLength(1);
  const row = rows[0];

  expect(row.runId).toBe("run-001");
  expect(row.isExpanded).toBe(true);
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.complete");
  expect(row.toggleLabel).toBe("history.close_diagnosis");
  expect(row.details?.warnings).toHaveLength(1);
  expect(row.details?.heatmap.zones.find((zone) => zone.key === "front-right wheel")?.valueLabel)
    .toBe("32.0 dB");
  expect(row.details?.insights.primary?.chips.map((chip) => chip.label))
    .toContain("history.findings_signature");
  expect(row.details?.footerEyebrow).toBe("history.run_actions_title");
  expect(row.details?.exportLabel).toBe("history.export");
  expect(row.details?.deleteLabel).toBe("history.delete");
});

test("buildHistoryTableRowsViewModel keeps collapsed quick-report context in the row summary", () => {
  const rows = buildHistoryTableRowsViewModel({
    runs: [historyListRun("run-001")],
    expandedRunId: null,
    runDetailsById: {
      "run-001": defaultDetail({
        preview: populatedInsights("run-001") as RunDetail["preview"],
      }),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
    historyExportUrl: (runId) => `/api/history/${runId}/export`,
  });

  expect(rows).toHaveLength(1);
  const row = rows[0];

  expect(row.isExpanded).toBe(false);
  expect(row.details).toBeNull();
  expect(row.summaryHeadline).toBe("history.source.wheel_tire");
  expect(row.summaryMeta?.includes("report.confidence")).toBe(true);
  expect(row.collapsedAction.pdfLabel).toBe("history.generate_pdf");
});
