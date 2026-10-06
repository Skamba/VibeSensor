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

type RawCaptureState = NonNullable<HistoryEntry["lifecycle"]>["raw_capture"];

function historyListRun(
  runId: string,
  rawCapture: RawCaptureState = "not_recorded",
): HistoryEntry {
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
      raw_capture: rawCapture,
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
  const run = historyListRun("run-001", "missing");
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

test("a run started before the Pi clock was set shows no wall times", () => {
  const run = historyListRun("run-clock");
  const detail = defaultDetail({ preview: populatedInsights("run-clock") });
  expect(buildRow(run, detail, false, f).startedAt).toBe(
    "2026-01-01T00:00:00Z",
  );

  const unset = { ...run, start_time_unverified: true };
  expect(buildRow(unset, detail, false, f).startedAt).toBe(
    "history.time_unknown",
  );
  const summary = buildDetails(unset, detail, f).runSummary ?? "";
  expect(summary).toContain("history.summary_created: history.time_unknown");
  expect(summary).toContain("history.summary_updated: history.time_unknown");
  expect(summary).toContain("history.summary_size: 12.3 s");
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
  const run = historyListRun("run-004", "degraded");
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
  extra: Partial<HistoryInsightsPayload["diagnosis"]> = {},
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
          ...extra,
        }
      : { source_checks: sourceChecks, ...extra },
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
    notApplicableTitle: "Not applicable",
    notApplicable: [],
    referencesTitle: "Car references",
    references: [
      {
        label: "Powertrain",
        detail: "not provided; analysed as a car with a combustion engine",
      },
      {
        label: "Drive layout",
        detail:
          "not provided; driveline advice assumes a propshaft to the rear axle",
      },
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
    expect(dutch.checks.references[3]).toEqual({
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
  expect(insights.checks.references[5]).toEqual({
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

test("an EV run names its motor, calls the engine not applicable and skips gearbox rows", async () => {
  const sourceChecks: SourceChecks = [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    { source: "driveline", status: "ruled_out", reason: "no_matching_order" },
    { source: "engine", status: "not_applicable", reason: "electric_car" },
  ];
  const ev = { fuel_type: "EV", final_drive_ratio: 9.05 } as const;
  const insights = checkedInsights("no_fault", sourceChecks, "en", ev);
  expect(insights.primary?.explanation).toBe(
    "Nothing stood out in the checks this run could make: wheels/tires and electric motor.",
  );
  expect(insights.checks.checked[1]).toEqual({
    label: "Electric motor",
    detail: "no vibration found at once or twice per motor revolution",
  });
  expect(insights.checks.notChecked).toEqual([]);
  expect(insights.checks.notApplicable).toEqual([
    {
      label: "Combustion engine",
      detail: "an electric car has no combustion engine",
    },
  ]);
  expect(insights.checks.references.map((line) => line.label)).toEqual([
    "Powertrain",
    "Tire size",
    "Reduction ratio (final drive)",
  ]);
  expect(insights.checks.references[0].detail).toContain(
    "electrical and gear-mesh orders are not analysed",
  );
  // A run that checked nothing still never says "engine".
  const nothing = checkedInsights(
    "no_fault",
    [
      ...sourceChecks.slice(0, 2).map((check) => ({
        ...check,
        status: "not_testable" as const,
        reason: "no_tire_reference" as const,
      })),
      sourceChecks[2],
    ],
    "en",
    ev,
  );
  expect(nothing.primary?.explanation).toBe(
    "No vibration stood out, but this run could not check the wheels or the electric motor against their rhythms, so it does not show that they are fine.",
  );

  await setLanguage("nl");
  try {
    const dutch = checkedInsights("no_fault", sourceChecks, "nl", ev);
    expect(dutch.checks.checked[1].label).toBe("Elektromotor");
    expect(dutch.checks.notApplicable[0].label).toBe("Verbrandingsmotor");
  } finally {
    await setLanguage("en");
  }
});

test("a strong vibration no checked order explains never reads as nothing found", () => {
  const sourceChecks: SourceChecks = [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    {
      source: "driveline",
      status: "not_testable",
      reason: "no_drive_reference",
    },
    { source: "engine", status: "not_applicable", reason: "electric_car" },
  ];
  const ev = { fuel_type: "EV", final_drive_ratio: null } as const;
  for (const [language, headline, explanation] of [
    [
      "en",
      "Vibration found, but no checked cause explains it",
      "Strongest at Rear Right Wheel, this vibration did not follow the rhythm of anything this run could check. Checked and not the cause: wheels/tires. Not checked, so not shown to be fine: electric motor.",
    ],
    [
      "nl",
      "Trilling gevonden, maar geen gecontroleerde oorzaak verklaart hem",
      "Het sterkst bij Achterwiel rechts; deze trilling volgde het ritme van niets wat deze rit kon controleren. Gecontroleerd en niet de oorzaak: wielen/banden. Niet gecontroleerd, dus niet aangetoond dat het in orde is: elektromotor.",
    ],
  ] as const) {
    const insights = checkedInsights("no_fault", sourceChecks, language, ev, {
      unexplained_vibration: true,
      location_amplitudes: [
        {
          location: "Rear Right Wheel",
          amplitude_mg: 228.5,
          db_above_floor: 36.5,
          ratio_to_strongest: 1,
          presence_ratio: null,
        },
      ],
    });
    expect(insights.primary).toMatchObject({
      headline,
      explanation,
      tone: "warn",
    });
  }
});

test("an EV motor fault names the motor and drive unit, and its recording advice skips neutral", () => {
  const insights = populatedInsights("run-011");
  insights.diagnosis = makeDiagnosis({
    verdict: "weak_evidence",
    confidence_level: "weak",
    finding_id: "finding-1",
    source: "driveline",
    zone: "driveshaft_tunnel",
  });
  insights.diagnosis.conditions.fuel_type = "EV";
  const run = historyListRun("run-011");
  const details = buildDetails(run, defaultDetail({ preview: insights }), f);
  expect(details.insights).toMatchObject({
    primary: {
      explanation:
        'history.verdict.weak_body:{"source":"history.source.motor","location":"history.zone.drive_unit_ev"}',
      nextStep:
        'history.recapture_recipe_ev:{"from":"50","to":"120","unit":"km/h"}',
    },
  });
});

/** A driveline (P1) diagnosis in real catalog text, for a car with `conditions`. */
function drivelineInsights(
  verdict: "fault" | "no_fault",
  diagnosis: Partial<HistoryInsightsPayload["diagnosis"]>,
  conditions: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]>,
  language: Lang = "en",
) {
  const insights = populatedInsights("run-013");
  const base = makeDiagnosis();
  insights.diagnosis = makeDiagnosis({
    ...(verdict === "fault"
      ? {
          verdict,
          confidence_level: "strong",
          finding_id: "finding-1",
          source: "driveline",
          order_code: "P1",
        }
      : {}),
    source_checks: [
      {
        source: "driveline",
        status: verdict === "fault" ? "candidate" : "ruled_out",
        reason: verdict === "fault" ? null : "no_matching_order",
      },
    ],
    ...diagnosis,
  });
  insights.diagnosis.conditions = {
    ...base.conditions,
    fuel_type: "ICE",
    ...conditions,
  };
  const details = buildDetails(
    historyListRun("run-013"),
    defaultDetail({ preview: insights }),
    { ...f, t: (key, vars) => translate(language, key, vars) },
  );
  if (details.insights.kind !== "findings") {
    throw new Error("expected findings");
  }
  return details.insights;
}

const FWD = {
  drive_layout: "FWD",
  final_drive_axle: "front",
  propshaft: false,
} as const;

// Drive shafts and CV joints turn at wheel speed, not at the driveline order.
const WHEEL_SPEED_PARTS = /drive shaft|CV joint|aandrijfas|homokinet/i;

test("a front-wheel-drive car's driveline fault names its gearbox output shaft, never a propshaft or drive shaft", async () => {
  const fault = drivelineInsights(
    "fault",
    { zone: "front_axle", driveline_parts: ["front_drive"] },
    FWD,
  );
  expect(fault.primary?.nextStep).toBe(
    "Front axle: have the gearbox output shaft, final-drive pinion and differential bearings checked",
  );
  expect(fault.checks.references[1]).toEqual({
    label: "Drive layout",
    detail:
      "front-wheel drive: the gearbox output shaft turns at the driveline order",
  });
  expect(JSON.stringify(fault)).not.toMatch(/propshaft\)|centre bearing/i);
  expect(JSON.stringify(fault)).not.toMatch(WHEEL_SPEED_PARTS);

  // No axle standing out: a centre-tunnel location is not a propshaft.
  const tunnel = drivelineInsights(
    "fault",
    { zone: "driveshaft_tunnel", driveline_parts: ["front_drive"] },
    FWD,
  );
  expect(tunnel.primary?.chips[0].value).toBe("Centre tunnel");

  const healthy = drivelineInsights("no_fault", {}, FWD);
  expect(healthy.checks.checked).toEqual([
    { label: "Driveline", detail: "no driveline-order vibration found" },
  ]);

  await setLanguage("nl");
  try {
    const dutch = drivelineInsights(
      "fault",
      { zone: "front_axle", driveline_parts: ["front_drive"] },
      FWD,
      "nl",
    );
    expect(dutch.primary?.nextStep).toBe(
      "Vooras: laat de uitgaande as van de versnellingsbak, het pignon van de eindoverbrenging en de differentieellagers controleren",
    );
    expect(JSON.stringify(dutch)).not.toMatch(/cardanas|middenlager/i);
    expect(JSON.stringify(dutch)).not.toMatch(WHEEL_SPEED_PARTS);
  } finally {
    await setLanguage("en");
  }
});

test("an all-wheel-drive car checks the axle the sensors point to first, then the other", () => {
  const rear = drivelineInsights(
    "fault",
    { zone: "rear_axle", driveline_parts: ["propshaft_rear", "front_drive"] },
    { drive_layout: "AWD", final_drive_axle: "rear", propshaft: true },
  );
  expect(rear.primary?.nextStep).toBe(
    "Rear axle: have the propshaft, its joints and centre bearing, and the rear differential checked; then the front propshaft (if fitted) and the front differential pinion",
  );
  expect(JSON.stringify(rear)).not.toMatch(WHEEL_SPEED_PARTS);
  const front = drivelineInsights(
    "fault",
    { zone: "front_axle", driveline_parts: ["front_drive", "propshaft_rear"] },
    { drive_layout: "AWD", final_drive_axle: "rear", propshaft: true },
  );
  expect(front.primary?.nextStep).toBe(
    "Front axle: have the front propshaft (if fitted) and the front differential pinion checked; then the propshaft, its joints and centre bearing, and the rear differential",
  );
  expect(front.checks.references[1].detail).toBe(
    "all-wheel drive: a propshaft to the rear axle and a drive to the front differential",
  );
  const rwd = drivelineInsights(
    "fault",
    { zone: "rear_axle", driveline_parts: ["propshaft_rear"] },
    { drive_layout: "RWD", final_drive_axle: "rear", propshaft: true },
  );
  expect(rwd.primary?.nextStep).toBe(
    "Rear axle: have the propshaft, its joints and centre bearing, and the rear differential checked",
  );
  expect(rwd.checks.references[1].detail).toBe(
    "rear-wheel drive: propshaft to the rear axle",
  );
});

test("a run without a drive layout keeps the propshaft wording and says the layout was not given", () => {
  const insights = drivelineInsights(
    "fault",
    { zone: "driveshaft_tunnel" },
    {},
  );
  expect(insights.primary?.nextStep).toBe("Centre tunnel (propshaft)");
  expect(insights.checks.references[1]).toEqual({
    label: "Drive layout",
    detail:
      "not provided; driveline advice assumes a propshaft to the rear axle",
  });
});

test("a plug-in hybrid's engine check is hedged without OBD and untested while it was off", () => {
  const phev = checkedInsights(
    "no_fault",
    [
      {
        source: "wheel/tire",
        status: "ruled_out",
        reason: "no_matching_order",
      },
      {
        source: "engine",
        status: "ruled_out_estimated",
        reason: "engine_may_be_off",
      },
    ],
    "en",
    { fuel_type: "PHEV", rpm_source: "estimated_top_gear" },
  );
  expect(phev.primary?.explanation).toBe(
    "Nothing stood out in the checks this run could make: wheels/tires and engine (may have been off).",
  );
  expect(phev.checks.checked[1].detail).toContain(
    "a plug-in hybrid's engine may have been off",
  );
  expect(phev.checks.references[0].detail).toContain(
    "without OBD-II RPM the engine check is not conclusive",
  );
  const off = checkedInsights(
    "no_fault",
    [
      {
        source: "engine",
        status: "not_testable",
        reason: "engine_not_running",
      },
    ],
    "en",
    { fuel_type: "PHEV", rpm_source: "measured" },
  );
  expect(off.checks.notChecked[0].detail).toContain(
    "the engine was off for most of the drive",
  );
  expect(off.checks.references[0].detail).toContain(
    "checked only while OBD-II RPM showed it running",
  );
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

test("brake judder names the axle's brake discs and asks for firm stops, not a sweep", () => {
  const insights = populatedInsights("run-012");
  insights.diagnosis = makeDiagnosis({
    verdict: "weak_evidence",
    confidence_level: "weak",
    finding_id: "finding-1",
    source: "brakes",
    zone: "front_axle",
  });
  const details = buildDetails(
    historyListRun("run-012"),
    defaultDetail({ preview: insights }),
    f,
  );
  expect(details.insights).toMatchObject({
    primary: {
      explanation:
        'history.verdict.weak_body:{"source":"history.source.brakes","location":"history.zone.brake_discs_front_axle"}',
      nextStep:
        'history.recapture_recipe_brakes:{"from":"100","to":"40","unit":"km/h"}',
    },
  });

  const noBraking = checkedInsights("no_fault", [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    { source: "brakes", status: "not_testable", reason: "no_braking" },
  ]);
  expect(noBraking.primary?.explanation).toBe(
    "Nothing stood out in the checks this run could make: wheels/tires. Not checked, so not shown to be fine: brakes.",
  );
  expect(noBraking.checks.notChecked).toEqual([
    {
      label: "Brakes",
      detail:
        "brake judder shows only while braking, and this drive did not brake firmly (coasting does not count) — do the guided test's firm stops, or brake firmly from about 100 km/h a few times during the drive.",
    },
  ]);
  const judder = checkedInsights("fault", [
    { source: "wheel/tire", status: "ruled_out", reason: "only_while_braking" },
    { source: "brakes", status: "candidate", reason: null },
  ]);
  expect(judder.checks.checked[0]).toEqual({
    label: "Wheel / Tire",
    detail:
      "ruled out: the vibration at the wheel's rhythm came only while braking (the brakes, not a wheel or tire)",
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
