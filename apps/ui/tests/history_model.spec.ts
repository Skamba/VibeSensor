import { expect, test } from "vitest";
import type { HistoryEntry, HistoryInsightsPayload } from "../src/api/types";
import {
  buildDetails,
  buildHeatmap,
  buildRow,
  EMPTY_RUN_DETAIL,
  heatColor,
  heatmapLocationKey,
  normalizeUnit,
  type RunDetail,
  sourceLabel,
} from "../src/pages/history/history_model";
import {
  makeHistoryFinding,
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
} from "./history_payload_test_support";

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
    lifecycle: {
      stage: "post_analysis_ready",
      raw_capture: "not_recorded",
      whole_run_artifacts: "ready",
      post_analysis: "ready",
      report: "ready",
    },
  } as HistoryEntry;
}

function populatedInsights(runId: string): HistoryInsightsPayload {
  return makeHistoryInsightsPayload({
    run_id: runId,
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
      makeHistoryFinding({
        suspected_source: "wheel_tire",
        confidence: 0.92,
        confidence_pct: "92%",
        confidence_tone: "success",
        strongest_location: "front-right wheel",
        strongest_speed_band: "80-100 km/h",
        frequency_hz_or_order: 32,
        evidence_summary: "Front-right wheel imbalance",
      }),
      makeHistoryFinding({
        finding_id: "finding-2",
        suspected_source: "driveline",
        confidence: 0.61,
        confidence_pct: "61%",
        confidence_tone: "warn",
        strongest_location: "driveshaft tunnel",
        strongest_speed_band: "60-80 km/h",
        frequency_hz_or_order: 18.5,
        evidence_summary: "Secondary driveline contribution",
      }),
      makeHistoryFinding({
        finding_id: "finding-3",
        suspected_source: "engine",
        confidence: 0.44,
        confidence_pct: "44%",
        confidence_tone: "neutral",
        strongest_location: "engine bay",
        strongest_speed_band: "idle",
        frequency_hz_or_order: 12.5,
        evidence_summary: "Engine harmonics remain visible",
      }),
      makeHistoryFinding({
        finding_id: "finding-4",
        suspected_source: "body_resonance",
        confidence: 0.27,
        confidence_pct: "27%",
        confidence_tone: "neutral",
        strongest_location: "driver seat",
        strongest_speed_band: "100-120 km/h",
        frequency_hz_or_order: 9.2,
        evidence_summary: "Cabin resonance remains possible",
      }),
    ],
    warnings: [
      {
        applies_to: "run",
        code: "speed-gap",
        severity: "warn",
        title: "history.warning.speed_gap",
        detail: "Gap",
      },
      {
        applies_to: "run",
        code: "speed-gap",
        severity: "warn",
        title: "history.warning.speed_gap",
        detail: "Gap",
      },
    ],
    sensor_intensity_by_location: [
      makeLocationIntensityRow({
        location: "front-right wheel",
        p95_intensity_db: 32,
      }),
      makeLocationIntensityRow({
        location: "driveshaft tunnel",
        p95_intensity_db: 25.5,
      }),
      makeLocationIntensityRow({
        location: "custom bracket",
        p95_intensity_db: 21.1,
      }),
    ],
  });
}

function defaultDetail(detail: Partial<RunDetail>): RunDetail {
  return { ...EMPTY_RUN_DETAIL, ...detail };
}

const f = {
  t: testTranslation,
  fmt: (value: number, digits = 0) => Number(value).toFixed(digits),
  fmtTs: (iso: string) => iso,
  formatInt: (value: number) => String(value),
};

test("builds the row summary and the expanded diagnosis from raw insights", () => {
  const run = historyListRun("run-001");
  run.lifecycle = { ...run.lifecycle!, raw_capture: "missing" };
  const detail = defaultDetail({
    preview: populatedInsights("run-001"),
    insights: populatedInsights("run-001"),
  });
  const row = buildRow(run, detail, true, f);
  expect(row.chips.map((chip) => chip.text)).toEqual([
    "history.row_status.complete",
  ]);
  expect(row.headline).toBe("history.source.wheel_tire");
  expect(row.meta).toBe(
    'report.confidence:{"value":"92%"} · history.summary_size: 12.3 s · history.summary_sensor_count: 2',
  );
  expect(row.reportPendingHint).toBeNull();

  const details = buildDetails(run, detail, f);
  if (details.insights.kind !== "findings") {
    throw new Error("expected findings");
  }
  expect(details.insights.primary).toMatchObject({
    headline: "history.source.wheel_tire",
    confidence: 'report.confidence:{"value":"92%"}',
    signature: "32.0 Hz",
    nextStepLabel: "history.findings_next_step_label",
  });
  expect(details.insights.visibleSecondary).toHaveLength(2);
  expect(details.insights.hiddenSecondary).toHaveLength(1);
  // Raw-capture warning first, then insight warnings without duplicates.
  expect(details.warnings).toEqual([
    {
      severity: "warn",
      title: "history.raw_capture_missing_title",
      detail: "history.raw_capture_missing_detail",
    },
    { severity: "warn", title: "history.warning.speed_gap", detail: "Gap" },
  ]);
  if (details.heatmap.kind !== "zones") {
    throw new Error("expected heatmap zones");
  }
  expect(
    details.heatmap.zones.find((zone) => zone.key === "front-right wheel"),
  ).toMatchObject({
    label: "front-right wheel",
    valueLabel: "32.0 dB",
    strongest: true,
  });
  expect(details.heatmap.extras).toEqual(["custom bracket · 21.1 dB"]);
});

