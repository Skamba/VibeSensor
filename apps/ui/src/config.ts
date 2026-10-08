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
 * The brake step's firm stops, at speeds an ordinary road allows. The braking
 * rule smears a stop's ends over its +-2.5 s slope window, so a stop counts only
 * when it sheds about 50 km/h at 0.2 g (45 from 0.22 g); from 80 to 20 km/h
 * sheds 60, so a driver who starts at 75 or stops at 25 still counts. It lasts
 * 5-8.5 s at 0.2-0.35 g, and three stops give the brake check ample braking
 * spectra (docs/analysis_pipeline.md).
 */
export const GUIDED_BRAKE_FROM_KMH = 80;
export const GUIDED_BRAKE_TO_KMH = 20;
export const GUIDED_BRAKE_STOPS = 3;
/**
 * The warm-up the guided test asks for before step 1, off the recording.
 * Tires flat-spotted by parking shake at the wheel orders and fade over the
 * first ~20 km (docs/simulator_realism.md "Parking flat spots"); below about
 * 38 km/h that comb can pass for an engine or driveline order
 * (docs/metrics.md).
 */
export const GUIDED_WARM_UP_KM = 20;
export const GUIDED_WARM_UP_MINUTES = 15;
export const GUIDED_WARM_UP_ABOVE_KMH = 40;

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
