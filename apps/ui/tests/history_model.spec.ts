import { expect, test } from "vitest";
import type { HistoryEntry, HistoryInsightsPayload } from "../src/api/types";
import { type Lang, setLanguage, translate } from "../src/i18n";
import {
  buildDetails,
  buildHeatmap,
  buildRow,
  EMPTY_RUN_DETAIL,
  type Formatters,
  heatColor,
  heatmapLocationKey,
  normalizeUnit,
  ownerDiagram,
  type RunDetail,
  sourceLabel,
  speedBandLabel,
} from "../src/pages/history/history_model";
import {
  makeDiagnosis,
  makeHistoryFinding,
  makeHistoryInsightsPayload,
  makeLocationIntensityRow,
  makeOwnerPage,
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
    duration_s: 72.3,
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

function loaded(summary: HistoryInsightsPayload): RunDetail {
  return { ...EMPTY_RUN_DETAIL, summary };
}

const f: Formatters = {
  t: testTranslation,
  fmt: (value: number, digits = 0) => Number(value).toFixed(digits),
  fmtTs: (iso: string) => iso,
  fmtShortTs: (iso: string) => `short(${iso})`,
  formatInt: (value: number) => String(value),
  speedUnit: "kmh",
};

/** The workshop findings behind "More details". */
function moreFindings(
  run: HistoryEntry,
  detail: RunDetail,
  formatters: Formatters = f,
) {
  const more = buildDetails(run, detail, formatters).more;
  if (!more) {
    throw new Error("expected a diagnosis");
  }
  return more.findings;
}

test("titles a run by its date and the server's result, and opens with the PDF's page 1", () => {
  const run = historyListRun("run-001", "missing");
  const summary = populatedInsights("run-001");
  const row = buildRow(run, loaded(summary), true, f);
  expect(row.title).toBe(
    "short(2026-01-01T00:00:00Z) · Front-left wheel · Moderate",
  );
  // The car is secondary; the run ID is never in the row.
  expect(row.subtitle).toBe("Track Car · 1:12");
  expect(`${row.title} ${row.subtitle} ${row.toggleTitle}`).not.toContain(
    "run-001",
  );
  expect(row.chips).toEqual([]);
  expect(row.reportPendingHint).toBeNull();

  const details = buildDetails(run, loaded(summary), f);
  expect(details.owner).toBe(summary.owner);
  expect(details.stateMessage).toBeNull();
  // Raw-capture warning first, then the diagnosis' own.
  expect(details.warnings).toEqual([
    {
      severity: "warn",
      title: "history.raw_capture_missing_title",
      detail: "history.raw_capture_missing_detail",
    },
    { severity: "warn", title: "history.warning.speed_gap", detail: "Gap" },
  ]);
  // The run ID, times and size once, in the footer.
  expect(details.facts).toEqual([
    { label: "report.run_id", value: "run-001" },
    { label: "history.started", value: "2026-01-01T00:00:00Z" },
    { label: "history.ended", value: "2026-01-01T00:00:12Z" },
    { label: "history.summary_size", value: "72.3 s" },
    { label: "history.summary_sensor_count", value: "2" },
    { label: "history.raw_samples", value: "9600" },
  ]);
  expect(details.reloadLabel).toBe("history.reload_insights");

  const findings = moreFindings(run, loaded(summary));
  expect(findings.primary).toEqual({
    source: "history.source.wheel_tire",
    signature: "T1 · 12.1 Hz @ 85 km/h",
    confidence:
      'history.confidence:{"level":"history.confidence_level.strong"}',
    tone: "success",
    location: "location.front_right_wheel",
    speedBand: "63–105 km/h",
    alsoAt: null,
    evidence: "Front-right wheel imbalance",
  });
  expect(findings.visibleSecondary).toHaveLength(2);
  expect(findings.hiddenSecondary).toHaveLength(1);
  const heatmap = buildDetails(run, loaded(summary), f).more?.heatmap;
  expect(
    heatmap?.zones.find((zone) => zone.key === "front_right_wheel"),
  ).toMatchObject({
    // Translated from the location code, not the server's English label.
    label: "location.front_right_wheel",
    valueLabel: "32.0 dB",
    strongest: true,
  });
  expect(heatmap?.extras).toEqual(["custom bracket · 21.1 dB"]);
});

test("a run without a fault, or without enough evidence, is titled by its result alone", () => {
  const run = historyListRun("run-005");
  const title = (owner: Partial<HistoryInsightsPayload["owner"]>) => {
    const summary = populatedInsights("run-005");
    summary.owner = makeOwnerPage(owner);
    return buildRow(run, loaded(summary), false, f).title;
  };
  const noFault = {
    verdict: "no_fault",
    level: null,
    level_word: null,
  } as const;
  expect(title({ ...noFault, result: "No significant vibration" })).toBe(
    "short(2026-01-01T00:00:00Z) · No significant vibration",
  );
  expect(title({ ...noFault, result: "No result" })).toBe(
    "short(2026-01-01T00:00:00Z) · No result",
  );
  // The level is a fault's: a weak candidate is just not conclusive.
  expect(
    title({
      verdict: "weak_evidence",
      result: "Not conclusive",
      level: "weak",
      level_word: "Weak",
    }),
  ).toBe("short(2026-01-01T00:00:00Z) · Not conclusive");
  expect(
    title({ level: "strong", level_word: "Strong", result: "Rear wheels" }),
  ).toBe("short(2026-01-01T00:00:00Z) · Rear wheels · Strong");
});

test("a run started before the Pi clock was set shows no wall times", () => {
  const run = { ...historyListRun("run-clock"), start_time_unverified: true };
  const detail = loaded(populatedInsights("run-clock"));
  expect(buildRow(run, detail, false, f).title).toBe(
    "history.date_unknown · Front-left wheel · Moderate",
  );
  const facts = buildDetails(run, detail, f).facts;
  expect(facts[1]).toEqual({
    label: "history.started",
    value: "history.time_unknown",
  });
  expect(facts[2]).toEqual({
    label: "history.ended",
    value: "history.time_unknown",
  });
});

test("a run cut off before Stop says so in its row", () => {
  const run = historyListRun("run-cut");
  const detail = loaded(populatedInsights("run-cut"));
  expect(buildRow(run, detail, false, f).chips).toEqual([]);
  expect(
    buildRow({ ...run, interrupted: true }, detail, false, f).chips,
  ).toEqual([
    { key: "interrupted", text: "history.interrupted", tone: "warn" },
  ]);
});

test("a closed run keeps its loaded title; only a first load or a failure says so", () => {
  const run = historyListRun("run-002");
  const summary = populatedInsights("run-002");
  // Reloading (a language switch) keeps the title until the new one arrives.
  const reloading = { ...loaded(summary), loading: true };
  expect(buildRow(run, reloading, false, f).title).toBe(
    "short(2026-01-01T00:00:00Z) · Front-left wheel · Moderate",
  );

  const first = { ...EMPTY_RUN_DETAIL, loading: true, pdfLoading: true };
  const row = buildRow(run, first, true, f);
  expect(row.title).toBe(
    "short(2026-01-01T00:00:00Z) · history.row_summary_loading",
  );
  expect(row.subtitle).toBe("Track Car · 0:12");
  expect(row.pdfLabel).toBe("history.generating_pdf");
  expect(row.pdfLoading).toBe(true);
  const details = buildDetails(run, first, f);
  expect(details.owner).toBeNull();
  expect(details.more).toBeNull();
  expect(details.stateMessage).toBe("history.loading_insights");
  expect(details.reloadDisabled).toBe(true);

  const failedLoad = { ...EMPTY_RUN_DETAIL, error: "history.error.insights" };
  expect(buildRow(run, failedLoad, false, f).title).toBe(
    "short(2026-01-01T00:00:00Z) · history.row_status.unavailable",
  );
  const failedDetails = buildDetails(run, failedLoad, f);
  expect(failedDetails.error).toBe("history.error.insights");
  expect(failedDetails.stateMessage).toBe("history.diagnosis_unavailable");
  expect(failedDetails.reloadLabel).toBe("history.load_insights");
});

test("a run still recording, analysing or failed says so in its title; the PDF waits", () => {
  const lifecycle = (
    stage: NonNullable<HistoryEntry["lifecycle"]>["stage"],
    state: "pending" | "degraded",
  ) => ({
    stage,
    raw_capture: "not_recorded" as const,
    post_analysis: state,
    report: state,
  });
  const analyzing: HistoryEntry = {
    ...historyListRun("run-003"),
    status: "analyzing",
    lifecycle: lifecycle("post_analysis_pending", "pending"),
  };
  const row = buildRow(analyzing, EMPTY_RUN_DETAIL, false, f);
  expect(row.title).toBe(
    "short(2026-01-01T00:00:00Z) · history.row_status.analyzing",
  );
  expect(row.reportPendingHint).toBe("history.quick_report_pending");
  expect(buildDetails(analyzing, EMPTY_RUN_DETAIL, f).stateMessage).toBe(
    "history.findings_pending",
  );

  const recording: HistoryEntry = {
    ...analyzing,
    status: "recording",
    lifecycle: lifecycle("recording", "pending"),
  };
  expect(buildRow(recording, EMPTY_RUN_DETAIL, false, f).title).toBe(
    "short(2026-01-01T00:00:00Z) · history.row_status.recording",
  );

  const degraded: HistoryEntry = {
    ...historyListRun("run-003b"),
    error_message: "analysis crashed",
    lifecycle: lifecycle("post_analysis_degraded", "degraded"),
  };
  const degradedRow = buildRow(degraded, EMPTY_RUN_DETAIL, false, f);
  expect(degradedRow.title).toBe(
    "short(2026-01-01T00:00:00Z) · history.row_status.error",
  );
  expect(degradedRow.chips).toEqual([
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
  const details = buildDetails(run, loaded(populatedInsights("run-004")), f);
  expect(details.warnings[0]).toEqual({
    severity: "warn",
    title: "history.raw_capture_degraded_title",
    detail:
      'history.raw_capture_degraded_timeout_detail:{"queueDepth":3,"errorSummary":"raw capture finalize timed out"}',
  });
});

test("the same wheel's twice-per-turn order is part of the diagnosed finding, not another candidate", () => {
  const summary = populatedInsights("run-014");
  summary.diagnosis = makeDiagnosis({
    ...summary.diagnosis,
    order_findings: [
      {
        finding_id: "finding-1",
        source: "wheel/tire",
        order_code: "T1",
        location: "Front Right Wheel",
        confidence_level: "strong",
        frequency_hz: 12.1,
        phases: [],
        presence_ratio: 1,
        reference_speed_kmh: 85,
        speed_min_kmh: 63,
        speed_max_kmh: 105,
      },
      {
        finding_id: "finding-5",
        source: "wheel/tire",
        order_code: "T2",
        location: "Front Right Wheel",
        confidence_level: "moderate",
        frequency_hz: 24.2,
        phases: [],
        presence_ratio: 1,
        reference_speed_kmh: 85,
        speed_min_kmh: 63,
        speed_max_kmh: 105,
      },
      {
        finding_id: "finding-2",
        source: "driveline",
        order_code: "P1",
        location: "Driveshaft Tunnel",
        confidence_level: "moderate",
        frequency_hz: 18.5,
        phases: [],
        presence_ratio: 1,
        reference_speed_kmh: 85,
        speed_min_kmh: 63,
        speed_max_kmh: 105,
      },
    ],
  });
  summary.findings = [
    summary.findings[0],
    makeHistoryFinding({
      finding_id: "finding-5",
      frequency_hz_or_order: "2x wheel",
      evidence_summary: "The same wheel at twice per turn",
    }),
    ...summary.findings.slice(1),
  ];
  const findings = moreFindings(historyListRun("run-014"), loaded(summary));
  expect(findings.primary?.alsoAt).toBe(
    'history.also_at:{"orders":"T2 (24.2 Hz)"}',
  );
  // The driveline order elsewhere stays a candidate of its own.
  expect(
    [...findings.visibleSecondary, ...findings.hiddenSecondary].map(
      (finding) => finding.evidence,
    ),
  ).toEqual([
    "Secondary driveline contribution",
    "Engine harmonics remain visible",
    "Cabin resonance remains possible",
  ]);
});

test("draws the PDF's car diagram: the zone, its wheels and a sized marker per sensor", () => {
  const wheel = ownerDiagram(makeOwnerPage().diagram);
  expect(wheel.frontLabel).toBe("FRONT");
  expect(wheel.zone).toBeNull();
  expect(
    wheel.wheels.filter((item) => item.highlighted).map((item) => item.code),
  ).toEqual(["front_left_wheel"]);
  const [frontLeft, trunk] = wheel.markers;
  // pdf.py: the body is 52% of a 62 mm box, the wheel at 10% across, 20% down.
  expect(frontLeft.cx).toBeCloseTo(14.88 + 0.1 * 32.24);
  expect(frontLeft.cy).toBeCloseTo(9 + 0.2 * 94);
  expect(frontLeft.r).toBeCloseTo(4);
  expect(frontLeft.text).toEqual({
    x: frontLeft.cx - 4,
    y: frontLeft.cy + 1,
    anchor: "end",
  });
  expect(trunk.r).toBeCloseTo(1.6 + 2.4 * 0.02);
  expect(trunk.text.anchor).toBe("middle");
  expect(trunk.text.y).toBeCloseTo(trunk.cy + trunk.r + 3);

  const axle = ownerDiagram({
    zone: "rear_axle",
    front_label: "VOOR",
    markers: [
      {
        code: "roof_rack",
        label: "roof",
        value: "1 mg",
        ratio: 1,
        strongest: true,
      },
    ],
  });
  expect(axle.zone).not.toBeNull();
  expect(
    axle.wheels.filter((item) => item.highlighted).map((item) => item.code),
  ).toEqual(["rear_left_wheel", "rear_right_wheel"]);
  // A location the diagram has no place for is left out, as on the PDF.
  expect(axle.markers).toEqual([]);
});

type SourceChecks = HistoryInsightsPayload["diagnosis"]["source_checks"];

/** The workshop findings in real catalog text, worded like the PDF's page 2. */
function checkedInsights(
  verdict: "fault" | "no_fault",
  sourceChecks: SourceChecks,
  language: Lang = "en",
  conditions: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]> = {},
  extra: Partial<HistoryInsightsPayload["diagnosis"]> = {},
  speedUnit: "kmh" | "mps" = "kmh",
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
  return moreFindings(historyListRun("run-010"), loaded(insights), {
    ...f,
    t: (key, vars) => translate(language, key, vars),
    speedUnit,
  });
}

test("lists what the run checked and couldn't, and the car references, as the PDF does", async () => {
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
  // A run without a fault has no candidates: page 1 says what it means.
  expect(insights.primary).toBeNull();
  expect(insights.secondaryTitle).toBeNull();
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
        detail: "not provided; analyzed as a car with a combustion engine",
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
      { label: "Engine", detail: "not known: E1 and E2 tested" },
      { label: "Engine RPM", detail: "not available" },
    ],
  });

  await setLanguage("nl");
  try {
    const dutch = checkedInsights("no_fault", sourceChecks, "nl", {
      final_drive_ratio: 3.15,
      final_drive_provenance: "family_default",
    });
    expect(dutch.checks.notCheckedTitle).toBe("Niet te controleren");
    expect(dutch.checks.references[3]).toEqual({
      label: "Eindoverbrenging",
      detail: "3.15 (autobibliotheek, schatting voor de modelreeks)",
    });
  } finally {
    await setLanguage("en");
  }
});

