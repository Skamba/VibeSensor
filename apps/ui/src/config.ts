export const UPDATE_POLL_INTERVAL_IDLE_MS = 10_000;
export const UPDATE_POLL_INTERVAL_RUNNING_MS = 2_000;
export const ESP_FLASH_POLL_IDLE_MS = 4_000;
export const ESP_FLASH_POLL_ACTIVE_MS = 1_000;
export const GPS_POLL_FAST_MS = 2_000;
export const GPS_POLL_SLOW_MS = 10_000;

/** Speeds the guided test drive names (km/h); shown in the driver's speed unit. */
export const GUIDED_SWEEP_FROM_KMH = 50;
export const GUIDED_SWEEP_TO_KMH = 120;
export const GUIDED_COAST_DROP_KMH = 30;
/**
 * The brake step's firm stops: from 100 to 40 km/h at a brisk 0.25-0.4 g lasts
 * 4-7 s, well over the 2.5 s at 0.2 g the analysis needs to call it braking,
 * and three stops give it ample braking spectra (docs/analysis_pipeline.md).
 */
export const GUIDED_BRAKE_FROM_KMH = 100;
export const GUIDED_BRAKE_TO_KMH = 40;
export const GUIDED_BRAKE_STOPS = 3;

export const SPECTRUM_DB_MIN = 0;
export const SPECTRUM_DB_MAX = 100;
export const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
export const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;
export const SPECTRUM_TWEEN_DURATION_MS = 180;

export const HISTORY_HEATMAP_POSITIONS = [
  { key: "front_left_wheel", area: "front-left" },
  { key: "front_right_wheel", area: "front-right" },
  { key: "rear_left_wheel", area: "rear-left" },
  { key: "rear_right_wheel", area: "rear-right" },
  { key: "engine_bay", area: "engine" },
  { key: "driveshaft_tunnel", area: "driveshaft" },
  { key: "driver_seat", area: "driver" },
  { key: "trunk", area: "trunk" },
] as const;
