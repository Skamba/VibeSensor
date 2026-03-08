/**
 * TypeScript types matching the server's LiveWsPayload Pydantic model.
 *
 * These types are derived from the JSON Schema at
 * apps/ui/src/contracts/ws_payload_schema.json and must stay in sync.
 *
 * When the server bumps SCHEMA_VERSION, update EXPECTED_SCHEMA_VERSION
 * here and adjust the decoding logic in server_payload.ts.
 */

/** Current schema version the frontend expects. */
export const EXPECTED_SCHEMA_VERSION = "1";

export interface StrengthMetricPeak {
  hz: number;
  amp: number;
  vibration_strength_db: number;
  strength_bucket: string | null;
}

export interface StrengthMetricsPayload {
  combined_spectrum_amp_g: number[];
  vibration_strength_db: number;
  peak_amp_g: number;
  noise_floor_amp_g: number;
  strength_bucket: string | null;
  top_peaks: StrengthMetricPeak[];
}

export interface WsSpectrumSeries {
  x: number[];
  y: number[];
  z: number[];
  combined_spectrum_amp_g: number[];
  strength_metrics: StrengthMetricsPayload;
  /** Per-client freq axis; present only when axes differ across clients. */
  freq?: number[] | null;
}

export interface WsAlignmentInfo {
  overlap_ratio: number;
  aligned: boolean;
  shared_window_s: number;
  sensor_count: number;
  clock_synced: boolean;
}

export interface WsFrequencyWarning {
  code: string;
  message: string;
  client_ids: string[];
}

export interface WsSpectraPayload {
  /** Shared frequency axis (non-empty when all clients share the same axis). */
  freq: number[];
  clients: Record<string, WsSpectrumSeries>;
  alignment?: WsAlignmentInfo | null;
  warning?: WsFrequencyWarning | null;
}

export interface WsRotationalSpeedValue {
  rpm: number | null;
  mode: string | null;
  reason: string | null;
}

export interface WsOrderBand {
  key: string;
  center_hz: number;
  tolerance: number;
}

export interface WsRotationalSpeeds {
  basis_speed_source: string | null;
  wheel: WsRotationalSpeedValue;
  driveshaft: WsRotationalSpeedValue;
  engine: WsRotationalSpeedValue;
  order_bands: WsOrderBand[] | null;
}

export interface WsClientInfo {
  id: string;
  mac_address: string;
  name: string;
  connected: boolean;
  location: string;
  firmware_version: string;
  sample_rate_hz: number;
  frame_samples: number;
  last_seen_age_ms: number | null;
  data_addr: [string, number] | null;
  control_addr: [string, number] | null;
  frames_total: number;
  dropped_frames: number;
  duplicates_received: number;
  queue_overflow_drops: number;
  parse_errors: number;
  server_queue_drops: number;
  latest_metrics: unknown;
  last_ack_cmd_seq: number | null;
  last_ack_status: number | null;
  reset_count: number;
  last_reset_time: number | null;
  timing_health: {
    jitter_us_ema: number;
    drift_us_total: number;
  };
}

export interface WsMatrixCell {
  count: number;
  seconds: number;
  contributors: Record<string, number>;
}

export interface WsDiagnosticLevel {
  bucket_key?: string;
  strength_db?: number;
  sensor_label?: string;
  sensor_location?: string;
  class_key?: string;
  peak_hz?: number;
  confidence?: number;
  agreement_count?: number;
  sensor_count?: number;
}

export interface WsDiagnosticsLevels {
  by_source: Record<string, WsDiagnosticLevel>;
  by_sensor: Record<string, WsDiagnosticLevel>;
  by_location: Record<string, WsDiagnosticLevel>;
}

export interface WsDiagnosticEvent {
  event_id?: number;
  kind: string;
  class_key: string;
  severity_key?: string | null;
  sensor_id: string;
  sensor_label: string;
  sensor_labels: string[];
  sensor_count: number;
  peak_hz: number;
  peak_amp: number;
  peak_amp_g: number;
  vibration_strength_db: number;
}

export interface WsStrengthBand {
  key: string;
  min_db: number;
  max_db: number | null;
  labelKey: string;
}

export interface WsDiagnosticsPayload {
  diagnostics_sequence: number;
  matrix: Record<string, Record<string, WsMatrixCell>>;
  events: WsDiagnosticEvent[];
  strength_bands: WsStrengthBand[];
  levels: WsDiagnosticsLevels;
  findings: unknown[];
  top_finding: unknown | null;
  driving_phase: string;
  error: string | null;
}

export interface LiveWsPayload {
  schema_version: string;
  server_time: string;
  speed_mps: number | null;
  clients: WsClientInfo[];
  selected_client_id: string | null;
  rotational_speeds: WsRotationalSpeeds | null;
  spectra: WsSpectraPayload | null;
  diagnostics: WsDiagnosticsPayload;
}
