export const UPDATE_POLL_INTERVAL_IDLE_MS = 10_000;
export const UPDATE_POLL_INTERVAL_RUNNING_MS = 2_000;
export const ESP_FLASH_POLL_IDLE_MS = 4_000;
export const ESP_FLASH_POLL_ACTIVE_MS = 1_000;
export const GPS_POLL_FAST_MS = 2_000;
export const GPS_POLL_SLOW_MS = 10_000;

export const SPECTRUM_DB_MIN = 0;
export const SPECTRUM_DB_MAX = 100;
export const SPECTRUM_DB_REFERENCE_AMP_G = 1e-4;
export const SPECTRUM_MIN_RENDER_AMP_G = 1e-6;
export const SPECTRUM_TWEEN_DURATION_MS = 180;

export const HISTORY_HEATMAP_POSITIONS = [
  { key: "front-left wheel", area: "front-left" },
  { key: "front-right wheel", area: "front-right" },
  { key: "rear-left wheel", area: "rear-left" },
  { key: "rear-right wheel", area: "rear-right" },
  { key: "engine bay", area: "engine" },
  { key: "driveshaft tunnel", area: "driveshaft" },
  { key: "driver seat", area: "driver" },
  { key: "trunk", area: "trunk" },
] as const;
