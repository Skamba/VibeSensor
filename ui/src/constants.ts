import { chartSeriesPalette } from "./theme";

export const palette = chartSeriesPalette;

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
] as const;

export const bandToleranceModelVersion = 2;

export const treadWearModel = {
  // 10/32 in (~7.9 mm) new to 2/32 in (~1.6 mm) legal minimum.
  new_tread_mm: 7.9,
  worn_tread_mm: 1.6,
  safety_margin_pct: 0.3,
} as const;

export const sourceColumns = [
  { key: "engine", labelKey: "matrix.source.engine" },
  { key: "driveshaft", labelKey: "matrix.source.driveshaft" },
  { key: "wheel", labelKey: "matrix.source.wheel" },
  { key: "other", labelKey: "matrix.source.other" },
] as const;

export const severityBands = [
  { key: "l5", labelKey: "matrix.severity.l5", minDb: 34, maxDb: Number.POSITIVE_INFINITY, minAmp: 0.048 },
  { key: "l4", labelKey: "matrix.severity.l4", minDb: 28, maxDb: 34, minAmp: 0.024 },
  { key: "l3", labelKey: "matrix.severity.l3", minDb: 22, maxDb: 28, minAmp: 0.012 },
  { key: "l2", labelKey: "matrix.severity.l2", minDb: 16, maxDb: 22, minAmp: 0.006 },
  { key: "l1", labelKey: "matrix.severity.l1", minDb: 10, maxDb: 16, minAmp: 0.003 },
] as const;

export const multiSyncWindowMs = 500;
export const multiFreqBinHz = 1.5;
