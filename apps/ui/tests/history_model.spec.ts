import { expect, test } from "vitest";
import type { HistoryEntry, HistoryInsightsPayload } from "../src/api/types";
import { type Lang, setLanguage, translate } from "../src/i18n";
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
  speedBandLabel,
} from "../src/pages/history/history_model";
import {
  makeDiagnosis,
  makeHistoryFinding,
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
} from "./history_payload_test_support";

const UNIT_LABELS: Record<string, string> = {
  "speed.unit.kmh": "km/h",
  "speed.unit.mps": "m/s",
};

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : (UNIT_LABELS[key] ?? key);
}

function historyListRun(runId: string): HistoryEntry {
  return {
    run_id: runId,
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    raw_sample_count: 9600,
    status: "complete",
    car_name: "Track Car",
    error_message: null,
    lifecycle: {
      stage: "post_analysis_ready",
      raw_capture: "not_recorded",
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
    diagnosis: makeDiagnosis({
      verdict: "fault",
      confidence_level: "strong",
      finding_id: "finding-1",
      source: "wheel/tire",
      location: "Front Right Wheel",
      zone: "front_right_wheel",
      order_code: "T1",
      frequency_hz: 12.1,
      reference_speed_kmh: 85,
      speed_min_kmh: 63,
      speed_max_kmh: 105,
    }),
    most_likely_origin: {
      suspected_source: "wheel/tire",
      location: "Front Right Wheel",
      speed_band: "80-100 km/h",
      explanation: "Most likely wheel-tire contribution.",
    },
    findings: [
      makeHistoryFinding({
        suspected_source: "wheel/tire",
        confidence: 0.92,
        confidence_level: "strong",
        strongest_location: "Front Right Wheel",
        strongest_speed_band: "80-100 km/h",
        frequency_hz_or_order: 32,
        evidence_summary: "Front-right wheel imbalance",
      }),
      makeHistoryFinding({
        finding_id: "finding-2",
        suspected_source: "driveline",
        confidence: 0.61,
        confidence_level: "moderate",
        strongest_location: "Driveshaft Tunnel",
        strongest_speed_band: "60-80 km/h",
        frequency_hz_or_order: 18.5,
        evidence_summary: "Secondary driveline contribution",
      }),
      makeHistoryFinding({
        finding_id: "finding-3",
        suspected_source: "engine",
        confidence: 0.44,
        confidence_level: "moderate",
        strongest_location: "Engine Bay",
        strongest_speed_band: "idle",
        frequency_hz_or_order: 12.5,
        evidence_summary: "Engine harmonics remain visible",
      }),
      makeHistoryFinding({
        finding_id: "finding-4",
        suspected_source: "body resonance",
        confidence: 0.27,
        confidence_level: "weak",
        strongest_location: "Driver Seat",
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
        location: "Front Right Wheel",
        p95_intensity_db: 32,
      }),
      makeLocationIntensityRow({
        location: "Driveshaft Tunnel",
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
  speedUnit: "kmh" as const,
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
    'history.confidence:{"level":"history.confidence_level.strong"} · history.summary_size: 12.3 s · history.summary_sensor_count: 2',
  );
  expect(row.reportPendingHint).toBeNull();
  expect(row.rawSampleCount).toBe("9600");
  expect(
    buildRow({ ...run, raw_sample_count: null }, detail, true, f)
      .rawSampleCount,
  ).toBe("--");

  const details = buildDetails(run, detail, f);
  if (details.insights.kind !== "findings") {
    throw new Error("expected findings");
  }
  expect(details.insights.primary).toMatchObject({
    headline: "history.source.wheel_tire",
    confidence:
      'history.confidence:{"level":"history.confidence_level.strong"} — history.confidence_meaning.strong',
    signature: "T1 · 12.1 Hz @ 85 km/h",
    explanation: "Front-right wheel imbalance",
    nextStepLabel: "history.findings_next_step_label",
    nextStep:
      'history.findings_next_step:{"location":"history.zone.front_right_wheel"}',
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
    details.heatmap.zones.find((zone) => zone.key === "front_right_wheel"),
  ).toMatchObject({
    // Translated from the location code, not the server's English label.
    label: "location.front_right_wheel",
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

test("a run without a fault says so and covers what was driven", () => {
  const insights = populatedInsights("run-005");
  insights.diagnosis = makeDiagnosis();
  insights.speed_stats = { ...insights.speed_stats, min_kmh: 50, max_kmh: 118 };
  const run = historyListRun("run-005");
  const detail = defaultDetail({ preview: insights });
  const row = buildRow(run, detail, false, f);
  expect(row.headline).toBe("history.verdict.no_fault");
  expect(row.meta).toBe(
    "history.summary_size: 12.3 s · history.summary_sensor_count: 2",
  );
  const details = buildDetails(run, detail, f);
  expect(details.insights).toMatchObject({
    kind: "findings",
    primary: {
      headline: "history.verdict.no_fault",
      confidence: "",
      chips: [
        { label: "history.covered_speeds", value: "50–118 km/h" },
        { label: "history.summary_sensor_count", value: "2" },
      ],
      nextStep: null,
    },
    visibleSecondary: [],
  });
});

type SourceChecks = HistoryInsightsPayload["diagnosis"]["source_checks"];

/** The expanded diagnosis in real catalog text, so History reads like the PDF. */
function checkedInsights(
  verdict: "fault" | "no_fault",
  sourceChecks: SourceChecks,
  language: Lang = "en",
  conditions: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]> = {},
) {
  const insights = populatedInsights("run-010");
  const base = makeDiagnosis();
  insights.diagnosis = makeDiagnosis(
    verdict === "fault"
      ? {
          verdict,
          confidence_level: "strong",
          finding_id: "finding-1",
          source: "wheel/tire",
          zone: "front_left_wheel",
          source_checks: sourceChecks,
        }
      : { source_checks: sourceChecks },
  );
  insights.diagnosis.conditions = { ...base.conditions, ...conditions };
  const details = buildDetails(
    historyListRun("run-010"),
    defaultDetail({ preview: insights }),
    { ...f, t: (key, vars) => translate(language, key, vars) },
  );
  if (details.insights.kind !== "findings") {
    throw new Error("expected findings");
  }
  return details.insights;
}

test("a no-fault run names only what it could check and lists what it couldn't, as the PDF does", async () => {
  const sourceChecks: SourceChecks = [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    {
      source: "driveline",
      status: "ruled_out_estimated",
      reason: "estimated_final_drive",
    },
    { source: "engine", status: "not_testable", reason: "no_engine_reference" },
  ];
  const insights = checkedInsights("no_fault", sourceChecks, "en", {
    tire_circumference_m: 1.984,
    tire_provenance: "user_confirmed",
    final_drive_ratio: 3.15,
    final_drive_provenance: "family_default",
  });
  expect(insights.primary?.explanation).toBe(
    "Nothing stood out in the checks this run could make: wheels/tires and driveline (against an estimated final drive). Not checked, so not shown to be fine: engine.",
  );
  expect(insights.checks).toEqual({
    checkedTitle: "Checked",
    checked: [
      {
        label: "Wheel / Tire",
        detail: "no once- or twice-per-wheel-turn vibration found",
      },
      {
        label: "Driveline",
        detail:
          "checked only against a car-library estimate of the final drive, so not conclusive — enter the exact ratio if you know it.",
      },
    ],
    notCheckedTitle: "Couldn't check",
    notChecked: [
      {
        label: "Engine",
        detail:
          "no engine RPM — connect an OBD-II adapter, or add the top-gear ratio to the car (optional).",
      },
    ],
    referencesTitle: "Car references",
    references: [
      {
        label: "Tire size",
        detail: "circumference 1.984 m (entered by you)",
      },
      {
        label: "Final drive",
        detail: "3.15 (car library, model-family estimate)",
      },
      { label: "Top gear ratio", detail: "not provided" },
      { label: "Engine RPM", detail: "not available" },
    ],
  });

  await setLanguage("nl");
  try {
    const dutch = checkedInsights("no_fault", sourceChecks, "nl", {
      final_drive_ratio: 3.15,
      final_drive_provenance: "family_default",
    });
    expect(dutch.primary?.explanation).toBe(
      "Niets viel op bij de controles die deze rit kon doen: wielen/banden en aandrijflijn (met een geschatte eindoverbrenging). Niet gecontroleerd, dus niet aangetoond dat het in orde is: motor.",
    );
    expect(dutch.checks.notCheckedTitle).toBe("Niet te controleren");
    expect(dutch.checks.references[1]).toEqual({
      label: "Eindoverbrenging",
      detail: "3.15 (autobibliotheek, schatting voor de modelreeks)",
    });
  } finally {
    await setLanguage("en");
  }
});

test("a no-fault run without a tire size does not suggest the car is fine", () => {
  const insights = checkedInsights(
    "no_fault",
    ["wheel/tire", "driveline", "engine"].map((source) => ({
      source,
      status: "not_testable" as const,
      reason: "no_tire_reference" as const,
    })),
  );
  expect(insights.primary?.explanation).toBe(
    "No vibration stood out, but this run could not check the wheels, driveline or engine against their rhythms, so it does not show that they are fine.",
  );
  expect(insights.checks.checked).toEqual([]);
  expect(insights.checks.notChecked.map((line) => line.detail)).toEqual([
    "no tire size — add it to the car in Settings.",
    "no tire size — add it to the car in Settings.",
    "no tire size — connect an OBD-II adapter to measure RPM, or add the tire size to the car.",
  ]);
});

test("a fault run lists the matching source as checked and states the top-gear assumption", () => {
  const insights = checkedInsights(
    "fault",
    [
      { source: "wheel/tire", status: "candidate", reason: null },
      {
        source: "driveline",
        status: "not_testable",
        reason: "no_drive_reference",
      },
      {
        source: "engine",
        status: "ruled_out_estimated",
        reason: "top_gear_assumed",
      },
    ],
    "en",
    { rpm_source: "estimated_top_gear" },
  );
  expect(insights.checks.checked).toEqual([
    { label: "Wheel / Tire", detail: "a matching vibration was found" },
    {
      label: "Engine",
      detail:
        "checked in top gear only: engine RPM was estimated from speed assuming top gear, so lower gears were not checked — an OBD-II adapter measures RPM in every gear.",
    },
  ]);
  expect(insights.checks.references[3]).toEqual({
    label: "Engine RPM",
    detail: "not measured; estimated from speed assuming top gear",
  });
  expect(insights.checks.notChecked).toEqual([
    {
      label: "Driveline",
      detail:
        "no final-drive ratio — add it to the car in Settings if you know it (optional).",
    },
  ]);
});

test("weak evidence hedges the best candidate and asks for a new recording", () => {
  const insights = populatedInsights("run-006");
  insights.diagnosis = makeDiagnosis({
    verdict: "weak_evidence",
    confidence_level: "weak",
    finding_id: "finding-1",
    source: "wheel/tire",
    zone: "front_axle",
  });
  const run = historyListRun("run-006");
  const detail = defaultDetail({ preview: insights });
  expect(buildRow(run, detail, false, f).headline).toBe(
    "history.verdict.weak_evidence",
  );
  const details = buildDetails(run, detail, f);
  expect(details.insights).toMatchObject({
    kind: "findings",
    primary: {
      headline: "history.verdict.weak_evidence",
      tone: "neutral",
      explanation:
        'history.verdict.weak_body:{"source":"history.source.wheel_tire","location":"history.zone.front_axle"}',
      nextStepLabel: "history.recapture_label",
      nextStep:
        'history.recapture_recipe:{"from":"50","to":"120","unit":"km/h"}',
    },
  });
});

test("a wheel fault felt only in the cabin names no wheel and asks for wheel sensors", () => {
  const cabinOnly = (verdict: "fault" | "weak_evidence") => {
    const insights = populatedInsights("run-008");
    insights.diagnosis = makeDiagnosis({
      verdict,
      confidence_level: verdict === "fault" ? "moderate" : "weak",
      finding_id: "finding-1",
      source: "wheel/tire",
      location: "Driver Seat",
      zone: "driver_seat",
    });
    const details = buildDetails(
      historyListRun("run-008"),
      defaultDetail({ preview: insights }),
      f,
    );
    if (details.insights.kind !== "findings") {
      throw new Error("expected findings");
    }
    return details.insights.primary;
  };
  expect(cabinOnly("fault")).toMatchObject({
    nextStepLabel: "history.findings_next_step_label",
    nextStep: "history.findings_next_step_locate_wheel",
  });
  expect(cabinOnly("weak_evidence")).toMatchObject({
    explanation:
      'history.verdict.weak_body:{"source":"history.source.wheel_tire","location":"history.zone.unlocated_wheel:{\\"location\\":\\"location.driver_seat\\"}"}',
    nextStep:
      'history.findings_next_step_locate_wheel history.recapture_recipe:{"from":"50","to":"120","unit":"km/h"}',
  });
});

test("shows every History speed in the m/s setting", () => {
  const mps = { ...f, speedUnit: "mps" as const };
  const run = historyListRun("run-007");
  const details = buildDetails(
    run,
    defaultDetail({ preview: populatedInsights("run-007") }),
    mps,
  );
  if (details.insights.kind !== "findings") {
    throw new Error("expected findings");
  }
  expect(details.insights.primary).toMatchObject({
    signature: "T1 · 12.1 Hz @ 24 m/s",
    chips: [
      { label: "history.findings_location" },
      { label: "history.findings_speed_band", value: "18–29 m/s" },
      { label: "history.findings_signature", value: "T1 · 12.1 Hz @ 24 m/s" },
    ],
  });
  expect(
    [
      ...details.insights.visibleSecondary,
      ...details.insights.hiddenSecondary,
    ].map((finding) => finding.speedBand),
  ).toEqual(["17–22 m/s", "idle", "28–33 m/s"]);

  const noFault = populatedInsights("run-008");
  noFault.diagnosis = makeDiagnosis();
  noFault.speed_stats = { ...noFault.speed_stats, min_kmh: 36, max_kmh: 108 };
  expect(
    buildDetails(run, defaultDetail({ preview: noFault }), mps).insights,
  ).toMatchObject({
    primary: { chips: [{ value: "10–30 m/s" }, {}] },
  });

  const weak = populatedInsights("run-009");
  weak.diagnosis = makeDiagnosis({
    verdict: "weak_evidence",
    confidence_level: "weak",
  });
  expect(
    buildDetails(run, defaultDetail({ preview: weak }), mps).insights,
  ).toMatchObject({
    primary: {
      nextStep: 'history.recapture_recipe:{"from":"14","to":"33","unit":"m/s"}',
    },
  });
});

test("relabels the analysis speed bands in the display unit", () => {
  const mps = { t: testTranslation, speedUnit: "mps" as const };
  expect(speedBandLabel("80-100 km/h", f)).toBe("80–100 km/h");
  expect(speedBandLabel("72-108 km/h", mps)).toBe("20–30 m/s");
  expect(speedBandLabel("90 km/h", mps)).toBe("25 m/s");
  expect(speedBandLabel(" 36.0-54.0 km/h ", mps)).toBe("10–15 m/s");
  // Labels in another shape are shown as the server wrote them.
  expect(speedBandLabel("idle", mps)).toBe("idle");
  expect(speedBandLabel("80-100 mph", mps)).toBe("80-100 mph");
});

test("labels sources, folding unknown keys into title case", () => {
  // Backend source values (VibrationSource) use "wheel/tire" and "body resonance".
  expect(sourceLabel("wheel/tire", testTranslation)).toBe(
    "history.source.wheel_tire",
  );
  expect(sourceLabel("body resonance", testTranslation)).toBe(
    "history.source.body_resonance",
  );
  expect(sourceLabel("rear_axle-hub", testTranslation)).toBe("Rear Axle Hub");
  expect(sourceLabel("Custom Thing", testTranslation)).toBe("Custom Thing");
  expect(sourceLabel("", testTranslation)).toBe("report.missing");
});

test("maps location names onto heatmap positions and scales the colour", () => {
  expect(heatmapLocationKey("Front_Left Wheel")).toBe("front_left_wheel");
  expect(heatmapLocationKey("Drive shaft tunnel")).toBe("driveshaft_tunnel");
  expect(heatmapLocationKey("roof")).toBe("roof");
  expect(normalizeUnit(5, 0, 10)).toBe(0.5);
  expect(normalizeUnit(15, 10, 20)).toBe(0.5);
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
    label: "location.trunk",
    strongest: true,
    accent: { fillPercent: 50 },
  });
});

test("heatmap says 'no sensor' where none was assigned, 'missing' where one sent nothing", () => {
  const heatmap = buildHeatmap(
    makeHistoryInsightsPayload({
      metadata: {
        sensor_snapshots: [
          { sensor_id: "a", location_code: "front_left_wheel" },
          { sensor_id: "b", location_code: "rear_right_wheel" },
        ],
      },
      sensor_intensity_by_location: [
        makeLocationIntensityRow({
          location: "Front Left Wheel",
          p95_intensity_db: 7.5,
        }),
      ],
    }),
    f,
  );
  if (heatmap.kind !== "zones") {
    throw new Error("expected zones");
  }
  const value = (key: string) =>
    heatmap.zones.find((zone) => zone.key === key)?.valueLabel;
  expect(value("front_left_wheel")).toBe("7.5 dB");
  expect(value("rear_right_wheel")).toBe("report.missing");
  expect(value("engine_bay")).toBe("history.heatmap_no_sensor");
  expect(value("trunk")).toBe("history.heatmap_no_sensor");
});