test("a run without a tire size or live speed lists every source as couldn't check", () => {
  const noTire = checkedInsights(
    "no_fault",
    ["wheel/tire", "driveline", "engine"].map((source) => ({
      source,
      status: "not_testable" as const,
      reason: "no_tire_reference" as const,
    })),
  );
  expect(noTire.checks.checked).toEqual([]);
  expect(noTire.checks.notChecked.map((line) => line.detail)).toEqual([
    "no tire size — add it to the car in Settings.",
    "no tire size — add it to the car in Settings.",
    "no tire size — connect an OBD-II adapter to measure RPM, or add the tire size to the car.",
  ]);

  const noSpeed = checkedInsights(
    "no_fault",
    ["wheel/tire", "driveline", "brakes"].map((source) => ({
      source,
      status: "not_testable" as const,
      reason: "speed_missing" as const,
    })),
  );
  expect(noSpeed.checks.checked).toEqual([]);
  expect(noSpeed.checks.notChecked[0]?.detail).toBe(
    "the live speed (GPS or OBD-II) was missing for most of the drive, so finding no match proves nothing — record again once the GPS receiver has a fix (or the OBD-II adapter reads speed).",
  );
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
  expect(insights.checks.references[6]).toEqual({
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

test("the car references name the engine and its firing order, as the PDF does", async () => {
  const sourceChecks: SourceChecks = [
    { source: "engine", status: "ruled_out", reason: "no_matching_order" },
  ];
  const engine: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]> = {
    fuel_type: "ICE",
    engine_profile: { layout: "inline", cylinders: 6 },
    engine_orders: [
      { code: "E1", roles: ["rotating"] },
      { code: "E3", roles: ["firing"] },
    ],
  };
  const engineLine = (lang: Lang) =>
    checkedInsights(
      "no_fault",
      sourceChecks,
      lang,
      engine,
    ).checks.references.find(
      (line) => line.label === (lang === "en" ? "Engine" : "Motor"),
    );
  expect(engineLine("en")).toEqual({
    label: "Engine",
    detail: "Inline-6, fires at E3",
  });
  await setLanguage("nl");
  try {
    expect(engineLine("nl")).toEqual({
      label: "Motor",
      detail: "6-in-lijn, ontsteking op E3",
    });
  } finally {
    await setLanguage("en");
  }
});

test("an EV run names its motor, calls the engine not applicable and skips gearbox rows", async () => {
  const sourceChecks: SourceChecks = [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    { source: "driveline", status: "ruled_out", reason: "no_matching_order" },
    { source: "engine", status: "not_applicable", reason: "electric_car" },
  ];
  const ev = { fuel_type: "EV", final_drive_ratio: 9.05 } as const;
  const insights = checkedInsights("no_fault", sourceChecks, "en", ev);
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
    "electrical and gear-mesh orders are not analyzed",
  );
  // An EV motor fault is named for the motor, not the driveline.
  const motor = checkedInsights("fault", sourceChecks, "en", ev, {
    source: "driveline",
    order_code: "P1",
  });
  expect(motor.primary?.source).toBe("Electric motor");

  await setLanguage("nl");
  try {
    const dutch = checkedInsights("no_fault", sourceChecks, "nl", ev);
    expect(dutch.checks.checked[1].label).toBe("Elektromotor");
    expect(dutch.checks.notApplicable[0].label).toBe("Verbrandingsmotor");
  } finally {
    await setLanguage("en");
  }
});

/** A driveline (P1) diagnosis in real catalog text, for a car with `conditions`. */
function drivelineInsights(
  verdict: "fault" | "no_fault",
  diagnosis: Partial<HistoryInsightsPayload["diagnosis"]>,
  conditions: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]>,
) {
  return checkedInsights(
    verdict,
    [
      {
        source: "driveline",
        status: verdict === "fault" ? "candidate" : "ruled_out",
        reason: verdict === "fault" ? null : "no_matching_order",
      },
    ],
    "en",
    { fuel_type: "ICE", ...conditions },
    verdict === "fault"
      ? { source: "driveline", order_code: "P1", ...diagnosis }
      : diagnosis,
  );
}

test("the drive layout reference names what turns at the driveline order", () => {
  const fwd = drivelineInsights(
    "no_fault",
    {},
    {
      drive_layout: "FWD",
      final_drive_axle: "front",
      propshaft: false,
    },
  );
  expect(fwd.checks.checked).toEqual([
    { label: "Driveline", detail: "no driveline-order vibration found" },
  ]);
  expect(fwd.checks.references[1]).toEqual({
    label: "Drive layout",
    detail:
      "front-wheel drive: the gearbox output shaft turns at the driveline order",
  });
  const layout = (
    conditions: Partial<HistoryInsightsPayload["diagnosis"]["conditions"]>,
  ) => drivelineInsights("fault", {}, conditions).checks.references[1].detail;
  expect(
    layout({ drive_layout: "AWD", final_drive_axle: "rear", propshaft: true }),
  ).toBe(
    "all-wheel drive: a propshaft to the rear axle and a drive to the front differential",
  );
  expect(
    layout({ drive_layout: "RWD", final_drive_axle: "rear", propshaft: true }),
  ).toBe("rear-wheel drive: propshaft to the rear axle");
  expect(layout({})).toBe(
    "not provided; driveline advice assumes a propshaft to the rear axle",
  );
});

test("an engine order on the propshaft's rhythm without measured RPM names both", () => {
  const insights = drivelineInsights(
    "fault",
    {
      source: "engine",
      order_code: "E3",
      confidence_level: "moderate",
      alternative: { source: "driveline", order_code: "P2" },
      source_checks: [
        { source: "engine", status: "candidate", reason: null },
        {
          source: "driveline",
          status: "not_testable",
          reason: "same_rhythm_as_candidate",
        },
      ],
    },
    { drive_layout: "RWD", final_drive_axle: "rear", propshaft: true },
  );
  expect(insights.primary?.source).toBe("Engine or driveline");
  expect(insights.primary?.signature.startsWith("E3 / P2")).toBe(true);
  expect(JSON.stringify(insights.checks)).toContain(
    "without measured RPM, the engine's order turns at this rhythm in top gear",
  );
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

test("brake checks say when the drive did not brake and what came only while braking", () => {
  const noBraking = checkedInsights("no_fault", [
    { source: "wheel/tire", status: "ruled_out", reason: "no_matching_order" },
    { source: "brakes", status: "not_testable", reason: "no_braking" },
  ]);
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

test("the brake tips name the speed to brake from in the display unit", () => {
  const wheels = {
    source: "wheel/tire",
    status: "ruled_out",
    reason: "no_matching_order",
  } as const;
  const noBraking = checkedInsights(
    "no_fault",
    [
      wheels,
      { source: "brakes", status: "not_testable", reason: "no_braking" },
    ],
    "en",
    {},
    {},
    "mps",
  );
  expect(noBraking.checks.notChecked[0].detail).toContain(
    "brake firmly from about 28 m/s a few times",
  );
  // An EV may have stopped on regeneration alone: its brakes are checked only
  // with a hedge, and the tip asks for firm stops on the brake pedal.
  const ev = checkedInsights(
    "no_fault",
    [
      wheels,
      {
        source: "brakes",
        status: "ruled_out_estimated",
        reason: "regen_braking",
      },
    ],
    "nl",
    { fuel_type: "EV" },
    {},
    "mps",
  );
  expect(ev.checks.checked[1].detail).toContain(
    "doe de stap stevig afremmen van de begeleide test met regeneratie op het laagste niveau",
  );
  expect(ev.checks.checked[1].detail).toContain(
    "harder dan regeneratie alleen, vanaf ongeveer 28 m/s.",
  );
});

test("a no-fault run with only a faint residual rules it out as faint, not as a candidate", () => {
  const insights = checkedInsights("no_fault", [
    { source: "wheel/tire", status: "ruled_out", reason: "faint_only" },
    { source: "driveline", status: "ruled_out", reason: "no_matching_order" },
  ]);
  expect(insights.checks.checked[0]).toEqual({
    label: "Wheel / Tire",
    detail: "ruled out: found only faintly, at a level a healthy car also has",
  });
});

test("shows every History speed in the m/s setting", () => {
  const mps = { ...f, speedUnit: "mps" as const };
  const findings = moreFindings(
    historyListRun("run-007"),
    loaded(populatedInsights("run-007")),
    mps,
  );
  expect(findings.primary).toMatchObject({
    signature: "T1 · 12.1 Hz @ 24 m/s",
    speedBand: "18–29 m/s",
  });
  expect(
    [...findings.visibleSecondary, ...findings.hiddenSecondary].map(
      (finding) => finding.speedBand,
    ),
  ).toEqual(["17–22 m/s", "idle", "28–33 m/s"]);
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
  const value = (key: string) =>
    heatmap.zones.find((zone) => zone.key === key)?.valueLabel;
  expect(value("front_left_wheel")).toBe("7.5 dB");
  expect(value("rear_right_wheel")).toBe("report.missing");
  expect(value("engine_bay")).toBe("history.heatmap_no_sensor");
  expect(value("trunk")).toBe("history.heatmap_no_sensor");
});
