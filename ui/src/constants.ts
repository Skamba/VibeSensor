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

export const sourceColumns = [
  { key: "engine", labelKey: "matrix.source.engine" },
  { key: "driveshaft", labelKey: "matrix.source.driveshaft" },
  { key: "wheel", labelKey: "matrix.source.wheel" },
  { key: "other", labelKey: "matrix.source.other" },
] as const;

export const multiSyncWindowMs = 500;
export const multiFreqBinHz = 1.5;
