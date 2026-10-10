import type { HistoryInsightsPayload } from "../src/api/types";

type HistoryFinding = HistoryInsightsPayload["findings"][number];
type LocationIntensityRow =
  HistoryInsightsPayload["sensor_intensity_by_location"][number];

function makeSpeedStats(): HistoryInsightsPayload["speed_stats"] {
  return {
    max_kmh: null,
    mean_kmh: null,
    min_kmh: null,
    range_kmh: null,
    sample_count: 0,
    stddev_kmh: null,
    steady_speed: false,
  };
}

export function makeHistoryFinding(
  overrides: Partial<HistoryFinding> = {},
): HistoryFinding {
  return {
    amplitude_metric: {
      name: "Vibration strength",
      units: "dB",
      value: null,
    },
    confidence: 0.92,
    confidence_level: "strong",
    evidence_summary: "Front-right wheel imbalance",
    finding_id: "finding-1",
    frequency_hz_or_order: 32,
    strongest_location: "Front Right Wheel",
    strongest_speed_band: "80-100 km/h",
    suspected_source: "wheel/tire",
    ...overrides,
  };
}

export function makeLocationIntensityRow(
  overrides: Partial<LocationIntensityRow> = {},
): LocationIntensityRow {
  return {
    dropped_frames_delta: 0,
    location: "Front Right Wheel",
    max_intensity_db: 32,
    mean_intensity_db: 16,
    p50_intensity_db: 8,
    p95_intensity_db: 30,
    partial_coverage: false,
    queue_overflow_drops_delta: 0,
    sample_count: 20,
    sample_coverage_ratio: 1,
    sample_coverage_warning: false,
    strength_bucket_distribution: {
      counts: {},
      percent_time_l0: 0,
      percent_time_l1: 0,
      percent_time_l2: 0,
      percent_time_l3: 0,
      percent_time_l4: 0,
      percent_time_l5: 0,
      total: 0,
    },
    ...overrides,
  };
}

export function makeDiagnosis(
  overrides: Partial<HistoryInsightsPayload["diagnosis"]> = {},
): HistoryInsightsPayload["diagnosis"] {
  return {
    verdict: "no_fault",
    confidence_level: null,
    finding_id: null,
    source: null,
    location: null,
    zone: null,
    order_code: null,
    frequency_hz: null,
    reference_speed_kmh: null,
    speed_min_kmh: null,
    speed_max_kmh: null,
    dominant_phase: null,
    presence_ratio: null,
    weak_reasons: [],
    guided_phases: [],
    speed_dependence: null,
    order_findings: [],
    amplitude_basis: "overall",
    location_amplitudes: [],
    unexplained_vibration: null,
    amplitude_vs_speed: [],
    spectrum: null,
    source_checks: [],
    conditions: {
      speed_source: null,
      rpm_source: "none",
      tire_circumference_m: null,
      final_drive_ratio: null,
      gear_ratio: null,
      tire_provenance: "missing",
      final_drive_provenance: "missing",
      gear_ratio_provenance: "missing",
      fuel_type: null,
    },
    ...overrides,
  };
}

/** A fault owner page as the server words it (vibesensor.report.view_model). */
export function makeOwnerPage(
  overrides: Partial<HistoryInsightsPayload["owner"]> = {},
): HistoryInsightsPayload["owner"] {
  return {
    verdict: "fault",
    result: "Front-left wheel",
    tone: "moderate",
    headline: "Likely cause: a wheel or tire problem at the front-left wheel",
    level: "moderate",
    confidence_label: "Confidence",
    level_word: "Moderate",
    level_meaning: "do the cheap confirming check first.",
    description: "A shake that repeats once per wheel turn.",
    candidate: null,
    reasons_title: null,
    reasons: [],
    covered_title: null,
    covered: null,
    not_covered_title: null,
    not_covered: [],
    felt_title: "What you feel",
    felt: "This cause explains most of what the test measured at the trunk, nearest where you sit.",
    next_step_title: "Next step",
    confirm_title: "Cheap check first",
    confirm: "Swap the front-left wheel to the other side and record again.",
    next_step: "Have the front-left wheel balanced.",
    fallback_step: "If that doesn't fix it: road-force all four wheels.",
    recapture_title: null,
    recapture: [],
    verify_title: "Check the fix",
    verify: "After the repair, record the same test again.",
    diagram: {
      zone: "front_left_wheel",
      front_label: "FRONT",
      markers: [
        {
          code: "front_left_wheel",
          label: "front-left wheel",
          value: "118 mg",
          ratio: 1,
          strongest: true,
        },
        {
          code: "trunk",
          label: "boot",
          value: "2.3 mg",
          ratio: 0.02,
          strongest: false,
        },
      ],
    },
    ...overrides,
  };
}

export function makeHistoryInsightsPayload(
  overrides: Partial<HistoryInsightsPayload> = {},
): HistoryInsightsPayload {
  return {
    accel_scale_g_per_lsb: null,
    data_quality: {
      accel_sanity: {
        saturation_count: null,
        sensor_limit: null,
        x_mean: null,
        x_variance: null,
        y_mean: null,
        y_variance: null,
        z_mean: null,
        z_variance: null,
      },
      outliers: {
        accel_magnitude: {
          count: 0,
          lower_bound: null,
          outlier_count: 0,
          outlier_pct: 0,
          upper_bound: null,
        },
        amplitude_metric: {
          count: 0,
          lower_bound: null,
          outlier_count: 0,
          outlier_pct: 0,
          upper_bound: null,
        },
      },
      required_missing_pct: {
        accel_x: 0,
        accel_y: 0,
        accel_z: 0,
        speed_kmh: 0,
        t_s: 0,
      },
      speed_coverage: {
        count_non_null: 0,
        max_kmh: null,
        mean_kmh: null,
        min_kmh: null,
        non_null_pct: 0,
        stddev_kmh: null,
      },
    },
    diagnosis: makeDiagnosis(),
    duration_s: 12,
    feature_interval_s: null,
    file_name: "run.csv",
    findings: [],
    incomplete_for_order_analysis: false,
    lang: "en",
    metadata: {},
    most_likely_origin: {},
    owner: makeOwnerPage(),
    phase_info: {
      cruise_pct: 0,
      has_acceleration: false,
      has_cruise: false,
      idle_pct: 0,
      phase_counts: {},
      phase_pcts: {},
      segment_count: 0,
      speed_unknown_pct: 0,
      total_samples: 0,
    },
    phase_segments: [],
    phase_speed_breakdown: [],
    phase_timeline: [],
    raw_sample_rate_hz: null,
    record_length: "12.0 s",
    rows: 0,
    run_id: "run-001",
    run_noise_baseline_db: null,
    run_suitability: [],
    sensor_count_used: 0,
    sensor_intensity_by_location: [],
    sensor_locations: [],
    sensor_locations_connected_throughout: [],
    speed_breakdown: [],
    speed_breakdown_skipped_reason: null,
    speed_stats: makeSpeedStats(),
    speed_stats_by_phase: {},
    start_time_utc: "2026-01-01T00:00:00Z",
    status: "complete",
    top_causes: [],
    warnings: [],
    ...overrides,
  };
}
