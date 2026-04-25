import { expect, test } from "vitest";
import type { HistoryEntry, HistoryInsightsPayload } from "../src/api/types";
import { buildHistoryTableRowsViewModel } from "../src/app/views/history_table_presenters";
import type { RunDetail } from "../src/app/ui_app_state";

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
      {
        suspected_source: "engine",
        confidence: 0.44,
        confidence_pct: "44%",
        confidence_tone: "neutral",
        strongest_location: "engine bay",
        strongest_speed_band: "idle",
        frequency_hz_or_order: 12.5,
        evidence_summary: "Engine harmonics remain visible",
      },
      {
        suspected_source: "body_resonance",
        confidence: 0.27,
        confidence_pct: "27%",
        confidence_tone: "neutral",
        strongest_location: "driver seat",
        strongest_speed_band: "100-120 km/h",
        frequency_hz_or_order: 9.2,
        evidence_summary: "Cabin resonance remains possible",
      },
    ],
    warnings: [
      { code: "speed-gap", severity: "warn", title: "history.warning.speed_gap", detail: "Gap" },
      { code: "speed-gap", severity: "warn", title: "history.warning.speed_gap", detail: "Gap" },
    ],
    sensor_intensity_by_location: [
      { location: "front-right wheel", p95_intensity_db: 32 },
      { location: "driveshaft tunnel", p95_intensity_db: 25.5 },
      { location: "custom bracket", p95_intensity_db: 21.1 },
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

test("history table presenter builds typed diagnosis models from raw insights", () => {
  const run = historyListRun("run-001");
  run.artifact_availability = {
    raw_capture: "missing",
    whole_run_artifacts: "available",
  };
  const rows = buildHistoryTableRowsViewModel({
    runs: [run],
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
  });

  expect(rows).toHaveLength(1);
  const row = rows[0];
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.complete");
  expect(row.summaryHeadline).toBe("history.source.wheel_tire");
  expect(row.summaryMeta).toContain('report.confidence:{"value":"92%"}');
  expect(row.summaryMeta).toContain("history.summary_size: 12.3 s");
  expect(row.summaryMeta).toContain("history.summary_sensor_count: 2");
  expect(row.details?.insights.primary).toMatchObject({
    headline: "history.source.wheel_tire",
    confidence: 'report.confidence:{"value":"92%"}',
    signature: "32.0 Hz",
    nextStepLabel: "history.findings_next_step_label",
  });
  expect(row.details?.insights.visibleSecondary).toHaveLength(2);
  expect(row.details?.insights.hiddenSecondary).toHaveLength(1);
  expect(row.details?.warnings).toEqual([
    {
      severity: "warn",
      title: "history.raw_capture_missing_title",
      detail: "history.raw_capture_missing_detail",
    },
    {
      severity: "warn",
      title: "history.warning.speed_gap",
      detail: "Gap",
    },
  ]);
  const frontRightZone = row.details?.heatmap.zones.find((zone) => zone.key === "front-right wheel");
  expect(frontRightZone).toMatchObject({
    label: "front-right wheel",
    valueLabel: "32.0 dB",
    strongest: true,
  });
  expect(row.details?.heatmap.extras).toContain("custom bracket · 21.1 dB");
});

test("history table presenter keeps loading and error state outside the renderer", () => {
  const run = historyListRun("run-002");
  const rows = buildHistoryTableRowsViewModel({
    runs: [run],
    expandedRunId: "run-002",
    runDetailsById: {
      "run-002": defaultDetail({
        previewLoading: true,
        insightsError: "history.error.insights",
        pdfLoading: true,
      }),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });

  const row = rows[0];
  expect(row.summaryHeadline).toBe("history.row_summary_loading");
  expect(row.summaryMeta).toBe("history.summary_size: 12.0 s");
  expect(row.collapsedAction).toEqual({
    hintText: null,
    pdfLabel: "history.generating_pdf",
    pdfLoading: true,
  });
  expect(row.details?.insights.stateMessage).toBe("history.loading_insights");
  expect(row.details?.heatmap).toMatchObject({
    stateMessage: "history.loading_preview",
    stateTone: "subtle",
  });
  expect(row.details?.insightsError).toBe("history.error.insights");
});

test("history table presenter keeps PDF pending until analysis completes", () => {
  const run = {
    ...historyListRun("run-003"),
    status: "analyzing" as const,
  };
  const rows = buildHistoryTableRowsViewModel({
    runs: [run],
    expandedRunId: null,
    runDetailsById: {
      "run-003": defaultDetail({
        preview: populatedInsights("run-003") as RunDetail["preview"],
      }),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });

  const row = rows[0];
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.preview_ready");
  expect(row.collapsedAction).toEqual({
    hintText: "history.quick_report_pending",
    pdfLabel: null,
    pdfLoading: false,
  });
});

test("history table presenter shows degraded raw capture warning details", () => {
  const run = historyListRun("run-004");
  run.artifact_availability = {
    raw_capture: "degraded",
    whole_run_artifacts: "available",
  };
  run.raw_capture_finalize = {
    status: "timeout",
    queue_depth: 3,
    error_summary: "raw capture finalize timed out",
  };
  const rows = buildHistoryTableRowsViewModel({
    runs: [run],
    expandedRunId: "run-004",
    runDetailsById: {
      "run-004": defaultDetail({
        preview: populatedInsights("run-004") as RunDetail["preview"],
      }),
    },
    t: testTranslation,
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });

  expect(rows[0].details?.warnings?.[0]).toEqual({
    severity: "warn",
    title: "history.raw_capture_degraded_title",
    detail:
      'history.raw_capture_degraded_timeout_detail:{"queueDepth":3,"errorSummary":"raw capture finalize timed out"}',
  });
});