test("keeps loading and error state in the models", () => {
  const run = historyListRun("run-002");
  const detail = defaultDetail({
    previewLoading: true,
    insightsError: "history.error.insights",
    pdfLoading: true,
  });
  const row = buildRow(run, detail, true, f);
  expect(row.headline).toBe("history.row_summary_loading");
  expect(row.meta).toBe("history.summary_size: 12.0 s");
  expect(row.pdfLabel).toBe("history.generating_pdf");
  expect(row.pdfLoading).toBe(true);
  const details = buildDetails(run, detail, f);
  expect(details.insights).toEqual({
    kind: "state",
    message: "history.loading_insights",
  });
  expect(details.heatmap).toEqual({
    kind: "state",
    message: "history.loading_preview",
    tone: "subtle",
  });
  expect(details.insightsError).toBe("history.error.insights");
  expect(details.reloadLabel).toBe("history.load_insights");
});

test("keeps the PDF pending until the report is ready", () => {
  const analyzing: HistoryEntry = {
    ...historyListRun("run-003"),
    status: "analyzing",
    lifecycle: {
      stage: "post_analysis_pending",
      raw_capture: "not_recorded",
      whole_run_artifacts: "pending",
      post_analysis: "pending",
      report: "pending",
    },
  };
  const row = buildRow(
    analyzing,
    defaultDetail({ preview: populatedInsights("run-003") }),
    false,
    f,
  );
  expect(row.chips[0].text).toBe("history.row_status.preview_ready");
  expect(row.reportPendingHint).toBe("history.quick_report_pending");

  const degraded: HistoryEntry = {
    ...historyListRun("run-003b"),
    error_message: "analysis crashed",
    lifecycle: {
      stage: "post_analysis_degraded",
      raw_capture: "not_recorded",
      whole_run_artifacts: "degraded",
      post_analysis: "degraded",
      report: "degraded",
    },
  };
  const degradedRow = buildRow(degraded, EMPTY_RUN_DETAIL, false, f);
  expect(degradedRow.chips).toEqual([
    { key: "status", text: "history.row_status.error", tone: "bad" },
    { key: "error-message", text: "analysis crashed", tone: "muted" },
  ]);
  expect(degradedRow.reportPendingHint).toBe("history.quick_report_pending");
});

test("explains degraded raw capture", () => {
  const run = historyListRun("run-004");
  run.lifecycle = { ...run.lifecycle!, raw_capture: "degraded" };
  run.raw_capture_finalize = {
    status: "timeout",
    queue_depth: 3,
    error_summary: "raw capture finalize timed out",
  };
  const details = buildDetails(
    run,
    defaultDetail({ preview: populatedInsights("run-004") }),
    f,
  );
  expect(details.warnings[0]).toEqual({
    severity: "warn",
    title: "history.raw_capture_degraded_title",
    detail:
      'history.raw_capture_degraded_timeout_detail:{"queueDepth":3,"errorSummary":"raw capture finalize timed out"}',
  });
});

test("an inconclusive top finding says so instead of naming a source", () => {
  const insights = populatedInsights("run-005");
  insights.findings = [
    makeHistoryFinding({ suspected_source: "baseline_noise", confidence: 0.2 }),
  ];
  const run = historyListRun("run-005");
  const detail = defaultDetail({ preview: insights });
  expect(buildRow(run, detail, false, f).headline).toBe(
    "history.row_source_inconclusive",
  );
  const details = buildDetails(run, detail, f);
  expect(details.insights).toMatchObject({
    kind: "findings",
    primary: {
      headline: "history.inconclusive_title",
      nextStep: "history.inconclusive_next_step",
    },
  });
});

test("labels sources, folding unknown keys into title case", () => {
  expect(sourceLabel("wheel_tire", testTranslation)).toBe(
    "history.source.wheel_tire",
  );
  expect(sourceLabel("rear_axle-hub", testTranslation)).toBe("Rear Axle Hub");
  expect(sourceLabel("Custom Thing", testTranslation)).toBe("Custom Thing");
  expect(sourceLabel("", testTranslation)).toBe("report.missing");
});

test("maps location names onto heatmap positions and scales the colour", () => {
  expect(heatmapLocationKey("Front_Left Wheel")).toBe("front-left wheel");
  expect(heatmapLocationKey("Drive shaft tunnel")).toBe("driveshaft tunnel");
  expect(heatmapLocationKey("roof")).toBe("roof");
  expect(normalizeUnit(5, 0, 10)).toBe(0.5);
  expect(normalizeUnit(7, 7, 7)).toBe(0.5);
  expect(normalizeUnit(0, 0, 0)).toBe(0);
  expect(heatColor(0)).toBe("hsl(212 76% 48%)");
  expect(heatColor(1)).toBe("hsl(22 76% 48%)");
  const single = buildHeatmap(
    makeHistoryInsightsPayload({
      sensor_intensity_by_location: [
        makeLocationIntensityRow({ location: "Trunk", p95_intensity_db: 10 }),
      ],
    }),
    f,
  );
  if (single.kind !== "zones") {
    throw new Error("expected zones");
  }
  expect(single.zones.find((zone) => zone.key === "trunk")).toMatchObject({
    label: "Trunk",
    strongest: true,
    accent: { fillPercent: 50 },
  });
});
