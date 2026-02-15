export const palette = ["#e63946", "#2a9d8f", "#3a86ff", "#f4a261", "#7b2cbf", "#1d3557", "#ff006e"];

export const defaultLocationCodes = [
  "front_left_wheel",
  "front_right_wheel",
  "rear_left_wheel",
  "rear_right_wheel",
  "transmission",
  "driveshaft_tunnel",
  "engine_bay",
  "front_subframe",
  "rear_subframe",
  "driver_seat",
  "front_passenger_seat",
  "rear_left_seat",
  "rear_center_seat",
  "rear_right_seat",
  "trunk",
];

export const bandToleranceModelVersion = 2;

export const treadWearModel = {
  // 10/32 in (~7.9 mm) new to 2/32 in (~1.6 mm) legal minimum.
  new_tread_mm: 7.9,
  worn_tread_mm: 1.6,
  safety_margin_pct: 0.3,
};

export const sourceColumns = [
  { key: "engine", labelKey: "matrix.source.engine" },
  { key: "driveshaft", labelKey: "matrix.source.driveshaft" },
  { key: "wheel", labelKey: "matrix.source.wheel" },
  { key: "other", labelKey: "matrix.source.other" },
];

export const severityBands = [
  { key: "l5", labelKey: "matrix.severity.l5", minDb: 40, maxDb: Number.POSITIVE_INFINITY },
  { key: "l4", labelKey: "matrix.severity.l4", minDb: 34, maxDb: 40 },
  { key: "l3", labelKey: "matrix.severity.l3", minDb: 28, maxDb: 34 },
  { key: "l2", labelKey: "matrix.severity.l2", minDb: 22, maxDb: 28 },
  { key: "l1", labelKey: "matrix.severity.l1", minDb: 16, maxDb: 22 },
];

export const multiSyncWindowMs = 500;
export const multiFreqBinHz = 1.5;
