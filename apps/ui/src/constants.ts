// Generated from backend-owned shared constants
// Do not edit manually; run make sync-contracts

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
  "trunk"
] as const;

export const defaultAnalysisSettings = {
  "speed_uncertainty_pct": 1.0,
  "tire_diameter_uncertainty_pct": 1.0,
  "final_drive_uncertainty_pct": 0.1,
  "gear_uncertainty_pct": 0.2,
  "tire_deflection_factor": 0.97
} as const;

export const defaultLiveAnalysisConfig = {
  "sampleRateHz": 800,
  "fftWindowSizeSamples": 2048,
  "spectrumMinHz": 5.0,
  "spectrumMaxHz": 200.0,
  "peakBandwidthHz": 1.2,
  "peakSeparationHz": 1.2,
  "strengthAlgorithmVersion": "strength-db-scalar-v1",
  "peakDetectorVersion": "peak-band-rms-v1",
  "calibrationProfileId": "noise-floor-p20-v1"
} as const;
